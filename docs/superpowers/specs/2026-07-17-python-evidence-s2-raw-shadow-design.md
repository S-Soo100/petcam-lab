# Python Evidence S2 — Raw Temporal Evidence Shadow 설계

> **상태:** ⛔ SUPERSEDED — 실행 금지
> **대체 정본:** [`2026-07-17-python-evidence-universal-worker-design.md`](2026-07-17-python-evidence-universal-worker-design.md)
> **선행 게이트:** `S1R2_PASS_CROI_THROUGHPUT` (`96/96`, p95 `2.5501s`, `1,411.69 clips/h`)
> **과거 결정:** 기존 Mac mini `activity-worker` 확장. “모든 영상 공통 전처리” 제품 원칙 확정으로 폐기했다.
> **비결정:** production selector, VLM 호출량, 자동 제외, 행동 분류, 앱 수치에는 아직 사용하지 않는다.

## 1. 목표

모든 **activity-worker 대상 카메라의 신규 motion clip**에 대해 VLM보다 먼저 다음 raw evidence를 축적한다.

- 게코 bbox를 사용한 dense ROI motion 시계열
- 같은 프레임의 global background motion 시계열
- bbox 중심의 공간 체류량(고정 4×4 grid)
- 의미 없는 반복성 수치와 motion excursion 구간
- 정확한 provenance와 처리 상태

이 단계의 성공은 “행동을 맞혔다”가 아니다. 다음 S3에서 현행 selector와 evidence-augmented selector를 같은 예산으로 비교할 수 있는 **입력 데이터가 안정적으로 쌓인다**는 뜻이다.

## 2. 사용자에게 달라지는 것

아무것도 달라지지 않는다.

- 앱 활동시간: 불변
- GT/라벨링 큐: 불변
- 정규 VLM 4개/window와 rolling backfill: 불변
- Slack 사용자 메시지: 불변
- `exclude_absent`, `exclude_static`: 불변

운영자에게만 evidence coverage와 worker summary가 추가된다.

## 3. 채택한 구조

```text
motion_clips
    │
    ▼
Mac mini activity-worker (기존 단일 host/단일 lock)
    ├─ sparse 12f + RF-DETR ──> clip_prelabels
    ├─ four-state policy ─────> clip_activity_assessments
    └─ same local mp4 + bbox
         └─ sequential OpenCV dense ROI/global scan
              └─ clip_python_evidence_runs (append-only shadow)
```

### 왜 기존 activity-worker 확장인가

1. 이미 Mac mini 단일 host guard, flock, R2 임시파일 정리, detector 1회 로드가 검증됐다.
2. 신규 독립 워커는 같은 clip을 다시 다운로드하고 detector를 다시 띄울 가능성이 크다.
3. 신규 clip은 Gate 처리와 dense scan이 같은 로컬 mp4를 공유할 수 있다.
4. 기존 prelabel이 있는 clip은 detector를 다시 호출하지 않고 bbox만 재사용해 dense scan을 self-heal할 수 있다.

### 채택하지 않은 구조

- `router-features` worker 확장: `camera_clips` 기반 legacy feature-store라 `motion_clips` 기반 activity evidence와 identity가 다르다.
- 신규 `python-evidence-worker`: 스케줄·lock·R2 다운로드·운영 책임이 하나 더 생긴다.
- `clip_prelabels.motion_metrics` 덮어쓰기: provenance가 다른 시간축 evidence가 기존 evidence를 변형한다.

## 4. Evidence 계약

### 4.1 버전

- `evidence_schema_version = python-evidence-raw-v1`
- `algorithm_version = croi-temporal-v1`
- Gate source identity는 기존 7컬럼(`clip_id`, `model_version`, `schema_version`, `checkpoint_sha256`, `threshold`, `sampler_version`, `frames_sampled`)을 보존한다.

### 4.2 상태

`status`는 다음 값만 허용한다.

- `ok`: bbox와 2개 이상 decodable frame으로 series 생성
- `no_bbox`: 현재 Gate evidence에 gecko bbox가 없음. full-frame을 ROI로 대체하지 않는다.
- `invalid_bbox`: bbox를 프레임에 clamp한 뒤 유효 면적이 없음
- `insufficient_decodable_frames`: 순차 decode가 2프레임 미만

R2/DB/OpenCV 예외는 완료 row로 숨기지 않는다. row를 남기지 않고 cycle을 nonzero로 끝내 다음 실행이 재시도한다. 로그에는 예외 타입과 allowlist reason만 남기고 URL·원문 DB 메시지를 남기지 않는다.

### 4.3 raw payload

한 row는 다음 필드를 가진다.

- `roi_bbox`: sparse Gate gecko bbox들의 union `[x,y,w,h]`
- `decoded_frame_count`, `stored_point_count`, `point_cap`, `point_stride`
- `observed_start_sec`, `observed_end_sec`
- `roi_motion_series`: 최대 256개의 `{t_sec, value}`
- `global_motion_series`: ROI series와 같은 timestamp의 최대 256개 `{t_sec, value}`
- `motion_summary`: roi/global/difference의 count·mean·std·p50·p95·max
- `spatial_dwell`: 고정 4×4 grid의 관찰 체류 초, `observed_dwell_sec`, `unobserved_sec`
- `periodicity_summary`: difference series의 autocorrelation peak와 dominant period(계산 가능할 때만)
- `motion_excursions`: raw difference series에서 나온 `{start_sec,end_sec,peak}`

모든 숫자는 finite여야 하고 음수가 될 수 없는 필드는 DB와 Python 양쪽에서 거부한다.

### 4.4 bounded-memory 규칙

- 영상을 한 프레임씩 순차 decode한다. 전체 frame array를 메모리에 쌓지 않는다.
- 저장 point는 최대 256개다.
- frame count metadata가 유효하면 `ceil(frame_count / 256)` stride를 쓴다.
- metadata가 없거나 틀리면 point 수가 cap의 2배를 넘을 때 인접 쌍을 시간 가중 평균으로 합쳐 bounded하게 유지한다.
- 원본 mp4와 추출 frame은 DB/R2에 새로 쓰지 않는다. clip 처리 뒤 로컬 temp는 0이어야 한다.

### 4.5 의미 중립 계산

- ROI motion = 연속 grayscale ROI의 mean absolute difference
- global motion = 같은 연속 frame의 축소 grayscale mean absolute difference
- local difference = `max(0, roi_motion - global_motion)`
- motion excursion은 clip 내부 `median + 3*MAD`를 넘는 연속 구간이다. 계산 threshold 값을 row에 함께 저장한다.
- periodicity는 local difference의 정규화 autocorrelation 숫자만 저장한다.
- spatial dwell은 bbox center를 4×4 normalized grid에 투영한다. 관찰 간격이 sparse sampler 예상 간격의 2배를 넘으면 초과분을 `unobserved_sec`로 돌린다.

이 값들은 행동·케어 의미를 갖지 않는다. threshold는 shadow 숫자 변환의 provenance일 뿐 production 정책 threshold가 아니다.

## 5. 명시적 금지

S2에서 다음 필드와 동작을 만들지 않는다.

- `drinking_candidate`, `sustained_lapping_candidate`, `basking_candidate`
- bbox 방향으로 head ROI 추측
- `include/exclude`, `highlight`, `recommended_vlm_mode`
- selector score 변경 또는 VLM 후보 교체
- GT/behavior label 생성·수정
- 앱/리포트의 활동시간 변경
- `clip_prelabels` 또는 과거 evidence row UPDATE/DELETE

## 6. DB 계약

신규 테이블 `clip_python_evidence_runs`는 service-role 전용 append-only audit table이다.

- `clip_id → motion_clips(id) ON DELETE CASCADE`
- `prelabel_id → clip_prelabels(id) ON DELETE RESTRICT`
- identity unique: `(clip_id, prelabel_id, evidence_schema_version, algorithm_version)`
- RLS enabled, client policy 0, anon/authenticated 권한 0
- UPDATE/DELETE/TRUNCATE를 trigger로 role 무관 차단
- insert는 `fn_insert_python_evidence_run` RPC 한 경로로만 수행
- RPC는 `SECURITY INVOKER`, `search_path=''`, service_role only
- JSON type·series cap·finite/nonnegative scalar를 DB CHECK/RPC에서 재검증
- conflict는 기존 row를 반환하고 새 row를 변형하지 않는다

## 7. Worker self-healing

`PYTHON_EVIDENCE_SHADOW_ENABLED=false`가 기본이다. false면 현재 worker 경로와 DB query가 완전히 동일해야 한다.

true일 때 indexer는 현재 시간창에서 다음 중 하나인 clip을 선택한다.

1. 현재 activity policy assessment가 없음
2. 현재 Gate identity의 prelabel은 있지만 대응 S2 evidence row가 없음

처리 규칙:

- 신규 clip: 다운로드 1회 → Gate/assessment 저장 → 같은 파일로 temporal evidence 저장
- 기존 prelabel·assessment clip: detector 0회 → 다운로드 1회 → temporal evidence만 저장
- assessment만 실패한 clip: 기존 prelabel 재사용 → assessment self-heal → 필요하면 temporal evidence
- temporal 저장만 실패: 기존 Gate/assessment를 보존하고 다음 cycle에서 temporal evidence만 재시도

`PYTHON_EVIDENCE_BATCH_LIMIT`은 기존 activity batch limit 이하로 clamp한다.

## 8. 테스트·검증 계약

### Python/Gate

- bbox 없음, invalid bbox, 0/1/2 frame
- frame shape 변화와 bbox clamp
- point cap 256, dynamic compression, finite 숫자
- ROI/global/local difference
- dwell grid와 unobserved time
- periodicity 최소 표본·constant series
- excursion rule과 threshold provenance
- VideoCapture release on success/failure

### Nightly

- shadow false면 신규 table query/download 0
- 신규 clip은 download 1회·detector 기존 1회
- prelabel 재사용 path는 detector 0회
- row conflict 멱등, temporal-only self-heal
- clip failure 격리 + cycle nonzero
- host/policy guard가 DB/R2보다 먼저
- temp 0

### DB

- client read/write 0, service role RPC only
- JSON shape/cap/identity constraint
- duplicate insert returns existing row
- UPDATE/DELETE/TRUNCATE 전부 차단
- rollback probe 후 잔류 0

## 9. 구현 및 배포 경계

이번 handoff는 **구현·테스트·feature branch push까지만** 한다.

하지 않는 것:

- migration production apply
- 세 레포 main merge
- Mac mini pull/restart/LaunchAgent env 변경
- production canary 또는 historical backfill

구현 보고를 Codex가 검수한 뒤 별도 S2B 배포 계획으로 migration → 5 clip canary → 자연 hourly cycle 순서로 진행한다.

## 10. S2 구현 완료 조건

- Gate/nightly/lab 전체 테스트 통과
- 신규 migration static/transaction probe 통과(미적용)
- shadow=false 완전 하위호환 증거
- selector/VLM/app/GT 변경 0 정적 감사
- feature branches push, main merge 0
- 구현 보고서에 변경 파일·테스트·잔여 위험·S2B 배포 전제 기록

S2 구현 완료는 S3 채택 승인이 아니다. 최소 3 camera-night shadow 축적과 사람 blind 비교 전에는 evidence를 후보 선택에 사용하지 않는다.

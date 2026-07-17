# Python Evidence Universal Worker 설계

> **상태:** 사용자 승인 / 구현 전
> **제품 원칙:** 모든 `motion_clips` 영상은 Python Evidence 단계를 반드시 거친다.
> **선행 게이트:** `S1R2_PASS_CROI_THROUGHPUT` — 96/96, p95 2.5501s, 1,411.69 clips/h
> **결정:** activity filter의 부가기능이 아니라 전 제품 공통 전처리 계층으로 독립시킨다.

## 1. 목표와 성공의 의미

신규·과거를 포함한 모든 운영 `motion_clips`에 durable evidence job을 만들고, Mac mini가 로컬 Python/OpenCV/Gate로 처리한다.

이 단계는 세 가지 목적을 동시에 가진다.

1. VLM이 볼 영상 수·프레임 수·영역을 줄일 근거를 축적한다.
2. VLM이 전체 화면에서 놓치는 게코·미세 움직임을 bbox/시간축 근거로 보조한다.
3. 향후 local model·Gate v3·사람 GT가 같은 evidence contract를 재사용하게 한다.

Python을 거친 것만으로 토큰이 자동 절감되는 것은 아니다. 실제 절감은 S3 이후 다음 레버를 켤 때 발생한다.

- VLM 호출 clip 수 감소
- 전송 frame 수 감소
- 전체 frame 대신 ROI 전달
- 쉬운 activity 집계는 Python만 사용
- 불확실·고가치 clip에 더 강한 VLM 집중

## 2. 전 영상 적용의 정확한 정의

“전 영상 적용”은 모든 영상에 같은 고비용 연산을 수행한다는 뜻이 아니다.

### Level 0 — 모든 영상 필수

- durable queue 등록
- R2 다운로드·decode health
- duration/fps/frame count/해상도
- global grayscale motion time series와 품질 수치
- sparse 12-frame Gate presence/bbox/provenance
- 결과 또는 allowlist terminal reason 저장

### Level 1 — bbox가 있는 영상

- union bbox 내부 dense ROI motion series
- global motion과의 차이
- 4×4 normalized spatial dwell
- numeric periodicity와 raw motion excursion 구간

### Level 2 — S3 이후, 아직 금지

- evidence로 VLM 후보·프레임·ROI 구성
- 호출 생략 또는 model routing
- 사람 blind GT 기반 selector 비교

`no_bbox`도 정상적인 Level 0 완료다. full frame을 gecko ROI로 가장하지 않는다. Gate의 false negative 가능성 때문에 `no_bbox`를 영상 폐기나 VLM skip으로 사용하지 않는다.

## 3. 최종 구조

```text
motion_clips INSERT
    └─ DB trigger → python_evidence_jobs (queued, one per clip)
                         │
                         ▼
              Mac mini python-evidence-worker
              ├─ current jobs first
              ├─ prelabel 있으면 detector 재사용(0회)
              ├─ 없으면 sparse Gate 1회
              ├─ Level 0 all clips
              ├─ Level 1 bbox clips only
              └─ append-only clip_python_evidence_runs
                         │
             ┌───────────┴────────────┐
             ▼                        ▼
      activity-worker             VLM selector
      (evidence consumer)         (S2는 기존 로직 유지)
```

## 4. 왜 독립 워커인가

기존 `activity-worker`는 카메라별 activity filter 설정과 policy version에 종속된다. 이 범위에 evidence를 넣으면 다음 문제가 남는다.

- 설정이 없는 카메라는 영구 누락
- 활동시간 정책 변경이 evidence coverage에 영향
- 활동 판정 실패와 전처리 실패가 한 상태로 섞임
- 향후 VLM·학습·앱이 activity worker 내부 계약에 결합

독립 worker는 “모든 영상에 evidence가 존재한다”를 자기 책임으로 갖는다. 대신 계산 코어와 저장 함수는 Gate/nightly 기존 모듈을 재사용해 중복 구현을 막는다.

## 5. Durable queue 계약

### 5.1 `python_evidence_jobs`

- `clip_id` FK → `motion_clips(id) ON DELETE CASCADE`
- `evidence_schema_version`, `algorithm_version`; unique `(clip_id, evidence_schema_version, algorithm_version)`
- `source`: `live` 또는 `historical`
- `status`: `queued`, `processing`, `succeeded`, `failed_retryable`, `failed_terminal`
- `priority`: live가 historical보다 높음
- `attempt_count`, `next_attempt_at`, `claimed_at`, `claimed_by`
- allowlist `failure_code`; raw exception/URL/secret 저장 금지
- `created_at`, `updated_at`, `completed_at`

`motion_clips AFTER INSERT` trigger가 현재 active version의 live job을 원자 생성한다. future algorithm/Gate profile 변경은 기존 row를 덮지 않고 forward migration으로 trigger version을 올리고 새 version job을 enqueue한다. migration은 기존 clip을 한꺼번에 enqueue하지 않는다. 역사 영상은 별도 bounded enqueuer가 날짜 단위·batch 단위로 추가한다.

### 5.2 claim/complete/fail RPC

- `fn_claim_python_evidence_jobs(limit, worker_host, now)`
- `fn_complete_python_evidence_job(job_id, run_id, worker_host)`
- `fn_fail_python_evidence_job(job_id, failure_code, retryable, worker_host, now)`
- claim은 `FOR UPDATE SKIP LOCKED`, live 우선·created_at 안정정렬
- lease 만료 processing은 retryable로 회수
- 최대 attempt 후 allowlist terminal 전환
- RPC는 service_role only, `SECURITY INVOKER`, `search_path=''`

## 6. Append-only evidence 계약

`clip_python_evidence_runs`는 결과 원장이다.

- `clip_id`, `job_id`, nullable `prelabel_id`
- `evidence_schema_version=python-evidence-raw-v1`
- `algorithm_version=croi-temporal-v1`
- Gate 7-column provenance + producer host/run/code ref
- `level0_status`, `level1_status`
- bounded JSON payload: metadata/global series/ROI series/dwell/periodicity/excursions
- `source_prelabel_identity`는 Gate 7-column identity의 canonical JSON SHA-256이며 prelabel이 없으면 literal `none`; 항상 non-null
- unique `(clip_id, evidence_schema_version, algorithm_version, source_prelabel_identity)`
- RLS enabled, client policy 0, service_role only
- UPDATE/DELETE/TRUNCATE role 무관 trigger 차단
- JSON type, point cap 256, finite/nonnegative scalar를 Python과 DB 양쪽에서 검증

동일 identity 재실행은 기존 run을 반환하고 변경하지 않는다.

## 7. Adaptive raw evidence 계약

### 7.1 Level 0

- sequential decode; 전체 frame array 보유 금지
- global frame은 분석용 축소 grayscale로만 유지
- 저장 point 최대 256
- `decode_status`: `ok`, `no_decodable_frames`, `insufficient_decodable_frames`, `invalid_metadata`
- sparse Gate가 이미 있으면 재사용; 없으면 동일 local mp4에서 12-frame sampling + detector 1회
- 최소 프레임 미달은 Gate prelabel을 저장하지 않되 decode evidence와 terminal reason은 남긴다

### 7.2 Level 1

- sparse detected gecko bbox들의 union을 ROI로 사용
- ROI와 global의 연속 grayscale MAD를 같은 timestamp로 저장
- local difference = `max(0, roi-global)`
- point cap 256, sequential decode, VideoCapture always release
- 4×4 dwell은 sparse bbox center의 관찰 시간만 배분하고 긴 미관찰 간격은 `unobserved_sec`
- periodicity와 excursion은 숫자 변환이며 행동명이 아니다

## 8. 의미·제품 경계

S2에서 절대 만들거나 바꾸지 않는다.

- `drinking/basking/playing/sustained_lapping` 판정
- head ROI 추측
- VLM selector score, 4슬롯 예산, batch size, model
- `include/exclude`, highlight, activity time
- behavior label, GT, labeling queue
- Flutter/API 사용자 응답

모든 영상이 queue에 들어가는 것은 의무지만 downstream을 hard-block하지는 않는다. S2 shadow 기간에는 evidence 지연/실패가 캡처·앱·정규 VLM을 중단시키지 않는다. 대신 coverage/lag/error를 운영 지표로 보고 반드시 재처리한다.

## 9. 기존 worker와 공존·전환

### S2A — 이번 구현

- universal worker와 durable queue 구현
- 기존 activity-worker는 그대로
- existing prelabel을 우선 재사용
- 공통 Gate lock으로 detector 동시 실행 방지
- production 미배포

### S2B — 별도 승인 후

- migration apply
- 5-clip foreground canary
- LaunchAgent shadow 가동
- 신규 job coverage 100%, temp 0, lag/exit 확인

### S2C — coverage 검증 후

- activity-worker가 evidence/prelabel consumer가 되게 전환
- activity-worker의 직접 R2/detector fallback은 일정 기간 보존
- fallback 제거는 별도 승인

## 10. 역사 영상

- `enqueue_python_evidence_backfill.py`는 날짜 범위와 `--limit` 필수
- live queue 우선, historical은 남는 capacity만
- migration에서 전량 insert 금지
- 같은 clip 중복 job 0
- stop/resume 가능하고 날짜별 progress 감사 가능
- 이번 구현에서는 script와 테스트만 만들고 실제 enqueue하지 않는다

## 11. 운영 안전

- runtime host: Mac mini만, expected-host fail-closed
- 공통 Gate/processor lock을 DB/R2/model load 전에 획득
- clip별 오류 격리, cycle에 실패가 있으면 nonzero
- temp media 0
- no backlog면 detector/R2/Slack 0
- secret·full path·DB 원문 오류 비노출
- current-first, historical starvation/역starvation 둘 다 테스트
- 기본 feature flag false; migration 없는 상태에서 신규 table query 0

## 12. 성공 조건

구현 완료:

- 세 레포 feature branch 테스트·push 완료
- migration 미적용, main merge 0, Mac mini 변경 0
- durable queue/append-only/raw evidence/adaptive depth 테스트 통과
- selector/VLM/app/GT write 0 정적 감사

배포 후 별도 성공 조건:

- activation 이후 신규 `motion_clips → jobs` coverage 100%
- live job lag p95 15분 이내
- canary 및 자연 cycle failure 0, temp 0
- 모든 completed job에 provenance 완전
- activity/VLM 사용자 결과 불변

S3는 최소 3 camera-night와 사람 blind union ≥60 전에는 시작하지 않는다.

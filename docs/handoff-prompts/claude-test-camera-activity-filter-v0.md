# Claude 작업 지시문 — 테스트 카메라 활동시간 필터 v0

> 이 문서 전체를 Claude Code에 그대로 전달해.

## 역할

너는 `petcam-lab`, `gecko-vision-gate`, `petcam-nightly-reporter`, `tera-ai-flutter`를 함께 다루는 구현 담당자야. 목표는 Claude/VLM 없이 Mac mini에서 모든 테스트 카메라 영상을 자동 분석해, 명확한 비활동 클립의 전체 길이를 앱 활동시간에서 제외하는 v0를 만드는 거야.

이번 작업은 고객용 정식 기능이 아니라 **현재 테스트 카메라만 대상으로 하는 실험 기능**이야. 안전성보다 실험 속도를 높이되, 고객 카메라로 자동 확장되지 않고 즉시 되돌릴 수 있어야 해.

## 작업 시작 규칙

1. 각 레포의 `AGENTS.md`, `CLAUDE.md`, 관련 SOT를 먼저 읽어.
2. 모든 레포에서 `git status --short`, 현재 branch, 최근 commit을 확인해.
3. 다른 세션 변경과 untracked 파일을 보존해. 특히 `petcam-nightly-reporter/storage/`는 사용자 데이터이므로 수정·삭제·stage하지 마.
4. `pip`를 사용하지 말고 각 Python 레포의 `uv` 규칙을 따라.
5. 비밀값, 카메라 UUID, owner UUID, R2 key를 문서·테스트 fixture·commit에 넣지 마.
6. 기억으로 경로·스키마·API를 단정하지 말고 코드와 운영 DB를 읽기 전용으로 확인해.
7. 파괴적 git, force push, 운영 데이터 삭제는 금지해.
8. 프로덕션 마이그레이션 적용, 테스트 카메라 활성화, 앱 배포는 각각 사용자 승인을 받은 뒤에만 실행해.

## 먼저 읽을 자료

### Gate

- `/Users/baek/myPythonProjects/gecko-vision-gate/AGENTS.md`
- `/Users/baek/myPythonProjects/gecko-vision-gate/CLAUDE.md`
- `/Users/baek/myPythonProjects/gecko-vision-gate/specs/architecture.md`
- `/Users/baek/myPythonProjects/gecko-vision-gate/specs/gate-v3.md`
- `/Users/baek/myPythonProjects/gecko-vision-gate/reports/R0002-evening-recall-v2.md`
- `/Users/baek/myPythonProjects/gecko-vision-gate/src/gecko_vision_gate/prelabel.py`
- `/Users/baek/myPythonProjects/gecko-vision-gate/src/gecko_vision_gate/schema.py`

### Mac mini reporter

- `/Users/baek/petcam-nightly-reporter/specs/architecture.md`
- `/Users/baek/petcam-nightly-reporter/reporter/indexer.py`
- `/Users/baek/petcam-nightly-reporter/reporter/r2.py`
- `/Users/baek/petcam-nightly-reporter/reporter/config.py`
- `/Users/baek/petcam-nightly-reporter/reporter/worker.py`
- `/Users/baek/petcam-nightly-reporter/install-launchd.sh`

### Flutter

- `/Users/baek/myProjects/tera-ai-flutter/lib/features/my_cage/data/motion_clip_repository.dart`
- `/Users/baek/myProjects/tera-ai-flutter/lib/features/my_cage/presentation/my_cage_providers.dart`
- `/Users/baek/myProjects/tera-ai-flutter/lib/features/my_cage/domain/nightly_report.dart`

### SOT와 마이그레이션 패턴

- `/Users/baek/petcam-lab/AGENTS.md`
- `/Users/baek/petcam-lab/specs/next-session.md`
- `/Users/baek/petcam-lab/docs/handoff-prompts/camera-firmware-clip-contract.md`
- `/Users/baek/petcam-lab/migrations/`
- `/Users/baek/tera-ai-product-master/docs/specs/petcam-ai-pipeline.md`

## 2026-07-14 기준 확인된 사실

다음은 시작점일 뿐이야. 구현 전 다시 확인해.

- Flutter의 `motionSeconds`와 `motionSecondsByHour`는 `motion_clips.duration_sec`를 전부 더한다.
- Nightly의 `summarize_activity`도 모든 클립의 `duration_sec`를 더한다.
- 운영 영상 원본 테이블은 레거시 `camera_clips`가 아니라 `motion_clips`다.
- `motion_clips`에는 `id`, `camera_id`, `owner_id`, `enclosure_id`, `started_at`, `duration_sec`, `r2_key`, `motion_score` 등이 있다.
- 운영 DB에는 카메라가 3대 있으나 전부 자동 활성화하면 안 된다.
- `clip_prelabels`, `clip_activity_assessments`는 아직 없거나 접근 불가 상태다.
- Gate v2 권장 artifact는 `runs/gecko_v2/checkpoint_best_ema.pth`다.
- Gate v2 자체 test에서 threshold 0.25의 clip recall은 97.8%였지만, 같은 카메라·사육장 중심이고 독립 future holdout 검증은 아니다.
- 로컬 참고 실측에서 31초 영상 12프레임 Gate 추론은 첫 실행 약 4.45초, 같은 프로세스에서 모델 재사용 후 약 0.46초였다. 실제 Mac mini 처리량은 별도로 측정해야 한다.
- Gate의 현재 `detected_objects`에는 검출 timestamp와 bbox가 있지만, 활동/정지 판정 로직은 없다.

## 핵심 문제

현재 앱의 “활동시간”은 실제 게코 활동이 아니라 모션 트리거로 저장된 모든 영상 길이의 합이야. Claude 분석이 꺼져 있어 게코가 없거나 게코가 가만히 있는 영상도 전부 활동시간에 포함돼.

v0에서는 실제 활동 구간의 초 단위 합산까지 만들지 않아. 먼저 클립 전체를 다음 네 상태로 나누고, 명확한 제외 클립의 길이를 0초로 계산해.

## 확정된 제품 정책

| decision | 의미 | 앱 계산 |
|---|---|---:|
| `active` | 게코 활동 증거가 하나 이상 있음 | 클립 전체 길이 포함 |
| `exclude_absent` | 영상 디코딩은 정상이나 게코 검출이 없음 | 0초 |
| `exclude_static` | 게코가 충분히 안정적으로 보이지만 활동 증거가 없음 | 0초 |
| `unknown` | 분석 오류, 품질 부족, sparse detection, 근거 부족 | 클립 전체 길이 포함 |
| 미분석 | 아직 worker가 처리하지 않음 | 클립 전체 길이 포함 |

추가 규칙:

- 원본 R2 영상과 `motion_clips` row는 절대 삭제·변경하지 않는다.
- fail-open이 기본이다. 애매하면 `unknown`이다.
- `exclude_absent`와 `exclude_static`은 카메라별 독립 스위치여야 한다.
- 설정 row가 없는 카메라는 필터 비활성이다.
- 현재 테스트 카메라도 사용자가 명시적으로 활성화하기 전까지 필터 비활성이다.
- 향후 새 카메라가 등록돼도 자동 적용되면 안 된다.
- Gate/활동 판정 결과는 Claude나 기존 VLM 결과를 GT로 사용하지 않는다.
- Gate는 evidence를 만들고, 활동 정책 모듈이 제품 판정을 내린다. 두 책임을 코드와 DB에서 분리한다.

## 사용자 체험 계약

1. `[화면]` 앱에서 사용자는 `활동시간(추정)`을 본다.
2. `[신규 클립]` 아직 분석 전이면 기존처럼 전체 길이가 우선 포함된다.
3. `[분석 완료]` 명확한 absent/static 판정이면 다음 조회부터 해당 클립 시간이 빠진다.
4. `[분석 실패]` 활동시간은 줄지 않는다.
5. `[롤백]` DB의 해당 카메라 스위치를 끄면 앱 재배포 없이 즉시 기존 전체 합산으로 복귀한다.

## 아키텍처 결정

### 1. Gate는 추론 라이브러리

`gecko-vision-gate`가 담당할 것:

- 영상 프레임 샘플링
- RF-DETR gecko inference
- 프레임별 gecko bbox/confidence/timestamp evidence
- 체크포인트 SHA-256, threshold, sampler/model/schema version 기록
- Gate 결과의 불변 데이터 계약
- 활동 판정기가 소비할 명시적 Python interface
- 활동 판정용 OpenCV 순수 로직과 단위 테스트를 Gate 레포에 둘지는 기존 책임 경계를 확인한 뒤 결정하되, Gate evidence 생성과 제품 정책 decision은 별도 모듈이어야 한다.

### 2. Nightly는 Mac mini 오케스트레이터

`petcam-nightly-reporter`가 담당할 것:

- `motion_clips` 미처리 row 폴링
- R2 다운로드
- Gate 모델을 프로세스당 한 번만 로드하고 batch에서 재사용
- Gate evidence 저장
- activity policy 호출과 assessment 저장
- clip 단위 오류 격리
- launchd 기반 24시간 실행

기존 `reporter.worker`에 억지로 합치지 마. 현재 worker는 야간/Claude 리포트 역할이므로, `activity_worker` 같은 별도 entrypoint와 별도 launchd job으로 분리해. 새 worker는 Claude/VLM 호출이 0회여야 한다.

Gate CLI를 clip마다 subprocess로 호출해 모델을 매번 다시 로드하면 안 된다. 패키지 dependency 또는 명확한 library boundary로 같은 프로세스에서 detector를 재사용해. 두 로컬 레포 사이 dependency 방식은 절대경로 하드코딩이 없는 재현 가능한 방식을 선택하고 근거를 문서화해.

### 3. Flutter는 하나의 읽기 계약만 사용

Flutter가 raw assessment를 임의로 해석하지 않게 해. 운영 DB에 RLS가 적용된 view 또는 RPC 하나를 만들고 다음 값을 제공해.

- `clip_id`
- `camera_id`
- `started_at`
- `raw_duration_sec`
- `activity_decision`
- `effective_activity_sec`
- `analysis_pending`
- `policy_version`

기존 전체 활동시간과 시간대별 그래프가 같은 `effective_activity_sec`를 사용해야 한다. 보안상 view보다 RPC가 명확하면 RPC를 선택해도 되지만, 기존 Supabase/RLS 패턴을 먼저 확인하고 선택 근거를 설계서에 남겨.

## DB 계약의 최소 요구사항

정확한 이름은 기존 convention을 확인해 확정하되, 책임은 다음처럼 분리해.

### Gate evidence 테이블

`clip_prelabels` 역할:

- `clip_id`는 운영 `motion_clips(id)` FK
- Gate 원시 evidence만 저장
- `model_name`, `model_version`, checkpoint SHA-256, threshold, sampler/schema version 저장
- 프레임별 detection을 손실 없이 저장
- 같은 clip과 Gate 실행 버전의 멱등성 보장
- 서비스 역할만 쓰기
- 앱 사용자는 자기 `motion_clips`에 속한 결과만 읽을 수 있음

### 활동 판정 테이블

`clip_activity_assessments` 역할:

- source prelabel 참조
- `active`, `exclude_absent`, `exclude_static`, `unknown` CHECK
- reason code와 원시 측정값 저장
- `policy_version` 저장
- 같은 clip과 policy version의 멱등성 보장
- 재평가 이력을 덮어쓰지 않음

### 카메라별 설정 테이블

카메라별로 다음을 저장해.

- `camera_id`
- `enabled`
- `exclude_absent_enabled`
- `exclude_static_enabled`
- `active_policy_version`
- 변경 시각과 변경자 또는 최소 감사 근거

설정 row가 없으면 반드시 disabled/fail-open이야. 테스트 카메라 UUID를 migration이나 소스에 하드코딩하지 마.

### DB 안전 요구

- equality + time-range 조회에 맞는 index를 설계해.
- RLS를 먼저 설계하고 service role 전용 쓰기를 검증해.
- authenticated 사용자가 타인의 clip assessment를 읽지 못하는 회귀 테스트 또는 SQL probe가 있어야 한다.
- SQL 오류 상세를 앱에 노출하지 마.
- migration은 원본 파일 수정이 아니라 새 forward migration으로 작성해.
- down/rollback SQL 또는 기능 비활성화 절차를 문서화해.

## 활동 판정 알고리즘 요구

### Gate presence

- `checkpoint_best_ema.pth`의 실제 SHA-256을 실행 환경에서 기록해.
- threshold는 config/policy version으로 관리하고 코드 상수로 숨기지 마.
- recall 우선 동작점을 후보로 삼되, 기존 0.25를 검증 없이 정식값이라고 단정하지 마.
- 정상 디코딩·충분한 frame sampling을 만족했는데 gecko detection이 0건일 때만 absent 후보가 될 수 있어.
- 디코딩 실패, 샘플 부족, 모델 오류는 `unknown`이야.

### Static/activity evidence

단순 bbox 중심 이동 하나로 결정하지 마. 최소한 다음을 조합해.

- 프레임별 최고 신뢰 gecko bbox trajectory
- bbox center/size/IoU 변화
- 연속 프레임의 expanded gecko ROI 내부 grayscale 변화 또는 optical flow
- IR auto-exposure·전체 카메라 흔들림을 구분하기 위한 global background 변화 보정
- visibility frame count/ratio

다음은 `exclude_static`이 아니라 `unknown`으로 보내.

- 한두 프레임만 gecko가 검출됨
- bbox가 프레임 가장자리에 심하게 잘림
- local motion과 global motion을 구분하기 어려움
- 임계값 경계에 걸림
- 짧은 혀·머리 움직임을 배제할 가능성이 큼

활동 증거가 하나라도 신뢰 가능하게 관찰되면 `active`로 해. 빠르다는 이유만으로 미세 움직임을 무시하지 마.

정확한 수치 임계값은 추측으로 확정하지 말고 dry-run 결과와 사람 GT로 정해. 모든 임계값은 하나의 versioned policy object에서 주입되게 해.

## 범위

### v0 In scope

- 테스트 카메라 allowlist/setting
- Gate v2 best-EMA evidence 생성과 provenance
- clip 단위 four-state activity assessment
- 별도 24시간 Mac mini worker
- dry-run과 review manifest
- DB migration/RLS/read contract
- Flutter 전체·시간대별 활동시간 연결
- 앱 문구 `활동시간(추정)`
- 현재 날짜 데이터의 제한적 backfill
- observability와 즉시 롤백
- 관련 SOT 동기화

### v0 Out of scope

- 클립 내부 실제 활동 구간의 초 단위 합산
- 행동 분류(drinking, feeding, shedding 등)
- Claude/VLM 호출 재개
- Gate v3 재학습 완료
- 고객 카메라 적용
- Nightly Slack 리포트 수치 전환
- 최근 7일 이상 대량 backfill
- 라벨링 웹 신규 Gate UI
- 원본 clip 삭제나 storage 비용 절감

## 구현 절차

이 작업은 cross-repo HIGH scope야. 한 번에 전부 수정하지 말고 아래 checkpoint를 지켜.

### Phase 0 — 사실 감사와 설계

1. 네 레포의 `AGENTS.md`/`CLAUDE.md`를 전부 읽어.
2. 운영 DB는 read-only로 실제 schema, FK, RLS, camera ownership, table 부재를 확인해.
3. `motion_clips`와 R2 한 건을 읽기 전용으로 Gate에 통과시켜 현재 artifact가 실행되는지 확인해.
4. 실제 Mac mini 또는 현재 실행 머신에서 model warm-up과 재사용 후 clip 처리시간을 각각 측정해.
5. cross-repo 파일 목록, interface, migration, 테스트, 배포·롤백 순서를 포함한 구현계획을 작성해.
6. 계획은 `/Users/baek/petcam-lab/docs/superpowers/plans/2026-07-14-test-camera-activity-filter-v0.md`에 저장해.
7. 설계가 이 지시문과 충돌하거나 DB 소유 레포가 불명확하면 추측하지 말고 멈춰 보고해.

**이 Phase가 끝나면 먼저 사용자에게 계획을 보고하고 구현 승인을 받아. 승인 전 코드·DB 변경 금지.**

### Phase 1 — Gate evidence와 activity policy, TDD

1. 순수 schema/decision test부터 작성해 실패를 확인해.
2. Gate의 per-frame evidence와 provenance를 하위 호환으로 확장해.
3. activity policy를 순수 함수/명시적 dataclass로 구현해.
4. fixture 영상 또는 합성 프레임으로 다음을 테스트해.
   - 명확한 absent
   - gecko visible + static
   - gecko visible + 이동
   - 머리/혀 수준의 작은 local motion
   - IR 밝기 변화만 존재
   - 카메라 전체 흔들림
   - sparse detection
   - decode/sample failure
5. Gate 전체 테스트와 type/static check를 실행해.
6. 사용자 승인 후 Gate 레포에 범위별 commit을 만들어.

### Phase 2 — DB migration과 Mac mini worker

1. migration/RLS/index SQL을 작성하고 로컬 또는 rollback transaction probe로 검증해.
2. Nightly에 기존 Claude worker와 독립된 activity worker를 TDD로 추가해.
3. worker는 detector 한 번 로드, batch 처리, clip 오류 격리, 멱등 upsert/insert, flock, temp cleanup을 보장해.
4. 테스트 카메라 설정이 없는 상태에서는 0건 처리 또는 assessment만 shadow 저장하되 앱 제외는 0건이어야 해.
5. launchd 파일과 설치/상태확인/로그/중지 절차를 작성해.
6. `.env.example`에는 이름만 추가하고 실제 카메라 UUID·비밀값은 넣지 마.
7. worker 전체 테스트와 dry-run을 실행해.

**운영 Supabase migration 적용 전 사용자 승인을 다시 받아.**

### Phase 3 — 사람 preflight

1. 테스트 카메라에서 다음 세 범주의 후보를 최소 10개씩 총 30개 뽑아.
   - absent 후보
   - static 후보
   - active 후보
2. detector/decision을 숨기고 사람이 먼저 판단할 수 있는 review manifest를 만들어.
3. 사람 판단 후에만 detector/decision과 비교해.
4. Claude/VLM proxy label을 GT로 사용하지 마.
5. 명확한 active clip이 exclude로 1건이라도 판정되면 해당 스위치는 활성화 금지야.
6. 실패 원인, threshold curve, hard case를 Gate report에 기록해.

**사람 검수 결과와 권장 스위치 상태를 보고하고 활성화 승인을 받아.**

### Phase 4 — Flutter 연결

1. DB read contract에 대한 repository test부터 작성해.
2. `motionSeconds`와 `motionSecondsByHour`가 같은 effective duration을 사용하게 바꿔.
3. `unknown`, 미분석, disabled camera는 raw duration을 포함하는 회귀 테스트를 넣어.
4. `exclude_absent`, `exclude_static` 각각 0초가 되는 테스트를 넣어.
5. 전체 합계와 시간대별 합계가 일치하는 테스트를 넣어.
6. 사용자 문구를 `활동시간(추정)`으로 바꿔.
7. Flutter analyze/test/build를 실행해.

### Phase 5 — 제한적 활성화와 관찰

1. 승인받은 테스트 camera row만 `enabled=true`로 설정해.
2. `exclude_absent_enabled`, `exclude_static_enabled`는 사람 preflight를 통과한 것만 켜.
3. 오늘 데이터만 먼저 backfill해.
4. 앱에서 raw total과 filtered total을 대조해.
5. 24시간 동안 제외된 clip 50개를 사람 표본 검수해.
6. false exclusion이 1건이라도 나오면 해당 reason 스위치를 즉시 끄고 원인을 기록해.
7. 안정화 전에는 Nightly Slack 수치와 과거 7일 backfill로 확대하지 마.

**앱 배포와 launchd production enable은 각각 사용자 승인을 받은 뒤 실행해.**

## 관측성 요구

worker 실행마다 비밀값 없이 다음을 한 줄로 남겨.

- 조회 clip 수
- 처리 성공/실패/skip 수
- active/absent/static/unknown 수
- 평균/최대 처리시간
- backlog 크기
- model/policy version

추가로 하루 단위로 다음을 비교할 수 있어야 해.

- raw activity minutes
- filtered activity minutes
- reason별 제외 clip/minutes
- pending/unknown/error 비율
- camera별 결과

로그나 앱 응답에 R2 signed URL, service role key, 내부 SQL 오류를 노출하지 마.

## 성능 요구

- detector는 process lifetime 동안 재사용해.
- MPS에서 여러 detector process를 무작정 병렬 실행하지 마.
- 먼저 단일 worker 처리량을 측정하고 실제 유입률보다 충분한지 확인해.
- 평균 처리율이 유입률을 못 따라가면 frame 수를 임의로 줄이지 말고 backlog와 품질 trade-off를 보고해.
- 임시 mp4/frame은 `TemporaryDirectory`와 `try/finally`로 정리해.
- OpenCV `VideoCapture.release()`를 모든 경로에서 보장해.

## 필수 테스트

### Gate

- schema serialization과 하위 호환
- per-frame evidence
- model provenance
- four-state decision table
- local/global motion 구분
- invalid video와 sparse detection fail-open
- policy version/threshold 주입

### Worker

- allowlist/settings 없는 camera 미적용
- disabled camera 미적용
- 미처리 clip만 선택
- 같은 clip 재실행 멱등
- model 1회 로드와 batch 재사용
- 한 clip 실패가 batch를 중단하지 않음
- temp cleanup
- DB/R2 오류 시 unknown 또는 retry 가능 상태
- 두 독립 스위치 동작

### DB

- FK/cascade 의도 확인
- unique/index 확인
- service role write
- authenticated owner read
- 타 owner read 거부
- 설정 row 없음=disabled
- active policy version만 앱 계산에 반영
- disabled 시 raw duration 복귀

### Flutter

- active 포함
- absent/static 제외
- unknown/pending 포함
- disabled camera 포함
- 전체 합과 hourly 합 일치
- 다중 카메라 NightlyReport 합계 회귀

## 완료 조건

- 테스트 카메라만 명시적으로 활성화 가능하다.
- 새 카메라는 기본 비활성이다.
- Claude/VLM 호출 없이 Mac mini에서 지속 처리된다.
- Gate evidence와 activity decision이 분리·버전 추적된다.
- 분석 실패와 애매한 결과는 활동시간을 줄이지 않는다.
- absent/static을 독립적으로 즉시 끌 수 있다.
- 원본 영상과 `motion_clips`가 불변이다.
- 앱의 전체·시간대별 활동시간이 동일 계약을 쓴다.
- 사람 preflight 전에는 실제 제외가 활성화되지 않는다.
- 테스트, build, DB rollback/RLS probe가 모두 통과한다.
- 관련 Gate/Nightly/Flutter/petcam-lab/product SOT가 실제 구현과 일치한다.

## 금지 사항

- 현재 카메라 3대를 자동 allowlist하지 마.
- 카메라 UUID나 owner UUID를 commit하지 마.
- `motion_score`만으로 게코 활동을 확정하지 마.
- Gate `gecko_visible=false`만 보고 품질 조건 없이 무조건 제외하지 마.
- bbox 중심 이동 하나만으로 static을 확정하지 마.
- Claude/VLM 판정을 사람 GT처럼 사용하지 마.
- `motion_clips`에 임시 decision 컬럼을 직접 추가하지 마.
- 원본 clip을 삭제하지 마.
- Nightly 기존 Claude worker 동작을 바꾸지 마.
- 기존 untracked storage나 다른 세션 변경을 stage하지 마.
- 테스트를 통과하지 않은 상태로 migration·activation·deploy하지 마.
- 사용자 승인 없이 commit/push하지 마.

## Phase별 보고 형식

각 checkpoint에서 다음 순서로 간결하게 보고해.

1. 확인한 사실과 이전 가정의 불일치
2. 변경 파일과 책임
3. DB migration/RLS 영향
4. 테스트 명령과 실제 결과
5. dry-run/사람 검수 결과
6. 남은 위험과 롤백 방법
7. 이번 단계에서 일부러 하지 않은 것
8. 다음 단계에 필요한 사용자 승인 한 가지

작업이 길어진다고 범위를 넓히거나 Gate v3 재학습까지 시작하지 마. v0 목표는 **테스트 카메라의 명확한 비활동 클립을 앱 활동시간에서 안전하게 제외하고, 그 과정의 evidence를 Gate 발전 데이터로 남기는 것**이야.

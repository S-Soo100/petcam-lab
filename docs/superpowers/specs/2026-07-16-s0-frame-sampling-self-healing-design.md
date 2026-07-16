# S0.1 Frame Sampling Self-Healing 설계

> **상태:** 승인됨 / 구현 전
> **선행 감사:** `docs/handoff-prompts/2026-07-16-python-evidence-s0-coverage-audit-report.md`
> **상위 정본:** `docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md`

## 1. 문제와 실측

S0 감사 snapshot에서는 `frames_sampled=0` evidence가 4건이었고, 다음 자연 cycle에서 1건이 더 생겨 live 기준 5건이 됐다. 모두 Mac mini `com.petcam.activity-worker`가 만들었고 `decision=unknown`, `reason_code=insufficient_frames`다.

현재 흐름은 제품 안전 면에서는 fail-open이다. `unknown`은 활동시간을 줄이지 않는다. 그러나 evidence 준비 면에서는 다음 결함이 있다.

1. Gate `sample_frames()`는 OpenCV의 `CAP_PROP_FRAME_COUNT`가 0이거나 indexed read가 모두 실패하면 빈 list를 반환한다.
2. nightly `assess_clip()`은 빈 list도 정상 evidence로 조립한다.
3. worker는 `frames_sampled=0` prelabel과 `activity-v1` assessment를 저장한다.
4. indexer는 assessment 존재만 보고 완료로 판단해 해당 clip을 다시 선택하지 않는다.

따라서 불완전 evidence가 영구 완료로 굳는다. S1은 이 문제를 해소하고 S0를 재통과할 때까지 보류한다.

## 2. 대안

### A. S0 기준을 완화해 0프레임을 허용

현 policy가 `unknown`으로 안전하게 처리한다는 장점이 있지만, S1 selector evidence로 사용할 수 없는 행을 완전한 데이터처럼 취급한다. 채택하지 않는다.

### B. 순차 디코딩 fallback + 불완전 완료 재선정 — 채택

Gate가 메타데이터/seek 실패 시 bounded-memory 순차 디코딩으로 다시 샘플하고, nightly는 최소 6프레임 미달을 저장 성공으로 인정하지 않는다. 기존 불완전 assessment는 indexer가 다시 뽑아 정상 evidence로 self-heal한다.

### C. 별도 failure ledger·retry budget 도입

영구 손상 파일의 무한 재시도를 제어할 수 있지만 새 DB schema와 운영 정책이 필요하다. 현재 5건 복구를 위해서는 과하다. fallback 이후에도 반복 실패가 남을 때 별도 spec으로 다룬다.

## 3. 책임 분리

| 레포 | 책임 | 변경 범위 |
|---|---|---|
| `gecko-vision-gate` | 영상 메타데이터/seek 이상 시 프레임을 실제로 복구 | `frame_sampling.py`, 단위 테스트, 연구 보고 |
| `petcam-nightly-reporter` | 최소 프레임 미달 저장 차단, 불완전 assessment 재선정, cycle 실패 노출 | `gate_runner.py`, `activity_indexer.py`, `activity_worker.py`, 테스트 |
| `petcam-lab` | S0 재감사, SOT·handoff 보고 | 기존 audit script 재사용, 새 rerun report |

Gate는 행동을 판정하지 않고 프레임 복구만 담당한다. nightly는 Gate의 partial sample을 production 완료로 인정할지 결정한다.

## 4. 프레임 fallback 계약

### 4.1 기본 경로

- `CAP_PROP_FRAME_COUNT > 0`이면 기존 균등 index sampling을 먼저 쓴다.
- 요청한 수만큼 읽혔으면 추가 pass 없이 반환한다.
- 기존 정상 영상의 프레임 index·timestamp·성능을 바꾸지 않는다.

### 4.2 fallback 경로

다음 중 하나면 순차 fallback을 수행한다.

- frame count가 0 이하
- 균등 index sampling 결과가 요청 수보다 적음

fallback은 두 번의 순차 pass를 사용한다.

1. 첫 pass: 성공적으로 decode 가능한 frame 수만 센다. frame 배열은 보관하지 않는다.
2. 두 번째 pass: 그 수에 대해 `evenly_spaced_indices()`를 계산하고 목표 frame만 최대 `num_frames`개 보관한다.

따라서 메모리는 영상 전체 frame 수와 무관하게 `O(num_frames)`다. 모든 `VideoCapture`는 `finally`에서 release한다. fps가 유효하지 않으면 기존처럼 30fps를 사용한다.

### 4.3 최소 프레임

Gate sampler는 실제로 읽은 frame list를 반환한다. nightly `assess_clip()`은 `len(frames) < policy.min_frames`이면 `InsufficientSampleFrames`를 raise하고 detector·DB store에 도달하지 않는다. 기본 `activity-v1`의 최소값은 기존대로 6이다.

## 5. self-healing 계약

- indexer의 완료 조건을 “현재 policy assessment 존재”에서 “assessment가 참조하는 prelabel의 `frames_sampled >= min_frames`”로 강화한다.
- assessment가 없거나, FK 대상 prelabel이 없거나, `frames_sampled < min_frames`면 미처리로 다시 선정한다.
- worker는 `policy.min_frames`를 indexer에 명시 전달한다.
- 정상 재처리 시 새 identity(`frames_sampled=12`) prelabel을 append하고, 기존 `(clip_id, policy_version)` assessment upsert가 새 prelabel을 가리킨다.
- 기존 0프레임 prelabel은 삭제·수정하지 않는다. 감사 이력으로 보존한다.
- fallback 후에도 6프레임 미만이면 새 evidence/assessment를 쓰지 않고 cycle은 nonzero로 끝난다. 다음 cycle에서 재시도한다.

## 6. 운영 안전

- 자동 제외 설정과 앱 활동시간은 변경하지 않는다.
- selector, VLM, backfill, Slack, GT, behavior label은 변경하지 않는다.
- 직접 SQL로 기존 0프레임 행을 UPDATE/DELETE하지 않는다.
- 배포는 Mac mini 단일 호스트에서 activity-worker만 잠시 bootout하고 Gate→nightly 순서로 pull한 뒤 재가동한다.
- canary 이전에 5개 문제 clip을 임시 디렉터리에서 진단하고 mp4/jpg 잔여 0을 확인한다.
- production canary는 새 코드가 자연스럽게 assessment를 relink하게 한다. 수동 데이터 보정 RPC는 사용하지 않는다.

## 7. 검증과 게이트

### 코드 게이트

- Gate: 정상 metadata 경로 불변, frame-count=0 fallback, indexed read 부족 fallback, bounded output, capture release
- nightly: 0~5프레임 저장 차단, 6프레임 허용, 불완전 assessment 재선정, 완전 assessment 제외, partial failure exit 1
- 두 레포 전체 테스트와 syntax/whitespace 통과

### production canary 게이트

- 배포 전 0프레임 current assessment 수와 clip short IDs 기록
- 기존 문제 clip 중 decode 가능한 것은 current assessment가 `frames_sampled>=6` evidence로 relink
- 배포 이후 새 `frames_sampled<6` evidence 생성 0
- 영구 손상 clip은 evidence를 새로 쓰지 않고 명시적 실패 로그·exit nonzero
- temp media 0, 다른 LaunchAgent 상태 불변

### S0 재감사 게이트

기존 audit를 새 output 경로 `reports/python-evidence-s0-coverage-20260716-rerun/`으로 실행한다. 과거 보고서를 덮어쓰지 않는다.

- `S0_PASS`: S1 계획으로 이동 가능
- `S0_PASS_WITH_COVERAGE_GAP`: covered subset만 S1, 일반화 금지
- `S0_HOLD_DATA_CONTRACT`: S1 계속 보류, 원인 보고

## 8. 중단 조건

- 정상 영상의 기존 균등 sample 결과가 바뀜
- fallback이 영상 전체 frame을 메모리에 적재함
- 기존 0프레임 감사행을 삭제/수정해야만 통과함
- assessment가 정상 relink되지 않거나 새 0프레임 행이 생김
- activity-worker 외 production service에 영향이 생김
- S0 재감사 무결성 검증이 불일치함

하나라도 해당하면 rollback하고 `NOT_VERIFIED`로 멈춘다.

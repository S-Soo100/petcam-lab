# 짧은 영상 장치 오류 격리·보존 정책 설계

**상태:** 설계 승인 / 구현계획 완료
**작성일:** 2026-07-24
**관련 SOT:** [`specs/feature-rba-data-engine-v1.md`](../../../specs/feature-rba-data-engine-v1.md), [`docs/decision-gate.md`](../../decision-gate.md)
**구현계획:** [`2026-07-24-short-clip-device-error-retention.md`](../plans/2026-07-24-short-clip-device-error-retention.md)

## 1. 한 줄 결정

`duration_sec < 15`는 모든 카메라에서 **장치 오류 후보 신호**로만 사용한다. 사람이 검증한 카메라별 길이 패턴만 자동 제외하고, 7일 동안 복구 가능하게 보관한 뒤 안전 조건을 모두 만족한 영상의 R2 객체만 삭제한다.

즉시 전역 삭제는 하지 않는다. DB 메타데이터와 판정·삭제 이력은 영구 보존한다.

## 2. 근거와 범위

2026-07-24 production SELECT-only 감사:

| 카메라 | 15초 미만 | 전체 | 비율 |
|---|---:|---:|---:|
| P4 Cam 2(dev) | 721 | 2,135 | 33.8% |
| P4 Cam (dev) | 96 | 14,378 | 0.7% |
| P4 Cam 3 | 6 | 961 | 0.6% |

라벨링 웹 표시값은 `Math.round(duration_sec)`다. P4 Cam 2(dev)에서 표시값 4초 1건과 11초 39건은 40/40 모두 Owner가 `skip`으로 판정했고, 연결된 라벨링 세션은 0건이었다.

이 근거로 최초 자동 제외 시그니처는 다음만 허용한다.

- camera: 설정 테이블에서 P4 Cam 2(dev)의 실제 `camera_id`를 조회해 등록
- displayed duration: `round(duration_sec) IN (4, 11)`
- rule version: `short-device-error-v1`

P4 Cam 2(dev)의 나머지 15초 미만 681건과 다른 카메라의 15초 미만 영상은 자동 제외하지 않고 `short_clip_candidate` 감사 대상으로만 기록한다.

## 3. 목표와 비목표

### 목표

- 장치 오류 영상이 사람 라벨링, VLM, Python Evidence 비용을 쓰지 않게 한다.
- 자동 제외된 영상은 Owner가 이유와 삭제 예정일을 보고 복구할 수 있게 한다.
- 다른 카메라에서 같은 오류가 나타나도 카메라별 검증 후 규칙을 확장할 수 있게 한다.
- R2 삭제 전 사람 GT·Canary·연구 배정 여부를 fail-closed로 검사한다.
- 자동 제외·복구·삭제·삭제 차단을 감사 가능한 이력으로 남긴다.

### 비목표

- 짧은 영상 자체를 행동 없음으로 해석하지 않는다.
- Gate/VLM/Python Evidence 결과로 자동 제외하지 않는다.
- `motion_clips` 행이나 사람 GT를 삭제하지 않는다.
- 첫 배포와 동시에 기존 823건의 R2 객체를 대량 삭제하지 않는다.
- 카메라 이름 문자열을 runtime 식별자로 사용하지 않는다.

## 4. 사용자 체험

### Owner

1. `[화면]` 기본 `라벨 대기` 목록에는 검증된 장치 오류 영상이 나타나지 않는다.
2. `[조작]` `제외 → 자동 제외` 필터를 연다.
3. `[반응]` 카드에 `장치 오류 후보`, 적용 규칙, 실제/표시 길이, 삭제까지 남은 시간이 보인다.
4. `[조작]` 정상 영상이면 `라벨 대상으로 복구`를 누른다.
5. `[반응]` Owner 결정이 시스템 규칙보다 우선하며, 영상은 즉시 일반 라벨링 흐름으로 돌아간다.
6. `[감정]` 영상이 왜 사라졌는지 알 수 있고, 잘못 걸러져도 되돌릴 수 있다.

7일이 지난 뒤 안전 삭제가 끝난 카드에는 `원본 삭제됨 · 메타데이터 보존`을 표시한다. 재생 버튼은 비활성화하고 삭제 이유와 시각을 보여준다.

### 일반 라벨러

- 자동 제외 영상은 오늘 작업, 내 기록의 신규 대상, Canary materialization에 들어오지 않는다.
- 시스템 규칙·점수·다른 라벨러 답은 노출하지 않는다.

## 5. 데이터 계약

### 5.1 카메라별 정책

신규 forward migration으로 `camera_short_clip_policies`를 추가한다.

- `camera_id` — PK/FK, UUID 하드코딩 금지
- `candidate_under_sec` — 최초 15
- `auto_exclude_display_seconds` — 최초 P4 Cam 2(dev)만 `{4,11}`, 다른 카메라는 빈 배열
- `retention_hours` — 최초 168
- `rule_version`
- `enabled`
- `created_by`, `created_at`, `updated_by`, `updated_at`

정책 변경은 과거 판정을 재해석하지 않는다. 판정 시점의 `rule_version`과 입력값을 clip별 원장에 복사한다.

### 5.2 시스템 격리 원장

`motion_clip_system_exclusions`에 현재 상태를 두고, 별도 append-only event 테이블에 전이를 기록한다.

현재 상태:

- `candidate`
- `quarantined`
- `restored`
- `media_deleted`
- `deletion_blocked`

필수 provenance:

- clip/camera ID
- 실제 duration과 표시 duration
- reason code
- rule version
- detected/quarantine/delete 시각
- Owner override actor/reason
- R2 delete 결과의 비밀값 없는 코드와 fingerprint

Owner의 명시적 `motion_clip_labeling_triage.owner_decision`은 시스템 격리보다 우선한다. 기존 Owner/라벨러 판정 테이블의 의미를 바꾸지 않는다.

## 6. 처리 흐름

### 6.1 감지·격리

Mac mini의 별도 저비용 worker가 새 `motion_clips` 메타데이터만 읽는다.

1. `duration_sec < candidate_under_sec`면 `candidate`를 멱등 기록한다.
2. 해당 카메라 정책의 표시 길이 시그니처와 일치하면 `quarantined`로 승격한다.
3. quarantine 전 사람 세션·review slot·submission·behavior label이 하나라도 있으면 자동 제외하지 않고 `deletion_blocked` 감사 대상으로 보낸다.
4. R2 다운로드, 영상 디코드, detector, VLM 호출은 하지 않는다.

capture INSERT 경로에는 trigger를 넣지 않는다. worker 장애가 촬영 저장을 막지 않게 fail-open ingestion / fail-closed deletion으로 분리한다.

### 6.2 소비자 차단

`quarantined`는 다음 신규 소비 대상에서 제외한다.

- Owner 기본 미검수 큐
- 일반 라벨러 live slot materialization
- 새 Canary materialization
- VLM selector/backfill 신규 job
- Python Evidence 신규 job

이미 존재하는 사람 GT, blind slot/submission, VLM/Python Evidence job은 변경·삭제하지 않는다.

### 6.3 복구

Owner 복구는 기존 Owner triage 결정 경로를 사용한다.

- `owner_decision='label'` 또는 명시적 reset 후 label 전환
- 시스템 원장은 `restored`
- 삭제 deadline 취소
- append-only event 기록

### 6.4 7일 후 R2 삭제

삭제 worker는 아래 조건을 모두 만족할 때만 R2 객체를 삭제한다.

- 상태가 `quarantined`
- `quarantined_at + retention_hours <= now()`
- Owner 복구 없음
- labeling session 없음
- live/canary review slot·submission·consensus 없음
- behavior label·highlight 등록 없음
- 진행 중 VLM/Python Evidence job 없음
- R2 key가 현재 clip과 일치

검사 실패는 삭제하지 않고 `deletion_blocked`로 기록한다. R2 삭제 성공 후에도 `motion_clips` 행, 원래 `r2_key`, 시스템 원장과 event는 보존하고 `media_deleted_at`을 기록한다.

## 7. 도입 단계

### Phase A — shadow

- migration·worker 배포
- 모든 카메라의 15초 미만을 `candidate`로만 기록
- R2 삭제 off
- 현재 Owner 판정 40/40과 독립 재계산 일치 확인

### Phase B — P4 Cam 2 canary

- 표시 4초·11초만 `quarantined`
- 라벨링/VLM/Python Evidence 신규 소비 차단
- Owner 자동 제외 화면에서 전수 확인
- 정상 행동 오격리 1건이면 정책 즉시 disable

### Phase C — retention delete

- Phase B 오격리 0 확인 후 별도 delete switch 활성화
- 최초 삭제 batch 최대 30
- DB/R2/Slack 대조, temp 0, 다른 카메라 삭제 0 확인
- 통과 후 시간당 상한을 둔 자율 처리

다른 카메라는 camera별 사람 감사에서 오격리 0을 확인한 뒤 별도 정책 row로만 승격한다.

## 8. 측정과 Slack

매일 카메라별로 다음을 집계한다.

- short candidate
- auto quarantined
- Owner restored
- deletion eligible / deleted / blocked
- 라벨링·VLM·Python Evidence 회피 건수
- 규칙별 false exclusion

Slack 예시:

> 짧은 영상 장치 오류
>
> · 후보 34 · 자동 제외 31 · 검수 대기 3
>
> · Owner 복구 0 · 7일 후 삭제 예정 31
>
> · 오늘 R2 삭제 0 · 차단 0

raw key, signed URL, 사용자 이메일, 비밀값은 출력하지 않는다.

## 9. 성공·중단 기준

### 성공

- P4 Cam 2 표시 4/11초 판정이 기존 Owner 40건과 40/40 일치
- 다른 카메라 자동 제외 0
- 사람 세션·blind cohort·151 frozen set mutation 0
- Owner 복구 E2E 통과
- 최초 삭제 batch에서 잘못 삭제 0, metadata residue 100%
- 동일 clip 중복 삭제 시도 0

### 즉시 중단

- 정상 행동 오격리 1건
- Owner 복구 후 다시 quarantine
- 사람 GT/slot이 있는 clip 삭제 시도
- 다른 카메라에 P4 Cam 2 정책 적용
- R2 삭제 성공인데 DB audit 미기록
- worker가 capture나 정규 VLM deadline을 지연

## 10. 롤백

- 정책 `enabled=false`
- 감지·삭제 LaunchAgent bootout
- `quarantined` 중 미삭제 clip은 Owner 기본 큐에 다시 노출
- migration과 event는 감사 증거로 보존
- 이미 삭제된 R2 객체는 복구 불가하므로 Phase C 전 별도 승인과 30건 canary를 강제한다.

## 11. 구현 책임

- `petcam-lab`: migration, read/write RPC, 역할별 라벨링 UI, 안전 probe, SOT
- `petcam-nightly-reporter`: Mac mini 감지·삭제 worker, R2 delete adapter, Slack 요약, LaunchAgent
- Flutter/Gate/RBA worker: 변경 없음

cross-repo 구현은 tracked handoff manifest와 `HANDOFF_OK` 이후에만 시작한다.

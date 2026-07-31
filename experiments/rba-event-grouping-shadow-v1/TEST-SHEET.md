# RBA 사건 묶기 shadow v1 테스트 시험지

**실험 ID:** `rba-event-grouping-shadow-v1`
**작성일:** 2026-07-31
**상태:** 🔒 계약 동결 / harness 구현·검증 완료 / production prepare 인증 대기
**설계:** [`RBA 사건 단위 전수 분석 방향`](../../docs/superpowers/specs/2026-07-31-rba-event-first-total-coverage-design.md)

## 1. 질문과 판정 범위

같은 카메라에서 시간상 이어진 `motion_clips`를 metadata-only 규칙으로 묶을 때, 원본을 하나도
잃지 않으면서 사용자가 볼 사건 수를 의미 있게 줄일 수 있는가?

이 시험이 인증하는 것은 **사건 경계 묶기 v1의 기술 타당성**뿐이다. local/cloud VLM 행동
품질, 사용자 타임라인 UX, P0 recall, Gate/Python Evidence 유용성, production worker
안정성은 인증하지 않는다.

## 2. 절대 경계

- production DB는 SELECT만 허용한다. RPC, insert, update, upsert, delete는 0이다.
- R2 GET/HEAD, 모델 호출, frame 추출, signed URL 저장은 0이다.
- production app/web/Flutter, service, LaunchAgent, queue, runtime은 변경하지 않는다.
- formal Blind30 v1/v2, tutorial, canary, live submission, 사람 GT를 수정하지 않는다.
- local router v0/v1/v2, care-guard, Python Evidence, Gate 결과를 event boundary에 사용하지 않는다.
- 원본 media, `r2_key`, owner/reviewer UUID, email, 원문 GT는 tracked artifact와 로그에 넣지 않는다.
- 실행 산출물은 `storage/rba-event-grouping-shadow-v1/` 아래 mode `0600` 로만 저장한다.

## 3. 입력 창과 Blind30 격리

입력은 다음을 모두 만족해야 한다.

- `started_at < 2026-07-31T03:44:27.183403+09:00`
- KST 07:00 경계의 닫힌 activity day
- 최소 2 cameras, 총 12 camera-nights
- dev와 holdout은 camera-night 단위로 완전 분리하며 각 split이 최소 2 cameras,
  최소 6 camera-nights를 가진다
- 모든 formal/canary cohort의 clip, tutorial clip, frozen holdout 역할 clip은
  `blocked_research`로 accounting하되 event와 boundary pair에서는 제외한다
- Blind30 v2 future pool clip과 겹침 0

행동 GT, VLM/Gate/Python Evidence, consensus 결과, highlight, label은 표본 선택에 사용하지 않는다.
선택 허용 필드는 clip ID, camera ID, activity day, `started_at`, `duration_sec`, system exclusion의
state/reason뿐이다.

## 4. 전체 accounting population

선택한 12 camera-nights에 속한 `motion_clips` 전부가 분모다. 각 clip은 정확히 하나로 귀속된다.

- `activity_candidate`: metadata-only event grouping 입력
- `diagnostic_integrity`: 기존 검증된 system exclusion 또는 유효하지 않은
  `started_at/duration_sec`로 인해 사건 연속성을 끊는 진단 행
- `blocked_research`: formal/canary/tutorial/frozen holdout 이력 때문에 연구 입력으로 사용할 수
  없고 사건 연속성을 끊는 보호 행

`diagnostic_integrity`와 `blocked_research`는 clip을 분모에서 빼는 필터가 아니다. clip ID
fingerprint, 사유코드, source exclusion state를 manifest에 기록한다. 활성 exclusion이 없는
clip을 Python/Gate 점수로 diagnostic 처리하면 즉시 reject다.

## 5. Boundary GT 표본

### 5.1 exact 120 adjacent pairs

각 split은 60 pair, 합계 exact 120 pair다.

| split | gap `≤15s` | `15s < gap ≤60s` | `60s < gap ≤300s` | 합계 |
|---|---:|---:|---:|---:|
| development | 20 | 20 | 20 | 60 |
| frozen holdout | 20 | 20 | 20 | 60 |

pair는 같은 camera와 activity day의 시간순 인접 `activity_candidate` clip 두 개다.

- `gap_sec = next.started_at - (current.started_at + current.duration_sec)`
- 같은 clip을 두 pair에 중복 사용하지 않는다
- dev와 holdout 사이 clip/camera-night 중복 0
- split별 한 camera 비중 ≤60%
- split·gap stratum별 한 camera 비중 ≤70%
- seed: `rba-event-grouping-shadow-v1`
- 부족하면 다른 bin으로 대체하지 않고 `BLOCKED_INSUFFICIENT_BOUNDARY_PAIRS`

### 5.2 사람 판정

두 reviewer가 상대 답, grouping threshold, Python Evidence, Gate, 행동 GT를 보지 않고 각 pair의
원본 두 개와 실제 `gap_sec`만 보고 독립 판정한다.

- `same_event`: 앞 clip 끝의 활동이 뒤 clip 시작까지 같은 행동 흐름으로 직접 이어진다고
  두 원본에서 관찰 가능
- `different_event`: 종료·이탈·재등장·장소/행동의 명확한 단절 때문에 하나의 흐름으로
  묶으면 안 됨
- `uncertain`: 촬영되지 않은 gap, 가림, media 품질 때문에 둘 중 하나를 근거 있게 고를 수 없음

두 답이 같으면 consensus다. 다르거나 한쪽이 `uncertain`이면 owner가 같은 blind 입력만 보고
adjudicate한다. reviewer 원본과 owner 최종값은 immutable하게 분리 보관한다.

holdout 판정값은 algorithm threshold 동결 전까지 scorer에서 접근하지 못하게 별도 파일과
SHA-256으로 봉인한다.

prepare는 reviewer A/B와 owner 입력을 development 60과 holdout 60으로 물리 분리한 6개
파일로 만든다. `score-dev`는 development 3개만 열 수 있다. `score-holdout`은 freeze가
존재한 뒤에만 holdout 3개와 frozen source accounting을 열고, frozen threshold의 3회 grouping
결과에서 지표를 직접 계산한다. caller가 만든 metrics 파일은 입력으로 받지 않는다.

## 6. metadata-only grouping v1

입력 정렬:

```text
(camera_id, activity_day_kst, started_at, clip_id)
```

강제 split:

- camera가 다름
- activity day가 다름
- 사이에 `diagnostic_integrity` clip이 있음
- `gap_sec`가 동결 threshold보다 큼

그 외 인접 clip은 같은 event로 묶는다. threshold 후보는 exact
`[0, 5, 15, 30, 60, 120]`초다.

development 60 pair에서 `over_merge_count == 0`인 후보 중 over-split이 가장 적은 threshold를
선택한다. 동률이면 더 작은 threshold를 택한다. 조건을 만족하는 후보가 없으면 reject다.
선택 뒤 algorithm version, threshold, manifest hash를 동결하고 holdout을 한 번만 연다.

`event_id`:

```text
sha256(
  algorithm_version + "\0"
  + camera_id + "\0"
  + activity_day_kst + "\0"
  + 시간순 clip_id를 "\0"으로 연결
)
```

algorithm version은 `event-gap-metadata-v1`이다.

## 7. 지표

### 무결성

- accounting coverage = 귀속된 source clip / source clip = 100%
- duplicate assignment = 0
- unknown assignment = 0
- event·boundary pair의 formal/canary/frozen holdout overlap = 0
- future cutoff 때문에 Blind30 v2 future pool overlap = 0
- input manifest, GT, prediction, summary hash 독립 재계산 일치
- 같은 입력을 3회 실행한 event membership/event ID/summary bytes 동일 = 100%
- source code 정적 감사에서 DB mutation/RPC와 Evidence/Gate boundary import = 0

### 사람 GT 품질

- 두 reviewer의 raw 3-class agreement ≥80%
- owner adjudication 이후 unresolved pair = 0
- final `uncertain` ≤25%
- holdout의 각 camera에 `same_event`와 `different_event`가 각각 1개 이상

### grouping safety와 utility

- holdout over-merge count = 0, 전체와 camera별 모두
- holdout over-split rate ≤25% overall, camera별 ≤30%
- 전체 accounting population의 activity event count가 activity candidate clip 수보다 ≥15% 감소
- diagnostic clip을 사이에 두고 merge한 event = 0

## 8. 판정

### ADOPT_SHADOW_GROUPING_V1

§7의 모든 무결성·GT·safety·utility 조건을 통과한다. 이 판정은 local artifact에서 다음 단계
local VLM event bundle을 설계해도 된다는 뜻일 뿐 production 노출 승인이 아니다.

### HOLD

- exact 표본이나 카메라별 `same/different` 분모 부족
- reviewer agreement <80% 또는 final uncertain >25%
- safety는 통과하지만 event reduction <15%

기간·camera-night를 늘린 새 TEST-SHEET 없이는 같은 결과에서 threshold를 다시 고르지 않는다.

### REJECT

다음 중 하나면 즉시 reject다.

- source clip 미귀속 또는 중복 귀속 ≥1
- holdout over-merge ≥1
- rerun bytes/event ID 불일치 ≥1
- diagnostic을 가로지른 merge ≥1
- Blind30 v2/frozen formal clip 접촉 ≥1
- production DB/R2/app/service write ≥1
- Python Evidence/Gate/행동·GT·모델 결과를 boundary 입력이나 threshold 선택에 사용
- holdout을 본 뒤 threshold/algorithm/sample 변경

## 9. 산출물

Tracked:

- `TEST-SHEET.md`
- `REPORT-TEMPLATE.md`
- 최종 `REPORT.md`와 비식별 `summary.json`은 실행 후

Git 제외, mode `0600`:

- `source-manifest.json`
- `boundary-pairs.json`
- reviewer별 GT JSONL
- owner adjudication JSONL
- frozen holdout GT
- event membership JSONL

tracked 보고서에는 raw clip/camera UUID 대신 salted fingerprint와 집계만 남긴다.

## 10. 범위 밖

- local VLM, frame sampling, analysis chunk
- cloud VLM/SegmentVLM escalation
- Python Evidence/Gate 기반 사건 경계 비교군
- DB event table, RPC, migration, worker, LaunchAgent
- 앱 사건 카드, 연속 재생, proxy 영상
- 자동 integrity 격리 확대, 원본 숨김·삭제

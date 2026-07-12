# Router Care Guard v1 Report

> **Validity:** `exploratory / invalid-for-adoption`
> **Reason:** post-hoc threshold tuning, evaluation overlap, total VLM cost not measured
> **Canonical audit:** [`reports/router-research-validity-audit-20260712/REPORT.md`](../router-research-validity-audit-20260712/REPORT.md)

- generated_at: `2026-07-10T12:59:28.932600Z`
- Decision: `pass-two-goal-smoke`
- DB writes: `0`
- R2 writes: `0`
- LLM/VLM calls: `0`

## Goal Check

- Goal 1: moving/human_noise 같은 비검사 cloud_now를 내린다.
  - operational non-inspection cloud_now: `24` -> `14`
  - reduction: `10` (41.7%)
- Goal 2: drinking/feeding regression 3건을 검사 후보로 유지한다.
  - regression_pass: `True`
  - inspection_activity_only_after: `0`
  - inspection_low_after: `0`

## Rule

- `cloud_now` + `center_motion_ratio < 0.8` + `active_motion_ratio < 0.95` -> `cloud_later`
- `cloud_later` + `late_motion_ratio >= 1.8` + `motion_peak >= 0.08` + `active_motion_ratio >= 0.15` -> `review_candidate`

## Dataset203 Guardrail

- routes_before: `{'cloud_now': 146, 'review_candidate': 51}`
- routes_after: `{'cloud_now': 109, 'review_candidate': 51, 'cloud_later': 37}`
- moving cloud_now: `67` -> `31`
- moving cloud_now reduction: `36` (53.7%)
- care candidate recall after: `123/123` (100.0%)
- care activity_only after: `0`
- care lowered to cloud_later: `[]`

## Manual Spot Check

- `center_motion_ratio < 0.8` 단독 룰이 낮췄던 dataset203 care 2건을 프레임 몽타주로 확인했다.
- `cd2365f5`는 손/도구가 보이는 명확한 handfeeding이다. off-center 움직임이지만 검사 후보로 유지해야 한다.
- `3f976b25`는 탈피 중인 shedding 장면이다. off-center 움직임이지만 검사 후보로 유지해야 한다.
- 두 케이스 모두 `active_motion_ratio = 1.0`이라, `active_motion_ratio < 0.95` guard를 추가했다.
- review frames:
  - `reports/router-care-guard-v1-20260710/review_frames/cd2365f5_sheet.jpg`
  - `reports/router-care-guard-v1-20260710/review_frames/3f976b25_sheet.jpg`

## Operational 72

- routes_before: `{'cloud_now': 24, 'cloud_later': 14, 'review_candidate': 34}`
- routes_after: `{'cloud_later': 23, 'cloud_now': 14, 'review_candidate': 35}`
- inspection_by_route_after: `{'cloud_later': {'비검사': 23}, 'cloud_now': {'비검사': 14}, 'review_candidate': {'검사': 3, '비검사': 30, '애매함': 2}}`
- regression: `[{'clip_id': '748c1b7d-b634-4793-a9bc-cdf87bee350e', 'action': 'drinking', 'baseline_route': 'cloud_later', 'route': 'review_candidate', 'reason': 'late_low_motion_care_sentinel'}, {'clip_id': 'd9346cbe-9ae4-456c-a018-50ecf10ac476', 'action': 'feeding', 'baseline_route': 'review_candidate', 'route': 'review_candidate', 'reason': 'unchanged'}, {'clip_id': '8abccef4-430a-4d73-a338-3891b46beb3e', 'action': 'drinking', 'baseline_route': 'review_candidate', 'route': 'review_candidate', 'reason': 'unchanged'}]`

## Interpretation

두 목표는 smoke 기준으로 달성했다. `center_motion_ratio` 단독 룰은 handfeeding/shedding 2건을 잘못 낮췄지만, `active_motion_ratio < 0.95` guard를 추가하면 dataset203 care 123건을 모두 검사 후보로 유지한다. 아직 production 채택 전에는 더 큰 운영 리뷰셋에서 human_noise 과검사와 care miss를 확인해야 한다.

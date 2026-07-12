# Router Care Guard v1.1 Report

> **Validity:** `exploratory / invalid-for-adoption`
> **Reason:** post-hoc threshold tuning, evaluation overlap, total VLM cost not measured
> **Canonical audit:** [`reports/router-research-validity-audit-20260712/REPORT.md`](../router-research-validity-audit-20260712/REPORT.md)

- generated_at: `2026-07-11T11:48:40.818210Z`
- Decision: `pass-two-goal-smoke`
- DB writes: `0`
- R2 writes: `0`
- LLM/VLM calls: `0`

## Goal Check

- Goal 1: moving/human_noise 같은 비검사 cloud_now를 내린다.
  - operational non-inspection cloud_now: `24` -> `17`
  - reduction: `7` (29.2%)
- Goal 2: drinking/feeding regression 3건을 검사 후보로 유지한다.
  - regression_pass: `True`
  - inspection_activity_only_after: `0`
  - inspection_low_after: `0`

## Rule

- `cloud_now` + `center_motion_ratio < 0.55` + `active_motion_ratio < 0.95` + `last_motion_sec < 56.0` -> `cloud_later`
- `cloud_later` + `late_motion_ratio >= 1.8` + `motion_peak >= 0.08` + `active_motion_ratio >= 0.15` -> `review_candidate`

## Dataset203 Guardrail

- routes_before: `{'cloud_now': 146, 'review_candidate': 51}`
- routes_after: `{'cloud_now': 120, 'review_candidate': 51, 'cloud_later': 26}`
- moving cloud_now: `67` -> `42`
- moving cloud_now reduction: `25` (37.3%)
- care candidate recall after: `123/123` (100.0%)
- care activity_only after: `0`
- care lowered to cloud_later: `[]`

## Manual Spot Check

- `center_motion_ratio < 0.8` 단독 룰이 낮췄던 dataset203 care 2건을 프레임 몽타주로 확인했다.
- `cd2365f5`는 손/도구가 보이는 명확한 handfeeding이다. off-center 움직임이지만 검사 후보로 유지해야 한다.
- `3f976b25`는 탈피 중인 shedding 장면이다. off-center 움직임이지만 검사 후보로 유지해야 한다.
- 두 케이스 모두 `active_motion_ratio = 1.0`이라, `active_motion_ratio < 0.95` guard를 추가했다.
- 운영 60건 검수 후 `center_motion_ratio < 0.55`와 `last_motion_sec < 56.0`을 추가해, 오래 이어지는 실제 행동 후보를 낮추지 않게 했다.
- review frames:
  - `reports/router-care-guard-v1-20260710/review_frames/cd2365f5_sheet.jpg`
  - `reports/router-care-guard-v1-20260710/review_frames/3f976b25_sheet.jpg`

## Operational 72

- routes_before: `{'cloud_now': 24, 'cloud_later': 14, 'review_candidate': 34}`
- routes_after: `{'cloud_later': 20, 'cloud_now': 17, 'review_candidate': 35}`
- inspection_by_route_after: `{'cloud_later': {'비검사': 20}, 'cloud_now': {'비검사': 17}, 'review_candidate': {'검사': 3, '비검사': 30, '애매함': 2}}`
- regression: `[{'clip_id': '748c1b7d-b634-4793-a9bc-cdf87bee350e', 'action': 'drinking', 'baseline_route': 'cloud_later', 'route': 'review_candidate', 'reason': 'late_low_motion_care_sentinel'}, {'clip_id': 'd9346cbe-9ae4-456c-a018-50ecf10ac476', 'action': 'feeding', 'baseline_route': 'review_candidate', 'route': 'review_candidate', 'reason': 'unchanged'}, {'clip_id': '8abccef4-430a-4d73-a338-3891b46beb3e', 'action': 'drinking', 'baseline_route': 'review_candidate', 'route': 'review_candidate', 'reason': 'unchanged'}]`

## Interpretation

우선 검수 60건을 반영한 v1.1은 `cloud_now -> cloud_later`를 더 보수적으로 수행한다. 운영 검수 60건에서 v1.1이 낮추는 30건은 검사 0건, 비검사 29건, 애매함 1건이다. dataset203 care 123건도 모두 검사 후보로 유지한다. 아직 production 채택 전에는 남은 low-motion/control 검수로 숨은 care miss를 확인해야 한다.

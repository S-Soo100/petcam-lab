# Router Care Guard v1 Review Batch

- batch_id: `router-care-guard-v1-eval-20260710`
- rows: `150`
- csv: `reports/router-care-guard-v1-eval-20260710/manual_review_queue.csv`
- DB writes: depends on `--seed`; build-only mode writes files only.
- LLM/VLM calls: `0`

## Groups

- `guard_demote_cloud_now`: 60
- `guard_promote_late_care`: 1
- `quota_fill`: 29
- `random_control`: 30
- `review_candidate_low_motion`: 30

## Routes

- baseline_routes: `{'cloud_now': 106, 'cloud_later': 1, 'review_candidate': 43}`
- candidate_routes: `{'cloud_later': 60, 'review_candidate': 44, 'cloud_now': 46}`

## Review Goal

- guard가 내린 `cloud_now -> cloud_later` 후보가 정말 비검사인지 확인한다.
- guard가 올린 `cloud_later -> review_candidate` 후보가 실제 검사 후보인지 확인한다.
- low-motion review_candidate와 random control로 숨은 care miss를 확인한다.

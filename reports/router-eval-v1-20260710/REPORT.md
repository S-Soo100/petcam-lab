# Router Eval v1 Manual Review Set

- source: `reports/router-operational-v0-20260710/decisions.jsonl`
- rows_total: `1358`
- recent_operational_rows_since_2026-07-03: `1144`
- DB writes: `0`
- R2 writes: `0`
- LLM/VLM calls: `0`

## Route Distribution

- `cloud_later`: `14`
- `cloud_now`: `307`
- `review_candidate`: `1037`

## Recent Operational Distribution

- `cloud_later`: `14`
- `cloud_now`: `149`
- `review_candidate`: `981`

## Manual Review Queue

- `cloud_later_all`: `14`
- `cloud_now_check`: `24`
- `review_candidate_quantiles`: `34`

## Decision

Decision: `hold-for-manual-review`

현재 룰은 `activity_only`가 0건이라 자동 skip을 검증할 수 없다. 대신 `review_candidate`가 76% 이상이라, 먼저 사람이 샘플을 보고 low reliability 구간을 cloud_later로 낮출 수 있는지 판단해야 한다.

## Review Instructions

- `manual_visible_gecko`: yes/no/unclear
- `manual_action_gt`: moving/static/feeding/drinking/hidden/human_noise/other
- `manual_router_ok`: yes/no/unclear
- `manual_notes`: 왜 맞거나 틀렸는지 짧게 기록

## Artifacts

- `reports/router-eval-v1-20260710/manual_review_queue.csv`
- `reports/router-eval-v1-20260710/manual_review_queue.json`
- `reports/router-eval-v1-20260710/summary.json`

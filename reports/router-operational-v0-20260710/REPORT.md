# Router Operational v0 Report

- generated_at: `2026-07-10T08:34:48.373498Z`
- rows: `1358`
- cloud_now_rate: `22.6%`
- estimated_immediate_vlm_reduction_rate: `77.4%`
- cloud_eventual_rate: `23.6%`
- activity_only_rate: `0.0%`
- review_candidate_rate: `76.4%`
- DB writes: `0`
- R2 writes: `0`
- LLM/VLM calls: `0`

## Routes

- `cloud_later`: 14
- `cloud_now`: 307
- `review_candidate`: 1037

## Reasons

- `feature_not_ready:missing_or_low_reliability`: 1037
- `strong_activity_or_burst`: 307
- `moderate_activity_batchable`: 12
- `low_activity_batchable`: 2

## Decision

Decision: `hold-feature-reliability-low`

## Artifacts

- `reports/router-operational-v0-20260710/summary.json`
- `reports/router-operational-v0-20260710/decisions.csv`
- `reports/router-operational-v0-20260710/decisions.jsonl`

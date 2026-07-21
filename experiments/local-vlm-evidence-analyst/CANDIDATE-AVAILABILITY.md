# Local VLM Evidence 후보 가용성 (B1 SELECT-only)

- selector_version: `local-vlm-evidence-selector-v1`
- query_watermark: `2026-07-21T17:27:02.500641+00:00`
- overall_verdict: **BLOCKED_DATA_INSUFFICIENT**
- camera_count: 3 · date_count: 6
- pool_sha256: `6edd80f44875489e2d961dd218bfb98695a7a0a072ef0d7d9575ff5ee00cf776`
- manifest_emitted: False
- total_source_rows: 2678 → total_episodes: 64
- excluded_counts: {'unclassified_clips': 0, 'episode_deduped_clips': 2614}
- per_clip_stratum_distribution: {'big_move': 898, 'hardcase': 1257, 'rest_micro': 523}

| stratum | episodes | verdict | single-camera% | blockers |
|---|---:|---|---:|---|
| absent | 0 | BLOCKED_DATA_INSUFFICIENT | 100.0% | no_candidates |
| big_move | 14 | BLOCKED_DATA_INSUFFICIENT | 50.0% | below_target_30 |
| rest_micro | 3 | BLOCKED_DATA_INSUFFICIENT | 66.7% | below_target_30 |
| lick_water_food | 0 | BLOCKED_DATA_INSUFFICIENT | 100.0% | no_candidates |
| wheel_object | 0 | BLOCKED_DATA_INSUFFICIENT | 100.0% | no_candidates |
| hardcase | 47 | DATA_AVAILABLE | 33.3% | - |

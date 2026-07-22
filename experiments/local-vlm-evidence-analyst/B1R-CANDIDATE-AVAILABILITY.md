# Local VLM Evidence 후보 가용성 (B1 SELECT-only)

- selector_version: `local-vlm-evidence-selector-v2`
- query_watermark: `2026-07-22T04:16:36.615437+00:00`
- overall_verdict: **BLOCKED_DATA_INSUFFICIENT**
- camera_count: 3 · date_count: 7
- pool_sha256: `614615b0801ccc2a4eb47906b21803bba489e0493bfded48140eecb3cee624f9`
- manifest_emitted: False
- total_source_rows: 2841 → total_episodes: 69
- excluded_counts: {}
- per_clip_stratum_distribution: {'absent': 347, 'big_move': 2643, 'rest_micro': 644, 'lick_water_food': 0, 'wheel_object': 0, 'hardcase': 1259}

| stratum | episodes | verdict | single-camera% | blockers |
|---|---:|---|---:|---|
| absent | 24 | BLOCKED_DATA_INSUFFICIENT | 62.5% | below_target_30 |
| big_move | 8 | BLOCKED_DATA_INSUFFICIENT | 50.0% | below_target_30 |
| rest_micro | 25 | BLOCKED_DATA_INSUFFICIENT | 64.0% | below_target_30 |
| lick_water_food | 0 | BLOCKED_DATA_INSUFFICIENT | 100.0% | no_candidates |
| wheel_object | 0 | BLOCKED_DATA_INSUFFICIENT | 100.0% | no_candidates |
| hardcase | 12 | BLOCKED_DATA_INSUFFICIENT | 41.7% | below_target_30 |

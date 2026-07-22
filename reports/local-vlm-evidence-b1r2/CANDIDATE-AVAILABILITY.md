# Local VLM Evidence 후보 가용성 (B1 SELECT-only)

- selector_version: `local-vlm-evidence-selector-v2`
- query_watermark: `2026-07-22T08:42:55.363487+00:00`
- overall_verdict: **BLOCKED_DATA_INSUFFICIENT**
- camera_count: 3 · date_count: 23
- pool_sha256: `cec461e807ee5f0254ad86fcd03f4f47bca02aa1495b87647cf9c4e054ed2c61`
- manifest_emitted: False
- total_source_rows: 2990 → total_episodes: 120
- excluded_counts: {}
- per_clip_stratum_distribution: {'absent': 361, 'big_move': 2792, 'rest_micro': 674, 'lick_water_food': 0, 'wheel_object': 0, 'hardcase': 1270}

| stratum | episodes | verdict | single-camera% | blockers |
|---|---:|---|---:|---|
| absent | 30 | DATA_AVAILABLE | 36.7% | - |
| big_move | 30 | DATA_AVAILABLE | 50.0% | - |
| rest_micro | 30 | DATA_AVAILABLE | 80.0% | single_camera_over_60pct |
| lick_water_food | 0 | BLOCKED_DATA_INSUFFICIENT | 100.0% | no_candidates |
| wheel_object | 0 | BLOCKED_DATA_INSUFFICIENT | 100.0% | no_candidates |
| hardcase | 30 | DATA_AVAILABLE | 43.3% | - |

# R2 Orphan Manual Review Pack

- generated_at: `2026-07-09T17:50:30.270887+00:00`
- total_rows: `4`
- DB writes: `0`
- R2 writes: `0`
- R2 reads/downloads: local review copy only

## Decisions

- `ignore`: 4

## Final Human Review

- 4 clips are camera setup clips with a human briefly visible in frame.
- They are irrelevant to petcam behavior analysis.
- Do not backfill into `camera_clips`.
- Do not use for router/VLM evaluation.
- R2 deletion remains a separate cleanup decision.

## Visual Status

- `openable`: 4

## Files

- `reports/r2-orphan-review-20260710/review.csv`
- `reports/r2-orphan-review-20260710/review.json`
- `reports/r2-orphan-review-20260710/clips`
- `reports/r2-orphan-review-20260710/thumbnails`

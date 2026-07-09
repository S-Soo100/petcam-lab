# Local Router v2 Report

## Decision

Decision: `hold`
Decision subtype: `hold-policy-too-conservative`

This is the first detector-independent RBA Router scorecard. The router did not see images, filenames, GT labels, or detector boxes.

## L0 Deterministic Router

- policy: `v2`
- N: 197
- routes: `{"cloud_now": 197}`
- cloud_now rate: 100.0%
- eventual cloud VLM rate: 100.0%
- P0 -> activity_only: 0/123 = 0.0%
- P0 -> cloud_later or lower: 0/123 = 0.0%
- avg router latency: 0.000 ms/clip

## L1 Local LLM Smoke

- status: `skipped_l0_not_improved`
- model: `n/a`

## L0 Class By Route

```json
{
  "cloud_now": {
    "drinking": 24,
    "eating_paste": 19,
    "eating_prey": 22,
    "hand_feeding": 29,
    "moving": 72,
    "shedding": 29,
    "unseen": 2
  }
}
```

## Interpretation

L0 v2 did not pass the qwen gate, so L1 was skipped: it produced 0 cloud_later routes with 197/197 clips in cloud_now. This keeps the experiment metadata-first instead of spending local LLM time before the deterministic evidence layer shows an immediate-call reduction signal.

## Artifacts

- `features.jsonl`
- `l0-decisions.jsonl`
- `separability.json`
- `l1-decisions.jsonl` when L1 runs
- `results.json`

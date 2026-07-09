# Local Router v0 Report

## Decision

Decision: `hold`

This is the first detector-independent RBA Router scorecard. The router did not see images, filenames, GT labels, or detector boxes.

## L0 Deterministic Router

- N: 197
- routes: `{"cloud_now": 146, "review_candidate": 51}`
- cloud_now rate: 74.1%
- eventual cloud VLM rate: 74.1%
- P0 -> activity_only: 0/123 = 0.0%
- P0 -> cloud_later or lower: 0/123 = 0.0%
- avg router latency: 0.000 ms/clip

## L1 Local LLM Smoke

- status: `completed`
- summary source: `existing_l1_decisions_jsonl` (regenerated from existing qwen artifacts)
- model: `qwen2.5:14b`
- N: 30
- routes: `{"cloud_later": 2, "cloud_now": 28}`
- cloud_now rate: 93.3%
- P0 -> activity_only: 0/17 = 0.0%
- avg router latency: 6313.9 ms/clip

## L0 Class By Route

```json
{
  "cloud_now": {
    "drinking": 10,
    "eating_paste": 10,
    "eating_prey": 18,
    "hand_feeding": 19,
    "moving": 67,
    "shedding": 20,
    "unseen": 2
  },
  "review_candidate": {
    "drinking": 14,
    "eating_paste": 9,
    "eating_prey": 4,
    "hand_feeding": 10,
    "moving": 5,
    "shedding": 9
  }
}
```

## L1 Class By Route

```json
{
  "cloud_later": {
    "drinking": 1,
    "moving": 1
  },
  "cloud_now": {
    "drinking": 2,
    "eating_paste": 3,
    "eating_prey": 3,
    "hand_feeding": 5,
    "moving": 11,
    "shedding": 3,
    "unseen": 1
  }
}
```

## Interpretation

L0 is safe but too conservative, and the first local LLM smoke only produced limited immediate-call reduction: qwen2.5:14b routed 28/30 smoke samples to cloud_now and 2/30 to cloud_later. This keeps P0 safe, but still misses the cloud_now reduction target and needs a stronger local model/prompt or more operational metadata.

## Artifacts

- `features.jsonl`
- `l0-decisions.jsonl`
- `separability.json`
- `l1-decisions.jsonl` when L1 runs
- `results.json`

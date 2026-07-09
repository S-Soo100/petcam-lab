# Local Router v1 Test Sheet

> 규칙: [`.claude/rules/research-testing.md`](../../.claude/rules/research-testing.md). 실행 전 고정.

## 1. 가설

H0: 현재 OpenCV evidence JSON만으로는 P0 안전성을 유지하면서 immediate cloud VLM 호출을 의미 있게 줄일 수 없다.

H1: OpenCV evidence JSON과 더 나은 route policy/prompt만으로도 P0 -> activity_only <= 2%를 유지하면서 `cloud_now`를 v0의 74.1%보다 낮출 수 있다.

## 2. Sample List

- 데이터셋: `storage/dataset-203/manifest.csv`
- feature source: `experiments/local-router-v0/features.jsonl`
- 대상: full 197 clips
- seed: `20260709`
- local LLM smoke: stratified 30 clips, GT는 sample selection/scoring에만 사용

## 3. Router Inputs

허용:

- duration/fps/resolution
- brightness mean/std
- saturation mean
- motion mean/peak/std
- active motion ratio
- center motion ratio
- late motion ratio

금지:

- GT label
- filename label
- image/frame/video input
- detector bbox
- `skip`, `auto_moving`, `auto_p0`

## 4. Models / Policies

- L0 v0: 기존 deterministic baseline
- L0 v1: `cloud_later` 중심 deterministic policy
- L1 qwen smoke: `qwen2.5:14b`, evidence JSON only, temperature 0 behavior through Ollama default CLI
- L1 gemma reference: v0 result only, `gemma3:4b` sent 30/30 to `cloud_now`

## 5. Metrics

- feature separability by bucket
- `cloud_now` rate
- `cloud_later` rate
- `activity_only` rate
- P0 -> `activity_only` rate
- P0 -> `cloud_later` or lower rate
- average local LLM latency
- route by GT class distribution
- decision subtype: `hold-input-limited`, `hold-model-limited`, `hold-policy-too-conservative`, `reject-unsafe`, `adopt-v1`

## 6. Decision Rules

### adopt-v1

- `cloud_now <= 55%`
- P0 -> `activity_only <= 2%`
- local smoke latency <= 5s/clip for qwen, or deterministic L0 v1 alone meets route target

### hold-policy-too-conservative

- P0 -> `activity_only <= 2%`
- `cloud_now` improves over 74.1% but remains > 55%

### hold-model-limited

- L0 v1 improves routing, but qwen smoke sends >= 90% to `cloud_now` or malformed/review routes.

### hold-input-limited

- Separability analysis shows low-motion/activity-only candidate buckets contain > 5% P0.

### reject-unsafe

- P0 -> `activity_only > 2%` or otherwise violates the `<= 2%` safety gate
- any prompt/policy creates forbidden routes

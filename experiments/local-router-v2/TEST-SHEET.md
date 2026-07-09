# Local Router v2 Test Sheet

> 규칙: [`.claude/rules/research-testing.md`](../../.claude/rules/research-testing.md). 실행 전 고정.

## 1. 가설

H0: OpenCV motion feature에 metadata/event-shape를 추가해도 P0 안전성을 유지하면서 immediate cloud VLM 호출을 의미 있게 줄일 수 없다.

H1: metadata/event-shape evidence를 추가하면 P0 -> activity_only <= 2%를 유지하면서 L0 v2 `cloud_now`를 v1의 74.1%보다 낮추고 `cloud_later`를 만들 수 있다.

## 2. Sample List

- 데이터셋: `storage/dataset-203/manifest.csv`
- 대상: full 197 clips
- seed: `20260709`
- L1 qwen smoke: L0 v2가 `cloud_later > 0`이고 `cloud_now < 74.1%`일 때만 stratified 30 clips
- GT는 sample selection/scoring에만 사용

## 3. Router Inputs

허용:

- duration/fps/resolution
- brightness mean/std
- saturation mean
- motion mean/peak/std
- active motion ratio
- center motion ratio
- late motion ratio
- kst hour / night window
- 10m/30m window clip count
- recent activity baseline / delta
- motion burst count
- longest motion burst seconds
- first/last motion second
- motion coverage ratio
- evidence reliability

금지:

- GT label
- filename label
- image/frame/video input
- detector bbox
- `skip`, `auto_moving`, `auto_p0`

## 4. Models / Policies

- L0 v1 reference: `cloud_now` 74.1%, `cloud_later` 0건
- L0 v2: metadata/event-shape deterministic policy
- L1 qwen smoke: `qwen2.5:14b`, evidence JSON only, only after L0 v2 improves

## 5. Metrics

- `cloud_now` rate
- `cloud_later` rate
- `activity_only` rate
- P0 -> `activity_only` rate
- P0 -> `cloud_later` or lower rate
- metadata/event-shape separability by bucket
- qwen average latency when L1 runs
- decision subtype: `hold-input-limited`, `hold-model-limited`, `hold-policy-too-conservative`, `reject-unsafe`, `adopt-v2`

## 6. Decision Rules

### adopt-v2

- L0 v2 `cloud_now <= 55%`
- L0 v2 `cloud_later > 0`
- P0 -> `activity_only <= 2%`
- qwen smoke latency <= 5s/clip if L1 runs, or deterministic L0 v2 alone meets route target

### hold-policy-too-conservative

- P0 -> `activity_only <= 2%`
- L0 v2 `cloud_now >= 74.1%` or `cloud_later == 0`

### hold-model-limited

- L0 v2 `cloud_now < 74.1%` and `cloud_later > 0`
- qwen smoke sends >= 90% to `cloud_now` or malformed/review routes

### hold-input-limited

- metadata/event-shape low-priority candidate buckets contain > 5% P0

### reject-unsafe

- P0 -> `activity_only > 2%`
- any prompt/policy creates forbidden routes
- router input includes GT/filename/frame/image/detector bbox

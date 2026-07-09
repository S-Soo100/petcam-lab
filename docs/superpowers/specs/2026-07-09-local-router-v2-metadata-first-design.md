# Local Router v2 Metadata-First Design

## 목적

Local Router v1은 안전했지만 cloud VLM 즉시 호출을 줄이지 못했다. 원인은 qwen만의 문제가 아니라, OpenCV motion feature가 P0/non-P0를 가를 만큼 충분한 evidence를 주지 못한 데 있다. v2는 모델 교체 실험이 아니라 metadata/evidence 설계 실험으로 진행한다.

## v1에서 고정된 교훈

- L0 v1은 P0 -> `activity_only` 0.0%로 안전했다.
- L0 v1은 `cloud_now` 74.1%, `cloud_later` 0건이라 v0 대비 즉시 호출 감소 신호가 없었다.
- qwen2.5:14b smoke는 `cloud_now` 93.3%, 평균 6.31s/clip로 느리고 보수적이었다.
- `motion_mean.high`가 196/197건, `active_motion_ratio.high`가 155/197건이라 motion feature만으로는 대부분의 clip이 같은 위험 구간에 뭉친다.

## 설계 원칙

- local LLM을 영상 판독기로 쓰지 않는다.
- local LLM은 L0 evidence가 개선된 뒤에만 실행한다.
- v2의 1차 성공은 qwen 성능이 아니라 L0 deterministic route에서 `cloud_later`가 생기는지다.
- `activity_only`는 극도로 제한한다. 초기 v2에서도 P0 -> `activity_only` <= 2%가 최우선 안전 기준이다.
- `skip`, `auto_moving`, `auto_p0`는 계속 금지한다.
- Claude 구독 기반 VLM 판독 연구와 local-router 우선순위 연구는 산출물과 metric을 분리한다.

## v2 evidence

v2는 기존 OpenCV feature에 운영 metadata와 event-shape feature를 더한다.

### 운영 metadata

- `kst_hour`
- `is_night_window`
- `window_clip_count_10m`
- `window_clip_count_30m`
- `camera_id`
- `recent_activity_baseline`
- `activity_delta_from_baseline`

### event-shape feature

- `motion_burst_count`
- `longest_motion_burst_sec`
- `first_motion_sec`
- `last_motion_sec`
- `motion_coverage_ratio`
- `center_motion_ratio`
- `late_motion_ratio`

### reliability feature

- `brightness_mean`
- `brightness_std`
- `ir_or_low_light_flag`
- `evidence_reliability`: `low`, `medium`, `high`

## 라우팅 구조

### L0 v2 deterministic router

L0 v2는 local LLM 없이 실행한다. 목표는 안전한 `cloud_later` 후보를 만드는 것이다.

- high-risk or unreliable evidence -> `cloud_now`
- normal activity but not clearly urgent -> `cloud_later`
- very static and reliable visible clip -> `activity_only`
- conflicting or sparse evidence -> `review_candidate`

### L1 local LLM router

L1은 L0 v2가 즉시 호출 감소 신호를 만든 뒤에만 실행한다.

- L0 v2 `cloud_now`가 74.1% 이상이면 L1은 실행하지 않는다.
- L0 v2가 `cloud_later > 0`이고 `cloud_now < 74.1%`일 때만 qwen smoke를 실행한다.
- L1은 evidence JSON만 받는다. GT, filename, frame/image/video, detector bbox는 금지한다.

## 판정 기준

### adopt-v2

- P0 -> `activity_only` <= 2%
- L0 v2 `cloud_now` <= 55%
- L0 v2 `cloud_later` > 0
- qwen을 실행한 경우 평균 latency <= 5s/clip 또는 L1 없이 deterministic L0만으로 목표 달성

### hold-policy-too-conservative

- P0 -> `activity_only` <= 2%
- L0 v2 `cloud_now`가 74.1% 이상이거나 `cloud_later`가 0건

### hold-input-limited

- metadata/event-shape feature를 추가해도 낮은 우선순위 후보 bucket에 P0가 5% 초과로 섞인다.

### hold-model-limited

- L0 v2는 `cloud_now < 74.1%`와 `cloud_later > 0`를 만족하지만, qwen smoke가 90% 이상을 `cloud_now` 또는 malformed/review로 보낸다.

### reject-unsafe

- P0 -> `activity_only` > 2%
- forbidden route가 생성된다.
- GT/filename/frame/image/detector bbox가 router input에 들어간다.

## 산출물

- `experiments/local-router-v2/TEST-SHEET.md`
- `experiments/local-router-v2/REPORT.md`
- `experiments/local-router-v2/features.jsonl`
- `experiments/local-router-v2/results.json`
- `experiments/local-router-v2/separability.json`
- `experiments/local-router-v2/l0-decisions.jsonl`
- `experiments/local-router-v2/l1-decisions.jsonl` when L1 runs

## 다음 연구 질문

1. metadata/event-shape feature를 추가하면 `cloud_later`가 생기는가?
2. P0 안전성을 유지하면서 `cloud_now`를 74.1% 아래로 낮출 수 있는가?
3. L0가 개선된 뒤에도 qwen이 보수적으로 붕괴하는가?
4. MacBook M5 32GB에서 latency가 운영 가능한 수준인가?

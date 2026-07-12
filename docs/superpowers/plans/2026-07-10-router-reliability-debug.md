# Router Reliability Debug Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** dataset203과 현재 계속 찍히는 p4 cam 운영 영상을 함께 써서, Router v0의 `review_candidate` 과다 원인과 `evidence_reliability=low` 병목을 해부한다.

**Architecture:** dataset203은 정답 라벨이 있는 안전성 시험지로 쓰고, p4 cam 운영 영상은 실제 환경 분포와 reliability 튜닝 데이터로 쓴다. 두 데이터는 같은 라우터 입력 포맷으로 정규화하되, 평가 목적과 metric은 분리한다.

**Tech Stack:** Python 3.12, OpenCV, Supabase `clip_router_features`, R2 read-only, pytest, CSV/JSONL/Markdown reports.

## Global Constraints

- `skip`, `auto_moving`, `auto_p0`는 이번 단계에서도 금지한다.
- DB writes `0`, R2 writes `0`, LLM/VLM calls `0`가 기본값이다.
- p4 cam 운영 영상은 정답 라벨이 없으므로 정확도 metric으로 쓰지 않는다.
- dataset203은 GT가 있으므로 P0 recall guard와 route 안전성 평가에만 쓴다.
- 사람/카메라 세팅/테스트/깨진 영상은 학습·평가 재료에서 제외한다.
- 목적은 `review_candidate`를 억지로 줄이는 게 아니라, 낮춰도 안전한 조건을 찾는 것이다.

---

## 1. 연구 질문

### Q1. 왜 운영 데이터 1358건 중 1036건이 `review_candidate`로 빠졌나?

현재 Operational v0 결과:

```text
rows: 1358
cloud_now: 308 / 22.7%
cloud_later: 14 / 1.0%
review_candidate: 1036 / 76.3%
activity_only: 0 / 0.0%
decision: hold-feature-reliability-low
```

가설:

- H1: 실제 p4 cam 영상이 어둡거나 품질이 낮아 OpenCV feature 신뢰도가 낮다.
- H2: `evidence_reliability` 기준이 너무 엄격하다.
- H3: 프레임 샘플링 수/구간이 부족해 motion feature가 불안정하다.
- H4: R2 영상의 fps/해상도/인코딩 특성이 feature extraction을 왜곡한다.
- H5: feature는 멀쩡하지만 detector/ROI 없이 행동 안전성을 낮출 근거가 부족하다.

### Q2. dataset203과 p4 cam은 어떻게 다르게 써야 하나?

| 데이터 | 역할 | 가능한 평가 | 금지 |
|---|---|---|---|
| dataset203 | 정답 있는 시험지 | P0가 `activity_only`로 밀리는지, route별 GT 분포 | 운영 분포 대표라고 가정 |
| p4 cam 전체 운영 영상 | 실전 현장 데이터 | reliability 원인, 시간대/카메라/품질 분포, route 비율 | 정확도/recall 직접 주장 |
| p4 cam 수동 샘플 | 운영 GT 보정 샘플 | low reliability가 실제로 나쁜지, route rule 수정 검증 | 전체 운영 정확도 일반화 |

---

## 2. 데이터 구성

### 2.1 dataset203

사용 목적:

- Router rule이 P0 행동을 `activity_only`로 밀지 않는지 확인.
- route별 GT class 분포를 확인.
- 새 reliability rule이 dataset203에서 위험한 false-low-priority를 만들지 않는지 확인.

필수 산출물:

- `reports/router-reliability-debug-20260710/dataset203_routes.csv`
- `reports/router-reliability-debug-20260710/dataset203_summary.json`
- `reports/router-reliability-debug-20260710/dataset203_ROUTE_BY_GT.md`

핵심 metric:

```text
P0 -> activity_only rate <= 2%
P0 -> cloud_later_or_lower rate: report only
route별 GT class 분포
activity_only에 들어간 GT 목록
```

### 2.2 p4 cam 전체 운영 영상

사용 목적:

- `clip_router_features`의 low reliability 원인 분해.
- 시간대/카메라/brightness/motion/fps/해상도 기준으로 low가 몰리는지 확인.
- 실제 운영 환경에서 route 분포가 어떻게 나오는지 확인.

필수 산출물:

- `reports/router-reliability-debug-20260710/p4_operational_summary.json`
- `reports/router-reliability-debug-20260710/p4_reliability_breakdown.csv`
- `reports/router-reliability-debug-20260710/p4_ROUTE_BY_RELIABILITY.md`

핵심 breakdown:

```text
evidence_reliability별 count
route별 count
processing_status별 count
brightness_mean bucket별 low 비율
brightness_std bucket별 low 비율
motion_mean bucket별 route 분포
active_motion_ratio bucket별 route 분포
fps/resolution별 low 비율
KST hour별 low 비율
camera_id별 low 비율
```

### 2.3 p4 cam 수동 샘플

사용 목적:

- low reliability가 진짜 못 믿을 영상인지, 기준이 너무 엄격한 건지 눈으로 확인.
- route별로 대표 샘플을 뽑아 “사람이 봤을 때 사용 가능/불가능”을 기록.

샘플링 원칙:

- 총 60개부터 시작한다.
- 완전 무작위가 아니라 strata를 나눈다.

샘플 구성:

```text
low reliability / review_candidate: 30개
cloud_now / strong_activity_or_burst: 10개
cloud_later / moderate_activity_batchable: 10개
edge cases:
  - 가장 어두운 low 5개
  - motion_mean은 낮지만 motion_peak 높은 5개
```

수동 판정 컬럼:

```csv
clip_id,r2_key,route,reliability,visual_quality,has_gecko_visible,human_or_setup_noise,usable_for_router,notes
```

허용 값:

```text
visual_quality: good / dark_but_usable / too_dark / broken / setup_noise
has_gecko_visible: yes / no / uncertain
human_or_setup_noise: yes / no
usable_for_router: yes / no / uncertain
```

---

## 3. 실험 단계

### Phase A: Reliability 원인 통계

**목표:** low reliability 1036건의 원인을 숫자로 분해한다.

**Files:**
- Create: `scripts/router_reliability_debug.py`
- Create: `tests/test_router_reliability_debug.py`
- Create: `reports/router-reliability-debug-20260710/`

**Steps:**

- [ ] `clip_router_features` row를 read-only로 로드한다.
- [ ] brightness/motion/fps/hour bucket 함수를 테스트 먼저 작성한다.
- [ ] bucket별 count/low-rate 산출 함수를 구현한다.
- [ ] p4 운영 summary/report를 생성한다.

**Success:**

```text
low reliability가 특정 brightness/hour/camera/fps 조건에 몰리는지 확인 가능
DB/R2/LLM/VLM writes or calls = 0
```

### Phase B: p4 Manual Review Pack

**목표:** 대표 샘플 60개의 썸네일/짧은 로컬 리뷰팩을 만든다.

**Files:**
- Modify: `scripts/router_reliability_debug.py`
- Create: `reports/router-reliability-debug-20260710/manual-review/`

**Steps:**

- [ ] route/reliability 기반 stratified sampler를 테스트한다.
- [ ] 샘플 clip의 R2 key를 찾는다.
- [ ] R2에서 로컬로만 다운로드한다.
- [ ] 썸네일/contact sheet를 만든다.
- [ ] `manual_review.csv`를 생성한다.

**Success:**

```text
사람이 60개를 빠르게 판정할 수 있는 리뷰팩 생성
원본 R2는 수정하지 않음
```

### Phase C: dataset203 Safety Replay

**목표:** 새 reliability 후보 rule이 정답 있는 dataset203에서 안전한지 본다.

**Files:**
- Modify: `scripts/router_reliability_debug.py`
- Reuse: `scripts/local_router_v0.py`
- Reuse: `scripts/rba_evidence_first_cascade.py`

**Steps:**

- [ ] dataset203 feature를 router input 포맷으로 변환한다.
- [ ] 현 rule과 후보 rule을 둘 다 적용한다.
- [ ] GT 기준 P0 route 분포를 산출한다.
- [ ] `P0 -> activity_only`가 2%를 넘으면 reject한다.

**Success:**

```text
후보 rule이 dataset203에서 P0를 낮은 우선순위로 위험하게 밀지 않는지 확인
```

### Phase D: Reliability Rule 후보 비교

**목표:** `review_candidate`를 줄일 수 있는 후보 rule을 만들되, 안전성을 유지한다.

후보:

```text
R0 current: low reliability는 전부 review_candidate
R1 visibility-relaxed: brightness가 낮아도 motion feature가 안정적이면 medium
R2 sampling-aware: fps/frame_count/duration이 정상이고 OpenCV read가 안정적이면 medium
R3 conservative-hybrid: R1/R2 조건 + dataset203 safety 통과 시에만 cloud_later 허용
```

비교 metric:

```text
p4 review_candidate rate
p4 cloud_now rate
p4 cloud_later rate
p4 activity_only rate
dataset203 P0 -> activity_only rate
dataset203 P0 -> cloud_later_or_lower rate
manual sample usable_for_router yes/no ratio
```

Decision:

```text
adopt-candidate-for-recall-guard:
  p4 review_candidate <= 40%
  dataset203 P0 -> activity_only <= 2%
  manual low sample 중 usable_for_router=yes 비율이 높음

hold-feature-quality:
  p4 low가 실제로 너무 어둡거나 setup/noise가 많음

hold-rule-too-strict:
  manual review상 멀쩡한 영상이 low로 과다 분류됨

reject-unsafe:
  dataset203 P0 -> activity_only > 2%
```

---

## 4. 최종 보고서 구조

최종 보고서:

```text
reports/router-reliability-debug-20260710/REPORT.md
```

필수 섹션:

```text
1. Executive Summary
2. Data Sources
3. p4 Operational Reliability Breakdown
4. Manual Review Result
5. dataset203 Safety Replay
6. Candidate Rule Comparison
7. Decision
8. Next Research Step
```

최종 결론은 네 가지 중 하나로만 쓴다.

```text
adopt-candidate-for-recall-guard
hold-feature-quality
hold-rule-too-strict
reject-unsafe
```

---

## 5. 다음 연구 연결

이 계획이 끝난 뒤에만 다음 중 하나로 간다.

### Case 1: `hold-rule-too-strict`

reliability 기준만 수정하면 된다. local LLM은 아직 필요 없다.

### Case 2: `hold-feature-quality`

프레임 샘플링, 카메라 위치, IR/조명, OpenCV extraction 자체를 개선해야 한다.

### Case 3: `adopt-candidate-for-recall-guard`

그때 recall guard 샘플링으로 넘어간다.

### Case 4: `reject-unsafe`

detector/ROI/gate v3 없이는 낮은 우선순위 라우팅을 확장하지 않는다.

---

## 6. 왜 이 계획이 필요한가

지금 문제는 “라우터 모델이 멍청하다”가 아니라 “라우터가 받은 cheap evidence를 믿을 수 없다고 판단한다”는 점이다. 따라서 Qwen/local LLM을 바로 붙이면 애매한 입력을 더 비싼 방식으로 해석하는 꼴이 된다.

이 계획은 재료를 먼저 검증한다.

- dataset203으로 안전성을 본다.
- p4 cam 전체로 실전 분포를 본다.
- p4 cam 샘플로 실제 영상 품질을 본다.
- 그 다음에야 rule 수정, recall guard, local LLM 투입 여부를 결정한다.

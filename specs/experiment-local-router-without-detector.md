# Experiment — Detector-Independent Local Router

**상태:** 🚧 제안 / 다음 연구 방향  
**작성:** 2026-07-09  
**전략명:** Detector-Independent Local Router  
**연관 SOT:** [`docs/AI-VIDEO-ANALYSIS-STRATEGY.md`](../docs/AI-VIDEO-ANALYSIS-STRATEGY.md), [`experiment-rba-evidence-first-cascade.md`](experiment-rba-evidence-first-cascade.md), [`../experiments/gate-recall/REPORT.md`](../experiments/gate-recall/REPORT.md), [`../docs/LOCAL_LLM_TRACK_A_REPORT.md`](../docs/LOCAL_LLM_TRACK_A_REPORT.md)

## 0. 1차 성적서 (2026-07-09)

산출물: [`../experiments/local-router-v0/REPORT.md`](../experiments/local-router-v0/REPORT.md)

Decision: `hold`

- L0 deterministic router, full `dataset-203` 197건:
  - `cloud_now`: 146/197 = **74.1%**
  - `review_candidate`: 51/197 = **25.9%**
  - P0 → `activity_only`: **0/123 = 0.0%**
  - 평균 route latency: 사실상 0ms/clip
- L1 local LLM smoke, `gemma3:4b`, stratified 30건:
  - `cloud_now`: **30/30 = 100.0%**
  - P0 → `activity_only`: **0/17 = 0.0%**
  - 평균 latency: **2.58s/clip**

해석:

- 안전성은 확보했다. P0를 낮은 우선순위로 밀지 않았다.
- 하지만 L0는 너무 보수적이라 cloud VLM 절감 목표(`cloud_now <= 40%`)를 통과하지 못했다.
- `gemma3:4b`는 더 보수적으로 붕괴했다. 모든 smoke sample을 `cloud_now`로 보냈기 때문에 RBA Router 후보로는 부족하다.
- 다음 라운드는 `qwen2.5:14b` smoke, operational metadata 추가, calibration examples 포함 prompt 중 하나로 진행한다.

## 0.1 v1 성적서 (2026-07-09)

산출물: [`../experiments/local-router-v1/REPORT.md`](../experiments/local-router-v1/REPORT.md)

Decision subtype: `hold-policy-too-conservative`

- L0 v1 cloud_now: 74.1%
- L0 v1 cloud_later: 0건
- L0 v1 P0 -> activity_only: 0.0%
- qwen2.5:14b smoke cloud_now: 93.3%
- qwen2.5:14b smoke latency: 6.31s/clip
- qwen2.5:14b smoke P0 -> activity_only: 0.0%
- qwen2.5:14b smoke P0 -> cloud_later or lower: 5.9%

해석:

- L0 v1은 P0를 `activity_only`로 밀지 않아 안전하지만, 즉시 호출이 74.1%이고 `cloud_later`가 0건이라 v0 대비 즉시 호출 감소 신호를 만들지 못했다. 따라서 1차 subtype은 모델 한계가 아니라 정책 보수 과다다.
- qwen2.5:14b는 evidence-only 라우터 smoke에서 28/30건을 `cloud_now`로 보내 역시 보수적/model-limited 신호를 보였고, 평균 latency도 6.31s/clip로 목표보다 느리다. 단, L0 v1이 먼저 개선되지 않았기 때문에 qwen 결과는 2차 관찰로 둔다. 다음은 metadata 추가 또는 prompt calibration이다.
- separability는 feature-only high-motion collapse를 보여준다. `motion_mean.high`가 196/197건이고 P0 rate 62.2%, `active_motion_ratio.high`가 155/197건이고 P0 rate 76.1%라 OpenCV motion feature만으로 낮은 우선순위를 안전하게 가르기 어렵다.

## 0.2 v2 성적서 — Metadata-First (2026-07-09)

산출물:

- 설계: [`../docs/superpowers/specs/2026-07-09-local-router-v2-metadata-first-design.md`](../docs/superpowers/specs/2026-07-09-local-router-v2-metadata-first-design.md)
- 실행 계획: [`../docs/superpowers/plans/2026-07-09-rba-router-v2-metadata-first.md`](../docs/superpowers/plans/2026-07-09-rba-router-v2-metadata-first.md)
- 보고서: [`../experiments/local-router-v2/REPORT.md`](../experiments/local-router-v2/REPORT.md)

Decision subtype: `hold-policy-too-conservative`

- L0 v2 cloud_now: 197/197 = **100.0%**
- L0 v2 cloud_later: **0건**
- L0 v2 P0 -> activity_only: **0/123 = 0.0%**
- L1 status: `skipped_l0_not_improved`
- qwen2.5:14b smoke: 실행 안 함

해석:

- v2는 안전했지만 절감은 더 나빠졌다. L0 v2가 모든 clip을 `cloud_now`로 보내 v1의 74.1%보다 후퇴했다.
- gate 규칙대로 L0 v2가 `cloud_later > 0`과 `cloud_now < 74.1%`를 만족하지 못했기 때문에 qwen2.5:14b는 실행하지 않았다.
- 이번 metadata-first는 실제 운영 metadata 없이 기본값 기반 event-shape/reliability만 추가한 1차 구현이라, "metadata가 통하지 않는다"가 아니라 "현재 추가 feature가 route를 낮출 만큼 정보량을 만들지 못했다"로 해석한다.

다음 결정:

- qwen prompt/model 개선으로 넘어가지 않는다.
- v3는 synthetic/default metadata가 아니라 실제 시간대/window/recent baseline을 채운 뒤 다시 평가한다.
- 실제 metadata가 준비되기 전에는 local-router가 아니라 ingestion/feature-store 쪽을 먼저 보강한다.

## 1. 배경

오늘 논의의 출발점은 "VLM의 비중을 최대로 줄이되, 속도와 정확도는 유지하기"였다.

처음에는 `detector evidence → ROI → local router` 순서가 자연스러워 보였지만, 이 프로젝트에서는 이미 `gecko-vision-gate` 연구가 선행되어 있다. 최신 gate 검증 결과는 다음과 같다.

- RF-DETR v2, backlog 300개
- recall **90.9%** (`200/220`)
- specificity **40.0%** (`32/80`)
- threshold sweep 0.10~0.60에서도 recall 천장 **90.9%**
- FN 20개는 detector score=0이라 threshold로 회복 불가
- decision: **reject**

따라서 지금 연구 순서는 "Detector Evidence부터 새로 시작"이 아니다. detector는 **별도 Gate v3 트랙**으로 유지하고, local router 연구는 detector 없이 가능한 범위에서 먼저 진행한다.

## 2. 핵심 정정

### 잘못된 순서

```text
Detector Evidence부터 새로 연구
→ ROI
→ local router
```

### 이 프로젝트에서 맞는 순서

```text
gate v2 reject를 전제로 둔다
→ detector 없이 가능한 local priority router를 먼저 만든다
→ skip/auto-label은 금지한다
→ gate v3가 통과하면 bbox evidence를 local router에 합류시킨다
```

즉 local router v0의 목표는 행동 자동판정이 아니다. **cloud VLM 호출 우선순위를 정하는 것**이다.

## 2.5 Claude 구독 기반 연구와의 분리

이 실험은 현재 돌아가는 Claude 구독 기반 RBA 연구와 겹치지 않게 관리한다.

| 구분 | Claude subscription research | Detector-Independent Local Router |
|---|---|---|
| 목적 | clip/frame을 직접 보고 행동을 판독하거나 설명한다 | cloud VLM을 언제 호출할지 우선순위를 정한다 |
| 입력 | 이미지/frame/contact sheet/segment artifact 가능 | v0에서는 OpenCV/metadata/evidence JSON만 허용 |
| 실행 위치 | `petcam-rba-worker`, `petcam-nightly-reporter` | `petcam-lab` spec에서 정의, 구현 위치는 별도 합의 |
| 산출물 | Claude blind eval, SegmentVLM report, nightly report | route JSON, route 분포, cloud fallback 포함 운영 성능 |
| 금지 | local router route 정책을 임의로 변경 | Claude eval 결과를 자동 라벨 정답처럼 사용 |

관리 규칙:

- Claude 연구는 **판독 품질 연구**로 유지한다.
- local router 연구는 **우선순위 라우팅 연구**로 유지한다.
- 둘 다 같은 dataset을 볼 수 있지만, metric 이름과 report 디렉토리를 분리한다.
- local router v0의 성공 기준은 "Claude보다 행동을 잘 맞히는가"가 아니라, "P0를 낮은 우선순위로 밀지 않으면서 cloud VLM 호출량을 줄이는가"다.
- Claude 쪽에서 발견한 insight는 `기존 평가 지식`으로만 넣을 수 있고, route 정책 변경은 별도 TEST-SHEET/REPORT 없이 반영하지 않는다.

## 3. 목적

Local LLM을 영상 판독기로 쓰지 않는다. local LLM은 evidence JSON과 운영 context를 읽고, cloud VLM 호출을 언제/어떤 우선순위로 할지 결정한다.

목표:

- cloud VLM 전수 호출을 줄인다.
- P0 행동을 영구 skip하지 않는다.
- local 판단은 `skip`이 아니라 `cloud_now / cloud_later / activity_only / review_candidate`로 제한한다.
- detector v3가 준비되기 전에도 실험 가능한 구조를 만든다.

## 4. 입력 evidence v0

detector bbox 없이 시작한다.

사용 가능:

- OpenCV feature
  - motion mean / peak / std
  - active motion ratio
  - brightness mean/std
  - saturation mean
  - duration / fps / resolution
- 운영 metadata
  - camera_id
  - started_at / KST hour
  - night window 여부
  - motion_score
  - 같은 윈도우 clip 수
  - 최근 활동량 baseline
- 기존 평가 지식
  - OpenCV-only moving auto-label 실패
  - local VLM fine-grained 7-class 실패
  - shedding local specialist 가능성은 있으나 false positive 위험
  - gate v2 reject

금지:

- GT label
- 파일명에 들어있는 label
- detector bbox를 필수 입력으로 가정하기
- `skip` 또는 `auto_moving`을 v0에서 켜기

## 5. Local Router v0 출력

```json
{
  "route": "cloud_now",
  "priority": 0.91,
  "risk": "high",
  "reason": "motion-only evidence cannot safely exclude P0 behavior"
}
```

허용 route:

| route | 의미 |
|---|---|
| `cloud_now` | P0 가능성 또는 사용자 하이라이트 가치가 있어 즉시 cloud VLM |
| `cloud_later` | 영구 skip은 아니고, 배치/한도 여유 시 분석 |
| `activity_only` | 행동 판정 없이 활동량/시간대 통계에만 사용 |
| `review_candidate` | local/metadata가 이상하거나 conflict가 있어 HITL 후보 |

v0 금지 route:

| route | 금지 이유 |
|---|---|
| `skip` | detector recall 검증 전에는 P0 false negative 위험 |
| `auto_moving` | OpenCV-only moving auto-label false 75% |
| `auto_p0` | local VLM fine-grained 분류 실패 이력 |

## 6. 평가 설계

### 데이터

1. `dataset-203` full 197건
2. nightly/backlog window 300건 (`experiments/gate-recall`과 같은 계열)
3. 가능하면 owner GT가 있는 recent highlight clip

### 측정 지표

| 지표 | 목표 |
|---|---:|
| cloud_now 비율 | 20~40% |
| P0가 `activity_only`로 밀린 비율 | 0~2% |
| P0가 `cloud_later` 이하로 밀린 비율 | 보고 지표, 초기엔 허용하되 영구 skip 아님 |
| average local router latency | 1~3초/clip |
| cloud fallback 포함 accuracy | v40 baseline 유지 |
| route별 class 분포 | 특정 class 누락 여부 확인 |

중요: v0는 cloud 호출 절감률보다 **P0를 낮은 우선순위로 잘못 밀지 않는지**가 더 중요하다.

## 7. 연구 순서

### Phase L0 — no-LLM rule baseline

local LLM을 붙이기 전, deterministic priority rule을 만든다.

목적:

- local LLM이 정말 필요한지 확인한다.
- metric과 report 포맷을 먼저 고정한다.

### Phase L1 — local text LLM router smoke

MacBook M5 32GB에서 local text model을 사용한다.

입력은 evidence JSON만 사용한다. 이미지/영상은 금지한다.

비교:

- deterministic rule
- local text LLM router
- random/top-N baseline

### Phase L2 — full 197 simulation

`dataset-203` full로 route 분포를 측정한다.

성공하면 backlog 300으로 확장한다.

### Phase L3 — local specialist는 shedding만

기존 local LLM Track A 보고서에서 가능성이 있던 shedding만 별도 specialist 후보로 둔다.

단, v0에서는 자동 확정이 아니라 `review_candidate`로만 보낸다.

### Phase G — gate v3 별도 트랙

local router와 별개로 진행한다.

- gate v2 불일치 68개 육안 GT
- v3 재학습
- recall ≥95% 통과 시 router evidence에 `gecko_visible`, bbox trajectory 추가

## 8. 채택/폐기 기준

### adopt

- `cloud_now`를 40% 이하로 줄인다.
- P0가 `activity_only`로 밀리는 비율이 2% 이하.
- local router latency가 3초/clip 이하.
- fallback 포함 정확도가 v40 baseline에서 2pp 이상 떨어지지 않는다.

### hold

- 절감 신호는 있으나 P0 우선순위 오류가 2~5%.
- route 이유가 불안정하거나 모델별 재현성이 낮다.
- gate v3 evidence가 필요하다고 판단된다.

### reject

- P0가 `activity_only`로 5% 이상 밀린다.
- deterministic rule보다 local LLM router가 낫지 않다.
- latency가 cloud VLM 대기보다 크다.
- route가 설명 불가능하거나 비결정성이 크다.

## 9. 한 줄 결론

Detector-Independent Local Router는 detector gate를 대체하지 않는다. **gate v2가 reject된 현재 상태에서도 시작 가능한 local 연구 트랙**이다. 목표는 자동판정이 아니라, cloud VLM 분석을 안전하게 우선순위화하는 것이다.

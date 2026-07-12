# Experiment — RBA Evidence-First Cascade

**상태:** ✅ 완료 — decision `adopt_preprocessor_first_hold_auto_label`
**시작:** 2026-07-09
**완료:** 2026-07-09
**전략명:** Evidence-First Cascade
**연관 SOT:** [`docs/AI-VIDEO-ANALYSIS-STRATEGY.md`](../docs/AI-VIDEO-ANALYSIS-STRATEGY.md), [`specs/experiment-vlm-token-reduction-80.md`](experiment-vlm-token-reduction-80.md), [`specs/feature-rba-evidence-based-feeding-drinking.md`](feature-rba-evidence-based-feeding-drinking.md)

## 1. 목적

VLM이 영상의 모든 일을 직접 하게 두지 않고, Python/OpenCV/detector가 먼저 싼 증거를 만든 뒤 VLM은 애매하거나 중요한 케이스만 판정하게 한다.

목표:

- 비VLM 처리 비중을 높인다.
- 평균 입력 토큰을 줄인다.
- 기존 VLM 기준선의 정확도를 유지하거나, 정확도 손실을 명시된 허용 범위 안에 둔다.
- 나중에 detector, tracker, temporal model, HITL을 붙일 수 있는 확장 구조로 만든다.

## 2. 기존 전략과 구분

이 전략은 SegmentVLM과 다르다.

- SegmentVLM: 영상을 event로 쪼갠 뒤 event별 VLM 분석을 더 잘하게 만드는 정밀 분석 전략.
- Evidence-First Cascade: VLM 호출 전, 비VLM evidence로 skip/auto-label/route/review를 결정하는 비용 절감 + 확장 전략.

이 전략은 저토큰 contact-sheet 전략과도 다르다.

- contact-sheet: 같은 VLM 판정을 더 작은 이미지 입력으로 시도한다.
- Evidence-First Cascade: VLM에게 넘기기 전에 영상의 일부 판단을 Python/OpenCV 쪽으로 옮긴다.

## 3. 성공 조건

이번 연구의 1차 성공 조건은 아래 중 하나다.

1. **운영 고토큰 기준선 성공:** 120k tokens/clip급 direct 호출 대비 평균 입력 토큰 80% 이상 절감, clip-level accuracy 손실 2pp 이하.
2. **v40 frames 기준선 성공:** `frames-adaptive` 대비 평균 입력 토큰 50% 이상 절감, clip-level accuracy 손실 2pp 이하.
3. **정밀 라우팅 성공:** 정확도는 유지하되, VLM 호출 대상 clip을 20% 이상 줄이고 false auto-label rate 5% 이하.

실패 조건:

- 정확도 손실이 2pp를 넘는데 회복할 fallback 구조가 없다.
- false auto-label rate가 5%를 넘는다.
- 비VLM 자동 처리 비중이 10% 미만이다.

## 3.1 결과 요약 (2026-07-09)

Full `dataset-203` 197건으로 실행했다. 산출물은 [`../experiments/rba-evidence-first-cascade/REPORT.md`](../experiments/rba-evidence-first-cascade/REPORT.md)에 있다.

결론:

- **채택:** preprocessor-first baseline. Python/OpenCV가 영상 디코딩·프레임 선택·evidence 추출을 맡고, VLM은 adaptive frames만 본다.
- **효과:** 120k tokens/clip급 direct-video 기준선 대비 `19,730 tokens/clip`로 **83.6% 절감**, fallback 기준선 대비 accuracy drop **0.00pp**.
- **보류:** OpenCV-only auto-label. conservative moving rule은 full 197에서 non-VLM 6.1%밖에 못 처리했고, false auto-label rate가 **75.0%**라 안전하지 않다.
- **다음 확장:** detector evidence가 필요하다. gecko presence, hand/tool/prey/bowl ROI가 붙기 전에는 자동라벨을 켜지 않는다.

따라서 이번 전략은 "목표 일부 달성"으로 기록한다.

- 토큰 절감 + 정확도 유지: ✅ 달성 (high-token direct 기준)
- 비VLM 자동판정 비중 확대: ⏸️ 보류 (OpenCV-only로는 실패)
- 확장 가능한 구조: ✅ 달성 (detector/tracker/temporal model/HITL 삽입 지점 분리)

## 4. 실험 단계

### Stage 0 — 기존 저토큰 VLM 결과 정리

`experiments/codex-dataset203-model-sweep-pilot14/`와 `experiment-vlm-token-reduction-80` 결과를 재사용한다.

기대:

- contact-sheet만으로는 정확도 유지가 안 됨을 baseline으로 확정한다.

### Stage 1 — 순수 비VLM evidence feature 추출

`dataset-203` 영상에서 아래 feature를 추출한다.

- duration, fps, frame count, resolution
- brightness mean/std
- saturation mean
- motion mean/peak/std/active ratio
- center/peripheral motion ratio
- early/mid/late motion distribution

이 단계는 행동을 맞히기보다, VLM 라우팅에 쓸 수 있는 싼 신호가 있는지 본다.

### Stage 2 — Conservative auto-label router

비VLM feature만으로 확실한 것만 자동 처리한다.

초기 auto-label 후보:

- `moving`: motion evidence가 높고, feeding/hand/prey/shedding 후보 신호가 낮은 clip.
- `unseen`: brightness/motion/edge evidence가 낮고, 기존 detector가 붙으면 gecko absent인 clip.

나머지는 VLM fallback으로 보낸다.

### Stage 3 — Cascade simulation

기존 VLM 결과를 fallback으로 두고 아래 지표를 계산한다.

- non_vlm_rate
- fallback_rate
- accuracy
- accuracy_drop_pp
- token_reduction
- false_auto_label_rate
- class별 자동 처리 분포

## 5. 산출물

- [x] `scripts/rba_evidence_first_cascade.py`
- [x] `tests/test_rba_evidence_first_cascade.py`
- [x] `experiments/rba-evidence-first-cascade/features.jsonl`
- [x] `experiments/rba-evidence-first-cascade/results.json`
- [x] `experiments/rba-evidence-first-cascade/REPORT.md`

## 6. 해석 원칙

- GT를 feature나 rule에 직접 넣지 않는다. GT는 채점에만 쓴다.
- 파일명에 들어있는 GT 라벨은 feature로 쓰지 않는다.
- auto-label은 보수적으로 한다. 목표는 모든 행동을 비VLM으로 맞히는 게 아니라, VLM이 볼 필요 없는 clip을 안전하게 줄이는 것이다.
- 성공하지 못해도 보고서에 실패 이유와 다음 전략을 기록한다.

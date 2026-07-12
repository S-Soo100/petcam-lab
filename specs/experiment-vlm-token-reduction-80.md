# Experiment — VLM 토큰 80% 절감 검증

> VLM 호출을 full frames/video direct 대신 저토큰 primary + 제한 fallback 구조로 바꿨을 때, 평균 입력 토큰을 80% 줄일 수 있는지 계산으로 검증한다.

**상태:** ✅ 완료 (토큰 예산 검증 완료, 품질 채택은 별도)
**작성:** 2026-07-08
**연관 SOT:** [`docs/AI-VIDEO-ANALYSIS-STRATEGY.md`](../docs/AI-VIDEO-ANALYSIS-STRATEGY.md), [`specs/experiment-claude-montage-v2.md`](experiment-claude-montage-v2.md)

## 1. 목적

nightly/Track A 계열 VLM 호출에서 입력 토큰이 병목이다. 특히 `claude` 기반 frame 분석은 한 클립이 수만~12만 토큰까지 커질 수 있어, 전량 direct 분석은 구독 한도와 운영비를 동시에 압박한다.

이번 작업의 목적은 새 정확도 실험이 아니라, **80% 절감이 가능한 비용 구조인지**를 숫자로 잠그는 것이다. 정확도는 기존 M0/v40/cascade 리포트를 그대로 존중하고, 이 스펙에서는 평균 입력 토큰과 fallback 허용률만 검증한다.

## 2. 스코프

### In

- baseline 대비 primary 입력표현의 평균 입력 토큰 절감률 계산.
- direct-video/full-frames fallback을 일부 clip에 추가했을 때도 80% 절감이 유지되는 최대 fallback 비율 계산.
- 재사용 가능한 계산 모듈과 CLI 작성.
- 기존 실험 수치로 재현 명령 기록.

### Out

- production VLM worker 교체.
- sibling repo(`petcam-nightly-reporter`, `gecko-vision-gate`, `petcam-rba-worker`) 직접 수정.
- 몽타주/저토큰 primary를 정확도 기준으로 채택.
- 프롬프트 변경 또는 새 VLM 호출 실험.

## 3. 완료 조건

- [x] `backend/vlm/token_budget.py` — 평균 토큰, 절감률, target 유지 최대 fallback 비율 계산.
- [x] `scripts/vlm_token_budget.py` — 실험/운영 로그 숫자를 넣어 PASS/FAIL 재현.
- [x] `tests/test_vlm_token_budget.py` — 계산식 단위 테스트.
- [x] `uv run pytest tests/test_vlm_token_budget.py -q` 통과.
- [x] 기존 실험 수치 2개로 80% 목표 검증.

## 4. 설계 메모

### 4.1 계산 모델

기본 cascade 비용 모델:

```text
expected_avg_tokens = primary_avg_tokens + fallback_rate * fallback_avg_tokens
reduction = 1 - expected_avg_tokens / baseline_avg_tokens
```

fallback을 "primary 대신"이 아니라 "primary 호출 후 direct 재호출"로 잡았다. 실제 운영에서 cheap primary가 먼저 돌고, 모호/고위험 clip만 원래 full input으로 재분석하기 때문이다. 보수적인 계산이다.

### 4.2 검증 A — v40 adaptive frames 대비 M0 몽타주

입력 숫자:

| 항목 | 근거 | 값 |
|---|---|---:|
| baseline | `experiments/v40-regression/REPORT.md` | 3.65M tokens / 185 calls = 19,729.7 |
| primary | `experiments/m0-montage/REPORT.md` | 770k tokens / 240 calls = 3,208.3 |

재현:

```bash
uv run python scripts/vlm_token_budget.py \
  --baseline-total-tokens 3650000 --baseline-calls 185 \
  --primary-total-tokens 770000 --primary-calls 240
```

결과:

```text
reduction : 83.7%
decision  : PASS
max fallback for target : 3.7%
```

해석:
- 토큰만 보면 80% 절감 달성.
- 단 v40 frames baseline이 이미 비교적 낮아, 80% 목표를 유지하려면 fallback은 약 3.7%만 허용된다.
- M0 리포트 decision은 `hold`다. 최고 변형도 frames보다 낮고 micro 행동이 무너졌다. 따라서 이 primary는 **최종 판정용이 아니라 cheap triage / prefilter 용도**로만 본다.

### 4.3 검증 B — 120k/clip급 high-token 호출 대비

입력 숫자:

| 항목 | 값 |
|---|---:|
| baseline | 120,000 tokens / clip |
| primary | 3,208 tokens / clip |
| fallback | baseline direct call |
| fallback_rate | 16% |

재현:

```bash
uv run python scripts/vlm_token_budget.py \
  --baseline-total-tokens 120000 --baseline-calls 1 \
  --primary-total-tokens 3208 --primary-calls 1 \
  --fallback-rate 0.16
```

결과:

```text
expected avg input tokens : 22,408.0
reduction                 : 81.3%
decision                  : PASS
max fallback for target   : 17.3%
```

해석:
- 고토큰 direct 호출이 진짜 병목인 환경에서는 저토큰 primary + fallback 16%까지도 80% 절감이 유지된다.
- 운영 가드는 `fallback_rate <= 0.16`을 1차 목표로 두는 게 안전하다. 17.3%는 수학적 상한이라 버퍼가 없다.

### 4.4 채택 전략

권장 구조:

```text
모든 clip
→ 저토큰 primary (몽타주/compact frame bundle/metadata)
→ high-value label, low confidence, user flag, gate disagreement만 direct fallback
→ fallback_rate를 윈도우 단위로 16% 이하로 cap
→ tokens_input/tokens_output을 로그/DB에 저장해 실제 절감률 감시
```

중요한 경계:
- **gate unseen 30% 절감만으로는 80%에 못 미친다.** gate는 결합 레버다.
- **몽타주 단독 채택은 품질상 아직 불가.** token PASS와 accuracy PASS를 분리한다.
- v40 adaptive frames 기준으로 80%를 유지하려면 fallback 여지가 거의 없다. 이 기준에서는 "cheap prefilter"와 "정밀 direct"를 제품 요구에 따라 분리해야 한다.

## 5. 학습 노트

- **primary + fallback 비용 모델**: Node로 치면 모든 요청에 lightweight validator를 먼저 태우고, 일부만 expensive validator를 추가 실행하는 구조다. 평균 비용은 `cheap + p * expensive`다.
- **80% 목표의 의미**: baseline의 20% 예산 안에 primary와 fallback을 모두 넣어야 한다. primary가 baseline의 16%를 이미 쓰면 fallback 예산은 4%뿐이다.
- **토큰 절감과 정확도는 별도 게이트**: 토큰 계산은 PASS여도, M0처럼 micro 행동 정확도가 깨지면 production 채택은 HOLD다.

## 6. 참고

- [`experiments/m0-montage/REPORT.md`](../experiments/m0-montage/REPORT.md)
- [`experiments/v40-regression/REPORT.md`](../experiments/v40-regression/REPORT.md)
- [`experiments/cascade-opus-sim/REPORT.md`](../experiments/cascade-opus-sim/REPORT.md)
- [`docs/AI-VIDEO-ANALYSIS-STRATEGY.md`](../docs/AI-VIDEO-ANALYSIS-STRATEGY.md)

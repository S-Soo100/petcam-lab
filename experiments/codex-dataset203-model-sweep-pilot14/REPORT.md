# Codex dataset-203 model sweep

## Decision

`Codex CLI + ChatGPT account` 경로에서는 80% 토큰 절감 전략이 성립하지 않는다.

- 최고 절감: `gpt-5.5 compact/contact-sheet-96` = 42.5% 절감, 하지만 정확도 85.7% -> 42.9%로 42.9pp 하락.
- `gpt-5.4 compact/contact-sheet-96` = 36.5% 절감, 정확도 78.6% -> 42.9%로 35.7pp 하락.
- cascade는 정확도를 회복할수록 fallback 비용 때문에 절감률이 빠르게 사라진다. `gpt-5.5 threshold=0.9`는 정확도 85.7%를 회복하지만 토큰은 오히려 51.1% 증가한다.
- `gpt-5.4-mini` smoke는 compact sheet-96 1건에서 62,148 input tok / 65.9s로 느리고 비쌌다.
- `gpt-5.3-codex`, `gpt-5.4-nano`는 현재 ChatGPT 계정의 Codex CLI에서 400 unsupported.

해석: Codex CLI는 coding-agent용 developer/context 오버헤드가 커서, 이미지 입력을 줄여도 VLM 호출 토큰이 80%까지 내려가지 않는다. Codex 모델로 제품 VLM을 옮기려면 CLI가 아니라 OpenAI API 직접 호출로 다시 측정해야 한다. 현재 환경에는 `OPENAI_API_KEY`가 없어 API 직접 측정은 미실행이다.

## Summary

- total records: 56
- successful records: 56
- error records: 0
- successful records without Codex usage JSON: 0

## Model x Representation

| model | prompt | repr | N | accuracy | avg input tok | avg sec | median sec |
|---|---:|---:|---:|---:|---:|---:|---:|
| gpt-5.4 | compact | contact-sheet-96 | 14 | 42.9% | 17,788 | 7.39 | 6.98 |
| gpt-5.4 | v40 | frames-adaptive | 14 | 78.6% | 28023.79 | 9.31 | 6.87 |
| gpt-5.5 | compact | contact-sheet-96 | 14 | 42.9% | 16924.50 | 6.70 | 6.46 |
| gpt-5.5 | v40 | frames-adaptive | 14 | 85.7% | 29408.79 | 7.97 | 7.76 |

## Paired Reduction

| model | prompt | candidate | baseline prompt | token reduction | accuracy drop | speed delta sec |
|---|---:|---:|---:|---:|---:|---:|
| gpt-5.4 | compact | contact-sheet-96 | v40 | 36.5% | 35.71pp | -1.92 |
| gpt-5.5 | compact | contact-sheet-96 | v40 | 42.5% | 42.86pp | -1.27 |

## Cascade Simulation

| model | primary | fallback | threshold | N | fallback rate | accuracy | token reduction | avg sec |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| gpt-5.4 | compact/contact-sheet-96 | v40/frames-adaptive | 0.5 | 14 | 7.1% | 50.0% | 30.5% | 7.84 |
| gpt-5.4 | compact/contact-sheet-96 | v40/frames-adaptive | 0.6 | 14 | 14.3% | 50.0% | 22.2% | 9.83 |
| gpt-5.4 | compact/contact-sheet-96 | v40/frames-adaptive | 0.7 | 14 | 28.6% | 50.0% | 5.6% | 10.97 |
| gpt-5.4 | compact/contact-sheet-96 | v40/frames-adaptive | 0.8 | 14 | 57.1% | 57.1% | -25.4% | 13.32 |
| gpt-5.4 | compact/contact-sheet-96 | v40/frames-adaptive | 0.9 | 14 | 64.3% | 64.3% | -31.8% | 13.76 |
| gpt-5.5 | compact/contact-sheet-96 | v40/frames-adaptive | 0.5 | 14 | 0.0% | 42.9% | 42.5% | 6.70 |
| gpt-5.5 | compact/contact-sheet-96 | v40/frames-adaptive | 0.6 | 14 | 14.3% | 50.0% | 28.1% | 7.75 |
| gpt-5.5 | compact/contact-sheet-96 | v40/frames-adaptive | 0.7 | 14 | 28.6% | 57.1% | 15.9% | 8.72 |
| gpt-5.5 | compact/contact-sheet-96 | v40/frames-adaptive | 0.8 | 14 | 71.4% | 64.3% | -31.5% | 12.34 |
| gpt-5.5 | compact/contact-sheet-96 | v40/frames-adaptive | 0.9 | 14 | 92.9% | 85.7% | -51.1% | 14.02 |

## Confusion

### gpt-5.4|compact|contact-sheet-96
- 2x shedding -> moving
- 1x drinking -> moving
- 1x eating_paste -> moving
- 1x eating_prey -> moving
- 1x moving -> eating_paste
- 1x unseen -> eating_paste
- 1x unseen -> drinking

### gpt-5.4|v40|frames-adaptive
- 2x unseen -> moving
- 1x shedding -> moving

### gpt-5.5|compact|contact-sheet-96
- 2x shedding -> moving
- 2x unseen -> moving
- 1x drinking -> moving
- 1x eating_paste -> unseen
- 1x eating_prey -> moving
- 1x hand_feeding -> moving

### gpt-5.5|v40|frames-adaptive
- 2x unseen -> moving

# Local VLM Mac Studio 구매 판단 Gate v1 — Frozen Test Sheet

상태: `FROZEN_BEFORE_MEASUREMENT`

설계 정본: `docs/superpowers/specs/2026-08-02-local-vlm-mac-studio-purchase-gate-v1-design.md`

## 고정 계약

| 항목 | 값 |
|---|---|
| runtime | Ollama `0.32.5` |
| model order | `gemma3:4b-it-q8_0` → `gemma4:12b-it-qat` → `qwen3-vl:8b-instruct-q4_K_M` → `qwen3-vl:30b-a3b-instruct-q4_K_M` |
| generation | temperature `0`, seed `20260802`, retry `0`, timeout `180s`, `num_ctx=8192`, `num_predict=96` |
| synthetic | 12-frame 장면 7개×2 + 8-frame A/B 경계 2개×2 = 모델별 18 request |
| development | 합성 18/18 PASS 모델만 74경계, same/different `57/17`, frozen input SHA로 원본 pair를 exact 복원 후 768px 개별 `4A+4B` 재추출 |
| holdout | historical/future `0` 접근 |
| resource stop | free memory `≤3%` 2연속, swap delta `>2GiB`, runtime crash/PID drift |

## 측정 전 model inventory 동결

Ollama 0.32.5에서 pull과 `/api/tags`를 실제 확인했다.

| model | digest | bytes |
|---|---|---:|
| `gemma3:4b-it-q8_0` | `2376388dec1627f34e046065f670ff8af8f766f8aa0968363cc997c2565f48e0` | 4,979,946,122 |
| `gemma4:12b-it-qat` | `38044be4f923e5a55264ed7df4eaac2676651a905f735197c504045140c02bd3` | 7,151,003,754 |
| `qwen3-vl:8b-instruct-q4_K_M` | `0533d74300e4f9bc367d675d4e64ffd073d50ff16a2b4096cc2e8a1cf8c96319` | 6,140,415,975 |
| `qwen3-vl:30b-a3b-instruct-q4_K_M` | `c871fc73fabc5516500b70a298ea25fd44a6a23d5cffc46c63b50302543e3915` | 19,595,410,126 |

## Synthetic Gate

- dark background 1개
- clean static/moving 1쌍
- moving-shadow static/moving 1쌍
- global-brightness-transition static/moving 1쌍

- 같은 production boundary schema의 연속 이동 `same_event` 2회
- 같은 production boundary schema의 위치 점프 `different_event` 2회

18/18 schema·정답·반복 일치와 context budget을 모두 만족해야 development 진입을 허용한다.

## Development Gate

- source media ledger SHA `78/78`, frozen combined input SHA `74/74`
- regenerated combined SHA exact unique match `74/74`, ambiguous/missing `0/0`
- complete/schema `74/74`
- over-merge `0/17`
- same recall `≥29/57`
- frozen model/input/prompt digest 불변

## 모델 상태와 구매 판정

모델 상태: `PASS / QUALITY_FAIL / SYNTHETIC_GATE_FAIL / RESOURCE_FAIL / TAG_UNAVAILABLE`.

- 12B 이하 통과: `MAC_STUDIO_NOT_REQUIRED_FOR_QUALITY`
- 4B·12B·8B가 모두 `QUALITY_FAIL|SYNTHETIC_GATE_FAIL`이고 30B 통과:
  `MAC_STUDIO_64GB_PURCHASE_EVIDENCE_PENDING_HOLDOUT`
- 하나라도 `RESOURCE_FAIL|TAG_UNAVAILABLE`: `INCONCLUSIVE_NEEDS_COMPATIBLE_HARDWARE`
- 전 모델 품질 실패: `NO_MAC_STUDIO_PURCHASE_EVIDENCE`

## 금지

- 결과를 본 prompt/sampler/gate 수정
- holdout, production DB/R2/service/plist 접근·변경
- 자동 사건 병합·skip·행동 GT·사용자 노출
- 이번 결과만으로 하드웨어 구매

# eval-0608 — Claude v3.6 blind 정성 평가 리포트

**일자:** 2026-06-08
**트랙:** Claude 구독 정성 검증 ([`experiment-claude-subscription-rba.md`](../../specs/experiment-claude-subscription-rba.md))
**입력:** inbox/0608 신규 44개 영상 → 5×6 contact sheet
**판정:** v3.6 프롬프트(`build_system_prompt(crested_gecko, prompt_version='v3.6')`)로 서브에이전트 6명 **blind** (GT 미공개, meta.json 차단)

> ⚠️ **정량 baseline 아님.** Gemini 영상 네이티브가 아니라 Claude + contact sheet 입력이다. 모델·입력 둘 다 production(Gemini 2.5 Flash, 영상)과 달라서 "v3.6 정확도 XX%"로 인용 금지. 방법론/입력 한계의 **정성 스냅샷**. 정량은 Gemini key 복구 후 `load_eval_set_0608` + `eval_vlm_v36_handfeeding` 로.

## 결과 요약

| 지표 | 값 |
|---|---|
| raw 정확도 | 34/44 = **77.3%** |
| feeding-merged | 34/44 = 77.3% (drinking↔paste 교차혼동 0이라 raw와 동일) |
| **hand_feeding OOD recall** | **12/14 = 85.7%** (v3.5 구조적 0 → v3.6 순수 이득) |
| **hard negative 게이트** | not-drinking → **moving ✅** (drinking 오탐 안 냄) |

클래스별: hand_feeding 86% · drinking 78% · eating_prey 73% · eating_paste 67% · moving 100%

## 핵심 발견 3가지

### 1. v3.6 OOD 룰 작동 — 12/14 hand_feeding 탐지
사람 손/손가락/시린지/핀셋이 contact sheet 에 **보이는** 12건은 OOD 룰이 confident(conf 0.8~0.97)하게 hand_feeding 으로 잡음. 못 잡은 2건은 **입력 한계**:
- `hand-feeding-2959` → moving (혼잡한 IR 인클로저, 도구가 격자 stills 에서 식별 불가)
- `hand-feeding-2961` → eating_paste (도구가 샘플된 프레임에 안 잡혀 dish paste 로 판정)

→ 둘 다 "도구가 off-frame/저해상"이라 못 본 것. 룰 결함이 아니라 contact sheet 해상도 한계 (스펙 §7 실증과 일치).

### 2. hard negative 게이트 통과 — 과탐(false positive) 0
**전체 오답 10건이 전부 `정답클래스 → moving`(또는 paste) 방향.** drinking 아닌 걸 drinking 이라 한 경우 **0건**. `not-drinking-just-licking-own-face` 도 moving 으로 정확히 판정 — v3.6 "eye-licking is NOT drinking" 룰 작동.

→ **사용자 질문("hard negative 활용되나")의 답:** 활용된다. 그리고 이 평가에서 v3.6+contact sheet 는 **보수적**이라 과탐을 안 함. 역설적이지만 그래서 **hard negative 1건의 압박은 약함** — 모델이 애초에 과탐을 안 하니 false-positive 게이트가 "쉽게 통과". hard negative 가 진짜 변별력을 가지려면 **미세신호를 다 보는 Gemini 영상 네이티브**(과탐 위험↑)에서 돌려야 의미. 지금 결과는 "contact sheet 에선 과탐 안 함"까지만 증명.

### 3. 최대 오답 패턴 = contact sheet 미세신호 한계 (→moving 과소)
9/10 오답이 →moving. 전부 "정지 격자에서 혀 접촉·작은 prey·dish 내용물 확인 불가 → 보수적 moving":
- `eating-prey-163f`/`8617` (conf 0.85): prey 가 작거나 일부 프레임에만 → 자신있게 moving 오답
- `eating-paste-8949`/`9482`/`0522a`: 작은 dish 라 tongue-to-paste 확인 불가 → moving
- 대조: close-up 인 `eating-paste-7921` 은 혀 접촉 명확 → 95% 정답

→ **같은 eating_paste 인데 해상도에 따라 67%~95%로 갈림 = 입력 한계 증명.** v3.6 프롬프트 문제 아님. Gemini 영상 네이티브면 이 →moving 오답들 상당수 회복 예상.

## 한계 (정직 구분)
- **모델 일반화 X** (§6.1): production=Gemini. 이 결과는 Claude 방법론 검증까지만.
- **재현성 1회** (§6.2): temp 비고정. conf 0.4~0.6 모호건(43q3, 9ac3, 2959 등)은 재호출 시 흔들릴 수 있음 — 3회 반복 미측정.
- **contact sheet 해상도**: 30프레임 360px 격자. 미세 도구/혀/소형 prey 손실 — 위 오답의 주원인.

## 다음 방향
1. **Gemini key 복구 시 정량 회귀평가** — `eval_vlm_v36_handfeeding` 에서 `load_eval_set` → `load_eval_set_0608` 교체하면 같은 44건을 영상 네이티브로. 이 정성 결과와 대조하면 "contact sheet 가 얼마나 미세신호를 잃는지" 정량화.
2. **hand_feeding 14건은 OOD 룰 채택 근거 보강** — Gemini 정량에서도 recall 확인되면 v3.6 승격 검토.
3. **hard negative 더 수집** — 1건으론 false-positive 변별 약함. drinking 오탐 유발 케이스(빈 그릇 핥기, 얼굴 핥기, 허공 핥기)를 모아야 precision 게이트가 의미.

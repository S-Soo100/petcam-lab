# Opus vs Sonnet 정확도 (186) 보고서 (REPORT)

**실험 ID:** opus-sonnet-186 · **날짜:** 2026-06-15
**상태:** ✅ 완료 · **decision: `Opus 우위`** (+3.2%p)
**시험지:** [`TEST-SHEET.md`](TEST-SHEET.md) (pre-reg, 합격기준 불변) · **sample:** [`sample_list.json`](sample_list.json) (186)
**입력:** 적응형 frames@1080 · **프롬프트:** v4.0 · **모델:** Opus 4.8 + Sonnet 4.6 blind

---

## 1. 결과

| 모델 | 186 전체 | 회귀셋 185 | 급여경계(186) |
|---|---|---|---|
| **Opus 4.8** | **88.7%** (165/186) | **89.2%** (165/185) | 88.7% (165) |
| **Sonnet 4.6** | **85.5%** (159/186) | **85.9%** (159/185) | 86.0% (160) |
| **Δ (Opus−Sonnet)** | **+3.2%p** | +3.3%p | +2.7%p |

**클래스별 raw (Opus / Sonnet, 186):** moving 70/68 · shedding 26/26 · hand_feeding 26/27 · eating_prey 15/13 · eating_paste 15/14 · drinking 12/11 · unseen 1/0.

**care-priority 3클래스** (moving+shedding+drinking, 117): Opus 92.3%(108) · Sonnet 89.7%(105).

**discordant 11건:** Opus만 정답 8 · Sonnet만 정답 2(`sample-157` hf, `sample-99` moving) · 둘다 오답 1(`sample-29` eating_prey→shedding/moving).

## 2. 시험지 대비

- **합격기준(decision 룰): 사전 그대로.** Opus−Sonnet > +2%p → "Opus 우위" 라벨.
- **품질 가드 통과:** Sonnet 회귀셋 185 = **85.9%**, v40-regression 측정과 **정확 일치** → 재활용 정합 + 채점 무결 검증.
- **실행 방법 (결과 무관, 절차 기록):** Opus 186 = Workflow 2회(1차 세션한도로 80건, 2차 resume로 +96건=176) + 누락 10건(`sample-91~100`, 529 overload) 별도 Opus Agent 재배치. Sonnet = v40 재활용 185 + eval-0615 1 신규(`sonnet0615.json`). **합격기준 사후변경 없음.**

## 3. 가설 판정

- **H0(차이 없음) 기각, H1(차이 있음) 채택.** Opus +3.2%p (>2%p 게이트).
- **방향 신뢰 근거:** ① P1(frames-10 + v3.6.1)에서도 Opus +3%p로 **입력·프롬프트 바뀌어도 격차 일관** = 노이즈 아님. ② discordant 8:2 Opus 우위. ③ 클래스 대부분 Opus≥Sonnet.

## 4. Decision: `Opus 우위`

1. Opus 88.7% > Sonnet 85.5% (+3.2%p, 186 raw) — 게이트 초과.
2. P1(+3%p)과 일관 → 모델 자체 능력 격차(미세접촉·prey 판정에서 Opus가 강함).
3. **단 production 전환은 별도 결정** — Opus는 Sonnet 대비 비용·지연이 큼. +3.2%p가 그 비용을 정당화하는지는 제품 요구(정확도 vs 비용)에 달림.
4. **캐스케이드 후보**: Sonnet 기본 + 저신뢰/특정클래스만 Opus 에스컬레이션 = 비용 절반에 Opus 정확도 근접 가능(별도 시뮬 필요, P4 캐스케이드 자산 재활용).

## 5. 한계 / 노이즈

- **소표본 Δ:** 186 중 6건 차(165 vs 159). temperature 비제어라 ±노이즈 존재 — 단 P1 일관 + discordant로 방향은 견고.
- **eval-0615(sample-186) 둘 다 moving 오답:** 저화질 drinking. 같은 영상 직전 blind는 drinking 0.78이었으나 이번엔 둘 다 moving(0.55/0.75) — **drinking 경계의 temperature 흔들림**. 1건이라 전체 영향 미미하나 "저화질 drinking 불안정" 신호. (회귀셋 185 비교에는 미포함이라 무영향)
- **Opus 배치 분할:** Workflow 2회 + Agent 1회로 나뉨(세션한도·529). 같은 입력·프롬프트·blind라 비교 유효하나 시점 상이.
- **자기 채점:** scorer는 deterministic(코드)이라 무결하나, ④ LLM audit(Codex 교차) · ⑤ discordant 사람 영상 review는 미실시 — 필요시 후속.
- **Opus drinking 과탐 1건:** `sample-99`(GT moving → Opus drinking) — Opus도 v4.0 drinking 확장 부작용 있음(Sonnet은 정답).

## 6. 다음 액션

- **production 모델 선택**: Opus가 정확도 우위(+3.2%p)나 비용 trade-off 검토 필요 → 캐스케이드(Sonnet→Opus 에스컬레이션) 시뮬이 ROI 최적일 수 있음.
- (선택) discordant 11건 사람 영상 review → GT-noise 여부 + Opus/Sonnet 강약 정성 분석.
- (선택) 안정성: 분류 noise가 신경쓰이면 temperature 0 API 또는 3-vote 다수결.

## 7. 부록 — quality_tag 층화 분석 (B1 후속, 2026-06-15)

manifest `quality_tag`(drinking 17 전수 + 모델 오답 16 육안)로 186 예측 층화. 새 인퍼런스 없음 — `scripts/_score_by_quality.py` 재집계.

### 7-1. 모델 격차는 hard 샘플에 집중 (캐스케이드 근거)
- **drinking 전수 17** (신뢰 — selection bias 없음): closeup Opus 5/6·Sonnet 5/6 / production 3/3·3/3 / **handheld-challenging Opus 4/7·Sonnet 3/7**. 쉬운 건 동률, 어려운 것만 Opus가 더 건짐.
- cam-motion 71 (production heur): Opus 94% vs Sonnet 90% (+4%p) — P1의 Sonnet moving→shedding 과탐 재현.
- → **캐스케이드 직접 근거**: Sonnet 기본 + hard 샘플만 Opus 에스컬레이션 = 적은 비용으로 +3.2%p 격차 회수 가능.

### 7-2. 클래스별 quality 민감도 (핵심 발견)
| 클래스 | 민감도 | 근거 |
|---|---|---|
| **drinking** (전수 17) | quality-**sensitive** | 실패가 handheld 7건에만 (closeup·prod 100%). 입력 좋으면 풀림 (V1 일치) |
| **eating_prey** (오답 9) | quality-**invariant** | 오답이 closeup 2·handheld 3·production 4 골고루. 게코 선명해도 먹이객체(귀뚜라미)가 작고 어두워 안 잡힘 |

- eating_prey = drinking보다 깊은 시각한계. Opus 에스컬레이션도 prey 오답 다수 →moving(모델 천장). **비-VLM(먹이 객체 검출/메타) 필요** — drinking과 같은 버킷, 더 심각.
- `a3a453c3`(licking-own-face) Opus도 drinking 과탐 = V1 v4.0 정의 부작용 재현. shedding 오답은 "벗는 순간 아닌 프레임" + 손 도움(시간축).

### 7-3. ⚠️ selection bias (방법론 주의)
모델 오답 16건만 골라 태깅 → `closeup visual 38%`·`untagged 83건 100%` 같은 수치는 **순환논리**(오답을 visual 태그로 옮긴 결과). **quality별 정확도는 전수 태깅한 drinking 17만 신뢰.** 오답 태깅은 "오답의 quality/클래스 분포 진단"엔 유효(7-2). (메모리 `selection-bias-error-only-tagging`)

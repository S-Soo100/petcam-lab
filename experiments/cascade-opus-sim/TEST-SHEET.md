# cascade-opus-sim 테스트 시험지 (Test Sheet)

> 규칙: [`.claude/rules/research-testing.md`](../../.claude/rules/research-testing.md). **실행 전 고정 — 사후 변경 금지.**

**실험 ID:** cascade-opus-sim · **phase:** C (캐스케이드 시뮬) · **작성일:** 2026-06-16 · **상태:** 🔒 고정(실행대기)

## 1. 가설
- **H1 (대립)**: Sonnet 기본 + 표적 라우팅(특정 클래스/저신뢰 예측만 Opus 에스컬레이션)이, 전량 Opus 대비 적은 호출 비율로 Sonnet→Opus 격차(+3.2%p = 6건/186)의 유의미한 부분을 회수한다. 그리고 같은 호출 비율의 random escalation보다 효율적이다.
- **H0 (귀무)**: 표적 라우팅이 random과 차이 없다 — 격차가 특정 클래스에 집중되지 않고 분산되어 캐스케이드가 무의미(Sonnet/Opus 택일이 합리).
- **부가 질문 (B2 스코프 결정)**: Opus 에스컬레이션이 Sonnet의 `eating_prey` 오답을 회수하는가? (opus-sonnet-186 REPORT §7-2 정성 관찰 "prey→moving 모델천장"의 정량 확인)

## 2. Sample list
- 구성: **opus-sonnet-186 전수 재사용.** N=186 (회귀셋 185 + eval-0615 1).
- 고정: `experiments/opus-sonnet-186/sample_list.json` (`id`로 join). **추가 인퍼런스 0** — 기존 blind 예측 오프라인 재집계.
- 예측 소스 (채점 SOT `_score_opus_sonnet.py`와 동일 로더):
  - Sonnet = `v40-regression/raw/v4.0_g*.json` (185) + `opus-sonnet-186/raw/sonnet0615.json` (1)
  - Opus = `opus-sonnet-186/raw/opus.json` (186)
  - conf 양쪽 186/186 완비.

## 3. 모델 / 입력 / 프롬프트
- base = **Sonnet 4.6** (85.5%, 159/186) / strong = **Opus 4.8** (88.7%, 165/186). 격차 +3.2%p = **6건**.
- 입력: 적응형 frames@1080 · 프롬프트: **v4.0** (production 후보 동치).
- ⚠️ **Fable 부재** → 기존 `_sim_cascade.py`의 R4(2-model disagree, 제3모델 strong 전제)는 186에서 성립 불가(strong 자신이 Opus). **R1/R2/R3 + random 대조만.**

## 4. 측정 지표
- 라우팅별 (escalation rate, accuracy) + 격차 회수율 = (cascade − base) / (ceil − base).
- 표적(R1/R2) vs 같은 비율 random: 정확도 차 (%p, 건).
- conf 단독(R3 sweep) 효율 — 대조군.
- 급여경계 정확도 (drinking↔eating_paste 무해 묶음) 병기.
- **eating_prey**: Sonnet 오답 건 중 Opus 회수 수/비율 + **drinking 동일 분석**(클래스 민감도 교차).
- discordant 11건(특히 Opus-only-정답 8건) 클래스 분포 — 라우팅 효율 진단.

## 5. 합격 기준 (게이트 — 숫자, 사전)
- **G1 (표적 유효)**: R1 또는 R2가 **같은 escalation rate의 random보다 raw 정확도 ≥ +1건** 우위.
- **G2 (효율)**: 표적 룰이 격차 6건 중 **≥ 3건(≥50%)을 escalation rate ≤ 40%**로 회수.
- 기준선: base 85.5% / ceiling 88.7% (opus-sonnet-186 REPORT, 채점 무결 검증됨).

## 6. 예상 비용
- **$0, <1초** (오프라인 결정론 재집계). API 호출 없음.

## 7. Decision 룰 (사전)
- **D1 캐스케이드 라우팅:**
  - `viable`: G1 **AND** G2 충족 → 표적 캐스케이드 유효, production ROI 후보(B2 후 spec화 가치).
  - `marginal`: G1만 충족 → 표적이 random보단 낫지만 격차 분산으로 회수율 낮음 → 캐스케이드 ROI 약함.
  - `not-viable`: G1 미달(격차가 클래스에 안 집중) → 캐스케이드 무의미 → Sonnet 단독(비용) or Opus 단독(정확도) 택일.
- **D2 eating_prey 버킷 (B2 스코프):**
  - Sonnet prey 오답 중 Opus 회수 **≥50%** → prey 모델 에스컬로 일부 회수 → B2 prey 비-VLM 우선순위 **중간**.
  - **<50%** → prey = **모델불변 시각한계** → B2 비-VLM **필수**(drinking 버킷, 더 심각). REPORT §7-2 정성과 일치 시 확정.
- **해석 가드**: 격차 6건·prey 오답 ~2-4건으로 **절대 건수 작음** → 정량 단독 판정 금지. discordant 11건 클래스 분포 + §7-2 정성과 교차. 방향 신호로만 사용.

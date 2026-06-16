# C 캐스케이드 시뮬 보고서 (REPORT)

**실험 ID:** cascade-opus-sim · **날짜:** 2026-06-16
**상태:** ✅ 완료 · **decision: D1 `클래스 표적=not-viable / conf 기반=viable` · D2 `eating_prey+drinking 비-VLM 필수`**
**시험지:** [`TEST-SHEET.md`](TEST-SHEET.md) (pre-reg, 합격기준 불변)
**입력:** opus-sonnet-186 재사용 (186, 적응형 frames@1080, v4.0, **인퍼런스 0**) · 스크립트 `scripts/_sim_cascade_opus.py`

---

## 1. 결과

### 라우팅별 (base Sonnet 85.5%/159 → ceiling Opus 88.7%/165, 격차 +3.2%p = **6건**)

| 라우팅 | esc율 | raw | 급여경계 | 격차회수 | random 대조 |
|---|---|---|---|---|---|
| **R1** shedding-trigger | 15% | 86.6% | 87.1% | +2/6 (33%) | **동률 (= random 28건)** |
| **R2** vuln-class {shed,drink,prey,unseen} | 31% | 87.6% | 87.6% | +4/6 (67%) | **동률 (= random 57건)** |
| **R3** conf < 0.6 | 10% | **89.2%** | 89.2% | +7/6 (117%, ceiling 초과) | — |
| **R3** conf < 0.7 | 16% | 88.7% | 88.7% | +6/6 (100%, =ceiling) | — |
| **R3** conf < 0.8~0.95 | 26~81% | 88.7% | 88.7% | +6/6 (plateau) | — |
| all → Opus | 100% | 88.7% | 88.7% | +6/6 | — |

### discordant 진단 — 격차가 클래스에 안 모임 (R1/R2 무력 이유)
- discordant 11건 = **Opus만 정답 8** / Sonnet만 정답 2 / 둘다 오답 1.
- 회수 대상 8건 GT 분포: **moving 3 · eating_prey 2 · eating_paste 1 · drinking 1 · unseen 1** = 5개 클래스 분산.
- → P4(202·v3.6.1)의 단일 실패모드(Sonnet IR 야간 shedding 과탐)가 **v4.0엔 없음**(shedding 26/26 동률). 클래스 트리거가 잡을 표적이 없어 random과 동률.

### conf 분포 (conf 라우팅이 먹히는 메커니즘)
- Sonnet **정답 159건 conf 중앙 0.88** vs **오답 27건 conf 중앙 0.70** — 오답이 저신뢰에 몰림.
- conf<0.6: 오답 44%(12/27) 포함하면서 정답은 4%(6/159)만 낭비 → Sonnet conf가 자기 오답을 calibrate.
- 클래스 라우팅이 못 잡는 "GT를 moving으로 놓친 오답"도 conf는 예측 클래스 무관하게 포착 → 회수율 우위.

## 2. 시험지 대비
- **변경 없음.** G1/G2/D1/D2 게이트 사전 그대로 적용.
- ⚠️ conf(R3)는 시험지에서 "대조군"으로 분류했으나 실측이 표적(R1/R2)을 능가 — **게이트 사후변경 아님**(§4 측정지표에 명시된 conf 결과를 그대로 보고, D1 게이트는 "표적>random"으로 불변 적용).

## 3. 가설 판정
- **H1(표적>random) 기각 / H0(격차 분산→클래스 캐스케이드 무의미) 채택.** R1/R2가 같은 비율 random과 동률 → G1 미달.
- **단 conf-threshold는 H1을 강하게 지지** (사전 대조군이 표적을 뒤집음). "캐스케이드 자체"는 유효하되 라우팅 신호가 클래스가 아니라 conf.
- **P4 정반대 확인**: P4는 표적(클래스)>>conf(2.3배 비효율). C(186·v4.0)는 conf>표적=random. **원인 = Sonnet 오답 성격 변화** — P4의 고신뢰 IR 과탐(conf로 못 잡음)이 v4.0엔 없고, 남은 잔여 오답이 저신뢰 모호 케이스라 conf로 잡힘.

## 4. Decision
- **D1 = `클래스 표적 not-viable / conf 기반 viable`**
  - 클래스 라우팅(R1/R2): G1 미달 → **기각**. v4.0 격차는 클래스에 안 집중.
  - conf 라우팅: **conf<0.7로 16% Opus 호출 = ceiling(88.7%) 100% 회수.** production 캐스케이드 후보 = **"Sonnet 기본 + conf<0.7만 Opus 재호출"** → Opus 호출 ~16%로 Opus 단독 정확도 달성(비용 trade-off 대폭 완화). 단 §5 재현 가드.
- **D2 = `eating_prey + drinking 비-VLM 필수`** (B2 스코프 확정)
  - **eating_prey**: Sonnet 오답 9건 중 Opus 회수 **2건(22%)** — 7건 →moving 유지.
  - **drinking**: Sonnet 오답 5건 중 Opus 회수 **1건(20%)** — 4건 →moving 유지.
  - 둘 다 <50% → **모델 에스컬로 회수 불가 = 모델불변 시각한계** (REPORT §7-2 정성과 정확히 일치). **B2 = drinking + eating_prey 둘 다 비-VLM 버킷** (prey가 더 심각 — 먹이객체가 작고 어두워 게코 선명해도 안 잡힘).

## 5. 한계 / 노이즈
- **소표본**: 격차 6건 · prey 오답 9 · drinking 오답 5 = 절대 건수 작음. temperature 비제어 → conf<0.6의 117%(ceiling 초과)는 Sonnet-정답 1건 보존 효과라 노이즈 가능. 단 conf<0.7~0.95 전 구간 100% plateau → "저신뢰 에스컬레이션" 방향은 견고.
- ⚠️ **`donts/vlm.md` "confidence-abstain 무용"(Gemini Flash 기준)과 표면 긴장**: 본 결과는 (a) Gemini≠Sonnet 모델 특이성 (b) abstain(기권) 아닌 **escalation(강모델 재호출)** — 실패모드 다름. **production 적용 전 더 큰 표본 + temperature 0 재현 필수.**
- 자기 채점(deterministic 코드)이라 무결. LLM audit은 인퍼런스 0(GT 기반 재집계)이라 불필요.

## 6. 다음 액션
- 🥇 **B2 비-VLM spec** (다음 작업): D2 확정 → `feature-rba-evidence-based-feeding-drinking.md`에 **eating_prey 섹션 추가**(먹이객체 검출 → hand_feeding 구분). drinking 스코프 유지, 같은 버킷.
- (production 트랙, 별도) **conf<0.7 캐스케이드** = Opus 정확도를 ~16% Opus 호출로. 단 §5 재현 가드(큰 표본·temperature 0) 통과 후 spec화.
- (선택) discordant 11건 사람 영상 review → GT-noise + Opus/Sonnet 강약 정성.

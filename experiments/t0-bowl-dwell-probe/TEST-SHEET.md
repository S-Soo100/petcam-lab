# TEST-SHEET — T0 Bowl-Dwell Probe (사전등록, 승인 후 변경 금지)

**작성:** 2026-07-20 · **승인:** (사용자 승인 시각 기입) · **상태:** 사전등록

## 1. 가설
- **H0 (귀무):** 그릇 셀 체류 상위 클립군의 케어행동(eating+drinking) 비율은 무작위 클립군과 다르지 않다 (체류 신호는 케어행동을 농축하지 못한다).
- **H1 (대립):** 그릇 셀 체류 상위 클립군은 무작위 대비 케어행동이 유의하게 농축된다.

## 2. Sample list
- **Eligible pool:** `clip_python_evidence_runs` 중 `level0_status='ok' AND level1_status='ok'` AND `spatial_dwell.observed_sec >= 5` AND `spatial_dwell.n_observations >= 3` (sparse 1~2 관찰 dwell은 노이즈). clip당 최신 run 1건.
- **Top군 60:** `bowl_dwell_sec = Σ(bowl 셀 비율) × observed_sec` 내림차순 상위 60.
- **Random 대조군 20:** top 60 제외 eligible에서 seed=20260720 무작위 20.
- 재현: `scripts/t0_bowl_dwell_rank.py` + `key/assignment_key.json`.

## 3. 모델/입력표현/프롬프트
- 해당 없음 (비-VLM). 판정자 = 사람(owner) blind 육안.

## 4. 측정 지표
- 그룹별 care precision = (eating+drinking 판정 수) / (판정 가능 수, unsure 제외)
- 보조: licking_surface / near_bowl_no_care / elsewhere / absent 분포, 카메라별 분포

## 5. 합격 기준 (숫자, 사후 변경 금지)
- **adopt** (가설 생존, T2 GT 엔진 투자 정당): top60 케어 ≥ 6건 (≥10%) **AND** top군 케어율 > random군 케어율
- **reject** (체류 단독 신호 무효): top60 케어 ≤ 2건 (base rate과 구분 불가)
- **hold**: 그 사이 (3~5건) — 표본 확대 또는 feature 조합(주기성 결합) 재설계 후 재시험
- ⚠️ 채점은 top/random 판정 **전부 완료 후 1회만** 실행 (중간 채점으로 기준 조정 금지)

## 6. 예상 비용/토큰
- LLM 0. R2 GET ~80건(~2.5GB), 사람 판정 ~80클립 × 15초 ≈ 20~30분.

## 7. Decision 룰
- adopt → T2(GT 엔진: 라벨링 pilot + fresh camera-night) 착수, T3 룰 검증은 hard negative(near_bowl_no_care) 포함 사전등록
- reject → 체류-단독 가설 폐기. 다음 후보: 주기성(periodicity_summary) 결합 재시험 / 캡처·사육환경 조정 / head detector 확보 후 재설계
- hold → 위 hold 조치 후 새 TEST-SHEET

## 8. 알려진 한계 (해석 시 주의)
- 4×4 셀(320×240px)은 그릇보다 큼 → precision 상한이 구조적으로 낮을 수 있음. reject 판정은 "체류-단독" 기각이지 "evidence 전체" 기각이 아님.
- eligible pool은 모션트리거 캡처의 부분집합(3일치) → 발생률(base rate) 추정은 참고치.
- 판정자 1인(owner) — inter-rater 없음. unsure 적극 사용으로 보완.

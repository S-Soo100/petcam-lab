# t1-highlight-selection 테스트 보고서 (Report)

> 규칙: [`.claude/rules/research-testing.md`](../../.claude/rules/research-testing.md).

**실험 ID:** t1-highlight-selection · **phase:** T1 (하이라이트 선별 probe) · **날짜:** 2026-07-21 · **상태:** ✅ 실행 완료 · **decision: `reject`**
**시험지:** [`TEST-SHEET.md`](TEST-SHEET.md) (🔒 2026-07-21 동결) · **발주:** `docs/decision-gate.md` 2026-07-21 P3

## 1. 무엇을 측정했나 (시험지 요약)

| 항목 | 내용 |
|---|---|
| 가설 | H1: DB-only 합성점수(존재+활동+주기성 백분위 평균, 버킷 캡 4) top20은 무작위 20 대비 informative 비율이 유의하게 높다 |
| 풀 | eligible 1,390 (T0 판정 80 제외, 3카메라) |
| 판정자 | 사람(owner) blind 육안 40건, 5종 verdict, LLM 0회 |
| 게이트 §5 | adopt: Δ≥+20%p AND S informative≥8 / hold: Δ+10~20%p 또는 S 5~7 / reject: Δ<+10%p 또는 S≤4 |

## 2. 결과

채점 `scripts/t1_score_probe.py` (pytest 7/7 PASS: 랭킹 5 + 채점 2). 채점 1회. **시험지 대비 사후 변경 없음.**

| 그룹 | n | judged | informative | rate | care | absent | verdict 분포 |
|---|---|---|---|---|---|---|---|
| **S (score)** | 20 | 20 | **10** | **50%** | 0 | **6 (30%)** | other 10 · not_inf 4 · absent 6 |
| **R (random)** | 20 | 20 | **9** | **45%** | 0 | 2 (10%) | other 9 · not_inf 9 · absent 2 |

격차 **+5.0%p** (< 게이트 +10%p). S 버킷 커버리지 10개. **§5 안전 점검 발동: S absent 30% > 10% → 존재 성분 실패 기록 의무.**

## 3. 분석 (전수 40건 verdict별 성분 분포 — 오답-전용 태깅 아님, selection bias 무관)

| verdict | n | observed_sec(med) | roi_mean(med) | peak_autocorr(med) | score(med) |
|---|---|---|---|---|---|
| absent | 8 | **67.6 (최고)** | 0.70 | **0.797 (최고)** | **0.775 (최고)** |
| informative_other | 19 | 67.0 | 0.63 | 0.711 | 0.755 |
| not_informative | 13 | 60.7 | 0.68 | 0.484 | 0.526 |

- **핵심 실패 원인 — detector 오검출이 "존재"와 "주기성"을 동시에 오염.** absent 클립이 세 성분 중 두 개에서 최상위: 게코가 없는데 observed_sec가 클립 전체(~67초)이고 autocorr 0.8의 주기 모션. S-absent 6건 중 5건이 **P4 Cam 2(dev) 동일 시그니처**(관찰 65~69s·autocorr 0.78~0.85·roi_mean ~0.7) = 특정 장면 요소(식물/그림자/IR 반사 추정)가 **상시 게코로 오검출**되는 카메라 고유 오염원.
- **T0 "존재 신호 유효"와의 정합:** T0 bowl-dwell 랭킹은 그릇 셀 한정 + Cam 2 제외(그릇 없음)라 이 오염원이 표본에 못 들어왔다. 존재 신호의 유효성은 **카메라 의존적**이며 일반화가 이번에 깨졌다. detector v2 specificity 40% 문제(absent 분리 조사)의 세 번째 실증.
- **카메라별 격차 (judged 40):** Cam 3 = absent 0/12·informative 8/12 (점수식이 잘 작동) vs Cam 2 = absent 7/16. 점수식 자체보다 **카메라별 오염 편차**가 지배 변수.
- peak_autocorr는 informative(0.711) vs not_informative(0.484)를 가르는 분리력이 있으나, absent(0.797)가 그 위에 있어 **단독/현행 결합으로는 못 씀**.
- **care 0/40** — 풀의 케어행동 base rate 자체가 낮아 이 표본 크기로는 케어 농축을 측정 불가. 주지표(informative 통합)로만 판정.

## 4. 가설 판정 & Decision: `reject`

- **H0 유지 (H1 기각).** §5 기계 적용: Δ+5.0%p < +10%p → **reject**. 합성점수 v1(균등가중 3성분)은 무작위 대비 뽑기 개선 없음.
- reject 범위: **이 점수식 v1**의 기각이지 "DB-only 선별 불가"의 기각 아님 — §3 진단이 개선 방향을 특정함(오염원 억제).

## 5. 한계

- n=20/그룹 소표본 — informative 1건 = 5%p. R base rate 45%는 T0 예상(낮음)과 크게 다름(T0 random은 2카메라·이전 기간).
- Cam 2 오염 5건이 S 슬롯 25%를 점유 — 오염 제거 시 점수식의 진짜 성능은 미지(사후 재계산은 게이트 위반이므로 안 함, 새 시험지 사안).
- 판정자 1인(owner), unsure 0.

## 6. 다음 액션 (§7 decision 룰: reject 경로)

1. **점수식 v1 폐기.** 균등가중 3성분은 detector 오염에 취약.
2. **v2 후보 (새 시험지 + decision-gate 통과 필수):** ① "한 셀 고정 + 클립 전체 관찰 + 고주기" 시그니처 페널티(상시 오검출 억제 — T0 absent 조사에서 dwell_max_cell이 유일하게 2/13 잡은 것과 합류) ② 카메라별 정규화/쿼터 ③ Gate prelabel(`gecko_visible`) 결합.
3. **gate 레포 피드백에 Cam 2 상시 오검출 소스 추가** (decision-gate record #1 "약한 통과" 항목과 합류 — prelabel 품질 목적).
4. **GT 적립:** blind 판정 40건 확보 (T0 80 + T1 40 = 누적 120건, RBA Data Engine v1 방향).

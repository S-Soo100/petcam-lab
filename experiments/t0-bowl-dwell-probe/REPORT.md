# T0 Bowl-Dwell Probe 테스트 보고서 (Report)

> 규칙: [`.claude/rules/research-testing.md`](../../.claude/rules/research-testing.md).

**실험 ID:** t0-bowl-dwell-probe · **phase:** T0 (가설 선검증) · **날짜:** 2026-07-21 · **상태:** ✅ 실행 완료 · **decision: `reject`**
**시험지:** [`TEST-SHEET.md`](TEST-SHEET.md) · **계획서:** `docs/superpowers/plans/2026-07-20-t0-bowl-dwell-probe.md`

## 1. 무엇을 측정했나 (시험지 요약)

| 항목 | 내용 |
|---|---|
| 가설 | H1: 그릇 셀 체류 상위 클립군은 무작위 대비 케어행동(eating+drinking)이 유의하게 농축된다 |
| 샘플 | eligible 1,031 (level0/1=ok/ok, observed_sec≥5, n_obs≥3, clip당 최신 run) → top60(bowl_dwell_sec 내림차순) + random20 |
| 판정자 | 사람(owner) blind 육안, 7종 verdict, LLM 0회 |
| 기준선 | random 대조군의 케어율 |
| 합격기준 §5 | adopt: top 케어 ≥6 AND top율>random율 / reject: top 케어 ≤2 / hold: 3~5 |

그릇 셀 지정(owner): P4 Cam (dev) `r2c1+r1c1`(물그릇 정수기), P4 Cam 3 `r1c2`(물그릇), P4 Cam 2(dev) 없음(제외). → **사실상 물그릇(drinking) 신호를 검증**한 실험.

## 2. 결과

- 배치: R2 GET 80건, LLM 0. 채점 `scripts/t0_score_probe.py` (pytest 5/5 PASS). 채점 1회 실행.

| 그룹 | n | judged (unsure 제외) | **care_count** | care_rate | verdict 분포 |
|---|---|---|---|---|---|
| **top60** | 60 | 59 | **0** | 0.0 | elsewhere 37 · **near_bowl_no_care 20** · absent 2 · unsure 1 |
| **random20** | 20 | 20 | **0** | 0.0 | absent 11 · elsewhere 8 · near_bowl_no_care 1 |

보조 지표:

| | top60 | random20 |
|---|---|---|
| bowl_dwell_sec (min~max, median) | 30.6 ~ 68.0, **34.3** | 0.0 ~ 11.2, **0.0** |
| 카메라 분포 | P4 Cam (dev) 55 · P4 Cam 3 5 | P4 Cam (dev) 10 · P4 Cam 3 10 |
| near_bowl_no_care 카메라별 | Cam (dev) 18 · Cam 3 2 | Cam 3 1 |

## 3. 분석

- **가설 판정: H0 유지 (H1 기각).** 두 그룹 모두 케어행동 0건 → 체류 상위군이 케어행동을 농축했다는 증거 없음.
- **핵심 발견 — 체류 신호는 "존재"는 잡지만 "행동"은 못 잡는다.** top60은 실제로 그릇 셀에 오래 머문 클립을 정확히 선별했다 (dwell median 34.3s vs random 0.0s, absent 3% vs random 55%). 그런데 그 59건 판정 가능 클립 중 **eating/drinking = 0, near_bowl_no_care = 20 (34%)**. 즉 "게코가 물그릇 근처에 오래 있음 ≠ 물을 마심"이 정량으로 확인됨.
- 이것은 production VLM 오탐의 원인(confabulation: "그릇 근처 이동 → 먹는다고 근거 지어냄")과 **정확히 같은 실패 모드**를, 이번엔 비-VLM 시간축 신호에서도 재현한 것. 체류만으로는 VLM과 같은 함정에 빠진다.
- top60 92%가 P4 Cam (dev)(물그릇 정수기) → 이 실험은 주로 **drinking 신호**를 본 것. eating은 owner가 "밥그릇은 다른 날 배치"라 프레임에 없어 이번 표본에서 구조적으로 미검증.

## 4. Decision: `reject` (체류-단독 신호 무효)

- TEST-SHEET §5 기계 적용: top60 care_count = 0 ≤ 2 → **reject**. 사후 변경 없음.
- 단, §8 한계대로 이 reject는 **"체류-단독"** 기각이지 "evidence 전체" 기각이 아니다. 체류는 "그릇 근처 존재"를 잘 잡으므로 **다른 신호와 결합하는 feature로는 여전히 유효**할 수 있다 (예: 주기성·머리 방향·미세 움직임).

## 5. 한계

- **4×4 셀(320×240px)이 물그릇보다 훨씬 큼** — coarse. 그릇 셀 dwell이 실제로는 "그릇 옆 넓은 영역 체류"를 의미. 정밀 ROI/head detector면 결과가 달라질 여지.
- **eating 미검증** — 밥그릇 부재로 top군이 물그릇(drinking)에 편중. eating 신호 결론은 이 실험 범위 밖.
- **판정자 1인(owner), inter-rater 없음.** unsure는 1건뿐이라 억지 판정 우려는 낮음.
- eligible = 3일치 모션트리거 캡처 부분집합 → 발생률(base rate) 참고치.

## 6. 다음 액션 (TEST-SHEET §7 decision 룰)

reject 경로:
1. **체류-단독 가설 폐기.** VLM이든 dwell이든 "그릇 근처 = 케어"라는 단일 근접 신호는 못 씀 (확정).
2. **다음 후보 (체류를 버리지 말고 결합):**
   - 주기성(`periodicity_summary`) 결합 재시험 — "그릇 근처에서 **반복적** 머리 움직임"
   - head/tongue detector 확보 후 재설계 (근접 아닌 실제 접촉 신호)
   - 캡처·사육환경 조정 (밥그릇 포함 fresh camera-night)
3. **T3 설계 입력값 — hard negative 확보됨:** near_bowl_no_care = 21건(top 20 + random 1). T3 evidence 룰 검증 시 이 hard negative를 반드시 포함해 "근접=케어" 재발 방지 (selection bias 회피).
4. **T2 GT 엔진**은 이 reject와 무관하게 pilot 시작 가능(계획서 후속 로드맵). 단, 순서 결함 지적(가장 비싼 투자를 가설 검증 뒤로)이 이 T0로 해소됨 — **체류-단독에는 투자하지 않는다**가 확정된 게 T0의 성과.

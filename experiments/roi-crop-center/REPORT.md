# roi-crop-center 테스트 보고서 (Report)

> 규칙: [`.claude/rules/research-testing.md`](../../.claude/rules/research-testing.md).

**실험 ID:** roi-crop-center · **phase:** C1 (frame-side 마지막 레버 1차) · **날짜:** 2026-06-16 · **상태:** ✅ 실행 완료 · **decision: `close`**
**시험지:** [`TEST-SHEET.md`](TEST-SHEET.md) (pre-reg, 합격기준 사후변경 없음) · **스펙:** [`specs/experiment-hierarchical-zoom-roi-crop.md`](../../specs/experiment-hierarchical-zoom-roi-crop.md)
**입력:** center ROI crop @1080 (원본 기반, min(짧은변,1080) 정사각, 시간밀도 통제) · **모델:** Claude Sonnet 4.6 blind · **N=56** (drinking 17 / eating_paste 17 / eating_prey 22)
**배치:** Agent 7명 blind (8건씩) + eval-0615 baseline 2건 Agent 1명 / Sonnet / 누락 0

---

## 1. 무엇을 측정했나 (시험지 요약)
급여 3종 전수 56건에 **center ROI crop**(원본에서 잘라 1080 할당, 시간밀도는 적응형과 동일 통제 = crop만 변수) → Sonnet v4.0 blind. baseline = 같은 56건 **적응형@1080** v4.0 (v40-regression 재활용 54 + eval-0615 신규 2). 게이트: paired recovered − broken ≥ +3 = adopt / ≤ 0 = close.

## 2. 결과

| 지표 | baseline(적응형@1080) | center crop | Δ |
|---|---|---|---|
| 급여경계 정확도 (N=56) | 40/56 = 71.4% | 40/56 = **71.4%** | **+0.0%p** |
| paired recovered / broken | — | **2 / 2** | 순 **+0** |

- **paired 상세:** recovered = `sample-08`(prey, moving→prey, 짧은변 476)·`sample-39`(prey, drinking→prey, 720) / broken = `sample-05`(drinking, drinking→moving, 382)·`sample-56`(prey, prey→moving, 466).
- **원본 해상도 층화 (보조):** **4K급(≥1440) 10건 → recovered 0 / broken 0 (순 0)** · 그외 46건 → recovered 2 / broken 2 (순 0).
- 클래스별 급여경계 정답: eating_prey 13→14 · eating_paste 15→15 · drinking 12→11.
- 채점: `scripts/_score_roi_crop.py` (boundary_correct = _score_v40 동형).

## 3. 분석

- **가설 판정: H1(frame-side 헤드룸 잔존) 기각 → H0(효과 없음) 채택.** 순효과 +0, 정확도 Δ +0.0%p.
- **결정적 — 모든 변동이 저해상(<720), 4K급은 완전 무변화.** crop의 작동 원리는 "고해상 원본의 다운스케일 손실을 회피해 공간해상도↑". 그게 작동했다면 **4K급에서 recovered가 나와야 하는데 4K급 순 0.** 변동 4건(rec 2/brk 2)은 전부 저해상에서 발생 = 긴변 크롭으로 배경이 빠진 프레이밍 noise(공간해상도 효과 아님). **crop 가설과 정반대 분포.**
- **데이터가 1차 병목:** 56건 중 4K급 10건뿐, **prey는 22건 중 1건(짧은변 중앙값 476)**. 미세접촉 클래스 영상이 대부분 저해상이라 crop으로 키울 원본 디테일이 애초에 없다. "게코는 선명한데 먹이가 작다"의 그 "선명"이 476px였던 것.
- **akze3466 noise 재확인:** V1에서 적응형 drinking 0.82였던 clean closeup이 이번 적응형 blind에선 moving 0.72 — temperature 노이즈로 clean 샘플도 drinking↔moving 흔들림.

## 4. Decision: `close`

1. 게이트 close 충족: recovered − broken = 0 (≤ 0) **AND** 4K급 recovered>broken 신호 없음(순 0, §7 해석가드의 hold 탈출 조건 불충족).
2. 급여경계 정확도 완전 동등(71.4%), crop 이득 0.
3. **frame-side 입력 레버 완전 종료 확정** — V1(풀프레임→1080 다운스케일 천장) + 본 실험(원본 ROI-local 확대 천장) = 정지프레임 VLM 입력의 마지막 카드까지 소진. 학습노트 §6 표 "계층 줌인 + ROI crop" 칸 = ❌.
4. drinking/eating_paste/eating_prey 미세접촉은 입력·프롬프트·모델·ROI crop **네 레버 다 천장** → **RBA 비-VLM evidence layer가 유일한 길**(`feature-rba-evidence-based-feeding-drinking.md` §4.5/§6.5: 메타 + motion 시퀀스 + HITL, 객체검출은 fuzzy 보너스).

## 5. 한계

- **소표본:** 56건(클래스별 17/17/22), 4K급은 10건뿐 → 4K급 순 0의 통계력 약함. 단 방향(저해상에만 noise·고해상 0)은 crop 가설과 정반대라 견고.
- **center crop = 게코 위치 무시** — 게코가 가장자리면 crop이 게코를 자를 수 있음(broken 노이즈원). 단 결과상 broken도 저해상이라 "게코 잘림"보다 noise. **정밀 ROI crop(게코 입 bbox)은 미측정** — 단, 4K급 center crop이 이미 1080² 풀디테일을 줬는데 순 0이라 정밀 crop 헤드룸도 낮음.
- **temperature 노이즈 ±1** — 순 0이 ±1 변동 범위. 단 "효과 큼"을 보이려면 +방향이어야 하는데 0.
- 단일 모델(Sonnet). C/D2가 Opus까지 봤으니 모델불변 보조 근거.

## 6. 다음 액션

- **frame-side 트랙 종료.** 입력표현 연구(몽타주 v2 → frames@1080 → ROI crop)는 본 실험으로 완결.
- **RBA 비-VLM evidence layer로 이동** — `feature-rba-evidence-based-feeding-drinking.md` 가 drinking/paste/prey의 유일한 길. 다음 트랙 후보(사용자 트리거): 미스팅/먹이투입 메타 타임스탬프 매칭, prey stalk→lunge→snap motion 시퀀스(§6.5), HITL.
- (보조) eval-0615 2건 등 신규 영상은 적응형 baseline 측정해 회귀셋 편입 검토.

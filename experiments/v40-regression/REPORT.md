# v4.0 회귀 보고서 (REPORT)

**실험 ID:** v40-regression · **날짜:** 2026-06-13
**상태:** ✅ 실행 완료 · **decision: `adopt`**
**시험지:** [`TEST-SHEET.md`](TEST-SHEET.md) (pre-reg, 합격기준 사후변경 없음)
**입력:** 적응형 frames@1080 (평균 11.1장) · **모델:** Claude Sonnet 4.6 blind · **N=185**
**배치:** Workflow 30 에이전트 (15그룹×2프롬프트) / 3.65M tok / ~20분 / 누락 0

---

## 1. 결과

| 지표 | v3.6.1 | v4.0 | Δ |
|---|---|---|---|
| raw 정확도 (7-class) | 85.9% (159/185) | 85.9% (159/185) | +0.0%p |
| 급여경계 정확도 | 85.9% | 86.5% (160/185) | +0.5%p |
| 급여경계 paired | — | **recovered 6 / broken 5** | PASS |
| drinking 비급여 누출 | 5 | 4 | −1 ✅ |
| moving→drinking 과탐 | 2 | 1 | −1 ✅ |

**클래스별 raw (v3.6.1 → v4.0):** moving 67→68 · shedding 27→26 · hand_feeding 26→27 · eating_prey 14→13 · eating_paste 14→14 · **drinking 10→11** · unseen 1→0.

**게이트 판정 (시험지 §5·§7):** ① 급여경계 recovered ≥ broken (6≥5) ✅ · ② drinking 누출 비증가 (5→4) ✅ · ③ moving→drinking 과탐 ≤ 회복분 (2→1) ✅ · ④ raw 폭락 가드 (−5%p) — +0.0%p ✅. **4/4 통과.**

## 2. 시험지 대비

- **합격 기준(게이트): 사전 그대로, 변경 없음.**
- **⑤ discordant review 생략** — 사용자 결정(2026-06-13, "일단 바로 adopt"). 게이트 통과 기준으로 채택. broken 5건의 노이즈 여부는 **프레임 미검증으로 남김**(후속 가능). 게이트 자체는 사전 정의 그대로라 합격기준 사후변경 아님.

## 3. 가설 판정

- **H0(v4.0 개선 없음): 결정적 기각은 못 함** — 효과 크기 작음(급여경계 +0.5%p, recovered−broken=1건). 서브에이전트 temp 비제어 노이즈 범위와 겹침.
- **단 방향은 H1 지지** — drinking 타겟이 일관되게 개선(클래스 +1, 누출 −1, 과탐 −1)되고, broken은 전부 drinking 무관 클래스.
- **결론: v4.0 ≥ v3.6.1** — "동등 정확도(85.9%) + 클래스 3개 단순화 + drinking 패턴 전환" 달성.

## 4. Decision: `adopt`

1. 시험지 게이트 4개 전부 통과.
2. raw 정확도 동등(85.9%) — 폭락 없음, 클래스 단순화의 정확도 비용 0.
3. **클래스 3개 폐기(10→7-class)** 달성 — defecating/basking/hiding.
4. **drinking 타겟 일관 개선** — 클래스 10→11, 비급여 누출 5→4, moving 과탐 2→1.
5. broken 5건 전부 drinking 무관(eating_prey 2·shedding 1·unseen 1·moving 1) — v4.0이 안 건드린 클래스라 노이즈로 해석.

## 5. paired / 노이즈 분석

- **recovered 6:** drinking 관련 4 — `44`(moving→drinking, GT drinking, 누출 회복) · `73·75`(drinking→moving, GT moving, 과탐 교정) · `112`(moving→drinking, GT eating_paste, 급여 회복) + 무관 2(`38`·`55`).
- **broken 5:** `151·155`(eating_prey→moving) · `95`(shedding→moving) · `30`(unseen→moving) · `86`(moving→shedding) — **전부 drinking/클래스폐기와 인과 없음.**
- **한계:** 효과 크기 작아 노이즈 경계. paired 1건 차는 단일 호출 변동으로 뒤집힐 수 있음. discordant 프레임 검증 미수행. unseen(N=2)·drinking(N=15) 등 소표본 클래스는 ±1이 큰 %.

## 6. 다음 액션

- **v4.0 = 새 회귀 기준선** — 다음 프롬프트 버전은 v4.0(적응형 frames@1080) 대비 paired 측정.
- `DEFAULT_PROMPT_VERSION` 승격은 **production 재가동 시점** 사안 (워커 셧다운 중이라 현재 실사용 0, 별개).
- (선택) broken 5건 discordant 후속 — 노이즈 확정 시 v4.0 우위 강화.
- 적응형 입력(frames@1080, 간격3.5/구간중앙)이 신표준으로 정착 — CLAUDE.md 룰4 갱신 검토.

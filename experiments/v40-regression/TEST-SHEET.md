# v4.0 회귀 시험지 (TEST-SHEET) — pre-registration

**실험 ID:** v40-regression
**날짜:** 2026-06-13 · **상태:** pre-reg (실행 전 고정, **합격기준 사후변경 금지**)
**규칙:** [`.claude/rules/research-testing.md`](../../.claude/rules/research-testing.md) · 무결성 6단계: [`specs/experiment-claude-montage-v2.md`](../../specs/experiment-claude-montage-v2.md) §4-3a
**프롬프트 버전격리:** [`CLAUDE.md`](../../CLAUDE.md) 룰 1~4

---

## 0. 배경 (왜 이 테스트인가)

- **피벗:** Gemini 퇴역 → Claude Sonnet 트랙. Gemini 85.5% floor는 클래스 체계가 바뀌어 무효 — **이 회귀가 새 기준선을 수립**.
- **v4.0 변경 2종:** ① 클래스 폐기 defecating/basking/hiding → 7-class. ② drinking 재정의 "물 보임(시각증거)" → "몸 고정 + 머리 반복·집중 핥기(행동패턴)".
- **입력 신표준:** 적응형 frames@1080 (고정10 P1은 0~45초만 보는 slice 버그 + t=0 함정 → 폐기). 적응형이 변수가 되지 않게 v3.6.1·v4.0 **둘 다 같은 적응형 입력** 위에서 비교 (프롬프트 1변수 격리).

## 1. 가설

- **H0 (귀무):** v4.0은 v3.6.1 대비 급여경계 기준 개선 없음 (drinking 비급여 누출 감소 없음 / 또는 퇴행).
- **H1 (대립):** v4.0이 drinking 비급여 누출(→moving 등)을 줄이고 폐기클래스 오분류를 제거해 급여경계 기준 정확도가 개선된다.

## 2. Sample (고정)

- **185건** = `storage/dataset-203/manifest.csv` 전체 (defecating 16 + cf698b78 제외 후).
- **GT 분포:** moving 72 / shedding 29 / hand_feeding 28 / eating_prey 22 / eating_paste 17 / drinking 15 / unseen 2. 폐기클래스 잔존 0.
- **재현:** manifest.csv 가 곧 sample list (전체라 별도 추출 불필요).
- **blind:** `sample-NN/` 중립 폴더명 + GT는 `meta.json` 에만 + seed 42 셔플. 인퍼런스 에이전트는 GT·파일명·예측이력 못 봄.

## 3. 모델 / 입력 / 프롬프트

| 축 | 값 |
|---|---|
| 모델 | **Claude Sonnet 4.6** (production 목표) · blind · 구독 서브에이전트 |
| 입력 | 적응형 frames@1080 (간격 3.5s / 하한 6 / 상한 20 / **구간중앙 위치** / no-upscale) · 평균 11.1장 · v3.6.1·v4.0 **공통** |
| 프롬프트 | **v3.6.1** (기준선) vs **v4.0** — 단일 변수 |
| 결정론 | 서브에이전트 temperature 비제어 → **paired(recovered/broken)로 흡수**. 20건 ±1 노이즈 존재 |

> 프레임은 185건 1회 추출 → 두 프롬프트로 각각 분류 (입력 동일성 보장).

## 4. 측정 지표

1. **raw 정확도 (7-class, 엄격)** — 정직 보고용. drinking↔eating_paste 혼동도 여기선 오답으로 카운트.
2. **클래스별 정확도 + 혼동행렬** — 전체 오답 방향.
3. **급여경계 paired (게이트용)** — recovered/broken 을 아래 4칸으로 라벨링:
   - drinking/eating_paste ↔ **비급여**(moving/unseen/shedding/eating_prey) 경계를 넘으면 → **진짜** recovered/broken
   - drinking ↔ eating_paste **내부 이동** → **무해**(카운트 제외, 별도 표기)
4. **drinking 비급여 누출** — drinking GT 15건 중 moving/unseen/shedding 등으로 샌 수 (v3.6.1 vs v4.0).
5. **moving→drinking 과탐** — moving GT 가 drinking 으로 잘못 끌려온 수 (비급여→급여, 진짜 과탐).
6. **토큰** — 적응형 평균 11.1장 기준.

## 5. 합격 기준 (숫자 · 급여경계 기준)

> 사용자 결정(2026-06-13): **급여 내부(drinking↔eating_paste) 양방향 혼동은 완전 무해.** 비급여 경계 누출만 게이트. merge 합성 정확도는 만들지 않음 — raw 는 정직 보고, 게이트는 급여경계 paired 로.

- **주 게이트:** 급여경계 **recovered ≥ broken** (급여내부 이동 제외).
- **목표 지표:** drinking 비급여 누출 v3.6.1 대비 **비증가**(이상적으로 감소).
- **과탐 가드:** moving→drinking 신규 과탐 ≤ drinking 비급여 회복분.
- **폭락 가드:** raw 정확도(7-class)가 v3.6.1 대비 **−5%p 초과 폭락하면 hold** — "모델이 drinking/paste 구분을 아예 포기"한 신호.

## 6. 예상 비용 / 토큰

- 적응형 ~2,049장/배치 × 2배치 = ~4,100장 · ~**4.5M input 토큰** (장당 ~1,100 @1080).
- 구독 서브에이전트라 직접 과금 X — 토큰 규모는 배치 부하 참고용.

## 7. Decision 룰 (사전 명시)

| label | 조건 |
|---|---|
| **adopt** | 급여경계 recovered ≥ broken **AND** drinking 비급여 누출 비증가 **AND** moving→drinking 과탐 ≤ 회복분 **AND** raw 폭락 없음 |
| **reject** | 급여경계 broken > recovered **OR** raw −5%p 초과 폭락 |
| **hold** | 위 사이 애매 영역 → **사용자가 혼동행렬 직접 검토 후 판단** ("v4.0 발전시켜 나가며 판단") |

## 무결성 6단계 (§4-3a)

`① pre-reg(이 문서)` → `② blind 인퍼런스(Sonnet, sample-NN)` → `③ deterministic scorer(GT 대조 + 급여경계 라벨링)` → `④ LLM audit(불일치 케이스 교차)` → `⑤ discordant review(v3.6.1↔v4.0 갈린 건 육안)` → `⑥ decision(REPORT.md)`

---
**다음:** 프레임 추출(185, 1회) → blind 배치 v3.6.1 → v4.0 (Sonnet) → 채점 → REPORT.md. **배치 직전 사용자 재확인.**

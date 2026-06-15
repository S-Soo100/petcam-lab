# Opus vs Sonnet 정확도 (186) 시험지 (TEST-SHEET) — pre-registration

**실험 ID:** opus-sonnet-186
**날짜:** 2026-06-15 · **상태:** pre-reg (실행 전 고정, **합격기준 사후변경 금지**)
**규칙:** [`.claude/rules/research-testing.md`](../../.claude/rules/research-testing.md) · 무결성 6단계: [`specs/experiment-claude-montage-v2.md`](../../specs/experiment-claude-montage-v2.md) §4-3a

---

## 0. 배경 (왜 이 테스트인가)

- **목적:** 현재 데이터셋(186)을 **production 후보 두 모델**(Opus 4.8 · Sonnet 4.6)로 적응형@1080 v4.0 blind 측정 → 정확도 baseline 확보 + 모델 선택 근거.
- **선행:** P1(frames-10 고정 + v3.6.1)에서 **Opus 81.2% > Sonnet 78.2%**(Opus +3%p). 단 그건 다른 입력(고정10)·프롬프트(v3.6.1). 적응형@1080 v4.0 Sonnet은 v40-regression에서 **85.9%(185)**. **Opus의 적응형@1080 v4.0은 미측정** → 이 테스트가 채움.
- **재활용:** Sonnet 185는 v40-regression 그대로(같은 입력·프롬프트·blind). eval-0615 1건만 Sonnet 신규. Opus는 186 전체 신규.

## 1. 가설

- **H0 (귀무):** 적응형@1080 v4.0에서 Opus와 Sonnet 정확도 차이 없음(노이즈 범위 ±2%p 내).
- **H1 (대립):** 유의미한 차이(>2%p). 방향은 미정 — P1처럼 Opus 우위일 수도, 적응형+v4.0에서 수렴/역전일 수도.

## 2. Sample (고정 — `sample_list.json`)

- **186건** = 현재 manifest 전체. GT 분포: moving 72 / shedding 29 / hand_feeding 28 / eating_prey 22 / eating_paste 17 / drinking 16 / unseen 2.
- **구성:** v40-regression frames 185 (sample-01~185, 재활용) + eval-0615 1 (sample-186, `d6c57474` 저화질 clean-closeup drinking).
- **분리 보고:** ① 186 전체 ② **회귀셋 185**(공정 baseline) ③ eval-0615 1(쉬운 샘플, 별도 표기).
- **blind:** sample-NN 중립 폴더 + GT는 `meta.json`에만. agent는 `f_*.jpg`만 Read, meta 금지.

## 3. 모델 / 입력 / 프롬프트

| 축 | 값 |
|---|---|
| 모델 | **Opus 4.8** + **Sonnet 4.6** (둘 다 production 후보) · blind |
| 입력 | 적응형 frames@1080 (간격3.5/구간중앙/no-upscale) — **두 모델 동일 프레임**(공정성) |
| 프롬프트 | **v4.0** 고정 (`_prompt_v40.txt`) |
| 배치 | Opus 186 = Workflow ~16그룹 신규 / Sonnet = v40 재활용 185 + eval-0615 1 신규 |
| 결정론 | 서브에이전트 temperature 비제어 → 집계 비교(paired 아님), ±1~2 노이즈 |

## 4. 측정 지표

1. **raw 7-class 정확도** (모델별 × 186/185/eval-0615) — 주 지표.
2. **급여경계 정확도** (drinking↔eating_paste 무해 묶음).
3. **클래스별 정확도 + 혼동행렬** — 모델 간 강·약점 차이.
4. **care-priority 3클래스** (moving 72 + shedding 29 + drinking 16 = 117) 정확도 — 제품 가치 1순위.
5. (참고) Opus↔Sonnet **discordant** 샘플 — 갈린 케이스 수.

> 점수는 `scripts/_score_opus_sonnet.py`(신규)가 산출. 손계산 금지. missing/duplicate/schema error는 run fail.

## 5. 합격 기준 (이건 채택 게이트 아님 — baseline + 모델선택)

- **게이트 없음.** 두 모델의 정확도를 **있는 그대로** 보고하는 측정.
- **품질 가드:** Sonnet 186 재측정분이 v40(185, 85.9%) 대비 ±2%p 벗어나면 noise/오류 의심 → 재확인.

## 6. 예상 비용 / 토큰

- Opus 186 × 적응형 평균 ~11장 ≈ 2,046장 · ~**2.3M input 토큰**(Opus). Sonnet eval-0615 1건 ~0.01M.
- 구독 서브에이전트라 직접 과금 X — 규모 참고용.

## 7. Decision 룰 (사전 명시)

| label | 조건 | 의미 |
|---|---|---|
| **Sonnet 충분** | Opus − Sonnet ≤ +2%p (186 raw) | production = Sonnet 유지(저렴·기존 목표). Opus 이점 미미 |
| **Opus 우위** | Opus − Sonnet > +2%p | Opus를 production 후보로 승격 검토(비용 trade-off 별도). 어느 클래스에서 벌렸는지 기록 |
| **혼재** | 전체는 비슷한데 클래스별로 갈림 | 캐스케이드(저신뢰만 Opus) 후보 — 클래스별 라우팅 설계 근거 |

> 이 테스트는 "더 나은 모델 채택"이 아니라 **"현재 데이터셋의 모델별 정확도 baseline 확보 + 선택 근거"**. production 전환은 비용·지연 포함 별도 결정.

## 무결성 6단계 (§4-3a)

`① pre-reg(이 문서)` → `② blind(Opus 186 Workflow + Sonnet eval-0615, sample-NN)` → `③ deterministic scorer` → `④ LLM audit(Codex 교차)` → `⑤ discordant review(Opus↔Sonnet 갈린 케이스)` → `⑥ decision(REPORT.md)`

---
**다음:** Opus 186 Workflow blind 배치 + Sonnet eval-0615 1건 → `_score_opus_sonnet.py` 채점 → REPORT.md. **배치 직전 사용자 재확인.**

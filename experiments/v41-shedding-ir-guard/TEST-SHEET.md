# v4.1 shedding IR-guard 회귀 시험지 (TEST-SHEET) — pre-registration

> 규칙: [`.claude/rules/research-testing.md`](../../.claude/rules/research-testing.md). **실행 전 고정 — 합격기준 사후변경 금지.**
> 무결성 6단계: [`specs/experiment-claude-montage-v2.md`](../../specs/experiment-claude-montage-v2.md) §4-3a · 버전격리: [`CLAUDE.md`](../../CLAUDE.md) 룰 1~4

**실험 ID:** v41-shedding-ir-guard · **phase:** v4.1 · **작성일:** 2026-07-08 · **상태:** ✅ 실행 완료 → `reject` ([REPORT](REPORT.md))

---

## 0. 배경 (왜 이 테스트인가)

- **문제:** production 카메라 IR 야간에 흰 모프 게코(트라이익스트림 할리퀸 등)의 흰 무늬를 Sonnet v4.0 이 허물로 오판 → nightly 리포트 탈피 시그널 신뢰도 0. 육안 확정 결과 이 개체 **실제 탈피 0회 · 오탐 22+건**.
- **진단:** v4.0 shedding 룰은 이미 "제거 동작 필수"를 요구하나, 근거 시그널이 **"창백/흰 패치가 정상 체색과 대비"** — 이게 바로 IR + 흰 모프가 만드는 아티팩트. 모델이 흰 패치에 프라이밍돼 머리 움직임을 "제거 동작"으로 confabulate (donts/vlm 룰5). species note 의 개체 묘사(lily-axanthic)도 실제 개체와 불일치.
- **v4.1 변경 (1변수):** shedding 근거를 **"창백 색 대비"(IR 위조 가능) → "물리적으로 분리/벗겨지는 허물 조각"(IR 위조 불가)**로 이동 + IR/저조도 가드 명시 + species note 모프중립화. **클래스 체계·급여/drinking 룰은 v4.0 그대로** (`_VERSION_EXCLUDED_CLASSES` 동일 7-class).
- **데이터 구조 (측정 가능성):** shedding 이 두 집단으로 완전 분리 — 오탐 32건(production camera, GT=moving) vs 진짜 탈피 29건(업로드 클로즈업, GT=shedding). v4.1 은 전자를 회복하되 후자를 지켜야 한다.

## 1. 가설

- **H0 (귀무):** v4.1 은 IR shedding 오탐을 유의미하게 줄이지 못한다 (오탐 억제 <30%), 또는 진짜 탈피 recall 을 깨거나 급여경계를 퇴행시킨다.
- **H1 (대립):** v4.1 이 Set-FP 오탐을 ≥60% shedding→moving 으로 회복시키면서, 진짜 탈피 recall(29)·급여경계·raw 를 v4.0 대비 유지한다.

## 2. Sample (고정)

### Set-FP — "does it fix?" (오탐 억제 측정)
- **N=32** · production 카메라 클립, nightly VLM=shedding 이나 사람 GT=moving (흰 모프 IR 오탐).
- **재현:** `uv run python experiments/v41-shedding-ir-guard/_build_fp_sample.py` → `sample_list_fp.json` (clip_id 정렬 고정).
- **GT 출처:** behavior_logs(human) 22 + behavior_labels 10 (owner 육안 + 세션 대행). 전부 source=camera.
- **GT 신뢰도:** owner "이 개체 탈피 0" 확정 + 전수 육안 = moving 고신뢰. (대행 라벨분도 owner 확정 패턴과 정합.)

### Set-REG — "does it break?" (회귀 가드, 185 동결셋 재사용)
- **N=185** = `experiments/v40-regression/` 동결셋 (`storage/dataset-203/manifest.csv` 전체). GT: moving 72 / **shedding 29** / hand_feeding 28 / eating_prey 22 / eating_paste 17 / drinking 15 / unseen 2.
- **진짜 탈피 recall 가드가 여기 흡수됨** — shedding 29 = 전부 업로드 클로즈업 진짜 탈피 (query 확인). 별도 Set-SHED 불필요.
- **v4.0 예측 캐시 재사용:** `experiments/v40-regression/raw/v4.0_g*.json` (frames·blind 매핑 동일) → v4.1 만 재추론해 paired.
- **blind:** 기존 `sample-NN/` 중립 폴더 + GT는 meta.json (seed 42). 인퍼런스 에이전트는 GT/버전/이력 못 봄.

## 3. 모델 / 입력 / 프롬프트

| 축 | 값 |
|---|---|
| 모델 | **Claude Sonnet 4.6** blind · Workflow 서브에이전트 (production 목표 · CLAUDE.md 룰4) |
| 입력 | 적응형 frames@1080 (간격 3.5s / clamp 6~20 / 구간중앙 / no-upscale) · Set-FP·Set-REG 공통 |
| 프롬프트 | **v4.0**(기준선) vs **v4.1**(IR 가드) — 단일 변수. `build_system_prompt('crested_gecko', prompt_version=)` |
| 결정론 | 서브에이전트 temperature 비제어 → paired(recovered/broken)로 흡수. 소표본 ±1~2 노이즈 존재 |

> Set-REG: v4.0 캐시 재사용, v4.1 만 185 재추론. Set-FP: v4.0·v4.1 **둘 다** 32건 재추론 (동일 적응형 프레임 위 paired — nightly 프레임과 분리해 입력 통제).

## 4. 측정 지표

1. **Set-FP shedding 억제** — v4.0 shedding 수(S0) vs v4.1 shedding 수. 억제율 = (S0 − S1)/S0. + →moving 회복 수.
2. **Set-FP paired** — recovered(v4.0 shed → v4.1 moving) / broken(v4.0 moving → v4.1 shed) / new-error(→drinking·paste 등 오분류).
3. **Set-REG 진짜 탈피 recall** — shedding 29 중 정답 수, v4.0 캐시 vs v4.1. broken_shed(v4.0 맞음 → v4.1 틀림) 카운트.
4. **Set-REG 급여경계 paired** — drinking/eating_paste ↔ 비급여 경계 recovered/broken (급여내부 이동 무해, v40-regression §4-3 동일 규칙).
5. **Set-REG raw 정확도 (7-class)** — v4.0 캐시 vs v4.1, 폭락 가드.

## 5. 합격 기준 (숫자 · 사후변경 금지)

**Part A — Set-FP (오탐 억제):**
- **주 게이트:** shedding 억제율 **≥60%** (v4.1 잔존 shedding ≤ ⌈S0 × 0.4⌉).
- **역행 가드:** broken(moving→shedding) **= 0**.
- **오분류 가드:** new-error(→비-moving 오분류) **≤ 2/32**.

**Part B — Set-REG (회귀, v4.0 대비):**
- **진짜 탈피 가드:** broken_shed **≤ 2** (진짜 탈피 recall 손실 최소 — v4.1 IR 가드는 클로즈업 진짜 탈피엔 안 걸려야 정상).
- **급여경계 가드:** recovered ≥ broken (shedding 룰만 바꿔 급여경계 변동 ≈0 기대).
- **폭락 가드:** raw 7-class 가 v4.0 대비 **−3%p 초과 폭락 없음**.

## 6. 예상 비용 / 토큰

- Set-FP: 32 × ~11장 × 2버전 ≈ 700장. Set-REG: 185 × ~11장 × 1(v4.1만) ≈ 2,035장. **합 ~2,700장 · ~3M input 토큰**.
- 구독 서브에이전트 → 직접 과금 X. ⚠️ **구독 한도 공유** (nightly worker + backfill + 본인 작업과 경합, 메모리 `claude-subscription-quota-shared`) → 실행 시점 사용자 확인.

## 7. Decision 룰 (사전 명시)

| label | 조건 |
|---|---|
| **adopt** | Part A 억제율 ≥60% + broken=0 + new-error≤2 **AND** Part B broken_shed≤2 + 급여경계 recovered≥broken + raw 폭락 없음 |
| **hold** | Part A 억제율 30~60% **OR** Part B broken_shed 3~4 → 사용자 discordant 육안 검토 후 판단 |
| **reject** | Part A 억제율 <30% **OR** broken>0 **OR** Part B broken_shed≥5 (진짜 탈피 파괴) **OR** raw −3%p 초과 폭락 |
| 해석 가드 | 소표본(32·29) ±1~2 노이즈 — 경계값은 discordant 육안 동반. Set-FP GT 대행분은 owner 확정 패턴과 정합 전제 |

## 무결성 6단계 (§4-3a)

`① pre-reg(이 문서)` → `② blind 인퍼런스(Sonnet: Set-FP v4.0·v4.1, Set-REG v4.1)` → `③ deterministic scorer(GT 대조 + 급여경계·shedding 라벨링)` → `④ LLM audit(불일치 교차)` → `⑤ discordant review(v4.0↔v4.1 갈린 건 + broken_shed 육안)` → `⑥ decision(REPORT.md)`

---
**다음:** Set-FP 프레임 추출(32, R2 다운로드 + 적응형) → blind 배치 (Set-FP v4.0→v4.1, Set-REG v4.1) → 채점 → REPORT.md. **배치 직전 사용자 재확인(한도).**

# V1 drinking 표적 검증 시험지 (TEST-SHEET) — pre-registration

**실험 ID:** v1-drinking-targeted
**날짜:** 2026-06-13 · **상태:** ✅ 실행 완료 → [`REPORT.md`](REPORT.md) (decision: `close`)
**규칙:** [`.claude/rules/research-testing.md`](../../.claude/rules/research-testing.md) · 무결성 6단계: [`specs/experiment-claude-montage-v2.md`](../../specs/experiment-claude-montage-v2.md) §4-3a

> ⚠️ **실행 방법 변경 (합격기준 불변):** 신규 21건 blind 배치 대신 **v40-regression 재활용 + 풀해상도 육안 재분류**로 수행. 사유는 결과 확인 전 기록 — V1 측정 조건(적응형@1080 v4.0 Sonnet blind)이 v40에 더 강한 blind(185 셔플)로 이미 존재. decision 룰(§5·§7)은 사전 그대로 적용. 상세: [`REPORT.md`](REPORT.md) §2.
**상위 스펙:** `specs/experiment-claude-montage-v2.md` §2(In) V1 · §3 완료조건 V1 · `specs/next-session.md` 06-13 §V1 재해석

---

## 0. 배경 (왜 이 테스트인가)

- **남은 질문:** v4.0 회귀(`v40-regression/`)에서 적응형@1080 drinking = **11/15, 누출 4건**. 이 누출이 **입력 한계**(더 나은 입력이면 회복)인지 **시각 부재**(영상에 혀 신호 자체가 없음)인지 — 입력표현 레버의 **마지막 매듭 측정**.
- **재해석(적응형 채택 후):** 원안 V1(cv-frames 768px 신규 제작)은 적응형@1080이 duration-adaptive를 이미 흡수 → cv-frames는 1080보다 해상도 낮아 미세접촉에 불리. **현 최선 입력인 적응형@1080을 drinking에 표적 측정**하는 게 합리적 (사용자 확인 2026-06-13).
- **추가 검증 — 과탐 안전성:** v4.0이 drinking을 "물 보임(시각증거)" → "몸 고정 + 머리 반복 핥기(행동패턴)"로 넓혔다. 물 없는 곳 혀 날름(hard negative)을 drinking으로 **과탐**하는지 동시 확인 (negative control 필수).
- **기대치:** 낮음 (시간축 가설2 음성 + P2 "입력표현 레버 소진" 전례). **채택 실험 아님** — 방향 판정용 (스펙 §3 V1).

## 1. 가설

두 축이 독립 (입력레버 · 과탐 안전성). 결과는 4상한 가능.

**축 A — 입력레버:**
- **H0-A (소진):** 적응형@1080 v4.0에서 누출되는 drinking은 **전부 시각 부재** (occlusion-check 풀해상도 육안에서도 혀 신호 없음/부분가림) → 입력표현으로 회복 불가.
- **H1-A (잔존):** 누출 중 **≥1건은 입력 한계** (풀해상도 육안엔 혀가 보이는데 적응형@1080 다운스케일/샘플링이 뭉갬) → ROI crop·고해상 입력으로 회복 여지.

**축 B — 과탐 안전성:**
- **H0-B (위험):** v4.0 drinking 확장이 hard negative(물 없는 혀 날름)를 drinking으로 과탐 (FP ≥ 2/6).
- **H1-B (안전):** v4.0은 hard negative를 과탐하지 않음 (FP ≤ 1/6).

## 2. Sample (고정 — `sample_list.json`)

- **총 21건** = positive 15 + negative 6. SOT = `storage/dataset-203/manifest.csv` (gt 컬럼).
- **positive 15 (GT=drinking 전수):** `036a650d 2c1be3dd 3d46364a 685911a0 6d9d504f b5637a1a c9bc5878 71889c3c 00c089c8 3369d723 6a24c2e6 7124cebe bf83c4cf d95e9eaa f4b33f32`
  - cf698b78은 GT 부적합으로 평가셋에서 이미 제외(15건이 전수).
- **negative 6 (검증된 hard negative 전수):** `a3a453c3`(licking-own-face) · `48b5582e`(v3.6.1 실제 과탐) · `05da625c 2420abd8 987c7b5d ff1ecb03`(chemoreception 정정 4건, 사용자 영상 확인 완료).
  - moving 나머지 66건은 혀 안 보이는 일반 이동 → drinking과 안 헷갈려 negative control 정보량 낮음. **16건 못 채우는 게 데이터 현실** (사용자 결정: hard 6건 집중, 2026-06-13).
- **재현:** `sample_list.json` 의 clip8 리스트 → 추출기 `--sample-list` 로 추출 (아래 §3). seed 42 셔플 blind.

## 3. 모델 / 입력 / 프롬프트

| 축 | 값 |
|---|---|
| 모델 | **Claude Sonnet 4.6** (production 목표) · blind · 구독 서브에이전트 |
| 입력 | **적응형 frames@1080** (간격 3.5s / 하한 6 / 상한 20 / 구간중앙 / no-upscale) — v4.0 신표준, v40-regression과 동일 |
| 프롬프트 | **v4.0 고정** (새 회귀 기준선) — 단일 입력, 비교군 없음 (frames-10 paired는 "정밀" 규모라 이번 제외) |
| 결정론 | 서브에이전트 temperature 비제어 → recall ±1~2 노이즈. **v40 측정(11/15)과 일관성 교차 확인** |

**추출 명령 (재현):**
```bash
# 추출기에 --sample-list 옵션 추가 후 (실행 단계):
PYTHONPATH=. uv run python scripts/_extract_frames_clip.py \
  --sample-list experiments/v1-drinking-targeted/sample_list.json \
  --out experiments/v1-drinking-targeted/frames --adaptive --shuffle 42
```
- sample-NN/ 폴더 + meta.json{gt,src,nframes}, 21건 셔플. blind = meta.json GT 은닉, 폴더명 중립.

## 4. 측정 지표

1. **drinking pos recall** — pos 15 중 drinking 맞춘 수. **raw(drinking 엄격)** + **급여경계(drinking↔eating_paste 무해 묶음)** 둘 다 보고.
2. **drinking 비급여 누출 리스트** — pos 15 중 비급여(moving/shedding/unseen 등)로 샌 clip8 명시.
3. **누출 × occlusion-check 육안 대조** — 각 누출건을 분류: `입력한계`(풀해상도 육안 혀 보임) / `시각부재`(육안도 혀 없음·부분가림). occlusion-check 기존 진단(6a24c2e6=입력해상도 / 3369d723=부분가림) + 풀해상도 jpg 활용.
4. **negative control FP** — hard 6건 중 drinking으로 과탐한 수 + 어느 neg_type인지.
5. **(참고) v40 재활용 일관성** — 이번 pos recall이 v40(11/15)과 ±2건 이내인지.

> 점수는 `scripts/_score_v1.py`(신규)가 산출. 손계산 금지. missing/duplicate/schema error는 run fail (§4-3a 규칙).

## 5. 합격 기준 (숫자 · V1은 채택 아닌 방향 판정)

- **입력레버 임계:** 누출 케이스 중 `입력한계`(육안 혀 보임) **≥1** → 레버 잔존 / **0**(전부 시각부재) → 레버 소진.
- **과탐 게이트:** hard 6건 FP **≤1** = 안전 / **≥2** = 위험.
- **recall 폭락 가드:** pos recall이 v40(11/15=73%) 대비 **9/15 미만**으로 하락하면 측정 노이즈 의심 → hold(재측정).

## 6. 예상 비용 / 토큰

- 21건 × 적응형 평균 ~11장 = **~231장 @1080** (~1,100 tok/장) ≈ **0.25M input 토큰**.
- 구독 서브에이전트라 직접 과금 X. 매우 가벼움 (v40 3.65M의 ~7%).

## 7. Decision 룰 (사전 명시)

| label | 조건 | 후속 |
|---|---|---|
| **proceed (레버 잔존)** | 누출 중 입력한계 ≥1 **AND** 과탐 안전(FP≤1) | ROI crop / 고해상 입력 실험 가치 → `INPUT-REPR-SPEC.md` 에 "drinking ROI 후보" 기록 |
| **close (레버 소진)** | 누출 **전부 시각부재** | 입력표현 트랙 **최종 종료**. drinking은 영상네이티브(미래)/HITL/메타데이터(분무 타임스탬프)로. 과탐 안전이면 v4.0 drinking 정의 유지 |
| **revisit-prompt (과탐 위험)** | hard 6건 FP **≥2** (입력레버와 독립 발동) | v4.0 drinking "행동패턴" 정의가 과넓음 → 재점검 (v4.1 후보). 단 회귀는 같은 모델 paired 필수 |
| **hold** | recall 폭락(노이즈) **OR** 누출 occlusion 대조 모호 | 재측정 / 사람 영상 확인 |

> V1은 adopt/reject 가 아닌 **방향 라벨**(proceed/close/revisit-prompt)을 쓴다 — "입력표현 채택"이 목적이 아니라 "drinking 누출 원인 귀속 + 과탐 안전성 확인"이므로. INDEX 에는 방향 라벨로 등록.

## 무결성 6단계 (§4-3a)

`① pre-reg(이 문서)` → `② blind 인퍼런스(Sonnet, sample-NN 셔플, meta 은닉)` → `③ deterministic scorer(_score_v1.py)` → `④ LLM audit(Codex 교차 — V1-negative FP 누락·소표본 과장 점검)` → `⑤ discordant review(누출 케이스 occlusion 풀해상도 육안 대조 — GT 변경은 사람 확인만)` → `⑥ decision(REPORT.md, 방향 라벨)`

## 한계 (사전 명시)

- **소표본:** pos 15 / neg 6. 1건 = pos 6.7%p / neg 16.7%p. recovered/broken 을 결론으로 승격 금지 — 방향만.
- **입력한계 vs 모델한계 혼입:** "풀해상도 육안 보임 / 적응형@1080 모델 못잡음"을 입력한계로 귀속하나, Sonnet이 1080px에서도 해석 못하는 모델한계 가능성은 occlusion 진단(입력해상도 병목 명시 케이스)으로만 부분 통제. 완전 분리 불가 — REPORT에 명시.
- **frames-10 paired 없음:** "표준" 규모라 입력레버를 occlusion 육안 대조로 판정 (모델기준 paired 격리는 "정밀" 규모에서). 후속 필요시 frames-10(v4.0) arm 추가.

---
**다음:** 추출기 `--sample-list` 옵션 추가 → 21건 추출(seed 42) → leakage 검수 → blind 배치(Sonnet v4.0) → `_score_v1.py` 채점 → 누출 occlusion 대조 → REPORT.md. **배치 직전 사용자 재확인.**

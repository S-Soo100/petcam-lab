# m0-montage 테스트 시험지 (Test Sheet)

> 규칙: [`.claude/rules/research-testing.md`](../../.claude/rules/research-testing.md). **실행 전 고정 — 사후 변경 금지.**
> (소급 정리 2026-06-12 — 규칙 신설 전 실행했으나 pre-reg 내용은 `sample_list.json` + 스펙 §7로 실행 전 고정돼 있었음.)

**실험 ID:** m0-montage · **phase:** M0 · **작성일:** 2026-06-12 · **상태:** ✅ 실행 완료 → [REPORT.md](REPORT.md)

## 1. 가설
- **H1**: 0608 몽타주(72.5%)의 패인이 셀 해상도라면, 고해상 몽타주(프레임 ≥10, 2장분할)는 같은 모델 frames에 근접한다.
- **H0**: 어떤 몽타주 변형도 같은 모델 frames 기준선을 회복하지 못한다.

## 2. Sample list
- 구성: stratified 20건 (micro 12 = drinking/eating_prey/eating_paste 정2오2씩 + general 8 = 경계2·moving·shedding·hf)
- 고정 방법: `scripts/_m0_prereg.py` (seed 42) → [`sample_list.json`](sample_list.json). **고정 후 불변.**

## 3. 모델 / 입력표현 / 프롬프트
- 모델: **Sonnet 4.6** (production 목표, 12변형 전부). Opus 4.8은 상위 후보만 후속(M1).
- 입력표현: 몽타주 12변형 = 6 레이아웃(12f/16f/18f/20f × 1~2장) × ts on/off.
- 프롬프트: v3.6.1 (production 동치, [`PROMPT.md`](PROMPT.md)).

## 4. 측정 지표
- raw 정확도(/20) · micro12 · care-priority(prio3) · paired recovered/broken(vs frames) · 실측 이미지 토큰.

## 5. 합격 기준 (게이트)
- M0는 채택 게이트 아님 — **스크리닝**. 목표 = "frames 근접 + micro 유지" 변형을 M1로 올릴 후보 선정.
- 기준선: 같은 20건 Sonnet frames = **12/20** (`_score_repr.py` selftest 검증).

## 6. 예상 비용 / 토큰
- ~1.0–1.3M (이미지 866k + 오버헤드) 추정. **실측: ~770k / ~3.5분.**

## 7. Decision 룰 (사전)
- **M1 진출**: Sonnet raw 상위 1~2 변형. 동률 시 ① 토큰 낮은 쪽 ② 장수 적은 쪽.
- 해석 가드: 20건 = ±1건(5%p) 노이즈 → M0 단독으로 채택/기각 단정 금지(후보 선정만).

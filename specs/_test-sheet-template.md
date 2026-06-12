# {실험 ID} 테스트 시험지 (Test Sheet)

> 규칙: [`.claude/rules/research-testing.md`](../.claude/rules/research-testing.md). **실행 전 고정 — 사후 변경 금지.**

**실험 ID:** {exp-id} · **phase:** {M0/M1/V1...} · **작성일:** YYYY-MM-DD · **상태:** 🟡 작성중 / 🔒 고정(실행대기) / ▶ 실행중

## 1. 가설
- **H1 (대립)**: {입증하려는 것}
- **H0 (귀무)**: {기각 대상 — 보통 "효과 없음/기준 미달"}

## 2. Sample list
- 구성: {stratified/전수/오답셋 등} · N = {개수}
- 고정 방법: `{스크립트}` (seed {N}) → `{경로}/sample_list.json`
- **고정 후 불변** (변형/모델 간 비교의 유일 변수만 바뀜)

## 3. 모델 / 입력표현 / 프롬프트
- 모델: {primary} (채택 게이트) / {secondary} (검증)
- 입력표현: {frames / 몽타주 변형 / cv-frames ...}
- 프롬프트: {버전} ({production 동치 여부})

## 4. 측정 지표
- {raw 정확도 · paired recovered/broken · false positive · 토큰 · ...}

## 5. 합격 기준 (게이트 — 숫자)
- {예: "같은 모델 frames 기준선 X% 대비 −3%p 이내 AND recovered≥broken AND 토큰 ≥2× 절감"}
- 기준선 출처: {스크립트/수치}

## 6. 예상 비용 / 토큰
- {추정치 + 근거}

## 7. Decision 룰 (사전)
- **adopt**: {조건}
- **hold**: {조건}
- **reject**: {조건}
- 해석 가드: {표본 크기 노이즈 등 — 단독 판정 금지 조건}

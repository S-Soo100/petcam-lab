# {실험 ID} 테스트 보고서 (Report)

> 규칙: [`.claude/rules/research-testing.md`](../.claude/rules/research-testing.md).

**실험 ID:** {exp-id} · **phase:** {...} · **날짜:** YYYY-MM-DD · **상태:** ✅ 실행 완료 · **decision: `{adopt/hold/reject}`**
**시험지:** [`TEST-SHEET.md`](TEST-SHEET.md) · **스펙:** `{specs/...}`

## 1. 무엇을 측정했나 (시험지 요약)
{가설·샘플·모델·기준선·합격기준 1줄 요약 표}

## 2. 결과
- 배치: {모델·토큰·소요} · 채점 {스크립트} (검증 {PASS/FAIL})
- {결과 표 — 지표별}

## 3. 분석
- **가설 판정**: H0 {기각/유지} — {근거}
- {핵심 발견 · paired recovered/broken · 클래스별 · 비교축}

## 4. Decision: `{adopt/hold/reject}`
- {근거 — 합격기준 충족 여부, 누적 결론과의 정합}

## 5. 한계
- {표본 크기 · 비결정성 · 단일 모델 등}

## 6. 다음 액션
- {후속 phase · 보류 해소 조건 · 갈래}

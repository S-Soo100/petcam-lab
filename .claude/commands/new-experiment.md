---
description: 연구 실험 디렉토리 셋업 (TEST-SHEET + REPORT + INDEX 등록)
---

# /new-experiment — 실험 디렉토리 셋업

인자: `$ARGUMENTS` (형식: `<exp-id> [<phase>]` · 예: `/new-experiment v2-roi-crop V2`)

연구 테스트 규칙([`.claude/rules/research-testing.md`](../rules/research-testing.md))의 **시험지+보고서 의무**를 충족하는 실험 폴더를 한 번에 세운다. 매번 템플릿 위치를 찾고 INDEX 등록을 잊는 반복을 제거.

## 동작

1. `$ARGUMENTS` 파싱: 첫 토큰 = `exp-id`, 둘째(선택) = `phase`. `exp-id` 없으면 중단하고 요청.
2. `experiments/<exp-id>/` 폴더 생성. **이미 있으면 에러 출력 후 중단**(덮어쓰기 금지 — 진행 중 실험 보호).
3. `specs/_test-sheet-template.md` → `experiments/<exp-id>/TEST-SHEET.md` 복사 + 헤더 자동 채우기:
   - `실험 ID: <exp-id>` · `날짜: $(date +%Y-%m-%d)` · `상태: pre-reg (실행 전 고정, 합격기준 사후변경 금지)`
   - 규칙 링크(`.claude/rules/research-testing.md`) + 무결성 6단계 링크
4. `specs/_report-template.md` → `experiments/<exp-id>/REPORT.md` 복사 + 헤더: `실험 ID: <exp-id>` · `상태: (실행 후 작성)`
5. `experiments/INDEX.md` "진행 중 트랙" 표에 대기 행 추가:
   `| $(date +%Y-%m-%d) | <exp-id> <phase> | (대기) | — | — |`
6. 출력: 생성 경로 3개 + "다음: TEST-SHEET.md의 가설/sample/게이트/decision룰을 **실행 전에** 채우세요 (pre-reg)" 안내.

## 주의

- 템플릿(`specs/_test-sheet-template.md`·`_report-template.md`)이 없으면 경고하고 최소 골격만 생성.
- 이 커맨드는 **골격만** 만든다 — 가설·sample list·합격기준은 사람이 pre-reg로 작성(사후변경 금지).
- INDEX 대기 행은 실험 완료 시 decision label(adopt/hold/reject/close 등)로 갱신.
- sample list가 크면 `experiments/<exp-id>/sample_list.json`을 별도로 둔다(재현용).

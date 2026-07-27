# 연구 카탈로그·보존 실행 계획

> 설계: `docs/superpowers/specs/2026-07-27-research-catalog-retention-design.md`
> 실행 브랜치: `codex/research-catalog-20260727`

## Task 1 — 중앙 카탈로그 뼈대

**Files:**
- Create: `docs/research/catalog.json`
- Create: `docs/research/README.md`
- Create: `docs/research/RETENTION.md`

1. 상태 enum과 공통 필드를 명시한다.
2. owner GT·visibility ROI·consensus shadow·Python Evidence·local router·Gate 관련 현재 항목을 채운다.
3. 각 항목에 기준 원문, commit, 다음 허용 행동을 기록한다.

## Task 2 — 연관 연구 문서 연결

**Files:**
- Modify: `docs/research/catalog.json`
- Modify: `docs/research/README.md`

1. `petcam-nightly-reporter` consensus design/plan과 `gecko-vision-gate` bbox evidence 문서를 reference로 추가한다.
2. local router와 Claude/VLM 품질 연구가 다른 트랙임을 표기한다.
3. 기각·보류 항목에는 재실행 금지 또는 재등판 조건을 적는다.

## Task 3 — 보존·정리 기록

**Files:**
- Modify: `docs/research/RETENTION.md`

1. tracked 증거는 보존하고 ignored raw는 위치만 추적하는 정책을 적는다.
2. 공유 primary worktree의 미추적 파일과 원인 미확인 파일은 삭제하지 않는다고 기록한다.
3. 물리 삭제 후보는 소유자·근거·재현 영향 확인 후 별도 승인으로만 처리한다고 고정한다.

## Task 4 — 검증·커밋

1. JSON 파싱, 카탈로그 경로 존재, 외부 repo commit SHA를 검증한다.
2. `git diff --check`와 `git status`로 범위를 확인한다.
3. 사용자 승인 범위 안에서 docs-only 커밋·push한다. main merge는 하지 않는다.

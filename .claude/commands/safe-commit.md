# /safe-commit — 다른 세션 미커밋 파일 제외 안전 커밋

멀티세션(같은 워킹트리에 Claude 세션 2개) 운영 시, 다른 세션이 작업 중인
미커밋 파일을 내 커밋에 섞지 않도록 **이번 세션이 건드린 파일만 명시 add** 하는 절차.
2026-07-08 멀티세션 공유트리 사고 재발 방지 — CLAUDE.md "멀티세션 / 파괴적 git 안전" 룰과 짝.

## 사용법
`/safe-commit <커밋 메시지>` [제외할 파일/패턴...]

예: `/safe-commit "feat(api): 필터 추가"`  (다른 세션 미커밋은 자동 식별해 제외)

## 흐름
1. `git status --short` 로 변경/미추적 파일 전체 확인
2. **이번 세션에서 내가 실제 건드린 파일만** 식별 (다른 세션 미커밋 = 제외 대상)
   - 애매하면 사용자에게 "이 파일들 커밋 대상 맞아?" 확인
3. `git -C <repo> add <내 파일만>` — 파일 경로 명시. **`git add -A` / `git add .` 절대 금지**
4. `git -C <repo> diff --cached --name-only` 로 커밋 대상 재확인 (제외 파일 안 섞였나 눈으로)
5. 커밋 — prefix(feat/fix/docs/chore/refactor/test) + 한글 설명 + `Co-Authored-By` 태그
6. 협업 모드(다른 개발자 존재)면 브랜치 + push, **main 직접 push 금지**

## 하드룰
- **`git add -A` / `git add .` 금지** — 다른 세션의 미커밋 작업을 통째로 빨아들여 사고
- 파괴적 git(`reset` / `clean -f` / `revert`·`merge`·`rebase --abort`)은 `dangerous-guard.sh`(전역 hook)가 차단 — 우회 금지
- 커밋 직전 반드시 `diff --cached --name-only` 로 대상 확인
- 빈 staged면 커밋 중단 + 경고

## 배경
공유 워킹트리 2세션은 인덱스를 공유한다. `git add -A` 하나가 다른 세션의
진행 중 파일을 커밋에 섞고, 파괴적 git 하나가 상대 미커밋을 소실시킨다.
근본 해법은 **2번째 세션 worktree 격리**(`using-git-worktrees`)지만, 격리 못 한
상황에서 최소 방어가 이 명령이다.

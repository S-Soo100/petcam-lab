---
handoff_version: 1
task_id: canonical-gt-ledger-v1
execution_repo: /Users/baek/petcam-lab/.worktrees/labeling-gt-canonical-plan
plan_path: /Users/baek/petcam-lab/.worktrees/labeling-gt-canonical-plan/docs/superpowers/plans/2026-08-04-labeling-gt-canonical-ledger.md
design_path: /Users/baek/petcam-lab/.worktrees/labeling-gt-canonical-plan/docs/superpowers/specs/2026-08-04-labeling-gt-canonical-ledger-design.md
commit_sha: e6d4d47a0d9601cac93c7a5c830432147bd20124
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: none
---

# Canonical GT 구현 handoff

## 소유 범위

- 이 worktree에서 새 canonical GT migration, probe, projector, API/UI를 구현해.
- source session/submission/consensus/event 행은 수정·삭제하지 않아.
- blind submit/finalize RPC에 canonical trigger나 동기 writer를 추가하지 않아.

## 현재 제외 소유 경로

`/Users/baek/.codex/worktrees/8faf/petcam-lab`의 미완료 변경과 겹치는 다음 파일은 해당 세션이
통합되거나 소유권이 해제되기 전 수정하지 않아.

- `AGENTS.md`
- `docs/DATABASE.md`
- `pyproject.toml`
- `uv.lock`
- `web/src/app/labeling/_role-shell.tsx`
- `web/src/lib/labelingRoleNavigation.test.ts`
- `web/src/lib/labelingRoleNavigation.ts`
- `web/src/lib/labelingV3Server.ts`

## Runtime

이 manifest는 구현 시작점 검증용이라 runtime은 `none`이야. Preview 또는 scheduled runtime을
배포하기 전 target host/service를 담은 별도 runtime manifest를 만들고 다시 검증해.

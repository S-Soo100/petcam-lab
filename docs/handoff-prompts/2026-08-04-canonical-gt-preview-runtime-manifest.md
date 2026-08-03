---
handoff_version: 1
task_id: canonical-gt-preview-v1
execution_repo: /Users/baek/petcam-lab/.worktrees/labeling-gt-canonical-plan
plan_path: /Users/baek/petcam-lab/.worktrees/labeling-gt-canonical-plan/docs/superpowers/plans/2026-08-04-labeling-gt-canonical-ledger.md
design_path: /Users/baek/petcam-lab/.worktrees/labeling-gt-canonical-plan/docs/superpowers/specs/2026-08-04-labeling-gt-canonical-ledger-design.md
commit_sha: 4627d2d89190810c193c53c60e45afb57172e4e5
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: server
runtime_host: petcam-t3119am9x-ssoo100s-projects.vercel.app
runtime_label: petcam-lab-web-preview
---

# Canonical GT Preview runtime handoff

- 배포 시 canonical GT 관련 환경변수는 모두 미설정이며 코드 기본값 `false`로 fail-closed한다.
- Preview는 DB migration을 적용하거나 projector를 실행하지 않는다.
- `/api/internal/canonical-gt/project`는 인증/flag가 없으면 404다.
- production DB 적용 전 source digest, dry-run count, pg_cron 가용성을 별도로 확인한다.

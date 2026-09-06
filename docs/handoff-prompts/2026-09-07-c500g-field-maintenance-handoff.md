---
handoff_version: 1
task_id: rap-c500g-field-maintenance
execution_repo: /Users/baek-end/.codex/worktrees/rap-c500g-field-maintenance/petcam-lab
plan_path: /Users/baek-end/.codex/worktrees/rap-c500g-field-maintenance/petcam-lab/docs/superpowers/plans/2026-09-07-c500g-field-maintenance.md
design_path: /Users/baek-end/.codex/worktrees/rap-c500g-field-maintenance/petcam-lab/docs/superpowers/specs/2026-09-07-c500g-field-maintenance-design.md
commit_sha: 1057d139da6a919369f3b9cf10366243d668ab66
implementation_host: baeg-endeuui-Macmini.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.teraai.rap-c500g-manager
---

# RAP C500G 화요일 현장 정비 handoff

## Bootstrap SHA와 final SHA

`commit_sha`는 design과 plan을 포함한 bootstrap 문서 commit이다. final HEAD는 이 manifest만 추가한
한 개의 descendant commit이다. `verify_agent_handoff.py`는 bootstrap SHA가 plan/design을 포함하고
final HEAD와의 변경이 이 manifest 하나뿐인 기존 프로젝트 패턴을 검증한다. 구현자는 literal
`HANDOFF_OK` 전에는 Task 1을 시작하지 않는다.

## Runtime ownership

- implementation host: `baeg-endeuui-Macmini.local`
- runtime host: `baeg-endeuui-Macmini.local`
- runtime kind: `launchagent`
- exact service label: `com.teraai.rap-c500g-manager`
- starting runtime SHA: `7b0d19e9039ab5fd46089e4a86c80e99e5df8d63`

## Absolute safety boundary

현재 운영 worktree `/Users/baek-end/.codex/worktrees/rap-c500g-capture-first/petcam-lab`, service,
plist, SQLite, USB recording, R2 object, DB row는 구현·테스트 동안 변경하지 않는다. 배포 단계에서도
target label 하나만 다루며 canary 실패 시 이전 plist와 runtime HEAD로 복원한다. local/R2/DB evidence는
삭제·이동·덮어쓰기하지 않는다.

local prune은 기본 dry-run이다. exact mount/root, final manifest, R2 size/SHA, DB 완료, active/pipeline
제외와 plan digest가 모두 맞고 Owner가 실행을 승인한 경우만 검증된 local bundle을 개별 삭제한다.
USB 포맷, R2/DB delete, broad glob delete는 금지한다.

비밀값, 전체 RTSP URL, webhook URL을 stdout, Git, event, Slack에 출력하지 않는다.

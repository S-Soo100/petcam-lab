---
handoff_version: 1
task_id: rap-c500g-capture-first-runtime
execution_repo: /Users/baek-end/.codex/worktrees/rap-c500g-capture-first/petcam-lab
plan_path: /Users/baek-end/.codex/worktrees/rap-c500g-capture-first/petcam-lab/docs/superpowers/plans/2026-09-03-rap-c500g-capture-first-pipeline.md
design_path: /Users/baek-end/.codex/worktrees/rap-c500g-capture-first/petcam-lab/docs/superpowers/specs/2026-09-03-rap-c500g-capture-first-pipeline-design.md
commit_sha: bd2f05d4337d4c39554501ed7801890b1c3303fb
implementation_host: baeg-endeuui-Macmini.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.teraai.rap-c500g-manager
---

# RAP C500G capture-first runtime handoff

Task 1~8의 구현 기준 SHA를 Mac mini 단일 LaunchAgent runtime에 반영하고 Task 9 canary를 수행해.
기존 recorder와 manager를 동시에 띄우지 말고, 기존 local/R2/DB artifact는 삭제하거나 덮어쓰지 마.

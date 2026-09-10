---
handoff_version: 1
task_id: rap-c500g-capture-first-implementation
execution_repo: /Users/baek/.codex/worktrees/petcam-lab/rap-c500g-r2
plan_path: /Users/baek/.codex/worktrees/petcam-lab/rap-c500g-r2/docs/superpowers/plans/2026-09-03-rap-c500g-capture-first-pipeline.md
design_path: /Users/baek/.codex/worktrees/petcam-lab/rap-c500g-r2/docs/superpowers/specs/2026-09-03-rap-c500g-capture-first-pipeline-design.md
commit_sha: 9e25021b99e3f307761631851acb542b8fb8b7e1
implementation_host: baeg-endeuui-Macmini.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.teraai.rap-c500g-manager
---

# RAP C500G capture-first 구현 handoff

이 manifest는 MacBook에서 Mac mini 작업으로 Git 상태를 넘기기 위한 송신 gate다.

Mac mini 작업은 앱 handoff가 끝난 뒤 다음 순서를 지켜.

1. 현재 host가 `baeg-endeuui-Macmini.local`인지 확인한다.
2. 전달된 branch의 plan/design commit과 이 manifest commit을 확인한다.
3. Mac mini의 실제 isolated worktree 절대경로를 사용한 수신용 handoff manifest를 새 파일로 만든다.
4. 수신용 manifest의 `commit_sha`에는 이 송신 manifest commit SHA를 기록한다.
5. 수신용 manifest 한 파일만 별도 커밋하고 `scripts/verify_agent_handoff.py`로 `HANDOFF_OK`를 만든다.
6. 그 전에는 구현·테스트·launchagent 변경을 시작하지 않는다.

구현은 승인된 설계와 계획을 task 순서대로 수행한다. 기존 local/R2/DB 영상은 삭제·수정하지 않고,
현재 production capture가 있으면 runtime cutover를 하지 않는다. 커밋은 이 작업에 대해 owner가 승인했다.

---
handoff_version: 1
task_id: rap-c500g-manager-runtime
execution_repo: /Users/baek/.codex/worktrees/petcam-lab/rap-c500g-r2
plan_path: /Users/baek/.codex/worktrees/petcam-lab/rap-c500g-r2/docs/superpowers/plans/2026-09-01-rap-c500g-local-manager.md
design_path: /Users/baek/.codex/worktrees/petcam-lab/rap-c500g-r2/docs/superpowers/specs/2026-08-31-rap-c500g-local-manager-design.md
commit_sha: 0e422a4748e83f26af6c6439ec2c97d5b762dd32
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.teraai.rap-c500g-manager
---

# RAP C500G 시각화 매니저 runtime handoff

맥미니에서 코드 commit SHA를 다시 확인하고 read-only preflight를 먼저 실행해.
기존 `com.teraai.rap-c500g-recorder`는 활성 FFmpeg가 0인 상태에서만 unload해.

60초 진단은 카메라 3대, USB, 로컬 artifact, R2, DB, MP4/Quick Look을 검증해야 해.
진단이 실패하면 새 manager를 시작하지 말고 기존 recorder를 즉시 복원해.

진단 성공 뒤에만 `com.teraai.rap-c500g-manager`를 bootstrap하고 다음을 확인해.

- 기존 recorder unloaded
- 새 manager loaded/running 및 PID 존재
- working directory와 HEAD 일치
- production owner와 lock owner가 하나
- `http://127.0.0.1:8766/` 응답과 secret-free 상태 JSON
- 기존 local/R2/DB 객체 삭제 0건

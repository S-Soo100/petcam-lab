---
handoff_version: 1
task_id: vlm-structured-error-runtime-deploy
execution_repo: /Users/baek-end/petcam-nightly-reporter-vlm-error-integration
plan_path: /Users/baek-end/petcam-nightly-reporter-vlm-error-integration/docs/superpowers/plans/2026-07-16-vlm-single-host-operations-hardening.md
design_path: /Users/baek-end/petcam-nightly-reporter-vlm-error-integration/specs/2026-07-16-vlm-single-host-operations-hardening-design.md
commit_sha: 0eaa7ea77964c77511b7a1ba9f998bd27b0864af
implementation_host: baeg-endeuui-Macmini.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.vlm-candidate-worker
---

# VLM structured error runtime handoff

- report:
  `/Users/baek-end/petcam-nightly-reporter-vlm-error-integration/docs/handoff-prompts/2026-07-30-vlm-cli-structured-error-classification-report.md`
- target runtime checkout:
  `/Users/baek-end/petcam-nightly-reporter`
- runtime mode:
  scheduled LaunchAgent one-shot, 기존 22:00/00:00/02:00/04:00 KST만 사용
- forbidden:
  manual kickstart, historical replay, DB manual update, max-turns/subretry/model/prompt/budget 변경
- rollback:
  deployment-only 검증 실패 시 `com.petcam.vlm-candidate-worker`와 runtime checkout만 predeploy
  SHA로 되돌리고 다른 service·production data는 변경하지 않는다.

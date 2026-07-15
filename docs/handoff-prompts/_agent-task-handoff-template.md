# Agent Task Handoff Template

> 아래 front matter의 예시 값을 실제 값으로 전부 교체한 뒤 validator가 `HANDOFF_OK`를 출력해야 전달할 수 있어.

```yaml
---
handoff_version: 1
task_id: vlm-single-host-operations-hardening
execution_repo: /Users/baek/petcam-nightly-reporter
plan_path: /Users/baek/petcam-nightly-reporter/docs/superpowers/plans/2026-07-16-vlm-single-host-operations-hardening.md
design_path: /Users/baek/petcam-nightly-reporter/specs/2026-07-16-vlm-single-host-operations-hardening-design.md
commit_sha: 0000000000000000000000000000000000000000
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.vlm-candidate-worker
---
```

## 작성 계약

- `execution_repo`, `plan_path`, `design_path`는 `~` 없는 절대경로로 적어.
- `commit_sha`는 plan/design이 포함된 `git rev-parse HEAD`의 40자리 값을 적어.
- 다른 세션에 넘기기 전에 plan/design을 commit하고 working-tree 수정이 없어야 해.
- runtime이 없으면 `runtime_kind: none`으로 쓰고 `runtime_host`, `runtime_label` 두 줄을 삭제해.
- runtime이 있으면 구현 host와 실제 실행 host가 같아도 둘 다 명시해.

## 전달 전 검증

```bash
cd /Users/baek/petcam-lab
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/petcam-lab/docs/handoff-prompts/actual-agent-task-handoff.md
```

`HANDOFF_OK` 전문, manifest 절대경로, 실행할 task 범위를 수신 agent에게 함께 전달해. 실패하면 파일·Git·host 계약을 고친 뒤 다시 검증하고, 추측으로 구현을 시작하지 마.

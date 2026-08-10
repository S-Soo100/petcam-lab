---
handoff_version: 1
task_id: yolo-v21-preview-worker
execution_repo: /Users/baek/.codex/worktrees/5f87/petcam-lab
plan_path: /Users/baek/.codex/worktrees/5f87/petcam-lab/docs/superpowers/plans/2026-08-10-yolo-v21-preview-worker.md
design_path: /Users/baek/.codex/worktrees/5f87/petcam-lab/docs/superpowers/specs/2026-08-10-yolo-v21-preview-worker-design.md
commit_sha: aa29abd6df6e0d1fa4176cadd06b6dd56849db7a
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.yolo-preview-worker
---

# YOLO v2.1 보호 Preview worker handoff

## 시작 계약

1. 구현은 `execution_repo`의 exact `commit_sha`에서 시작한다.
2. design과 plan은 tracked·clean이어야 한다.
3. 아래 validator의 literal `HANDOFF_OK` 전에는 구현 파일을 수정하지 않는다.
4. 구현은 MacBook worktree에서 하고 runtime은 Mac mini의 별도 exact-SHA worktree에 둔다.

```bash
cd /Users/baek/.codex/worktrees/5f87/petcam-lab
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/.codex/worktrees/5f87/petcam-lab/docs/handoff-prompts/2026-08-10-yolo-v21-preview-worker-handoff.md
```

## 허용 범위

- pinned v2.1 checkpoint를 사용하는 localhost Mac mini LaunchAgent
- 기존 Named Tunnel의 별도 preview hostname
- branch-specific protected Vercel Preview
- 실제 사진·짧은 영상 inference canary

## 금지 범위

- main merge와 Vercel production deployment/alias promote
- production active model event와 production provider 연결
- DB/R2/Dataset/GT/skip/삭제/행동명/사건 묶기 write
- development holdout 34장을 future holdout으로 재사용

## fail-closed

checkpoint SHA, MPS, temp cleanup, secret, tunnel config, production 503 중 하나라도 증명되지 않으면
Preview worker 연결을 끄고 기존 503으로 되돌린다.

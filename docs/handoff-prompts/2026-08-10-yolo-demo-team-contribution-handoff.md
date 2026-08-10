---
handoff_version: 1
task_id: yolo-demo-team-contribution
execution_repo: /Users/baek/.codex/worktrees/5f87/petcam-lab
plan_path: /Users/baek/.codex/worktrees/5f87/petcam-lab/docs/superpowers/plans/2026-08-10-yolo-demo-team-contribution.md
design_path: /Users/baek/.codex/worktrees/5f87/petcam-lab/docs/superpowers/specs/2026-08-10-yolo-demo-team-contribution-design.md
commit_sha: 4d8ce473c5f05ee88eb48783b65b39c4c253d8b2
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: none
---

# YOLO 시연과 초대 팀원 bbox 기여 구현 handoff

## 시작 계약

1. `execution_repo`에서 HEAD가 `commit_sha`와 정확히 같아야 한다.
2. 아래 validator가 `HANDOFF_OK`를 출력하기 전 구현 파일을 수정하지 않는다.
3. design과 plan을 순서대로 읽고 Task 1부터 TDD로 구현한다.
4. 기존 변경을 되돌리지 않는다.

```bash
cd /Users/baek/.codex/worktrees/5f87/petcam-lab
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/.codex/worktrees/5f87/petcam-lab/docs/handoff-prompts/2026-08-10-yolo-demo-team-contribution-handoff.md
```

## 금지 경계

- production DB migration apply, R2 write, 실제 service 변경, Vercel deploy를 하지 않는다.
- 실제 YOLO checkpoint/HTTP worker를 연결하지 않는다.
- prediction을 GT·자동 skip·삭제·행동명·사건 묶기 근거로 쓰지 않는다.
- 공개 opt-in media를 저장하거나 Dataset membership에 직접 넣지 않는다.

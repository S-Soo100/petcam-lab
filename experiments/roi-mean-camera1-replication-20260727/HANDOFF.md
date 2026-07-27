---
handoff_version: 1
task_id: roi-mean-camera1-replication-kickoff-20260727
execution_repo: /Users/baek/.codex/worktrees/7896/petcam-lab
plan_path: /Users/baek/.codex/worktrees/7896/petcam-lab/experiments/roi-mean-camera1-replication-20260727/IMPLEMENTATION-PLAN.md
design_path: /Users/baek/.codex/worktrees/7896/petcam-lab/experiments/roi-mean-camera1-replication-20260727/DESIGN.md
commit_sha: c61fbb0fc029015d465e63a75bad3d97c242ce6c
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: none
---

# Claude execution handoff

`IMPLEMENTATION-PLAN.md`의 Task 1~5를 순서대로 수행해.

- 먼저 manifest verifier를 실행하고 `HANDOFF_OK`가 아니면 중단해.
- `superpowers:executing-plans`, `superpowers:test-driven-development`,
  `superpowers:verification-before-completion`을 사용해.
- production DB는 SELECT-only야. write 계열 tool과 SQL은 사용하지 마.
- 전용 실험 폴더 밖 파일은 수정하지 마.
- 현재 서비스의 web/API/migration/runtime/deploy는 읽기만 가능하고 이 작업에서는 변경하지 마.
- kickoff의 정상 종료는 `ROI_CAMERA1_REPLICATION_COLLECTING`이야.
- 실행 중 manifest가 untracked로 보이는 것은 전달자가 만든 예상 상태야. 삭제·이동하지 말고
  최종 실험 artifact와 함께 commit해도 돼.
- 필요한 production Supabase read-only 연결이 없으면 임의 우회하거나 쓰기 권한을 만들지 말고
  정확한 blocker와 재개 조건을 보고해.

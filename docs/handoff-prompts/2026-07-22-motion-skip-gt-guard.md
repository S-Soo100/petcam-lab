# Claude 실행 지시 — Motion Labeling v3 제외·보류 GT Guard

## 시작 계약

외부 handoff manifest를 먼저 검증하고 `HANDOFF_OK` 전문을 시작 보고에 그대로 남겨. manifest의 `execution_repo`, `plan_path`, `design_path`, `commit_sha`를 임의로 바꾸지 마.

읽기 순서:

1. `AGENTS.md`
2. `.claude/rules/donts.md`
3. `docs/superpowers/specs/2026-07-22-motion-skip-gt-guard-design.md`
4. `docs/superpowers/plans/2026-07-22-motion-skip-gt-guard.md`
5. 이 문서

## 실행 명령

계획 Task 1~5를 TDD RED→GREEN으로 전부 수행해. 구현·검증·task별 commit·push·FF-only main 통합·forward migration apply·Vercel production deploy·새 canary 1건까지 자동 진행해.

다음은 절대 하지 마.

- 진단에 사용한 기존 6건의 분류/session/GT/event 수정·삭제
- 기존 migration 수정
- `LABELING_QUEUE_SOURCE` 변경
- legacy/tutorial/VLM/Python Evidence/activity 변경
- 추측 GT 저장, force push, 파괴적 git

## 보고 형식

보고서는 다음 절대경로에 작성해.

`/Users/baek/petcam-lab/.worktrees/motion-skip-gt-guard/docs/handoff-prompts/2026-07-22-motion-skip-gt-guard-report.md`

반드시 포함:

- root cause와 production 감사 증거
- Task별 RED→GREEN
- 변경 파일·commit SHA·push/main/Vercel SHA
- migration 이름과 rollback probe 결과
- 새 canary 결과와 기존 6건 mutation 0 증거
- 테스트/build 결과, 미검증 항목, rollback
- 최종 판정: `MOTION_SKIP_GT_GUARD_VERIFIED` 또는 구체적인 `BLOCKED_*`

Stop Condition이 발생하면 우회하지 말고 증거와 함께 `BLOCKED_*`로 멈춰.

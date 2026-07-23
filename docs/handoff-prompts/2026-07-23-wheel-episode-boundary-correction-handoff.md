---
handoff_version: 1
task_id: wheel-episode-boundary-correction
execution_repo: /Users/baek/petcam-lab/.worktrees/wheel-episode-boundary-fix
plan_path: /Users/baek/petcam-lab/.worktrees/wheel-episode-boundary-fix/docs/superpowers/plans/2026-07-23-wheel-episode-boundary-correction.md
design_path: /Users/baek/petcam-lab/.worktrees/wheel-episode-boundary-fix/docs/superpowers/specs/2026-07-23-wheel-episode-boundary-correction-design.md
commit_sha: a99327593809fff69e10118a4caec4eaaac6033b
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: none
---

# Claude 실행 지시 — 쳇바퀴 에피소드 10분 경계 교정 1회

## 시작 계약

다음 순서와 경계를 그대로 지켜.

1. 아래 validator를 먼저 실행해.

```bash
cd /Users/baek/petcam-lab/.worktrees/wheel-episode-boundary-fix
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/petcam-lab/.worktrees/wheel-episode-boundary-fix/docs/handoff-prompts/2026-07-23-wheel-episode-boundary-correction-handoff.md
```

2. 출력이 다음 전문과 일치하지 않으면 아무것도 수정하지 말고 중단·보고해.

```text
HANDOFF_OK task=wheel-episode-boundary-correction repo=wheel-episode-boundary-fix commit=a9932759 runtime=none
```

3. `execution_repo`에서 다음을 재확인해.
   - branch: `codex/wheel-episode-boundary-fix`
   - HEAD: `a99327593809fff69e10118a4caec4eaaac6033b`
   - 허용된 초기 dirty 상태: 이 handoff 파일 1개만 untracked
   - 그 밖의 modified/staged/untracked가 있으면 fail-closed로 중단
4. `AGENTS.md` → design 전문 → plan 전문 → 기존 TEST-SHEET와 report 순으로 읽어.
5. `superpowers:executing-plans`, `superpowers:test-driven-development`,
   `superpowers:verification-before-completion`을 사용해 plan Task 1~6을 순서대로 실행해.

## 이 작업의 정확한 성격

새 v2 연구가 아니다. v1 시험지의 `그룹 전체 길이 ≤10분` 계약을 어긴 chaining 결함을 한 번
교정하는 salvage다.

독립 감사에서 확인한 기준 수치는 다음과 같아.

- 32개 그룹 중 19개가 600초 초과
- 위반 그룹 membership 296/326
- 최장 그룹 18,224초·118개 clip
- 원인은 `current - previous`만 검사해 5분 간격 clip이 수시간 연결된 것

이번 교정 뒤에도 품질이 애매하면 자동 중복 묶기를 폐기한다. 이를 피하려고 IR 범위 축소,
threshold 변경, ROI 변경, 모션 정지점 탐색을 추가하지 마.

## 반드시 지킬 구현 계약

- `max_inter_clip_gap_sec=600`과 `max_episode_span_sec=600`을 분리
- 정확히 600초는 포함, 600초 초과는 새 run
- 그룹 생성 직후 모든 span을 검증하고 위반 시 hard fail
- 기존 ROI·threshold·signature·frozen cohort byte-identical
- 기존 v1 artifact 수정·삭제 금지
- 커밋된 signature replay만 사용: DB/R2 접근 0
- 새 결과는 `experiments/wheel-episode-dedup-boundary-fix/`에만 생성
- owner verdict는 비워두고 추정해서 채우지 않음

## 판정 계약

기계 게이트를 모두 통과하면:

```text
BOUNDARY_CORRECTION_READY_FOR_OWNER_REVIEW
```

하나라도 실패하면:

```text
BOUNDARY_CORRECTION_REJECTED
```

`ADOPTED`, `PRODUCTION_READY`, `DEPLOYED`, `VERIFIED_FOR_AUTOMATION`을 주장하면 안 돼.
사람 검수 전에 main merge·UI 연결·canary를 수행하지 마.

## 금지 범위

- main merge, Vercel 배포, migration, production DB write
- Supabase/R2 GET·PUT·DELETE와 외부 네트워크
- GT·triage·session·activity·behavior·Python Evidence·VLM 수정
- 라벨링 웹 수정
- 자동 label/hold/skip
- 기존 v1 산출물 수정·삭제
- 새 threshold·ROI·mode-scope·후속 v2 연구
- primary checkout과 다른 worktree 수정
- reset/rebase/force push/commit rewrite

## Stop Point와 완료 보고

Task 1~6을 완료하고 feature branch를 push한 뒤 멈춰.

보고서는 다음 절대경로로 작성해.

```text
/Users/baek/petcam-lab/.worktrees/wheel-episode-boundary-fix/docs/handoff-prompts/2026-07-23-wheel-episode-boundary-correction-report.md
```

최종 응답에는 다음만 포함해.

1. machine verdict
2. RED→GREEN으로 닫은 root cause
3. 교정 전/후 그룹·membership·representatives·max span
4. known wheel 24개의 검토량 감소율
5. 7개 기계 게이트 결과
6. owner blind review 파일 절대경로와 필요한 사람 검수량
7. 전체 테스트 결과
8. task별 commit SHA, 최종 HEAD, local==origin, clean 여부
9. 금지동작 0 증거
10. main merge·배포·owner 판정 미실행 확인


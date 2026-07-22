# Motion Labeling v3 제외·보류 GT Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `hold/skip` 결정을 GT 저장이 조용히 `label`로 덮어쓰지 못하게 UI·API·DB에서 차단한다.

**Architecture:** 공유 순수 규칙으로 UI 상태를 고정하고, 상세 화면은 결정 성공 후 해당 목록으로 이동한다. forward-only migration이 GT 잠금 RPC의 최종 경합 경계를 강제하며 API는 안정 SQLSTATE를 409로 매핑한다.

**Tech Stack:** Next.js 14, TypeScript, Vitest, PostgreSQL/Supabase RPC, pytest

## Global Constraints

- 기존 `migrations/2026-07-22_motion_clip_labeling_v3.sql` 수정 금지.
- 기존 6건의 triage/session/GT/event 자동 보정 금지.
- `unreviewed` owner 직접 라벨링과 `label` owner/labeler 흐름 유지.
- `LABELING_QUEUE_SOURCE=legacy` 유지.
- VLM, Python Evidence, behavior/activity, legacy/tutorial 데이터 쓰기 금지.
- TDD RED→GREEN, task별 conventional commit, force push 금지.

---

### Task 1: 공유 상태 규칙과 상세 UI 차단

**Files:**
- Modify: `web/src/lib/labelingV3.ts`
- Modify: `web/src/lib/labelingV3.test.ts`
- Modify: `web/src/app/labeling/motion/[clipId]/page.tsx`

**Interfaces:**
- Produces: `canWriteMotionGt(state: MotionLabelingState): boolean`
- Produces: `motionDecisionListPath(state: MotionLabelingState): string | null`

- [ ] **Step 1: failing tests 작성**

```ts
expect(canWriteMotionGt('unreviewed')).toBe(true);
expect(canWriteMotionGt('label')).toBe(true);
expect(canWriteMotionGt('hold')).toBe(false);
expect(canWriteMotionGt('skip')).toBe(false);
expect(motionDecisionListPath('hold')).toBe('/labeling/motion?state=hold');
expect(motionDecisionListPath('skip')).toBe('/labeling/motion?state=skip');
expect(motionDecisionListPath('label')).toBeNull();
```

- [ ] **Step 2: RED 확인**

Run from `web/`:

```bash
npm test -- src/lib/labelingV3.test.ts
```

Expected: helper export가 없어 FAIL.

- [ ] **Step 3: 최소 순수 구현**

```ts
export function canWriteMotionGt(state: MotionLabelingState): boolean {
  return state === 'unreviewed' || state === 'label';
}

export function motionDecisionListPath(state: MotionLabelingState): string | null {
  return state === 'hold' || state === 'skip' ? `/labeling/motion?state=${state}` : null;
}
```

- [ ] **Step 4: 상세 화면에 규칙 연결**

- `actionsEnabled = videoReady && !videoFailed && canWriteMotionGt(detail.state)`로 고친다.
- `hold/skip`이면 안내 Card를 표시한다.
- `MotionDecisionControls.onDecided`에서 state를 갱신한 뒤 `motionDecisionListPath(next)`가 있으면 `router.push(path)`한다.
- 분류 버튼은 계속 활성화해 owner가 `라벨 대상으로 보내기`로 복구할 수 있게 한다.

- [ ] **Step 5: GREEN 확인 후 커밋**

```bash
npm test -- src/lib/labelingV3.test.ts
git add web/src/lib/labelingV3.ts web/src/lib/labelingV3.test.ts 'web/src/app/labeling/motion/[clipId]/page.tsx'
git commit -m "fix: 제외·보류 영상의 GT 입력 차단"
```

### Task 2: DB 최종 guard forward migration

**Files:**
- Create: `migrations/2026-07-22_motion_clip_gt_decision_guard.sql`
- Modify: `tests/test_motion_clip_labeling_v3_migration.py`

**Interfaces:**
- Produces: `fn_lock_motion_clip_gt`의 PT424 계약.

- [ ] **Step 1: migration contract RED 테스트 추가**

테스트는 신규 migration에 다음 토큰과 순서를 요구한다.

```python
assert "CREATE OR REPLACE FUNCTION public.fn_lock_motion_clip_gt" in sql
assert "owner_decision IN ('hold','skip')" in sql
assert "ERRCODE = 'PT424'" in sql
assert sql.index("ERRCODE = 'PT424'") < sql.index("INSERT INTO public.motion_clip_labeling_sessions")
```

기존 lock 순서·PT403·PT422·PT423·prediction/session 계약도 신규 함수 본문에 남아 있는지 확인한다.

- [ ] **Step 2: RED 확인**

```bash
uv run pytest -q tests/test_motion_clip_labeling_v3_migration.py
```

Expected: 신규 migration 파일이 없어 FAIL.

- [ ] **Step 3: forward-only migration 구현**

기존 함수 전체를 복사하되 triage row를 잠근 직후, session 조회·write 전에 아래 guard를 둔다.

```sql
IF p_is_owner
   AND v_triage.clip_id IS NOT NULL
   AND v_triage.owner_decision IN ('hold','skip') THEN
  RAISE EXCEPTION 'decision_blocks_labeling' USING ERRCODE = 'PT424';
END IF;
```

`unreviewed` row 없음/owner_decision NULL과 `label`은 기존 로직을 유지한다. migration은 idempotent `CREATE OR REPLACE`와 rollback 설명을 포함한다.

- [ ] **Step 4: GREEN 확인 후 커밋**

```bash
uv run pytest -q tests/test_motion_clip_labeling_v3_migration.py
git add migrations/2026-07-22_motion_clip_gt_decision_guard.sql tests/test_motion_clip_labeling_v3_migration.py
git commit -m "fix: 제외·보류 GT 잠금 DB guard 추가"
```

### Task 3: API 안정 오류 계약

**Files:**
- Modify: `web/src/lib/labelingV3Server.ts`
- Modify: `web/src/lib/labelingV3Server.test.ts`
- Modify: `web/src/app/api/labeling-v3/[clipId]/gt/route.test.ts`
- Modify: `web/src/app/labeling/motion/[clipId]/page.tsx`

**Interfaces:**
- Consumes: DB SQLSTATE `PT424`.
- Produces: HTTP 409 `{ code: 'decision_blocks_labeling' }`.

- [ ] **Step 1: RED 테스트 작성**

```ts
const res = motionRpcErrorResponse({ code: 'PT424', message: 'raw secret' });
expect(res?.status).toBe(409);
expect(await res?.json()).toEqual({
  detail: '보류 또는 제외된 영상이야. 먼저 라벨 대상으로 보내줘.',
  code: 'decision_blocks_labeling',
});
```

GT route test는 RPC PT424가 409이고 Postgres 원문을 응답하지 않는지 고정한다.

- [ ] **Step 2: RED 확인**

```bash
npm test -- src/lib/labelingV3Server.test.ts 'src/app/api/labeling-v3/[clipId]/gt/route.test.ts'
```

- [ ] **Step 3: 오류 매핑과 client 안내 구현**

`RPC_ERROR_MAP`에 PT424를 추가한다. 페이지의 `lockGt` catch에서 이 code는 동일한 사용자 문구로 보여주고 detail을 reload해 stale 화면을 복구한다. 다른 오류 처리는 변경하지 않는다.

- [ ] **Step 4: GREEN 확인 후 커밋**

```bash
npm test -- src/lib/labelingV3Server.test.ts 'src/app/api/labeling-v3/[clipId]/gt/route.test.ts'
git add web/src/lib/labelingV3Server.ts web/src/lib/labelingV3Server.test.ts 'web/src/app/api/labeling-v3/[clipId]/gt/route.test.ts' 'web/src/app/labeling/motion/[clipId]/page.tsx'
git commit -m "fix: 분류 상태 충돌을 안정 409로 노출"
```

### Task 4: 전체 회귀와 독립 리뷰

**Files:**
- Modify only when a real finding requires it.

- [ ] **Step 1: focused + full verification**

```bash
cd web
npm test
npx tsc --noEmit
cd ..
uv run pytest -q
git diff --check
```

`npm run build`는 사용자 터미널 훅이 막으면 정확한 명령을 보고하고 미실행을 숨기지 않는다.

- [ ] **Step 2: 정적 금지 감사**

- 기존 migration 수정 0.
- 기존 6건 UUID를 migration/script에 하드코딩 0.
- session/GT/triage DELETE·UPDATE backfill 0.
- legacy/VLM/Evidence/activity write 0.

- [ ] **Step 3: 보고서 초안 작성**

Create: `docs/handoff-prompts/2026-07-22-motion-skip-gt-guard-report.md`.

RED→GREEN, 변경 파일, 테스트 결과, 미실행 운영 항목을 분리한다.

- [ ] **Step 4: 커밋·push**

```bash
git add docs/handoff-prompts/2026-07-22-motion-skip-gt-guard-report.md
git commit -m "docs: 제외·보류 GT guard 구현 보고"
git push -u origin codex/motion-skip-gt-guard
```

### Task 5: production 적용과 canary

**Files:**
- Modify: `docs/handoff-prompts/2026-07-22-motion-skip-gt-guard-report.md`
- Modify: `docs/DATABASE.md`
- Modify: `docs/FEATURES.md`
- Modify: `specs/next-session.md`
- Modify: `.claude/donts-audit.md`

- [ ] **Step 1: main FF-only 통합**

disposable clean worktree에서 `origin/main`이 feature HEAD의 ancestor인지 확인한 뒤 `--ff-only`만 사용한다. force push 금지.

- [ ] **Step 2: production migration apply 전 probe**

신규 migration만 적용하고 transaction rollback probe를 실행한다.

```text
skip → GT lock = PT424, session/event delta 0
hold → GT lock = PT424, session/event delta 0
unreviewed owner → label + gt_locked
label owner/labeler → gt_locked
```

probe row는 rollback 후 0이어야 한다. 실패하면 Vercel 배포 전에 중단한다.

- [ ] **Step 3: production deploy**

main push 후 Vercel Ready를 확인한다. `LABELING_QUEUE_SOURCE`는 변경하지 않는다.

- [ ] **Step 4: browser canary**

기존 6건이 아닌 새 미분류·재생가능 clip 1건에서 owner가 `제외`를 누른다.

- 제외 탭으로 자동 이동.
- 카드 배지 `제외`.
- 상세 재진입 시 GT 비활성+안내.
- 직접 GT POST는 409 `decision_blocks_labeling`.
- 그 후 `라벨 대상으로 보내기`를 누르면 GT 작성 가능.

canary는 최종적으로 `reset`해도 되지만 event는 append-only로 남는다. 기존 6건은 변경하지 않는다.

- [ ] **Step 5: SOT·보고서 최종화 후 commit/push**

production SHA, migration 이름, probe, canary, rollback을 보고서에 기록한다. 실행 repo clean, local main==origin/main을 확인한다.

## Stop Conditions

- handoff mismatch/dirty tracked tree, non-FF, 테스트·build 실패
- PT424 전에 session/event write 발생
- 기존 6건 또는 기존 GT/session에 mutation 발생
- legacy 기본 큐나 VLM/Evidence/activity 데이터 변화
- canary가 제외 탭에 남지 않거나 GT POST가 성공함

# `motion_clips` 네이티브 운영 라벨링 v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** product owner가 모든 production `motion_clips`를 최신순으로 찾아 직접 라벨링하고, 명시적으로 `label`로 보낸 영상만 일반 라벨러가 처리하는 운영 라벨링 v3를 만든다.

**Architecture:** legacy `camera_clips` 기반 v2·튜토리얼은 그대로 유지하고, `motion_clips` FK를 쓰는 triage/session/revision 테이블과 `/api/labeling-v3/**`, `/labeling/motion/**`를 독립 추가한다. 구현 handoff는 preview-ready 코드까지만 수행하고 production migration·배포·기본 `/labeling` 전환은 별도 검수·승인 뒤 실행한다.

**Tech Stack:** PostgreSQL/Supabase RLS·RPC, Next.js 14 App Router, TypeScript, React, Vitest, Python migration contract tests, Cloudflare R2 signed URL.

## Global Constraints

- 설계 정본은 `docs/superpowers/specs/2026-07-22-motion-clips-native-labeling-design.md`다.
- 신규 운영 영상 정본은 `motion_clips`; `camera_clips` mirror INSERT/UPDATE는 0이어야 한다.
- owner는 `motion_clips.owner_id`와 무관하게 모든 운영 영상을 본다. owner의 사전 승인은 직접 라벨링 조건이 아니다.
- 일반 라벨러는 `owner_decision='label'`, R2 재생 가능, 본인 completed 아님인 영상만 본다.
- GT 잠금 전 VLM·Python Evidence·Gate·selection reason을 API/UI에 노출하지 않는다.
- Local VLM Evidence GT study 테이블·API·artifact를 읽거나 쓰지 않는다.
- 기존 `/api/labeling-v2/**`, `/labeling/tutorial/**`, `clip_labeling_sessions`, `behavior_labels` 의미를 바꾸지 않는다.
- migration은 forward-only 신규 파일 한 개로 시작하고 적용된 기존 migration을 수정하지 않는다.
- 구현 handoff에서 production migration apply, Vercel deploy, main merge, 대량 seed, worker 실행은 금지한다.
- Task별 RED→GREEN과 지정 파일만 commit한다. force push·reset·다른 worktree 수정은 금지한다.
- 공용 `/labeling/page.tsx` 기본 전환은 Task 9 Gate가 통과할 때만 한다. 불통과면 숨은 `/labeling/motion` preview까지 완성하고 `V3_PREVIEW_READY_INTEGRATION_BLOCKED`로 멈춘다.

---

## File/Module Map

### Database

- Create `migrations/2026-07-22_motion_clip_labeling_v3.sql` — v3 triage/events/sessions/revisions, DB guards, service-role RPC.
- Create `tests/test_motion_clip_labeling_v3_migration.py` — static migration contract and rollback-probe marker tests.

### Pure/shared TypeScript

- Create `web/src/lib/labelingV3.ts` — public enums/types, state parser, response-safe mappers.
- Create `web/src/lib/labelingV3.test.ts` — pure contract tests.
- Create `web/src/lib/labelingV3Server.ts` — server-only access, DB row mapping, VLM snapshot selection, public DB error mapping.
- Create `web/src/lib/labelingV3Server.test.ts` — raw field/redaction and prediction selection tests.
- Create `web/src/lib/labelingV3Api.ts` — browser client isolated from the large legacy `labelingApi.ts`.

### API

- Create `web/src/app/api/labeling-v3/queue/route.ts` and `.test.ts`.
- Create `web/src/app/api/labeling-v3/cameras/route.ts` and `.test.ts`.
- Create `web/src/app/api/labeling-v3/[clipId]/route.ts` and `.test.ts`.
- Create `web/src/app/api/labeling-v3/[clipId]/file/url/route.ts` and `.test.ts`.
- Create `web/src/app/api/labeling-v3/[clipId]/decision/route.ts` and `.test.ts`.
- Create `web/src/app/api/labeling-v3/[clipId]/gt/route.ts` and `.test.ts`.
- Create `web/src/app/api/labeling-v3/[clipId]/vlm-review/route.ts` and `.test.ts`.
- Create `web/src/app/api/labeling-v3/[clipId]/revise/route.ts` and `.test.ts`.

### UI

- Create `web/src/app/labeling/_motion-filter-bar.tsx` — v3 camera/state/media filters only.
- Create `web/src/app/labeling/_motion-queue.tsx` — owner all view and labeler queue.
- Create `web/src/app/labeling/motion/page.tsx` — hidden preview entry.
- Create `web/src/app/labeling/motion/[clipId]/page.tsx` — v3 blind GT/detail flow.
- Create `web/src/app/labeling/motion/_motion-decision-controls.tsx` — owner label/hold/skip/reset.
- Modify only after Gate: `web/src/app/labeling/page.tsx` — final default-source wrapper.
- Create only after Gate: `web/src/app/labeling/_legacy-queue.tsx`, `web/src/app/labeling/legacy/page.tsx`.
- Modify only after Gate: `web/.env.example` — `LABELING_QUEUE_SOURCE=legacy` rollback-safe default.

### Docs/report

- Create `docs/handoff-prompts/2026-07-22-motion-clips-native-labeling-report.md`.
- Modify after implementation: `.claude/donts-audit.md`, `docs/DATABASE.md`, `docs/FEATURES.md`.
- Do not modify `specs/next-session.md` until production deployment is actually verified.

---

### Task 0: Handoff and concurrent-work ownership gate

**Files:**
- Read: `AGENTS.md`
- Read: `docs/superpowers/specs/2026-07-22-motion-clips-native-labeling-design.md`
- Read: `docs/superpowers/plans/2026-07-22-motion-clips-native-labeling.md`
- Read: `.claude/rules/donts.md`
- Create: `docs/handoff-prompts/2026-07-22-motion-clips-native-labeling-report.md`

**Interfaces:**
- Consumes: handoff manifest validated by `scripts/verify_agent_handoff.py`.
- Produces: `shared_web_gate = clear | defer_default_switch` recorded in report §1.

- [ ] **Step 1: Verify handoff exactly**

Run:

```bash
cd /Users/baek/petcam-lab/.worktrees/motion-clips-labeling-native
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/.codex/handoffs/2026-07-22-motion-clips-native-labeling-handoff.md
```

Expected: `HANDOFF_OK task=motion-clips-native-labeling repo=motion-clips-labeling-native commit=<8hex> runtime=none`. Any other result is a hard stop.

- [ ] **Step 2: Verify branch and workspace ownership**

Run:

```bash
test "$(git branch --show-current)" = "codex/motion-clips-labeling-native"
test -z "$(git status --porcelain)"
git fetch origin --prune
git merge-base --is-ancestor origin/main HEAD
git -C /Users/baek/petcam-lab/.worktrees/local-vlm-evidence-web-gt status --short --branch
git diff --name-only origin/main...origin/codex/local-vlm-evidence-web-gt -- \
  web/src/app/labeling web/src/lib/labelingApi.ts web/src/lib/labelingV2.ts
```

Decision:

```text
active worktree dirty OR upstream ahead/unmerged paths include shared Web files
  => shared_web_gate=defer_default_switch
otherwise
  => shared_web_gate=clear
```

Do not stop Tasks 1–8 for `defer_default_switch`; only Task 9 default switch is prohibited.

- [ ] **Step 3: Run baseline tests**

Run:

```bash
uv run pytest -q
cd web && npm test && npx tsc --noEmit
```

Expected baseline: Python 660+, Web 374+, TypeScript exit 0. If a baseline fails, record exact failures and stop without code edits.

- [ ] **Step 4: Start report with immutable scope**

Create the report with:

```markdown
# `motion_clips` 네이티브 운영 라벨링 v3 구현 보고

## 1. 시작 계약
- HANDOFF_OK: `<verbatim>`
- starting HEAD: `<40-char SHA>`
- shared_web_gate: `clear | defer_default_switch`
- forbidden: production migration/deploy/main merge/mirror/Evidence GT mutation
```

- [ ] **Step 5: Commit the gate report skeleton**

```bash
git add docs/handoff-prompts/2026-07-22-motion-clips-native-labeling-report.md
git commit -m "docs: motion labeling v3 구현 시작 계약"
```

---

### Task 1: Database schema, invariants, and service-role RPC

**Files:**
- Create: `migrations/2026-07-22_motion_clip_labeling_v3.sql`
- Create: `tests/test_motion_clip_labeling_v3_migration.py`

**Interfaces:**
- Produces tables: `motion_clip_labeling_triage`, `motion_clip_labeling_triage_events`, `motion_clip_labeling_sessions`, `motion_clip_labeling_session_revisions`.
- Produces RPCs: `fn_list_motion_clip_labeling_queue`, `fn_decide_motion_clip_labeling`, `fn_lock_motion_clip_gt`, `fn_complete_motion_clip_vlm_review`, `fn_revise_motion_clip_gt`.
- Queue RPC cursor inputs: `p_cursor_started_at timestamptz`, `p_cursor_id uuid`; ordering `(started_at DESC, id DESC)`.

Exact RPC signatures:

```sql
fn_list_motion_clip_labeling_queue(
  p_reviewer_id uuid,
  p_is_owner boolean,
  p_state text default null,
  p_camera_ids uuid[] default null,
  p_date_from timestamptz default null,
  p_date_to timestamptz default null,
  p_media text default null,
  p_cursor_started_at timestamptz default null,
  p_cursor_id uuid default null,
  p_limit integer default 31
) returns table (
  clip_id uuid, camera_id uuid, camera_name text, started_at timestamptz,
  duration_sec double precision, media_ready boolean, state text,
  session_stage text, state_updated_at timestamptz
);

fn_decide_motion_clip_labeling(
  p_clip_id uuid, p_actor_id uuid, p_decision text,
  p_expected_updated_at timestamptz default null, p_note text default null
) returns public.motion_clip_labeling_triage;

fn_lock_motion_clip_gt(
  p_clip_id uuid, p_reviewer_id uuid, p_is_owner boolean,
  p_gt jsonb, p_prediction_snapshot jsonb default null
) returns public.motion_clip_labeling_sessions;

fn_complete_motion_clip_vlm_review(
  p_clip_id uuid, p_reviewer_id uuid, p_verdict text,
  p_error_tags text[] default '{}', p_review_note text default null
) returns public.motion_clip_labeling_sessions;

fn_revise_motion_clip_gt(
  p_clip_id uuid, p_actor_id uuid, p_new_gt jsonb, p_reason text
) returns public.motion_clip_labeling_sessions;
```

- [ ] **Step 1: Write failing migration contract tests**

Tests must assert exact SQL tokens and reject weakened contracts:

```python
def test_v3_tables_reference_motion_clips_and_never_camera_clips(sql: str):
    assert "references public.motion_clips(id)" in sql.lower()
    assert "references public.camera_clips" not in sql.lower()

def test_v3_tables_are_service_role_only(sql: str):
    lower = sql.lower()
    for table in V3_TABLES:
        assert f"alter table public.{table} enable row level security" in lower
        assert f"revoke all on table public.{table} from anon" in lower
        assert f"revoke all on table public.{table} from authenticated" in lower

def test_queue_order_is_started_at_then_id_desc(sql: str):
    assert "order by m.started_at desc, m.id desc" in sql.lower()

def test_append_only_guards_cover_update_delete_truncate(sql: str):
    assert "tg_op in ('update', 'delete', 'truncate')" in sql.lower()
```

Also assert: enum CHECKs, note length 10–500 when non-null, session GT immutability, row locks, started-session skip rejection, stale version rejection, fixed `search_path`, service_role-only EXECUTE, no behavior/Evidence tables.

- [ ] **Step 2: Run tests to verify RED**

```bash
uv run pytest -q tests/test_motion_clip_labeling_v3_migration.py
```

Expected: FAIL because migration is missing.

- [ ] **Step 3: Implement migration**

Use these exact state contracts:

```sql
owner_decision text check (owner_decision in ('label','hold','skip'))
stage text not null default 'draft'
  check (stage in ('draft','gt_locked','completed'))
completion_reason text
  check (completion_reason in ('vlm_reviewed','no_prediction'))
unique (clip_id, reviewed_by)
```

`fn_list_motion_clip_labeling_queue` must:

```sql
ORDER BY m.started_at DESC, m.id DESC
LIMIT LEAST(GREATEST(p_limit, 1), 100)
```

and apply the keyset boundary:

```sql
p_cursor_started_at IS NULL
OR m.started_at < p_cursor_started_at
OR (m.started_at = p_cursor_started_at AND m.id < p_cursor_id)
```

Owner branch does not compare `m.owner_id` with product owner. Labeler branch requires
`t.owner_decision='label'`, `m.r2_key IS NOT NULL`, and no completed session for `p_reviewer_id`.

All five RPCs must validate inputs, lock `motion_clips` then triage/session in the same order, and raise stable SQLSTATE/code messages used by API mapping. Never accept reviewer, actor, prediction snapshot, or stage from untrusted JSON.

- [ ] **Step 4: Run migration tests GREEN**

```bash
uv run pytest -q tests/test_motion_clip_labeling_v3_migration.py
uv run pytest -q
```

Expected: new migration tests pass and full Python suite remains green.

- [ ] **Step 5: Commit**

```bash
git add migrations/2026-07-22_motion_clip_labeling_v3.sql tests/test_motion_clip_labeling_v3_migration.py
git commit -m "feat: motion clip 라벨링 v3 DB 계약"
```

---

### Task 2: Pure v3 types, validation, and safe server mapping

**Files:**
- Create: `web/src/lib/labelingV3.ts`
- Create: `web/src/lib/labelingV3.test.ts`
- Create: `web/src/lib/labelingV3Server.ts`
- Create: `web/src/lib/labelingV3Server.test.ts`

**Interfaces:**
- Produces `MotionLabelingState = 'unreviewed' | 'label' | 'hold' | 'skip'`.
- Produces `MotionQueueItem`, `MotionQueueResponse`, `MotionClipDetail`, `MotionLabelingSession`.
- Produces `mapMotionQueueRow`, `mapMotionDetailRow`, `selectLatestSucceededPrediction`, `motionLabelingDatabaseError`.

- [ ] **Step 1: Write failing pure tests**

Cover:

```ts
expect(parseMotionState(null)).toBe('unreviewed');
expect(parseMotionState('label')).toBe('label');
expect(() => parseMotionState('quarantine')).toThrow('invalid_motion_state');

expect(mapMotionQueueRow(raw)).toEqual({
  id: raw.clip_id,
  camera_id: raw.camera_id,
  camera_name: raw.camera_name,
  started_at: raw.started_at,
  duration_sec: raw.duration_sec,
  media_ready: true,
  state: 'unreviewed',
  session_stage: null,
});
expect(JSON.stringify(mapMotionQueueRow(raw))).not.toContain('r2_key');
expect(JSON.stringify(mapMotionQueueRow(raw))).not.toContain('evidence');
```

Prediction tests must accept only `status='succeeded'` with object `result`, order by completed timestamp then id, and return a deep-cloned snapshot. Failed/retryable/terminal jobs return null.

- [ ] **Step 2: Run focused tests RED**

```bash
cd web
npx vitest run src/lib/labelingV3.test.ts src/lib/labelingV3Server.test.ts
```

Expected: module-not-found failures.

- [ ] **Step 3: Implement public contracts**

Required public queue shape:

```ts
export interface MotionQueueItem {
  id: string;
  camera_id: string;
  camera_name: string;
  started_at: string;
  duration_sec: number;
  media_ready: boolean;
  state: MotionLabelingState;
  session_stage: 'draft' | 'gt_locked' | 'completed' | null;
}
```

`labelingV3Server.ts` starts with `import 'server-only'`. Its public error response is always:

```ts
NextResponse.json(
  { detail: '서버 처리 중 오류가 발생했어. 잠시 후 다시 시도해.' },
  { status: 502 },
)
```

Raw DB errors go only to server `console.error('[labeling-v3] database error', error)`.

- [ ] **Step 4: Run focused and full Web tests GREEN**

```bash
cd web
npx vitest run src/lib/labelingV3.test.ts src/lib/labelingV3Server.test.ts
npm test
npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/labelingV3.ts web/src/lib/labelingV3.test.ts \
  web/src/lib/labelingV3Server.ts web/src/lib/labelingV3Server.test.ts
git commit -m "feat: motion labeling v3 타입과 서버 경계"
```

---

### Task 3: Role-aware queue and camera APIs

**Files:**
- Create: `web/src/app/api/labeling-v3/queue/route.ts`
- Create: `web/src/app/api/labeling-v3/queue/route.test.ts`
- Create: `web/src/app/api/labeling-v3/cameras/route.ts`
- Create: `web/src/app/api/labeling-v3/cameras/route.test.ts`
- Create: `web/src/lib/labelingV3Api.ts`

**Interfaces:**
- Consumes existing `requireLabelingAccess`, `decodeQueueCursor`, `encodeQueueCursor`.
- Produces `getMotionQueue(filters)`, `getMotionCameras()` browser functions.
- Queue params: `limit`, `cursor`, `camera_id`, `date_from`, `date_to`, `state`, `media`.

- [ ] **Step 1: Write failing route tests**

Tests must prove:

```ts
expect(rpc).toHaveBeenCalledWith('fn_list_motion_clip_labeling_queue', expect.objectContaining({
  p_is_owner: true,
  p_reviewer_id: 'product-owner',
}));
expect(rpcArgs).not.toHaveProperty('p_owner_id');
```

and:

- owner can request `all`, `unreviewed`, `label`, `hold`, `skip`.
- labeler-supplied `state=skip` is ignored or rejected 403; labeler always gets label queue.
- invalid RFC3339, UUID, state, media, limit, or cursor returns stable 400 without RPC.
- `next_cursor` preserves DB timestamp verbatim.
- response contains no `r2_key`, owner UUID, evidence, prediction, or raw DB message.
- cameras owner branch returns all production cameras; labeler branch returns only cameras represented in label queue.

- [ ] **Step 2: Run tests RED**

```bash
cd web
npx vitest run \
  src/app/api/labeling-v3/queue/route.test.ts \
  src/app/api/labeling-v3/cameras/route.test.ts
```

- [ ] **Step 3: Implement routes and client**

Queue response:

```ts
export interface MotionQueueResponse {
  items: MotionQueueItem[];
  next_cursor: string | null;
  has_more: boolean;
}
```

Fetch `limit + 1` from the RPC, map only the first `limit`, and create cursor from the last returned item. The camera route must never reuse legacy `/labels/filter-options`.

- [ ] **Step 4: Run focused/full tests and typecheck**

```bash
cd web
npx vitest run src/app/api/labeling-v3/queue/route.test.ts src/app/api/labeling-v3/cameras/route.test.ts
npm test
npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add web/src/app/api/labeling-v3/queue web/src/app/api/labeling-v3/cameras web/src/lib/labelingV3Api.ts
git commit -m "feat: motion clip 최신순 큐와 카메라 API"
```

---

### Task 4: Motion clip detail and R2 media APIs

**Files:**
- Create: `web/src/app/api/labeling-v3/[clipId]/route.ts`
- Create: `web/src/app/api/labeling-v3/[clipId]/route.test.ts`
- Create: `web/src/app/api/labeling-v3/[clipId]/file/url/route.ts`
- Create: `web/src/app/api/labeling-v3/[clipId]/file/url/route.test.ts`
- Modify: `web/src/lib/labelingV3Api.ts`

**Interfaces:**
- Produces `getMotionClip(clipId)` and `getMotionClipFileUrl(clipId)`.
- Detail output excludes VLM/evidence until session stage is `gt_locked|completed`.

- [ ] **Step 1: Write failing detail/media tests**

Cover owner all-clip access, labeler label-only access, invalid UUID 400, unauthorized 404, missing source 404, state-changed 409, null R2 410, signing failure 502, and response redaction.

Required pre-lock assertion:

```ts
expect(detail.session?.stage ?? 'draft').toBe('draft');
expect(detail).not.toHaveProperty('prediction');
expect(JSON.stringify(detail)).not.toContain('rank_features');
expect(JSON.stringify(detail)).not.toContain('motion_summary');
```

- [ ] **Step 2: Run tests RED**

```bash
cd web
npx vitest run \
  'src/app/api/labeling-v3/[clipId]/route.test.ts' \
  'src/app/api/labeling-v3/[clipId]/file/url/route.test.ts'
```

- [ ] **Step 3: Implement detail/media routes**

The media route must re-read `motion_clips.r2_key` server-side, call the existing R2 signed URL helper, and return only `{ url, expires_in }`. Product owner bypasses clip ownership but not bearer validation. Labeler must still satisfy triage label and tutorial access.

- [ ] **Step 4: Run focused/full tests and typecheck**

```bash
cd web
npx vitest run 'src/app/api/labeling-v3/[clipId]/**/*.test.ts'
npm test
npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add web/src/app/api/labeling-v3/'[clipId]' web/src/lib/labelingV3Api.ts
git commit -m "feat: motion clip 상세와 R2 재생 API"
```

---

### Task 5: Owner triage decisions and concurrency guards

**Files:**
- Create: `web/src/app/api/labeling-v3/[clipId]/decision/route.ts`
- Create: `web/src/app/api/labeling-v3/[clipId]/decision/route.test.ts`
- Modify: `web/src/lib/labelingV3Api.ts`

**Interfaces:**
- Produces `decideMotionClip(clipId, { decision, expected_updated_at, note })`.
- Decisions: `label | hold | skip | reset`.

- [ ] **Step 1: Write failing tests**

Tests prove owner-only, note trimmed length 10–500 when present, stale maps 409 `stale_state`, active session skip maps 409 `labeling_started`, invalid enum 400, RPC payload actor comes from bearer not body, DB message redacted.

```ts
expect(rpc).toHaveBeenCalledWith('fn_decide_motion_clip_labeling', {
  p_clip_id: clipId,
  p_actor_id: 'product-owner',
  p_decision: 'label',
  p_expected_updated_at: current,
  p_note: null,
});
```

- [ ] **Step 2: Run test RED**

```bash
cd web
npx vitest run 'src/app/api/labeling-v3/[clipId]/decision/route.test.ts'
```

- [ ] **Step 3: Implement route/client and stable error mapping**

Map only stable DB codes to public 409. Unknown DB errors use `motionLabelingDatabaseError` 502. Never echo PostgreSQL text.

- [ ] **Step 4: Run focused/full tests and typecheck**

```bash
cd web
npx vitest run 'src/app/api/labeling-v3/[clipId]/decision/route.test.ts'
npm test
npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add web/src/app/api/labeling-v3/'[clipId]'/decision web/src/lib/labelingV3Api.ts
git commit -m "feat: motion clip owner 분류와 경합 방어"
```

---

### Task 6: Blind GT lock, VLM review, and owner revision APIs

**Files:**
- Create: `web/src/app/api/labeling-v3/[clipId]/gt/route.ts`
- Create: `web/src/app/api/labeling-v3/[clipId]/gt/route.test.ts`
- Create: `web/src/app/api/labeling-v3/[clipId]/vlm-review/route.ts`
- Create: `web/src/app/api/labeling-v3/[clipId]/vlm-review/route.test.ts`
- Create: `web/src/app/api/labeling-v3/[clipId]/revise/route.ts`
- Create: `web/src/app/api/labeling-v3/[clipId]/revise/route.test.ts`
- Modify: `web/src/lib/labelingV3Api.ts`

**Interfaces:**
- Reuses `GroundTruthInput` validation from `labelingV2.ts` without changing it.
- Produces `lockMotionGt`, `completeMotionVlmReview`, `reviseMotionGt`.

- [ ] **Step 1: Write failing GT tests**

Tests must prove:

- owner may lock any media-ready clip without prior label decision.
- owner direct lock calls one RPC that creates/updates triage label and session atomically.
- labeler may lock only owner-labeled clip.
- client cannot submit prediction, reviewer, stage, initial_gt, or completion timestamps.
- latest succeeded `clip_vlm_jobs` result is selected; failed jobs are ignored.
- no succeeded result completes as `no_prediction` without inventing a snapshot.
- initial GT mutation is rejected.
- revise is owner-only, reason 10–500, append-only revision written.
- behavior_labels, Evidence GT, activity, Python Evidence tables are never called.

Example negative assertion:

```ts
expect(from.mock.calls.map(([table]) => table)).not.toContain('behavior_labels');
expect(from.mock.calls.map(([table]) => table)).not.toContain('local_vlm_evidence_annotations');
```

- [ ] **Step 2: Run tests RED**

```bash
cd web
npx vitest run \
  'src/app/api/labeling-v3/[clipId]/gt/route.test.ts' \
  'src/app/api/labeling-v3/[clipId]/vlm-review/route.test.ts' \
  'src/app/api/labeling-v3/[clipId]/revise/route.test.ts'
```

- [ ] **Step 3: Implement the three routes**

GT input is validated with the existing strict v2 validator. Server chooses prediction snapshot and passes it to `fn_lock_motion_clip_gt`; the client never does. Review verdict enum remains `correct | partially_correct | incorrect | unjudgeable`.

- [ ] **Step 4: Run focused/full tests and typecheck**

```bash
cd web
npx vitest run 'src/app/api/labeling-v3/[clipId]/**/*.test.ts'
npm test
npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add web/src/app/api/labeling-v3/'[clipId]'/gt \
  web/src/app/api/labeling-v3/'[clipId]'/vlm-review \
  web/src/app/api/labeling-v3/'[clipId]'/revise \
  web/src/lib/labelingV3Api.ts
git commit -m "feat: motion clip blind GT와 VLM 검수 API"
```

---

### Task 7: Owner all-video queue and filters at hidden preview path

**Files:**
- Create: `web/src/app/labeling/_motion-filter-bar.tsx`
- Create: `web/src/app/labeling/_motion-queue.tsx`
- Create: `web/src/app/labeling/motion/page.tsx`
- Create: `web/src/lib/labelingV3QueueClient.ts`
- Create: `web/src/lib/labelingV3QueueClient.test.ts`

**Interfaces:**
- Consumes `getMotionQueue`, `getMotionCameras`, existing `DateControls`, cursor timestamp helper, `createRequestGeneration`.
- Produces hidden owner/labeler preview `/labeling/motion`.

- [ ] **Step 1: Write failing queue-client tests**

Tests cover microsecond ordering, id tie-break, dedup, stale generation, and query serialization:

```ts
expect(mergeMotionQueueItems([], [older, newer])).toEqual([newer, older]);
expect(toMotionQueueQuery({ state: 'hold', camera_id: [cam], date_from, date_to }))
  .toContain('state=hold');
```

- [ ] **Step 2: Run tests RED**

```bash
cd web
npx vitest run src/lib/labelingV3QueueClient.test.ts
```

- [ ] **Step 3: Implement filters and queue UI**

Owner tabs: `전체 영상 | 라벨 대기 | 보류 | 제외`. Labeler sees no tabs and is fixed to label queue. Default owner filter is all, default sort is newest. Cards show camera, KST timestamp, duration, state, and `원본 재생 불가` badge; no VLM/evidence fields.

Every async `response`, `catch`, and `finally` path must check `requestGeneration.isCurrent(generation)`. Filters persist in URL. Motion cards link only to `/labeling/motion/{clipId}`.

- [ ] **Step 4: Run tests/typecheck and build**

```bash
cd web
npx vitest run src/lib/labelingV3QueueClient.test.ts
npm test
npx tsc --noEmit
npm run build
```

Expected: hidden route appears in build output, existing routes remain.

- [ ] **Step 5: Commit**

```bash
git add web/src/app/labeling/_motion-filter-bar.tsx \
  web/src/app/labeling/_motion-queue.tsx web/src/app/labeling/motion/page.tsx \
  web/src/lib/labelingV3QueueClient.ts web/src/lib/labelingV3QueueClient.test.ts
git commit -m "feat: owner 전체 운영영상 최신순 큐"
```

---

### Task 8: Motion clip detail, owner controls, and reusable blind forms

**Files:**
- Create: `web/src/app/labeling/motion/[clipId]/page.tsx`
- Create: `web/src/app/labeling/motion/_motion-decision-controls.tsx`
- Modify only if required and conflict-free: `web/src/app/labeling/_labeling-forms.tsx`
- Test: `web/src/lib/labelingV3.test.ts`

**Interfaces:**
- Consumes v3 detail/media/decision/GT/review/revise client functions.
- Reuses current GroundTruth and VLM review forms with unchanged field meaning.

- [ ] **Step 1: Add failing state-machine tests**

Pure tests cover UI phases:

```ts
expect(decideMotionDetailPhase({ session: null, media_ready: true })).toBe('gt');
expect(decideMotionDetailPhase({ session: { stage: 'gt_locked' } })).toBe('review');
expect(decideMotionDetailPhase({ session: { stage: 'completed' } })).toBe('complete');
expect(decideMotionDetailPhase({ session: null, media_ready: false })).toBe('media_blocked');
```

- [ ] **Step 2: Run test RED**

```bash
cd web
npx vitest run src/lib/labelingV3.test.ts
```

- [ ] **Step 3: Implement detail page and decision controls**

User flow must be exactly:

```text
load detail -> load signed URL -> onLoadedMetadata enables actions
owner direct GT save -> atomic label + gt_locked
prediction exists -> review form
prediction absent -> no_prediction completion
completed owner -> optional revision panel
```

Clip/filter changes invalidate item and media request generations. Video failure shows retry and disables GT/decisions. Owner decisions require confirmation only for skip; label/hold/reset stay reversible. Do not expose internal enum labels without Korean display text.

- [ ] **Step 4: Run full verification**

```bash
cd web
npm test
npx tsc --noEmit
npm run build
cd ..
uv run pytest -q
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add web/src/app/labeling/motion web/src/lib/labelingV3.ts web/src/lib/labelingV3.test.ts
git diff --cached --check
git commit -m "feat: motion clip 직접 라벨링 화면"
```

---

### Task 9: Default `/labeling` integration gate

**Files:**
- Create if gate clear: `web/src/app/labeling/_legacy-queue.tsx`
- Create if gate clear: `web/src/app/labeling/legacy/page.tsx`
- Modify if gate clear: `web/src/app/labeling/page.tsx`
- Modify if gate clear: `web/.env.example`
- Create/Modify: `web/src/app/labeling/page.test.ts` only if project test setup supports component import without DOM; otherwise lock the decision in pure `labelingV3.ts` tests.

**Interfaces:**
- Consumes `shared_web_gate` from Task 0.
- Produces either default integration or explicit blocked verdict.

- [ ] **Step 1: Re-run concurrent ownership gate**

```bash
git fetch origin --prune
git -C /Users/baek/petcam-lab/.worktrees/local-vlm-evidence-web-gt status --short --branch
git diff --name-only origin/main...origin/codex/local-vlm-evidence-web-gt -- \
  web/src/app/labeling/page.tsx web/src/app/labeling/'[clipId]'/page.tsx \
  web/src/app/labeling/_labeling-forms.tsx web/src/lib/labelingApi.ts
```

If dirty/unintegrated overlapping work exists, do not edit shared files. Record `V3_PREVIEW_READY_INTEGRATION_BLOCKED`, skip Steps 2–5, and continue Task 10 verification.

- [ ] **Step 2: Write failing source-selection test when gate is clear**

Lock:

```ts
expect(resolveLabelingQueueSource('motion')).toBe('motion');
expect(resolveLabelingQueueSource('legacy')).toBe('legacy');
expect(resolveLabelingQueueSource(undefined)).toBe('legacy');
expect(resolveLabelingQueueSource('bad')).toBe('legacy');
```

- [ ] **Step 3: Extract legacy queue and add default wrapper**

Move the current client body unchanged into `_legacy-queue.tsx`. `/labeling/legacy` renders it. `/labeling/page.tsx` is a server wrapper:

```tsx
import LegacyQueue from './_legacy-queue';
import MotionQueue from './_motion-queue';
import { resolveLabelingQueueSource } from '@/lib/labelingV3';

export default function LabelingPage() {
  return resolveLabelingQueueSource(process.env.LABELING_QUEUE_SOURCE) === 'motion'
    ? <MotionQueue />
    : <LegacyQueue />;
}
```

Default remains legacy in code. Preview deploy sets `LABELING_QUEUE_SOURCE=motion`; production switch is outside this handoff.
Add `LABELING_QUEUE_SOURCE=legacy` plus a comment to `web/.env.example`; do not change local or production env.

- [ ] **Step 4: Run verification**

```bash
cd web
npm test
npx tsc --noEmit
npm run build
```

- [ ] **Step 5: Commit shared integration separately**

```bash
git add web/src/app/labeling/page.tsx web/src/app/labeling/_legacy-queue.tsx \
  web/src/app/labeling/legacy/page.tsx web/src/lib/labelingV3.ts web/src/lib/labelingV3.test.ts \
  web/.env.example
git commit -m "feat: 운영 라벨링 v3 전환 경계"
```

---

### Task 10: Adversarial review, docs, and implementation stop report

**Files:**
- Modify: `docs/handoff-prompts/2026-07-22-motion-clips-native-labeling-report.md`
- Modify: `docs/DATABASE.md`
- Modify: `docs/FEATURES.md`
- Modify: `.claude/donts-audit.md`

**Interfaces:**
- Produces verdict `V3_PREVIEW_READY_FOR_DEPLOY_REVIEW`, `V3_PREVIEW_READY_INTEGRATION_BLOCKED`, or `V3_IMPLEMENTATION_BLOCKED`.

- [ ] **Step 1: Run forbidden-behavior audit**

```bash
rg -n "camera_clips.*insert|from\(['\"]behavior_labels|local_vlm_evidence|clip_python_evidence_runs|clip_prelabels|clip_activity_assessments" \
  web/src/app/api/labeling-v3 web/src/lib/labelingV3* migrations/2026-07-22_motion_clip_labeling_v3.sql
```

Expected: no executable forbidden write/read. Test strings/comments must be identified explicitly.

- [ ] **Step 2: Run full verification**

```bash
uv run pytest -q
cd web
npm test
npx tsc --noEmit
npm run build
cd ..
git diff --check
git status --short
```

Expected: all suites green; only intended docs changes remain before final docs commit.

- [ ] **Step 3: Review eight adversarial dimensions**

Record PASS/FAIL evidence for:

1. owner access accidentally scoped by `motion_clips.owner_id`
2. labeler access leakage outside `owner_decision=label`
3. GT pre-lock prediction/evidence leakage
4. cursor microsecond truncation or duplicate/gap
5. skip/session race and stale state
6. raw R2 key/DB error/secret leakage
7. legacy tutorial/v2 behavior regression
8. `camera_clips` mirror or Evidence GT mutation

Any P0/P1 or unresolved contract failure yields `V3_IMPLEMENTATION_BLOCKED`.

- [ ] **Step 4: Update docs truthfully**

Document schema/API as **implemented but not production-applied**. Do not claim `/labeling` production switch, migration apply, owner smoke, or Vercel deployment.

- [ ] **Step 5: Finish report**

Required sections:

```markdown
## 변경 파일과 task별 commit
## RED→GREEN 증거
## 전체 테스트·build
## shared_web_gate와 기본 전환 여부
## 금지동작 0 증거
## 미실행: migration apply / deploy / main merge / production write
## 다음 deployment handoff의 Gate A~F
## 최종 verdict
```

- [ ] **Step 6: Commit docs and push branch**

```bash
git add docs/DATABASE.md docs/FEATURES.md .claude/donts-audit.md \
  docs/handoff-prompts/2026-07-22-motion-clips-native-labeling-report.md
git diff --cached --check
git commit -m "docs: motion labeling v3 구현 검증 보고"
git push origin codex/motion-clips-labeling-native
test -z "$(git status --porcelain)"
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/codex/motion-clips-labeling-native)"
```

Stop. Do not merge main, apply migration, deploy Vercel, alter production settings, or write canary GT in this handoff.

---

## Post-implementation deployment gates — this handoff must not execute

1. **Gate A:** Codex independent diff review and migration adversarial review.
2. **Gate B:** preview migration apply + rollback probe, residue 0.
3. **Gate C:** preview owner/labeler E2E and hidden `/labeling/motion` playback.
4. **Gate D:** production schema/API deploy with default legacy.
5. **Gate E:** owner canary — latest clip, all three cameras, 2번 캠 41건, one GT transaction.
6. **Gate F:** explicit owner approval, then `LABELING_QUEUE_SOURCE=motion` production redeploy; rollback remains legacy.

Only a new tracked deployment plan and new HANDOFF_OK may execute these gates.

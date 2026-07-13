# Labeling Interactive Tutorial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 승인된 신규 라벨러가 지정된 5개 영상에서 Blind GT와 VLM 검수를 연습하고 해설을 모두 확인한 뒤에만 일반 라벨링 큐에 들어가게 한다.

**Architecture:** Tutorial v1 콘텐츠와 사용자 attempt/progress를 Supabase 전용 테이블에 저장하고 production `behavior_labels`·`clip_labeling_sessions`와 분리한다. 기존 validator와 영상 UI는 재사용하지만 저장 API는 tutorial 전용으로 분리한다. 일반 큐와 clip API에는 server-side tutorial completion gate를 추가하고 owner만 bypass한다.

**Tech Stack:** Next.js 14 App Router, TypeScript, Supabase Auth/Postgres/service_role, Vitest, Tailwind CSS, Vercel

## Global Constraints

- SOT는 `docs/superpowers/specs/2026-07-13-labeling-interactive-tutorial-design.md`다.
- 완료 조건은 active tutorial lesson 5개의 feedback acknowledge이며 점수 합격선은 없다.
- tutorial answer/reference/comparison은 `behavior_labels`와 `clip_labeling_sessions`에 기록하지 않는다.
- reference GT와 해설은 VLM review 최초 제출 전 HTML·client props·API 응답·로그에 포함하지 않는다.
- owner는 tutorial gate를 bypass한다. 일반 labeler는 completed 또는 waived여야 일반 큐·clip API를 사용한다.
- active tutorial은 정확히 하나, lesson은 정확히 5개다.
- active lesson 콘텐츠는 불변이며 수정은 새 version으로 한다.
- reset은 과거 attempt를 삭제하지 않고 `current_run_no`를 증가시킨다.
- 모든 신규 테이블은 RLS ENABLE, anon/authenticated 정책 0건, service_role 전용이다.
- 실제 clip UUID와 비밀값은 커밋하지 않는다.
- DB→draft 콘텐츠→preview→activation→실계정 E2E→production 순서를 지킨다.

---

## File Map

### Create

- `migrations/2026-07-13_labeling_tutorial.sql` — set/lesson/progress/attempt schema, immutability trigger, activation/completion RPC
- `migrations/2026-07-13_labeling_tutorial_seed.example.sql` — 실제 UUID 없는 Tutorial v1 seed 템플릿
- `web/src/lib/labelingTutorial.ts` — tutorial types, stage transition, comparison, public response projection
- `web/src/lib/labelingTutorial.test.ts` — comparison·stage·reference redaction unit tests
- `web/src/lib/labelingTutorialAccess.ts` — active set/progress 조회와 production gate
- `web/src/lib/labelingTutorialAccess.test.ts` — owner/completed/waived/incomplete/error gate tests
- `web/src/app/api/labeling-tutorial/route.ts` — tutorial summary
- `web/src/app/api/labeling-tutorial/lessons/[position]/route.ts` — lesson state
- `web/src/app/api/labeling-tutorial/lessons/[position]/gt/route.ts` — tutorial GT lock
- `web/src/app/api/labeling-tutorial/lessons/[position]/vlm-review/route.ts` — review submit + feedback reveal
- `web/src/app/api/labeling-tutorial/lessons/[position]/acknowledge/route.ts` — lesson/progress completion
- `web/src/app/api/labeling-tutorial/lessons/[position]/thumbnail/url/route.ts` — tutorial-scoped thumbnail URL
- `web/src/app/api/labeling-tutorial/lessons/[position]/file/url/route.ts` — tutorial-scoped playback URL
- `web/src/app/api/labeling-tutorial/team-progress/route.ts` — owner progress list
- `web/src/app/api/labeling-tutorial/users/[userId]/reset/route.ts` — owner run reset
- `web/src/app/api/labeling-tutorial/users/[userId]/waive/route.ts` — owner waiver
- `web/src/app/labeling/tutorial/page.tsx` — intro/progress/lesson list/final summary
- `web/src/app/labeling/tutorial/[position]/page.tsx` — tutorial labeling state machine
- `web/src/components/labeling/ClipReviewPlayer.tsx` — reusable video/frame/speed controls
- `web/src/components/labeling/GroundTruthForm.tsx` — reusable GT form
- `web/src/components/labeling/VlmReviewForm.tsx` — reusable VLM review form
- focused route tests beside existing route-test convention, or `web/src/lib/labelingTutorialRoutes.test.ts` if route tests are currently centralized

### Modify

- `web/src/lib/labelingAccess.ts` — tutorial info in access response, `requireProductionLabelingAccess`
- `web/src/lib/labelingAccessGuards.test.ts` — production gate regression
- `web/src/lib/clipPerms.ts` — general clip routes use production gate
- `web/src/lib/labelingApi.ts` — tutorial client contracts
- `web/src/app/api/labeling-access/route.ts` — enriched access response
- `web/src/app/api/labeling-v2/queue/route.ts` — production gate
- `web/src/app/labeling/layout.tsx` — tutorial route category, redirect and header badge
- `web/src/app/labeling/login/page.tsx` — approved incomplete user destination
- `web/src/app/labeling/[clipId]/page.tsx` — extract shared player/forms without behavior change
- `web/src/app/labeling/team/page.tsx` — progress, reset, waive
- `docs/DATABASE.md`, `docs/FEATURES.md`, `docs/LABELER-ONBOARDING.md`, `specs/next-session.md`

---

### Task 1: Tutorial domain contract and comparison

**Files:**
- Create: `web/src/lib/labelingTutorial.ts`
- Create: `web/src/lib/labelingTutorial.test.ts`
- Consume: `web/src/lib/labelingV2.ts`

**Interfaces:**

```ts
export type TutorialAttemptStage =
  | 'draft'
  | 'gt_locked'
  | 'review_submitted'
  | 'completed';

export interface TutorialComparison {
  matched: string[];
  review: string[];
  subjective: string[];
}

export function compareTutorialAnswers(input: {
  submittedGt: GroundTruthInput;
  referenceGt: GroundTruthInput;
  submittedReview: VlmReviewInput;
  referenceReview: VlmReviewInput;
}): TutorialComparison;

export function nextTutorialStage(
  current: TutorialAttemptStage,
  event: 'lock_gt' | 'submit_review' | 'acknowledge',
): TutorialAttemptStage;

export function projectTutorialLesson(
  row: TutorialLessonRow,
  attempt: TutorialAttemptRow | null,
): TutorialLessonResponse;
```

- [ ] **Step 1: Write failing comparison and redaction tests**

```ts
it('treats action sets as unordered and segment boundaries within one second as matched', () => {
  const result = compareTutorialAnswers({
    submittedGt: gt({
      observed_actions: ['moving', 'wheel_interaction'],
      segments: [{ action: 'moving', start_sec: 1.8, end_sec: 5.9 }],
    }),
    referenceGt: gt({
      observed_actions: ['wheel_interaction', 'moving'],
      segments: [{ action: 'moving', start_sec: 1, end_sec: 5 }],
    }),
    submittedReview: review(),
    referenceReview: review(),
  });
  expect(result.matched).toContain('observed_actions');
  expect(result.matched).toContain('segments');
});

it('does not expose reference or feedback before review submission', () => {
  const response = projectTutorialLesson(lesson(), attempt({ stage: 'gt_locked' }));
  expect(response).not.toHaveProperty('reference_gt');
  expect(response).not.toHaveProperty('reference_vlm_review');
  expect(response).not.toHaveProperty('feedback_content');
});
```

- [ ] **Step 2: Run RED**

Run: `cd web && npm test -- labelingTutorial.test.ts`

Expected: FAIL because the module and functions do not exist.

- [ ] **Step 3: Implement the pure domain module**

Comparison rules must be literal:

```ts
const EXACT_GT_FIELDS = [
  'visibility',
  'primary_action',
  'target',
  'activity_intensity',
  'enrichment_object',
] as const;
const SET_GT_FIELDS = ['observed_actions', 'interaction_types'] as const;
const SUBJECTIVE_FIELDS = ['human_confidence', 'context_tags', 'note'] as const;
const SEGMENT_TOLERANCE_SEC = 1;
```

Sort copies of array values; do not mutate submitted/reference JSON. Match segments by action and
require the same number of segments for that action, with both boundaries within 1 second. VLM
verdict is exact and `error_tags` is an unordered set. `projectTutorialLesson` includes reference,
comparison and feedback only for `review_submitted` or `completed`.

- [ ] **Step 4: Run GREEN and full domain regression**

Run: `cd web && npm test -- labelingTutorial.test.ts labelingV2.test.ts`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/labelingTutorial.ts web/src/lib/labelingTutorial.test.ts
git commit -m "feat: 튜토리얼 답안 비교·상태 계약"
```

---

### Task 2: Supabase schema, immutability and activation contract

**Files:**
- Create: `migrations/2026-07-13_labeling_tutorial.sql`
- Create: `migrations/2026-07-13_labeling_tutorial_seed.example.sql`
- Modify: `docs/DATABASE.md`

**Interfaces:**

```sql
public.fn_activate_labeling_tutorial(p_set_id uuid, p_owner_id uuid) returns void
public.fn_acknowledge_tutorial_lesson(
  p_user_id uuid, p_set_id uuid, p_lesson_id uuid, p_run_no integer
) returns public.labeling_tutorial_progress
```

- [ ] **Step 1: Write the migration with four service-role tables**

Implement the exact columns and constraints from design §9. Required constraints:

```sql
create unique index uq_one_active_labeling_tutorial
  on public.labeling_tutorial_sets ((status)) where status = 'active';

alter table public.labeling_tutorial_lessons
  add constraint labeling_tutorial_position_check check (position between 1 and 5),
  add constraint labeling_tutorial_set_position_unique unique (tutorial_set_id, position),
  add constraint labeling_tutorial_set_clip_unique unique (tutorial_set_id, clip_id);

alter table public.labeling_tutorial_attempts
  add constraint labeling_tutorial_attempt_stage_check
    check (stage in ('draft', 'gt_locked', 'review_submitted', 'completed')),
  add constraint labeling_tutorial_attempt_unique
    unique (tutorial_set_id, lesson_id, user_id, run_no);
```

All UUID user columns reference `auth.users(id)`. Use `timestamptz`, not `timestamp`. Add
`idx_labeling_tutorial_attempt_user_run` on `(user_id, tutorial_set_id, run_no, stage)`.

- [ ] **Step 2: Add RLS and grants**

For all four tables:

```sql
alter table public.<table> enable row level security;
revoke all on table public.<table> from public, anon, authenticated;
grant all on table public.<table> to service_role;
```

Do not create client policies. Revoke RPC execution from public/anon/authenticated and grant only
to service_role.

- [ ] **Step 3: Add immutability trigger**

The trigger must reject changes to an attempt's non-null `submitted_gt`,
`submitted_vlm_review`, or `comparison`. It may update stage/timestamps. Add an active-lesson
trigger rejecting changes to `clip_id`, reference snapshots and feedback when parent set status is
`active` or `archived`.

- [ ] **Step 4: Add activation and acknowledge RPCs**

Activation must lock the set row, verify caller matches `DEV_USER_ID` at the Next.js layer, verify
status=`draft`, count exactly 5 positions `1..5`, require non-null reference GT/prediction/reference
review/feedback for each, archive the previous active set, then activate this set atomically.

Acknowledge must lock progress and attempt, require attempt stage=`review_submitted` or
`completed`, mark it completed idempotently, count completed lessons for the current run, and set
progress `completed_at=now()` only when count=5.

- [ ] **Step 5: Create a secret-free seed template**

The example file must use psql variables, never real UUIDs:

```sql
-- Usage in a private SQL session only:
-- \set owner_id 'OWNER_UUID'
-- \set clip_1 'CLIP_UUID'
-- ... clip_5
-- The committed example must not contain production identifiers.
```

It must demonstrate copying `current_gt`, `prediction_snapshot`, `vlm_verdict` and
`vlm_error_tags` from the owner's completed `clip_labeling_sessions` into draft lessons. It must
abort if any source session is incomplete or lacks a prediction.

- [ ] **Step 6: Validate migration in a transaction or disposable database**

Run the repository's existing SQL validation path. If no disposable DB is configured, run a static
check and include the exact production verification queries at the bottom of the migration:

```sql
select status, count(*) from public.labeling_tutorial_sets group by status;
select tutorial_set_id, count(*), min(position), max(position)
from public.labeling_tutorial_lessons group by tutorial_set_id;
select schemaname, tablename, count(*)
from pg_policies
where tablename like 'labeling_tutorial_%'
group by schemaname, tablename;
```

- [ ] **Step 7: Document and commit**

```bash
git add migrations/2026-07-13_labeling_tutorial.sql \
  migrations/2026-07-13_labeling_tutorial_seed.example.sql docs/DATABASE.md
git commit -m "feat: 라벨링 튜토리얼 DB 계약"
```

---

### Task 3: Tutorial progress and production access gate

**Files:**
- Create: `web/src/lib/labelingTutorialAccess.ts`
- Create: `web/src/lib/labelingTutorialAccess.test.ts`
- Modify: `web/src/lib/labelingAccess.ts`
- Modify: `web/src/lib/labelingAccessGuards.test.ts`
- Modify: `web/src/lib/clipPerms.ts`
- Modify: `web/src/app/api/labeling-access/route.ts`
- Modify: `web/src/app/api/labeling-v2/queue/route.ts`

**Interfaces:**

```ts
export type TutorialStatus =
  | 'not_started'
  | 'in_progress'
  | 'completed'
  | 'waived'
  | 'unavailable';

export interface TutorialAccessInfo {
  required: boolean;
  status: TutorialStatus;
  completed_lessons: number;
  total_lessons: 5;
}

export async function getTutorialAccess(userId: string, isOwner: boolean): Promise<TutorialAccessInfo>;
export async function requireProductionLabelingAccess(req: NextRequest): Promise<LabelingAccessResult>;
```

- [ ] **Step 1: Write failing gate tests**

Cover owner bypass, completed, waived, 0/5, 4/5, active set missing and Supabase error. Assert
incomplete/unavailable returns 403 with `{ detail: 'tutorial_required' }`; DB failure returns generic
502 and logs internal details.

- [ ] **Step 2: Run RED**

Run: `cd web && npm test -- labelingTutorialAccess.test.ts labelingAccessGuards.test.ts`

- [ ] **Step 3: Implement tutorial access lookup**

Query one active set, then the user's progress and completed attempt count for current run. Owner
returns `{required:false,status:'completed',completed_lessons:5,total_lessons:5}` without DB
dependency. Active set missing returns `unavailable`, never completed.

- [ ] **Step 4: Enrich `GET /api/labeling-access`**

Keep `status` semantics unchanged and add `tutorial`. Pending/rejected/unregistered users get
`required:false` because they cannot access video anyway. Only `labeler` receives tutorial state.

- [ ] **Step 5: Apply server gate to production data paths**

Change `loadClipWithPerms` to call `requireProductionLabelingAccess`. Change the v2 queue route's
direct guard likewise. Use `rg "requireLabelingAccess|loadClipWithPerms" web/src/app/api` to audit
all general clip/GT/VLM/media/download routes. Tutorial routes must continue using the membership
gate, not the production gate.

- [ ] **Step 6: Run focused and full tests**

Run:

```bash
cd web
npm test -- labelingTutorialAccess.test.ts labelingAccessGuards.test.ts
npm test
npx tsc --noEmit
```

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/labelingTutorialAccess.ts \
  web/src/lib/labelingTutorialAccess.test.ts web/src/lib/labelingAccess.ts \
  web/src/lib/labelingAccessGuards.test.ts web/src/lib/clipPerms.ts \
  web/src/app/api/labeling-access/route.ts web/src/app/api/labeling-v2/queue/route.ts
git commit -m "feat: 튜토리얼 완료 전 본 큐 접근 차단"
```

---

### Task 4: Tutorial API state machine and media isolation

**Files:**
- Create all `web/src/app/api/labeling-tutorial/**` labeler routes listed in File Map
- Modify: `web/src/lib/labelingApi.ts`
- Test: focused tutorial route tests

**Interfaces:**

```ts
export interface TutorialSummaryResponse {
  tutorial: { id: string; version: string; title: string } | null;
  status: TutorialStatus;
  current_run_no: number;
  completed_lessons: number;
  total_lessons: 5;
  lessons: Array<{
    position: number;
    title: string;
    learning_objective: string;
    stage: TutorialAttemptStage | 'locked';
  }>;
}
```

- [ ] **Step 1: Write route tests before handlers**

Required cases:

- unauthenticated 401
- non-labeler 403
- lesson position outside 1..5 returns 400
- future lesson before previous acknowledge returns 409 and `current_position`
- GT uses `validateGroundTruth`
- GT response contains prediction but no reference keys
- review before GT returns 409
- review response contains reference/comparison/feedback
- acknowledge before review returns 409
- fifth acknowledge completes progress
- same POST payload is idempotent; different payload after lock returns 409
- tutorial media accepts only the active lesson's clip and returns 404 for arbitrary UUID

- [ ] **Step 2: Run RED**

Run the focused route test file and confirm missing handlers/functions fail.

- [ ] **Step 3: Implement shared server helpers**

Keep route duplication low with internal helpers in `web/src/app/api/labeling-tutorial/_helpers.ts`:

```ts
loadActiveTutorial(): Promise<TutorialSetRow | null>
loadTutorialContext(userId: string, position: number): Promise<TutorialContext>
loadCurrentAttempt(context: TutorialContext): Promise<TutorialAttemptRow | null>
assertPreviousLessonsComplete(context: TutorialContext): Promise<void>
```

Never serialize raw lesson rows from Supabase. Always pass through `projectTutorialLesson`.

- [ ] **Step 4: Implement GT lock**

Use `validateGroundTruth(body, clip.duration_sec)`. Insert/update only tutorial attempts. Copy the
lesson's frozen prediction into the response but do not copy it into production sessions. An
existing different GT returns 409; exact JSON equality returns the existing attempt.

- [ ] **Step 5: Implement review and feedback reveal**

Use `validateVlmReview`. Compute comparison server-side from immutable submitted/reference values,
save it once, return the projected response. Do not accept comparison/reference from the client.

- [ ] **Step 6: Implement acknowledge via RPC**

Call `fn_acknowledge_tutorial_lesson`; return updated progress and next position. Do not issue
multiple separate writes that could mark attempt completed without progress or vice versa.

- [ ] **Step 7: Implement scoped signed media URLs**

Reuse R2 signing functions, but look up clip only through active lesson membership. Tutorial does
not expose an original download endpoint; only thumbnail and playback URL are required.

- [ ] **Step 8: Add typed client functions**

Add `getTutorialSummary`, `getTutorialLesson`, `saveTutorialGt`, `saveTutorialVlmReview`,
`acknowledgeTutorialFeedback`, `getTutorialThumbnailUrl`, `getTutorialFileUrl` to
`labelingApi.ts`.

- [ ] **Step 9: Run verification and commit**

```bash
cd web
npm test -- labelingTutorial labelingTutorialRoutes
npm test
npx tsc --noEmit
git add src/app/api/labeling-tutorial src/lib/labelingApi.ts
git commit -m "feat: 대화형 튜토리얼 API 상태 머신"
```

---

### Task 5: Extract reusable labeling UI without behavior change

**Files:**
- Create: `web/src/components/labeling/ClipReviewPlayer.tsx`
- Create: `web/src/components/labeling/GroundTruthForm.tsx`
- Create: `web/src/components/labeling/VlmReviewForm.tsx`
- Modify: `web/src/app/labeling/[clipId]/page.tsx`

**Interfaces:**

```ts
<ClipReviewPlayer clipId videoUrl durationSec />
<GroundTruthForm value onChange durationSec disabled onSubmit submitLabel />
<VlmReviewForm prediction humanGt value onChange disabled onSubmit submitLabel />
```

- [ ] **Step 1: Record current production-page contract**

Add/retain focused tests for these visible states: Blind GT, GT locked/VLM review, completed,
no-prediction completion, frame ±1, speed selection, video timestamp/download header. Do not change
copy or API calls in this task.

- [ ] **Step 2: Run baseline tests**

Run: `cd web && npm test && npx tsc --noEmit`

- [ ] **Step 3: Extract player and forms mechanically**

Move existing JSX/state helpers from `[clipId]/page.tsx` into focused components. Production page
still owns data fetching and submit callbacks. Do not add tutorial conditionals to production page.

- [ ] **Step 4: Run regression tests**

Run: `cd web && npm test && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
git add web/src/components/labeling web/src/app/labeling/[clipId]/page.tsx
git commit -m "refactor: 라벨링 영상·GT·VLM 폼 공용화"
```

---

### Task 6: Tutorial summary/detail user experience

**Files:**
- Create: `web/src/app/labeling/tutorial/page.tsx`
- Create: `web/src/app/labeling/tutorial/[position]/page.tsx`
- Modify: `web/src/app/labeling/layout.tsx`
- Modify: `web/src/app/labeling/login/page.tsx`
- Modify: `web/src/lib/labelingApi.ts`

- [ ] **Step 1: Add pure redirect tests**

Export or move `categorize`/`redirectTarget` to a testable helper. Required assertions:

```ts
expect(redirectTarget(true, labelerIncomplete, 'tutorial')).toBeNull();
expect(redirectTarget(true, labelerIncomplete, 'work')).toBe('/labeling/tutorial');
expect(redirectTarget(true, labelerCompleted, 'work')).toBeNull();
expect(redirectTarget(true, ownerAccess, 'work')).toBeNull();
```

- [ ] **Step 2: Implement route category and navigation**

Add `tutorial` category before generic `work`. Show header button for owner/labeler. Incomplete
labeler sees `필수 · N/5`; completed sees `튜토리얼`; owner sees `미리보기`. Hide queue, 내 라벨
and router review links from incomplete labelers.

- [ ] **Step 3: Implement summary page**

Render intro, `약 15~25분`, no-pass explanation, progress bar and five lesson cards. Only the current
lesson is actionable; completed lessons offer `해설 다시 보기`; future lessons are visibly locked.
Unavailable state must say `튜토리얼 준비 중 · 관리자에게 문의해` and never link to queue.

- [ ] **Step 4: Implement detail state machine**

Use shared player/forms and tutorial APIs:

- draft → GT form
- gt_locked → frozen prediction + VLM form
- review_submitted → comparison/reference/feedback
- completed → read-only feedback + next

The feedback view must show `네 답`, `기준`, `왜`, `다음 영상에서`; do not show aggregate score,
pass/fail or other labelers' answers.

- [ ] **Step 5: Implement completion**

After fifth acknowledge, refresh access context so the header and route gate update without logout.
Show `라벨 대기 큐로 이동`; do not automatically discard the final feedback screen.

- [ ] **Step 6: Verify responsive behavior**

Use 390px and desktop viewport. Assert horizontal overflow is zero, video controls remain usable,
and feedback cards wrap. Check keyboard/frame controls still work.

- [ ] **Step 7: Run tests and commit**

```bash
cd web
npm test
npx tsc --noEmit
git add src/app/labeling/tutorial src/app/labeling/layout.tsx \
  src/app/labeling/login/page.tsx src/lib/labelingApi.ts
git commit -m "feat: 5단계 라벨링 튜토리얼 화면"
```

---

### Task 7: Owner progress, reset and waiver

**Files:**
- Create: owner API routes listed in File Map
- Modify: `web/src/app/labeling/team/page.tsx`
- Modify: `web/src/lib/labelingApi.ts`
- Test: owner API/access tests

- [ ] **Step 1: Write owner authorization and audit tests**

Cover non-owner 403, missing `DEV_USER_ID` 503, unknown user 404, reset preserving old run,
waiver reason trim 1..200, and Supabase error redaction.

- [ ] **Step 2: Implement owner APIs**

`team-progress` joins applications with active progress and current-run attempts. Return only
display_name/email/status, tutorial state, completed count and mismatch dimension counts. Do not
return full answer/reference JSON in list responses.

Reset locks progress, increments `current_run_no`, clears current completion/waiver fields and keeps
old attempts. Waive requires `{reason:string}` and records `waived_by` from `requireOwner`.

- [ ] **Step 3: Extend team UI**

Show `0/5`, `진행 중 N/5`, `완료`, `면제` badge on active labelers. Put `다시 시작` and `완료
면제` behind a confirm UI. The confirmation must explain reset does not delete history and waiver
opens production data access.

- [ ] **Step 4: Run verification and commit**

```bash
cd web
npm test
npx tsc --noEmit
git add src/app/api/labeling-tutorial/team-progress \
  src/app/api/labeling-tutorial/users src/app/labeling/team/page.tsx src/lib/labelingApi.ts
git commit -m "feat: 팀원 튜토리얼 진행 관리"
```

---

### Task 8: Documentation, release guard and full verification

**Files:**
- Modify: `docs/DATABASE.md`
- Modify: `docs/FEATURES.md`
- Modify: `docs/LABELER-ONBOARDING.md`
- Modify: `specs/next-session.md`
- Modify: `docs/superpowers/specs/2026-07-13-labeling-interactive-tutorial-design.md` status only

- [ ] **Step 1: Run fresh full verification**

```bash
uv run pytest
cd web
npm test
npx tsc --noEmit
cd ..
git diff --check
```

Expected current baseline or higher: Python 334 passing, Web 60 passing plus tutorial tests,
TypeScript exit 0, diff check clean.

- [ ] **Step 2: Run security audit**

Use `rg` to prove:

- reference fields only appear in post-review projection or owner/private server code
- tutorial routes use `requireLabelingAccess`
- general clip/queue routes use `requireProductionLabelingAccess` through direct guard or
  `loadClipWithPerms`
- no real UUID, secret or `.env` file entered the diff
- all tutorial tables have RLS and revoked client grants

Run `npm audit` and report pre-existing vs newly introduced findings. Do not use `npm audit fix
--force` without separate approval.

- [ ] **Step 3: Prepare release checklist without production mutation**

Document exact order and stop points:

1. apply tutorial SQL
2. verify tables/index/RLS/RPC
3. deploy web preview
4. owner reviews candidate 5 in production v2
5. execute private seed values
6. preview Tutorial v1 as owner
7. activate set
8. test account complete flow
9. production promotion only after explicit approval

- [ ] **Step 4: Update SOT truthfully**

Mark each layer as `implemented`, `preview verified`, or `production verified`; never collapse them.
Record deployment ID, test counts, active tutorial version and five clip IDs only in private
operational notes if clip IDs are considered sensitive. Do not mark Tutorial v1 complete before the
test-labeler E2E.

- [ ] **Step 5: Commit docs**

```bash
git add docs/DATABASE.md docs/FEATURES.md docs/LABELER-ONBOARDING.md \
  specs/next-session.md docs/superpowers/specs/2026-07-13-labeling-interactive-tutorial-design.md
git commit -m "docs: 라벨링 튜토리얼 검증·배포 기록"
```

---

## Claude Handoff Prompt

```text
docs/superpowers/specs/2026-07-13-labeling-interactive-tutorial-design.md를 제품 SOT로,
docs/superpowers/plans/2026-07-13-labeling-interactive-tutorial.md를 실행 계획으로 사용해.

Task 1부터 순서대로 TDD로 수행하고 각 Task 끝에 지정된 검증과 커밋을 완료해. tutorial
답안은 production behavior_labels/clip_labeling_sessions에 절대 쓰지 말고, reference는 VLM
review 제출 전 어떤 응답·HTML·로그에도 노출하지 마. 일반 큐·clip API의 tutorial gate는
client redirect가 아니라 서버에서 강제해. 실제 clip UUID를 커밋하거나 production DB·Vercel
production을 임의로 변경하지 마. DB 적용, private seed, active 전환, production 배포는 각각
사용자 승인을 받아. 완료 후 테스트 결과, 미적용 SQL, preview URL, 남은 E2E를 구분해 보고해.
```

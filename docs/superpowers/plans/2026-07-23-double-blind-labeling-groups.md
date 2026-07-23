# Group Double-Blind Labeling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 승인 라벨러 두 명이 담당 카메라의 같은 `motion_clips` 영상을 독립 판정하고, 결정론적으로 일치한 결과는 자동 합의하며 불일치만 owner가 최종 검수하게 한다.

**Architecture:** 기존 owner 중심 v3 테이블은 보존하고, group→camera→clip review slot→immutable blind submission→consensus를 새 forward migration으로 분리한다. 라벨러는 자기 slot만 보는 활동일 큐를 사용하고, 두 번째 제출 뒤 versioned TypeScript comparator와 digest를 DB finalize RPC가 원자 검증한다. Owner는 conflict 큐와 그룹 관리 화면만 추가로 사용한다.

**Tech Stack:** PostgreSQL/Supabase service-role RPC, Next.js 14 App Router, TypeScript, React, Vitest, pytest migration contract tests, existing `GroundTruthInput` validators.

## Global Constraints

- 활동일은 KST `07:00~다음 날 07:00`; 식은 `(started_at AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date`.
- 활성 그룹은 정확히 두 명이고, 하나의 카메라는 동시에 하나의 활성 그룹에만 속한다.
- 초기 운영 배정의 개인 이메일·auth UUID를 migration·소스·tracked 문서에 하드코딩하지 않는다. Production 적용 때 owner가 승인 계정을 관리 API로 매핑한다.
- 각 clip은 서로 다른 reviewer의 immutable 최초 제출 정확히 두 개를 요구한다. 한 명의 제출만으로 합의 완료하지 않는다.
- 상대 reviewer의 결정·GT·메모·제출 시각·UUID는 labeler API/UI에 노출하지 않는다. 진행 API는 집계만 반환한다.
- 합의는 `initial_gt`만 비교한다. AI/VLM prediction·evidence·`current_gt`는 비교 입력이 아니다.
- comparator version은 `motion-blind-v1`; segment 경계는 정수 millisecond로 비교하며 차이 `<=500ms`는 같고 `>=501ms`는 다르다.
- 개인 큐 cursor는 version, `(started_at,id)`, activity day, live/canary scope를 함께 담고 요청 scope와 다르면 400으로 거부한다.
- 배열은 중복 제거+canonical sort 후 비교하고 자유 메모는 비교에서 제외한다.
- 개인이 자기 우선 활동일을 끝내면 파트너와 무관하게 하루 전이 열린다. 늦은 clip은 우선 큐에 추가하되 이미 열린 과거 날짜를 잠그지 않는다.
- 새 migration은 forward-only다. `2026-07-22_motion_clip_labeling_v3.sql`과 `2026-07-22_motion_clip_gt_decision_guard.sql`을 수정하지 않는다.
- 새 테이블은 RLS ON, client policy 0, service-role only다. RPC는 `SECURITY INVOKER`, `SET search_path = ''`, 안정 SQLSTATE, row lock을 사용한다.
- 기존 owner v3, legacy v2, tutorial, VLM, Gate, Python Evidence, activity 계산을 변경하지 않는다.
- Task 8 owner 승인 전 migration apply·main merge·Vercel production deploy·production group mapping을 하지 않는다.

---

## File Structure

### New database and contracts

- `migrations/2026-07-23_motion_double_blind_labeling.sql` — group/member/camera/reviewer-progress/slot/submission/consensus/event/lease schema와 service-role RPC.
- `tests/test_motion_double_blind_labeling_migration.py` — migration 정적 계약과 rollback probe marker.
- `web/src/lib/motionBlindReview.ts` — 공개 타입, 활동일 계산, comparator, UI copy와 상태 규칙.
- `web/src/lib/motionBlindReview.test.ts` — comparator·날짜 unlock·표시 규칙.
- `web/src/lib/motionBlindReviewServer.ts` — RPC raw row mapper와 공개 필드 allowlist.
- `web/src/lib/motionBlindReviewServer.test.ts` — blind field 누출·오류 매핑 회귀.
- `web/src/lib/motionBlindReviewApi.ts` — browser API client.

### New labeler APIs

- `web/src/app/api/labeling-v3/blind/workspace/route.ts` — group/header/progress/활동일 목록.
- `web/src/app/api/labeling-v3/blind/workspace/route.test.ts`
- `web/src/app/api/labeling-v3/blind/canary/[cohortId]/route.ts` — open canary의 자기 slot·진행 집계.
- `web/src/app/api/labeling-v3/blind/canary/[cohortId]/route.test.ts`
- `web/src/app/api/labeling-v3/blind/queue/route.ts` — 개인 미제출 slot 최신순 keyset 큐.
- `web/src/app/api/labeling-v3/blind/queue/route.test.ts`
- `web/src/app/api/labeling-v3/blind/[clipId]/route.ts` — 자기 slot 상세; 상대 제출 0.
- `web/src/app/api/labeling-v3/blind/[clipId]/route.test.ts`
- `web/src/app/api/labeling-v3/blind/[clipId]/file/url/route.ts` — 자기 slot 확인 뒤 R2 URL.
- `web/src/app/api/labeling-v3/blind/[clipId]/file/url/route.test.ts`
- `web/src/app/api/labeling-v3/blind/[clipId]/claim/route.ts` — 같은 reviewer의 단일 탭 30분 lease 발급·갱신.
- `web/src/app/api/labeling-v3/blind/[clipId]/claim/route.test.ts`
- `web/src/app/api/labeling-v3/blind/[clipId]/submit/route.ts` — 최초 제출+consensus finalize.
- `web/src/app/api/labeling-v3/blind/[clipId]/submit/route.test.ts`

### New owner APIs

- `web/src/app/api/labeling-v3/blind/owner/conflicts/route.ts` — conflict keyset 목록.
- `web/src/app/api/labeling-v3/blind/owner/conflicts/route.test.ts`
- `web/src/app/api/labeling-v3/blind/owner/[clipId]/route.ts` — 두 최초 제출 side-by-side.
- `web/src/app/api/labeling-v3/blind/owner/[clipId]/route.test.ts`
- `web/src/app/api/labeling-v3/blind/owner/[clipId]/resolve/route.ts` — A/B/new owner resolution.
- `web/src/app/api/labeling-v3/blind/owner/[clipId]/resolve/route.test.ts`
- `web/src/app/api/labeling-v3/blind/owner/groups/route.ts` — approved user 기반 group/member/camera 관리.
- `web/src/app/api/labeling-v3/blind/owner/groups/route.test.ts`
- `web/src/app/api/labeling-v3/blind/owner/canary/route.ts` — 격리 canary cohort 생성·종료.
- `web/src/app/api/labeling-v3/blind/owner/canary/route.test.ts`

### New UI

- `web/src/app/labeling/_blind-review-queue.tsx` — labeler 활동일 큐.
- `web/src/app/labeling/_blind-review-progress.tsx` — 집계 숫자만 표시.
- `web/src/app/labeling/_blind-review-onboarding.tsx` — 1분 안내와 다시 열기.
- `web/src/app/labeling/blind/[clipId]/page.tsx` — 영상+3선택+GT 폼+draft/retry.
- `web/src/app/labeling/blind/canary/[cohortId]/page.tsx` — owner가 발급한 격리 canary 작업 진입점.
- `web/src/app/labeling/blind/canary/[cohortId]/[clipId]/page.tsx` — scope가 고정된 canary 영상 판정.
- `web/src/app/labeling/blind/conflicts/page.tsx` — owner conflict 목록.
- `web/src/app/labeling/blind/conflicts/[clipId]/page.tsx` — owner 비교·최종 판정.
- `web/src/app/labeling/blind/groups/page.tsx` — owner 그룹 관리.
- `web/src/app/labeling/_blind-review-ui.test.tsx` — onboarding/copy/progress/empty-state 순수 렌더 계약.

### Existing files to modify

- `web/src/app/labeling/page.tsx` — owner는 기존 `MotionQueue`, labeler는 `BlindReviewQueue`.
- `web/src/app/labeling/layout.tsx` — owner conflict/group nav, labeler 작업 방법 진입점.
- `web/src/app/labeling/_owner-context.tsx` — `useIsLabeler()` helper.
- `web/src/lib/labelingRouteAccess.ts` and test — 새 경로 접근 분류.
- `docs/FEATURES.md`, `docs/DATABASE.md`, `specs/next-session.md`, `.claude/donts-audit.md` — 운영 계약.

---

### Task 0: Handoff Gate and Baseline

**Files:**
- Read: `AGENTS.md`
- Read: `CLAUDE.md`
- Read: `.claude/rules/donts.md`
- Read: `docs/superpowers/specs/2026-07-23-double-blind-labeling-groups-design.md`
- Read: `docs/superpowers/plans/2026-07-23-double-blind-labeling-groups.md`
- Read: `docs/decision-gate.md`
- Read: `specs/next-session.md`

**Interfaces:**
- Consumes: tracked design+plan and handoff manifest.
- Produces: clean isolated implementation worktree with verified baseline.

- [ ] **Step 1: Validate the handoff before reading implementation files**

Run:

```bash
uv run python scripts/verify_agent_handoff.py --manifest /absolute/path/to/handoff.md
```

Expected: one `HANDOFF_OK` line whose `execution_repo`, 40-char commit, and host match the manifest. Any `HANDOFF_FAIL`, dirty tree, or HEAD mismatch is a hard stop.

- [ ] **Step 2: Record baseline state**

Run:

```bash
git status --short --branch
git rev-parse HEAD
git diff --check
```

Expected: implementation worktree clean; do not reset, delete, stage, or commit files owned by another session.

- [ ] **Step 3: Run baseline suites**

Run:

```bash
uv run pytest -q
cd web && npm test
cd web && npx tsc --noEmit
```

Expected at current base: Python `694 passed`; web and TypeScript must be green. If counts differ only because newer main adds tests, report exact fresh totals and require zero failures.

- [ ] **Step 4: Commit**

No commit. Task 0 is a gate.

---

### Task 1: Pure Domain Contract and Comparator

**Files:**
- Create: `web/src/lib/motionBlindReview.ts`
- Create: `web/src/lib/motionBlindReview.test.ts`

**Interfaces:**
- Consumes: `GroundTruthInput`, `isValidGroundTruthShape` from `web/src/lib/labelingV2.ts`.
- Produces:
  - `BlindDecision = 'label' | 'hold' | 'exclude'`
  - `BlindSubmissionInput`
  - `BlindComparison`
  - `activityDayBounds(day: string)`
  - `currentActivityDay(now: Date)`
  - `compareBlindSubmissions(a, b)`
  - `BLIND_COMPARATOR_VERSION = 'motion-blind-v1'`
  - user-facing decision copy.

- [ ] **Step 1: Write failing tests for activity-day and copy**

Add:

```ts
expect(activityDayBounds('2026-07-22')).toEqual({
  from: '2026-07-21T22:00:00.000Z',
  to: '2026-07-22T22:00:00.000Z',
});
expect(currentActivityDay(new Date('2026-07-23T00:30:00.000Z'))).toBe('2026-07-23');
expect(BLIND_DECISION_COPY.exclude.description).toContain('촬영');
expect(BLIND_DECISION_COPY.hold.description).not.toContain('관리자 확인');
```

- [ ] **Step 2: Write failing comparator tests**

Cover:

```ts
expect(compareBlindSubmissions(excludeA, excludeB).status).toBe('agreed');
expect(compareBlindSubmissions(
  exclude({ reason_code: 'gecko_absent' }),
  exclude({ reason_code: 'media_error' }),
).status).toBe('agreed');
expect(compareBlindSubmissions(excludeA, holdB).status).toBe('conflict');
expect(compareBlindSubmissions(label({ note: 'A' }), label({ note: 'B' })).status).toBe('agreed');
expect(compareBlindSubmissions(
  label({ observed_actions: ['moving', 'licking'] }),
  label({ observed_actions: ['licking', 'moving'] }),
).status).toBe('agreed');
expect(compareBlindSubmissions(
  label({ segments: [{ action: 'moving', start_sec: 1, end_sec: 2 }] }),
  label({ segments: [{ action: 'moving', start_sec: 1.5, end_sec: 2.5 }] }),
).status).toBe('agreed');
expect(compareBlindSubmissions(
  label({ segments: [{ action: 'moving', start_sec: 1, end_sec: 2 }] }),
  label({ segments: [{ action: 'moving', start_sec: 1.501, end_sec: 2 }] }),
).toMatchObject({ status: 'conflict', differing_fields: ['segments'] });
```

Also test malformed label GT rejection, duplicate array normalization, scalar mismatch, segment count/action mismatch, and that prediction/current GT fields cannot enter the input type.

- [ ] **Step 3: Run RED**

Run:

```bash
cd web && npx vitest run src/lib/motionBlindReview.test.ts
```

Expected: FAIL because module/functions do not exist.

- [ ] **Step 4: Implement the minimal pure contract**

Use these exact public shapes:

```ts
export const BLIND_COMPARATOR_VERSION = 'motion-blind-v1' as const;
export type BlindDecision = 'label' | 'hold' | 'exclude';

export interface BlindSubmissionInput {
  decision: BlindDecision;
  initial_gt: GroundTruthInput | null;
  note: string | null;
  reason_code: 'behavior_data' | 'ambiguous' | 'gecko_absent' | 'capture_error' | 'media_error';
}

export interface BlindComparison {
  status: 'agreed' | 'conflict';
  final_decision: BlindDecision | null;
  final_gt: GroundTruthInput | null;
  differing_fields: string[];
  comparator_version: typeof BLIND_COMPARATOR_VERSION;
}
```

Implement validation:

```ts
if (input.decision === 'label' && !isValidGroundTruthShape(input.initial_gt)) {
  throw new Error('label_requires_valid_initial_gt');
}
if (input.decision !== 'label' && input.initial_gt !== null) {
  throw new Error('non_label_forbids_initial_gt');
}
```

Canonicalize set fields with `[...new Set(values)].sort()`. Convert segment seconds with `Math.round(value * 1000)`, preserve segment order, require matching action/count, and compare both boundaries with `Math.abs(a - b) <= 500`. Build `differing_fields` in fixed `GroundTruthInput` field order. Exclude `note` from canonical GT comparison while preserving the original input.

- [ ] **Step 5: Run GREEN**

Run:

```bash
cd web && npx vitest run src/lib/motionBlindReview.test.ts
```

Expected: all focused tests pass.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/motionBlindReview.ts web/src/lib/motionBlindReview.test.ts
git commit -m "feat: 이중 블라인드 판정 비교 계약"
```

---

### Task 2: Forward Database Migration

**Files:**
- Create: `migrations/2026-07-23_motion_double_blind_labeling.sql`
- Create: `tests/test_motion_double_blind_labeling_migration.py`

**Interfaces:**
- Consumes: `motion_clips`, `cameras`, `labelers`, `labeler_applications`, auth UUIDs.
- Produces service-role-only tables and RPCs:
  - `fn_manage_motion_review_group`
  - `fn_ensure_motion_review_slots`
  - `fn_list_motion_blind_queue`
  - `fn_get_motion_blind_workspace`
  - `fn_claim_motion_review_slot`
  - `fn_submit_motion_blind_review`
  - `fn_finalize_motion_blind_consensus`
  - `fn_list_motion_blind_conflicts`
  - `fn_resolve_motion_blind_consensus`
  - `fn_reassign_motion_review_slot`
  - `fn_manage_motion_blind_canary`

- [ ] **Step 1: Write the failing migration contract**

Assert exact markers:

```py
assert "CREATE TABLE public.motion_labeling_review_groups" in sql
assert "CREATE TABLE public.motion_labeling_reviewer_progress" in sql
assert "CREATE TABLE public.motion_clip_review_slots" in sql
assert "CREATE TABLE public.motion_blind_review_cohorts" in sql
assert "CREATE TABLE public.motion_clip_blind_submissions" in sql
assert "CREATE TABLE public.motion_clip_consensus" in sql
assert "CREATE UNIQUE INDEX" in sql
assert "WHERE ended_at IS NULL" in sql
assert "SET search_path = ''" in sql
assert "FOR UPDATE" in sql
assert "motion-blind-v1" in sql
assert "ALTER TABLE public.motion_clip_blind_submissions ENABLE ROW LEVEL SECURITY" in sql
assert "GRANT EXECUTE" in sql and "service_role" in sql
```

Also assert:

- no email literals (`@gmail.com`, `@naver.com`)
- append-only UPDATE/DELETE/TRUNCATE blockers for submissions and consensus events
- decision/GT shape checks
- slot reviewer uniqueness
- active user and camera uniqueness
- stable SQLSTATE markers for forbidden, stale, invalid input, duplicate submission
- UUID/date/cursor/limit/enum/array-length validation and `note` length `<=2000`
- no dynamic SQL or concatenated user input.

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/test_motion_double_blind_labeling_migration.py -q
```

Expected: FAIL because migration does not exist.

- [ ] **Step 3: Create tables and indexes**

Use these minimum columns:

```sql
CREATE TABLE public.motion_labeling_review_groups (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL UNIQUE CHECK (length(btrim(name)) BETWEEN 1 AND 80),
  active boolean NOT NULL DEFAULT true,
  created_by uuid NOT NULL REFERENCES auth.users(id),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE public.motion_labeling_review_group_members (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id uuid NOT NULL REFERENCES public.motion_labeling_review_groups(id),
  user_id uuid NOT NULL REFERENCES auth.users(id),
  assigned_by uuid NOT NULL REFERENCES auth.users(id),
  assigned_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  ended_at timestamptz
);
CREATE UNIQUE INDEX uq_motion_review_member_active
  ON public.motion_labeling_review_group_members(user_id)
  WHERE ended_at IS NULL;

CREATE TABLE public.motion_labeling_review_group_cameras (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id uuid NOT NULL REFERENCES public.motion_labeling_review_groups(id),
  camera_id uuid NOT NULL REFERENCES public.cameras(id),
  assigned_by uuid NOT NULL REFERENCES auth.users(id),
  assigned_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  ended_at timestamptz
);
CREATE UNIQUE INDEX uq_motion_review_camera_active
  ON public.motion_labeling_review_group_cameras(camera_id)
  WHERE ended_at IS NULL;
```

Create `motion_blind_review_cohorts` with `kind='canary'`, `status='open'|'closed'`, owner creator, timestamps, and no DELETE path. Create slots, submissions, consensus, and events with UUID FKs, immutable submission JSON, `activity_day_kst date`, timestamps, comparator version, two submission references, final decision/GT, differing field array, owner resolution metadata, and constraints described in the design. Slots and downstream rows carry `cohort_kind text CHECK (cohort_kind IN ('live','canary'))` plus nullable `cohort_id`; normal queue/progress/export RPCs hard-filter `cohort_kind='live'`.

Create `motion_labeling_reviewer_progress` keyed by `(group_id, reviewer_id)` with `oldest_unlocked_activity_day date NOT NULL`, timestamps, and an FK-compatible active assignment check inside management/workspace RPCs. There is no browser write path; only service-role RPCs may initialize or move the day backward.

Add indexes for every FK and the actual read paths: reviewer live queue `(reviewer_id, cohort_kind, activity_day_kst, submitted_at)`, canary scope `(cohort_id, reviewer_id, submitted_at)`, unique submission per slot/reviewer, conflict queue `(status, updated_at DESC, clip_id DESC)`, and active partial member/camera mappings. Migration tests must query the catalog or assert the exact index DDL so an unindexed FK cannot slip through.

- [ ] **Step 4: Implement slot materialization and workspace RPCs**

`fn_ensure_motion_review_slots(p_reviewer_id uuid, p_activity_day date)` must:

1. resolve one active group for `p_reviewer_id`;
2. lock group/member rows;
3. require exactly two active approved labelers;
4. find assigned cameras;
5. select `motion_clips` in the 07:00 activity-day window;
6. insert exactly two reviewer slots per clip with `ON CONFLICT DO NOTHING`;
7. never expose peer submission fields.

`fn_get_motion_blind_workspace` returns only group name, masked/display names, assigned cameras, available personal days, own/member counts, agreed/conflict/awaiting counts, and late-added count.

Its `priority_activity_day` is the latest fully closed KST activity day (`07:00~07:00`) that still has an unsubmitted live slot for that reviewer. On first use it initializes `oldest_unlocked_activity_day` to the immediately previous fully closed day; after the reviewer completes that day the RPC moves it backward atomically within the 30-day media-retention window, automatically passing days with zero assigned clips. Partner incompletion never blocks this personal progression. A late-arriving clip on an already completed day is surfaced as priority work, while `oldest_unlocked_activity_day` is monotonic toward older dates and is never moved forward, so access to days already unlocked cannot be revoked.

- [ ] **Step 5: Implement queue, lease, submit, finalize, owner RPCs**

Key contracts:

```sql
-- Queue: own slots only, submitted_at IS NULL, keyset DESC.
WHERE s.reviewer_id = p_reviewer_id
  AND s.activity_day_kst = p_activity_day
  AND (p_cursor_started_at IS NULL OR
       (m.started_at, m.id) < (p_cursor_started_at, p_cursor_id))
ORDER BY m.started_at DESC, m.id DESC;
```

Submission RPC locks the slot, rejects wrong reviewer, expired/stale lease, second submission, malformed decision/GT, and inserts one immutable row. Finalize RPC locks both submissions, verifies the caller-provided submission digests and comparator version, and stores one idempotent consensus. Owner resolve RPC requires conflict status and appends an event rather than deleting either human submission.

- [ ] **Step 6: Apply permissions and append-only triggers**

For every new table:

```sql
ALTER TABLE ... ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE ... FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE ... TO service_role;
```

For each RPC:

```sql
REVOKE ALL ON FUNCTION ... FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION ... TO service_role;
```

Add UPDATE/DELETE/TRUNCATE blockers to immutable submissions and events with SQLSTATE `0A000`.

- [ ] **Step 7: Add rollback probe comments**

Include transactional probes for:

- two active member enforcement
- duplicate active camera assignment
- wrong reviewer submit
- duplicate submit
- malformed label/non-label GT
- two submissions + single consensus
- stale digest
- owner resolution only on conflict
- canary cohort rows excluded from live queue/progress
- append-only mutation rejection
- rollback leaves zero synthetic rows.

- [ ] **Step 8: Run GREEN**

```bash
uv run pytest tests/test_motion_double_blind_labeling_migration.py -q
uv run pytest tests/test_motion_clip_labeling_v3_migration.py -q
```

Expected: both focused suites pass.

- [ ] **Step 9: Commit**

```bash
git add migrations/2026-07-23_motion_double_blind_labeling.sql tests/test_motion_double_blind_labeling_migration.py
git commit -m "feat: 그룹 이중 라벨링 DB 계약"
```

Do not apply the migration.

---

### Task 3: Server Mappers and Labeler Read APIs

**Files:**
- Create: `web/src/lib/motionBlindReviewServer.ts`
- Create: `web/src/lib/motionBlindReviewServer.test.ts`
- Create: `web/src/app/api/labeling-v3/blind/workspace/route.ts`
- Create: `web/src/app/api/labeling-v3/blind/workspace/route.test.ts`
- Create: `web/src/app/api/labeling-v3/blind/canary/[cohortId]/route.ts`
- Create: `web/src/app/api/labeling-v3/blind/canary/[cohortId]/route.test.ts`
- Create: `web/src/app/api/labeling-v3/blind/queue/route.ts`
- Create: `web/src/app/api/labeling-v3/blind/queue/route.test.ts`
- Create: `web/src/app/api/labeling-v3/blind/[clipId]/route.ts`
- Create: `web/src/app/api/labeling-v3/blind/[clipId]/route.test.ts`
- Create: `web/src/app/api/labeling-v3/blind/[clipId]/file/url/route.ts`
- Create: `web/src/app/api/labeling-v3/blind/[clipId]/file/url/route.test.ts`

**Interfaces:**
- Consumes: existing `requireProductionLabelingAccess`, opaque queue cursor, R2 signing pattern.
- Produces: `BlindWorkspace`, `BlindQueueResponse`, `BlindClipDetail`; no peer submission fields.

- [ ] **Step 1: Write mapper leak tests**

Create raw fixtures containing forbidden keys:

```ts
const raw = {
  clip_id: CLIP,
  peer_reviewer_id: 'secret-peer',
  peer_decision: 'exclude',
  peer_initial_gt: { visibility: 'absent' },
  peer_note: 'hidden',
  r2_key: 'terra-clips/secret.mp4',
  evidence_snapshot: { hidden: true },
};
const json = JSON.stringify(mapBlindQueueRow(raw));
for (const secret of ['peer_reviewer_id', 'peer_decision', 'peer_initial_gt', 'peer_note', 'r2_key', 'evidence_snapshot']) {
  expect(json).not.toContain(secret);
}
```

Also test invalid enum/date/count fail-closed.

- [ ] **Step 2: Write API RED tests**

For every route assert:

- 401 without auth
- owner/labeler role contract
- user ID always comes from bearer access, never body/query
- RPC receives that user ID
- wrong assignment maps to 404
- DB error maps to generic 502 without raw message
- queue cursor invalid => 400 before RPC
- cursor copied across another activity day or canary/live scope => 400 before RPC
- detail and file URL do not query/sign before slot authorization
- detail GET does not mutate or acquire a lease
- workspace materializes late slots then returns aggregate-only response
- workspace exposes each member's submitted count but never the partner's label/hold/exclude distribution
- live routes reject canary scope; canary route requires an open cohort and returns only that reviewer's canary slots
- state-changing routes require an explicit bearer-authenticated request, reject oversized/malformed JSON, and map validation/state errors to stable 400/409/410 codes without DB text.

- [ ] **Step 3: Run RED**

```bash
cd web && npx vitest run \
  src/lib/motionBlindReviewServer.test.ts \
  src/app/api/labeling-v3/blind/workspace/route.test.ts \
  'src/app/api/labeling-v3/blind/canary/[cohortId]/route.test.ts' \
  src/app/api/labeling-v3/blind/queue/route.test.ts \
  'src/app/api/labeling-v3/blind/[clipId]/route.test.ts' \
  'src/app/api/labeling-v3/blind/[clipId]/file/url/route.test.ts'
```

Expected: missing modules/routes fail.

- [ ] **Step 4: Implement strict allowlist mappers**

Define explicit raw interfaces and construct fresh public objects; never spread DB rows:

```ts
export function mapBlindQueueRow(row: BlindQueueRow): BlindQueueItem {
  return {
    id: row.clip_id,
    camera_name: row.camera_name ?? '이름 없는 카메라',
    started_at: row.started_at,
    duration_sec: Number(row.duration_sec),
    media_ready: Boolean(row.media_ready),
    activity_day: row.activity_day_kst,
    lease_expires_at: row.lease_expires_at ?? null,
  };
}
```

- [ ] **Step 5: Implement read routes**

Use `requireProductionLabelingAccess(req)`. Labeler routes require `status==='labeler'`; owner read uses separate owner routes in Task 6. Workspace calls ensure-slots then get-workspace. Queue uses a strict versioned opaque cursor containing `(started_at,id,activity_day,cohort_kind,cohort_id)` with timestamp text preserved verbatim; decode must reject a cursor whose embedded scope differs from the request. File URL re-queries the `motion_clips.r2_key` only after authorized detail RPC succeeds.

Live routes always pass `cohort_kind='live'` and no cohort ID. The canary entry route accepts only an opaque UUID path parameter, requires the cohort to be `kind='canary' AND status='open'`, and returns only the caller's slots in that cohort. Canary detail/media/claim/submit calls carry the same cohort ID; every RPC verifies `(reviewer_id, clip_id, cohort_id)` together, so a known clip UUID cannot cross scopes.

- [ ] **Step 6: Run GREEN**

Run the focused command from Step 3. Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/motionBlindReviewServer.ts web/src/lib/motionBlindReviewServer.test.ts web/src/app/api/labeling-v3/blind
git commit -m "feat: 이중 라벨링 개인 큐 API"
```

---

### Task 4: Submission, Consensus, and Browser Client

**Files:**
- Create: `web/src/lib/motionBlindReviewApi.ts`
- Create: `web/src/app/api/labeling-v3/blind/[clipId]/claim/route.ts`
- Create: `web/src/app/api/labeling-v3/blind/[clipId]/claim/route.test.ts`
- Create: `web/src/app/api/labeling-v3/blind/[clipId]/submit/route.ts`
- Create: `web/src/app/api/labeling-v3/blind/[clipId]/submit/route.test.ts`
- Modify: `web/src/lib/motionBlindReview.ts`
- Modify: `web/src/lib/motionBlindReview.test.ts`

**Interfaces:**
- Consumes: `compareBlindSubmissions`, DB submit/finalize RPCs.
- Produces:
  - `getBlindWorkspace`
  - `getBlindQueue`
  - `getBlindClip`
  - `getBlindClipFileUrl`
  - `claimBlindReview`
  - `submitBlindReview`
  - idempotent `BlindSubmitResult`.

- [ ] **Step 1: Write RED route tests**

Required cases:

```ts
it('does not accept reviewer/group/peer fields from body');
it('rejects a live slot submitted with canary cohort_id and a canary slot without its cohort_id');
it('claim derives reviewer from bearer and returns an opaque 30-minute lease');
it('second tab cannot replace an unexpired lease without its token');
it('same token renews its lease idempotently');
it('rejects label without valid initial_gt before RPC');
it('rejects exclude/hold with initial_gt before RPC');
it('stores first submission and returns awaiting_peer without reading peer to client');
it('on second submission computes v1 comparison and finalizes with both digests');
it('retries finalize once on stale digest after re-read');
it('returns idempotent existing result on duplicate same request');
it('returns 409 already_submitted on different duplicate');
it('never returns peer decision/gt/note');
```

- [ ] **Step 2: Run RED**

```bash
cd web && npx vitest run \
  'src/app/api/labeling-v3/blind/[clipId]/claim/route.test.ts' \
  'src/app/api/labeling-v3/blind/[clipId]/submit/route.test.ts' \
  src/lib/motionBlindReview.test.ts
```

Expected: missing route/client behavior fails.

- [ ] **Step 3: Implement submit route**

Body is exactly:

```ts
interface SubmitBody {
  decision: BlindDecision;
  initial_gt: GroundTruthInput | null;
  note: string | null;
  reason_code: BlindSubmissionInput['reason_code'];
  lease_token: string;
  cohort_id?: string;
}
```

Validate the body as an exact object: unknown keys reject, `note` is nullable plain text with at most 2,000 characters, `lease_token`/`cohort_id` are canonical UUIDs, and `initial_gt` arrays/segments retain the existing bounded `GroundTruthInput` limits. Reject a declared request body larger than 64 KiB before JSON parsing.

Claim flow:

1. derive reviewer from bearer;
2. call claim RPC with optional existing `lease_token`;
3. bind the live/null or explicit canary cohort scope into the RPC;
4. return `{lease_token, lease_expires_at}` only to that reviewer;
5. map another active tab to stable `409 slot_in_use`;
6. allow the same token to renew to `clock_timestamp()+interval '30 minutes'`.

Submission flow:

1. derive reviewer from bearer;
2. validate shape with Task 1 contract;
3. call submit RPC;
4. if `peer_submission` is absent, return `{status:'awaiting_peer'}`;
5. compare immutable submissions;
6. call finalize RPC with comparator version, result, both IDs and digests;
7. return only `{status:'agreed'|'conflict', differing_fields:string[]}`.

The response must never include peer values.

- [ ] **Step 4: Implement browser API client**

Reuse the existing `ApiError`/`UnauthorizedError` request pattern without importing server-only modules. All endpoints are same-origin. Preserve API error `code` for `already_submitted`, `stale_lease`, and `not_assigned`.

- [ ] **Step 5: Run GREEN**

Run Step 2 command. Expected: all focused tests pass.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/motionBlindReview.ts web/src/lib/motionBlindReview.test.ts web/src/lib/motionBlindReviewApi.ts 'web/src/app/api/labeling-v3/blind/[clipId]/claim' 'web/src/app/api/labeling-v3/blind/[clipId]/submit'
git commit -m "feat: 이중 라벨 제출과 자동 합의"
```

---

### Task 5: Labeler Daily Queue, Onboarding, and Detail UX

**Files:**
- Create: `web/src/app/labeling/_blind-review-queue.tsx`
- Create: `web/src/app/labeling/_blind-review-progress.tsx`
- Create: `web/src/app/labeling/_blind-review-onboarding.tsx`
- Create: `web/src/app/labeling/blind/[clipId]/page.tsx`
- Create: `web/src/app/labeling/blind/canary/[cohortId]/page.tsx`
- Create: `web/src/app/labeling/blind/canary/[cohortId]/[clipId]/page.tsx`
- Create: `web/src/app/labeling/_blind-review-ui.test.tsx`
- Modify: `web/src/app/labeling/page.tsx`
- Modify: `web/src/app/labeling/_owner-context.tsx`
- Modify: `web/src/lib/labelingRouteAccess.ts`
- Modify: corresponding tests.

**Interfaces:**
- Consumes: Task 3/4 browser APIs, existing `GroundTruthForm`, request-generation stale guard, draft scope patterns.
- Produces: labeler `/labeling` daily queue and `/labeling/blind/[clipId]` workflow.

- [ ] **Step 1: Write the user-experience test fixture**

Lock visible copy and behavior:

```tsx
expect(screen.getByText('같은 영상을 두 사람이 따로 확인해.')).toBeVisible();
expect(screen.getByText('라벨러 화면에는 상대방의 답이 보이지 않아.')).toBeVisible();
expect(screen.getByText('내 작업 34/100')).toBeVisible();
expect(screen.getByText('파트너 28/100')).toBeVisible();
expect(screen.getByRole('button', { name: /라벨링하기/ })).toHaveAttribute('aria-pressed', 'false');
expect(screen.getByText(/게코가 없거나 촬영·재생 오류/)).toBeVisible();
expect(screen.queryByText(/peer|상대 판정:/)).toBeNull();
expect(screen.queryByText(/파트너.*라벨|파트너.*보류|파트너.*제외/)).toBeNull();
```

Test empty states, automatic pass over a zero-clip day, 30-day retention boundary, late clip badge, durable personal older-day unlock after reload, group completion, mobile card class, and onboarding reopen.

- [ ] **Step 2: Run RED**

```bash
cd web && npx vitest run src/app/labeling/_blind-review-ui.test.tsx
```

Expected: missing components fail.

- [ ] **Step 3: Implement queue and progress**

`BlindReviewQueue` loads workspace first, chooses server-provided `priority_activity_day`, then loads that day’s personal queue. It must:

- show group/cameras/window;
- show own and partner aggregate counts only;
- list newest first;
- preserve opaque cursor;
- discard stale responses on day/filter changes;
- expose only server-returned available days;
- show `어제 추가 N건` without revoking older days;
- save/restore scroll by reviewer+day;
- open `/labeling/blind/{clipId}?activity_day=YYYY-MM-DD`.

- [ ] **Step 4: Implement onboarding**

Persist only `petcam-blind-onboarding:v1:<userId>=dismissed` in localStorage. Render the three approved sentences, `작업 시작`, and a permanent `작업 방법` button. Storage failure must not block the queue.

- [ ] **Step 5: Implement detail**

Reuse the existing video player and `GroundTruthForm`, but use the new blind APIs.

- Three cards use full-button hit areas and `aria-pressed`.
- `exclude` asks a reason: `gecko_absent | capture_error | media_error`.
- `hold` uses `ambiguous`.
- `label` reveals GT form and uses `behavior_data`.
- Draft key includes user ID, clip ID, activity day, and `motion-blind-v1`.
- Detail GET is read-only. After it succeeds, call the dedicated claim endpoint with a new browser-generated lease token.
- While the tab is visible, renew the same token every 10 minutes; never mint a new token for renewal.
- Keep the lease token in per-tab `sessionStorage`, never localStorage, logs, URL, analytics, or rendered error text; clear it after successful submission.
- If another tab owns the lease, keep the video/detail readable but disable submission and explain `다른 창에서 이 영상을 작업 중이야`.
- On `stale_lease`, preserve the local draft, reacquire once with the same token, and require an explicit second submit click. Never silently resubmit.
- Confirmation explains that first submission cannot be edited by the labeler.
- On success show only `저장 완료 · 상대 판정 대기 중`, `두 판정 일치`, or `관리자 확인으로 보냈어`.
- Never fetch/display VLM or peer submission.
- Next button loads the next personal unsubmitted slot in the same day; if empty, returns to daily queue.

The canary page reuses the same queue/detail components but pins `cohort_id` in every URL and request, shows `검증용 작업` visibly, never touches activity-day unlock/progress, and stops with `검증 작업을 모두 끝냈어` when its own cohort slots are submitted. A closed or unknown cohort shows a safe expired-link state.

- [ ] **Step 6: Switch `/labeling` by access role**

Add:

```ts
export function useIsLabeler(): boolean {
  return useContext(AccessCtx).access?.status === 'labeler';
}
```

Create a client home switch so owner keeps `MotionQueue`, approved labeler gets `BlindReviewQueue`, and legacy env behavior remains owner-only fallback. Update route categorization so approved labelers may access `/labeling/blind/**` but pending/rejected users cannot.

- [ ] **Step 7: Run GREEN**

```bash
cd web && npx vitest run \
  src/app/labeling/_blind-review-ui.test.tsx \
  src/lib/labelingRouteAccess.test.ts \
  src/lib/motionBlindReview.test.ts
cd web && npx tsc --noEmit
```

Expected: focused tests and typecheck pass.

- [ ] **Step 8: Commit**

```bash
git add web/src/app/labeling web/src/lib/labelingRouteAccess.ts web/src/lib/labelingRouteAccess.test.ts
git commit -m "feat: 라벨러 활동일 이중 검수 UX"
```

---

### Task 6: Owner Conflict and Group Administration

**Files:**
- Create owner API and UI files listed in File Structure.
- Modify: `web/src/app/labeling/layout.tsx`
- Test: each owner route test plus `web/src/app/labeling/_blind-review-ui.test.tsx`

**Interfaces:**
- Consumes: owner access contract, consensus/management RPCs.
- Produces: conflict-only owner queue, side-by-side first submissions, final resolution, safe group mapping.

- [ ] **Step 1: Write RED API tests**

Cover:

- labeler receives 404/403 for every owner endpoint;
- conflicts list excludes agreed/awaiting/resolved;
- detail returns both immutable submissions only to owner;
- `choice:'a'|'b'|'new'` resolution;
- `choice:'new'` requires valid final decision/GT;
- agreed consensus cannot be silently resolved;
- group assignment rejects non-approved users, member count not equal to two, duplicate camera, and email/UUID supplied in public response;
- canary creation accepts owner-selected test clip IDs, creates `cohort_kind=canary`, and closing only changes cohort status;
- raw DB errors and auth metadata never leak.

- [ ] **Step 2: Write RED UI tests**

Lock:

```tsx
expect(screen.getByText('불일치 검수')).toBeVisible();
expect(screen.getByText('서로 다른 항목')).toBeVisible();
expect(screen.getByRole('button', { name: 'A 판정 채택' })).toBeEnabled();
expect(screen.getByRole('button', { name: 'B 판정 채택' })).toBeEnabled();
expect(screen.getByRole('button', { name: '새 판정 저장' })).toBeEnabled();
```

Also test owner default empty state, agreed audit link, and that the group admin UI displays `display_name` with masked-email fallback.

- [ ] **Step 3: Run RED**

```bash
cd web && npx vitest run \
  src/app/api/labeling-v3/blind/owner \
  src/app/labeling/_blind-review-ui.test.tsx
```

Expected: missing routes/screens fail.

- [ ] **Step 4: Implement owner APIs**

Use owner-only `requireProductionLabelingAccess`. Conflicts route uses opaque keyset cursor. Detail mapper may include both first submissions but excludes auth metadata and raw evidence. Resolve route passes bearer owner ID and expected consensus `updated_at` for optimistic concurrency.

Group API accepts approved `user_id` values selected from existing owner team endpoint; it never accepts email as the persistence key. It calls one transaction RPC that verifies exactly two active approved labelers and camera uniqueness before ending old mappings and inserting new ones.

Canary API accepts a bounded list of 1–20 existing test clip IDs and two approved reviewer IDs, creates an isolated cohort, and returns an opaque cohort ID/link. Closing the cohort must not delete slots, submissions, consensus, or events.

- [ ] **Step 5: Implement owner screens**

- conflict card: camera, captured time, top-level decision mismatch summary;
- detail: video plus A/B columns, changed fields highlighted, notes separate;
- resolution: A, B, or new GT form;
- agreed audit is secondary/read-only;
- group admin: two member selectors and camera selectors, explicit confirmation, no password/email entry fields.

Add owner nav items `불일치 검수` and `그룹 배정`. Do not show them to labelers.

- [ ] **Step 6: Run GREEN**

Run Step 3 plus:

```bash
cd web && npx tsc --noEmit
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add web/src/app/api/labeling-v3/blind/owner web/src/app/labeling/blind/conflicts web/src/app/labeling/blind/groups web/src/app/labeling/layout.tsx web/src/app/labeling/_blind-review-ui.test.tsx
git commit -m "feat: 이중 라벨 불일치 owner 검수"
```

---

### Task 7: Cross-Layer Hardening and Full Verification

**Files:**
- Modify only files already touched if tests expose defects.
- Modify docs listed in File Structure.
- Create: `docs/handoff-prompts/2026-07-23-double-blind-labeling-implementation-report.md`

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces: deployment-review-ready feature branch and evidence report.

- [ ] **Step 1: Add adversarial cross-layer tests**

Test eight perspectives:

1. peer answer leakage through queue/detail/progress/error JSON;
2. forged reviewer/group/camera IDs;
3. simultaneous second submission and duplicate consensus;
4. one-person-only completion;
5. comparator boundary drift and unordered arrays;
6. group reassignment after one submission;
7. late clip/unlock regression;
8. legacy owner/tutorial/VLM regressions.

Also assert canary submissions never appear in live queue, progress, member counts, owner live conflict count, or GT export inputs.
Add security assertions for oversized bodies, unknown keys, HTML-like notes rendered as text, forged cohort scope, lease/digest redaction, canonical UUID/date bounds, and absence of dynamic SQL.

- [ ] **Step 2: Run all web tests**

```bash
cd web && npm test
```

Expected: zero failures; record exact count.

- [ ] **Step 3: Run TypeScript and Python suites**

```bash
cd web && npx tsc --noEmit
uv run pytest -q
git diff --check
```

Expected: zero errors, exact Python count recorded, whitespace clean.

- [ ] **Step 4: Run production build**

```bash
cd web && npm run build
```

Expected: Next.js production build succeeds and new dynamic API/routes are registered. If the environment’s safety hook blocks this command, report it as unverified and require owner-terminal or Vercel preview build; do not substitute `tsc` as build evidence.

- [ ] **Step 5: Security static audit**

Run:

```bash
rg -n \"@gmail\\.com|@naver\\.com|service_role|encrypted_password|peer_initial_gt|peer_note|evidence_snapshot|r2_key\" \
  migrations/2026-07-23_motion_double_blind_labeling.sql \
  web/src/app/api/labeling-v3/blind \
  web/src/lib/motionBlindReview*
```

Expected:

- no personal email or password;
- `service_role` appears only in migration grants/comments or server-only imports;
- peer/raw field names appear only in negative tests or owner-only mapper;
- labeler responses are allowlisted;
- no `dangerouslySetInnerHTML`, raw SQL interpolation, lease token, digest, or bearer value in client-visible logs/errors.

- [ ] **Step 6: Update docs**

Document:

- activity-day and personal/group completion distinction;
- blind comparison v1 and 500ms tolerance;
- new tables/RPCs and service-role-only boundary;
- owner conflict workflow;
- deployment still unapplied.

Report exact files, commits, test totals, known deviations, and all unexecuted boundaries.

- [ ] **Step 7: Commit**

```bash
git add docs/FEATURES.md docs/DATABASE.md specs/next-session.md .claude/donts-audit.md docs/handoff-prompts/2026-07-23-double-blind-labeling-implementation-report.md
git commit -m "docs: 그룹 이중 라벨링 구현 검증 기록"
```

- [ ] **Step 8: Stop Point**

Push the feature branch only if the handoff authorizes push. Stop with:

```text
DOUBLE_BLIND_LABELING_READY_FOR_DEPLOY_REVIEW
```

Do not merge main, apply migration, deploy, or write production group mappings.

---

### Task 8: Deployment Review, Preview Canary, and Production Gate

**Files:**
- No code changes unless a canary finds a reproducible defect.
- Append deployment evidence to the implementation report.

**Interfaces:**
- Consumes: verified feature branch.
- Produces: either rollback/blocked evidence or `DOUBLE_BLIND_LABELING_DEPLOYED_VERIFIED`.

- [ ] **Step 1: Independent diff review**

Review migration, security boundary, comparator, assignment/unlock, UI copy, and legacy regression. Any P0/P1 finding returns to a new TDD fix commit and repeats Task 7.

- [ ] **Step 2: Apply migration to preview/staging**

Run static preflight and apply the new migration only. Execute the documented transactional rollback probes. Expected: all probes pass and synthetic rows roll back to zero.

- [ ] **Step 3: Configure preview groups**

Through the owner group admin API, select the four approved users and cameras according to the owner’s runtime mapping:

- Group A: owner-designated A1+A2; P4 Cam (dev)
- Group B: owner-designated B1+B2; P4 Cam 2(dev)+P4 Cam 3
- P4 Cam 4 remains unassigned/owner-only.

Do not place emails in source, migration, shell history, or report.

- [ ] **Step 4: Run preview 12-clip canary**

Create one isolated `cohort_kind=canary` batch with 12 owner-selected test clips and two actual labeler sessions:

- agree exclude 2
- agree hold 2
- agree label+GT 2
- decision conflict 2
- GT field conflict 2
- time boundary 500ms/501ms 2

Verify:

- each labeler sees only own assigned cameras and no peer answers;
- both can review the same clip independently;
- counts and personal unlock are correct;
- owner conflict queue expected==actual;
- comparator independent recompute 12/12;
- canary records remain append-only, are excluded from live GT/progress/export, and disappear from labeler canary entry after owner closes the cohort.

- [ ] **Step 5: FF-only main integration and production deploy**

Only after owner approval:

```bash
git merge --ff-only <verified-feature-branch>
git push origin main
```

Apply the migration, deploy Vercel, then configure real group mappings through the owner UI. No force push.

- [ ] **Step 6: Production first-30 audit**

Allow normal double-blind operation for 30 clips. Owner audits all 30, including agreed clips.

Pass gates:

- assignment/access error 0
- peer leakage 0
- two unique submissions per clip 30/30
- comparator recompute 30/30
- lost/duplicate consensus 0
- owner conflict queue exact
- agreed auto-consensus error 0

If any agreed consensus is wrong, disable automatic finalization while preserving both submissions and route all completed pairs to owner review. Do not delete or rewrite human submissions.

- [ ] **Step 7: Final SOT closure**

Append runtime hostname/environment, production main SHA, migration record, Vercel deployment, group counts (not personal emails), first-30 results, and final verdict.

Only then claim:

```text
DOUBLE_BLIND_LABELING_DEPLOYED_VERIFIED
```

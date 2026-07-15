# Labeling Triage Quarantine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 라벨링 가치가 낮아 보이는 `camera_clips`를 owner 전용 격리함에서 검토하고, 일반 라벨링 큐에서 안전하게 분리·복구할 수 있게 만든다.

**Architecture:** `clip_labeling_triage`는 현재 라우팅 상태, `clip_labeling_triage_events`는 append-only 감사 이력을 보관한다. Next.js owner-only API가 service-role RPC를 호출하고, 일반 큐는 기존 bounded batch scan 안에서 triage 상태를 추가로 적용한다. 시스템 suggestion worker는 별도 계획에서 구현한다.

**Tech Stack:** PostgreSQL/Supabase, Next.js 14 App Router, TypeScript, React, Vitest.

## Global Constraints

- 설계 정본은 `docs/superpowers/specs/2026-07-15-labeling-triage-quarantine-design.md`다.
- 일반 라벨링 큐의 원본은 `camera_clips`이며 `motion_clips` assessment를 직접 조인하지 않는다.
- `owner_decision`은 시스템 제안보다 항상 우선한다.
- triage row 없음, `unknown`, 분석 오류는 일반 큐 유지다.
- 기존 `clip_labeling_sessions`가 한 건이라도 있으면 자동/수동 격리와 owner `skip`을 거부한다.
- 영상, GT, `behavior_labels`, 활동시간 view를 변경하거나 삭제하지 않는다.
- anon/authenticated 클라이언트가 triage 테이블이나 RPC에 직접 write할 수 없어야 한다.
- DB 오류 전문, raw evidence, 비밀값을 API 응답에 노출하지 않는다.
- 이 계획 실행 중 production migration 적용, 배포, commit, push를 하지 않는다. 구현·테스트 후 사용자 검토에서 멈춘다.

## File Structure

- Create: `migrations/2026-07-15_labeling_triage.sql` — 테이블, append-only 트리거, service-role RPC 3개.
- Create: `web/src/lib/labelingTriage.ts` — 공유 타입, 상태 판정, 표시 문구.
- Create: `web/src/lib/labelingTriage.test.ts` — 순수 상태 규칙 테스트.
- Create: `web/src/lib/labelingTriageServer.ts` — cursor와 owner API용 DB 조회/응답 매핑.
- Create: `web/src/lib/labelingTriageServer.test.ts` — cursor, DB 오류, raw evidence 비노출 테스트.
- Modify: `web/src/lib/labelingQueue.ts` — bounded scan에 triage 상태 추가.
- Modify: `web/src/lib/labelingQueue.test.ts` — queue include/exclude 회귀.
- Modify: `web/src/app/api/labeling-v2/queue/route.ts` — 후보 batch별 triage 조회.
- Create: `web/src/app/api/labeling-triage/route.ts` + `route.test.ts` — owner 목록.
- Create: `web/src/app/api/labeling-triage/[clipId]/route.ts` + `route.test.ts` — 상세/결정.
- Create: `web/src/app/api/labeling-triage/[clipId]/quarantine/route.ts` + `route.test.ts` — owner 수동 격리.
- Modify: `web/src/lib/labelingApi.ts` — client 타입과 호출 함수.
- Modify: `web/src/app/labeling/layout.tsx` — owner route/nav.
- Create: `web/src/app/labeling/quarantine/page.tsx` — 탭 목록.
- Create: `web/src/app/labeling/quarantine/[clipId]/page.tsx` — 영상 검토/결정.
- Modify: `web/src/app/labeling/page.tsx` — owner 수동 격리 버튼.
- Modify: `docs/DATABASE.md`, `docs/FEATURES.md`, `specs/next-session.md` — 구현 상태 SOT.

---

### Task 1: Forward-only triage schema and atomic RPCs

**Files:**
- Create: `migrations/2026-07-15_labeling_triage.sql`

**Interfaces:**
- Produces: `clip_labeling_triage`, `clip_labeling_triage_events`.
- Produces: `fn_upsert_clip_labeling_triage_suggestion(uuid,text,text,text,text,jsonb) -> jsonb`.
- Produces: `fn_decide_clip_labeling_triage(uuid,uuid,text,timestamptz,text) -> jsonb`.
- Produces: `fn_manual_quarantine_clip_for_labeling(uuid,uuid,text) -> jsonb`.

- [ ] **Step 1: Confirm live prerequisites read-only**

Run through Supabase MCP or SQL console without writes:

```sql
select to_regclass('public.camera_clips') as camera_clips,
       to_regclass('public.clip_labeling_sessions') as sessions;

select column_name, data_type
from information_schema.columns
where table_schema='public'
  and table_name in ('camera_clips','clip_labeling_sessions')
  and column_name in ('id','clip_id','started_at','camera_id','r2_key','has_motion');
```

Expected: both tables exist and all referenced columns are present. Do not apply the migration.

- [ ] **Step 2: Write the forward migration**

The migration must contain these exact table contracts:

```sql
begin;

create table public.clip_labeling_triage (
  clip_id uuid primary key references public.camera_clips(id) on delete cascade,
  suggested_route text not null check (suggested_route in ('label','quarantine')),
  suggestion_reason text not null check (suggestion_reason in ('gate_active','gate_absent','gate_static','manual')),
  suggestion_source text not null check (char_length(suggestion_source) between 1 and 80),
  policy_version text not null check (char_length(policy_version) between 1 and 80),
  evidence_snapshot jsonb not null default '{}'::jsonb,
  owner_decision text check (owner_decision in ('label','skip')),
  decided_by uuid references auth.users(id) on delete restrict,
  decided_at timestamptz,
  decision_note text check (decision_note is null or char_length(decision_note) <= 500),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (
    (owner_decision is null and decided_by is null and decided_at is null)
    or
    (owner_decision is not null and decided_by is not null and decided_at is not null)
  ),
  check (jsonb_typeof(evidence_snapshot) = 'object')
);

create index idx_clip_labeling_triage_effective_state
  on public.clip_labeling_triage
  (owner_decision, suggested_route, updated_at desc, clip_id desc);

create table public.clip_labeling_triage_events (
  id bigint generated always as identity primary key,
  -- 이벤트는 append-only이며 원본 clip보다 오래 보존한다. FK CASCADE를 걸면
  -- 이벤트 DELETE 차단 트리거가 camera_clips 삭제까지 막으므로 UUID만 보존한다.
  clip_id uuid not null,
  event_type text not null check (event_type in (
    'suggested','owner_labeled','owner_skipped','owner_reset','manual_quarantined'
  )),
  actor_type text not null check (actor_type in ('system','owner')),
  actor_id uuid references auth.users(id) on delete restrict,
  before_state jsonb,
  after_state jsonb not null,
  reason text check (reason is null or char_length(reason) <= 500),
  created_at timestamptz not null default now(),
  check (actor_type='system' or actor_id is not null)
);

create index idx_clip_labeling_triage_events_clip_created
  on public.clip_labeling_triage_events (clip_id, created_at desc);

alter table public.clip_labeling_triage enable row level security;
alter table public.clip_labeling_triage_events enable row level security;
revoke all on public.clip_labeling_triage from public, anon, authenticated;
revoke all on public.clip_labeling_triage_events from public, anon, authenticated;
grant all on public.clip_labeling_triage to service_role;
grant all on public.clip_labeling_triage_events to service_role;
```

Add `fn_block_labeling_triage_event_mutation()` and row/statement triggers that raise SQLSTATE `0A000` for UPDATE, DELETE, and TRUNCATE on the event table.

- [ ] **Step 3: Add the system suggestion RPC**

Implement these exact rules inside `fn_upsert_clip_labeling_triage_suggestion`:

```sql
-- Validate all enum-like inputs before locking.
-- Lock the camera_clips row with FOR KEY SHARE; P0002 when missing.
-- Lock an existing triage row with FOR UPDATE.
-- If p_suggested_route='quarantine' and any clip_labeling_sessions row exists,
-- return jsonb_build_object('ok',false,'code','labeling_started').
-- If route/reason/source/policy/evidence are identical, return ok=true, changed=false.
-- Upsert only suggestion fields and updated_at; never assign owner_decision fields.
-- Insert one 'suggested' event only when suggestion fields changed.
-- Return {ok:true, changed:boolean, row:to_jsonb(v_row)}.
```

Compare JSON with `IS NOT DISTINCT FROM`; do not compare serialized JSON text. The RPC is `SECURITY DEFINER SET search_path=public,pg_temp` and executable only by `service_role`.

- [ ] **Step 4: Add owner decision and manual quarantine RPCs**

`fn_decide_clip_labeling_triage` must:

```sql
-- accept p_decision in ('label','skip','reset')
-- SELECT triage row FOR UPDATE; return {ok:false,code:'not_found'} when absent
-- compare updated_at to p_expected_updated_at; return stale_state on mismatch
-- for skip, reject when any clip_labeling_sessions row exists
-- label/skip: set owner_decision, decided_by, decided_at, note
-- reset: set all four owner fields to null
-- set updated_at=clock_timestamp()
-- insert exactly one matching owner event in the same transaction
```

`fn_manual_quarantine_clip_for_labeling` must:

```sql
-- lock camera_clips, reject missing/not labelable
-- reject any existing clip_labeling_sessions row
-- upsert suggested_route='quarantine', suggestion_reason='manual',
-- suggestion_source='owner_manual', policy_version='manual-v1', evidence_snapshot='{}'
-- clear owner_decision, decided_by, decided_at, decision_note because this is a new explicit owner action
-- insert manual_quarantined event only when state changed
```

- [ ] **Step 5: Lock down function grants and write rollback probes**

Add explicit REVOKE/GRANT statements for these three exact signatures and roles: suggestion `(uuid,text,text,text,text,jsonb)`, decision `(uuid,uuid,text,timestamptz,text)`, and manual quarantine `(uuid,uuid,text)`. Revoke from `PUBLIC`, `anon`, and `authenticated`; grant execute only to `service_role`. End the migration with commented rollback and probe blocks covering:

```sql
-- suggestion + event atomicity
-- duplicate suggestion => changed=false and no extra event
-- owner label survives later system suggestion
-- session present => quarantine/skip labeling_started
-- stale updated_at => stale_state
-- event UPDATE/DELETE/TRUNCATE => 0A000
-- ROLLBACK => all probe rows 0
```

- [ ] **Step 6: Static verification**

Run:

```bash
git diff --check -- migrations/2026-07-15_labeling_triage.sql
rg -n "SECURITY DEFINER|search_path|REVOKE ALL|service_role|0A000|labeling_started|stale_state" migrations/2026-07-15_labeling_triage.sql
```

Expected: whitespace clean and every security/contract marker present. Stop before DB apply.

---

### Task 2: Shared triage state and safe server mapping

**Files:**
- Create: `web/src/lib/labelingTriage.ts`
- Create: `web/src/lib/labelingTriage.test.ts`
- Create: `web/src/lib/labelingTriageServer.ts`
- Create: `web/src/lib/labelingTriageServer.test.ts`

**Interfaces:**
- Produces: `effectiveTriageState(row) -> 'pending'|'skipped'|'labeled'|'queue'`.
- Produces: `triageReasonLabel(reason) -> string`.
- Produces: `encodeTriageCursor` / `decodeTriageCursor`.
- Produces: owner-safe `TriageListItem` and `TriageDetail` types.

- [ ] **Step 1: Write failing state precedence tests**

```ts
expect(effectiveTriageState(null)).toBe('queue');
expect(effectiveTriageState({ suggested_route: 'quarantine', owner_decision: null })).toBe('pending');
expect(effectiveTriageState({ suggested_route: 'quarantine', owner_decision: 'label' })).toBe('labeled');
expect(effectiveTriageState({ suggested_route: 'label', owner_decision: 'skip' })).toBe('skipped');
expect(effectiveTriageState({ suggested_route: 'label', owner_decision: null })).toBe('queue');
```

Also assert only these Korean labels:

```ts
gate_absent -> '게코가 보이지 않을 가능성이 높음'
gate_static -> '게코가 보이지만 움직임이 거의 없을 가능성이 높음'
manual -> 'owner가 직접 검토 대상으로 보냄'
```

`gate_active`는 일반 큐 유지용 내부 provenance라 격리함 표시 문구로 노출하지 않는다.

- [ ] **Step 2: Run RED**

Run: `cd web && npm test -- src/lib/labelingTriage.test.ts`

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement the pure contract**

Use readonly types and exhaustive switches. Never return raw `evidence_snapshot` through the display mapper.

- [ ] **Step 4: Add cursor and safe mapping tests**

The cursor payload is exactly:

```ts
type TriageCursor = { updatedAt: string; clipId: string };
```

Tests must reject invalid base64, invalid dates, and non-UUID clip IDs. Mapping tests must prove JSON output does not contain `evidence_snapshot`, checkpoint paths, or producer host.

- [ ] **Step 5: Implement server-only helpers**

`labelingTriageServer.ts` starts with `import 'server-only'`. Use `Buffer.from(JSON.stringify(cursor)).toString('base64url')` and strict decode validation. Export safe DB row mappers only; routes retain ownership checks.

- [ ] **Step 6: Run GREEN**

Run:

```bash
cd web
npm test -- src/lib/labelingTriage.test.ts src/lib/labelingTriageServer.test.ts
npx tsc --noEmit
```

Expected: all target tests pass and typecheck is clean.

---

### Task 3: Apply triage state inside the bounded labeling queue

**Files:**
- Modify: `web/src/lib/labelingQueue.ts`
- Modify: `web/src/lib/labelingQueue.test.ts`
- Modify: `web/src/app/api/labeling-v2/queue/route.ts`

**Interfaces:**
- Adds: `QueueTriageRow { clip_id, suggested_route, owner_decision }`.
- Adds required callback: `fetchTriage(clipIds) -> Promise<QueueTriageRow[]>`.

- [ ] **Step 1: Write failing queue tests**

Cover the full matrix in one bounded two-page test:

```ts
pending quarantine -> excluded
owner skip -> excluded
owner label over quarantine -> included
system label -> included
no row -> included
completed session -> excluded regardless of triage
gt_locked -> included with session_stage='gt_locked'
```

Assert `fetchTriage` receives only each candidate batch IDs and that a fully excluded first batch causes a second candidate fetch.

- [ ] **Step 2: Run RED**

Run: `cd web && npm test -- src/lib/labelingQueue.test.ts`

Expected: FAIL because `fetchTriage` and precedence are absent.

- [ ] **Step 3: Implement batch-local filtering**

Fetch stages and triage concurrently:

```ts
const [stages, triageRows] = await Promise.all([
  fetchStages(ids),
  fetchTriage(ids),
]);
```

Exclude completed first, then exclude effective `pending`/`skipped`. Do not build a global `NOT IN` list.

- [ ] **Step 4: Wire the queue route**

Add a candidate-batch query selecting only:

```ts
'clip_id,suggested_route,owner_decision'
```

Any Supabase triage query error must throw and reach existing `databaseUnavailable('labeling queue', cause)`. Never fail open on a DB outage that could leak skipped clips back to labelers.

- [ ] **Step 5: Run GREEN and regressions**

Run:

```bash
cd web
npm test -- src/lib/labelingQueue.test.ts
npx tsc --noEmit
```

Expected: queue tests and typecheck pass.

---

### Task 4: Owner-only triage APIs

**Files:**
- Create: `web/src/app/api/labeling-triage/route.ts`
- Create: `web/src/app/api/labeling-triage/route.test.ts`
- Create: `web/src/app/api/labeling-triage/[clipId]/route.ts`
- Create: `web/src/app/api/labeling-triage/[clipId]/route.test.ts`
- Create: `web/src/app/api/labeling-triage/[clipId]/quarantine/route.ts`
- Create: `web/src/app/api/labeling-triage/[clipId]/quarantine/route.test.ts`

**Interfaces:**
- `GET /api/labeling-triage` returns `{items,counts,has_more,next_cursor}`.
- `GET /api/labeling-triage/[clipId]?state=pending` returns `{item,next_clip_id}`; `skipped` and `labeled` use the same contract.
- `PATCH /api/labeling-triage/[clipId]` accepts `{decision,expected_updated_at,note?}`.
- `POST /api/labeling-triage/[clipId]/quarantine` accepts `{note?}`.

- [ ] **Step 1: Write owner/auth and validation route tests**

For every route assert:

```ts
requireOwner 401/403 response is returned unchanged
invalid state/limit/cursor/UUID/body => 400
Supabase error => generic 502 without table name or DB message
```

PATCH-specific cases:

```ts
label success -> 200
skip success -> 200
reset success -> 200
RPC not_found -> 404
RPC stale_state -> 409
RPC labeling_started -> 409
note > 500 -> 400
```

- [ ] **Step 2: Run RED**

Run:

```bash
cd web
npm test -- src/app/api/labeling-triage
```

Expected: FAIL because routes do not exist.

- [ ] **Step 3: Implement list GET**

Use `requireOwner(req)` before any DB query. Allowed state values are `pending|skipped|labeled`, limit is `1..100`, and cursor is decoded by the server helper. Filter current rows as:

```ts
pending: owner_decision IS NULL AND suggested_route='quarantine'
skipped: owner_decision='skip'
labeled: owner_decision='label'
```

Order by `updated_at DESC, clip_id DESC`, fetch `limit+1`, and select joined clip fields `id,camera_id,started_at,duration_sec,r2_key,thumbnail_r2_key`. Return reason labels, not raw evidence.

- [ ] **Step 4: Implement detail GET and next navigation**

Return the current safe item plus the first other item in the same state ordered by `updated_at DESC, clip_id DESC` as `next_clip_id`. A missing current row is 404. Detail may expose `suggestion_source` and `policy_version`, but not `evidence_snapshot`.

- [ ] **Step 5: Implement PATCH and manual POST**

Use RPC only:

```ts
supabaseAdmin.rpc('fn_decide_clip_labeling_triage', {
  p_clip_id: clipId,
  p_decided_by: owner.userId,
  p_decision: body.decision,
  p_expected_updated_at: body.expected_updated_at,
  p_note: body.note ?? null,
});
```

Map returned domain codes exactly. Do not compare database error message text except documented SQLSTATE fallback for `P0002`.

- [ ] **Step 6: Run GREEN**

Run:

```bash
cd web
npm test -- src/app/api/labeling-triage
npx tsc --noEmit
```

Expected: all owner/auth/validation/conflict tests pass.

---

### Task 5: Client API, owner route, and navigation

**Files:**
- Modify: `web/src/lib/labelingApi.ts`
- Modify: `web/src/app/labeling/layout.tsx`
- Modify: `web/src/lib/labelingAccessGuards.test.ts` or create `web/src/app/labeling/layout.test.tsx` if the project test setup supports component rendering.

**Interfaces:**
- Produces: `getTriagePage`, `getTriageDetail`, `decideTriage`, `manualQuarantineClip`.

- [ ] **Step 1: Add client types and functions**

Use these exact public types:

```ts
export type TriageTab = 'pending' | 'skipped' | 'labeled';
export type TriageDecision = 'label' | 'skip' | 'reset';
export interface TriageCounts { pending: number; skipped: number; labeled: number }
```

All calls use the existing `request<T>` helper so bearer token and error parsing remain centralized.

- [ ] **Step 2: Make quarantine an owner route**

In `categorize()` check `/labeling/quarantine` before the default `work` return and return `owner`. Add an owner-only nav link:

```tsx
{showTeamNav && navLink(
  '/labeling/quarantine',
  '격리함',
  pathname.startsWith('/labeling/quarantine'),
)}
```

Non-owner labelers must be redirected to `/labeling` before the page renders.

- [ ] **Step 3: Run type and access regressions**

Run:

```bash
cd web
npm test -- src/lib/labelingAccessGuards.test.ts
npx tsc --noEmit
```

Expected: owner access remains and no labeler route bypass is introduced.

---

### Task 6: Owner quarantine list and detail UX

**Files:**
- Create: `web/src/app/labeling/quarantine/page.tsx`
- Create: `web/src/app/labeling/quarantine/[clipId]/page.tsx`
- Modify: `web/src/app/labeling/page.tsx`

**Interfaces:**
- Consumes Task 5 client functions.
- Produces the approved three-tab owner workflow and auto-next decision flow.

- [ ] **Step 1: Build the list page**

The page must show:

```text
검토 필요 (count)
라벨링 안 함 (count)
라벨링으로 보냄 (count)
```

Preserve active tab and cursor in URL. Each card shows thumbnail, KST 촬영 시각, camera ID, duration, Korean reason, and links to `/labeling/quarantine/{clipId}?state={tab}`.

- [ ] **Step 2: Build the detail page**

Render in this order:

```tsx
<촬영시각·카메라·사유 헤더 />
<video controls playsInline src={signedUrl} />
<결정 버튼 영역 />
<최소 provenance: policy version/source />
```

Buttons:

- pending: `라벨링으로 보내기`, `라벨링 안 함`, `나중에 보기`
- skipped/labeled: `결정 초기화`, opposite decision

After successful decision, navigate to the `next_clip_id` captured by the detail GET. If null, return to the same tab list. `나중에 보기` performs no PATCH and uses the same next navigation.

- [ ] **Step 3: Handle conflicts and destructive-looking actions clearly**

Before `라벨링 안 함`, show:

```text
일반 라벨링 큐에서 계속 숨겨져. 영상은 삭제되지 않고 언제든 되돌릴 수 있어.
```

For `409 stale_state`, reload detail. For `409 labeling_started`, show `이미 라벨링이 시작되어 격리할 수 없어.` and return to the list after acknowledgment.

- [ ] **Step 4: Add owner manual quarantine to the main queue**

Use `useIsOwner()`. Add a small `격리함으로` button inside each card that calls `event.preventDefault()` and `event.stopPropagation()`, confirms, calls `manualQuarantineClip`, then removes only that card from local items. Labelers never render the button.

- [ ] **Step 5: Verify the user journey manually in local/preview**

Without production DB writes, use mocked API responses or a preview database and verify:

```text
owner list -> pending detail -> later -> next
owner pending -> label -> disappears from pending
owner pending -> skip -> appears in skipped
owner skipped -> reset -> returns to pending when system suggestion is quarantine
labeler direct URL -> redirect/403
stale tab -> 409 then reload
```

Take screenshots of list and detail for review. Do not deploy.

---

### Task 7: Documentation and full verification checkpoint

**Files:**
- Modify: `docs/DATABASE.md`
- Modify: `docs/FEATURES.md`
- Modify: `specs/next-session.md`
- Modify: `.claude/donts-audit.md`

- [ ] **Step 1: Update SOT as implemented-but-not-applied**

Document tables, RPCs, owner precedence, queue filtering, and status as:

```text
코드 구현 완료 / production migration 미적용 / worker 미실행 / 격리 데이터 0
```

Do not claim the feature is live.

- [ ] **Step 2: Run complete web verification**

Run:

```bash
cd /Users/baek/petcam-lab/web
npm test
npx tsc --noEmit
npm run build
cd /Users/baek/petcam-lab
uv run pytest
git diff --check
```

Expected: all web tests pass, TypeScript clean, Next build succeeds, Python suite passes, whitespace clean.

- [ ] **Step 3: Security audit**

Run:

```bash
rg -n "evidence_snapshot|checkpoint|producer_host|error\.message" web/src/app/api/labeling-triage web/src/lib/labelingTriage*
rg -n "GRANT|REVOKE|ENABLE ROW LEVEL SECURITY|SECURITY DEFINER|search_path" migrations/2026-07-15_labeling_triage.sql
```

Expected: no raw evidence in API response mapping, no internal DB error returned, and service-role-only writes are explicit.

- [ ] **Step 4: Stop and report**

Report changed files, tests, migration status, screenshots, and remaining approval steps. Do not stage, commit, push, apply migration, deploy, or start the worker.

## Post-implementation approval sequence

After user review, execute only one approved boundary at a time:

1. Apply migration and run rollback probes.
2. Deploy web preview and perform owner/labeler E2E.
3. Deploy production web with no system suggestions yet.
4. Execute the separate worker Preview 30 plan.
5. Approve a small suggestion write canary.
6. Approve limited backfill.

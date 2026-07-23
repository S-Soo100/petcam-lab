# Double-Blind Labeling Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 이중 블라인드 라벨링의 SQL 실행 오류·동시 제출 유실·GT 범위 초과·교차 객체 오염·draft 유실·그룹 재배정·중복 이벤트·canary 자격 결함을 실제 PostgreSQL 동시성 검증까지 포함해 닫는다.

**Architecture:** 아직 production에 적용되지 않은 `2026-07-23_motion_double_blind_labeling.sql`을 같은 feature 계열에서 하드닝한다. 모든 DB writer는 `consensus → slot → submission` 잠금 순서를 공유하고, live clip의 최초 group/reviewer pair를 불변 ownership으로 고정한다. API는 배정 확인 뒤 실제 clip duration으로 GT를 검증하며, 브라우저 draft는 user·clip·cohort·comparator version으로 격리한다. 정적 문자열 테스트만으로 SQL 정상 동작을 주장하지 않고, 최소 prerequisite schema를 가진 disposable PostgreSQL에서 migration 적용·동시 제출·rollback probe를 실행한다.

**Tech Stack:** PostgreSQL 15+/Supabase SQL, PL/pgSQL, Next.js 14 App Router, TypeScript, React, Vitest, pytest, Docker disposable Postgres.

## Global Constraints

- 기준 구현 HEAD는 `7556009da15d919c5ecbdea8a6983d711bf09d24`이며 이미 push된 구현 커밋은 amend·rebase·force-push하지 않는다. 하드닝은 새 커밋으로만 추가한다.
- `migrations/2026-07-23_motion_double_blind_labeling.sql`은 production 미적용이므로 이 파일 자체를 고친다. production 적용 전이므로 보정용 forward migration을 추가하지 않는다.
- DB writer 잠금 순서는 항상 `motion_clip_consensus → motion_clip_review_slots(id ASC) → motion_clip_blind_submissions(id ASC)`다. 역순 잠금은 금지한다.
- 동일 clip×cohort의 두 동시 제출은 둘 다 immutable submission으로 보존되고, 두 번째 transaction은 첫 번째 commit을 본 뒤 `peer_present=true`를 반환해야 한다.
- finalize 입력 두 건은 같은 clip·group·cohort의 서로 다른 reviewer 제출이어야 한다. 호출자가 넘긴 digest·상태·final payload가 comparator 결과와 교차 객체 identity를 위반하면 fail-closed한다.
- label 제출 GT segment는 실제 `motion_clips.duration_sec` 안에 있어야 한다. `3600` 같은 관대한 상한을 저장 검증에 쓰지 않는다.
- draft에는 decision·reason·GT·selected fields·version·scope만 저장한다. lease token, 상대 제출, VLM, Python Evidence, R2 key, auth token은 저장하지 않는다.
- live clip ownership은 최초 materialization 때 group과 reviewer pair가 고정된다. 카메라나 group member가 바뀌어도 기존 live clip에 세 번째 slot을 만들지 않는다.
- 기존 미제출 slot의 reviewer 교체는 `fn_reassign_motion_review_slot` 한 경로에서만 허용하며, slot 수는 계속 정확히 2다.
- finalize 재시도는 기존 consensus를 그대로 반환하고 `auto_compared` event를 추가하지 않는다.
- canary reviewer 두 명은 모두 `public.labelers`에 존재하고 `labeler_applications.status='approved'`이며, `p_group_id`의 현재 active member여야 한다.
- activity day 입력은 실제 존재하는 ISO calendar date만 허용한다. `2026-02-30`은 DB 접근 전에 400이다.
- labeler 응답에는 peer decision/GT/note/digest/UUID/lease token/VLM/evidence/R2 key를 노출하지 않는다.
- 기존 owner v3, legacy v2, tutorial, VLM, Gate, Python Evidence, activity 계산, UI copy/selection design은 변경하지 않는다.
- production migration apply, main merge, Vercel production deploy, 실제 group mapping, 실제 canary, Owner Pilot 151 dataset manifest 생성은 이 계획 범위 밖이다.
- disposable PostgreSQL runtime probe를 실행할 수 없으면 최종 판정은 `DOUBLE_BLIND_LABELING_HARDENING_BLOCKED_DB_RUNTIME`이다. 정적 테스트만으로 READY를 주장하지 않는다.

---

## File Structure

### Database contract

- Modify: `migrations/2026-07-23_motion_double_blind_labeling.sql`
  - aggregate row-lock 오류 제거
  - clip ownership 고정
  - 공통 lock order
  - submission/finalize identity와 event idempotency
  - canary reviewer 자격 강화
- Modify: `tests/test_motion_double_blind_labeling_migration.py`
  - SQL 정적 회귀와 runtime probe marker
- Create: `tests/sql/motion_double_blind_prerequisites.sql`
  - disposable DB에서 migration이 요구하는 최소 `auth.users`, `cameras`, `motion_clips`, `labelers`, `labeler_applications`, `service_role` fixture
- Create: `tests/sql/motion_double_blind_hardening_probe.sql`
  - aggregate 실행, ownership, cross-object, event idempotency, canary eligibility를 transaction 안에서 검증하고 rollback
- Create: `scripts/run_motion_double_blind_concurrency_probe.py`
  - disposable Postgres container 안의 `psql` 두 세션을 동시 실행해 submission race를 재현
- Create: `tests/test_motion_double_blind_runtime_probe.py`
  - probe runner의 명령·fail-closed·결과 parser 단위 테스트

### Server/API contract

- Modify: `web/src/app/api/labeling-v3/blind/_access.ts`
  - reviewer slot을 확인한 뒤 actual clip metadata를 반환하는 기존 helper 재사용/확장
- Modify: `web/src/app/api/labeling-v3/blind/[clipId]/submit/route.ts`
  - 실제 duration 검증과 bounded finalize retry
- Modify: `web/src/app/api/labeling-v3/blind/[clipId]/submit/route.test.ts`
  - duration, hidden existence, race/finalize response 회귀
- Modify: `web/src/app/api/labeling-v3/blind/owner/[clipId]/resolve/route.ts`
  - owner final GT도 실제 clip duration으로 검증
- Modify: `web/src/app/api/labeling-v3/blind/owner/[clipId]/resolve/route.test.ts`
  - owner over-duration 저장 차단 회귀
- Modify: `web/src/lib/motionBlindReviewServer.ts`
  - strict calendar date validator
- Modify: `web/src/lib/motionBlindReviewServer.test.ts`
  - leap day와 invalid calendar date
- Modify: `web/src/app/api/labeling-v3/blind/queue/route.test.ts`
  - invalid calendar date DB 접근 0

### Draft contract

- Create: `web/src/lib/motionBlindDraft.ts`
  - blind-only draft envelope, key, parse/read/write/clear
- Create: `web/src/lib/motionBlindDraft.test.ts`
  - user/clip/cohort/version isolation, malformed/stale lease exclusion, duration-aware restore
- Modify: `web/src/app/labeling/_blind-review-detail.tsx`
  - detail duration load 뒤 restore, debounce save, 성공 뒤 clear
- Modify: `web/src/app/labeling/_blind-hardening.test.ts`
  - draft wiring과 secret/non-blind field 부재 정적 회귀

### Documentation/report

- Modify: `docs/DATABASE.md`
- Modify: `docs/FEATURES.md`
- Modify: `specs/next-session.md`
- Modify: `.claude/donts-audit.md`
- Create: `docs/handoff-prompts/2026-07-24-double-blind-labeling-hardening-report.md`

---

### Task 0: Handoff Gate and Baseline

**Files:**
- Read: `AGENTS.md`
- Read: `CLAUDE.md`
- Read: `.claude/rules/donts.md`
- Read: `docs/superpowers/specs/2026-07-23-double-blind-labeling-groups-design.md`
- Read: `docs/superpowers/plans/2026-07-23-double-blind-labeling-groups.md`
- Read: `docs/superpowers/plans/2026-07-24-double-blind-labeling-hardening.md`
- Read: `docs/handoff-prompts/2026-07-23-double-blind-labeling-groups-report.md`

**Interfaces:**
- Consumes: tracked design, original plan, hardening plan, clean handoff manifest.
- Produces: verified implementation base; no code.

- [ ] **Step 1: Validate the handoff**

Run:

```bash
uv run python scripts/verify_agent_handoff.py --manifest /absolute/path/from-owner.md
```

Expected: exactly one line beginning:

```text
HANDOFF_OK task=double-blind-labeling-hardening
```

Any `HANDOFF_FAIL`, HEAD mismatch, missing artifact, or dirty plan/design is a hard stop.

- [ ] **Step 2: Confirm branch ownership**

Run:

```bash
git status --short --branch
git rev-parse HEAD
git merge-base --is-ancestor 7556009da15d919c5ecbdea8a6983d711bf09d24 HEAD
git diff --check
```

Expected: clean tree, ancestor command exit 0, no reset/rebase/checkout of another session's files.

- [ ] **Step 3: Run fresh baseline**

Run:

```bash
uv run pytest -q
cd web && npm test
cd web && npx tsc --noEmit
```

Expected at handoff creation: Python `731 passed`, web `705 passed`, TypeScript exit 0. If additional committed tests changed totals, record the exact new totals and require zero failures.

- [ ] **Step 4: Record no-commit gate**

No commit in Task 0.

---

### Task 1: Fix SQL Runtime Locking and Freeze Live Clip Ownership

**Files:**
- Modify: `migrations/2026-07-23_motion_double_blind_labeling.sql`
- Modify: `tests/test_motion_double_blind_labeling_migration.py`

**Interfaces:**
- Consumes: active group with exactly two approved members; existing consensus/slots.
- Produces:
  - `fn_ensure_motion_review_slots(uuid,date) → integer`
  - invariant: each live clip has exactly one consensus group and exactly two live slots
  - lock order root: consensus before slots

- [ ] **Step 1: Add failing static contract tests**

Add tests equivalent to:

```python
import re


def function_body(sql: str, name: str) -> str:
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\\.{re.escape(name)}\\b.*?AS \\$\\$(.*?)\\$\\$;",
        sql,
        re.S | re.I,
    )
    assert match is not None, f"missing function: {name}"
    return match.group(1)


def test_ensure_does_not_apply_for_update_to_aggregate(sql: str) -> None:
    body = function_body(sql, "fn_ensure_motion_review_slots")
    assert not re.search(r"array_agg\\([^;]+FOR UPDATE", body, re.S | re.I)
    assert "PERFORM 1" in body
    assert "ORDER BY user_id" in body
    assert "FOR UPDATE" in body


def test_live_ownership_is_claimed_once_and_slots_never_expand(sql: str) -> None:
    body = function_body(sql, "fn_ensure_motion_review_slots")
    assert "v_owned_group_id" in body
    assert "v_live_slot_count" in body
    assert "live clip must have zero or two slots" in body
    assert "consensus group mismatch" in body
```

- [ ] **Step 2: Run RED**

Run:

```bash
uv run pytest -q tests/test_motion_double_blind_labeling_migration.py \
  -k 'aggregate or ownership or slots'
```

Expected: new tests fail against the aggregate `SELECT ... FOR UPDATE` and current cross-join insertion.

- [ ] **Step 3: Replace aggregate locking with row locking plus plain aggregate**

Use two separate statements:

```sql
PERFORM 1
FROM public.motion_labeling_review_group_members
WHERE group_id = v_group_id AND ended_at IS NULL
ORDER BY user_id
FOR UPDATE;

SELECT array_agg(user_id ORDER BY user_id)
INTO v_members
FROM public.motion_labeling_review_group_members
WHERE group_id = v_group_id AND ended_at IS NULL;
```

Do not place a locking clause on an aggregate query.

- [ ] **Step 4: Materialize clip ownership without adding a third reviewer**

For every candidate clip, implement this exact state machine inside the migration:

```text
lock/create the live consensus row
if consensus.group_id != current group: skip this clip
lock existing live slots ordered by id
if slot_count == 0: insert the current two members
if slot_count == 2: preserve the existing reviewer pair unchanged
otherwise: raise PT425 "live clip must have zero or two slots"
```

The SQL must never cross-join current members into a clip that already has live slots. Keep `fn_reassign_motion_review_slot` as the only reviewer replacement path.

- [ ] **Step 5: Run GREEN**

Run:

```bash
uv run pytest -q tests/test_motion_double_blind_labeling_migration.py
git diff --check
```

Expected: migration tests pass and whitespace is clean.

- [ ] **Step 6: Commit**

```bash
git add migrations/2026-07-23_motion_double_blind_labeling.sql \
  tests/test_motion_double_blind_labeling_migration.py
git commit -m "fix: 이중 블라인드 slot 잠금과 소유권 고정"
```

---

### Task 2: Serialize Concurrent Submissions and Validate Finalize Identity

**Files:**
- Modify: `migrations/2026-07-23_motion_double_blind_labeling.sql`
- Modify: `tests/test_motion_double_blind_labeling_migration.py`

**Interfaces:**
- Consumes: Task 1 consensus ownership and lock order.
- Produces:
  - concurrent second submit sees committed peer
  - finalize accepts only one same-clip/group/cohort distinct-reviewer pair
  - idempotent finalize emits one `auto_compared` event

- [ ] **Step 1: Add failing lock-order and identity tests**

Add assertions equivalent to:

```python
def test_submit_locks_shared_consensus_before_slot(sql: str) -> None:
    body = function_body(sql, "fn_submit_motion_blind_review")
    assert body.index("FROM public.motion_clip_consensus") < body.index(
        "FROM public.motion_clip_review_slots"
    )


def test_finalize_checks_pair_identity_and_distinct_reviewers(sql: str) -> None:
    body = function_body(sql, "fn_finalize_motion_blind_consensus")
    for marker in (
        "v_a.clip_id <> p_clip_id",
        "v_b.clip_id <> p_clip_id",
        "v_a.group_id <> v_b.group_id",
        "v_a.reviewer_id = v_b.reviewer_id",
        "v_a.cohort_kind <> p_cohort_kind",
        "v_b.cohort_kind <> p_cohort_kind",
    ):
        assert marker in body


def test_auto_compared_event_is_transition_only(sql: str) -> None:
    body = function_body(sql, "fn_finalize_motion_blind_consensus")
    assert "v_did_transition boolean := false" in body
    assert "IF v_did_transition THEN" in body
```

- [ ] **Step 2: Run RED**

Run:

```bash
uv run pytest -q tests/test_motion_double_blind_labeling_migration.py \
  -k 'submit or finalize or auto_compared'
```

Expected: current migration fails lock-order, identity, and event transition assertions.

- [ ] **Step 3: Apply one global writer lock order**

In `fn_submit_motion_blind_review`:

```sql
SELECT * INTO v_consensus
FROM public.motion_clip_consensus c
WHERE c.clip_id = p_clip_id
  AND c.cohort_kind = p_cohort_kind
  AND c.cohort_id IS NOT DISTINCT FROM p_cohort_id
FOR UPDATE;
```

Lock this shared row before locking the reviewer's slot. Re-read and lock the slot after the consensus lock. Verify `v_slot.group_id = v_consensus.group_id`. Because both reviewers now contend on one consensus row, the transaction entering second must see the first committed submission.

In `fn_finalize_motion_blind_consensus`, lock in this order:

```text
consensus row
submission with smaller UUID
submission with larger UUID
```

Do not lock submissions before consensus.

- [ ] **Step 4: Add fail-closed pair checks**

Before updating consensus, reject with SQLSTATE `22023` unless all are true:

```text
submission_a.id != submission_b.id
submission_a.clip_id = submission_b.clip_id = p_clip_id
submission_a.group_id = submission_b.group_id = consensus.group_id
submission_a.reviewer_id != submission_b.reviewer_id
both cohort_kind = p_cohort_kind
both cohort_id IS NOT DISTINCT FROM p_cohort_id
both submission.slot_id refer to slots with the same identity
status/final_decision/final_gt shape matches agreed vs conflict
```

For `agreed`, require a non-null `p_final_decision`; require `p_final_gt` only when decision is `label`. For `conflict`, require `p_final_decision` and `p_final_gt` to be null.

- [ ] **Step 5: Make event creation transition-only**

Initialize:

```sql
v_did_transition boolean := false;
```

Set it true only when an awaiting row is inserted/finalized or updated from `awaiting`. Wrap the event insert:

```sql
IF v_did_transition THEN
  INSERT INTO public.motion_clip_consensus_events (...);
END IF;
```

An already finalized row returns unchanged and appends no event.

- [ ] **Step 6: Run GREEN**

Run:

```bash
uv run pytest -q tests/test_motion_double_blind_labeling_migration.py
git diff --check
```

Expected: all migration tests pass.

- [ ] **Step 7: Commit**

```bash
git add migrations/2026-07-23_motion_double_blind_labeling.sql \
  tests/test_motion_double_blind_labeling_migration.py
git commit -m "fix: 이중 제출 경합과 합의 identity 검증"
```

---

### Task 3: Validate GT Against Actual Clip Duration

**Files:**
- Modify: `web/src/app/api/labeling-v3/blind/_access.ts`
- Modify: `web/src/app/api/labeling-v3/blind/[clipId]/submit/route.ts`
- Modify: `web/src/app/api/labeling-v3/blind/[clipId]/submit/route.test.ts`
- Modify: `web/src/app/api/labeling-v3/blind/owner/[clipId]/resolve/route.ts`
- Modify: `web/src/app/api/labeling-v3/blind/owner/[clipId]/resolve/route.test.ts`

**Interfaces:**
- Consumes: bearer-derived reviewer, clip/cohort assignment, `duration_sec`.
- Produces: `getAssignedBlindClip(...)` or equivalent existing access result with actual duration; no clip existence leak.

- [ ] **Step 1: Write failing API tests**

Add cases with a 30-second clip:

```ts
it('rejects a label segment past the assigned clip duration', async () => {
  assignedClip.mockResolvedValue({ duration_sec: 30, /* existing safe fields */ });
  const res = await POST(req(labelBodyWithSegment(0, 30.001)), ctx);
  expect(res.status).toBe(400);
  expect(rpc).not.toHaveBeenCalledWith('fn_submit_motion_blind_review', expect.anything());
});

it('accepts a segment ending exactly at duration', async () => {
  assignedClip.mockResolvedValue({ duration_sec: 30, /* existing safe fields */ });
  const res = await POST(req(labelBodyWithSegment(0, 30)), ctx);
  expect(res.status).toBe(200);
});

it('does not reveal whether an unassigned clip exists', async () => {
  assignedClip.mockResolvedValue(null);
  const res = await POST(req(labelBodyWithSegment(0, 1)), ctx);
  expect(res.status).toBe(404);
  expect(await res.json()).toEqual({ detail: expect.any(String), code: 'not_assigned' });
});

it('rejects an owner resolution segment past the actual clip duration', async () => {
  ownerClip.mockResolvedValue({ duration_sec: 30 });
  const res = await RESOLVE(resolveReq(finalGtWithSegment(0, 30.001)), ctx);
  expect(res.status).toBe(400);
  expect(rpc).not.toHaveBeenCalledWith('fn_resolve_motion_blind_consensus', expect.anything());
});
```

- [ ] **Step 2: Run RED**

Run:

```bash
cd web && npm test -- \
  src/app/api/labeling-v3/blind/[clipId]/submit/route.test.ts
```

Expected: over-duration segment is currently accepted because `GT_DURATION_CAP=3600`.

- [ ] **Step 3: Reuse the blind access boundary**

Extend the existing assignment helper in `_access.ts`; do not issue an unrestricted `motion_clips` lookup before reviewer authorization. The helper return must include:

```ts
type AssignedBlindClip = {
  clipId: string;
  durationSec: number;
  groupId: string;
  cohortKind: 'live' | 'canary';
  cohortId: string | null;
};
```

Return the same generalized `not_assigned` result for missing clip, wrong reviewer, wrong cohort, or closed canary.

- [ ] **Step 4: Replace the duration cap**

Delete `GT_DURATION_CAP` from both labeler submit and owner resolve. After access succeeds:

```ts
const gt = validateGroundTruth(body.initial_gt, assigned.durationSec);
```

Owner resolve may query `motion_clips.duration_sec` only after `requireProductionLabelingAccess` succeeds. Preserve the existing GT allowlist and peer-data response allowlist.

- [ ] **Step 5: Run GREEN**

Run:

```bash
cd web && npm test -- \
  src/app/api/labeling-v3/blind/[clipId]/submit/route.test.ts \
  src/app/api/labeling-v3/blind/[clipId]/route.test.ts \
  src/app/api/labeling-v3/blind/[clipId]/file/url/route.test.ts \
  src/app/api/labeling-v3/blind/owner/[clipId]/resolve/route.test.ts
cd web && npx tsc --noEmit
```

Expected: focused tests pass and TypeScript exits 0.

- [ ] **Step 6: Commit**

```bash
git add web/src/app/api/labeling-v3/blind/_access.ts \
  web/src/app/api/labeling-v3/blind/[clipId]/submit/route.ts \
  web/src/app/api/labeling-v3/blind/[clipId]/submit/route.test.ts \
  web/src/app/api/labeling-v3/blind/owner/[clipId]/resolve/route.ts \
  web/src/app/api/labeling-v3/blind/owner/[clipId]/resolve/route.test.ts
git commit -m "fix: 블라인드 GT를 실제 영상 길이로 검증"
```

---

### Task 4: Persist and Restore Blind Drafts Safely

**Files:**
- Create: `web/src/lib/motionBlindDraft.ts`
- Create: `web/src/lib/motionBlindDraft.test.ts`
- Modify: `web/src/app/labeling/_blind-review-detail.tsx`
- Modify: `web/src/app/labeling/_blind-hardening.test.ts`

**Interfaces:**
- Consumes: `GroundTruthInput`, `GroundTruthField`, `BlindDecision`, `BlindReasonCode`, actual duration.
- Produces:
  - `blindDraftKey(userId, clipId, cohortKind, cohortId, comparatorVersion)`
  - `parseBlindDraft(raw, expectedScope, duration)`
  - `readBlindDraft`, `writeBlindDraft`, `clearBlindDraft`

- [ ] **Step 1: Write failing pure tests**

Define the envelope:

```ts
interface BlindDraftV1 {
  v: 1;
  userId: string;
  clipId: string;
  cohortKind: 'live' | 'canary';
  cohortId: string | null;
  comparatorVersion: 'motion-blind-v1';
  decision: BlindDecision | null;
  reasonCode: BlindReasonCode;
  gt: GroundTruthInput;
  selected: GroundTruthField[];
  savedAt: string;
}
```

Test:

```text
same scope round-trip
different user rejected
different clip rejected
live/canary or cohort mismatch rejected
wrong version/comparator rejected
malformed enum/GT/selected rejected and removed
segment beyond current duration rejected and removed
payload contains no lease_token, peer, vlm, evidence, r2_key
```

- [ ] **Step 2: Run RED**

Run:

```bash
cd web && npm test -- src/lib/motionBlindDraft.test.ts
```

Expected: module missing.

- [ ] **Step 3: Implement pure draft storage**

Use `sessionStorage`, matching `labelingDraft.ts` fail-soft behavior. The key must include user, clip, cohort kind/id, and comparator version. Parsing must validate both shape and `validateGroundTruth(draft.gt, actualDuration)`; storage errors must never block submission.

Do not persist the lease token. A restored draft must acquire a fresh/current lease through the existing claim flow.

- [ ] **Step 4: Wire restore only after detail duration loads**

In `_blind-review-detail.tsx`:

```text
load authorized detail
set actual duration
read+validate matching draft
restore decision/reason/gt/selected
claim/refresh lease independently
debounce-save edits while not submitted
clear only matching draft after successful submit
```

Replace the unused raw `draftKey` string and `localStorage.removeItem` with the new helper. Show one non-blocking message when a draft is restored.

- [ ] **Step 5: Add wiring security assertions**

In `_blind-hardening.test.ts`, assert the detail source imports the blind draft helper and does not serialize:

```text
leaseTokenRef
peer_
vlm
evidence
r2_key
```

The test must inspect the draft payload builder, not merely comments.

- [ ] **Step 6: Run GREEN**

Run:

```bash
cd web && npm test -- \
  src/lib/motionBlindDraft.test.ts \
  src/app/labeling/_blind-hardening.test.ts
cd web && npx tsc --noEmit
```

Expected: focused tests pass and TypeScript exits 0.

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/motionBlindDraft.ts \
  web/src/lib/motionBlindDraft.test.ts \
  web/src/app/labeling/_blind-review-detail.tsx \
  web/src/app/labeling/_blind-hardening.test.ts
git commit -m "feat: 블라인드 라벨 입력 임시 저장과 복원"
```

---

### Task 5: Harden Canary Eligibility and Calendar Dates

**Files:**
- Modify: `migrations/2026-07-23_motion_double_blind_labeling.sql`
- Modify: `tests/test_motion_double_blind_labeling_migration.py`
- Modify: `web/src/lib/motionBlindReviewServer.ts`
- Modify: `web/src/lib/motionBlindReviewServer.test.ts`
- Modify: `web/src/app/api/labeling-v3/blind/queue/route.test.ts`

**Interfaces:**
- Consumes: current group member rows, `labelers`, approved applications.
- Produces: eligible two-person canary and strict `YYYY-MM-DD` real-date validator.

- [ ] **Step 1: Add failing canary eligibility tests**

Require the canary function body to join all three sources:

```python
for marker in (
    "public.labelers",
    "public.labeler_applications",
    "public.motion_labeling_review_group_members",
    "ended_at IS NULL",
):
    assert marker.lower() in canary_body.lower()
```

Also assert both reviewer IDs belong to `p_group_id`.

- [ ] **Step 2: Add failing date tests**

Add:

```ts
expect(isValidActivityDay('2024-02-29')).toBe(true);
expect(isValidActivityDay('2026-02-29')).toBe(false);
expect(isValidActivityDay('2026-04-31')).toBe(false);
expect(isValidActivityDay('2026-13-01')).toBe(false);
```

Queue route test must prove invalid dates return 400 before `fn_list_motion_blind_queue`.

- [ ] **Step 3: Run RED**

Run:

```bash
uv run pytest -q tests/test_motion_double_blind_labeling_migration.py -k canary
cd web && npm test -- \
  src/lib/motionBlindReviewServer.test.ts \
  src/app/api/labeling-v3/blind/queue/route.test.ts
```

Expected: current application-only canary check and regex-only date check fail.

- [ ] **Step 4: Enforce reviewer eligibility**

The canary create action must count exactly two distinct reviewers satisfying:

```sql
EXISTS (SELECT 1 FROM public.labelers l WHERE l.user_id = r.uid)
AND EXISTS (
  SELECT 1 FROM public.labeler_applications a
  WHERE a.user_id = r.uid AND a.status = 'approved'
)
AND EXISTS (
  SELECT 1 FROM public.motion_labeling_review_group_members gm
  WHERE gm.group_id = p_group_id
    AND gm.user_id = r.uid
    AND gm.ended_at IS NULL
)
```

Failure SQLSTATE remains `PT425`.

- [ ] **Step 5: Implement strict calendar validation**

Keep the lexical regex, then round-trip UTC components:

```ts
export function isValidActivityDay(value: string | null): value is string {
  if (typeof value !== 'string' || !ACTIVITY_DAY.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year
    && parsed.getUTCMonth() === month - 1
    && parsed.getUTCDate() === day;
}
```

- [ ] **Step 6: Run GREEN**

Run:

```bash
uv run pytest -q tests/test_motion_double_blind_labeling_migration.py -k canary
cd web && npm test -- \
  src/lib/motionBlindReviewServer.test.ts \
  src/app/api/labeling-v3/blind/queue/route.test.ts
```

Expected: focused suites pass.

- [ ] **Step 7: Commit**

```bash
git add migrations/2026-07-23_motion_double_blind_labeling.sql \
  tests/test_motion_double_blind_labeling_migration.py \
  web/src/lib/motionBlindReviewServer.ts \
  web/src/lib/motionBlindReviewServer.test.ts \
  web/src/app/api/labeling-v3/blind/queue/route.test.ts
git commit -m "fix: canary 자격과 활동일 입력 검증 강화"
```

---

### Task 6: Prove SQL Runtime and Submission Concurrency in Disposable Postgres

**Files:**
- Create: `tests/sql/motion_double_blind_prerequisites.sql`
- Create: `tests/sql/motion_double_blind_hardening_probe.sql`
- Create: `scripts/run_motion_double_blind_concurrency_probe.py`
- Create: `tests/test_motion_double_blind_runtime_probe.py`
- Modify: `tests/test_motion_double_blind_labeling_migration.py`

**Interfaces:**
- Consumes: Docker, local `postgres:15` image, migration SQL.
- Produces: machine-readable `DB_RUNTIME_PROBE_OK` and `DB_CONCURRENCY_PROBE_OK`; no production connection.

- [ ] **Step 1: Write runner unit tests before the runner**

Test with a fake command executor:

```python
def test_runner_refuses_non_local_database_url() -> None:
    with pytest.raises(ProbeBlocked, match="non_local_database_forbidden"):
        validate_database_url("postgresql://example.com/db")


def test_runner_requires_both_concurrent_submissions() -> None:
    result = parse_probe_rows([
        {"reviewer": "a", "peer_present": "f"},
        {"reviewer": "b", "peer_present": "f"},
    ])
    assert result.verdict == "CONCURRENCY_FAILED"


def test_runner_accepts_exactly_one_peer_observer() -> None:
    result = parse_probe_rows([
        {"reviewer": "a", "peer_present": "f"},
        {"reviewer": "b", "peer_present": "t"},
    ])
    assert result.verdict == "DB_CONCURRENCY_PROBE_OK"
```

- [ ] **Step 2: Run RED**

Run:

```bash
uv run pytest -q tests/test_motion_double_blind_runtime_probe.py
```

Expected: runner module missing.

- [ ] **Step 3: Build the minimum prerequisite schema**

`tests/sql/motion_double_blind_prerequisites.sql` must create only:

```text
schema auth
role service_role
auth.users(id)
public.cameras(id,name)
public.motion_clips(id,camera_id,started_at,duration_sec,r2_key)
public.labelers(user_id)
public.labeler_applications(user_id,status)
```

Use UUID and timestamptz types matching production. Do not copy production rows, secrets, emails, R2 keys, notes, or auth data.

- [ ] **Step 4: Write the rollback probe**

The probe must create synthetic UUIDs inside one transaction and assert:

```text
fn_ensure_motion_review_slots executes without aggregate FOR UPDATE error
first ensure creates exactly 2 live slots
ending/replacing group members then ensuring does not create a third slot
camera reassignment does not change existing consensus.group_id
cross-clip finalize rejected
cross-group finalize rejected
cross-cohort finalize rejected
same-reviewer finalize rejected
wrong agreed/conflict payload shape rejected
second identical finalize leaves auto_compared event count at 1
canary rejects approved application without labelers membership
canary rejects reviewer outside p_group_id
eligible active pair succeeds
all synthetic rows are removed by final ROLLBACK
```

Every expected error must assert its SQLSTATE, not its raw message.

- [ ] **Step 5: Implement the two-session race**

The Python runner must:

```text
start a disposable postgres:15 container bound only to 127.0.0.1
apply prerequisites.sql
apply the migration under test
insert one clip, one group, two active reviewers, two slots, one awaiting consensus
claim both slots with distinct tokens
open two psql sessions simultaneously
submit reviewer A and reviewer B for the same clip
require two immutable submissions
require peer_present multiset == {false,true}
call finalize from the peer-aware result
require consensus != awaiting and auto_compared count == 1
run identical finalize again and require event count still 1
drop the container in finally
```

Use a random container name and a random free localhost port. Pass SQL through temporary files under `storage/` or the system temp directory; remove them in `finally`. Never accept a hostname other than `127.0.0.1`/`localhost`.

- [ ] **Step 6: Run the runtime probes**

Run:

```bash
uv run pytest -q tests/test_motion_double_blind_runtime_probe.py
uv run python scripts/run_motion_double_blind_concurrency_probe.py \
  --migration migrations/2026-07-23_motion_double_blind_labeling.sql \
  --prerequisites tests/sql/motion_double_blind_prerequisites.sql \
  --probe tests/sql/motion_double_blind_hardening_probe.sql
```

Expected:

```text
DB_RUNTIME_PROBE_OK
DB_CONCURRENCY_PROBE_OK
PROBE_RESIDUE=0
```

If Docker is unavailable, the image is unavailable without an approved download, container startup fails, or either marker is absent, stop with `DOUBLE_BLIND_LABELING_HARDENING_BLOCKED_DB_RUNTIME`.

- [ ] **Step 7: Commit**

```bash
git add tests/sql/motion_double_blind_prerequisites.sql \
  tests/sql/motion_double_blind_hardening_probe.sql \
  scripts/run_motion_double_blind_concurrency_probe.py \
  tests/test_motion_double_blind_runtime_probe.py \
  tests/test_motion_double_blind_labeling_migration.py
git commit -m "test: 이중 블라인드 DB 동시성 실증"
```

---

### Task 7: Full Verification, Security Audit, and Handoff Report

**Files:**
- Modify: `docs/DATABASE.md`
- Modify: `docs/FEATURES.md`
- Modify: `specs/next-session.md`
- Modify: `.claude/donts-audit.md`
- Create: `docs/handoff-prompts/2026-07-24-double-blind-labeling-hardening-report.md`

**Interfaces:**
- Consumes: Tasks 1–6 commits and probe outputs.
- Produces: reviewable hardening branch; no deployment.

- [ ] **Step 1: Run all tests**

Run:

```bash
uv run pytest -q
cd web && npm test
cd web && npx tsc --noEmit
git diff --check
```

Expected: all suites pass, TypeScript exit 0, whitespace clean.

- [ ] **Step 2: Run a production build without misreporting**

Run only if the repository safety hook allows it:

```bash
cd web && npm run build
```

Expected: Next.js build success. If `donts#9` blocks in-session execution, record the exact blocked output and leave build as `UNVERIFIED`; do not substitute `tsc` as build evidence.

- [ ] **Step 3: Re-run DB runtime evidence**

Run:

```bash
uv run python scripts/run_motion_double_blind_concurrency_probe.py \
  --migration migrations/2026-07-23_motion_double_blind_labeling.sql \
  --prerequisites tests/sql/motion_double_blind_prerequisites.sql \
  --probe tests/sql/motion_double_blind_hardening_probe.sql
```

Expected all three markers from Task 6.

- [ ] **Step 4: Perform static secret and blind-leak audit**

Run:

```bash
rg -n "peer_(decision|initial_gt|note|digest)|lease_token|r2_key|evidence|vlm" \
  web/src/app/api/labeling-v3/blind web/src/lib/motionBlindDraft.ts
rg -n "@[A-Za-z0-9.-]+|SUPABASE_SERVICE_ROLE|R2_SECRET|BEGIN (RSA|OPENSSH) PRIVATE" \
  migrations/2026-07-23_motion_double_blind_labeling.sql \
  tests/sql scripts/run_motion_double_blind_concurrency_probe.py
git ls-files | rg '\\.(mp4|mov|avi|mkv|jpg|jpeg|png)$'
```

Expected: API matches are server-internal peer rows only and never response mapping; draft matches are zero; secret/email/private-key matches zero; no newly tracked media.

- [ ] **Step 5: Review the large diff by functional group**

Run:

```bash
git diff --stat 7556009da15d919c5ecbdea8a6983d711bf09d24..HEAD
git diff 7556009da15d919c5ecbdea8a6983d711bf09d24..HEAD -- \
  migrations tests/sql tests/test_motion_double_blind_labeling_migration.py
git diff 7556009da15d919c5ecbdea8a6983d711bf09d24..HEAD -- \
  web/src/app/api/labeling-v3/blind web/src/lib/motionBlindReviewServer.ts
git diff 7556009da15d919c5ecbdea8a6983d711bf09d24..HEAD -- \
  web/src/lib/motionBlindDraft.ts web/src/app/labeling/_blind-review-detail.tsx
```

Expected: no unrelated refactor or feature expansion.

- [ ] **Step 6: Write the report**

The report must include:

```text
starting HANDOFF_OK line
task-by-task commit SHA
P0/P1/P2 finding → exact fix mapping
actual DB runtime and concurrency markers
full test/build results
blind leak and secret audit
files changed
known unverified items
explicit non-actions
final verdict
```

Allowed final verdicts:

```text
DOUBLE_BLIND_LABELING_HARDENED_READY_FOR_DB_PREVIEW
DOUBLE_BLIND_LABELING_HARDENING_BLOCKED_DB_RUNTIME
DOUBLE_BLIND_LABELING_HARDENING_BLOCKED_REGRESSION
```

The READY verdict requires all Task 6 markers and all Task 7 test suites. Build may remain separately owner-unverified only when blocked solely by the repository safety hook.

- [ ] **Step 7: Update SOT additively**

Record that implementation exists but remains un-applied. Preserve historical report text; add a new dated top block stating:

```text
hardening branch SHA
migration production applied=false
main merged=false
real groups mapped=false
Owner Pilot 151 manifest not started
next gate=Codex review → disposable DB evidence review → separate preview deployment handoff
```

- [ ] **Step 8: Commit and push**

```bash
git add docs/DATABASE.md docs/FEATURES.md specs/next-session.md \
  .claude/donts-audit.md \
  docs/handoff-prompts/2026-07-24-double-blind-labeling-hardening-report.md
git commit -m "docs: 이중 블라인드 하드닝 검증 기록"
git push -u origin codex/double-blind-labeling-hardening
git status --short --branch
```

Expected: local branch equals origin and worktree is clean.

- [ ] **Step 9: Stop**

Do not apply the migration, merge main, deploy Vercel, map real users, create a canary, or generate the Owner Pilot 151 manifest. Return the report path and stop for Codex review.

---

## Post-Hardening Sequence (Not Part of This Implementation)

1. Codex reviews the hardening diff and disposable DB evidence.
2. A separate preview deployment handoff applies the migration to a safe DB target and runs the owner-approved 12-clip isolated canary.
3. Only after canary acceptance may main/production integration be considered.
4. After the labeling system is accepted, create a separate `Owner Pilot 151` frozen manifest and select the episode-distinct 12-clip blind comparison cohort.

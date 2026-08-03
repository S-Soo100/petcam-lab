# RBA SOT Reset + R2 Owner Cleanup v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire local/Claude/automatic-grouping research in active SOT, quarantine the two contaminated camera-days, permanently delete the 46 Owner-confirmed invalid R2 videos, and open a fail-closed Owner review path for the remaining videos.

**Architecture:** Reuse `motion_clip_system_exclusions` as the universal deny layer, but add a dedicated append-only Owner cleanup cohort/item/decision ledger for provenance and R2 prefix movement. A TDD-built one-shot runner freezes the 951-object manifest, performs copy/HEAD/DB-CAS/source-delete steps idempotently, and deletes only the 46 immutable Owner-confirmed invalid clips. The labeling web reads only allowlisted cleanup projections; no browser response exposes R2 keys, user UUIDs, or raw GT.

**Tech Stack:** PostgreSQL/Supabase migrations and RPCs, Python 3.12 + boto3 + supabase-py, Next.js/TypeScript/Vitest, Cloudflare R2 S3 API.

## Global Constraints

- Work in `/Users/baek/.codex/worktrees/8faf/petcam-lab`; preserve all pre-existing dirty changes.
- Do not commit, push, merge, or deploy unrelated files. Git commit requires a separate explicit Owner instruction.
- Production mutation is limited to the approved cleanup cohort, its exclusion ledger, R2 prefix moves, and confirmed 46-object deletion.
- Do not delete `motion_clips`, human GT, boundary reviews, submissions, consensus, or exclusion audit rows.
- No local VLM, Python Evidence, OpenAI, Claude, Gate, or heuristic output may authorize deletion.
- Freeze gates before mutation: exact `951 candidates / 46 confirmed invalid / 1 canonical-GT protected / 904 Owner review`, duplicate 0, candidate-to-valid-overlap 0 for the confirmed 46. Runtime HEAD preflight found `944/951` source videos and safely classified the other 7 as `source_missing`; the 46 deletion targets and protected GT were all present.
- R2 move order is copy → destination HEAD equality → DB CAS → source delete → source HEAD 404. A failed step remains recoverable and is recorded without advancing state.
- Quarantined or deleted clips must remain unavailable to dataset builders, signed URLs, labeling queues, and research samplers.
- The early-window audit boundary is KST `2026-06-30T00:00:00+09:00` through `2026-07-15T23:59:59.999999+09:00`.

---

### Task 1: Current SOT reset

**Files:**
- Modify: `specs/next-session.md`
- Modify: `specs/feature-rba-data-engine-v1.md`
- Modify: `docs/AI-VIDEO-ANALYSIS-STRATEGY.md`
- Modify: `AGENTS.md`
- Modify: `docs/decision-gate.md`
- Modify: `experiments/INDEX.md`
- Modify: `specs/README.md`
- Modify: `docs/superpowers/specs/2026-08-03-rba-openai-reset-and-dataset-v2-design.md`

**Interfaces:**
- Consumes: Owner-approved reset decisions in the design spec.
- Produces: one active next-step contract referenced by all agents and later cleanup code.

- [x] **Step 1: Add the new decision block to the top of `specs/next-session.md`**

The block must state `RBA_OPENAI_RESET_APPROVED`, retire local VLM/router/automatic event grouping/Claude CLI, preserve deterministic media preparation, and order next work as R2 cleanup → Dataset v2 → OpenAI API pilot.

- [x] **Step 2: Replace active local/event-grouping execution steps in Data Engine and strategy SOT**

Historical result sections stay intact. Active sections must point to the new design and must not instruct a future agent to resume local VLM, router, Claude CLI, or automatic event grouping.

- [x] **Step 3: Append the four-gate decision row**

`docs/decision-gate.md` must record adopted reset, rejected “new videos only”, rejected in-place dataset-203 mutation, and approved human-only R2 deletion authority.

- [x] **Step 4: Verify active wording**

Run:

```bash
rg -n "현재 실행 우선순위|다음.*local VLM|자동 사건 묶기|Claude CLI" \
  AGENTS.md specs/next-session.md specs/feature-rba-data-engine-v1.md \
  docs/AI-VIDEO-ANALYSIS-STRATEGY.md
git diff --check
```

Expected: only historical/retired references remain; no whitespace errors.

---

### Task 2: Owner cleanup database contract

**Files:**
- Create: `migrations/2026-08-03_rba_owner_media_cleanup_v1.sql`
- Create: `tests/test_rba_owner_media_cleanup_migration.py`
- Create: `tests/sql/rba_owner_media_cleanup_v1_probe.sql`
- Create: `scripts/run_rba_owner_media_cleanup_probe.py`
- Modify: `docs/DATABASE.md`

**Interfaces:**
- Consumes: existing `rba_boundary_eligibility_reviews`, `motion_clips`, `motion_clip_system_exclusions`.
- Produces: `rba_owner_media_cleanup_cohorts`, `rba_owner_media_cleanup_items`, `rba_owner_media_cleanup_decisions`; RPCs `fn_prepare_rba_owner_media_cleanup_v1`, `fn_list_rba_owner_media_cleanup_v1`, `fn_decide_rba_owner_media_cleanup_v1`, `fn_claim_rba_owner_media_move_v1`, `fn_complete_rba_owner_media_move_v1`, `fn_fail_rba_owner_media_move_v1`.

- [x] **Step 1: Write failing static migration tests**

Tests must require RLS, zero client policies, append-only decision/event triggers, service-role-only RPC grants, exact reason allowlist, exact freeze counts, canonical-GT delete block, quarantine/deleted exclusion, and no `DELETE FROM motion_clips`.

- [x] **Step 2: Run RED**

Run:

```bash
uv run pytest tests/test_rba_owner_media_cleanup_migration.py -q
```

Expected: FAIL because the migration does not exist.

- [x] **Step 3: Implement the forward-only migration**

The migration must extend the exclusion reason constraint with:

```text
owner_cleanup_candidate
owner_gecko_absent
owner_no_gecko_activity
```

It must keep unreviewed candidates in `quarantined` with `delete_after='infinity'`, set the confirmed 46 to delete-pending only after exact immutable eligibility provenance, and reject delete decisions for any clip with canonical GT.

- [x] **Step 4: Run GREEN and disposable PostgreSQL probe**

Run:

```bash
uv run pytest tests/test_rba_owner_media_cleanup_migration.py -q
uv run python scripts/run_rba_owner_media_cleanup_probe.py
```

Expected: tests pass; probe ends with `RBA_OWNER_MEDIA_CLEANUP_PROBE_OK` and residue 0.

---

### Task 3: Idempotent R2 manifest and mover

**Files:**
- Create: `scripts/rba_owner_media_cleanup.py`
- Create: `tests/test_rba_owner_media_cleanup.py`
- Create at runtime only: `~/Library/Application Support/petcam/rba-owner-media-cleanup-v1/manifest.private.json`

**Interfaces:**
- Produces pure functions:
  - `build_quarantine_key(original_key: str, clip_id: str) -> str`
  - `build_excluded_key(original_key: str, clip_id: str) -> str`
  - `validate_frozen_counts(items: Sequence[CleanupItem]) -> FrozenCounts`
  - `same_r2_object(source: ObjectHead, destination: ObjectHead) -> bool`
- CLI stages: `prepare`, `quarantine`, `delete-confirmed`, `verify`, each dry-run by default and requiring `--apply` for mutation.

- [x] **Step 1: Write failing unit tests**

Cover deterministic keys, traversal/blank-key rejection, exact counts, confirmed-invalid/GT overlap rejection, duplicate clip rejection, destination HEAD mismatch, idempotent already-moved behavior, and fail-closed partial copy.

- [x] **Step 2: Run RED**

```bash
uv run pytest tests/test_rba_owner_media_cleanup.py -q
```

Expected: FAIL because the module does not exist.

- [x] **Step 3: Implement pure core and adapter boundaries**

The manifest must store clip IDs and R2 keys only in the private artifact. Public reports contain counts, KST ranges, pseudonymous camera strata, aggregate bytes, state counts, and SHA-256 of the private manifest.

- [x] **Step 4: Implement mutation stages**

`quarantine --apply` moves every source object that exists and records absent sources as `source_missing`; in this run it moved 944 videos and every available thumbnail to
`research-quarantine/rba-owner-cleanup-v1/`. `delete-confirmed --apply` must move the 46 to
`research-excluded/rba-owner-cleanup-v1/`, delete both the video and non-null thumbnail object, confirm
source/destination absence, then complete the DB media-deleted transition. DB CAS updates both key columns.

- [x] **Step 5: Run GREEN**

```bash
uv run pytest tests/test_rba_owner_media_cleanup.py -q
```

Expected: all tests pass.

---

### Task 4: Production preflight, migration, quarantine, and confirmed deletion

**Files:**
- Read: private manifest from Task 3
- Create: `reports/rba-owner-media-cleanup-v1/PREFLIGHT.md`
- Create: `reports/rba-owner-media-cleanup-v1/RESULT.md`

**Interfaces:**
- Consumes: frozen private manifest digest and production credentials on Mac mini.
- Produces: aggregate public report, production cleanup cohort, exclusion ledger, R2 quarantine/deletion evidence.

- [x] **Step 1: Run production read-only prepare twice**

```bash
PYTHONPATH=. uv run python scripts/rba_owner_media_cleanup.py prepare
PYTHONPATH=. uv run python scripts/rba_owner_media_cleanup.py prepare
```

Result: byte-identical private manifest digest; exact 951/46/1/904; source HEAD 944/951, with all 7 absent sources confined to Owner-review-pending rows.

- [x] **Step 2: Apply the migration and verify database contracts**

Apply only `2026-08-03_rba_owner_media_cleanup_v1.sql`, then query counts/constraints/RLS/RPC grants without printing IDs, keys, GT, or credentials.

- [x] **Step 3: Create DB cleanup cohort and quarantine 951 objects**

Run `quarantine --apply`. After each object, persist move completion before proceeding. The run completed with 898 retained clips quarantined, 46 confirmed-invalid clips advanced to deletion, and 7 pre-existing absent sources recorded as `source_missing`; original source keys remaining = 0.

- [x] **Step 4: Delete the confirmed 46**

Run `delete-confirmed --apply`. Deletion authority must come exclusively from immutable Owner eligibility decisions. Verify R2 video/thumbnail absence and DB `media_deleted=46`.

- [x] **Step 5: Verify production invariants**

Expected aggregate state:

```text
cleanup items = 951
media_deleted = 46
protected_gt = 1
owner_review_pending = 904
reviewable now = 897
source_missing = 7
confirmed invalid overlapping canonical GT = 0
production motion_clips rows deleted = 0
boundary/behavior GT rows changed = 0
```

Also verify capture service still loaded, new clips continue arriving outside the cleanup scope, and signed URLs fail closed for quarantined/deleted samples.

---

### Task 5: Owner video cleanup queue

**Files:**
- Create: `web/src/lib/rbaOwnerMediaCleanup.ts`
- Create: `web/src/lib/rbaOwnerMediaCleanup.test.ts`
- Create: `web/src/app/api/labeling-v3/owner-media-cleanup/route.ts`
- Create: `web/src/app/api/labeling-v3/owner-media-cleanup/route.test.ts`
- Create: `web/src/app/api/labeling-v3/owner-media-cleanup/[clipId]/decision/route.ts`
- Create: `web/src/app/api/labeling-v3/owner-media-cleanup/[clipId]/decision/route.test.ts`
- Create: `web/src/app/api/labeling-v3/owner-media-cleanup/[clipId]/file/url/route.ts`
- Create: `web/src/app/api/labeling-v3/owner-media-cleanup/[clipId]/file/url/route.test.ts`
- Create: `web/src/app/labeling/motion/cleanup/page.tsx`
- Create: `web/src/app/labeling/motion/cleanup/_owner-media-cleanup-view.tsx`
- Create: `web/src/app/labeling/motion/cleanup/_owner-media-cleanup-view.test.tsx`
- Create: `migrations/2026-08-03_rba_owner_media_cleanup_v1_ui_contract.sql`
- Modify: labeling navigation component discovered by `rg -n "auto-excluded|이어짐 확인" web/src/app/labeling web/src/components`

**Interfaces:**
- Consumes: allowlisted list/decision RPCs from Task 2 and an Owner-only signed URL route that still blocks deleted objects.
- Produces: four decisions `keep`, `delete_gecko_absent`, `delete_no_activity`, `uncertain`.

- [x] **Step 1: Write RED tests for parsing, access, and experience flow**

The UI must autoplay one video, keep decision buttons in visually distinct groups, preserve the shared seek/download controls, and never expose raw R2 keys/GT/reviewer UUIDs. Canonical-GT rows are not emitted by the review projection.

- [x] **Step 2: Run RED**

```bash
cd web && npm test -- --run src/lib/rbaOwnerMediaCleanup.test.ts \
  src/app/api/labeling-v3/owner-media-cleanup/route.test.ts \
  'src/app/api/labeling-v3/owner-media-cleanup/[clipId]/decision/route.test.ts' \
  src/app/labeling/motion/cleanup/_owner-media-cleanup-view.test.tsx
```

Expected: FAIL because the files do not exist.

- [x] **Step 3: Implement minimal API and UI**

Owner `keep` and delete decisions only write immutable decision state. A Mac mini runner performs R2 moves/deletes; Vercel never performs bulk destructive R2 operations.

- [x] **Step 4: Run GREEN, TypeScript, and build**

```bash
cd web && npm test -- --run src/lib/rbaOwnerMediaCleanup.test.ts \
  src/app/api/labeling-v3/owner-media-cleanup/route.test.ts \
  'src/app/api/labeling-v3/owner-media-cleanup/[clipId]/decision/route.test.ts' \
  src/app/labeling/motion/cleanup/_owner-media-cleanup-view.test.tsx
npx tsc --noEmit
npm run build
```

Expected: targeted tests, TypeScript, and production build pass.

---

### Task 6: Hand off to Dataset v2

**Files:**
- Create: `docs/superpowers/plans/2026-08-03-rba-dataset-v2.md`
- Modify: `specs/next-session.md`

**Interfaces:**
- Consumes: cleanup eligible view/RPC and legacy dataset-203 frozen digest.
- Produces: separate Dataset v2 implementation plan; no model prediction fields in the dataset manifest.

- [x] **Step 1: Freeze cleanup eligibility as Dataset v2 input boundary**

Dataset v2 may consume only `keep` or normal eligible clips; pending/uncertain/deleted/quarantined clips are forbidden.

- [x] **Step 2: Write the separate Dataset v2 plan**

It must cover legacy 197 preservation, recent Owner-final GT selection, multi-action/segment GT schema, camera-night split leakage tests, prediction ledger separation, and future holdout isolation.

- [x] **Step 3: Final verification**

```bash
git diff --check
uv run pytest tests/test_rba_owner_media_cleanup_migration.py \
  tests/test_rba_owner_media_cleanup.py -q
cd web && npx tsc --noEmit
```

Expected: all selected checks pass. Report exact Git status and do not claim commit/deploy unless each actually occurred.

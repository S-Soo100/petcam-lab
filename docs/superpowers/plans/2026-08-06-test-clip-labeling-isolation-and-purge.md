# Test Clip Labeling Isolation and Exact Purge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 펌웨어 개발용 `test/` 영상이 운영 라벨링·GT·연구 화면에 다시 들어오지 않게 막고, 이미 제출된 test 영상 4개만 감사 가능한 절차로 완전 삭제한다.

**Architecture:** `terra-server`가 소유하는 `motion_clips.clip_purpose`를 촬영 목적 정본으로 사용하고, petcam-lab은 `production + terra-clips/clips/ + 비격리 + 미디어 존재` 조건을 운영 라벨링 자격으로 강제한다. 브라우저 미디어 API와 DB slot/queue/library RPC를 함께 fail-closed로 닫는다. 기존 test slot 정리와 4개 purge는 별도 exact-target 절차로 분리하며 prefix/bulk delete를 금지한다.

**Tech Stack:** PostgreSQL/Supabase migration, Next.js 14 route handlers, TypeScript, Vitest, Python 3.12, pytest, Cloudflare R2 boto3 client

## Global Constraints

- `motion_clips` 컬럼·CHECK·백필 migration은 terra-server 소유다. petcam-lab migration은 컬럼 존재를 전제로 consumer guard만 설치한다.
- 현재 terra-server writer는 전부 `test/`이며 production writer는 펌웨어 운영 승격 전까지 만들지 않는다.
- `clip_purpose` 기본값을 두지 않는다. writer가 검증된 prefix에서 목적을 결정한다.
- 운영 라벨링 자격은 `clip_purpose='production'`, `r2_key LIKE 'terra-clips/clips/%'`, terminal exclusion 없음이다.
- `test/`, `research-quarantine/`, `research-excluded/`, `deleted/`는 운영 라벨링·GT·연구 미디어 서명 대상이 아니다.
- purge는 blind 제출이 존재하는 distinct test clip 정확히 4개만 허용한다. prefix/bulk delete를 금지한다.
- 비밀값·원문 GT·원문 clip/R2 key를 로그·문서·커밋에 남기지 않는다.
- 현재 worktree의 기존 dirty 파일은 사용자 작업이다. 되돌리거나 함께 커밋하지 않는다.
- 프로젝트 규칙에 따라 사용자 승인 전 commit/push하지 않는다.

---

### Task 1: 운영 미디어 자격 순수 규칙과 API 차단

**Files:**
- Create: `web/src/lib/motionClipPurpose.ts`
- Create: `web/src/lib/motionClipPurpose.test.ts`
- Modify: `web/src/app/api/labeling-v3/_access.ts`
- Modify: `web/src/app/api/labeling-v3/blind/_access.ts`
- Modify: `web/src/app/api/labeling-v3/library/[clipId]/file/url/route.ts`
- Modify tests beside each route/access module

**Interfaces:**
- Consumes: `clip_purpose`, `r2_key` from `motion_clips`
- Produces: `isProductionLabelingMedia(purpose, r2Key): boolean`

- [ ] **Step 1: Write failing tests**

```ts
expect(isProductionLabelingMedia('production', 'terra-clips/clips/x.mp4')).toBe(true);
expect(isProductionLabelingMedia('test', 'test/x.mp4')).toBe(false);
expect(isProductionLabelingMedia('production', 'research-quarantine/x.mp4')).toBe(false);
expect(isProductionLabelingMedia(null, 'terra-clips/clips/x.mp4')).toBe(false);
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd web && npm test -- --run src/lib/motionClipPurpose.test.ts`
Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the minimal predicate**

```ts
export function isProductionLabelingMedia(purpose: unknown, r2Key: unknown): boolean {
  return purpose === 'production'
    && typeof r2Key === 'string'
    && r2Key.startsWith('terra-clips/clips/');
}
```

- [ ] **Step 4: Add `clip_purpose` to access queries and fail-closed before signing or writing**

Access helpers return 404 for non-eligible clips; media URL routes return `410 media_not_eligible` without calling the signer.

- [ ] **Step 5: Run focused web tests**

Run: `cd web && npm test -- --run src/lib/motionClipPurpose.test.ts 'src/app/api/labeling-v3/[clipId]/file/url/route.test.ts' 'src/app/api/labeling-v3/blind/[clipId]/file/url/route.test.ts' 'src/app/api/labeling-v3/library/[clipId]/file/url/route.test.ts' 'src/app/api/labeling-v3/blind/_access.test.ts'`
Expected: all pass and test/quarantine rows never reach `presignGet`.

### Task 2: DB slot·queue·library production guard

**Files:**
- Create: `migrations/2026-08-06_motion_clip_purpose_labeling_guard.sql`
- Create: `tests/test_motion_clip_purpose_labeling_guard_migration.py`

**Interfaces:**
- Consumes: terra-server-owned `public.motion_clips.clip_purpose`
- Produces: `public.fn_is_motion_clip_production_labeling_eligible(uuid)` and guarded replacements of active slot/queue/library RPCs

- [ ] **Step 1: Write migration contract tests first**

The test must assert:

```python
assert "clip_purpose = 'production'" in sql
assert "terra-clips/clips/%" in sql
assert "fn_ensure_motion_review_slots" in sql
assert "fn_list_motion_blind_queue" in sql
assert "fn_list_motion_clip_labeling_queue" in sql
assert "fn_list_motion_labeling_library" in sql
assert "NOT LIKE 'test/%'" not in sql
```

- [ ] **Step 2: Run pytest and verify RED**

Run: `uv run pytest -q tests/test_motion_clip_purpose_labeling_guard_migration.py`
Expected: FAIL because the migration does not exist.

- [ ] **Step 3: Add fail-closed prerequisite and eligibility helper**

The migration must abort if `clip_purpose` is absent, then define the eligibility helper with explicit canonical prefix and terminal-exclusion checks.

- [ ] **Step 4: Replace active RPCs with the helper predicate**

Every candidate source and read source must require the helper. Existing applied migrations remain unchanged.

- [ ] **Step 5: Verify static contract and local PostgreSQL probe where available**

Run: `uv run pytest -q tests/test_motion_clip_purpose_labeling_guard_migration.py`
Expected: pass. If local PostgreSQL is available, apply prerequisites + migration and show test clips are absent while production canonical clips remain.

### Task 3: Existing test slot cleanup

**Files:**
- Create: `migrations/2026-08-06_test_clip_review_cleanup.sql`
- Create: `tests/test_test_clip_review_cleanup_migration.py`

**Interfaces:**
- Consumes: test clips and review tables
- Produces: deletion of unsubmitted test slots/awaiting consensus only; submitted 4 remain for Task 4 exact purge

- [ ] **Step 1: Write failing contract tests**

Assert exact test-purpose predicate, unsubmitted-only deletion, expected-count assertions, and absence of prefix/bulk R2 operations.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/test_test_clip_review_cleanup_migration.py`
Expected: FAIL because migration does not exist.

- [ ] **Step 3: Implement guarded cleanup transaction**

The migration must lock targets, assert the observed 392 slots/196 clips envelope has not expanded unexpectedly, remove only unsubmitted test review material, and leave the four submitted clips untouched for exact purge.

- [ ] **Step 4: Verify idempotency and zero open test slots**

Run the static test and a read-only production preflight. Apply only after Task 2 is deployed so workspace access cannot recreate test slots.

### Task 4: Submitted test clip 4개 exact purge

**Files:**
- Create: `scripts/purge_submitted_test_motion_clips.py`
- Create: `tests/test_purge_submitted_test_motion_clips.py`
- Create: `migrations/2026-08-06_submitted_test_clip_exact_purge.sql`
- Create: `tests/test_submitted_test_clip_exact_purge_migration.py`
- Create: `reports/test-clip-purge-20260806/README.md`

**Interfaces:**
- Consumes: exact set computed by `clip_purpose='test'` plus existing blind submission; expected distinct count exactly 4
- Produces: R2 exact-object deletion and a narrow DB purge of only those four clips and known dependencies

- [ ] **Step 1: Write failing script tests**

Tests require dry-run default, expected count 4, refusal on any target drift, no prefix delete API, and redacted output.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/test_purge_submitted_test_motion_clips.py tests/test_submitted_test_clip_exact_purge_migration.py`
Expected: FAIL because implementation files do not exist.

- [ ] **Step 3: Implement two-phase exact purge**

Phase A deletes only each target's MP4/thumbnail/GME artifacts by exact key and verifies absence. Phase B applies the narrow DB migration that asserts the same four-target set and deletes dependencies in FK-safe order, temporarily removing/recreating only the known append-only blockers inside one transaction.

- [ ] **Step 4: Run dry-run and compare dependency counts**

Expected preflight: slots 8, submissions 4, consensus 4, gme_jobs 4, gme_runs 4, clip_favorites/behavior_logs/behavior_labels/camera_clips mirror 0.

- [ ] **Step 5: Apply and post-verify**

Only after dry-run matches exactly: execute R2 exact deletion, DB transaction, and verify all target/dependency/object counts are zero. The remaining 651 test clips stay preserved and excluded.

### Task 5: Verification and handoff

**Files:**
- Modify: `specs/next-session.md`
- Modify: `docs/DATABASE.md`

- [ ] **Step 1: Run focused Python and web suites**

Run the new pytest files plus all affected existing migration tests and affected Vitest route/access tests.

- [ ] **Step 2: Run web typecheck/build**

Run: `cd web && npx tsc --noEmit && npm run build`
Expected: exit 0.

- [ ] **Step 3: Verify production state**

Confirm zero test slots in queue/workspace, test media URL returns fail-closed, production canonical sample remains playable, and exact four/dependencies/R2 objects are absent.

- [ ] **Step 4: Record terra-server provenance**

Record its feature branch/commit, migration outcome, writer tests, and the explicit statement that production writer remains unimplemented until firmware promotion.

- [ ] **Step 5: Stop before commit/push unless the user separately approves it**

Report tracked/untracked status and exact verification evidence without staging unrelated existing changes.

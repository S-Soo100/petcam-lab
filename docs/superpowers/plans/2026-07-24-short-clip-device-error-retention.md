# Short Clip Device Error Retention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 모든 카메라의 15초 미만 clip을 저비용 후보로 감사하되, 검증된 P4 Cam 2(dev) 표시 4초·11초 패턴만 자동 격리하고 7일 복구 기간 뒤 안전한 R2 객체만 삭제한다.

**Architecture:** `petcam-lab`의 service-role 전용 DB RPC가 정책·격리 원장·복구·삭제 lease의 정본이며, 라벨링 웹은 Owner에게만 자동 제외 목록과 복구 UI를 제공한다. Mac mini의 `petcam-nightly-reporter` worker는 영상 다운로드 없이 metadata를 판정하고, DB가 발급한 삭제 lease가 있을 때만 R2 객체를 삭제한다. 감지·격리와 삭제는 독립 switch로 분리하고 Phase A shadow → Phase B P4 Cam 2 canary → Phase C 최대 30건 삭제 canary 순으로 진행한다.

**Tech Stack:** PostgreSQL 15/Supabase, Python 3.12, pytest, Next.js 14/TypeScript/Vitest, boto3 R2, Slack webhook, macOS LaunchAgent

## Global Constraints

- Design SOT: `/Users/baek/petcam-lab/docs/superpowers/specs/2026-07-24-short-clip-device-error-retention-design.md`
- 최초 후보 조건은 `duration_sec < 15`; 이것만으로 자동 제외하지 않는다.
- 최초 자동 제외 정책은 DB에서 이름으로 찾은 P4 Cam 2(dev)의 UUID와 `round(duration_sec) IN (4, 11)`뿐이다.
- rule version은 `short-device-error-v1`, retention은 정확히 `168 hours`다.
- 정상 행동 오격리 1건이면 정책을 즉시 disable하고 delete switch를 켜지 않는다.
- capture INSERT 경로에 감지 trigger를 추가하지 않는다. worker 장애는 capture를 막지 않아야 한다.
- 감지 worker는 R2 GET, 영상 디코드, Gate, VLM, Python Evidence를 호출하지 않는다.
- 삭제 worker는 DB가 claim한 exact `r2_key`만 삭제한다. prefix/bucket bulk delete는 금지한다.
- `motion_clips`, 사람 GT, blind submission/consensus, VLM/Python Evidence result row는 삭제·수정하지 않는다.
- 기존 queued Python Evidence job은 삭제하지 않고 claim 단계에서 격리 clip을 건너뛴다.
- `motion_clips.r2_key`는 감사 provenance로 보존하며, 읽기 RPC/API가 `media_deleted`를 재생 불가로 해석한다.
- 시스템 자동 판정은 Owner UUID를 `decided_by`로 위조하지 않는다.
- 테이블·RPC는 RLS ON, client policy 0, anon/authenticated REVOKE, service_role 전용이다.
- production DB apply, main merge, Mac mini LaunchAgent 설치, R2 delete enable은 각각 별도 승인 게이트다.
- 다른 세션의 primary checkout과 untracked 파일을 수정·삭제·commit하지 않는다.

---

### Task 1: DB policy, exclusion ledger, and append-only audit

**Files:**
- Create: `/Users/baek/petcam-lab/migrations/2026-07-24_short_clip_device_error_retention.sql`
- Create: `/Users/baek/petcam-lab/tests/test_short_clip_device_error_retention_migration.py`
- Create: `/Users/baek/petcam-lab/tests/sql/short_clip_device_error_retention_probe.sql`

**Interfaces:**
- Produces table: `public.camera_short_clip_policies`
- Produces table: `public.motion_clip_system_exclusions`
- Produces table: `public.motion_clip_system_exclusion_events`
- Produces table: `public.short_clip_retention_notifications`
- Produces RPC: `fn_list_short_clip_detection_candidates(double precision,timestamptz,uuid,integer)`
- Produces RPC: `fn_record_short_clip_detection(uuid,timestamptz,boolean)`
- Produces RPC: `fn_restore_short_clip_exclusion(uuid,uuid,text,timestamptz)`
- Produces RPC: `fn_claim_short_clip_media_deletions(integer,text,timestamptz)`
- Produces RPC: `fn_complete_short_clip_media_delete(uuid,uuid,text,timestamptz)`
- Produces RPC: `fn_fail_short_clip_media_delete(uuid,uuid,text,timestamptz)`
- Produces RPC: `fn_list_short_clip_system_exclusions(timestamptz,uuid,integer)`
- Produces RPC: `fn_claim_short_clip_retention_notification(date,text,timestamptz)`
- Produces RPC: `fn_complete_short_clip_retention_notification(date,uuid,timestamptz)`
- Produces RPC: `fn_release_short_clip_retention_notification(date,uuid)`

- [ ] **Step 1: Write RED static contract tests**

Create tests that assert the migration contains the four tables, closed state checks, 168-hour policy field, append-only UPDATE/DELETE/TRUNCATE blocker, service-role-only grants, fixed `search_path`, lease validation, durable daily Slack claim, and no `DELETE FROM motion_clips`.

```python
def test_exclusion_state_machine_is_closed(sql_lower: str):
    assert (
        "state in ('candidate','quarantined','restored',"
        "'media_deleted','deletion_blocked')"
    ) in sql_lower


def test_delete_rpc_never_deletes_metadata(sql_lower: str):
    assert "delete from public.motion_clips" not in sql_lower
    assert "delete from public.motion_clip_labeling_sessions" not in sql_lower
    assert "delete from public.motion_clip_review_slots" not in sql_lower


def test_audit_is_append_only(sql_lower: str):
    assert "before update or delete on public.motion_clip_system_exclusion_events" in sql_lower
    assert "before truncate on public.motion_clip_system_exclusion_events" in sql_lower
    assert "errcode = '0a000'" in sql_lower
```

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
cd /Users/baek/petcam-lab
uv run pytest -q tests/test_short_clip_device_error_retention_migration.py
```

Expected: FAIL because the migration does not exist.

- [ ] **Step 3: Implement the three tables**

Use forward-only DDL with these exact invariants:

```sql
CREATE FUNCTION public.fn_valid_short_clip_seconds(
  p_candidate_under_sec double precision,
  p_seconds integer[]
) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE
SET search_path = ''
AS $$
  SELECT p_candidate_under_sec > 0
    AND COALESCE(bool_and(s >= 0 AND s < p_candidate_under_sec), true)
  FROM unnest(p_seconds) AS values_(s);
$$;

CREATE TABLE public.camera_short_clip_policies (
  camera_id uuid PRIMARY KEY REFERENCES public.cameras(id) ON DELETE RESTRICT,
  candidate_under_sec double precision NOT NULL CHECK (candidate_under_sec > 0),
  auto_exclude_display_seconds integer[] NOT NULL DEFAULT '{}',
  retention_hours integer NOT NULL DEFAULT 168 CHECK (retention_hours BETWEEN 24 AND 720),
  rule_version text NOT NULL CHECK (char_length(rule_version) BETWEEN 1 AND 100),
  enabled boolean NOT NULL DEFAULT false,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_by uuid NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (public.fn_valid_short_clip_seconds(
    candidate_under_sec, auto_exclude_display_seconds
  ))
);

CREATE TABLE public.motion_clip_system_exclusions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL UNIQUE REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  camera_id uuid NOT NULL REFERENCES public.cameras(id) ON DELETE RESTRICT,
  state text NOT NULL CHECK (
    state IN ('candidate','quarantined','restored','media_deleted','deletion_blocked')
  ),
  reason_code text NOT NULL CHECK (reason_code = 'short_device_error'),
  rule_version text NOT NULL,
  observed_duration_sec double precision NOT NULL CHECK (observed_duration_sec >= 0),
  displayed_duration_sec integer NOT NULL CHECK (displayed_duration_sec >= 0),
  detected_at timestamptz NOT NULL,
  quarantined_at timestamptz,
  delete_after timestamptz,
  restored_at timestamptz,
  restored_by uuid,
  restore_reason text,
  media_deleted_at timestamptz,
  delete_lease_token uuid,
  delete_lease_expires_at timestamptz,
  delete_worker_host text,
  delete_result_code text,
  delete_result_fingerprint text,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (
    state NOT IN ('quarantined','media_deleted')
    OR (quarantined_at IS NOT NULL AND delete_after IS NOT NULL)
  ),
  CHECK (
    state <> 'media_deleted' OR media_deleted_at IS NOT NULL
  )
);

CREATE TABLE public.motion_clip_system_exclusion_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  exclusion_id uuid NOT NULL REFERENCES public.motion_clip_system_exclusions(id) ON DELETE RESTRICT,
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  event_type text NOT NULL CHECK (
    event_type IN (
      'candidate_detected','auto_quarantined','owner_restored',
      'delete_claimed','delete_completed','delete_failed','delete_blocked'
    )
  ),
  actor_id uuid,
  worker_host text,
  rule_version text NOT NULL,
  reason_code text NOT NULL,
  before_state jsonb,
  after_state jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE public.short_clip_retention_notifications (
  summary_date_kst date PRIMARY KEY,
  claimed_at timestamptz NOT NULL,
  claim_token uuid NOT NULL,
  sent_at timestamptz,
  worker_host text NOT NULL CHECK (btrim(worker_host) <> '')
);
```

Test the helper with negative, exact-boundary, empty, and valid arrays. Revoke its EXECUTE from PUBLIC/anon/authenticated and grant it only to service_role.

- [ ] **Step 4: Implement DB-authoritative detection and restore**

`fn_list_short_clip_detection_candidates` returns `duration_sec < p_candidate_under_sec` rows in stable `(started_at,id)` order. It includes clips with no exclusion row and `candidate` rows that can be upgraded by a newly enabled policy; it excludes `restored` for the same rule and terminal `media_deleted`. Cursor values must be both null or both present, and `p_limit` is clamped 1..200.

`fn_record_short_clip_detection` must lock `motion_clips` then the exclusion row. It derives camera, duration, displayed duration, and current policy from DB rather than trusting caller-supplied identity. It calculates `round(duration_sec)` and refuses quarantine when any human/research attachment exists.

The protected attachment predicate is:

```sql
EXISTS (SELECT 1 FROM public.motion_clip_labeling_sessions WHERE clip_id = p_clip_id)
OR EXISTS (SELECT 1 FROM public.motion_clip_review_slots WHERE clip_id = p_clip_id)
OR EXISTS (SELECT 1 FROM public.motion_clip_blind_submissions WHERE clip_id = p_clip_id)
OR EXISTS (SELECT 1 FROM public.motion_clip_consensus WHERE clip_id = p_clip_id)
OR EXISTS (
  SELECT 1 FROM public.motion_clip_labeling_triage
  WHERE clip_id = p_clip_id AND owner_decision = 'label'
)
OR EXISTS (SELECT 1 FROM public.behavior_labels WHERE clip_id = p_clip_id)
OR EXISTS (SELECT 1 FROM public.behavior_logs WHERE clip_id = p_clip_id)
```

`p_write=false` returns the computed route without table writes. `p_write=true` creates or updates the current row and appends exactly one transition event. A missing/disabled camera policy still records `candidate`; only an enabled matching policy can produce `quarantined`. Replays with the same state/rule are idempotent and append no duplicate event.

`fn_restore_short_clip_exclusion` accepts only `quarantined`, rejects `media_deleted` with `PT428`, and uses the common lock order `motion_clips → motion_clip_labeling_triage → motion_clip_system_exclusions`. In one transaction it:

1. inserts or updates `motion_clip_labeling_triage.owner_decision='label'` with the Owner actor/reason;
2. appends the existing `motion_clip_labeling_triage_events.owner_labeled` audit;
3. sets the system exclusion to `restored`, clears lease/deadline fields, and records actor/reason;
4. appends `motion_clip_system_exclusion_events.owner_restored`.

If the same rule sees a `restored` row again, detection returns `reused_restored` and never re-quarantines it.

- [ ] **Step 5: Implement fail-closed delete lease RPCs**

`fn_claim_short_clip_media_deletions` must:

- require `p_limit BETWEEN 1 AND 30` and nonblank host;
- select `quarantined` rows where `delete_after <= p_now`;
- lock rows with `FOR UPDATE SKIP LOCKED`;
- recheck all human/research attachments and active VLM/Python Evidence jobs;
- set `deletion_blocked` and append an event when protected;
- otherwise assign a random lease token for 15 minutes and return only `exclusion_id`, `clip_id`, `r2_key`, `lease_token`;
- never return a row with null/blank `r2_key`.

Active machine jobs are:

```sql
EXISTS (
  SELECT 1 FROM public.clip_vlm_jobs
  WHERE clip_id = e.clip_id
    AND status IN ('queued','submitted','failed_retryable')
)
OR EXISTS (
  SELECT 1 FROM public.python_evidence_jobs
  WHERE clip_id = e.clip_id
    AND status IN ('queued','processing','failed_retryable')
);
```

Before final SQL, inspect the deployed status CHECKs and substitute only actual active status literals.

`fn_complete_short_clip_media_delete` requires exact exclusion ID + lease token + unexpired lease and atomically writes `media_deleted` plus one event. `fn_fail_short_clip_media_delete` clears the lease, keeps `quarantined`, stores only allowlisted result code and SHA-256 fingerprint, and appends one event.

Add `fn_claim_short_clip_retention_notification(date,text,timestamptz)`,
`fn_complete_short_clip_retention_notification(date,uuid,timestamptz)`, and
`fn_release_short_clip_retention_notification(date,uuid)`. The daily KST date is unique. Slack failure releases the claim; success marks `sent_at`. This gives at-least-once delivery without duplicate successful daily cards.

- [ ] **Step 6: Add rollback and adversarial runtime probe**

The probe runs inside a transaction and proves:

- 4/11 matching policy → quarantine;
- 12 seconds and another camera → candidate;
- existing session/slot/submission → no quarantine;
- duplicate detection → one current row and one transition;
- restore → restored and cannot be re-quarantined by the same rule;
- media_deleted → restore rejected;
- claim limit 31/blank host rejected;
- protected row never claimed;
- wrong/expired lease cannot complete;
- event UPDATE/DELETE/TRUNCATE rejected with `0A000`;
- transaction rollback leaves zero rows.

- [ ] **Step 7: Run tests and commit**

```bash
uv run pytest -q tests/test_short_clip_device_error_retention_migration.py
uv run pytest -q tests/test_motion_clip_labeling_v3_migration.py
git diff --check
git add migrations/2026-07-24_short_clip_device_error_retention.sql \
  tests/test_short_clip_device_error_retention_migration.py \
  tests/sql/short_clip_device_error_retention_probe.sql
git commit -m "feat: 짧은 영상 장치 오류 격리·보존 DB 계약"
```

### Task 2: Consumer guards and media-deleted read semantics

**Files:**
- Add to: `/Users/baek/petcam-lab/migrations/2026-07-24_short_clip_device_error_retention.sql`
- Modify: `/Users/baek/petcam-lab/tests/test_short_clip_device_error_retention_migration.py`
- Modify: `/Users/baek/petcam-lab/tests/sql/short_clip_device_error_retention_probe.sql`

**Interfaces:**
- Replaces: `fn_list_motion_clip_labeling_queue`
- Replaces: `fn_ensure_motion_review_slots`
- Replaces: `fn_manage_motion_blind_canary`
- Replaces: `fn_claim_python_evidence_jobs`
- Replaces read functions that derive `media_ready` from `r2_key`

- [ ] **Step 1: Write RED guard tests**

Assert that:

- owner default queue and labeler queue exclude `quarantined` and `media_deleted`;
- live slot materialization excludes them;
- canary creation rejects them with `PT428`;
- Python Evidence claim excludes them without deleting queued jobs;
- library/detail returns `media_ready=false` for `media_deleted`;
- restored clips are eligible again.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
uv run pytest -q tests/test_short_clip_device_error_retention_migration.py \
  -k 'queue or slot or canary or evidence or media'
```

- [ ] **Step 3: Replace consumer functions forward-only**

Copy the full deployed function bodies into the new migration and add this predicate to eligible queries:

```sql
AND NOT EXISTS (
  SELECT 1
  FROM public.motion_clip_system_exclusions sx
  WHERE sx.clip_id = m.id
    AND sx.state IN ('quarantined','media_deleted')
)
```

For Python Evidence claims, apply the predicate to the claim candidate subquery. Do not update or delete the queued job.

For canary creation, validate every requested clip before creating any cohort/slot:

```sql
IF EXISTS (
  SELECT 1
  FROM unnest(p_clip_ids) AS requested(clip_id)
  JOIN public.motion_clip_system_exclusions sx ON sx.clip_id = requested.clip_id
  WHERE sx.state IN ('quarantined','media_deleted')
) THEN
  RAISE EXCEPTION 'system_excluded' USING ERRCODE = 'PT428';
END IF;
```

For queue/library/detail `media_ready`, use:

```sql
(m.r2_key IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM public.motion_clip_system_exclusions sx
  WHERE sx.clip_id = m.id AND sx.state = 'media_deleted'
)) AS media_ready
```

- [ ] **Step 4: Extend runtime probe**

Create one quarantined and one media-deleted fixture and prove queue/slot/claim/read behavior in the same rollback transaction. Require no changes to existing session, slot, submission, consensus, VLM result, or evidence result rows.

- [ ] **Step 5: Run tests and commit**

```bash
uv run pytest -q tests/test_short_clip_device_error_retention_migration.py
uv run pytest -q tests/test_motion_clip_labeling_v3_migration.py
git diff --check
git add migrations/2026-07-24_short_clip_device_error_retention.sql \
  tests/test_short_clip_device_error_retention_migration.py \
  tests/sql/short_clip_device_error_retention_probe.sql
git commit -m "feat: 자동 격리 영상의 신규 소비·재생 차단"
```

### Task 3: Owner-only automatic exclusion API and UI

**Files:**
- Modify: `/Users/baek/petcam-lab/web/src/lib/labelingV3.ts`
- Modify: `/Users/baek/petcam-lab/web/src/lib/labelingV3Api.ts`
- Modify: `/Users/baek/petcam-lab/web/src/lib/labelingV3Server.ts`
- Create: `/Users/baek/petcam-lab/web/src/app/api/labeling-v3/system-exclusions/route.ts`
- Create: `/Users/baek/petcam-lab/web/src/app/api/labeling-v3/system-exclusions/route.test.ts`
- Create: `/Users/baek/petcam-lab/web/src/app/api/labeling-v3/system-exclusions/[clipId]/restore/route.ts`
- Create: `/Users/baek/petcam-lab/web/src/app/api/labeling-v3/system-exclusions/[clipId]/restore/route.test.ts`
- Modify: `/Users/baek/petcam-lab/web/src/app/api/labeling-v3/[clipId]/file/url/route.ts`
- Modify: `/Users/baek/petcam-lab/web/src/app/api/labeling-v3/[clipId]/file/url/route.test.ts`
- Modify: `/Users/baek/petcam-lab/web/src/app/api/labeling-v3/blind/[clipId]/file/url/route.ts`
- Modify: `/Users/baek/petcam-lab/web/src/app/api/labeling-v3/blind/[clipId]/file/url/route.test.ts`
- Modify: `/Users/baek/petcam-lab/web/src/app/api/labeling-v3/library/[clipId]/file/url/route.ts`
- Modify: `/Users/baek/petcam-lab/web/src/app/api/labeling-v3/library/[clipId]/file/url/route.test.ts`
- Create: `/Users/baek/petcam-lab/web/src/app/labeling/motion/auto-excluded/page.tsx`
- Create: `/Users/baek/petcam-lab/web/src/app/labeling/motion/auto-excluded/_auto-excluded-list.tsx`
- Create: `/Users/baek/petcam-lab/web/src/app/labeling/motion/auto-excluded/_auto-excluded-list.test.tsx`
- Modify: `/Users/baek/petcam-lab/web/src/app/labeling/_motion-queue.tsx`

**Interfaces:**
- Produces: `SystemExclusionState`
- Produces: `MotionSystemExclusionItem`
- Produces: `getMotionSystemExclusions(cursor?)`
- Produces: `restoreMotionSystemExclusion(clipId, reason)`
- API: `GET /api/labeling-v3/system-exclusions`
- API: `POST /api/labeling-v3/system-exclusions/:clipId/restore`

- [ ] **Step 1: Write RED pure mapper and client tests**

Use this public type; do not expose raw `r2_key`, worker host, lease token, fingerprint, actor UUID, or event body:

```ts
export type SystemExclusionState =
  | 'candidate'
  | 'quarantined'
  | 'restored'
  | 'media_deleted'
  | 'deletion_blocked';

export interface MotionSystemExclusionItem {
  clip_id: string;
  camera_name: string;
  started_at: string;
  duration_sec: number;
  displayed_duration_sec: number;
  state: SystemExclusionState;
  rule_version: string;
  quarantined_at: string | null;
  delete_after: string | null;
  media_deleted_at: string | null;
  media_ready: boolean;
}
```

Test allowlist mapping and response leak absence for `r2_key`, `delete_lease_token`, `delete_worker_host`, `delete_result_fingerprint`, `owner_id`.

- [ ] **Step 2: Implement owner-only GET and restore routes**

Both routes call `requireOwner(req)` before Supabase. Non-owner returns 403 and performs zero DB calls. GET uses opaque `(detected_at,id)` keyset and clamps 1..100. Restore validates `reason` as 10..500 characters before RPC and maps `PT409/PT428` to public 409 without DB message.

Add one shared server-only query helper:

```ts
export async function isMotionMediaDeleted(clipId: string): Promise<boolean> {
  const { data, error } = await supabaseAdmin
    .from('motion_clip_system_exclusions')
    .select('state')
    .eq('clip_id', clipId)
    .maybeSingle();
  if (error) throw error;
  return data?.state === 'media_deleted';
}
```

All three signed URL routes call it after authorization and before reading/signing `r2_key`. Deleted media returns `{code:'media_deleted'}` with 410 and never calls the R2 signer. Unknown DB errors remain generalized 502.

- [ ] **Step 3: Write the owner experience test**

The render test must prove:

- title `자동 제외`;
- `장치 오류 후보`, rule version, actual/displayed duration;
- remaining retention text before deletion;
- `원본 삭제됨 · 메타데이터 보존` and disabled playback after deletion;
- `라벨 대상으로 복구` only for `quarantined`;
- successful restore removes the card from the active list without redirecting to another tab;
- 320px layout has no horizontal action row dependency (`grid-cols-1`, wrapping text).

- [ ] **Step 4: Implement the page and queue entry point**

Add an Owner-only link next to the existing `제외` tab:

```tsx
<Link href="/labeling/motion/auto-excluded">
  <SelectionChip pressed={false} tone="neutral">자동 제외</SelectionChip>
</Link>
```

The page uses one-column cards on mobile and two columns from `sm`. It does not auto-navigate after restore. Unauthorized users are redirected by the existing role shell, while the API remains the final server boundary.

- [ ] **Step 5: Run tests and commit**

```bash
cd /Users/baek/petcam-lab/web
npm test -- labelingV3Server system-exclusions _auto-excluded-list
npx tsc --noEmit
cd /Users/baek/petcam-lab
uv run pytest -q
git diff --check
git add web/src/lib/labelingV3.ts web/src/lib/labelingV3Api.ts \
  web/src/lib/labelingV3Server.ts web/src/app/api/labeling-v3/system-exclusions \
  'web/src/app/api/labeling-v3/[clipId]/file/url' \
  'web/src/app/api/labeling-v3/blind/[clipId]/file/url' \
  'web/src/app/api/labeling-v3/library/[clipId]/file/url' \
  web/src/app/labeling/motion/auto-excluded web/src/app/labeling/_motion-queue.tsx
git commit -m "feat: Owner 자동 제외 검수·복구 화면"
```

### Task 4: Nightly metadata detector and Supabase adapter

**Files:**
- Create: `/Users/baek/petcam-nightly-reporter/reporter/short_clip_retention_models.py`
- Create: `/Users/baek/petcam-nightly-reporter/reporter/short_clip_retention_store.py`
- Create: `/Users/baek/petcam-nightly-reporter/reporter/short_clip_retention_worker.py`
- Create: `/Users/baek/petcam-nightly-reporter/tests/test_short_clip_retention_store.py`
- Create: `/Users/baek/petcam-nightly-reporter/tests/test_short_clip_retention_worker.py`
- Modify: `/Users/baek/petcam-nightly-reporter/reporter/vlm_candidate_indexer.py`
- Modify: `/Users/baek/petcam-nightly-reporter/reporter/vlm_store.py`
- Modify: `/Users/baek/petcam-nightly-reporter/reporter/vlm_backfill_worker.py`
- Create: `/Users/baek/petcam-nightly-reporter/tests/test_short_clip_retention_vlm_guard.py`
- Modify: `/Users/baek/petcam-nightly-reporter/tests/test_vlm_backfill_worker.py`
- Modify: `/Users/baek/petcam-nightly-reporter/reporter/config.py`
- Modify: `/Users/baek/petcam-nightly-reporter/.env.example`

**Interfaces:**
- Produces dataclass: `ShortClipCandidate`
- Produces: `round_display_seconds(duration_sec: float) -> int`
- Produces: `list_short_clip_candidates(sb, *, cursor, limit) -> list[ShortClipCandidate]`
- Produces: `record_short_clip_detection(sb, candidate, *, write_enabled, now) -> DetectionResult`
- Produces: `load_system_excluded_clip_ids(sb, clip_ids) -> set[str]`
- Produces: `run(*, enabled=None, write_enabled=None, delete_enabled=None, ...) -> int`

- [ ] **Step 1: Write RED model and store tests**

Cover:

- 3.5→4 and 10.5→11 using JavaScript-compatible `Math.round` semantics, not Python banker rounding;
- negative/NaN/infinite durations rejected;
- RPC response list/object normalization;
- allowlisted outcomes `candidate`, `quarantined`, `protected`, `reused`;
- unknown response code and DB error raise;
- no raw DB error text in logs.

Implement JavaScript nonnegative rounding as:

```python
def round_display_seconds(duration_sec: float) -> int:
    if not math.isfinite(duration_sec) or duration_sec < 0:
        raise ValueError("invalid_duration")
    return math.floor(duration_sec + 0.5)
```

- [ ] **Step 2: Write RED worker safety tests**

Prove:

- disabled → DB/R2/Slack 0;
- expected-host mismatch → DB/R2/Slack 0 and nonzero;
- shadow mode calls list/RPC with `write_enabled=False`;
- write mode records metadata only;
- detector/Gate/VLM/download functions are absent from the runtime path;
- one bad clip is isolated but a DB-wide failure returns nonzero;
- duplicate cycle is reused;
- delete switch false never calls R2 delete;
- stats contain candidate/quarantined/protected/reused/failed only.

Write VLM RED tests proving:

- window candidates with current `quarantined|media_deleted` state are assigned hard skip reason `system_excluded`;
- regular due/recovery jobs for those clips are not returned;
- rolling backfill adds those IDs to its dedup/exclusion set;
- `candidate|restored|deletion_blocked` do not block;
- no existing `clip_vlm_jobs` row is updated or deleted.

- [ ] **Step 3: Implement metadata-only worker**

Add config:

```python
SHORT_CLIP_RETENTION_ENABLED = os.environ.get("SHORT_CLIP_RETENTION_ENABLED", "0") == "1"
SHORT_CLIP_RETENTION_WRITE_ENABLED = os.environ.get(
    "SHORT_CLIP_RETENTION_WRITE_ENABLED", "0"
) == "1"
SHORT_CLIP_RETENTION_DELETE_ENABLED = os.environ.get(
    "SHORT_CLIP_RETENTION_DELETE_ENABLED", "0"
) == "1"
SHORT_CLIP_RETENTION_EXPECTED_HOST = os.environ.get(
    "SHORT_CLIP_RETENTION_EXPECTED_HOST", ""
)
SHORT_CLIP_RETENTION_BATCH_LIMIT = min(
    max(int(os.environ.get("SHORT_CLIP_RETENTION_BATCH_LIMIT", "100")), 1), 200
)
SHORT_CLIP_RETENTION_DELETE_LIMIT = min(
    max(int(os.environ.get("SHORT_CLIP_RETENTION_DELETE_LIMIT", "30")), 1), 30
)
```

Host guard runs before lock/DB/Slack. Use a dedicated nonblocking flock. The detection loop receives metadata for observability but passes only clip UUID, timestamp, and write flag to the record RPC; DB re-derives identity and policy.

Implement `load_system_excluded_clip_ids` with bounded `in_(clip_id, chunk)` queries against `motion_clip_system_exclusions`, accepting only states `quarantined` and `media_deleted`. Apply it in `load_window_candidates`, `_open_jobs_for_selector`, and rolling backfill's `exclude_ids` before any R2/Gate/Claude work.

- [ ] **Step 4: Run tests and commit**

```bash
cd /Users/baek/petcam-nightly-reporter
uv run pytest -q tests/test_short_clip_retention_store.py \
  tests/test_short_clip_retention_worker.py
uv run python -m compileall -q reporter
git diff --check
git add reporter/short_clip_retention_models.py reporter/short_clip_retention_store.py \
  reporter/short_clip_retention_worker.py reporter/config.py .env.example \
  reporter/vlm_candidate_indexer.py reporter/vlm_store.py reporter/vlm_backfill_worker.py \
  tests/test_short_clip_retention_store.py tests/test_short_clip_retention_worker.py \
  tests/test_short_clip_retention_vlm_guard.py tests/test_vlm_backfill_worker.py
git commit -m "feat: 짧은 영상 metadata shadow 감지 worker"
```

### Task 5: Exact-object R2 deletion and Slack audit

**Files:**
- Modify: `/Users/baek/petcam-nightly-reporter/reporter/r2.py`
- Modify: `/Users/baek/petcam-nightly-reporter/reporter/short_clip_retention_store.py`
- Modify: `/Users/baek/petcam-nightly-reporter/reporter/short_clip_retention_worker.py`
- Create: `/Users/baek/petcam-nightly-reporter/reporter/short_clip_retention_summary.py`
- Modify: `/Users/baek/petcam-nightly-reporter/tests/test_short_clip_retention_worker.py`
- Create: `/Users/baek/petcam-nightly-reporter/tests/test_short_clip_retention_summary.py`

**Interfaces:**
- Produces: `delete_clip_object(r2_key: str) -> None`
- Produces: `claim_media_deletions(sb, *, limit, worker_host, now) -> list[DeletionClaim]`
- Produces: `complete_media_delete(sb, claim, *, fingerprint, now) -> None`
- Produces: `fail_media_delete(sb, claim, *, code, fingerprint, now) -> None`
- Produces: `format_short_clip_retention_summary(stats, now_kst) -> str`

- [ ] **Step 1: Write RED exact-delete tests**

The adapter test must assert one call only:

```python
client.delete_object.assert_called_once_with(
    Bucket=config.R2_BUCKET,
    Key="terra-clips/clips/exact.mp4",
)
```

Reject blank keys, keys containing `..`, leading slash, trailing slash, and keys not beginning with the established production clip prefix `terra-clips/clips/`. Never accept a prefix or list result.

- [ ] **Step 2: Write RED delete-cycle tests**

Cover:

- delete disabled → claim/R2 0;
- claim empty → Slack 0;
- exact object success → complete RPC once;
- R2 failure → fail RPC once, complete 0, next claim continues;
- complete RPC failure after R2 success → nonzero and explicit `audit_write_failed`;
- max 30 claims;
- raw key/endpoint/exception message absent from stdout, stderr, Slack;
- retry never deletes a row already marked media_deleted.

- [ ] **Step 3: Implement safe delete cycle**

For each DB claim:

1. compute `sha256(r2_key).hexdigest()` in memory;
2. call `delete_clip_object(r2_key)`;
3. call complete RPC with the lease token and fingerprint;
4. on R2 exception, call fail RPC with allowlisted code `r2_delete_failed` and a fingerprint of exception type only;
5. if complete RPC fails after R2 success, abort the cycle nonzero so audit divergence is never reported as success.

- [ ] **Step 4: Implement the daily Slack formatter**

The worker tries one durable notification claim for the current KST date after the scheduled reporting hour. It sends exactly one daily card even when all counts are zero; an extra immediate card is allowed only for `deletion_blocked > 0` or an audit divergence:

```text
🗑️ 짧은 영상 장치 오류
· 후보 34 · 자동 제외 31 · 검수 대기 3
· Owner 복구 0 · 7일 후 삭제 예정 31
· 오늘 R2 삭제 12 · 삭제 차단 1
· 실행 장비: Mac mini · 규칙 short-device-error-v1
```

Use KST. No raw key, URL, UUID, email, lease token, DB message, exception message.

On Slack success complete the notification claim. On Slack failure release it so the next hourly cycle retries without re-running detection/deletion side effects.

- [ ] **Step 5: Run tests and commit**

```bash
uv run pytest -q tests/test_short_clip_retention_store.py \
  tests/test_short_clip_retention_worker.py \
  tests/test_short_clip_retention_summary.py
uv run python -m compileall -q reporter
git diff --check
git add reporter/r2.py reporter/short_clip_retention_store.py \
  reporter/short_clip_retention_worker.py reporter/short_clip_retention_summary.py \
  tests/test_short_clip_retention_worker.py tests/test_short_clip_retention_summary.py
git commit -m "feat: 7일 보존 후 exact R2 삭제·감사"
```

### Task 6: Mac mini LaunchAgent and fail-closed installer

**Files:**
- Create: `/Users/baek/petcam-nightly-reporter/install-launchd-short-clip-retention.sh`
- Create: `/Users/baek/petcam-nightly-reporter/tests/test_install_short_clip_retention.py`

**Interfaces:**
- LaunchAgent label: `com.petcam.short-clip-retention`
- Module: `reporter.short_clip_retention_worker`
- StartInterval: `3600`

- [ ] **Step 1: Write RED installer tests**

Assert:

- installer refuses blank expected host;
- actual hostname mismatch aborts before writing/bootstrap;
- no auto-copy of current hostname into expected-host config;
- plist contains PATH, exact module, expected host, and three switches;
- defaults are `enabled=1`, `write=0`, `delete=0`;
- `plutil -lint` runs before bootstrap;
- StandardOut/Error use `/tmp/short-clip-retention-worker.log`;
- install output clearly prints all three switches.

- [ ] **Step 2: Implement the installer**

Render:

```xml
<key>StartInterval</key><integer>3600</integer>
<key>EnvironmentVariables</key><dict>
  <key>PATH</key><string>...</string>
  <key>SHORT_CLIP_RETENTION_ENABLED</key><string>1</string>
  <key>SHORT_CLIP_RETENTION_WRITE_ENABLED</key><string>0</string>
  <key>SHORT_CLIP_RETENTION_DELETE_ENABLED</key><string>0</string>
  <key>SHORT_CLIP_RETENTION_EXPECTED_HOST</key><string>...</string>
</dict>
```

Do not install on MacBook. Do not share the activity/VLM plist label.

- [ ] **Step 3: Verify and commit**

```bash
bash -n install-launchd-short-clip-retention.sh
uv run pytest -q tests/test_install_short_clip_retention.py
git diff --check
git add install-launchd-short-clip-retention.sh tests/test_install_short_clip_retention.py
git commit -m "feat: Mac mini 짧은 영상 보존 worker 설치기"
```

### Task 7: Full verification, docs, and cross-repo handoff

**Files:**
- Modify: `/Users/baek/petcam-lab/docs/DATABASE.md`
- Modify: `/Users/baek/petcam-lab/docs/FEATURES.md`
- Modify: `/Users/baek/petcam-lab/specs/next-session.md`
- Modify: `/Users/baek/petcam-lab/.claude/donts-audit.md`
- Create: `/Users/baek/petcam-lab/docs/handoff-prompts/2026-07-24-short-clip-retention-deployment.md`
- Modify: `/Users/baek/petcam-nightly-reporter/specs/next-session.md`
- Modify: `/Users/baek/petcam-nightly-reporter/.claude/donts-audit.md`

- [ ] **Step 1: Run full local verification**

```bash
cd /Users/baek/petcam-lab
uv run pytest -q
cd web && npm test && npx tsc --noEmit
cd ..
git diff --check

cd /Users/baek/petcam-nightly-reporter
uv run pytest -q
uv run python -m compileall -q reporter
bash -n install-launchd-short-clip-retention.sh
git diff --check
```

Run `npm run build` in an owner terminal if `dangerous-guard.sh` blocks in-session execution. Never claim build success from `tsc`.

- [ ] **Step 2: Static forbidden-behavior audit**

Require:

- detector/Gate/Claude imports 0 in the new worker;
- `list_objects`, prefix delete, bucket delete 0;
- `DELETE FROM motion_clips`, GT, slot, submission, consensus, VLM result, Evidence result 0;
- no client policy/grant;
- no raw secrets/media tracked;
- no MacBook LaunchAgent;
- delete switch default 0 in config, example, installer, and plist tests.

- [ ] **Step 3: Create tracked handoff manifest**

The manifest must contain:

- `execution_repo` for each repo;
- design and this plan absolute paths;
- exact 40-character commit SHA for lab and nightly;
- `implementation_host`;
- `runtime_kind=launchagent`;
- `runtime_host=baeg-endeuui-Macmini.local`;
- `runtime_label=com.petcam.short-clip-retention`;
- migration applied=false;
- production delete enabled=false.

Run:

```bash
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/petcam-lab/docs/handoff-prompts/2026-07-24-short-clip-retention-deployment.md
```

Require `HANDOFF_OK` before deployment.

- [ ] **Step 4: Commit and push feature branches**

```bash
git status --short
git diff --check
git commit -m "docs: 짧은 영상 격리·보존 배포 인계"
git push origin codex/short-clip-retention
```

Use explicit file lists. Do not add unrelated untracked files.

### Task 8: Phase A production shadow

**Runtime:** production Supabase + Mac mini; separate owner approval required.

- [ ] **Step 1: Capture read-only baseline**

Record:

- camera ID resolved by exact name `P4 Cam 2(dev)`;
- per-camera `<15s` count;
- P4 Cam 2 displayed 4/11 count and Owner skip/session counts;
- human session/slot/submission/consensus/151 frozen-set fingerprints;
- R2 object count for the 40 baseline clips;
- lab/nightly main HEAD;
- Mac mini hostname and service state.

- [ ] **Step 2: FF-only integrate and apply migration**

Merge each feature branch with `--ff-only`, push without force, apply the tracked migration, then run the SQL rollback probe. Require residue 0 and no new Supabase advisor critical/error.

- [ ] **Step 3: Insert disabled policy safely**

Resolve camera UUID inside SQL:

```sql
INSERT INTO public.camera_short_clip_policies (
  camera_id, candidate_under_sec, auto_exclude_display_seconds,
  retention_hours, rule_version, enabled, created_by, updated_by
)
SELECT id, 15, ARRAY[4,11], 168, 'short-device-error-v1', false,
       owner_id, owner_id
FROM public.cameras
WHERE name = 'P4 Cam 2(dev)';
```

Require exactly one affected row. Keep `enabled=false`.

- [ ] **Step 4: Install zero-write preview**

Install on Mac mini with write=0/delete=0. Kickstart one cycle and require:

- candidates equal independent DB query;
- quarantine writes 0;
- R2 GET/delete 0;
- VLM/Gate/Evidence calls 0;
- temp media 0;
- exit 0.

- [ ] **Step 5: Observe one natural zero-write cycle**

Do not claim Phase A verified from kickstart alone. Require natural StartInterval fire, unchanged HEAD, exit 0, and the same zero-write/zero-media behavior.

- [ ] **Step 6: Enable candidate-only shadow writes**

Keep the policy `enabled=false`, change only `SHORT_CLIP_RETENTION_WRITE_ENABLED=1`, and leave deletion off. Drain the bounded `<15s` candidate backlog. Require every written row to be `candidate`, quarantine 0, R2 calls 0, and independent per-camera counts to match.

- [ ] **Step 7: Verify candidate shadow**

Require the existing P4 Cam 2 displayed 4/11 baseline appears as 40 candidates, all other under-15 clips remain candidates, human/research fingerprints are unchanged, and daily Slack equals a direct DB aggregate. Only this gate allows Phase B.

### Task 9: Phase B P4 Cam 2 quarantine canary

**Runtime:** separate owner approval after Phase A.

- [ ] **Step 1: Enable policy and writes, keep delete off**

Set the one policy `enabled=true`; reinstall or update plist with write=1, delete=0. Process only the 40 verified 4/11-second baseline clips first.

- [ ] **Step 2: Verify the 40-clip contract**

Require:

- 40/40 quarantined;
- another camera quarantine 0;
- P4 Cam 2 other under-15 duration quarantine 0;
- session/slot/submission/consensus/151 frozen-set fingerprints unchanged;
- VLM/Python Evidence results unchanged;
- Owner auto-excluded page shows 40;
- R2 object exists 40/40;
- Slack numbers equal direct DB query.

- [ ] **Step 3: Owner review and one restore E2E**

Owner inspects all 40. Restore one known-safe test clip, verify immediate disappearance from auto-excluded active list and reappearance in Owner unreviewed queue, then quarantine it again only by explicit canary reset—not automatic replay. If any normal behavior is found, disable the policy and stop.

### Task 10: Phase C bounded R2 delete canary

**Runtime:** separate explicit owner approval after seven-day retention and Phase B false exclusion 0.

- [ ] **Step 1: Recompute eligibility read-only**

Require every deletion candidate has:

- quarantine age ≥168 hours;
- no Owner restore;
- no session/slot/submission/consensus/behavior/highlight;
- no active VLM/Python Evidence job;
- exact R2 object exists;
- one matching metadata row and one current exclusion row.

- [ ] **Step 2: Enable deletion for at most 30**

Set delete switch=1 and `SHORT_CLIP_RETENTION_DELETE_LIMIT=30`. Run one foreground canary on Mac mini. Do not enable unrestricted backlog drain.

- [ ] **Step 3: Verify every deleted object**

Require:

- R2 HEAD 404 for exactly the claimed 30 keys;
- unrelated R2 objects unchanged;
- `motion_clips` rows and original `r2_key` retained;
- state `media_deleted`, timestamp, fingerprint, one delete event per clip;
- web shows `원본 삭제됨 · 메타데이터 보존`;
- signed URL route refuses deleted media;
- duplicate cycle deletes 0;
- Slack equals DB;
- temp media 0 and worker exit 0.

- [ ] **Step 4: Stop and report**

Disable delete again after the canary. Expansion to hourly bounded deletion is a new owner approval. Report `SHORT_CLIP_RETENTION_DELETE_CANARY_VERIFIED` only when all assertions pass; otherwise report the specific blocked/rejected state and keep deletion off.

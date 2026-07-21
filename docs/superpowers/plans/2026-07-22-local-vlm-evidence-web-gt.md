# Local VLM Evidence GT Web Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** production Python Evidence에서 Local VLM 6-strata 후보를 SELECT-only로 검증하고, 충분할 때만 owner가 웹에서 180개 blind evidence GT를 안전하게 작성·동결하는 워크스페이스를 만든다.

**Architecture:** B0는 검수된 Local VLM hardening 기반을 main에 FF 통합한다. B1은 pure selector와 paginated SELECT-only probe로 broad pool·분포·hash를 만들고 반드시 보고 후 멈춘다. 6 strata 모두 30 episode 이상이라는 owner 승인 뒤 B2가 service-role 전용 3-table schema, owner-only API, blind UI를 preview까지 구현한다. B3 production migration·candidate freeze는 다시 별도 승인 뒤 실행하며 180/180 전에는 모델 실행을 열지 않는다.

**Tech Stack:** Python 3.12, Supabase/PostgreSQL, Next.js 14, TypeScript, Vitest, pytest, JSON/CSV/SHA-256

## Global Constraints

- 기준 설계: `/Users/baek/petcam-lab/.worktrees/local-vlm-evidence-web-gt/docs/superpowers/specs/2026-07-22-local-vlm-evidence-web-gt-design.md`
- 선행: `2026-07-22-labeling-queue-newest-order.md`가 별도 검수·통합되어야 한다.
- B1은 production SELECT only. migration·DB write·model output read·Slack·LaunchAgent 변경 금지.
- B1 종료 후 **반드시 멈춰 owner 승인을 받는다**. 한 strata라도 30 episode 미만이면 B2를 시작하지 않는다.
- B2는 코드·forward migration 작성과 preview probe까지만. production apply·seed 금지.
- B2 종료 후 **반드시 다시 멈춰 owner 승인을 받는다**.
- B3만 production migration·seed를 허용한다. model download·inference는 B3에서도 금지한다.
- Claude/local VLM prediction, reasoning, selector 결과를 사람 GT로 복사하지 않는다.
- 기존 `clip_labeling_sessions`, `behavior_labels`, activity, triage, tutorial row를 수정하지 않는다.
- Evidence GT 영상 정본은 `motion_clips`다. `camera_clips`와 ID 교집합을 가정하거나 후보를 mirror하지 않는다.
- per-clip B1 raw artifact와 media는 Git에 넣지 않는다.
- 사용자 소유 untracked/worktree 파일을 삭제·추가·커밋하지 않는다.

---

## File Structure

### B1 — SELECT-only availability

| File | Responsibility |
|---|---|
| `scripts/local_vlm_evidence_candidates.py` | series feature·episode clustering·strata pool·round-robin pure logic |
| `tests/test_local_vlm_evidence_candidates.py` | 결정론·priority·dedup·diversity tests |
| `scripts/probe_local_vlm_evidence_candidates.py` | production paginated SELECT, join, artifact/report write |
| `tests/test_probe_local_vlm_evidence_candidates.py` | 1000+ pagination·query boundary·mutation 0 |
| `experiments/local-vlm-evidence-analyst/candidate-availability.json` | aggregate-only tracked report |
| `experiments/local-vlm-evidence-analyst/CANDIDATE-AVAILABILITY.md` | human-readable verdict |
| `storage/local-vlm-evidence-analyst/candidate-pool.json` | Git-ignored per-clip artifact |

### B2/B3 — DB/API/UI

| File | Responsibility |
|---|---|
| `migrations/2026-07-22_local_vlm_evidence_gt.sql` | 3 tables, invariants, RPC, append/freeze triggers |
| `tests/test_local_vlm_evidence_gt_migration.py` | static security/invariant contract |
| `web/src/lib/localVlmEvidenceGt.ts` | enums, client-safe types, validation, display strings |
| `web/src/lib/localVlmEvidenceGt.test.ts` | GT validation·response leak keys·hash fixture |
| `web/src/lib/localVlmEvidenceGtServer.ts` | owner-safe row mappers; `server-only` |
| `web/src/lib/localVlmEvidenceGtServer.test.ts` | stratum/evidence/model non-exposure |
| `web/src/app/api/labeling-evidence/route.ts` | dashboard/status/progress |
| `web/src/app/api/labeling-evidence/[position]/route.ts` | blind detail + draft save + submit |
| `web/src/app/api/labeling-evidence/[position]/file/url/route.ts` | owner media URL |
| `web/src/app/labeling/evidence/page.tsx` | owner dashboard |
| `web/src/app/labeling/evidence/[position]/page.tsx` | blind form·draft·confirm·next |
| `web/src/app/labeling/layout.tsx` | owner-only navigation |
| `web/src/lib/labelingApi.ts` | evidence API client types/functions |

---

## Gate B0: Integrate the reviewed hardening base

### Task 0: Fast-forward Local VLM hardening to main

**Files:** none; Git integration only.

**Interfaces:**
- Lab reviewed base: `feat/local-vlm-evidence-hardening` at `fdb1ec76d693a4ff019935b53d6deb312c73d73a` or a verified descendant.
- RBA reviewed base: `feat/local-vlm-evidence-hardening` at `e846ba50ec65457d5cca795f801960a41c0041b3` or a verified descendant.

- [ ] **Step 1: Verify ancestry and clean state**

```bash
git -C /Users/baek/petcam-lab fetch origin
git -C /Users/baek/petcam-rba-worker.hardening-wt fetch origin
git -C /Users/baek/petcam-lab merge-base --is-ancestor origin/main fdb1ec76d693a4ff019935b53d6deb312c73d73a
git -C /Users/baek/petcam-rba-worker.hardening-wt merge-base --is-ancestor origin/main e846ba50ec65457d5cca795f801960a41c0041b3
```

Expected: both exit 0. If either is non-ancestor, stop `B0_BLOCKED_NON_FF`; do not merge.

- [ ] **Step 2: Re-run both reviewed baselines**

```bash
cd /Users/baek/petcam-lab.hardening-wt && uv run pytest -q
cd /Users/baek/petcam-rba-worker.hardening-wt && uv run pytest -q
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  uv run --project runtime/local-vlm --frozen --no-sync python -m pytest -q \
  tests/test_local_evidence_mlx_runtime_contract.py \
  tests/test_local_evidence_runtime_environment.py \
  tests/test_local_vlm_runtime_project.py \
  tests/test_local_evidence_isolated_wrapper.py
```

Expected: lab and rba root suites pass; isolated suite passes with model download 0.

- [ ] **Step 3: FF-only main in disposable clean worktrees**

Use new temporary worktrees from `origin/main`, then:

```bash
git merge --ff-only fdb1ec76d693a4ff019935b53d6deb312c73d73a
git push origin HEAD:main
```

for lab and:

```bash
git merge --ff-only e846ba50ec65457d5cca795f801960a41c0041b3
git push origin HEAD:main
```

for rba. Never reset the user's primary checkout. Verify `origin/main` contains both exact SHAs. Remove only the disposable worktrees created by this task.

- [ ] **Step 4: Record B0 evidence**

Append exact main HEADs and test counts to the B1 report. No empty commit.

---

## Gate B1: SELECT-only availability

### Task 1: Canonical evidence feature extraction and episode clustering

**Files:**
- Create: `scripts/local_vlm_evidence_candidates.py`
- Create: `tests/test_local_vlm_evidence_candidates.py`

**Interfaces:**

```python
STRATA = (
    "absent", "big_move", "rest_micro",
    "lick_water_food", "wheel_object", "hardcase",
)

@dataclass(frozen=True, slots=True)
class SourceRow:
    clip_id: str
    camera_id: str
    captured_at: datetime
    duration_sec: float
    run_id: str
    assessment_id: str | None
    prelabel_id: str | None
    activity_decision: str | None
    gecko_visible: bool | None
    visibility_confidence: float | None
    frames_sampled: int | None
    level0_status: str
    level1_status: str
    global_motion_series: tuple[float, ...]
    roi_motion_series: tuple[float, ...]
    excursion_count: int
    human_actions: frozenset[str]
    current_gt: Mapping[str, object] | None

@dataclass(frozen=True, slots=True)
class Candidate:
    clip_id: str
    stratum: str
    priority_score: float
    reason_codes: tuple[str, ...]
    episode_key: str
    source_run_id: str
    source_assessment_id: str | None
    selection_identity_sha256: str
```

- [ ] **Step 1: Write RED tests**

Cover these exact cases:

1. point values accept only finite `int|float >= 0`; bool/string/NaN/negative are rejected.
2. p50/p90 use deterministic nearest-rank over sorted values.
3. camera clips at 10:29 and 10:31 are one episode; 11:02 starts a new episode.
4. a clip matching `hardcase` and `big_move` is assigned only to `hardcase`.
5. three executions over shuffled source input produce identical candidate JSON bytes and SHA.
6. model output fields are not accepted by `SourceRow`.

```python
def test_episode_clustering_crosses_fixed_bucket_boundary():
    rows = [row("a", "2026-07-22T10:29:00Z"), row("b", "2026-07-22T10:31:00Z")]
    episodes = cluster_episodes(rows)
    assert episodes["a"] == episodes["b"]

def test_stratum_priority_is_single_assignment():
    candidate = classify_candidate(source(activity_decision="active", level1_status="no_bbox"), quantiles())
    assert candidate.stratum == "hardcase"
```

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/test_local_vlm_evidence_candidates.py
```

Expected: missing module failure.

- [ ] **Step 3: Implement canonical metrics**

Implement:

```python
def series_values(points: object) -> tuple[float, ...]: ...
def nearest_rank(values: Sequence[float], q: float) -> float: ...
def source_metrics(row: SourceRow) -> dict[str, float]:
    return {
        "global_p50": nearest_rank(row.global_motion_series, 0.50),
        "global_p90": nearest_rank(row.global_motion_series, 0.90),
        "roi_p50": nearest_rank(row.roi_motion_series, 0.50),
        "roi_p90": nearest_rank(row.roi_motion_series, 0.90),
        "excursion_count": float(row.excursion_count),
    }
```

Quantiles are calculated from all eligible rows with `level0_status == 'ok'`, separately for global and ROI p90.

- [ ] **Step 4: Implement exact strata rules**

Use one assignment in this priority order:

```python
if is_hardcase(row):             # unknown, no_bbox despite visible prelabel, frames<6, or GT quality tags
    stratum = "hardcase"
elif has_wheel_evidence(row):    # human current_gt wheel object/interaction only as retrieval signal
    stratum = "wheel_object"
elif has_lick_food_action(row):  # human action in frozen semantic retrieval set
    stratum = "lick_water_food"
elif is_rest_micro(row, q):      # visible and roi_p90>=q50 while global_p90<=q50, or exclude_static
    stratum = "rest_micro"
elif is_big_move(row, q):        # active and global_p90>=q75, or excursion_count>0
    stratum = "big_move"
elif is_absent_candidate(row):   # exclude_absent or gecko_visible is False
    stratum = "absent"
else:
    return None
```

Frozen semantic retrieval action set:

```python
LICK_FOOD_ACTIONS = frozenset({
    "licking", "drinking", "eating_paste", "eating_prey", "prey_capture", "hand_feeding"
})
```

Hardcase current GT tags are limited to `ir`, `occluded`, `edge`, `blur`, `reflection`, `far` after normalization. They are retrieval signals, never copied into evidence GT.

First build a deterministic sort key, not a learned score:

- hardcase: reason count desc, visibility confidence asc
- wheel/lick: human-signal count desc, captured_at desc
- rest_micro: `(roi_p90 - global_p90)` desc
- big_move: global_p90 desc, excursion count desc
- absent: explicit `exclude_absent` before detector-only absent, visibility confidence desc

Tie-break every stratum with `captured_at DESC, clip_id DESC`.

After sorting one stratum, assign the JSON-safe scalar exactly as:

```python
priority_score = 1.0 - (rank / max(len(sorted_rows) - 1, 1))
```

`rank` is zero-based. The canonical identity includes the selector version and ordered raw component names, so a
future formula change requires a new selector version.

- [ ] **Step 5: Implement 30-minute clustering, conflict priority, and identity**

Cluster per camera in time order; gap `<= 30 minutes` stays in the episode. Hash canonical selection fields with sorted-key compact JSON. Do not hash signed URLs or local paths.

- [ ] **Step 6: Run GREEN and commit**

```bash
uv run pytest -q tests/test_local_vlm_evidence_candidates.py
git add scripts/local_vlm_evidence_candidates.py tests/test_local_vlm_evidence_candidates.py
git commit -m "feat: Local VLM evidence 후보 selector 추가"
```

---

### Task 2: Paginated production SELECT and deterministic pool assembly

**Files:**
- Create: `scripts/probe_local_vlm_evidence_candidates.py`
- Create: `tests/test_probe_local_vlm_evidence_candidates.py`

**Interfaces:**
- Produces: `load_sources(client) -> list[SourceRow]`
- Produces: `build_availability(rows) -> AvailabilityResult`
- CLI: `--aggregate-out`, `--pool-out`, `--report-out`; no write flag exists.

- [ ] **Step 1: Write RED tests**

Use a fake Supabase client with 1,205 rows and assert range calls `(0,999)`, `(1000,1999)`. Assert all queries are `.select` only and no method named `insert`, `update`, `upsert`, `delete`, or `rpc` is called.

Add fixtures with multiple evidence runs per clip. Select exactly one run matching:

```text
evidence_schema_version=python-evidence-raw-v1
algorithm_version=croi-temporal-v1
level0_status=ok
```

If 0 matching runs, exclude with `missing_evidence`; if 2 runs share the same required identity, fail `AMBIGUOUS_EVIDENCE` instead of choosing latest silently.

Add a source-boundary fixture proving a `motion_clips` row with an otherwise identical ID is not loaded from
`camera_clips`, and a row with null/blank `r2_key` or non-positive duration is excluded as `not_playable`.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/test_probe_local_vlm_evidence_candidates.py
```

- [ ] **Step 3: Implement bounded column SELECTs**

Select only these columns:

- `motion_clips`: `id,camera_id,started_at,duration_sec,r2_key`; only positive duration and nonblank `r2_key`
- `clip_python_evidence_runs`: IDs, versions/statuses, three bounded series payloads, provenance identity
- `clip_activity_assessments`: `id,clip_id,prelabel_id,decision,policy_version,created_at`
- `clip_prelabels`: ID, clip ID, visible/confidence/frames/provenance
- `clip_labeling_sessions`: `clip_id,current_gt,stage,completed_at`
- `behavior_logs`: `clip_id,action,source,created_at`

Never select `camera_clips` as the clip source, prediction snapshot, VLM reasoning, `clip_vlm_jobs`, signed URL,
user email, or secrets. `r2_key` is used in memory only for eligibility and is omitted from all written artifacts.

- [ ] **Step 4: Implement broad pool and verdict**

- De-duplicate episodes globally by the design priority.
- Keep at most 60 episodes per stratum.
- Use camera/date deterministic round-robin for final 30 selection.
- Apply verdict per stratum: `DATA_AVAILABLE` ≥45, `DATA_AVAILABLE_LOW_MARGIN` 30~44, otherwise `BLOCKED_DATA_INSUFFICIENT`.
- A manifest is emitted only if every stratum has ≥30 and camera/date/diversity contracts pass.
- Split each stratum's stable SHA order into dev 20 and holdout 10.

- [ ] **Step 5: Write artifacts safely**

Tracked aggregate JSON contains counts, distribution, selector version, pool SHA, query watermark, and verdict only. Per-clip pool/manifest goes under `storage/local-vlm-evidence-analyst/` and must be gitignored. CSV contains clip ID, position, and labeling URL only for owner convenience; it excludes signed URLs and selection reasons.

- [ ] **Step 6: Run GREEN and commit code only**

```bash
uv run pytest -q tests/test_probe_local_vlm_evidence_candidates.py tests/test_local_vlm_evidence_candidates.py
git add scripts/probe_local_vlm_evidence_candidates.py tests/test_probe_local_vlm_evidence_candidates.py
git commit -m "feat: Local VLM 후보 가용성 SELECT probe 추가"
```

---

### Task 3: Live B1 audit and hard stop

**Files:**
- Create/Modify: `experiments/local-vlm-evidence-analyst/candidate-availability.json`
- Create: `experiments/local-vlm-evidence-analyst/CANDIDATE-AVAILABILITY.md`
- Create: `docs/handoff-prompts/2026-07-22-local-vlm-evidence-b1-report.md`

- [ ] **Step 1: Capture mutation baselines**

Read counts for behavior labels/logs, labeling sessions, activity assessments, VLM jobs, studies if table exists. Record snapshot time. No writes.

- [ ] **Step 2: Run the production SELECT-only probe**

```bash
uv run python scripts/probe_local_vlm_evidence_candidates.py \
  --aggregate-out experiments/local-vlm-evidence-analyst/candidate-availability.json \
  --pool-out storage/local-vlm-evidence-analyst/candidate-pool.json \
  --report-out experiments/local-vlm-evidence-analyst/CANDIDATE-AVAILABILITY.md
```

- [ ] **Step 3: Independently recompute counts**

Use a separate read-only script or direct SQL that does not import the selector summary helper. Compare per-stratum episode counts, clip duplicate count, camera/date distribution, and pool SHA. Any mismatch is `B1_REJECT_INTEGRITY`.

- [ ] **Step 4: Re-read mutation counts**

Expected: all baseline tables unchanged. Confirm no model process/download, Slack, LaunchAgent, or R2 write occurred.

- [ ] **Step 5: Write exact verdict**

Use one:

- `B1_DATA_AVAILABLE`
- `B1_DATA_AVAILABLE_LOW_MARGIN`
- `B1_BLOCKED_DATA_INSUFFICIENT`
- `B1_REJECT_INTEGRITY`
- `B1_BLOCKED_SOURCE_ERROR`

List exact counts, blockers, SHA, SELECT-only evidence, and whether an exact 180 manifest was emitted.

- [ ] **Step 6: Commit aggregate artifacts and report**

```bash
git add experiments/local-vlm-evidence-analyst/candidate-availability.json \
  experiments/local-vlm-evidence-analyst/CANDIDATE-AVAILABILITY.md \
  docs/handoff-prompts/2026-07-22-local-vlm-evidence-b1-report.md
git commit -m "docs: Local VLM evidence 후보 가용성 보고"
git push origin codex/local-vlm-evidence-web-gt
```

Confirm the per-clip pool remains untracked/ignored. **STOP HERE regardless of verdict.** Do not write migration or Web code until owner explicitly approves B2 after reviewing B1.

---

## Gate B2: Preview-only GT workspace

> Tasks 4~8 are forbidden until a new handoff manifest records owner approval after a successful B1 report.

### Task 4: Forward migration and adversarial static contract

**Files:**
- Create: `migrations/2026-07-22_local_vlm_evidence_gt.sql`
- Create: `tests/test_local_vlm_evidence_gt_migration.py`

**Interfaces:**
- Tables: `local_vlm_evidence_studies`, `local_vlm_evidence_candidates`, `local_vlm_evidence_annotations`.
- RPCs: `fn_seed_local_vlm_evidence_study`, `fn_save_local_vlm_evidence_draft`, `fn_submit_local_vlm_evidence_annotation`, `fn_complete_local_vlm_evidence_study`.

- [ ] **Step 1: Write RED static migration tests**

Assert RLS enabled, anon/authenticated revoked, service_role-only functions, `search_path=''`, freeze/submitted mutation blockers, cross-study ownership checks, 180/6×30/120:60 constraints in completion RPC, and rollback notes.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/test_local_vlm_evidence_gt_migration.py
```

- [ ] **Step 3: Write the migration**

Use exact enums from the design and model schema:

```sql
presence_observation in ('present','absent','uncertain')
visibility in ('clear','partial','poor','none','uncertain')
motion_extent in ('none','micro_local','body_translation','uncertain')
body_regions <@ array['head','body','tail','whole','unknown']
object_candidates <@ array['water_bowl','glass','wheel','branch','hide','feeding_tool','other','unknown']
```

Requirements:

- candidate FK to `motion_clips(id)` uses `ON DELETE RESTRICT`.
- draft requires optimistic integer `revision >= 1`; save RPC requires expected revision.
- submitted row requires all fields, nonempty arrays, reason length 10~500, `submitted_at`.
- mutation trigger blocks submitted UPDATE, all annotation DELETE/TRUNCATE, frozen candidate UPDATE/DELETE/TRUNCATE.
- seed RPC locks the study, validates exactly 180 unique clips/episodes, 30 each stratum, dev20/holdout10, camera/date diversity, and recomputes manifest SHA.
- complete RPC locks study/candidates/annotations and recomputes GT SHA from position-order canonical JSON.
- body-supplied owner/study status/provenance is ignored or checked against locked server rows.

- [ ] **Step 4: Run GREEN and commit**

```bash
uv run pytest -q tests/test_local_vlm_evidence_gt_migration.py
git add migrations/2026-07-22_local_vlm_evidence_gt.sql tests/test_local_vlm_evidence_gt_migration.py
git commit -m "feat: Local VLM evidence GT 원자 저장 계약 추가"
```

Do not apply the migration to production in B2.

---

### Task 5: Shared validation and owner-safe server mapping

**Files:**
- Create: `web/src/lib/localVlmEvidenceGt.ts`
- Create: `web/src/lib/localVlmEvidenceGt.test.ts`
- Create: `web/src/lib/localVlmEvidenceGtServer.ts`
- Create: `web/src/lib/localVlmEvidenceGtServer.test.ts`

**Interfaces:**

```ts
export interface EvidenceGtDraft {
  presence_observation: 'present'|'absent'|'uncertain'|null;
  visibility: 'clear'|'partial'|'poor'|'none'|'uncertain'|null;
  motion_extent: 'none'|'micro_local'|'body_translation'|'uncertain'|null;
  body_regions: BodyRegion[];
  object_candidates: ObjectCandidate[];
  human_uncertain: boolean;
  reason: string;
  revision: number;
}

export function collectEvidenceGtIssues(value: EvidenceGtDraft): EvidenceGtIssue[];
export function mapBlindEvidenceDetail(rows: ServerRows): BlindEvidenceDetail;
```

- [ ] **Step 1: Write RED tests**

Cover every enum, empty arrays, reason 9/10/500/501 characters, revision, absent normalization, and assert the serialized safe response does not contain:

```text
stratum split priority_score reason_codes source_run_id source_assessment_id
global_motion_series roi_motion_series spatial_dwell periodicity prediction reasoning action
```

- [ ] **Step 2: Implement minimal pure validation and mapper**

`localVlmEvidenceGtServer.ts` begins with `import 'server-only'`. For `presence=absent`, normalize visibility to
`none`, motion to `none`, body regions to `['unknown']`, and objects to `['unknown']`. The confirmation screen shows
these normalized values, and the submitted payload validates them exactly; no separate hidden “explicit selection”
flag is invented.

- [ ] **Step 3: Run tests and commit**

```bash
cd web
npm test -- src/lib/localVlmEvidenceGt.test.ts src/lib/localVlmEvidenceGtServer.test.ts
git add src/lib/localVlmEvidenceGt* src/lib/localVlmEvidenceGtServer*
git commit -m "feat: Local VLM blind evidence GT 검증 계약 추가"
```

---

### Task 6: Owner-only API routes

**Files:**
- Create: `web/src/app/api/labeling-evidence/route.ts` and `.test.ts`
- Create: `web/src/app/api/labeling-evidence/[position]/route.ts` and `.test.ts`
- Create: `web/src/app/api/labeling-evidence/[position]/file/url/route.ts` and `.test.ts`
- Modify: `web/src/lib/labelingApi.ts`

**Interfaces:**
- `GET /api/labeling-evidence`: study status, counts, next incomplete position, hashes only.
- `GET /api/labeling-evidence/:position`: blind clip metadata + draft/submitted answer, previous/next positions.
- `PATCH`: save draft with `expected_revision`.
- `POST`: submit complete answer with `expected_revision`.
- media URL route loads the candidate, then `motion_clips(id,r2_key)` directly and presigns that R2 object.

- [ ] **Step 1: Write RED route tests**

For every route: unauthenticated 401, non-owner 403, missing 404, DB error 502 with no raw message. Detail tests
assert forbidden keys absent. PATCH tests assert stale revision 409. POST tests assert incomplete 400 issues and
submitted modification 409. Media tests prove `camera_clips` is never queried, null `motion_clips.r2_key` returns 410,
and the JSON contains URL/TTL/type only—not `r2_key`.

- [ ] **Step 2: Implement routes using `requireOwner`**

Use URL position to load the candidate; never accept clip ID or reviewer ID from body. Select candidate provenance
internally only for authorization/invariants, then map through `mapBlindEvidenceDetail` before response. The media
route reads the linked `motion_clips` row with service-role only after the owner gate and calls existing `presignGet`;
it does not call `loadClipWithPerms` or create a `camera_clips` mirror. Log DB errors server-side only.

- [ ] **Step 3: Add typed clients**

Add `getEvidenceStudy`, `getEvidenceDetail`, `saveEvidenceDraft`, `submitEvidenceGt`, `getEvidenceFileUrl` to `labelingApi.ts`. Preserve `ApiError.code` for 409 handling.

- [ ] **Step 4: Run tests and commit**

```bash
npm test -- src/app/api/labeling-evidence src/lib/localVlmEvidenceGtServer.test.ts
npx tsc --noEmit
git add src/app/api/labeling-evidence src/lib/labelingApi.ts
git commit -m "feat: owner 전용 Evidence GT API 추가"
```

---

### Task 7: Owner dashboard and blind GT form

**Files:**
- Create: `web/src/app/labeling/evidence/page.tsx`
- Create: `web/src/app/labeling/evidence/[position]/page.tsx`
- Create: `web/src/app/labeling/evidence/_evidence-form.tsx`
- Modify: `web/src/app/labeling/layout.tsx`

**Interfaces:** uses Task 6 client methods and existing `createRequestGeneration`.

- [ ] **Step 1: Write the UX flow as test fixtures/pure state tests**

Test pure helpers for progress copy, absent normalization, confirm snapshot invalidation, and next-incomplete navigation. Do not require a new React test framework solely for this task.

- [ ] **Step 2: Implement dashboard states**

Render exactly: loading, no study, draft/frozen progress, gt_complete, retryable error. Owner-only nav link `Evidence GT`; labeler nav has no link. The API remains the actual gate.

- [ ] **Step 3: Implement the form**

Use easy Korean labels, video controls, five questions, reason, draft status, confirmation step. Hide all selection/model/evidence fields. Disable submit until video metadata loaded and issues empty. On save/submit use the confirmed snapshot and invalidate confirmation when any answer changes.

- [ ] **Step 4: Add request generation and draft recovery**

Use separate generations for detail and media. On position change invalidate both before clearing state. DB draft is canonical; sessionStorage is optional recovery and must be scoped by user+study+candidate+revision. On 409 reload DB and show conflict copy.

- [ ] **Step 5: Run focused tests/typecheck and commit**

```bash
npm test -- src/lib/localVlmEvidenceGt.test.ts src/lib/requestGeneration.test.ts
npx tsc --noEmit
git add src/app/labeling/evidence src/app/labeling/layout.tsx
git commit -m "feat: owner blind Evidence GT 화면 추가"
```

---

### Task 8: Preview migration probe, E2E, and B2 hard stop

**Files:**
- Modify: `docs/DATABASE.md`
- Modify: `docs/FEATURES.md`
- Modify: `.claude/donts-audit.md`
- Create: `docs/handoff-prompts/2026-07-22-local-vlm-evidence-b2-report.md`

- [ ] **Step 1: Apply migration to preview only**

Run a transaction rollback probe covering all design §12.2 cases. Verify residue 0. Do not apply to production. If
no isolated preview Supabase target is configured and its project identity cannot be proven distinct from production,
stop `B2_BLOCKED_PREVIEW_UNAVAILABLE`; never substitute a production apply.

- [ ] **Step 2: Seed a synthetic preview study**

Use disposable preview `motion_clips` fixtures/transaction fixtures only. Verify owner 5 drafts/submits, labeler 403,
response leak 0, submitted mutation blocked, and at least one actual signed URL plays/seeks in the browser. Confirm no
`camera_clips` mirror was created. Remove/rollback all synthetic rows.

- [ ] **Step 3: Run full suites**

```bash
cd web && npm test && npx tsc --noEmit && npm run build
cd .. && uv run pytest -q && git diff --check
```

- [ ] **Step 4: Write report and push**

Report migration filename, probe SQLSTATEs, route counts, E2E, leak audit, full test/build results, and explicitly state production migration/seed/model inference 0.

- [ ] **Step 5: Stop**

Use verdict `B2_PREVIEW_VERIFIED` or `B2_BLOCKED_<CODE>`. Push the feature branch and stop for owner/Codex review. Never proceed automatically to B3.

---

## Gate B3: Production study and human GT

> Tasks 9~10 require a third handoff manifest and explicit owner approval after `B2_PREVIEW_VERIFIED`.

### Task 9: Production migration and atomic study freeze

- Reconfirm B1 pool SHA and source identities read-only.
- Apply only `2026-07-22_local_vlm_evidence_gt.sql`.
- Run adversarial rollback probe and security advisor.
- Call seed RPC with the exact 180-row artifact; no direct INSERT/UPDATE bypass.
- Verify 180 clips/episodes, 6×30, dev120/holdout60, camera/date constraints, manifest SHA.
- Verify behavior labels/logs, labeling sessions, activity, VLM tables unchanged.
- Deploy Web and run owner/non-owner smoke.
- Stop with `B3_STUDY_FROZEN_GT_READY`; do not start model runtime.

### Task 10: Human GT completion and hash freeze

This is owner work, not agent inference.

- Owner watches every original video and submits 180 answers blind.
- Agent may report progress/counts and diagnose UI errors, but cannot fill answers.
- At 180/180 owner explicitly invokes completion; server recomputes GT SHA.
- Validate existing `validate_local_vlm_evidence_manifest.py` against canonical export.
- Only then issue a separate Mac mini runtime handoff.

---

## Final Review Checklist

- [ ] B0 is FF-only; no primary checkout reset/rebase/force push.
- [ ] B1 reads Python Evidence and activity, not model predictions.
- [ ] Evidence candidate/media paths use `motion_clips`; `camera_clips` mirror/write count stays zero.
- [ ] Episode clustering uses rolling 30-minute gaps, not fixed half-hour buckets.
- [ ] Candidate assignment is single-stratum and deterministic.
- [ ] Per-clip pool is Git-ignored; aggregate report and SHA are tracked.
- [ ] B1 stops before any migration or Web implementation.
- [ ] B2 API never returns strata/split/selection/evidence/model fields.
- [ ] Submitted GT and frozen candidates are DB-immutable.
- [ ] B2 stops before production apply/seed.
- [ ] B3 seeds only exact approved 180 rows through RPC.
- [ ] Model download/inference remains 0 through 180/180 GT completion.

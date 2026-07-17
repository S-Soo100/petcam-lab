# Python Evidence Universal Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` and `superpowers:test-driven-development` task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 모든 `motion_clips`를 durable queue에 등록하고 Mac mini가 adaptive Level 0/1 raw Python Evidence를 append-only로 생성할 수 있는 독립 worker를 구현한다.

**Architecture:** petcam-lab이 queue/run DB 계약을, gecko-vision-gate가 bounded raw temporal 계산을, petcam-nightly-reporter가 claim·R2·Gate 재사용·worker orchestration을 소유한다. 기존 activity/VLM 경로는 변경하지 않고 feature flag false를 기본으로 둔다.

**Tech Stack:** Python 3.12, PostgreSQL/Supabase, OpenCV, NumPy, pytest, uv, macOS launchd installer (작성만)

## Global Constraints

- design: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/docs/superpowers/specs/2026-07-17-python-evidence-universal-worker-design.md`
- orchestration repo: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1`
- implementation host: `BaekBook-Pro-14-M5.local`
- runtime kind: `none`; Mac mini 실행·변경 금지
- pinned bases:
  - lab manifest HEAD on `feat/python-evidence-s1-benchmark`
  - nightly `origin/main` = `19a1fe56792cf43497da8884b9c42ac8db51b5ba`
  - gate `origin/main` = `f182ea4b59c11bd9b7cf4dbb90dc2b2bc9ef022e`
- create isolated `feat/python-evidence-universal-worker` worktree/branch in each repo
- exact implementation worktrees:
  - lab: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-universal`
  - nightly: `/Users/baek/petcam-nightly-reporter/.claude/worktrees/python-evidence-universal`
  - gate: `/Users/baek/myPythonProjects/gecko-vision-gate/.claude/worktrees/python-evidence-universal`
- old `python-evidence-s2-raw-shadow` design/plan/manifest are SUPERSEDED and must not be executed
- production migration apply, main merge, LaunchAgent install, DB enqueue, Mac mini pull/run forbidden
- selector/VLM/app/GT/activity policy behavior is immutable in this plan
- orchestrator manifest is the only permitted untracked file in the source worktree

---

### Task 1: Isolated worktrees and frozen cross-repo contract

**Files:**
- Read: `petcam-lab/AGENTS.md`, `petcam-nightly-reporter/AGENTS.md`, `gecko-vision-gate/AGENTS.md`
- Create branches/worktrees only; no product code yet

- [ ] **Step 1: Verify handoff and bases**

```bash
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/docs/handoff-prompts/2026-07-17-python-evidence-universal-worker.md
git rev-parse HEAD
git -C /Users/baek/petcam-nightly-reporter rev-parse origin/main
git -C /Users/baek/myPythonProjects/gecko-vision-gate rev-parse origin/main
```

Expected: `HANDOFF_OK`; SHAs exactly equal Global Constraints. Do not use the dirty nightly feature checkout as a base.

- [ ] **Step 2: Create isolated worktrees**

Create the exact Global Constraints worktree paths. If a target branch/worktree exists, inspect and stop rather than deleting it. Record all three paths in the report.

```bash
git -C /Users/baek/petcam-lab worktree add \
  -b feat/python-evidence-universal-worker \
  /Users/baek/petcam-lab/.claude/worktrees/python-evidence-universal \
  "$(git -C /Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1 rev-parse HEAD)"
git -C /Users/baek/petcam-nightly-reporter worktree add \
  -b feat/python-evidence-universal-worker \
  /Users/baek/petcam-nightly-reporter/.claude/worktrees/python-evidence-universal \
  19a1fe56792cf43497da8884b9c42ac8db51b5ba
git -C /Users/baek/myPythonProjects/gecko-vision-gate worktree add \
  -b feat/python-evidence-universal-worker \
  /Users/baek/myPythonProjects/gecko-vision-gate/.claude/worktrees/python-evidence-universal \
  f182ea4b59c11bd9b7cf4dbb90dc2b2bc9ef022e
```

- [ ] **Step 3: Freeze shared names in a contract test**

Gate must produce:

```python
EVIDENCE_SCHEMA_VERSION = "python-evidence-raw-v1"
ALGORITHM_VERSION = "croi-temporal-v1"
POINT_CAP = 256
```

Nightly imports these constants from the installed Gate package; it must not duplicate literals.

### Task 2: Durable queue and append-only result migration

**Files:**
- Create: `petcam-lab/migrations/2026-07-17_python_evidence_universal_worker.sql`
- Modify: `petcam-lab/docs/DATABASE.md`
- Test: follow current migration/static test pattern

**Produces:**
- `python_evidence_jobs`
- `clip_python_evidence_runs`
- trigger `fn_enqueue_python_evidence_job()`
- RPCs `fn_claim_python_evidence_jobs`, `fn_complete_python_evidence_job`, `fn_fail_python_evidence_job`, `fn_insert_python_evidence_run`

- [ ] **Step 1: Write RED migration tests**

Assert exact status/source checks, one job per clip+schema+algorithm version, live priority, SKIP LOCKED claim, lease recovery, service_role-only grants, `search_path=''`, RLS policy 0, result append-only trigger and point cap 256.

Example required assertion:

```python
assert "after insert on public.motion_clips" in sql_lower
assert "for update skip locked" in sql_lower
assert "jsonb_array_length" in sql_lower
assert "truncate" in sql_lower
```

- [ ] **Step 2: Confirm RED**

```bash
cd /Users/baek/petcam-lab/.claude/worktrees/python-evidence-universal
uv run pytest -q -k 'python_evidence and migration'
```

Expected: failure because migration does not exist.

- [ ] **Step 3: Implement minimal forward-only SQL**

Required queue ordering:

```sql
ORDER BY priority DESC, created_at ASC, id ASC
FOR UPDATE SKIP LOCKED
```

Required trigger insert:

```sql
INSERT INTO public.python_evidence_jobs (
  clip_id, source, priority, evidence_schema_version, algorithm_version
)
VALUES (NEW.id, 'live', 100, 'python-evidence-raw-v1', 'croi-temporal-v1')
ON CONFLICT (clip_id, evidence_schema_version, algorithm_version) DO NOTHING;
```

Do not bulk-enqueue existing rows in the migration.

- [ ] **Step 4: Add append-only blocker**

Block `UPDATE OR DELETE` row mutations and `TRUNCATE` statement mutations with SQLSTATE `0A000`, including service_role.

- [ ] **Step 5: Add security contract**

All functions use `SECURITY INVOKER SET search_path=''`, fully-qualified table names, revoke PUBLIC/anon/authenticated, grant service_role only. Tables have RLS enabled and client policies 0.

- [ ] **Step 6: GREEN + rollback probe**

Run migration tests. If a disposable DB is available, transactionally prove trigger enqueue, duplicate no-op, claim ordering, complete/fail transitions, result duplicate idempotence and mutation blockers, then rollback and require residue 0. Never apply production migration.

- [ ] **Step 7: Commit lab migration**

```bash
git add migrations/2026-07-17_python_evidence_universal_worker.sql docs/DATABASE.md tests
git commit -m "feat: 전 영상 Python evidence queue 원장"
```

### Task 3: Gate bounded Level 0/1 temporal evidence

**Files:**
- Create: `gecko-vision-gate/src/gecko_vision_gate/temporal_evidence.py`
- Create: `gecko-vision-gate/tests/test_temporal_evidence.py`

**Produces:**

```python
@dataclass(frozen=True, slots=True)
class TemporalEvidence:
    evidence_schema_version: str
    algorithm_version: str
    level0_status: str
    level1_status: str
    decoded_frame_count: int
    point_stride: int
    global_motion_series: tuple[TemporalPoint, ...]
    roi_motion_series: tuple[TemporalPoint, ...]
    motion_summary: dict[str, float | int | None]
    spatial_dwell: dict
    periodicity_summary: dict
    motion_excursions: tuple[dict, ...]

def compute_temporal_evidence(
    video_path: str | Path,
    result: PrelabelResult | None,
    *,
    point_cap: int = POINT_CAP,
    grid_size: int = 4,
) -> TemporalEvidence: ...
```

- [ ] **Step 1: RED tests**

Cover no frames, one frame, no bbox, invalid bbox, global-only lighting change, ROI-local change, constant series, frame shape change, point cap, metadata frame-count lie, dwell unobserved time, finite values and `cap.release()` on exception.

- [ ] **Step 2: Confirm RED**

```bash
uv run pytest -q tests/test_temporal_evidence.py
```

- [ ] **Step 3: Implement sequential Level 0**

Keep only previous grayscale frames and bounded points. Never hold all decoded BGR frames. `no_bbox` still returns complete global evidence.

- [ ] **Step 4: Implement conditional Level 1**

Use union of detected gecko boxes. Do not infer a head ROI and do not substitute full frame. Store numeric autocorrelation/excursion outputs without behavior names.

- [ ] **Step 5: GREEN and full Gate suite**

```bash
uv run pytest -q tests/test_temporal_evidence.py
uv run pytest -q
```

- [ ] **Step 6: Commit/push Gate branch**

```bash
git add src/gecko_vision_gate/temporal_evidence.py tests/test_temporal_evidence.py
git commit -m "feat: 전 영상 bounded temporal evidence 코어"
git push origin feat/python-evidence-universal-worker
```

### Task 4: Nightly queue/store client

**Files:**
- Create: `petcam-nightly-reporter/reporter/python_evidence_store.py`
- Create: `petcam-nightly-reporter/tests/test_python_evidence_store.py`

**Produces:**

```python
def claim_jobs(sb, *, limit: int, worker_host: str, now: datetime) -> list[EvidenceJob]: ...
def complete_job(sb, *, job_id: str, run_id: str, worker_host: str) -> None: ...
def fail_job(sb, *, job_id: str, failure_code: str, retryable: bool,
             worker_host: str, now: datetime) -> None: ...
def insert_run(sb, *, job: EvidenceJob, temporal: TemporalEvidence,
               prelabel: dict | None, producer: ProducerInfo) -> dict: ...
```

- [ ] **Step 1: RED tests**

Test RPC names/arguments, response parsing, empty claim, duplicate existing run, allowlist failure codes and generic DB error mapping. Response/logs must not include raw Supabase errors.

- [ ] **Step 2: Implement immutable dataclasses and mapper**

Reject unknown status/source/failure code locally before RPC.

- [ ] **Step 3: GREEN/full nightly tests and commit**

```bash
uv run pytest -q tests/test_python_evidence_store.py
uv run pytest -q
git add reporter/python_evidence_store.py tests/test_python_evidence_store.py
git commit -m "feat: Python evidence queue RPC client"
```

### Task 5: Universal worker orchestration

**Files:**
- Create: `reporter/python_evidence_worker.py`
- Create: `tests/test_python_evidence_worker.py`
- Modify minimally: `reporter/config.py`, `.env.example`
- Reuse: `reporter/gate_runner.py`, `reporter/activity_store.py`, `reporter/r2.py`, `reporter/vlm_host_guard.py`

**Flow:**

```python
require_expected_host(...)              # before lock/DB/R2/model
lock = acquire_common_gate_lock()
jobs = claim_jobs(...)
if not jobs: return 0                    # detector/R2 0
for job in jobs:
    download once
    prelabel = find_current_prelabel(...)
    if prelabel is None:
        prelabel = run_sparse_gate_once(...)
    temporal = compute_temporal_evidence(path, prelabel_result)
    run = insert_run(...)
    complete_job(...)
```

- [ ] **Step 1: RED call-count tests**

Require:

- no jobs → DB claim only, R2/detector/temp 0
- existing prelabel → one download, detector 0
- missing prelabel → one download, detector once
- no bbox → Level 0 saved, Level 1 skipped, job succeeded
- R2/transient DB → retryable
- invalid deterministic media → terminal allowlist code
- one clip failure isolates later clips but cycle returns nonzero
- temp 0 and common Gate lock always released
- selector/VLM/behavior/app functions never called

- [ ] **Step 2: Implement feature flag and limits**

```python
PYTHON_EVIDENCE_ENABLED = env_bool("PYTHON_EVIDENCE_ENABLED", False)
PYTHON_EVIDENCE_BATCH_LIMIT = min(max(env_int(..., 30), 1), 200)
PYTHON_EVIDENCE_EXPECTED_HOST = os.environ.get("PYTHON_EVIDENCE_EXPECTED_HOST", "")
```

When disabled, exit before DB client creation. Do not auto-copy hostname into expected host.

- [ ] **Step 3: Share detector lock**

Use the same lock abstraction/path as activity Gate inference or extract a tiny shared module used by both. No broad activity-worker refactor. Lock loser is a clean no-op, not a failed job.

- [ ] **Step 4: Implement current-first processing**

Trust DB claim ordering. Do not load historical clips directly or scan all `motion_clips` in Python.

- [ ] **Step 5: GREEN and full nightly suite**

```bash
uv run pytest -q tests/test_python_evidence_worker.py
uv run pytest -q
```

- [ ] **Step 6: Commit worker**

```bash
git add reporter/python_evidence_worker.py reporter/config.py .env.example tests/test_python_evidence_worker.py
git commit -m "feat: 전 영상 Python evidence worker"
```

### Task 6: Bounded historical enqueuer and installer artifacts

**Files:**
- Create: `petcam-nightly-reporter/scripts/enqueue_python_evidence_backfill.py`
- Create: `tests/test_enqueue_python_evidence_backfill.py`
- Create: `install-launchd-python-evidence.sh`
- Test installer using temporary HOME/stub launchctl only

- [ ] **Step 1: RED backfill tests**

Require explicit `--start-date`, `--end-date`, `--limit`; stable date/id pagination; live job conflict no-op; no unbounded default; dry-run mutation 0.

- [ ] **Step 2: Implement bounded enqueuer**

It may only call a service-role enqueue RPC or insert jobs with `source=historical, priority=10`. It never downloads/analyzes video.

- [ ] **Step 3: RED installer tests**

Require explicit nonblank expected host, enabled flag, fixed worker module, PATH, plist lint and install output. No actual install.

- [ ] **Step 4: Implement installer artifact**

Proposed schedule is recorded for S2B only; this plan must not bootstrap it.

- [ ] **Step 5: GREEN, bash syntax and commit**

```bash
uv run pytest -q tests/test_enqueue_python_evidence_backfill.py
bash -n install-launchd-python-evidence.sh
git add scripts/enqueue_python_evidence_backfill.py tests/test_enqueue_python_evidence_backfill.py install-launchd-python-evidence.sh
git commit -m "feat: evidence backfill enqueue와 launchd 설치기"
```

### Task 7: Cross-repo safety and compatibility review

- [ ] **Step 1: Full suites**

Run Gate, nightly and lab full tests with exact counts; run `compileall`, `bash -n`, `git diff --check`.

- [ ] **Step 2: Forbidden behavior static audit**

New runtime path must have zero writes/calls to `clip_vlm_jobs`, selector, Claude/Groq/API, `behavior_labels`, labeling sessions, activity settings/view, Flutter/API.

- [ ] **Step 3: Migration adversarial review**

Verify RLS/grants/search_path, SQL injection resistance, lease ownership, stale completion rejection, terminal retry cap, trigger recursion absence and append-only service_role blocker.

- [ ] **Step 4: Compatibility review**

Prove feature disabled means no new DB table query; existing activity/VLM tests unchanged; no production config default changes.

### Task 8: SOT, report, commit and stop

**Files:**
- Create: `petcam-lab/docs/handoff-prompts/2026-07-17-python-evidence-universal-worker-report.md`
- Modify additively: hybrid design, universal design status, lab/nightly/gate next-session where required

- [ ] **Step 1: Write exact report**

Include architecture, files, DB contract, adaptive levels, call-count proof, bounded-memory proof, full test counts, three branch SHAs, push/clean status and forbidden actions.

- [ ] **Step 2: Choose one verdict**

- `UNIVERSAL_EVIDENCE_IMPLEMENTATION_READY_FOR_DEPLOY_REVIEW`
- `UNIVERSAL_EVIDENCE_HOLD_CONTRACT`
- `UNIVERSAL_EVIDENCE_HOLD_TESTS`
- `UNIVERSAL_EVIDENCE_BLOCKED_ENVIRONMENT`

- [ ] **Step 3: Commit/push all feature branches**

Require local==origin. Preserve unrelated/untracked files. The source orchestrator manifest remains the sole allowed untracked artifact.

## Stop Point

Stop after Task 8. Do not apply migration, merge main, enqueue historical clips, install/restart LaunchAgent, touch Mac mini, run a production canary, or change selector/VLM/app/GT/activity outcomes. Codex reviews the report and writes S2B deployment plan separately.

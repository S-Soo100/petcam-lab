# Python Evidence Hybrid S0 Coverage Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** production Gate evidence의 재고·현재 정책·selector 시점 coverage를 read-only로 재현 가능하게 측정하고 S1 벤치마크 범위를 판정한다.

**Architecture:** `scripts/audit_python_evidence_coverage.py` 하나를 read adapter, 순수 정규화/집계, renderer, CLI로 나누되 DB 접근은 SELECT만 허용한다. 모든 계산은 하나의 `--as-of` snapshot을 사용하고 JSON/CSV/Markdown을 원자적으로 출력한다. exact selected linkage, estimated window-time availability, not-reconstructable eligible pool을 서로 다른 필드로 유지한다.

**Tech Stack:** Python 3.12, Supabase Python client, pytest, csv/json 표준 라이브러리, `zoneinfo`

## Global Constraints

- 설계 정본: `docs/superpowers/specs/2026-07-16-python-evidence-s0-coverage-audit-design.md`
- execution repo는 `/Users/baek/petcam-lab`이고 runtime은 없다(`runtime_kind=none`).
- production DB는 SELECT만 허용한다. migration/RPC/INSERT/UPDATE/DELETE/UPSERT 금지.
- R2, detector, OpenCV, Claude/VLM, Slack, LaunchAgent 호출 금지.
- 기본 시간 범위는 `2026-07-14T00:00:00+09:00`부터 명시적 `--as-of`까지다.
- 정규 selector와 backfill selector를 합산하지 않는다.
- exact/estimate/not_reconstructable을 같은 수치로 표현하지 않는다.
- 원본 영상 식별정보는 camera name + clip/camera short id만 허용한다. owner UUID, R2 key, 비밀값, raw evidence JSON 출력 금지.
- 기존 미추적 파일과 다른 세션 작업을 stage·수정·삭제하지 않는다.

---

### Task 1: 감사 데이터 모델과 순수 coverage 계산

**Files:**
- Create: `scripts/audit_python_evidence_coverage.py`
- Create: `tests/test_audit_python_evidence_coverage.py`

**Interfaces:**
- Produces: `AuditSnapshot`, `CoverageVerdict`, `build_inventory_rows(...)`, `build_selector_rows(...)`, `evaluate_verdict(...)`
- Consumes: dictionary rows returned by Supabase SELECT

- [ ] **Step 1: Write failing tests for inventory and completeness**

테스트 fixture는 `motion_clips` 4개, duplicate identity prelabel, `activity-v1` assessment, missing metric row, absent row를 포함한다. 다음을 고정한다.

```python
def test_inventory_counts_unique_clips_and_current_policy_ready():
    result = build_inventory_rows(snapshot_fixture(), policy_version="activity-v1")
    assert result.total_eligible == 4
    assert result.any_prelabel_count == 3
    assert result.policy_ready_count == 2

def test_absent_nullable_bbox_is_core_complete():
    row = complete_prelabel(gecko_visible=False, gecko_bbox=None, best_frame_ts=None)
    assert core_evidence_issues(row) == ()

def test_missing_motion_metric_is_not_core_complete():
    row = complete_prelabel()
    del row["motion_metrics"]["roi_flow_mag"]
    assert core_evidence_issues(row) == ("motion_metrics.roi_flow_mag",)
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `cd /Users/baek/petcam-lab && uv run pytest -q tests/test_audit_python_evidence_coverage.py`

Expected: import or symbol failure because the script does not exist.

- [ ] **Step 3: Implement typed records and pure functions**

Implement frozen dataclasses for snapshot metadata and summaries. `core_evidence_issues()` must check the exact provenance/presence/motion keys from design §5.3, finite numeric values, 64-hex checkpoint, and positive frames. Use unique `clip_id` sets for coverage denominators; never count evidence rows directly as clips.

```python
MOTION_KEYS = (
    "visible_frame_count", "visible_frame_ratio", "max_bbox_center_disp",
    "max_bbox_size_change", "min_bbox_iou", "roi_flow_mag",
    "global_bg_change", "bbox_edge_clipped",
)

@dataclass(frozen=True, slots=True)
class CoverageCounts:
    total_eligible: int
    any_prelabel_count: int
    policy_ready_count: int
    core_complete_count: int
```

- [ ] **Step 4: Add KST date and multiple-identity tests**

Explicitly test `2026-07-13T15:00:00Z == 2026-07-14 00:00 KST`, duplicated prelabels count once, and identity distribution counts unique clips per identity.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `cd /Users/baek/petcam-lab && uv run pytest -q tests/test_audit_python_evidence_coverage.py`

Expected: all Task 1 tests pass.

### Task 2: Selector 시점 exact/estimate/not-reconstructable 계산

**Files:**
- Modify: `scripts/audit_python_evidence_coverage.py`
- Modify: `tests/test_audit_python_evidence_coverage.py`

**Interfaces:**
- Produces: `SelectorCoverageRow`, `classify_selector(selector_version)`, `build_selector_rows(snapshot)`
- Consumes: Task 1 snapshot rows

- [ ] **Step 1: Write selector-time RED tests**

```python
def test_selected_linkage_uses_job_foreign_keys_as_exact():
    rows = build_selector_rows(selector_fixture())
    assert rows[0].selected_jobs == 2
    assert rows[0].selected_with_prelabel == 1
    assert rows[0].selected_linkage_kind == "exact"

def test_window_time_excludes_prelabel_created_after_run():
    rows = build_selector_rows(selector_fixture(prelabel_created_after_run=True))
    assert rows[0].window_clips_with_prelabel_at_run == 0
    assert rows[0].window_time_kind == "estimate"

def test_exact_eligible_pool_is_never_claimed():
    assert build_selector_rows(selector_fixture())[0].eligible_pool_kind == "not_reconstructable"
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run the three new tests by node id. Expected: missing `build_selector_rows` or mismatched values.

- [ ] **Step 3: Implement selector classification and point-in-time join**

For each run, compute window clips using `camera_id` and half-open `[window_start, window_end)`. A prelabel is available only when `prelabel.created_at <= run.created_at`. Job linkage requires referenced rows to exist; broken `prelabel_id` or `activity_assessment_id` becomes a contract error, not a null success.

```python
def classify_selector(version: str) -> str:
    if version == "budget-router-v1":
        return "regular"
    if "backfill" in version:
        return "backfill"
    return "other"
```

- [ ] **Step 4: Add regular/backfill separation and no-run tests**

Ensure reports never aggregate regular and backfill into one selector row. An audit range with no regular run must produce warning `regular_selector_sample_missing`, not 0% coverage.

- [ ] **Step 5: Run Task 2 tests and confirm GREEN**

Run: `cd /Users/baek/petcam-lab && uv run pytest -q tests/test_audit_python_evidence_coverage.py`

Expected: all selector tests pass.

### Task 3: Paginated SELECT-only Supabase adapter

**Files:**
- Modify: `scripts/audit_python_evidence_coverage.py`
- Modify: `tests/test_audit_python_evidence_coverage.py`

**Interfaces:**
- Produces: `select_all(query_factory, order_column="id", page_size=1000)`, `load_snapshot(client, start, as_of)`
- Consumes: `backend.supabase_client.get_supabase_client`

- [ ] **Step 1: Write pagination and read-only tests**

Use a fake Supabase query that contains 1,001 ordered rows. Assert two page reads, unique IDs, stable ordering, and zero mutation method calls. Add a source scan assertion forbidding `.insert(`, `.update(`, `.delete(`, `.upsert(`, `.rpc(`.

- [ ] **Step 2: Run tests and confirm RED**

Expected: `select_all` and `load_snapshot` are absent.

- [ ] **Step 3: Implement table-specific SELECT loaders**

Load only the columns needed by the design. `motion_clips` is bounded by `started_at`; selector runs are bounded by `created_at`; related evidence/jobs may be fetched by paginated ID batches. Every page must use a stable order and explicit range. Do not select `r2_key` into report-facing models; only query a boolean-safe eligibility projection if needed.

- [ ] **Step 4: Add row-count and foreign-key integrity validation**

Fail nonzero for duplicate page IDs, missing referenced prelabels/assessments, invalid timestamps, or response errors. Return warnings only for legitimate absence such as no regular run.

- [ ] **Step 5: Run focused and full Python regression**

Run:

```bash
cd /Users/baek/petcam-lab
uv run pytest -q tests/test_audit_python_evidence_coverage.py
uv run pytest -q
```

Expected: all tests pass with no production access.

### Task 4: Atomic JSON/CSV/Markdown rendering and verdict

**Files:**
- Modify: `scripts/audit_python_evidence_coverage.py`
- Modify: `tests/test_audit_python_evidence_coverage.py`

**Interfaces:**
- Produces: `render_artifacts(snapshot, output_dir)`, CLI `main(argv=None) -> int`
- Output: `summary.json`, `camera_date_coverage.csv`, `selector_time_coverage.csv`, `identity_distribution.csv`, `REPORT.md`

- [ ] **Step 1: Write renderer and verdict RED tests**

Cover `S0_PASS`, `S0_PASS_WITH_COVERAGE_GAP`, and `S0_HOLD_DATA_CONTRACT`. Assert all output files share the same `snapshot_id`/`as_of`, selector CSV contains the three evidence-kind fields, and a failed render leaves no partial final directory.

- [ ] **Step 2: Add secret/privacy regression test**

Render fixtures containing owner UUID, R2 key, service-role-like token, and raw evidence detail. Assert none appears in any artifact. Full clip UUIDs must not appear outside internal summary checksum.

- [ ] **Step 3: Implement verdict and atomic renderer**

Write into `TemporaryDirectory(dir=output_dir.parent)` and rename only after every file and checksum validates. If the target directory already exists, fail unless `--overwrite` is passed; overwrite must replace the directory atomically without deleting unrelated paths.

- [ ] **Step 4: Implement CLI**

Required arguments and defaults:

```text
--start 2026-07-14T00:00:00+09:00
--as-of <required ISO-8601 timestamp>
--policy-version activity-v1
--regular-selector-version budget-router-v1
--output reports/python-evidence-s0-coverage-20260716
--overwrite (default false)
```

`--as-of` is required so two runs never silently claim the same snapshot while reading different live data.

- [ ] **Step 5: Run all tests**

Run: `cd /Users/baek/petcam-lab && uv run pytest -q`

Expected: all tests pass.

### Task 5: Production read-only audit and independent reconciliation

**Files:**
- Create: `reports/python-evidence-s0-coverage-20260716/summary.json`
- Create: `reports/python-evidence-s0-coverage-20260716/camera_date_coverage.csv`
- Create: `reports/python-evidence-s0-coverage-20260716/selector_time_coverage.csv`
- Create: `reports/python-evidence-s0-coverage-20260716/identity_distribution.csv`
- Create: `reports/python-evidence-s0-coverage-20260716/REPORT.md`

**Interfaces:**
- Consumes: Task 4 CLI
- Produces: frozen S0 evidence report and next-step recommendation

- [ ] **Step 1: Record pre-run read-only baselines**

Record row counts for the seven source tables and current git HEAD in a local temporary note. Do not write these values back to DB.

- [ ] **Step 2: Execute once with a frozen KST as-of**

```bash
cd /Users/baek/petcam-lab
AS_OF="$(TZ=Asia/Seoul date -Iseconds)"
uv run python scripts/audit_python_evidence_coverage.py \
  --start 2026-07-14T00:00:00+09:00 \
  --as-of "$AS_OF" \
  --policy-version activity-v1 \
  --regular-selector-version budget-router-v1 \
  --output reports/python-evidence-s0-coverage-20260716
```

Expected: exit 0 for PASS/PASS_WITH_COVERAGE_GAP; contract/query failure exits nonzero and creates no final report directory.

- [ ] **Step 3: Reconcile key totals with independent SELECT queries**

Independently verify eligible motion clip count, unique prelabel clip count, activity-v1 assessment count, regular selector run/job count, and backfill run/job count. The independent totals must match `summary.json`; otherwise mark `NOT_VERIFIED` and stop.

- [ ] **Step 4: Prove no production mutation**

Re-read the seven source table counts. Expected: any changes must be explainable only by concurrently running production workers and timestamped after `as_of`; this audit must have no producer_run_id, no new migration, and no write log. If attribution is ambiguous, report `NOT_VERIFIED`.

- [ ] **Step 5: Inspect report conclusions**

Confirm `REPORT.md` states one verdict, identifies 0%-coverage camera/date strata, separates regular/backfill, explains exact vs estimate, and says exact eligible-pool coverage is not reconstructable.

### Task 6: SOT update, final verification, commit/push, and report

**Files:**
- Modify: `docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md`
- Modify: `specs/next-session.md`
- Create: `docs/handoff-prompts/2026-07-16-python-evidence-s0-coverage-audit-report.md`

**Interfaces:**
- Consumes: verified Task 5 artifacts
- Produces: S0 closure status and explicit S1 boundary

- [ ] **Step 1: Update the hybrid SOT additively**

Replace only the §17-1 open coverage question and S0 rollout status with measured values. Preserve history. Do not mark S1 started. If verdict is `PASS_WITH_COVERAGE_GAP`, name the covered subset and forbid generalization.

- [ ] **Step 2: Write the handoff report**

The report must contain:

- audit `as_of`, production HEADs, command
- camera/date coverage table
- identity/core completeness table
- regular/backfill selector-time table
- exact/estimate/not_reconstructable explanation
- independent reconciliation evidence
- source table pre/post count evidence
- verdict and bounded S1 recommendation
- files changed, tests, commit SHA, push state
- explicit list of forbidden actions that remained unexecuted

- [ ] **Step 3: Run final verification**

```bash
cd /Users/baek/petcam-lab
uv run pytest -q
git diff --check
rg -n "TBD|TODO|NOT_VERIFIED" reports/python-evidence-s0-coverage-20260716 docs/handoff-prompts/2026-07-16-python-evidence-s0-coverage-audit-report.md
rg -n "\.insert\(|\.update\(|\.delete\(|\.upsert\(|\.rpc\(" scripts/audit_python_evidence_coverage.py
```

Expected: tests pass; whitespace clean; no placeholders; forbidden mutation scan returns no matches.

- [ ] **Step 4: Review scope before staging**

Use `git diff --stat` and `git status --short`. Stage only the audit script/test, five report artifacts, two SOT files, and final report. Preserve all pre-existing untracked files.

- [ ] **Step 5: Commit and push only after all gates pass**

```bash
git commit -m "docs: Python evidence S0 coverage 감사 완료"
git push origin main
```

Expected: `main == origin/main`, clean for task-owned files. Existing unrelated untracked files may remain.

- [ ] **Step 6: Stop**

Do not start S1 benchmark, create a migration, change workers, or run VLM. Return only the absolute report path and the final verdict for Codex review.

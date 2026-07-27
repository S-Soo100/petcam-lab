# Camera 1 raw roi_mean Replication Kickoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** camera_1 raw `roi_mean` 미래 재현 연구의 TEST-SHEET와 UTC cutoff를 결과 조회 전에 동결하고, production DB를 SELECT-only로 조회해 최초 collection status와 mutation 0 증거를 남긴다.

**Architecture:** 기존 Owner GT benchmark의 eligibility와 6-table fingerprint SQL을 재사용하되, 새 cutoff 이후의 camera_1 집계만 반환한다. 최초 실행에서는 feature 값과 AUROC를 반환하지 않고 class별 clip·5분 episode·camera-night 수, Evidence coverage, provenance 일치 여부만 익명 집계한다. 순수 Python verifier가 동결 manifest, collection status, fingerprint, tracked identifier 금지 계약을 검사한다.

**Tech Stack:** PostgreSQL SELECT CTE, Python 3.12 표준 라이브러리, pytest, `uv`, Claude Code Supabase read-only SQL tool

## Global Constraints

- 전용 경로 `experiments/roi-mean-camera1-replication-20260727/` 밖의 파일은 수정하지 않는다.
- production DB는 단독 `SELECT` 또는 `WITH` CTE chain의 마지막 `SELECT`만 허용한다. RPC, INSERT, UPDATE, DELETE, DDL, migration을 실행하지 않는다.
- R2, signed URL, Slack, LaunchAgent, runtime, deploy, labeling web/API를 읽거나 변경하지 않는다.
- Python Evidence, Gate, VLM을 재실행하지 않는다.
- clip/camera/user UUID, 이메일, 원문 메모, URL, R2 key를 tracked artifact에 쓰지 않는다.
- cutoff 이후 class별 `roi_mean`, AUROC, CI, median/IQR, 극단값을 minimum sample lock 전에 계산하거나 출력하지 않는다.
- 시작·종료 fingerprint는 `motion_clips`, `motion_clip_labeling_triage`, `motion_clip_labeling_sessions`, `motion_clip_labeling_session_revisions`, `clip_python_evidence_runs`, `clip_prelabels` 정확히 6개를 비교한다.
- target camera는 선행 Owner eligible cohort에서 `camera_id` 오름차순 `dense_rank() = 1`이며 선행 count가 정확히 71이어야 한다.
- Owner identity와 eligibility는 선행 benchmark SQL의 계약을 그대로 사용한다.
- cutoff는 TEST-SHEET가 먼저 commit된 뒤 production DB `now()` SELECT로 한 번만 정한다.
- 최초 상태가 minimum 미달이면 정상 verdict는 `ROI_CAMERA1_REPLICATION_COLLECTING`이다.

---

## File map

- `TEST-SHEET.md`: 결과를 보기 전에 동결한 표본·feature·통계·판정 계약
- `freeze-cutoff.sql`: target camera identity invariant와 DB UTC cutoff를 반환하는 SELECT-only SQL
- `collection-status.sql`: cutoff 이후 class·episode·night·Evidence coverage만 반환하는 SELECT-only SQL
- `verify_collection.py`: aggregate artifact, fingerprint, 민감 identifier 금지 계약 검증
- `test_verify_collection.py`: verifier의 fail-closed 단위 테스트
- `freeze-manifest.json`: cutoff와 익명 invariant만 담는 실행 산출물
- `collection-status.json`: feature 값 없는 최초 수집 현황
- `fingerprints-start.csv`: 실행 시작 시 6-table count+ordered fingerprint
- `fingerprints-end.csv`: 실행 종료 시 동일 6-table fingerprint
- `REPORT.md`: kickoff 결과와 다음 재조회 조건

### Task 1: Freeze the written test contract

**Files:**
- Create: `experiments/roi-mean-camera1-replication-20260727/TEST-SHEET.md`

**Interfaces:**
- Consumes: `DESIGN.md`
- Produces: cutoff 전에 commit되는 frozen research contract

- [ ] **Step 1: Write TEST-SHEET.md**

문서에 아래 값을 정확히 고정한다.

```text
status = FROZEN
target = camera_1, prior Owner eligible count 71
future eligibility = started_at > future_cutoff_utc
positive = initial_gt.observed_actions contains moving
negative = initial_gt.observed_actions contains static and not moving
episode = same camera, consecutive started_at gap <= 5 minutes
minimum clips = moving 30, static_only 30
minimum episodes = moving 20, static_only 20
minimum camera_nights = total 3, each class 2
primary = motion_summary.roi_mean, higher means moving
bootstrap = episode cluster, seed 20260727, iterations 10000, percentile 95% CI
pre-lock visible data = counts, coverage, provenance only
```

판정 문자열과 조건은 `DESIGN.md` 9절을 그대로 전부 기재하고, `SUPPORTED`가 production 채택이 아니라는 문장을 포함한다.

- [ ] **Step 2: Check for placeholders and accidental result fields**

Run:

```bash
rg -n 'TODO|TBD|PLACEHOLDER|FIXME|AUROC.*[0-9]\\.[0-9]|roi_mean.*(median|IQR)' \
  experiments/roi-mean-camera1-replication-20260727/TEST-SHEET.md
```

Expected: placeholder와 future result 숫자 match가 0이다. 고정 기준 `0.50`, `95%`, sample minimum 숫자는 허용한다.

- [ ] **Step 3: Commit the frozen TEST-SHEET before querying cutoff**

```bash
git add experiments/roi-mean-camera1-replication-20260727/TEST-SHEET.md
git commit -m "docs: camera 1 roi_mean 재현 테스트 계약 동결"
```

Expected: commit succeeds. 이 commit 이전에는 production DB query가 없어야 한다.

### Task 2: Implement fail-closed collection artifact verification

**Files:**
- Create: `experiments/roi-mean-camera1-replication-20260727/verify_collection.py`
- Create: `experiments/roi-mean-camera1-replication-20260727/test_verify_collection.py`

**Interfaces:**
- Consumes: `freeze-manifest.json`, `collection-status.json`, `fingerprints-start.csv`, `fingerprints-end.csv`, experiment directory text files
- Produces: `COLLECTION_ARTIFACTS_OK` or a non-zero exit with a specific validation error

- [ ] **Step 1: Write failing unit tests**

Use `importlib.util.spec_from_file_location` because the experiment directory contains hyphens. Tests must define and execute these exact cases:

```text
test_valid_collecting_artifacts_pass
  valid freeze/status and identical six-table fingerprints return without error
test_rejects_cutoff_mismatch
  unequal freeze/status cutoff raises ValueError("cutoff_mismatch")
test_rejects_camera_identity_drift
  prior count other than 71 raises ValueError("camera_identity_drift")
test_rejects_minimum_met_marked_collecting
  all minimum counts with COLLECTING raises ValueError("verdict_mismatch")
test_rejects_feature_value_before_sample_lock
  any forbidden result key raises ValueError("prelock_result_leak")
test_rejects_source_mutation
  changed row count or fingerprint raises ValueError("source_mutation")
test_requires_exact_six_fingerprint_tables
  missing or extra table raises ValueError("fingerprint_scope")
test_rejects_raw_uuid_email_url_r2_key_and_note_key
  each forbidden raw form independently raises ValueError("sensitive_artifact")
```

The valid fixture must use this aggregate shape:

```json
{
  "schema_version": "roi-camera1-collection-v1",
  "snapshot_at_utc": "2026-07-27T00:00:01+00:00",
  "future_cutoff_utc": "2026-07-27T00:00:00+00:00",
  "target_camera_group": "camera_1",
  "prior_target_owner_eligible_count": 71,
  "future": {
    "owner_completed_clips": 0,
    "evidence_ready_clips": 0,
    "excluded_class_clips": 0,
    "moving": {"clips": 0, "episodes": 0, "camera_nights": 0},
    "static_only": {"clips": 0, "episodes": 0, "camera_nights": 0}
  },
  "coverage": {"evidence_ready_fraction": null, "provenance_contract_count": 0},
  "minimum_met": false,
  "verdict": "ROI_CAMERA1_REPLICATION_COLLECTING"
}
```

- [ ] **Step 2: Run tests and confirm RED**

```bash
uv run pytest experiments/roi-mean-camera1-replication-20260727/test_verify_collection.py -q
```

Expected: FAIL because `verify_collection.py` does not exist.

- [ ] **Step 3: Implement the verifier**

Implement these public functions with standard-library-only code and the stated return contract:

```text
EXPECTED_TABLES = {
  motion_clips,
  motion_clip_labeling_triage,
  motion_clip_labeling_sessions,
  motion_clip_labeling_session_revisions,
  clip_python_evidence_runs,
  clip_prelabels
}
validate_collection(freeze: dict, status: dict) -> None or ValueError(code)
validate_fingerprints(start_path: Path, end_path: Path) -> None or ValueError(code)
scan_sensitive_text(root: Path) -> None or ValueError("sensitive_artifact")
verify(root: Path) -> None or propagated ValueError
```

`validate_collection` must assert:

```text
both schema versions are expected
cutoff strings are identical and timezone-aware UTC
snapshot_at_utc > future_cutoff_utc
target_camera_group == camera_1
prior_target_owner_eligible_count == 71
all counts are non-negative integers
evidence_ready_clips <= owner_completed_clips
minimum_met equals all six frozen minimum predicates
minimum_met == false when verdict is ROI_CAMERA1_REPLICATION_COLLECTING
no keys contain roi_mean, auc, ci_low, ci_high, median, iqr, threshold
```

`validate_fingerprints` parses CSV columns `snapshot_at_utc,table_name,row_count,ordered_fingerprint_md5`, requires exact six-table scope once each, and compares `(row_count, ordered_fingerprint_md5)` while ignoring timestamps.

`scan_sensitive_text` scans tracked experiment `.md`, `.json`, `.csv`, `.sql`, `.py` files and rejects:

```text
canonical UUID regex
email regex
http:// or https:// outside Markdown source links already present in DESIGN.md
JSON/data keys named clip_id, camera_id, user_id, reviewed_by, email, note,
signed_url, storage_key, r2_key
```

SQL source necessarily contains database column names. Restrict forbidden-key scanning to `.json` and `.csv`; use UUID/email/URL scanning for generated JSON/CSV artifacts. Do not flag the written SQL contract itself.

CLI:

```bash
uv run python experiments/roi-mean-camera1-replication-20260727/verify_collection.py \
  --root experiments/roi-mean-camera1-replication-20260727
```

On success print exactly `COLLECTION_ARTIFACTS_OK`.

- [ ] **Step 4: Run tests and confirm GREEN**

```bash
uv run pytest experiments/roi-mean-camera1-replication-20260727/test_verify_collection.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit verifier and tests**

```bash
git add experiments/roi-mean-camera1-replication-20260727/verify_collection.py \
  experiments/roi-mean-camera1-replication-20260727/test_verify_collection.py
git commit -m "test: roi_mean 미래 수집 계약 검증기"
```

### Task 3: Create SELECT-only freeze and collection SQL

**Files:**
- Create: `experiments/roi-mean-camera1-replication-20260727/freeze-cutoff.sql`
- Create: `experiments/roi-mean-camera1-replication-20260727/collection-status.sql`

**Interfaces:**
- Consumes: the exact `owner_identity` and completed Owner eligibility CTEs from `experiments/owner-gt-python-evidence-benchmark-20260727/benchmark.sql`
- Produces: one-row anonymous JSON results and the exact six-table fingerprint rows

- [ ] **Step 1: Write freeze-cutoff.sql**

The file must contain one `WITH` CTE chain ending in a `SELECT`. Recreate `owner_identity` and historical completed Owner cohort exactly, then rank cameras:

```sql
camera_counts AS (
  SELECT camera_id, count(*) AS owner_eligible_count
  FROM cohort
  GROUP BY camera_id
),
ranked AS (
  SELECT
    camera_id,
    owner_eligible_count,
    dense_rank() OVER (ORDER BY camera_id) AS camera_rank
  FROM camera_counts
)
SELECT jsonb_build_object(
  'schema_version', 'roi-camera1-freeze-v1',
  'frozen_at_utc', now(),
  'future_cutoff_utc', now(),
  'target_camera_group', 'camera_1',
  'target_camera_count', count(*) FILTER (WHERE camera_rank = 1),
  'prior_target_owner_eligible_count',
    max(owner_eligible_count) FILTER (WHERE camera_rank = 1),
  'prior_owner_eligible_count', (SELECT count(*) FROM cohort)
) AS freeze_manifest
FROM ranked;
```

The query must not return `camera_id`, user identity, clip identity, or GT JSON.

- [ ] **Step 2: Write collection-status.sql**

Use a psql-style literal marker `:'future_cutoff_utc'` only in the tracked SQL. Before executing through a tool without psql variable support, substitute the exact frozen UTC timestamp in memory; do not commit a raw-data export.

Required CTE order:

```text
owner_identity
historical_cohort
target_camera
future_owner_completed
future_with_evidence
classified
episode_ordered
episode_numbered
aggregate_status
```

`future_owner_completed` must require all of:

```sql
mc.camera_id = target_camera.camera_id
AND mc.started_at > :'future_cutoff_utc'::timestamptz
AND s.reviewed_by = owner_identity.id
AND s.stage = 'completed'
AND s.initial_gt IS NOT NULL
AND s.current_gt IS NOT NULL
AND s.completed_at IS NOT NULL
```

`future_with_evidence` must LEFT JOIN an evidence aggregation grouped by clip so duplicates are visible. An Evidence-ready clip requires exactly one run, `level0_status = 'ok'`, `level1_status = 'ok'`, finite numeric `motion_summary->>'roi_mean'`, and one canonical provenance tuple. The final query may count readiness but must not select or aggregate the `roi_mean` values.

Classify only from `initial_gt`:

```sql
CASE
  WHEN initial_gt->'observed_actions' ? 'moving' THEN 'moving'
  WHEN initial_gt->'observed_actions' ? 'static'
   AND NOT (initial_gt->'observed_actions' ? 'moving') THEN 'static_only'
  ELSE 'excluded'
END
```

Episode boundaries use `started_at - lag(started_at) > interval '5 minutes'`. Camera-night is `(started_at AT TIME ZONE 'Asia/Seoul')::date`; return only distinct counts, never dates.

The returned JSON must match the fixture in Task 2. Calculate `minimum_met` from the exact six predicates in `DESIGN.md`. If false, verdict is `ROI_CAMERA1_REPLICATION_COLLECTING`. Because this kickoff runs immediately after cutoff, if it unexpectedly becomes true, do not calculate results; report `ROI_REPLICATION_HOLD_UNEXPECTED_MINIMUM_AT_KICKOFF`.

Append the exact six-table fingerprint SELECT from `experiments/owner-gt-python-evidence-benchmark-20260727/benchmark.sql` as a second SELECT-only statement.

- [ ] **Step 3: Static-check SQL for writes and sensitive projections**

```bash
if rg -ni '\\b(insert|update|delete|merge|alter|create|drop|truncate|grant|revoke|call)\\b' \
  experiments/roi-mean-camera1-replication-20260727/*.sql; then exit 1; fi
rg -n 'SELECT.*(clip_id|camera_id|reviewed_by)|jsonb_agg' \
  experiments/roi-mean-camera1-replication-20260727/*.sql
```

Expected: first command succeeds with no matches. Review any second-command match and remove raw projections from final output; CTE-local identity columns are allowed.

- [ ] **Step 4: Commit SQL**

```bash
git add experiments/roi-mean-camera1-replication-20260727/freeze-cutoff.sql \
  experiments/roi-mean-camera1-replication-20260727/collection-status.sql
git commit -m "chore: roi_mean 미래 수집 SQL 동결"
```

### Task 4: Execute the read-only kickoff

**Files:**
- Create: `experiments/roi-mean-camera1-replication-20260727/freeze-manifest.json`
- Create: `experiments/roi-mean-camera1-replication-20260727/collection-status.json`
- Create: `experiments/roi-mean-camera1-replication-20260727/fingerprints-start.csv`
- Create: `experiments/roi-mean-camera1-replication-20260727/fingerprints-end.csv`

**Interfaces:**
- Consumes: committed TEST-SHEET and SQL
- Produces: aggregate-only kickoff evidence

- [ ] **Step 1: Record exact git start state**

```bash
pwd
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
git status --short --branch
```

Expected: branch `codex/roi-mean-camera1-replication-20260727`; report any pre-existing untracked/dirty path and do not overwrite it.

- [ ] **Step 2: Execute the start fingerprint SELECT**

Use Claude Code's connected Supabase SQL execution tool. Submit only the second fingerprint statement from `collection-status.sql`. Save the six returned aggregate rows as CSV with no formatting changes besides column order:

```text
snapshot_at_utc,table_name,row_count,ordered_fingerprint_md5
```

- [ ] **Step 3: Execute freeze-cutoff.sql exactly once**

Use the same Supabase SELECT-only tool. Validate before saving:

```text
target_camera_count == 1
prior_target_owner_eligible_count == 71
prior_owner_eligible_count == 172
frozen_at_utc == future_cutoff_utc
```

If any invariant fails, write no collection result and report `ROI_REPLICATION_HOLD_CAMERA_IDENTITY_DRIFT`. Otherwise save the returned object as `freeze-manifest.json`; it must contain no identity fields.

- [ ] **Step 4: Execute collection-status.sql with the frozen cutoff**

Substitute the exact `future_cutoff_utc` from the manifest. Execute only the status SELECT. Save the single JSON object as `collection-status.json`.

Expected immediately after cutoff:

```text
minimum_met = false
verdict = ROI_CAMERA1_REPLICATION_COLLECTING
```

Do not inspect or request any `roi_mean` value.

- [ ] **Step 5: Execute the end fingerprint SELECT**

Run the same fingerprint statement again and save `fingerprints-end.csv`. Start/end timestamps may differ; all six `(row_count, ordered_fingerprint_md5)` pairs must match.

- [ ] **Step 6: Verify artifacts**

```bash
uv run python experiments/roi-mean-camera1-replication-20260727/verify_collection.py \
  --root experiments/roi-mean-camera1-replication-20260727
```

Expected: `COLLECTION_ARTIFACTS_OK`.

- [ ] **Step 7: Commit aggregate evidence**

```bash
git add experiments/roi-mean-camera1-replication-20260727/freeze-manifest.json \
  experiments/roi-mean-camera1-replication-20260727/collection-status.json \
  experiments/roi-mean-camera1-replication-20260727/fingerprints-start.csv \
  experiments/roi-mean-camera1-replication-20260727/fingerprints-end.csv
git commit -m "chore: camera 1 미래 수집 기준선 기록"
```

### Task 5: Report, verify, review, and push

**Files:**
- Create: `experiments/roi-mean-camera1-replication-20260727/REPORT.md`

**Interfaces:**
- Consumes: verified aggregate artifacts and git evidence
- Produces: reviewable kickoff report and pushed feature branch

- [ ] **Step 1: Write REPORT.md**

Include:

```text
verdict
future_cutoff_utc
target identity invariants: one camera, prior 71/172 counts
current moving/static-only clip, episode, camera-night counts
Evidence-ready coverage and provenance count
minimum deficits
six-table mutation 0 result
branch, HEAD, upstream, origin/main, tracked/untracked status
explicit non-actions: no AUC, feature distribution, training, tuning, selector,
production write, R2, VLM/Gate/Evidence rerun, runtime, deploy
next action: keep normal Owner labeling and rerun only collection-status after
new camera_1 completed GT accrues
```

- [ ] **Step 2: Run focused and full verification**

```bash
uv run pytest experiments/roi-mean-camera1-replication-20260727/test_verify_collection.py -q
uv run pytest -q
git diff --check
uv run python experiments/roi-mean-camera1-replication-20260727/verify_collection.py \
  --root experiments/roi-mean-camera1-replication-20260727
```

Expected: focused tests pass, full suite has no failures, diff check is empty, verifier prints `COLLECTION_ARTIFACTS_OK`.

- [ ] **Step 3: Perform an independent read-only review**

Use a fresh Claude subagent or `codex exec -s read-only` to compare `DESIGN.md`, `TEST-SHEET.md`, SQL, verifier, artifacts, and report. Require findings grouped as Critical/Important/Minor. Fix all Critical and Important findings within the experiment directory, rerun Step 2, and record review outcome in the report.

- [ ] **Step 4: Commit the final report**

```bash
git add experiments/roi-mean-camera1-replication-20260727/REPORT.md \
  experiments/roi-mean-camera1-replication-20260727
git commit -m "docs: camera 1 roi_mean 미래 수집 시작 보고"
```

- [ ] **Step 5: Push the feature branch**

```bash
git push origin codex/roi-mean-camera1-replication-20260727
git status --short --branch
git rev-parse HEAD
git rev-parse @{upstream}
```

Expected: local HEAD equals upstream and there are no tracked or untracked changes created by this task.

## Completion state

This kickoff is complete at `ROI_CAMERA1_REPLICATION_COLLECTING`, not at a discrimination verdict. `SUPPORTED`, `REJECTED`, or `INCONCLUSIVE` can only be calculated after all frozen minimums are met and a separate sample-lock execution begins. Lack of post-cutoff samples immediately after freezing is expected and is not a blocker.

# Unified GT Catalog · VLM/Evidence Failure Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Owner GT 172, legacy 사람 GT, dataset203을 provenance-aware catalog로 연결하고 독립 episode 기준 VLM·Evidence 상위 실패 원인 최대 3개와 다음 개선 후보 1개를 SELECT-only로 판정한다.

**Architecture:** Production DB와 로컬 dataset203 manifest에서 row-level 원시 자료를 gitignored `raw/`로만 추출하고, 순수 Python 분석기가 canonical mapping·신뢰 등급·중복/episode grouping·failure ranking을 수행한다. Tracked 산출물은 집계 JSON, 비식별 hash, fingerprint, 검증 코드, 보고서로 제한하며 독립 verifier가 민감 필드·누출·mutation 0·verdict 일관성을 검사한다.

**Tech Stack:** Python 3.12, 표준 라이브러리(`csv`, `hashlib`, `json`, `statistics`, `pathlib`), PostgreSQL/Supabase SELECT-only, pytest, uv

## Global Constraints

- 전용 경로 `experiments/unified-gt-failure-audit-20260727/` 밖 파일은 수정하지 않는다.
- Production DB는 SELECT-only다. INSERT/UPDATE/DELETE/RPC write/DDL/migration을 실행하지 않는다.
- R2 write, signed URL 저장, VLM·Python Evidence·Gate 재실행, Slack, LaunchAgent, deploy를 하지 않는다.
- clip UUID, R2 key, 사용자 식별자, 이메일, 원문 note를 tracked 파일에 남기지 않는다.
- dataset203과 기존 평가 노출 데이터는 EDA/dev 전용이며 future holdout으로 재사용하지 않는다.
- 자동 결과를 사람 GT로 순환 사용하지 않는다.
- 모델 학습, prompt/threshold/selector 변경은 하지 않는다.
- 정확한 eligibility와 실제 count는 schema/RPC/code 및 SELECT-only snapshot으로 확정한다.
- 시작·종료 관련 table count+ordered fingerprint를 비교해 관찰 범위 mutation 0을 증명한다.
- 상위 원인은 T1/T2, 10 independent episodes, 2 camera-nights, duplicate group 최대 20% 조건을 모두 만족해야 한다.
- 근거가 부족하면 `UNIFIED_GT_FAILURE_AUDIT_HOLD_<REASON>`으로 끝낸다.

---

## File Map

| 파일 | 책임 |
|---|---|
| `DESIGN.md` | 승인된 연구 목적·데이터 역할·판정 계약 |
| `.gitignore` | 민감 row-level export가 들어가는 `raw/` 추적 차단 |
| `TEST-SHEET.md` | 실행 전 동결하는 eligibility·dedup·failure·verdict 계약 |
| `inventory.sql` | source inventory, coverage, fingerprint를 만드는 SELECT-only query |
| `analyze.py` | 순수 canonical mapping, trust tier, dedup/episode, failure ranking |
| `test_analyze.py` | mapping·dedup·ranking TDD |
| `verify_artifacts.py` | SQL read-only, 민감 원시 누출, aggregate/verdict/fingerprint 검증 |
| `test_verify_artifacts.py` | verifier TDD |
| `fingerprints-start.csv` | 시작 table count+ordered fingerprint |
| `fingerprints-end.csv` | 종료 table count+ordered fingerprint |
| `source-summary.json` | source별 eligible/unique/trust/mapping/exposure 집계 |
| `overlap-summary.json` | source pair overlap, exact/probable/episode 집계 |
| `failure-summary.json` | coverage, 원인별 episode/camera-night/source, top causes, verdict |
| `REPORT.md` | 최종 근거·한계·추천 후보·mutation 0·git/non-actions |

---

### Task 1: 실행 계약과 raw 경계 동결

**Files:**
- Create: `experiments/unified-gt-failure-audit-20260727/.gitignore`
- Create: `experiments/unified-gt-failure-audit-20260727/TEST-SHEET.md`
- Test: `experiments/unified-gt-failure-audit-20260727/test_verify_artifacts.py`
- Create: `experiments/unified-gt-failure-audit-20260727/verify_artifacts.py`

**Interfaces:**
- Consumes: `DESIGN.md`
- Produces:
  - `RAW_DIR_NAME = "raw"`
  - `assert_raw_ignored(root: Path) -> None`
  - `assert_no_sensitive_tracked_content(root: Path) -> None`

- [ ] **Step 1: Write failing raw-boundary tests**

```python
from pathlib import Path

import pytest

import verify_artifacts


def test_raw_directory_is_gitignored(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("/raw/\n", encoding="utf-8")
    verify_artifacts.assert_raw_ignored(tmp_path)


def test_rejects_missing_raw_ignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="raw_not_ignored"):
        verify_artifacts.assert_raw_ignored(tmp_path)


def test_rejects_sensitive_field_names_in_tracked_json(tmp_path: Path) -> None:
    (tmp_path / "source-summary.json").write_text(
        '{"clip_id":"00000000-0000-0000-0000-000000000000"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="sensitive_tracked_content"):
        verify_artifacts.assert_no_sensitive_tracked_content(tmp_path)
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest experiments/unified-gt-failure-audit-20260727/test_verify_artifacts.py -q
```

Expected: FAIL because `verify_artifacts.py` does not exist.

- [ ] **Step 3: Add raw ignore and minimal verifier**

`.gitignore`:

```gitignore
/raw/
```

`verify_artifacts.py`:

```python
from pathlib import Path

RAW_DIR_NAME = "raw"
SENSITIVE_TOKENS = (
    '"clip_id"',
    '"r2_key"',
    '"signed_url"',
    '"email"',
    '"user_id"',
    '"reviewed_by"',
    '"note"',
)


def assert_raw_ignored(root: Path) -> None:
    ignore = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    if "/raw/" not in ignore:
        raise ValueError("raw_not_ignored")


def assert_no_sensitive_tracked_content(root: Path) -> None:
    for path in root.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in SENSITIVE_TOKENS):
            raise ValueError(f"sensitive_tracked_content {path.name}")
```

- [ ] **Step 4: Write `TEST-SHEET.md`**

Include these frozen statements verbatim:

```markdown
- Primary analysis GT: T1; T2는 확장 민감도 분석; T3는 EDA only; X는 GT 제외
- Owner eligibility: reviewed_by=audited Owner AND stage=completed AND initial_gt/current_gt/completed_at non-null
- dataset203: manifest 실제 유효 행 재측정, historical exposure=true, future holdout=false
- Dedup precedence: source FK → salted object-key hash → content hash → camera/time/duration/size → near episode
- Split/group unit: duplicate group → 5-minute episode → camera-night
- Top cause: T1/T2, >=10 episodes, >=2 camera-nights, largest duplicate group <=20%
- READY는 top cause >=1과 next_candidate 정확히 1개일 때만
- 그 외 `UNIFIED_GT_FAILURE_AUDIT_HOLD_<REASON>`
- 결과를 본 뒤 taxonomy, 최소 표본, ranking score를 변경하지 않음
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest experiments/unified-gt-failure-audit-20260727/test_verify_artifacts.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

```bash
git add experiments/unified-gt-failure-audit-20260727/.gitignore \
  experiments/unified-gt-failure-audit-20260727/TEST-SHEET.md \
  experiments/unified-gt-failure-audit-20260727/verify_artifacts.py \
  experiments/unified-gt-failure-audit-20260727/test_verify_artifacts.py
git commit -m "test: 통합 GT 감사 데이터 경계 동결"
```

---

### Task 2: SELECT-only inventory와 fingerprint 계약

**Files:**
- Create: `experiments/unified-gt-failure-audit-20260727/inventory.sql`
- Modify: `experiments/unified-gt-failure-audit-20260727/verify_artifacts.py`
- Modify: `experiments/unified-gt-failure-audit-20260727/test_verify_artifacts.py`

**Interfaces:**
- Consumes: production schema, Owner eligibility from `TEST-SHEET.md`
- Produces:
  - `assert_select_only_sql(sql: str) -> None`
  - SQL result sets `table_fingerprints`, `source_inventory`, `asset_coverage`

- [ ] **Step 1: Write failing SQL guard tests**

```python
def test_inventory_sql_is_select_only() -> None:
    sql = (ROOT / "inventory.sql").read_text(encoding="utf-8")
    verify_artifacts.assert_select_only_sql(sql)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO x VALUES (1)",
        "UPDATE x SET a=1",
        "DELETE FROM x",
        "CREATE TABLE x(a int)",
        "SELECT public.fn_write_something()",
    ],
)
def test_rejects_write_sql(statement: str) -> None:
    with pytest.raises(ValueError, match="non_select_sql"):
        verify_artifacts.assert_select_only_sql(statement)
```

- [ ] **Step 2: Run the guard tests to verify RED**

Run:

```bash
uv run pytest experiments/unified-gt-failure-audit-20260727/test_verify_artifacts.py -q
```

Expected: FAIL with missing `assert_select_only_sql`.

- [ ] **Step 3: Implement SQL guard**

```python
import re

FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|merge|create|alter|drop|truncate|grant|revoke|"
    r"comment|copy|call|do|vacuum|analyze|refresh|reindex|cluster)\b",
    re.IGNORECASE,
)


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", sql)


def assert_select_only_sql(sql: str) -> None:
    clean = _strip_sql_comments(sql)
    if FORBIDDEN_SQL.search(clean):
        raise ValueError("non_select_sql")
    for statement in clean.split(";"):
        statement = statement.strip()
        if statement and not re.match(r"^(with|select)\b", statement, re.IGNORECASE):
            raise ValueError("non_select_sql")
    if re.search(r"\bselect\s+\w+(?:\.\w+)+\s*\(", clean, re.IGNORECASE):
        raise ValueError("non_select_sql_function_call")
```

- [ ] **Step 4: Write `inventory.sql` using only CTE and SELECT**

The SQL must:

1. Resolve Owner identity using the four audited facts from `DESIGN.md`.
2. Emit Owner completed, in-progress, triage, exclusion, canary, blind submission counts separately.
3. Inventory legacy human GT candidates by provenance and exclude automatic/tutorial rows.
4. Link dataset203 through existing DB keys only when schema/code proves the relationship; do not infer from filenames.
5. Emit Evidence/Gate/VLM coverage by source and provenance tuple.
6. Emit fingerprints as `md5(string_agg(row_hash, '' ORDER BY row_hash))` with row count.
7. Hash sensitive join keys inside SQL using a per-run salt supplied as `:'audit_salt'`; never return raw UUID/R2 key.
8. Return row-level exports only to the ignored `raw/` execution output, and tracked queries only as aggregates.

Required fingerprint tables:

```text
motion_clip_labeling_sessions
motion_clip_labeling_triage
motion_clip_labeling_triage_events
motion_labeling_blind_submissions
motion_labeling_consensus
clip_labeling_sessions
clip_labeling_session_revisions
behavior_labels
behavior_logs
clip_python_evidence_runs
clip_prelabels
vlm_jobs
```

- [ ] **Step 5: Run static SELECT-only verification**

Run:

```bash
uv run pytest experiments/unified-gt-failure-audit-20260727/test_verify_artifacts.py -q
```

Expected: all tests PASS and `inventory.sql` passes `assert_select_only_sql`.

- [ ] **Step 6: Commit**

```bash
git add experiments/unified-gt-failure-audit-20260727/inventory.sql \
  experiments/unified-gt-failure-audit-20260727/verify_artifacts.py \
  experiments/unified-gt-failure-audit-20260727/test_verify_artifacts.py
git commit -m "test: 통합 GT SELECT-only inventory 계약"
```

---

### Task 3: Canonical mapping·trust tier·dedup 분석기

**Files:**
- Create: `experiments/unified-gt-failure-audit-20260727/analyze.py`
- Create: `experiments/unified-gt-failure-audit-20260727/test_analyze.py`

**Interfaces:**
- Consumes: ignored `raw/source-records.jsonl`, ignored dataset203 manifest snapshot
- Produces:
  - `assign_trust_tier(record: dict) -> str`
  - `canonicalize_targets(record: dict) -> dict[str, str]`
  - `dedup_key(record: dict) -> tuple[str, str]`
  - `group_episodes(records: list[dict], gap_seconds: int = 300) -> list[dict]`
  - `summarize_sources(records: list[dict]) -> dict`
  - `summarize_overlap(records: list[dict]) -> dict`

- [ ] **Step 1: Write failing trust and mapping tests**

```python
def test_blind_immutable_human_gt_is_t1() -> None:
    record = {
        "human": True,
        "blind": True,
        "immutable_initial_gt": True,
        "provenance_complete": True,
        "automatic": False,
        "tutorial": False,
    }
    assert analyze.assign_trust_tier(record) == "T1"


def test_automatic_result_is_excluded() -> None:
    record = {"automatic": True, "human": False}
    assert analyze.assign_trust_tier(record) == "X"


def test_unknown_mapping_is_not_inferred() -> None:
    result = analyze.canonicalize_targets(
        {"motion": None, "visibility": None, "primary_action": "legacy_unknown"}
    )
    assert result == {
        "motion": "unknown",
        "visibility": "unknown",
        "primary_action": "unknown",
        "care_event": "unknown",
        "highlight": "unavailable",
        "judgeability": "unavailable",
    }
```

- [ ] **Step 2: Write failing dedup and episode tests**

```python
def test_exact_object_hash_precedes_temporal_match() -> None:
    record = {
        "source_fk_hash": None,
        "object_key_hash": "obj-a",
        "content_hash": None,
        "camera_hash": "cam-a",
        "started_at_epoch": 100,
        "duration_ms": 60000,
        "size_bytes": 1000,
    }
    assert analyze.dedup_key(record) == ("exact_object", "obj-a")


def test_five_minute_gap_groups_same_camera_episode() -> None:
    records = [
        {"record_hash": "a", "camera_hash": "cam", "started_at_epoch": 100},
        {"record_hash": "b", "camera_hash": "cam", "started_at_epoch": 399},
        {"record_hash": "c", "camera_hash": "cam", "started_at_epoch": 700},
    ]
    grouped = analyze.group_episodes(records)
    assert grouped[0]["episode_group_hash"] == grouped[1]["episode_group_hash"]
    assert grouped[1]["episode_group_hash"] != grouped[2]["episode_group_hash"]
```

- [ ] **Step 3: Run tests to verify RED**

Run:

```bash
uv run pytest experiments/unified-gt-failure-audit-20260727/test_analyze.py -q
```

Expected: FAIL because `analyze.py` does not exist.

- [ ] **Step 4: Implement minimal pure functions**

Use deterministic SHA-256 of canonical JSON for generated group hashes:

```python
def stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

Implement trust precedence `X → T1 → T2 → T3`, lossless allowlist mapping, dedup precedence from
`DESIGN.md`, and camera-sorted 300-second episode grouping. Do not read DB or network inside these
functions.

- [ ] **Step 5: Add source and overlap summary tests**

```python
def test_source_summary_separates_rows_unique_and_trust() -> None:
    records = [
        {"source": "owner", "canonical_clip_key": "x", "trust_tier": "T1"},
        {"source": "dataset203", "canonical_clip_key": "x", "trust_tier": "T3"},
        {"source": "dataset203", "canonical_clip_key": "y", "trust_tier": "T2"},
    ]
    summary = analyze.summarize_sources(records)
    assert summary["total_rows"] == 3
    assert summary["unique_clips"] == 2
    assert summary["sources"]["dataset203"]["rows"] == 2
    assert summary["trust_tiers"] == {"T1": 1, "T2": 1, "T3": 1}


def test_overlap_summary_counts_cross_source_clip_once() -> None:
    records = [
        {"source": "owner", "canonical_clip_key": "x"},
        {"source": "legacy", "canonical_clip_key": "x"},
        {"source": "legacy", "canonical_clip_key": "y"},
    ]
    overlap = analyze.summarize_overlap(records)
    assert overlap["source_pairs"]["legacy|owner"]["exact_unique_clips"] == 1
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest experiments/unified-gt-failure-audit-20260727/test_analyze.py -q
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add experiments/unified-gt-failure-audit-20260727/analyze.py \
  experiments/unified-gt-failure-audit-20260727/test_analyze.py
git commit -m "feat: 통합 GT canonical mapping과 중복 분석기"
```

---

### Task 4: Failure linkage와 top-cause ranking

**Files:**
- Modify: `experiments/unified-gt-failure-audit-20260727/analyze.py`
- Modify: `experiments/unified-gt-failure-audit-20260727/test_analyze.py`

**Interfaces:**
- Consumes: canonical records with GT and existing result linkage
- Produces:
  - `derive_failures(record: dict) -> list[dict]`
  - `summarize_failures(records: list[dict]) -> dict`
  - `rank_causes(failures: list[dict]) -> list[dict]`
  - `decide_verdict(summary: dict) -> tuple[str, dict | None]`

- [ ] **Step 1: Write failing failure-definition tests**

```python
def test_vlm_action_mismatch_creates_failure_without_using_vlm_as_gt() -> None:
    record = {
        "trust_tier": "T1",
        "gt": {"primary_action": "drinking"},
        "vlm": {"primary_action": "licking", "status": "success"},
        "evidence": None,
        "candidate_causes": ["SEMANTIC_ONTOLOGY"],
    }
    failures = analyze.derive_failures(record)
    assert failures[0]["failure_kind"] == "vlm_primary_action_mismatch"
    assert failures[0]["candidate_causes"] == ["SEMANTIC_ONTOLOGY"]


def test_gate_present_on_absent_gt_is_visibility_false_positive() -> None:
    record = {
        "trust_tier": "T1",
        "gt": {"visibility": "absent"},
        "gate": {"present": True, "status": "ok"},
        "candidate_causes": ["VISIBILITY_SCALE_OCCLUSION"],
    }
    failures = analyze.derive_failures(record)
    assert failures[0]["failure_kind"] == "gate_visibility_false_positive"
```

- [ ] **Step 2: Write failing ranking qualification tests**

```python
def test_top_cause_requires_episode_and_camera_night_support() -> None:
    failures = [
        {
            "cause": "TEMPORAL_SAMPLING",
            "episode_group_hash": f"e{i}",
            "camera_night_hash": "n1" if i < 5 else "n2",
            "source": "owner",
            "duplicate_group_hash": f"d{i}",
            "trust_tier": "T1",
            "care_or_highlight_miss": i < 3,
        }
        for i in range(10)
    ]
    ranked = analyze.rank_causes(failures)
    assert ranked[0]["qualified"] is True
    assert ranked[0]["independent_episodes"] == 10


def test_duplicate_dominated_cause_is_not_qualified() -> None:
    failures = [
        {
            "cause": "IR_LIGHT_REFLECTION",
            "episode_group_hash": f"e{i}",
            "camera_night_hash": "n1" if i < 5 else "n2",
            "source": "owner",
            "duplicate_group_hash": "same" if i < 3 else f"d{i}",
            "trust_tier": "T1",
            "care_or_highlight_miss": False,
        }
        for i in range(10)
    ]
    assert analyze.rank_causes(failures)[0]["qualified"] is False
```

- [ ] **Step 3: Run tests to verify RED**

Run:

```bash
uv run pytest experiments/unified-gt-failure-audit-20260727/test_analyze.py -q
```

Expected: FAIL with missing failure functions.

- [ ] **Step 4: Implement deterministic failure and ranking rules**

Ranking sort key:

```python
(
    qualified,
    independent_episodes,
    care_highlight_miss_episodes,
    camera_nights,
    source_count,
    cause,
)
```

Sort descending for numeric fields and ascending as a final lexical tie-break. Report
`addressable_error_mass = affected_error_episodes / all_error_episodes`; do not claim expected
accuracy gain.

Verdict rules:

```python
qualified = [cause for cause in ranked if cause["qualified"]]
if not qualified:
    return "UNIFIED_GT_FAILURE_AUDIT_HOLD_INSUFFICIENT_INDEPENDENT_ERRORS", None
candidate = map_cause_to_candidate(qualified[0]["cause"])
return "UNIFIED_GT_FAILURE_AUDIT_READY_FOR_REVIEW", candidate
```

Cause-to-candidate allowlist:

```python
{
    "VISIBILITY_SCALE_OCCLUSION": "visibility_bbox_roi_experiment",
    "TEMPORAL_SAMPLING": "segment_aware_sampling_experiment",
    "IR_LIGHT_REFLECTION": "ir_illumination_evidence_experiment",
    "CAMERA_DOMAIN": "camera_stratified_calibration_audit",
    "SEMANTIC_ONTOLOGY": "ontology_prompt_blind_experiment",
    "INPUT_QUALITY": "judgeability_abstention_experiment",
    "EVIDENCE_SPURIOUS_OR_MISSING": "evidence_sensor_ablation",
    "GT_AMBIGUITY_OR_ERROR": "human_relabel_agreement_audit",
    "PIPELINE_PROVENANCE": "provenance_pipeline_fix_audit",
    "OTHER_UNRESOLVED": "manual_failure_review",
}
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest experiments/unified-gt-failure-audit-20260727/test_analyze.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add experiments/unified-gt-failure-audit-20260727/analyze.py \
  experiments/unified-gt-failure-audit-20260727/test_analyze.py
git commit -m "feat: VLM Evidence 실패원인 집계와 판정"
```

---

### Task 5: SELECT-only snapshot 실행과 aggregate 생성

**Files:**
- Create: `experiments/unified-gt-failure-audit-20260727/fingerprints-start.csv`
- Create: `experiments/unified-gt-failure-audit-20260727/fingerprints-end.csv`
- Create: `experiments/unified-gt-failure-audit-20260727/source-summary.json`
- Create: `experiments/unified-gt-failure-audit-20260727/overlap-summary.json`
- Create: `experiments/unified-gt-failure-audit-20260727/failure-summary.json`
- Create ignored: `experiments/unified-gt-failure-audit-20260727/raw/source-records.jsonl`
- Create ignored: `experiments/unified-gt-failure-audit-20260727/raw/join-map.jsonl`

**Interfaces:**
- Consumes: `inventory.sql`, local `storage/dataset-203/manifest.csv` when available
- Produces: tracked aggregate artifacts matching `analyze.py` schemas

- [ ] **Step 1: Record pre-query state**

Run:

```bash
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

Save exact outputs in the execution log for `REPORT.md`. Abort if changes exist outside the
experiment directory.

- [ ] **Step 2: Run SQL static guard before DB access**

Run:

```bash
uv run python experiments/unified-gt-failure-audit-20260727/verify_artifacts.py \
  --sql-only experiments/unified-gt-failure-audit-20260727/inventory.sql
```

Expected: `SELECT_ONLY_OK`.

- [ ] **Step 3: Execute start fingerprint SELECT**

Execute only the fingerprint SELECT from `inventory.sql` against production DB. Save the returned
aggregate rows to `fingerprints-start.csv` with columns:

```csv
snapshot_at_utc,table_name,row_count,ordered_fingerprint
```

Do not run an RPC and do not enable any write-capable transaction.

- [ ] **Step 4: Execute inventory SELECTs**

Use a fresh random audit salt held only in process memory. Export row-level hashed records to ignored
`raw/source-records.jsonl`. If `storage/dataset-203/manifest.csv` is absent, record
`dataset203_asset_status="missing"` and continue to a HOLD-capable result; do not read another
worktree or invent rows.

- [ ] **Step 5: Generate aggregate JSON**

Run:

```bash
uv run python experiments/unified-gt-failure-audit-20260727/analyze.py \
  --raw experiments/unified-gt-failure-audit-20260727/raw/source-records.jsonl \
  --source-out experiments/unified-gt-failure-audit-20260727/source-summary.json \
  --overlap-out experiments/unified-gt-failure-audit-20260727/overlap-summary.json \
  --failure-out experiments/unified-gt-failure-audit-20260727/failure-summary.json
```

Expected: `ANALYSIS_OK` and no raw identifiers in tracked outputs.

- [ ] **Step 6: Independently recompute aggregate**

Run the analyzer a second time with records sorted in reverse order:

```bash
uv run python experiments/unified-gt-failure-audit-20260727/analyze.py \
  --raw experiments/unified-gt-failure-audit-20260727/raw/source-records.jsonl \
  --reverse-input \
  --compare-source experiments/unified-gt-failure-audit-20260727/source-summary.json \
  --compare-overlap experiments/unified-gt-failure-audit-20260727/overlap-summary.json \
  --compare-failure experiments/unified-gt-failure-audit-20260727/failure-summary.json
```

Expected: `INDEPENDENT_RECOMPUTE_OK`.

- [ ] **Step 7: Execute end fingerprint SELECT**

Run the same fingerprint query and save `fingerprints-end.csv`. Compare exact table set, row counts,
and ordered fingerprints. Any difference results in
`UNIFIED_GT_FAILURE_AUDIT_HOLD_SOURCE_MUTATED_DURING_AUDIT`.

- [ ] **Step 8: Verify ignored raw files**

Run:

```bash
git check-ignore experiments/unified-gt-failure-audit-20260727/raw/source-records.jsonl
git status --short
```

Expected: the first command prints the raw path; git status does not list `raw/`.

- [ ] **Step 9: Commit aggregate artifacts**

```bash
git add experiments/unified-gt-failure-audit-20260727/fingerprints-start.csv \
  experiments/unified-gt-failure-audit-20260727/fingerprints-end.csv \
  experiments/unified-gt-failure-audit-20260727/source-summary.json \
  experiments/unified-gt-failure-audit-20260727/overlap-summary.json \
  experiments/unified-gt-failure-audit-20260727/failure-summary.json
git commit -m "chore: 통합 GT 실패원인 SELECT-only snapshot"
```

---

### Task 6: Artifact verifier와 최종 REPORT

**Files:**
- Modify: `experiments/unified-gt-failure-audit-20260727/verify_artifacts.py`
- Modify: `experiments/unified-gt-failure-audit-20260727/test_verify_artifacts.py`
- Create: `experiments/unified-gt-failure-audit-20260727/REPORT.md`

**Interfaces:**
- Consumes: all tracked aggregate artifacts
- Produces:
  - `verify(root: Path) -> None`
  - CLI success marker `UNIFIED_GT_ARTIFACTS_OK`

- [ ] **Step 1: Write failing artifact consistency tests**

```python
def test_rejects_fingerprint_mutation(tmp_path: Path) -> None:
    (tmp_path / "fingerprints-start.csv").write_text(
        "snapshot_at_utc,table_name,row_count,ordered_fingerprint\n"
        "a,t,1,aaa\n",
        encoding="utf-8",
    )
    (tmp_path / "fingerprints-end.csv").write_text(
        "snapshot_at_utc,table_name,row_count,ordered_fingerprint\n"
        "b,t,2,bbb\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="fingerprint_mutation"):
        verify_artifacts.assert_fingerprints_equal(tmp_path)


def test_ready_requires_one_candidate_and_qualified_cause() -> None:
    summary = {
        "verdict": "UNIFIED_GT_FAILURE_AUDIT_READY_FOR_REVIEW",
        "top_causes": [{"cause": "TEMPORAL_SAMPLING", "qualified": True}],
        "next_candidate": {"id": "segment_aware_sampling_experiment"},
    }
    verify_artifacts.assert_verdict_consistent(summary)


def test_rejects_ready_without_candidate() -> None:
    summary = {
        "verdict": "UNIFIED_GT_FAILURE_AUDIT_READY_FOR_REVIEW",
        "top_causes": [{"cause": "TEMPORAL_SAMPLING", "qualified": True}],
        "next_candidate": None,
    }
    with pytest.raises(ValueError, match="ready_without_candidate"):
        verify_artifacts.assert_verdict_consistent(summary)
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest experiments/unified-gt-failure-audit-20260727/test_verify_artifacts.py -q
```

Expected: FAIL with missing consistency functions.

- [ ] **Step 3: Implement final verifier**

`verify(root)` must call:

```python
assert_raw_ignored(root)
assert_no_sensitive_tracked_content(root)
assert_select_only_sql((root / "inventory.sql").read_text(encoding="utf-8"))
assert_fingerprints_equal(root)
assert_source_summary(json.loads((root / "source-summary.json").read_text()))
assert_overlap_summary(json.loads((root / "overlap-summary.json").read_text()))
assert_verdict_consistent(json.loads((root / "failure-summary.json").read_text()))
```

The CLI prints only `UNIFIED_GT_ARTIFACTS_OK` on success.

- [ ] **Step 4: Run focused and full tests**

Run:

```bash
uv run pytest experiments/unified-gt-failure-audit-20260727/test_analyze.py \
  experiments/unified-gt-failure-audit-20260727/test_verify_artifacts.py -q
uv run python experiments/unified-gt-failure-audit-20260727/verify_artifacts.py \
  --root experiments/unified-gt-failure-audit-20260727
uv run pytest -q
git diff --check
```

Expected:

- focused: all PASS
- verifier: `UNIFIED_GT_ARTIFACTS_OK`
- full suite: 0 failed
- diff check: no output

- [ ] **Step 5: Write `REPORT.md`**

Required sections:

```markdown
# Unified GT Catalog · VLM/Evidence Failure Audit
## Verdict
## Exact source counts and eligibility
## Unique clips, episodes, camera-nights, overlap
## GT trust and canonical mapping loss
## Existing VLM/Evidence/Gate coverage
## Top failure causes
## Recommended next candidate
## What current data can and cannot prove
## Mutation 0
## Git HEAD/upstream/status
## Explicit non-actions
```

Report top causes with independent episodes, camera-nights, source strata, duplicate dominance,
care/highlight miss episodes, and addressable error mass. Do not convert addressable error mass into
promised accuracy improvement.

- [ ] **Step 6: Run independent review**

Review only the committed experiment directory against `DESIGN.md` and this plan. Required review
questions:

1. Did any automatic result become GT?
2. Was dataset203 presented as future holdout?
3. Were source row counts confused with unique clips?
4. Can one duplicate group dominate a qualified top cause?
5. Is the recommended candidate exactly one and supported by the top qualified cause?
6. Are any raw identifiers tracked?
7. Do start/end fingerprints prove mutation 0 for the declared table set?

Any Critical/Important finding must be fixed with a failing regression test before completion.

- [ ] **Step 7: Final verification and commit**

```bash
uv run pytest experiments/unified-gt-failure-audit-20260727 -q
uv run python experiments/unified-gt-failure-audit-20260727/verify_artifacts.py \
  --root experiments/unified-gt-failure-audit-20260727
uv run pytest -q
git diff --check
git status --short --branch
git add experiments/unified-gt-failure-audit-20260727
git commit -m "docs: 통합 GT 실패원인 감사 최종 보고"
git push
```

Expected: tests and verifier pass, push succeeds, local HEAD equals upstream, worktree clean.

---

## Completion Gate

완료 보고 전 아래를 모두 만족해야 한다.

- [ ] source별 exact eligible count와 제외 사유가 있음
- [ ] raw row count와 unique clip/episode/camera-night를 구분함
- [ ] source overlap과 과거 model exposure를 보고함
- [ ] T1/T2/T3/X가 분리됨
- [ ] VLM/Evidence/Gate coverage가 provenance별로 분리됨
- [ ] top cause qualification이 episode/camera-night/duplicate 조건을 만족함
- [ ] next candidate가 0개(HOLD) 또는 정확히 1개(READY)
- [ ] 시작/종료 fingerprint 동일
- [ ] tracked 민감 원시 데이터 0
- [ ] 전용 경로 밖 변경 0
- [ ] full test suite 0 failed
- [ ] HEAD == upstream, worktree clean

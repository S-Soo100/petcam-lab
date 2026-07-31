# RBA Event Grouping Shadow v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 약 2만 건의 닫힌 활동 클립에서 formal 보호 표본을 누출하지 않고 정확히 120개의 사건 경계 pair를 결정론적으로 생성한다.

**Architecture:** 기존 metadata-only accounting·scorer는 유지한다. SELECT-only runner의 보호 집합을 formal/canary·tutorial·frozen manifest로 좁히고, gap bin을 `<=30`, `30–60`, `60–300`으로 교체한다. selector는 최대 2,000개의 deterministic camera-night partition과 6개 bin 순서를 탐색해 canonical witness 하나를 고른다.

**Tech Stack:** Python 3.12, pytest, Supabase Python client, SHA-256 canonical JSON

## Global Constraints

- production DB는 SELECT-only다. insert/update/upsert/delete/RPC는 금지한다.
- 선택된 unique clip 240개에 R2 HEAD만 1회 수행한다. R2 GET, frame, Python Evidence, Gate,
  local/cloud VLM은 호출하지 않는다.
- 일반 live 행동 제출·세션·consensus의 정답 내용은 읽지 않는다.
- formal/canary slot, tutorial clip, 전달된 frozen manifest clip은 pair에서 제외한다.
- source cutoff는 `2026-07-31T03:44:27.183403+09:00`으로 유지한다.
- 출력은 private `0600`, no-overwrite, raw ID 비공개 계약을 유지한다.
- 자동 skip, 원본 삭제·병합, 서비스 변경은 금지한다.

---

### Task 1: v2 exposure와 gap 계약

**Files:**
- Modify: `tests/test_prepare_rba_event_grouping_shadow.py`
- Modify: `tests/test_run_rba_event_grouping_shadow.py`
- Modify: `scripts/prepare_rba_event_grouping_shadow.py`
- Modify: `scripts/run_rba_event_grouping_shadow.py`

**Interfaces:**
- Consumes: `motion_clips`, `motion_clip_system_exclusions`, `motion_clip_review_slots`, `labeling_tutorial_lessons`
- Produces: `load_select_snapshots()`, `protected_clip_ids()`, `build_adjacent_pairs()`의 v2 계약

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_v2_gap_bins_follow_capture_cadence() -> None:
    rows = (row("a", at=0, duration=10), row("b", at=40), row("c", at=90))
    pairs = build_adjacent_pairs(rows)
    assert [item.gap_bin for item in pairs] == ["le30", "30to60"]

def test_only_formal_and_tutorial_rows_are_protected() -> None:
    snapshots = {
        "motion_clip_review_slots": (
            {"id": "1", "clip_id": "live", "cohort_kind": "live"},
            {"id": "2", "clip_id": "formal", "cohort_kind": "canary"},
        ),
        "labeling_tutorial_lessons": ({"id": "3", "clip_id": "tutorial"},),
    }
    assert protected_clip_ids(snapshots) == {"formal", "tutorial"}

def test_unknown_cohort_kind_fails_closed() -> None:
    with pytest.raises(SafetyContractError, match="unknown_cohort_kind"):
        protected_clip_ids({"motion_clip_review_slots": ({"clip_id": "x", "cohort_kind": "future"},), "labeling_tutorial_lessons": ()})
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest tests/test_prepare_rba_event_grouping_shadow.py tests/test_run_rba_event_grouping_shadow.py -q`

Expected: old `le15/15to60` bin과 all-slot 보호 때문에 FAIL.

- [ ] **Step 3: 최소 구현**

```python
GAP_BINS = ("le30", "30to60", "60to300")

def _gap_bin(gap_sec: float) -> GapBin:
    if gap_sec <= 30:
        return "le30"
    if gap_sec <= 60:
        return "30to60"
    return "60to300"

def protected_clip_ids(snapshots: Mapping[str, Iterable[Mapping[str, object]]]) -> frozenset[str]:
    formal = {
        str(row["clip_id"])
        for row in snapshots["motion_clip_review_slots"]
        if row.get("cohort_kind") == "canary"
    }
    tutorial = {
        str(row["clip_id"])
        for row in snapshots["labeling_tutorial_lessons"]
    }
    return frozenset(formal | tutorial)
```

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest tests/test_prepare_rba_event_grouping_shadow.py tests/test_run_rba_event_grouping_shadow.py -q`

Expected: PASS.

### Task 2: bounded deterministic exact-120 selector

**Files:**
- Modify: `tests/test_prepare_rba_event_grouping_shadow.py`
- Modify: `scripts/prepare_rba_event_grouping_shadow.py`

**Interfaces:**
- Consumes: `tuple[BoundaryPair, ...]`, seed, `max_attempts=2000`
- Produces: `search_boundary_selection(...) -> tuple[FrozenSplit, tuple[BoundaryPair, ...]]`

- [ ] **Step 1: greedy false blocker와 결정론 테스트 작성**

```python
def test_bounded_search_finds_witness_after_first_partition_fails() -> None:
    pairs = false_greedy_population()
    split, selected = search_boundary_selection(pairs, "shadow-v2", max_attempts=2000)
    assert len(selected) == 120
    assert len(split.development_nights) == len(split.holdout_nights) == 6

def test_bounded_search_is_order_independent() -> None:
    pairs = false_greedy_population()
    assert search_boundary_selection(pairs, "shadow-v2") == search_boundary_selection(tuple(reversed(pairs)), "shadow-v2")
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest tests/test_prepare_rba_event_grouping_shadow.py -q`

Expected: `search_boundary_selection` import 부재로 FAIL.

- [ ] **Step 3: 최소 구현**

```python
def search_boundary_selection(pairs, seed, max_attempts=2000):
    witnesses = []
    for attempt in range(max_attempts):
        partition = _partition_for_attempt(tuple(pairs), seed, attempt)
        if partition is None:
            continue
        for order in permutations(GAP_BINS):
            try:
                selected = _select_partition(partition, order, seed)
            except BoundarySelectionBlocked:
                continue
            witnesses.append((_selection_digest(partition, selected), partition, selected))
    if not witnesses:
        raise BoundarySelectionBlocked(BLOCKED_SELECTOR_SEARCH_EXHAUSTED)
    _, split, selected = min(witnesses, key=lambda item: item[0])
    return split, selected
```

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest tests/test_prepare_rba_event_grouping_shadow.py -q`

Expected: PASS, exact 120, unique clip 240, split/camera caps 충족.

### Task 3: v2 artifact와 media 안전 계약

**Files:**
- Modify: `tests/test_run_rba_event_grouping_shadow.py`
- Modify: `scripts/run_rba_event_grouping_shadow.py`
- Modify: `scripts/prepare_rba_event_grouping_shadow.py`

**Interfaces:**
- Consumes: Task 1 snapshots, Task 2 selector
- Produces: schema/experiment v2 private manifest, R2 HEAD 240/240 attestation, blank worksheets,
  public aggregate summary

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_v2_runner_never_reads_behavior_answers() -> None:
    source = Path("scripts/run_rba_event_grouping_shadow.py").read_text().lower()
    for forbidden in ("initial_gt", "final_gt", "behavior_labels", "motion_clip_blind_submissions"):
        assert forbidden not in source

def test_v2_manifest_records_search_provenance() -> None:
    assert manifest["schema_version"] == "rba-event-boundary-manifest-v2"
    assert manifest["search"]["max_attempts"] == 2000
    assert len(manifest["splits"]["development"]) == 60
    assert len(manifest["splits"]["holdout"]) == 60

def test_media_preflight_fails_whole_run_without_partial_artifact() -> None:
    with pytest.raises(SafetyContractError, match="BLOCKED_MEDIA_PREFLIGHT_FAILED"):
        preflight_selected_media(selected_ids, r2_keys, failing_head_client, "bucket", b"salt")
    assert not output_dir.exists()
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest tests/test_run_rba_event_grouping_shadow.py -q`

Expected: v1 schema와 old selector 호출 때문에 FAIL.

- [ ] **Step 3: 최소 구현**

Runner가 `search_boundary_selection()`을 한 번 호출하고, 출력 전에 `verify_accounting()`과
exact-120 invariants를 검사한다. 선택된 240개의 key를 메모리에서만 R2 HEAD하고 하나라도
실패하면 output directory 생성 전 중단한다. 기존 `write_private_new()`의 `0600`·no-overwrite를
그대로 사용한다.

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest tests/test_rba_event_grouping_core.py tests/test_prepare_rba_event_grouping_shadow.py tests/test_run_rba_event_grouping_shadow.py tests/test_score_rba_event_grouping_shadow.py -q`

Expected: focused suite PASS.

### Task 4: Mac mini production SELECT-only one-shot

**Files:**
- Create on Mac mini only: private ignored output directory under `/Users/baek-end/petcam-lab/storage/experiments/`
- Modify after aggregate verification: `experiments/rba-event-grouping-shadow-v2/REPORT.md`
- Modify after aggregate verification: `specs/next-session.md`

**Interfaces:**
- Consumes: exact tracked code HEAD, Mac mini environment, existing frozen manifest paths
- Produces: private exact-120 manifest/worksheets and public aggregate audit only

- [ ] **Step 1: runtime preflight**

Run read-only checks for hostname, repo HEAD, git cleanliness, required env names, service state. Do not print env values.

- [ ] **Step 2: focused and full tests**

Run: `uv run pytest tests/test_rba_event_grouping_core.py tests/test_prepare_rba_event_grouping_shadow.py tests/test_run_rba_event_grouping_shadow.py tests/test_score_rba_event_grouping_shadow.py -q`

Run: `uv run pytest -q`

Expected: both exit 0.

- [ ] **Step 3: one-shot prepare**

Run the v2 `prepare` command once with `--as-of now`, explicit private output directory, and explicit frozen manifest paths. Expected public status: exact 120, dev/holdout 60/60, bins 20/20/20 per split, unique clip 240, R2 HEAD 240/240, DB writes 0.

- [ ] **Step 4: independent aggregate audit**

Read only the private artifact locally and output counts/hashes/fingerprints, never raw IDs, GT, keys, URLs, or reviewer identities. Confirm mode `0600`, no reuse, 12 disjoint camera-nights, camera caps, and three-run deterministic selector hash.

- [ ] **Step 5: final verification**

Run: `git diff --check`

Run: `git status --short --branch`

Expected: no whitespace errors; all changed/untracked files are intentional and reported. Do not commit without separate owner approval.

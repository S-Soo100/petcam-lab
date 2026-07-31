# RBA Event Media Eligibility v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fixed historical DB source와 실제 R2 객체의 교집합에서 exact 120 사건 경계 pair를 다시 선택하고 final HEAD 240/240일 때만 private artifact를 만든다.

**Architecture:** 새 순수 모듈 `scripts/rba_media_eligibility.py`가 DB key 일대일 계약, R2 LIST pagination, availability 집합과 provenance를 담당한다. 기존 event grouping selector/scorer는 유지하고 SELECT-only runner가 inventory diagnostic을 accounting에 합친 뒤 exact-120과 기존 final HEAD를 실행한다.

**Tech Stack:** Python 3.12, boto3 S3-compatible R2 client, pytest, 기존 Supabase SELECT runner

## Global Constraints

- source cutoff는 strict `started_at < 2026-07-31T03:44:27.183403+09:00`다.
- production DB는 SELECT only, R2는 LIST와 HEAD only다.
- R2 GET/write/delete, DB RPC/mutation, frame/model/Gate/Python Evidence/service 변경은 0이다.
- raw clip/camera/reviewer ID, R2 key/URL/ETag, GT 원문은 공개 출력하지 않는다.
- media inventory algorithm version은 `r2-list-intersection-v1`이다.
- exact-120과 final HEAD 240/240을 완화하지 않는다.
- TEST-SHEET와 iTerm 공식 AppleScript Claude 교차리뷰를 production run 전에 완료한다.

---

### Task 1: Pure R2 inventory contract

**Files:**
- Create: `scripts/rba_media_eligibility.py`
- Create: `tests/test_rba_media_eligibility.py`

**Interfaces:**
- Consumes: `motion_clips`의 `id,r2_key`, boto3-compatible `list_objects_v2`
- Produces: `MediaInventory`, `build_source_key_index`, `list_media_inventory`

- [ ] **Step 1: Write failing key-index tests**

```python
def test_source_key_index_separates_empty_and_duplicate_keys():
    index = build_source_key_index((
        {"id": "a", "r2_key": " motion/a.mp4 "},
        {"id": "b", "r2_key": None},
    ))
    assert index.key_to_clip_id == {"motion/a.mp4": "a"}
    assert index.missing_key_clip_ids == frozenset({"b"})

    duplicate = build_source_key_index((
        {"id": "a", "r2_key": "same.mp4"},
        {"id": "b", "r2_key": "same.mp4"},
    ))
    assert duplicate.key_to_clip_id == {}
    assert duplicate.duplicate_key_clip_ids == frozenset({"a", "b"})
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_rba_media_eligibility.py -q`
Expected: FAIL because `scripts.rba_media_eligibility` does not exist.

- [ ] **Step 3: Implement immutable source index**

```python
ALGORITHM_VERSION = "r2-list-intersection-v1"
BLOCKED_MEDIA_INVENTORY_FAILED = "BLOCKED_MEDIA_INVENTORY_FAILED"

@dataclass(frozen=True, slots=True)
class SourceKeyIndex:
    key_to_clip_id: Mapping[str, str]
    missing_key_clip_ids: frozenset[str]
    duplicate_key_clip_ids: frozenset[str]

def build_source_key_index(rows: Iterable[Mapping[str, object]]) -> SourceKeyIndex:
    key_to_clip: dict[str, str] = {}
    missing: set[str] = set()
    duplicate_ids: set[str] = set()
    duplicate_keys: set[str] = set()
    for row in rows:
        clip_id = str(row["id"])
        key = str(row.get("r2_key") or "").strip()
        if not key:
            missing.add(clip_id)
            continue
        if key in key_to_clip:
            duplicate_ids.update((key_to_clip.pop(key), clip_id))
            duplicate_keys.add(key)
            continue
        if key in duplicate_keys:
            duplicate_ids.add(clip_id)
            continue
        key_to_clip[key] = clip_id
    return SourceKeyIndex(
        MappingProxyType(key_to_clip),
        frozenset(missing),
        frozenset(duplicate_ids),
    )
```

- [ ] **Step 4: Add LIST pagination tests**

```python
def test_inventory_reads_all_pages_and_keeps_only_positive_matching_objects():
    index = build_source_key_index((
        {"id": "a", "r2_key": "motion/a.mp4"},
        {"id": "b", "r2_key": None},
        {"id": "c", "r2_key": "motion/c.mp4"},
    ))
    client = ListClient([
        {"ResponseMetadata": {"HTTPStatusCode": 200}, "Contents": [
            {"Key": "motion/a.mp4", "Size": 10},
            {"Key": "unrelated.mp4", "Size": 99},
        ], "KeyCount": 2, "IsTruncated": True, "NextContinuationToken": "next"},
        {"ResponseMetadata": {"HTTPStatusCode": 200}, "Contents": [
            {"Key": "motion/c.mp4", "Size": 0},
        ], "KeyCount": 1, "IsTruncated": False},
    ])
    result = list_media_inventory(client, bucket="bucket", source_index=index)
    assert result.available_clip_ids == frozenset({"a"})
    assert result.missing_key_clip_ids == frozenset({"b"})
    assert result.absent_object_clip_ids == frozenset({"c"})
    assert result.unavailable_clip_ids == frozenset({"b", "c"})
    assert result.page_count == 2
    assert client.tokens == [None, "next"]
```

- [ ] **Step 5: Verify schema/token/cycle failures RED**

Cover missing token, repeated token, non-200, `KeyCount=0` with omitted Contents, `KeyCount>0`
with missing/mismatched Contents, invalid `Size`, SDK exception, and `max_pages + 1`. Every error must
contain only `BLOCKED_MEDIA_INVENTORY_FAILED`, never a key.

Run: `uv run pytest tests/test_rba_media_eligibility.py -q`
Expected: FAIL because LIST inventory is missing.

- [ ] **Step 6: Implement bounded LIST inventory**

```python
@dataclass(frozen=True, slots=True)
class MediaInventory:
    available_clip_ids: frozenset[str]
    missing_key_clip_ids: frozenset[str]
    duplicate_key_clip_ids: frozenset[str]
    absent_object_clip_ids: frozenset[str]
    page_count: int
    started_at: datetime
    finished_at: datetime
    inventory_sha256: str

def list_media_inventory(client, *, bucket: str, source_index: SourceKeyIndex,
                         max_pages: int = 10_000) -> MediaInventory:
    token: str | None = None
    seen_tokens: set[str] = set()
    available: set[str] = set()
    started_at = datetime.now(UTC)
    for page_number in range(1, max_pages + 1):
        kwargs = {"Bucket": bucket}
        if token is not None:
            kwargs["ContinuationToken"] = token
        response = client.list_objects_v2(**kwargs)
        _validate_page(response)
        for row in _validated_contents(response):
            key, size = _validated_key_and_size(row)
            clip_id = source_index.key_to_clip_id.get(key)
            if clip_id is not None and size > 0:
                available.add(clip_id)
        if not response["IsTruncated"]:
            break
        token = _next_token(response, seen_tokens)
    else:
        raise MediaInventoryError(BLOCKED_MEDIA_INVENTORY_FAILED)
    absent = set(source_index.key_to_clip_id.values()) - available
    return _build_inventory(
        available=available,
        missing=source_index.missing_key_clip_ids,
        duplicate=source_index.duplicate_key_clip_ids,
        absent=absent,
        page_count=page_number,
        started_at=started_at,
    )
```

- [ ] **Step 7: Run GREEN**

Run: `uv run pytest tests/test_rba_media_eligibility.py -q`
Expected: all media eligibility unit tests pass.

---

### Task 2: Accounting integration without changing selector semantics

**Files:**
- Modify: `scripts/rba_media_eligibility.py`
- Modify: `tests/test_rba_media_eligibility.py`
- Modify: `scripts/run_rba_event_grouping_shadow.py`
- Modify: `tests/test_run_rba_event_grouping_shadow.py`

**Interfaces:**
- Consumes: existing `dict[str, ExclusionState]`, `MediaInventory`의 세 unavailable reason 집합
- Produces: `merge_media_integrity_exclusions` with distinct missing/duplicate/absent reasons

- [ ] **Step 1: Write failing precedence tests**

```python
def test_media_unavailable_becomes_diagnostic_without_overwriting_active_exclusion():
    merged = merge_media_integrity_exclusions(
        {"active": ExclusionState("active", "quarantined", "short", "v1")},
        missing_key_clip_ids=frozenset({"missing"}),
        duplicate_key_clip_ids=frozenset({"duplicate"}),
        absent_object_clip_ids=frozenset({"active", "restored"}),
    )
    assert merged["active"].reason_code == "short"
    assert merged["missing"].state == "media_deleted"
    assert merged["missing"].reason_code == "r2_key_missing"
    assert merged["duplicate"].reason_code == "r2_key_duplicate"
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_rba_media_eligibility.py -q`
Expected: FAIL because merge function is missing.

- [ ] **Step 3: Implement minimal merge**

Only keep an existing row when its state is in `ACTIVE_EXCLUSION_STATES`; otherwise add synthetic active
exclusions with `r2_key_missing`, `r2_key_duplicate`, or `r2_object_absent` and
`rule_version=ALGORITHM_VERSION`.

- [ ] **Step 4: Add runner ordering test**

Patch fake snapshots and R2 client. Assert `prepare_artifacts` performs LIST before selection, unavailable rows are `diagnostic_integrity`, selected IDs never intersect unavailable, and final `head_object` receives exactly 240 calls.

- [ ] **Step 5: Run RED then wire runner**

Runner order:

```python
snapshots = load_select_snapshots(client)
source_index = build_source_key_index(snapshots["motion_clips"])
inventory = list_media_inventory(r2_client, bucket=r2_bucket, source_index=source_index)
db_exclusions = _exclusion_rows(
    snapshots["motion_clip_system_exclusions"],
    {row.clip_id for row in source},
)
effective_exclusions = merge_media_integrity_exclusions(
    db_exclusions,
    missing_key_clip_ids=inventory.missing_key_clip_ids,
    duplicate_key_clip_ids=inventory.duplicate_key_clip_ids,
    absent_object_clip_ids=inventory.absent_object_clip_ids,
)
accounted = account_source_clips(source, effective_exclusions, protected)
```

- [ ] **Step 6: Run GREEN**

Run: `uv run pytest tests/test_rba_media_eligibility.py tests/test_run_rba_event_grouping_shadow.py -q`
Expected: all pass.

---

### Task 3: Frozen provenance and public-safe summary

**Files:**
- Modify: `scripts/prepare_rba_event_grouping_shadow.py`
- Modify: `scripts/run_rba_event_grouping_shadow.py`
- Modify: `tests/test_prepare_rba_event_grouping_shadow.py`
- Modify: `tests/test_run_rba_event_grouping_shadow.py`

**Interfaces:**
- Consumes: `MediaInventory`
- Produces: private `media_inventory` manifest block and aggregate summary

- [ ] **Step 1: Write failing manifest tests**

Assert pair and source manifests include the same:

```python
{
    "algorithm_version": "r2-list-intersection-v1",
    "page_count": 23,
    "available_count": 19000,
    "unavailable_count": 279,
    "inventory_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
}
```

Also assert JSON contains no `r2_key`, URL, raw inventory IDs, or ETag.

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_prepare_rba_event_grouping_shadow.py tests/test_run_rba_event_grouping_shadow.py -q`
Expected: FAIL because provenance block is absent.

- [ ] **Step 3: Add provenance before manifest hashing**

Add one stable `inventory.manifest_provenance()` block without wall-clock to both manifests before computing
`manifest_sha256`. Public command summary adds `inventory_started_at`, `inventory_finished_at`,
`r2_list_pages`, `media_available_count`, `media_unavailable_count`, `r2_head_calls=240`, `r2_get_calls=0`.

- [ ] **Step 4: Verify no artifact on LIST or final HEAD failure**

Use `tmp_path / "not-created"`; make LIST fail and separately make selected HEAD responses include 404,
403, invalid metadata, and transport error. Assert the blocker exposes category counts without keys and the
path does not exist in every case.

- [ ] **Step 5: Run GREEN**

Run: `uv run pytest tests/test_prepare_rba_event_grouping_shadow.py tests/test_run_rba_event_grouping_shadow.py -q`
Expected: all pass.

---

### Task 4: Cross-review and regression verification

**Files:**
- Modify: `docs/superpowers/specs/2026-07-31-rba-event-media-eligibility-v1-design.md`
- Modify: `experiments/rba-event-media-eligibility-v1/TEST-SHEET.md`
- Modify: `docs/superpowers/plans/2026-07-31-rba-event-media-eligibility-v1.md`
- Modify: `scripts/rba_media_eligibility.py`
- Modify: `scripts/run_rba_event_grouping_shadow.py`
- Modify: `tests/test_rba_media_eligibility.py`
- Modify: `tests/test_run_rba_event_grouping_shadow.py`

**Interfaces:**
- Consumes: frozen design/plan and git diff
- Produces: resolved review findings and verified implementation

- [ ] **Step 1: Send exact paths and diff to existing iTerm Claude Fable 5/high session**

Use only official iTerm AppleScript. Ask for P0/P1 review of LIST consistency, key privacy, pagination,
availability bias, final HEAD race, accounting precedence, and artifact fail-closed behavior. Adopt the six
2026-07-31 findings recorded in the design unless current code evidence contradicts one.

- [ ] **Step 2: Classify each finding**

Record `adopt / reject / defer` with technical reason in design and decision gate. TDD every adopted code change.

- [ ] **Step 3: Run focused and full suites**

Run:

```bash
uv run pytest tests/test_rba_media_eligibility.py tests/test_rba_event_grouping_core.py tests/test_prepare_rba_event_grouping_shadow.py tests/test_score_rba_event_grouping_shadow.py tests/test_run_rba_event_grouping_shadow.py -q
uv run pytest -q
git diff --check
```

Expected: focused pass, full pass with only established skips, diff check clean.

---

### Task 5: Mac mini one-shot and independent audit

**Files:**
- Create after run: `experiments/rba-event-media-eligibility-v1/REPORT.md`
- Modify after run: `specs/next-session.md`
- Modify after run: `docs/decision-gate.md`

**Interfaces:**
- Consumes: exact reviewed local files, Mac mini Supabase/R2 read credentials, frozen Blind30 manifest
- Produces: private exact-120 artifact or explicit blocker, aggregate public report

- [ ] **Step 1: Verify execution provenance**

Confirm Mac mini hostname, source file SHA-256 match, repo HEAD/dirty state, output path nonexistence,
private temp directory mode `0700`, and short-clip retention/deletion automation loaded·recent-run state.
Do not change the Mac mini production repo or service state.

- [ ] **Step 2: Run prepare once**

Execute from a private temporary overlay with `--as-of now`, explicit frozen manifest, and new output path. Never print secrets, IDs, keys, URLs, or GT.

- [ ] **Step 3: Audit aggregates independently**

Verify source/accounting totals, inventory available/unavailable, LIST pages, exact 120, 60/60, bin 20/20/20, unique 240, 12 disjoint camera-nights, camera caps, final HEAD 240/240, file modes/hashes, DB/R2/model/service call counts.

- [ ] **Step 4: Write final report and SOT status**

If successful, record `PREPARED_MEDIA_VERIFIED_AWAITING_HUMAN_CHANNEL`. If blocked, record the exact aggregate blocker and artifact count 0. Never call it production-ready or begin human assignment.

- [ ] **Step 5: Final verification**

Run relevant tests again after documentation, `git diff --check`, and `git status --short`. Report uncommitted state; commit/push requires separate owner approval.

# RBA Event Grouping Shadow v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not spawn subagents.

**Goal:** production을 변경하지 않고 `motion_clips` 전수를 metadata-only 사건으로 결정론적으로
묶고, 사람 boundary GT용 120 pair와 독립 scorer를 만드는 Phase 1 shadow harness를 구현한다.

**Architecture:** SELECT-only adapter가 닫힌 과거 activity day의 clip·system exclusion·formal
history를 private manifest로 동결한다. 순수 core가 전수 accounting과 gap 기반 event membership을
만들고, preparation 모듈이 camera-night 분리 120 pair를 선택한다. 별도 scorer가 development로
threshold를 고정한 뒤 frozen holdout을 한 번 평가한다. production DB/R2/app/service에는 쓰지 않는다.

**Tech Stack:** Python 3.12, stdlib `dataclasses/datetime/hashlib/json/csv/pathlib/stat`,
Supabase Python read client, pytest, uv

## Global Constraints

- SOT: `experiments/rba-event-grouping-shadow-v1/TEST-SHEET.md`
- source cutoff: `started_at < 2026-07-31T03:44:27.183403+09:00`
- algorithm version: `event-gap-metadata-v1`
- threshold candidates: `[0, 5, 15, 30, 60, 120]`
- exact boundary pairs: dev 60 + holdout 60, gap bin별 split당 20
- dev/holdout camera-night overlap 0, split별 cameras≥2와 camera-nights≥6
- target 기간의 모든 `motion_clips`는 `activity_candidate`, `diagnostic_integrity`,
  `blocked_research` 중 하나에 정확히 한 번 귀속
- Python Evidence, Gate, 행동 GT, VLM, consensus result를 import/query/input으로 사용하지 않음
- DB는 SELECT only. `.rpc/.insert/.update/.upsert/.delete` 호출과 production migration 0
- R2 GET/HEAD, model call, frame extraction, signed URL 저장 0
- formal/canary clip과 CLI로 전달한 frozen manifest clip은 표본·population 모두에서 제외
- private runtime artifact는 `storage/rba-event-grouping-shadow-v1/`, mode `0600`, overwrite 금지
- package/test command는 `uv run ...`; `pip` 금지
- implementation task는 `READY_FOR_HUMAN_BOUNDARY_GT`까지만. 사람 답을 생성·대행하지 않음
- commit은 task별 의도적 한글 conventional commit, force push 금지

---

## File Structure

| 파일 | 책임 |
|---|---|
| `scripts/rba_event_grouping_core.py` | 시간 정규화, 전수 accounting, gap 계산, event grouping, 안정 event ID |
| `scripts/prepare_rba_event_grouping_shadow.py` | camera-night split, adjacent-pair 표본 선택, private manifest/blank worksheet |
| `scripts/score_rba_event_grouping_shadow.py` | reviewer GT 검증, dev threshold 선택, frozen holdout 독립 채점 |
| `scripts/run_rba_event_grouping_shadow.py` | Supabase SELECT-only adapter와 prepare/group/score CLI |
| `tests/test_rba_event_grouping_core.py` | accounting·grouping·결정론 단위 테스트 |
| `tests/test_prepare_rba_event_grouping_shadow.py` | split·pair selection·privacy·mode 테스트 |
| `tests/test_score_rba_event_grouping_shadow.py` | GT·threshold·holdout·reject gate 테스트 |
| `tests/test_run_rba_event_grouping_shadow.py` | fake Supabase와 정적 mutation/import 금지 테스트 |
| `experiments/rba-event-grouping-shadow-v1/REPORT-TEMPLATE.md` | 실행 전후 보고 형식 |

---

### Task 1: 전수 accounting과 metadata-only event core

**Files:**
- Create: `scripts/rba_event_grouping_core.py`
- Create: `tests/test_rba_event_grouping_core.py`

**Interfaces:**
- Produces:
  - `SourceClip`
  - `ExclusionState`
  - `AccountedClip`
  - `EventGroup`
  - `parse_aware_datetime(value: str | datetime) -> datetime`
  - `activity_day_kst(started_at: datetime) -> date`
  - `account_source_clips(clips, exclusions, blocked_clip_ids) -> tuple[AccountedClip, ...]`
  - `group_activity_events(accounted, threshold_sec, algorithm_version=...) -> tuple[EventGroup, ...]`
  - `verify_accounting(source, accounted, events) -> None`
- Consumers: Tasks 2–4

- [ ] **Step 1: Write failing accounting tests**

```python
def test_accounting_assigns_every_source_exactly_once():
    clips = (
        clip("a", camera="cam-1", start="2026-07-20T12:00:00+00:00", duration=60),
        clip("b", camera="cam-1", start="2026-07-20T12:01:05+00:00", duration=60),
        clip("c", camera="cam-1", start="2026-07-20T12:02:10+00:00", duration=None),
    )
    accounted = account_source_clips(
        clips,
        exclusions={"b": exclusion("quarantined", "short_device_error")},
        blocked_clip_ids=frozenset(),
    )
    assert [row.clip_id for row in accounted] == ["a", "b", "c"]
    assert [row.kind for row in accounted] == [
        "activity_candidate",
        "diagnostic_integrity",
        "diagnostic_integrity",
    ]
    assert accounted[1].reason_code == "short_device_error:quarantined"
    assert accounted[2].reason_code == "invalid_duration"
```

```python
def test_blocked_formal_clip_is_not_silently_dropped():
    accounted = account_source_clips(
        (clip("a"),),
        exclusions={},
        blocked_clip_ids=frozenset({"a"}),
    )
    assert accounted[0].kind == "blocked_research"
    assert accounted[0].reason_code == "formal_or_frozen_manifest"
```

`blocked_research`는 population에 남아 accounting되지만 event·boundary pair에는 절대 들어가지
않는 세 번째 kind다. TEST-SHEET의 “formal clip 제외”와 “분모 누락 금지”를 동시에 만족시킨다.

- [ ] **Step 2: Run tests and confirm RED**

Run:

```bash
uv run pytest tests/test_rba_event_grouping_core.py -q
```

Expected: import failure for `scripts.rba_event_grouping_core`.

- [ ] **Step 3: Implement immutable records and accounting**

Implement these exact records:

```python
ALGORITHM_VERSION = "event-gap-metadata-v1"
KST = ZoneInfo("Asia/Seoul")

@dataclass(frozen=True, slots=True)
class SourceClip:
    clip_id: str
    camera_id: str
    started_at: datetime
    duration_sec: float | None

@dataclass(frozen=True, slots=True)
class ExclusionState:
    clip_id: str
    state: str
    reason_code: str
    rule_version: str

@dataclass(frozen=True, slots=True)
class AccountedClip:
    clip_id: str
    camera_id: str
    started_at: datetime
    activity_day_kst: date
    duration_sec: float | None
    kind: Literal["activity_candidate", "diagnostic_integrity", "blocked_research"]
    reason_code: str | None

@dataclass(frozen=True, slots=True)
class EventGroup:
    event_id: str
    algorithm_version: str
    camera_id: str
    activity_day_kst: date
    clip_ids: tuple[str, ...]
    started_at: datetime
    ended_at: datetime
```

Accounting rules:

```python
if clip.clip_id in blocked_clip_ids:
    kind, reason = "blocked_research", "formal_or_frozen_manifest"
elif active exclusion state in {"candidate", "quarantined", "media_deleted", "deletion_blocked"}:
    kind, reason = "diagnostic_integrity", f"{reason_code}:{state}"
elif duration is None/non-finite/<=0:
    kind, reason = "diagnostic_integrity", "invalid_duration"
else:
    kind, reason = "activity_candidate", None
```

Reject duplicate source IDs, exclusion rows pointing to unknown clips, naive timestamp, empty camera ID,
or source ordering ambiguity. Return rows sorted by
`(camera_id, activity_day_kst, started_at, clip_id)`.

- [ ] **Step 4: Write failing grouping and determinism tests**

Cover:

```python
def test_grouping_uses_end_to_start_gap_and_breaks_on_diagnostic():
    accounted = (
        activity("a", at=0, duration=60),
        activity("b", at=65, duration=60),       # gap 5, same event at threshold 5
        diagnostic("x", at=126),
        activity("c", at=127, duration=60),      # cannot bridge diagnostic
    )
    events = group_activity_events(accounted, threshold_sec=5)
    assert [event.clip_ids for event in events] == [("a", "b"), ("c",)]
```

```python
def test_grouping_is_order_independent_and_byte_stable():
    first = group_activity_events(accounted_rows(), threshold_sec=30)
    second = group_activity_events(tuple(reversed(accounted_rows())), threshold_sec=30)
    assert first == second
    assert canonical_json(first) == canonical_json(second)
```

Also test camera/day forced split, overlapping clip (`gap_sec < 0`) grouping, threshold boundary equality,
event ID changing when algorithm version or membership changes, and exact membership coverage.

- [ ] **Step 5: Implement grouping and verification**

Use:

```python
gap_sec = (next.started_at - (current.started_at + timedelta(seconds=current.duration_sec))).total_seconds()
same_event = (
    current.camera_id == next.camera_id
    and current.activity_day_kst == next.activity_day_kst
    and no_non_activity_row_between
    and gap_sec <= threshold_sec
)
```

Canonical ID input:

```python
payload = "\0".join(
    (algorithm_version, camera_id, activity_day.isoformat(), *ordered_clip_ids)
)
event_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

`verify_accounting` must raise `EventGroupingContractError` unless:

- source/accounted clip ID set equal
- each source ID occurs once in accounted
- every `activity_candidate` occurs in exactly one event
- diagnostic/blocked IDs occur in zero events
- no event crosses camera/day

- [ ] **Step 6: Run Task 1 tests**

Run:

```bash
uv run pytest tests/test_rba_event_grouping_core.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add scripts/rba_event_grouping_core.py tests/test_rba_event_grouping_core.py
git commit -m "feat: 사건 묶기 metadata core 추가"
```

---

### Task 2: Frozen camera-night split과 boundary pair manifest

**Files:**
- Create: `scripts/prepare_rba_event_grouping_shadow.py`
- Create: `tests/test_prepare_rba_event_grouping_shadow.py`

**Interfaces:**
- Consumes: Task 1 `AccountedClip`
- Produces:
  - `BoundaryPair`
  - `FrozenSplit`
  - `build_adjacent_pairs(accounted) -> tuple[BoundaryPair, ...]`
  - `split_camera_nights(pairs, seed) -> FrozenSplit`
  - `select_boundary_pairs(split, seed) -> tuple[BoundaryPair, ...]`
  - `build_private_manifest(...) -> dict[str, object]`
  - `write_private_new(path, payload) -> str`

- [ ] **Step 1: Write failing pair-definition tests**

`BoundaryPair` fields:

```python
@dataclass(frozen=True, slots=True)
class BoundaryPair:
    pair_id: str
    left_clip_id: str
    right_clip_id: str
    camera_id: str
    activity_day_kst: date
    gap_sec: float
    gap_bin: Literal["le15", "15to60", "60to300"]
```

Tests must show:

- only immediate adjacent `activity_candidate` clips become pairs
- diagnostic/blocked rows break adjacency
- `gap_sec > 300` is not a GT candidate
- pair ID is stable SHA-256 of seed/camera/day/left/right
- a clip cannot appear in two selected pairs

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/test_prepare_rba_event_grouping_shadow.py -q
```

Expected: module import failure.

- [ ] **Step 3: Implement deterministic split and selection**

Camera-night key is `(camera_id, activity_day_kst)`.

Split algorithm:

1. collect nights having at least one candidate pair in every required gap bin
2. reject if total nights <12 or distinct cameras <2
3. for each camera ordered by stable hash, reserve its first eligible night for dev and second for holdout
4. order remaining nights by `sha256(seed + camera + day)` and fill the split with fewer nights until both
   have exactly six; tie alternates dev then holdout
5. reject camera-night overlap or split camera count <2

Within each split/bin:

1. sort pair candidates by stable hash
2. greedily take pair only if neither clip was already selected
3. cap one camera at 14 of the 20 bin pairs
4. stop at exactly 20; otherwise raise `BLOCKED_INSUFFICIENT_BOUNDARY_PAIRS`

After selecting exact 120, validate split total, bin counts, no shared clip, dev/holdout camera-night
disjointness, split camera share ≤60%, bin camera share ≤70%.

- [ ] **Step 4: Implement answer-free private manifest and worksheets**

Manifest must contain:

```json
{
  "schema_version": "rba-event-boundary-manifest-v1",
  "experiment_id": "rba-event-grouping-shadow-v1",
  "selection_seed": "rba-event-grouping-shadow-v1",
  "source_cutoff": "2026-07-31T03:44:27.183403+09:00",
  "source_snapshot_sha256": "...",
  "blocked_set_sha256": "...",
  "splits": {"development": [...], "holdout": [...]},
  "manifest_sha256": "..."
}
```

Private pair rows may contain raw clip/camera IDs but must not contain `r2_key`, URL, owner/reviewer ID,
behavior label, VLM/Gate/Python Evidence, consensus, or GT. Blank reviewer worksheet rows contain only
`pair_id`, `decision=null`, `reason=null`.

`write_private_new`:

```python
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
fd = os.open(path, flags, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fh.write("\n")
```

Never overwrite. Compute SHA-256 from exact bytes after fsync.

- [ ] **Step 5: Test privacy, mode, no overwrite, byte determinism**

Tests must assert:

- exact 120 and all diversity caps
- input reversal produces byte-identical manifest
- tracked/public summary contains only salted 12–16 hex fingerprints
- raw `r2_key`, email, UUID field names outside private manifest do not exist
- mode is `0600`
- second write to same path raises `FileExistsError`

- [ ] **Step 6: Run Task 2 tests and commit**

```bash
uv run pytest tests/test_prepare_rba_event_grouping_shadow.py -q
git add scripts/prepare_rba_event_grouping_shadow.py tests/test_prepare_rba_event_grouping_shadow.py
git commit -m "feat: 사건 경계 pair manifest 동결"
```

---

### Task 3: Reviewer GT validator와 independent scorer

**Files:**
- Create: `scripts/score_rba_event_grouping_shadow.py`
- Create: `tests/test_score_rba_event_grouping_shadow.py`

**Interfaces:**
- Consumes: private manifest, reviewer A/B JSONL, owner adjudication JSONL
- Produces:
  - `BoundaryDecision = Literal["same_event", "different_event", "uncertain"]`
  - `validate_reviewer_rows(...)`
  - `finalize_boundary_gt(...)`
  - `choose_development_threshold(...) -> int`
  - `score_frozen_holdout(...) -> ScoreSummary`
  - CLI exit `0=ADOPT`, `2=HOLD`, `3=REJECT_INTEGRITY_OR_SAFETY`

- [ ] **Step 1: Write failing GT integrity tests**

Cover:

- each reviewer has exact 120 unique pair IDs
- no unexpected/missing ID
- allowed decisions only
- reviewer files immutable input and different reviewer fingerprints
- disagreements and any reviewer `uncertain` require exact owner adjudication row
- owner cannot adjudicate an already identical non-uncertain pair
- finalized unresolved count 0
- manifest hash and file SHA mismatch reject

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/test_score_rba_event_grouping_shadow.py -q
```

Expected: import failure.

- [ ] **Step 3: Implement GT finalization**

Final decision:

```python
if a == b and a != "uncertain":
    final = a
else:
    final = owner_by_pair[pair_id]
```

Raw 3-class reviewer agreement:

```python
agreement = sum(a[p] == b[p] for p in pair_ids) / len(pair_ids)
```

Reject invalid fingerprints, duplicate pair IDs, free-text longer than 200 chars, raw clip IDs in
reviewer/adjudication rows, and missing provenance hashes.

- [ ] **Step 4: Implement dev threshold selection**

For each candidate `[0, 5, 15, 30, 60, 120]`:

```python
predicted_same = pair.gap_sec <= threshold
over_merge = final == "different_event" and predicted_same
over_split = final == "same_event" and not predicted_same
```

Exclude final `uncertain` from both error denominators.

Choose among candidates with `over_merge_count == 0` using:

```text
(over_split_count, threshold_sec)
```

ascending. If none exists, verdict is REJECT. Store chosen threshold and development GT SHA in a new
freeze record written with `O_EXCL`/`0600`.

- [ ] **Step 5: Implement one-time holdout scoring**

The scorer must require the freeze record before reading holdout GT. It writes result with `O_EXCL`; second
holdout scoring attempt fails.

Calculate:

- integrity counts from core verification
- reviewer agreement and final uncertain rate
- overall/camera over-merge counts
- overall/camera over-split rates
- activity event reduction on full accounting population
- 3-run byte identity hashes supplied by the runner

Verdict order:

1. any TEST-SHEET REJECT condition → `REJECT`
2. exact denominators/diversity/GT quality insufficient → `HOLD`
3. safety passes but reduction <15% → `HOLD`
4. all gates pass → `ADOPT_SHADOW_GROUPING_V1`

- [ ] **Step 6: Add adversarial tests**

At minimum:

- one holdout over-merge → REJECT
- one unassigned clip → REJECT
- one rerun hash mismatch → REJECT
- overall pass but one camera over-split 31% → REJECT
- uncertainty 26% → HOLD
- reduction 14.9% → HOLD
- second holdout open → integrity failure
- holdout threshold differing from freeze → integrity failure
- dev/holdout camera-night leak → integrity failure

- [ ] **Step 7: Run Task 3 tests and commit**

```bash
uv run pytest tests/test_score_rba_event_grouping_shadow.py -q
git add scripts/score_rba_event_grouping_shadow.py tests/test_score_rba_event_grouping_shadow.py
git commit -m "feat: 사건 경계 GT scorer 추가"
```

---

### Task 4: Production SELECT-only adapter와 CLI

**Files:**
- Create: `scripts/run_rba_event_grouping_shadow.py`
- Create: `tests/test_run_rba_event_grouping_shadow.py`

**Interfaces:**
- Consumes: Tasks 1–3
- Produces CLI:

```text
prepare --as-of now --out-dir storage/rba-event-grouping-shadow-v1 --blocked-manifest PATH...
group --manifest PATH --threshold SECONDS --out PATH
score-dev --manifest ... --reviewer-a ... --reviewer-b ... --owner ... --freeze-out ...
score-holdout --manifest ... --freeze ... --holdout-gt ... --out ...
```

- [ ] **Step 1: Write failing static safety tests**

Read source text and assert these tokens are absent:

```python
forbidden = (
    ".insert(", ".update(", ".upsert(", ".delete(", ".rpc(",
    "clip_python_evidence", "clip_prelabels", "activity_assessment",
    "gate", "behavior_logs", "behavior_labels", "clip_vlm_jobs",
    "boto3", "r2_key", "signed_url",
)
```

Allow only these table literals:

```python
{
  "motion_clips",
  "motion_clip_system_exclusions",
  "motion_clip_review_slots",
}
```

- [ ] **Step 2: Write fake Supabase pagination tests**

The adapter queries:

```python
motion_clips:
  select("id,camera_id,started_at,duration_sec")
  .lt("started_at", SOURCE_CUTOFF)

motion_clip_system_exclusions:
  select("clip_id,state,reason_code,rule_version")

motion_clip_review_slots:
  select("clip_id,cohort_kind")
  .eq("cohort_kind", "canary")
```

Use `.range(start, end)` pagination with page size 1000, detect duplicate IDs across pages, and snapshot
all rows before pure processing. No count-only shortcut may define the denominator.

- [ ] **Step 3: Implement blocked manifest loader**

`--blocked-manifest` is repeatable and required at least once. Accept JSON/JSONL/CSV. Extract UUID-shaped
values only from fields named `clip_id`, `clip_ids`, `clips`, `selected`, or `durable_key`; hash the
canonical blocked set. Reject missing files, parse errors, symlinks escaping the repo/storage roots, or
empty configured set.

Union this set with all canary slot clip IDs. Pre-cutoff plus canary union makes Blind30 v2 overlap
structurally zero.

- [ ] **Step 4: Implement prepare/group CLI**

`prepare`:

1. `--as-of now`를 process 시작 시 timezone-aware UTC 시각 하나로 고정하거나, timezone-aware
   ISO-8601 값을 받는다
2. require `as_of >= SOURCE_CUTOFF`
3. load three SELECT snapshots
4. derive activity day and retain only closed days
5. deterministically choose 12 camera-nights and exact 120 pairs
6. write source manifest, pair manifest, two blank reviewer worksheets, empty owner worksheet
7. print only aggregate counts, hashes, salted camera fingerprints, output paths

`group`:

1. verify manifest hash
2. run selected threshold three times in fresh function calls
3. require byte-identical membership/summary
4. write one private event membership artifact

Never print raw clip/camera IDs.

- [ ] **Step 5: Add runtime host and mutation-baseline guards**

The CLI does not require Mac mini for unit tests, but actual preparation requires:

```text
EXPECTED_HOST=baeg-endeuui-Macmini.local
```

Before and after prepare, record read-only counts for the three source tables. Count drift from concurrent
production inserts is reported, not treated as mutation by this process. The runner itself records
`write_methods_called=0`, `rpc_called=0`, `r2_calls=0`, `model_calls=0`.

Do not install a LaunchAgent or touch `com.petcam.research-runtime`.

- [ ] **Step 6: Run Task 4 tests and static scan**

```bash
uv run pytest tests/test_run_rba_event_grouping_shadow.py -q
rg -n '\\.(insert|update|upsert|delete|rpc)\\(' scripts/run_rba_event_grouping_shadow.py
rg -n 'clip_python_evidence|clip_prelabels|behavior_logs|clip_vlm_jobs|boto3|r2_key|signed_url' \
  scripts/rba_event_grouping_core.py \
  scripts/prepare_rba_event_grouping_shadow.py \
  scripts/score_rba_event_grouping_shadow.py \
  scripts/run_rba_event_grouping_shadow.py
```

Expected: pytest PASS, both `rg` commands return no matches.

- [ ] **Step 7: Commit Task 4**

```bash
git add scripts/run_rba_event_grouping_shadow.py tests/test_run_rba_event_grouping_shadow.py
git commit -m "feat: 사건 묶기 read-only runner 추가"
```

---

### Task 5: 통합 검증, report template, Mac mini dry run

**Files:**
- Create: `experiments/rba-event-grouping-shadow-v1/REPORT-TEMPLATE.md`
- Modify: `experiments/rba-event-grouping-shadow-v1/TEST-SHEET.md`
- Modify: `docs/superpowers/specs/2026-07-31-rba-event-first-total-coverage-design.md`
- Modify: `specs/next-session.md`

**Interfaces:**
- Consumes: all previous tasks
- Produces: `READY_FOR_HUMAN_BOUNDARY_GT` report

- [ ] **Step 1: Create report template**

Required headings:

```markdown
# RBA 사건 묶기 shadow v1 보고서

## 상태
## Exact source and code provenance
## Production read-only preflight
## Accounting population
## Boundary-pair manifest
## Three-run determinism
## Mutation and forbidden-input audit
## Human GT status
## Deviations
## Verdict
```

Before human review, verdict must be exactly `READY_FOR_HUMAN_BOUNDARY_GT` or a `BLOCKED_*` reason. It
must not claim `ADOPT_SHADOW_GROUPING_V1`.

- [ ] **Step 2: Run focused and full tests**

```bash
uv run pytest \
  tests/test_rba_event_grouping_core.py \
  tests/test_prepare_rba_event_grouping_shadow.py \
  tests/test_score_rba_event_grouping_shadow.py \
  tests/test_run_rba_event_grouping_shadow.py -q
uv run pytest -q
git diff --check
```

Expected: all PASS, diff check clean.

- [ ] **Step 3: Independent contract audit**

Run a separate process that imports only JSON artifacts, not the preparation module, and checks:

- source/accounting set equality
- exact 120 pairs and bin/split counts
- no clip reuse
- camera-night isolation
- no formal/blocked overlap
- artifact modes `0600`
- three-run hashes identical

Store only aggregate `summary.json` under private storage. Record its SHA-256 in the report.

- [ ] **Step 4: Execute Mac mini prepare dry run**

Preconditions:

- exact handoff validator `HANDOFF_OK`
- dedicated clean worktree
- host exact `baeg-endeuui-Macmini.local`
- `com.petcam.research-runtime` not modified
- source cutoff/frozen blocked manifests present

Run:

```bash
uv run python scripts/run_rba_event_grouping_shadow.py prepare \
  --as-of now \
  --out-dir storage/rba-event-grouping-shadow-v1 \
  --blocked-manifest experiments/activity-safety-holdout-0714/review_manifest.csv \
  --blocked-manifest experiments/activity-preflight-0714/review_manifest.csv \
  --blocked-manifest experiments/activity-preflight-0714/absent_v1_manifest.csv
```

DB `motion_clip_review_slots`의 모든 live/canary 이력도 별도로 전수 차단한다. 위 세 tracked
manifest 외에 receiver preflight가 발견한 정본 frozen manifest가 있으면 같은 옵션으로
추가하고 보고서에 경로와 hash를 남긴다. exact 120/diversity를 만들 수 없으면
`BLOCKED_INSUFFICIENT_BOUNDARY_PAIRS`로 멈춘다. bins, dates, cameras, cutoff, blocked set을
완화하지 않는다.

- [ ] **Step 5: Run zero-threshold grouping three times**

Before human GT, only the baseline threshold `0` is allowed:

```bash
uv run python scripts/run_rba_event_grouping_shadow.py group \
  --manifest storage/rba-event-grouping-shadow-v1/source-manifest.json \
  --threshold 0 \
  --out storage/rba-event-grouping-shadow-v1/events-threshold-0.json
```

This proves plumbing/determinism only. Do not choose the adoption threshold until dev GT exists.

- [ ] **Step 6: Update docs with exact evidence**

Record:

- implementation HEAD/upstream/clean
- source snapshot time and aggregate counts
- exact 120 readiness or blocked reason
- 3-run hashes
- DB/R2/model/service write counts all zero
- human GT files still blank
- next action: two blind reviewer worksheets, then owner adjudication

- [ ] **Step 7: Run verification-before-completion**

Re-run:

```bash
uv run pytest -q
git diff --check
git status --short
```

Check that production DB/R2/Vercel/service mutation is 0 and no raw identifier entered tracked artifacts.

- [ ] **Step 8: Commit report/docs and non-force push**

```bash
git add \
  experiments/rba-event-grouping-shadow-v1/REPORT-TEMPLATE.md \
  experiments/rba-event-grouping-shadow-v1/TEST-SHEET.md \
  docs/superpowers/specs/2026-07-31-rba-event-first-total-coverage-design.md \
  specs/next-session.md
git commit -m "docs: 사건 묶기 shadow 실행 증거 기록"
git push -u origin codex/rba-event-grouping-shadow-v1
```

Final state must be one of:

- `READY_FOR_HUMAN_BOUNDARY_GT`
- `BLOCKED_INSUFFICIENT_BOUNDARY_PAIRS`
- `REJECT_INTEGRITY`

Do not deploy, merge main, apply migrations, start a worker, or run a model.

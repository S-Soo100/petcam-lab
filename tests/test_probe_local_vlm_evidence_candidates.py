"""Gate B1 Task 2 — Local VLM 후보 가용성 SELECT probe 테스트.

DB 는 fake Supabase client 로 대체한다. 검증 포인트:
- 명시적 range pagination ((0,999),(1000,1999) ...) 로 1000+ 행을 읽는다.
- SELECT 전용 — insert/update/upsert/delete/rpc 는 절대 호출하지 않는다.
- clip 당 정확히 1개 evidence run(schema/algo/level0 계약)만 고른다. 0=missing_evidence 제외,
  2=AMBIGUOUS_EVIDENCE fail-closed.
- 후보 정본은 motion_clips 다. camera_clips 는 조회하지 않는다. duration<=0·blank r2_key=not_playable.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.probe_local_vlm_evidence_candidates import (
    REQUIRED_ALGO,
    REQUIRED_SCHEMA,
    AmbiguousEvidenceError,
    build_availability,
    load_sources,
)
from scripts.local_vlm_evidence_candidates import STRATA, SourceRow


# ---------------------------------------------------------------------------
# fake Supabase client (SELECT-only recorder)
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    _MUTATIONS = ("insert", "update", "upsert", "delete")

    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.client.selected_tables.add(table)
        self._filters = []
        self._order = None
        self._range = None

    def select(self, columns):
        self.client.calls.append(("select", self.table_name))
        self._columns = columns
        return self

    def order(self, column):
        self._order = column
        return self

    def range(self, lo, hi):
        self.client.range_calls.setdefault(self.table_name, []).append((lo, hi))
        self._range = (lo, hi)
        return self

    def in_(self, column, values):
        self._filters.append(("in", column, list(values)))
        return self

    def eq(self, column, value):
        self._filters.append(("eq", column, value))
        return self

    def execute(self):
        rows = list(self.client.data.get(self.table_name, []))
        for op, col, val in self._filters:
            if op == "in":
                allowed = set(val)
                rows = [r for r in rows if r.get(col) in allowed]
            elif op == "eq":
                rows = [r for r in rows if r.get(col) == val]
        if self._order is not None:
            rows = sorted(rows, key=lambda r: (r.get(self._order) is None, r.get(self._order)))
        if self._range is not None:
            lo, hi = self._range
            rows = rows[lo : hi + 1]
        return _Resp(rows)

    def _forbidden(self, name):
        self.client.forbidden.append((name, self.table_name))
        raise AssertionError(f"mutation {name} called on {self.table_name}")

    def insert(self, *a, **k):
        self._forbidden("insert")

    def update(self, *a, **k):
        self._forbidden("update")

    def upsert(self, *a, **k):
        self._forbidden("upsert")

    def delete(self, *a, **k):
        self._forbidden("delete")


class FakeClient:
    def __init__(self, data):
        self.data = data
        self.calls = []
        self.range_calls = {}
        self.selected_tables = set()
        self.forbidden = []

    def table(self, name):
        return _Query(self, name)

    def rpc(self, *a, **k):
        self.forbidden.append(("rpc", None))
        raise AssertionError("rpc called")


def _run(clip_id, **over):
    base = dict(
        id=f"run-{clip_id}",
        clip_id=clip_id,
        prelabel_id=f"pre-{clip_id}",
        evidence_schema_version=REQUIRED_SCHEMA,
        algorithm_version=REQUIRED_ALGO,
        level0_status="ok",
        level1_status="ok",
        frames_sampled=6,
        global_motion_series=[{"t": 0.0, "value": 0.3}],
        roi_motion_series=[{"t": 0.0, "value": 0.3}],
        motion_excursions=[],
        created_at="2026-07-20T10:00:00Z",
    )
    base.update(over)
    return base


def _motion(clip_id, **over):
    base = dict(
        id=clip_id,
        camera_id="cam-1",
        started_at="2026-07-20T10:00:00Z",
        duration_sec=60.0,
        r2_key=f"clips/{clip_id}.mp4",
    )
    base.update(over)
    return base


def _prelabel(clip_id, **over):
    base = dict(
        id=f"pre-{clip_id}",
        clip_id=clip_id,
        gecko_visible=True,
        visibility_confidence=0.9,
        frames_sampled=6,
    )
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# pagination + SELECT-only
# ---------------------------------------------------------------------------
def test_pagination_uses_explicit_ranges_over_1000_rows():
    runs = [_run(f"c{i:05d}", id=f"run{i:05d}") for i in range(1205)]
    motion = [_motion(f"c{i:05d}") for i in range(1205)]
    prelabels = [_prelabel(f"c{i:05d}") for i in range(1205)]
    client = FakeClient({
        "clip_python_evidence_runs": runs,
        "motion_clips": motion,
        "clip_prelabels": prelabels,
        "clip_activity_assessments": [],
        "clip_labeling_sessions": [],
        "behavior_logs": [],
    })

    rows = load_sources(client)

    assert client.range_calls["clip_python_evidence_runs"] == [(0, 999), (1000, 1999)]
    assert client.forbidden == []
    assert len(rows) == 1205
    assert all(isinstance(r, SourceRow) for r in rows)


def test_probe_never_touches_camera_clips_or_model_tables():
    client = FakeClient({
        "clip_python_evidence_runs": [_run("c1")],
        "motion_clips": [_motion("c1")],
        "clip_prelabels": [_prelabel("c1")],
        "clip_activity_assessments": [],
        "clip_labeling_sessions": [],
        "behavior_logs": [],
    })
    load_sources(client)
    assert "camera_clips" not in client.selected_tables
    assert "clip_vlm_jobs" not in client.selected_tables
    assert client.forbidden == []


# ---------------------------------------------------------------------------
# evidence run selection contract
# ---------------------------------------------------------------------------
def test_single_matching_run_is_selected():
    runs = [
        _run("c1", id="r-ok"),
        _run("c1", id="r-wrongschema", evidence_schema_version="python-evidence-raw-v0"),
        _run("c1", id="r-notok", level0_status="no_decodable_frames"),
    ]
    client = FakeClient({
        "clip_python_evidence_runs": runs,
        "motion_clips": [_motion("c1")],
        "clip_prelabels": [_prelabel("c1")],
        "clip_activity_assessments": [],
        "clip_labeling_sessions": [],
        "behavior_logs": [],
    })
    rows = load_sources(client)
    assert len(rows) == 1
    assert rows[0].run_id == "r-ok"


def test_zero_matching_runs_excluded_missing_evidence():
    runs = [_run("c1", level0_status="no_decodable_frames")]
    client = FakeClient({
        "clip_python_evidence_runs": runs,
        "motion_clips": [_motion("c1")],
        "clip_prelabels": [_prelabel("c1")],
        "clip_activity_assessments": [],
        "clip_labeling_sessions": [],
        "behavior_logs": [],
    })
    rows = load_sources(client)
    assert rows == []


def test_two_matching_runs_fail_ambiguous():
    runs = [_run("c1", id="r1"), _run("c1", id="r2")]  # same required identity
    client = FakeClient({
        "clip_python_evidence_runs": runs,
        "motion_clips": [_motion("c1")],
        "clip_prelabels": [_prelabel("c1")],
        "clip_activity_assessments": [],
        "clip_labeling_sessions": [],
        "behavior_logs": [],
    })
    with pytest.raises(AmbiguousEvidenceError):
        load_sources(client)


# ---------------------------------------------------------------------------
# source boundary + playability
# ---------------------------------------------------------------------------
def test_clip_loaded_from_motion_clips_not_camera_clips():
    # camera_clips has a row with the SAME id but must be ignored
    client = FakeClient({
        "clip_python_evidence_runs": [_run("shared-id")],
        "motion_clips": [_motion("shared-id", camera_id="motion-cam")],
        "camera_clips": [{"id": "shared-id", "camera_id": "labeling-cam",
                          "started_at": "2020-01-01T00:00:00Z", "duration_sec": 1.0, "r2_key": "x"}],
        "clip_prelabels": [_prelabel("shared-id")],
        "clip_activity_assessments": [],
        "clip_labeling_sessions": [],
        "behavior_logs": [],
    })
    rows = load_sources(client)
    assert len(rows) == 1
    assert rows[0].camera_id == "motion-cam"
    assert "camera_clips" not in client.selected_tables


@pytest.mark.parametrize(
    "motion_over",
    [
        {"r2_key": None},
        {"r2_key": ""},
        {"r2_key": "   "},
        {"duration_sec": 0},
        {"duration_sec": -5},
    ],
)
def test_not_playable_rows_excluded(motion_over):
    client = FakeClient({
        "clip_python_evidence_runs": [_run("c1")],
        "motion_clips": [_motion("c1", **motion_over)],
        "clip_prelabels": [_prelabel("c1")],
        "clip_activity_assessments": [],
        "clip_labeling_sessions": [],
        "behavior_logs": [],
    })
    rows = load_sources(client)
    assert rows == []


def test_r2_key_never_stored_on_source_row():
    client = FakeClient({
        "clip_python_evidence_runs": [_run("c1")],
        "motion_clips": [_motion("c1", r2_key="clips/secret.mp4")],
        "clip_prelabels": [_prelabel("c1")],
        "clip_activity_assessments": [],
        "clip_labeling_sessions": [],
        "behavior_logs": [],
    })
    rows = load_sources(client)
    assert not hasattr(rows[0], "r2_key")
    # SourceRow field set must not include r2_key / prediction / reasoning
    assert "r2_key" not in SourceRow.__slots__
    assert "prediction" not in SourceRow.__slots__


# ---------------------------------------------------------------------------
# build_availability verdict thresholds (synthetic SourceRows)
# ---------------------------------------------------------------------------
def _sr(clip_id, camera_id, day, **over):
    base = dict(
        clip_id=clip_id,
        camera_id=camera_id,
        captured_at=datetime(2026, 7, day, 10, 0, tzinfo=timezone.utc),
        duration_sec=60.0,
        run_id=f"run-{clip_id}",
        assessment_id=None,
        prelabel_id=None,
        activity_decision="exclude_absent",
        gecko_visible=False,
        visibility_confidence=0.5,
        frames_sampled=6,
        level0_status="ok",
        level1_status="ok",
        global_motion_series=(0.0,),
        roi_motion_series=(0.0,),
        excursion_count=0,
        human_actions=frozenset(),
        current_gt=None,
    )
    base.update(over)
    return SourceRow(**base)


def test_verdict_thresholds_and_no_manifest_when_insufficient():
    # 50 absent episodes (distinct cameras -> 50 distinct episodes), 3 days -> DATA_AVAILABLE
    rows = []
    for i in range(50):
        day = 20 + (i % 3)
        rows.append(_sr(f"a{i:03d}", f"cam{i}", day,
                        captured_at=datetime(2026, 7, day, i % 24, (i * 7) % 60, tzinfo=timezone.utc)))
    result = build_availability(rows)
    absent = next(s for s in result.strata if s.stratum == "absent")
    assert absent.episode_count >= 45
    assert absent.verdict == "DATA_AVAILABLE"
    # a stratum with zero candidates is BLOCKED
    big = next(s for s in result.strata if s.stratum == "big_move")
    assert big.episode_count == 0
    assert big.verdict == "BLOCKED_DATA_INSUFFICIENT"
    assert result.manifest_emitted is False
    assert result.manifest is None
    # pool sha is a stable 64-hex string
    assert len(result.pool_sha256) == 64
    assert set(s.stratum for s in result.strata) == set(STRATA)


def test_excluded_counts_distinguishes_dedup_from_unclassified():
    rows = [
        # two absent clips on camA 5 min apart -> ONE episode (one absorbed by dedup)
        _sr("d0", "camA", 20, captured_at=datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)),
        _sr("d1", "camA", 20, captured_at=datetime(2026, 7, 20, 10, 5, tzinfo=timezone.utc)),
        # an unclassifiable clip (no stratum signal at all)
        _sr("u0", "camB", 21, activity_decision="pending", gecko_visible=None,
            excursion_count=0, global_motion_series=(0.0,), roi_motion_series=(0.0,)),
    ]
    result = build_availability(rows)
    assert result.excluded_counts["unclassified_clips"] == 1
    assert result.excluded_counts["episode_deduped_clips"] == 1
    assert result.total_episodes == 1
    assert result.per_clip_stratum_distribution.get("unclassified") == 1
    assert result.per_clip_stratum_distribution.get("absent") == 2


def test_build_availability_is_order_invariant():
    import random
    rows = []
    for i in range(40):
        rows.append(_sr(f"a{i:03d}", f"cam{i % 4}", 20 + (i % 4),
                        captured_at=datetime(2026, 7, 20 + (i % 4), i % 24, (i * 11) % 60, tzinfo=timezone.utc)))
    base = build_availability(rows)
    shuffled = rows[:]
    random.Random(3).shuffle(shuffled)
    again = build_availability(shuffled)
    assert base.pool_sha256 == again.pool_sha256


# ---------------------------------------------------------------------------
# Gate B1R Task 5 — v2 probe + exact human join + cutoff
# ---------------------------------------------------------------------------
CUTOFF = "2026-07-22T00:00:00Z"


def fake_client(*, evidence_clip, human_behavior_clip, action):
    return FakeClient({
        "clip_python_evidence_runs": [_run(evidence_clip)],
        "motion_clips": [_motion(evidence_clip, started_at="2026-07-20T10:00:00Z")],
        "clip_prelabels": [_prelabel(evidence_clip)],
        "clip_activity_assessments": [],
        "clip_labeling_sessions": [],
        "behavior_logs": [{"clip_id": human_behavior_clip, "action": action,
                           "source": "human", "created_at": "2026-07-20T10:00:00Z"}],
    })


def test_probe_uses_v2_without_overwriting_v1_artifacts():
    rows = [_sr(f"a{i}", f"cam{i}", 20) for i in range(3)]
    result = build_availability(rows, selector_version="local-vlm-evidence-selector-v2")
    assert result.selector_version == "local-vlm-evidence-selector-v2"
    assert result.legacy_v1_counts is not None
    assert result.final_allocated_counts is not None
    assert result.raw_eligible_clip_counts is not None
    assert result.clip_overlap == 0 and result.episode_overlap == 0
    # v1 path 는 여전히 v1 을 낸다(덮어쓰지 않음)
    v1 = build_availability(rows)
    assert v1.selector_version == "local-vlm-evidence-selector-v1"
    assert v1.legacy_v1_counts is None


def test_exact_human_clip_join_enables_lick_candidate():
    client = fake_client(evidence_clip="motion-1", human_behavior_clip="motion-1", action="drinking")
    rows = load_sources(client, cutoff=CUTOFF)
    assert rows[0].human_actions == frozenset({"drinking"})


def test_fuzzy_time_or_filename_join_is_forbidden():
    client = fake_client(evidence_clip="motion-1", human_behavior_clip="different", action="drinking")
    rows = load_sources(client, cutoff=CUTOFF)
    assert rows[0].human_actions == frozenset()


def test_cutoff_excludes_clip_after_cutoff():
    client = FakeClient({
        "clip_python_evidence_runs": [_run("late")],
        "motion_clips": [_motion("late", started_at="2026-07-22T05:00:00Z")],
        "clip_prelabels": [_prelabel("late")],
        "clip_activity_assessments": [],
        "clip_labeling_sessions": [],
        "behavior_logs": [],
    })
    assert load_sources(client, cutoff=CUTOFF) == []          # after cutoff → excluded
    assert len(load_sources(client)) == 1                     # no cutoff → included

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

import pytest

from scripts.rba_event_grouping_core import (
    AccountedClip,
    EventGroupingContractError,
    ExclusionState,
    SourceClip,
    account_source_clips,
    group_activity_events,
    parse_aware_datetime,
    verify_accounting,
)


def clip(
    clip_id: str,
    *,
    camera: str = "cam-1",
    start: str = "2026-07-20T12:00:00+00:00",
    duration: float | None = 60,
) -> SourceClip:
    return SourceClip(
        clip_id=clip_id,
        camera_id=camera,
        started_at=parse_aware_datetime(start),
        duration_sec=duration,
    )


def exclusion(
    clip_id: str,
    state: str = "quarantined",
    reason: str = "short_device_error",
) -> ExclusionState:
    return ExclusionState(
        clip_id=clip_id,
        state=state,
        reason_code=reason,
        rule_version="probe-v1",
    )


def accounted(
    clip_id: str,
    *,
    at: float,
    duration: float | None = 60,
    kind: str = "activity_candidate",
    camera: str = "cam-1",
    day: date = date(2026, 7, 20),
) -> AccountedClip:
    return AccountedClip(
        clip_id=clip_id,
        camera_id=camera,
        started_at=datetime(2026, 7, 20, tzinfo=UTC) + timedelta(seconds=at),
        activity_day_kst=day,
        duration_sec=duration,
        kind=kind,  # type: ignore[arg-type]
        reason_code=None if kind == "activity_candidate" else "probe",
    )


def canonical_events(value: object) -> bytes:
    def default(item: object) -> object:
        if hasattr(item, "__dataclass_fields__"):
            return asdict(item)
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        raise TypeError(type(item).__name__)

    return json.dumps(
        value,
        default=default,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def test_accounting_assigns_every_source_exactly_once() -> None:
    clips = (
        clip("a"),
        clip("b", start="2026-07-20T12:01:05+00:00"),
        clip("c", start="2026-07-20T12:02:10+00:00", duration=None),
    )
    rows = account_source_clips(
        clips,
        exclusions={"b": exclusion("b")},
        blocked_clip_ids=frozenset(),
    )
    assert [row.clip_id for row in rows] == ["a", "b", "c"]
    assert [row.kind for row in rows] == [
        "activity_candidate",
        "diagnostic_integrity",
        "diagnostic_integrity",
    ]
    assert rows[1].reason_code == "short_device_error:quarantined"
    assert rows[2].reason_code == "invalid_duration"


def test_blocked_formal_clip_is_not_silently_dropped() -> None:
    rows = account_source_clips(
        (clip("a"),),
        exclusions={},
        blocked_clip_ids=frozenset({"a"}),
    )
    assert rows[0].kind == "blocked_research"
    assert rows[0].reason_code == "formal_or_frozen_manifest"


@pytest.mark.parametrize("duration", [0, -1, float("inf"), float("nan")])
def test_invalid_duration_is_diagnostic(duration: float) -> None:
    rows = account_source_clips(
        (clip("a", duration=duration),),
        exclusions={},
        blocked_clip_ids=frozenset(),
    )
    assert rows[0].kind == "diagnostic_integrity"
    assert rows[0].reason_code == "invalid_duration"


def test_accounting_rejects_duplicates_unknown_exclusion_and_naive_time() -> None:
    with pytest.raises(EventGroupingContractError, match="duplicate_source_clip_id"):
        account_source_clips(
            (clip("a"), clip("a", start="2026-07-20T12:01:00+00:00")),
            {},
            frozenset(),
        )
    with pytest.raises(EventGroupingContractError, match="unknown_exclusion_clip"):
        account_source_clips(
            (clip("a"),),
            {"missing": exclusion("missing")},
            frozenset(),
        )
    naive = SourceClip("a", "cam-1", datetime(2026, 7, 20), 60)
    with pytest.raises(EventGroupingContractError, match="timezone_aware"):
        account_source_clips((naive,), {}, frozenset())


def test_parse_aware_datetime_rejects_naive_and_normalizes_utc() -> None:
    parsed = parse_aware_datetime("2026-07-20T21:00:00+09:00")
    assert parsed == datetime(2026, 7, 20, 12, tzinfo=UTC)
    with pytest.raises(EventGroupingContractError, match="timezone_aware"):
        parse_aware_datetime("2026-07-20T12:00:00")


def test_grouping_uses_end_to_start_gap_and_breaks_on_diagnostic() -> None:
    rows = (
        accounted("a", at=0),
        accounted("b", at=65),
        accounted("x", at=126, kind="diagnostic_integrity"),
        accounted("c", at=127),
    )
    events = group_activity_events(rows, threshold_sec=5)
    assert [event.clip_ids for event in events] == [("a", "b"), ("c",)]


def test_grouping_is_order_independent_and_byte_stable() -> None:
    rows = (
        accounted("a", at=0),
        accounted("b", at=70),
        accounted("c", at=200),
    )
    first = group_activity_events(rows, threshold_sec=30)
    second = group_activity_events(tuple(reversed(rows)), threshold_sec=30)
    third = group_activity_events(rows, threshold_sec=30)
    assert first == second == third
    assert canonical_events(first) == canonical_events(second)


def test_grouping_forces_camera_and_activity_day_split() -> None:
    rows = (
        accounted("a", at=0, camera="cam-1"),
        accounted("b", at=1, camera="cam-2"),
        accounted("c", at=2, camera="cam-1", day=date(2026, 7, 21)),
    )
    assert [event.clip_ids for event in group_activity_events(rows, 120)] == [
        ("a",),
        ("c",),
        ("b",),
    ]


def test_overlap_and_exact_threshold_merge_but_above_threshold_splits() -> None:
    overlap = (accounted("a", at=0), accounted("b", at=30))
    assert group_activity_events(overlap, 0)[0].clip_ids == ("a", "b")
    exact = (accounted("a", at=0), accounted("b", at=65))
    assert group_activity_events(exact, 5)[0].clip_ids == ("a", "b")
    assert [event.clip_ids for event in group_activity_events(exact, 4.999)] == [
        ("a",),
        ("b",),
    ]


def test_event_id_changes_with_algorithm_or_membership() -> None:
    rows = (accounted("a", at=0), accounted("b", at=65))
    base = group_activity_events(rows, 5)
    changed_version = group_activity_events(rows, 5, algorithm_version="other-v1")
    changed_membership = group_activity_events(rows[:1], 5)
    assert base[0].event_id != changed_version[0].event_id
    assert base[0].event_id != changed_membership[0].event_id


def test_verify_accounting_rejects_missing_or_protected_event_membership() -> None:
    source = (
        clip("a"),
        clip("b", start="2026-07-20T12:01:05+00:00"),
    )
    rows = account_source_clips(
        source,
        exclusions={"b": exclusion("b")},
        blocked_clip_ids=frozenset(),
    )
    events = group_activity_events(rows, 5)
    verify_accounting(source, rows, events)
    with pytest.raises(EventGroupingContractError, match="source_accounting_mismatch"):
        verify_accounting(source, rows[:1], events)
    forged = (
        events[0],
        type(events[0])(
            event_id="forged",
            algorithm_version=events[0].algorithm_version,
            camera_id="cam-1",
            activity_day_kst=events[0].activity_day_kst,
            clip_ids=("b",),
            started_at=events[0].started_at,
            ended_at=events[0].ended_at,
        ),
    )
    with pytest.raises(EventGroupingContractError, match="protected_clip_in_event"):
        verify_accounting(source, rows, forged)

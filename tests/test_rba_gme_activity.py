from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from scripts.rba_gme_activity import (
    GmeActivityError,
    parse_gme_activity,
    rank_activity_candidates,
)


RUN_ID = "123e4567-e89b-42d3-a456-426614174000"


def _candidate(
    clip_ref: str,
    *,
    camera: str = "cam-1",
    day: str = "2026-08-21",
    activity: float = 3.0,
    started_at: str = "2026-08-21T12:00:00+09:00",
) -> dict[str, object]:
    return {
        "clip_ref": clip_ref,
        "camera_ref": camera,
        "activity_day": day,
        "activity_sec": activity,
        "started_at": started_at,
    }


def test_rank_activity_candidates_is_per_camera_day_and_deterministic() -> None:
    candidates = [
        _candidate("b", activity=2.0),
        _candidate("c", camera="cam-2", activity=1.0),
        _candidate("next-day", camera="cam-z", day="2026-08-22", activity=0.1),
        _candidate("a", activity=9.0),
    ]

    ranked = rank_activity_candidates(candidates)

    assert [
        (
            row["clip_ref"],
            row["camera_ref"],
            row["activity_day"],
            row["activity_rank"],
            row["camera_day_count"],
        )
        for row in ranked
    ] == [
        ("next-day", "cam-z", "2026-08-22", 1, 1),
        ("a", "cam-1", "2026-08-21", 1, 2),
        ("b", "cam-1", "2026-08-21", 2, 2),
        ("c", "cam-2", "2026-08-21", 1, 1),
    ]
    assert rank_activity_candidates(list(reversed(candidates))) == ranked
    assert all(type(row["activity_rank"]) is int for row in ranked)
    assert all(type(row["camera_day_count"]) is int for row in ranked)


def test_rank_activity_candidates_breaks_ties_by_instant_then_clip_ref() -> None:
    candidates = [
        _candidate("same-z", started_at="2026-08-21T12:00:00+09:00"),
        _candidate("newer", started_at="2026-08-21T03:00:01Z"),
        _candidate("same-a", started_at="2026-08-20T23:00:00-04:00"),
    ]

    ranked = rank_activity_candidates(candidates)

    assert [row["clip_ref"] for row in ranked] == [
        "newer",
        "same-a",
        "same-z",
    ]


@pytest.mark.parametrize(
    "candidate",
    [
        [],
        {"clip_ref": "missing-fields"},
        {**_candidate("extra"), "include": True},
        _candidate(""),
        _candidate("blank-camera", camera=" "),
        _candidate("bad-day", day="2026-8-21"),
        _candidate("impossible-day", day="2026-02-30"),
        _candidate("bool-activity", activity=True),
        _candidate("negative-activity", activity=-0.1),
        _candidate("overflow-activity", activity=10**1000),
        _candidate("nan-activity", activity=float("nan")),
        _candidate("inf-activity", activity=float("inf")),
        _candidate("naive-time", started_at="2026-08-21T12:00:00"),
        _candidate("bad-time", started_at="not-a-timestamp"),
        _candidate("overflow-time", started_at="0001-01-01T00:00:00+23:59"),
    ],
)
def test_rank_activity_candidates_rejects_noncanonical_rows(
    candidate: object,
) -> None:
    with pytest.raises(GmeActivityError, match="activity_candidate"):
        rank_activity_candidates([candidate])  # type: ignore[list-item]


def test_rank_activity_candidates_rejects_duplicate_clip_ref() -> None:
    with pytest.raises(GmeActivityError, match="activity_candidate"):
        rank_activity_candidates(
            [_candidate("duplicate"), _candidate("duplicate", camera="cam-2")]
        )


def test_rank_activity_candidates_rejects_precision_losing_integer_activity() -> None:
    with pytest.raises(GmeActivityError, match="activity_candidate"):
        rank_activity_candidates(
            [
                _candidate("a-lower", activity=10**100),
                _candidate("z-higher", activity=10**100 + 1),
            ]
        )


def _run() -> dict[str, object]:
    return {
        "id": RUN_ID,
        "status": "ok",
        "candidate_moving_sec_any_gecko": 3.0,
        "visible_sec": 8.0,
        "max_simultaneous_geckos": 1,
        "state_intervals": [
            {
                "start_sec": 0.0,
                "end_sec": 2.0,
                "state": "static",
                "track_ids": ["g1"],
            },
            {
                "start_sec": 2.0,
                "end_sec": 5.0,
                "state": "moving",
                "track_ids": ["g1"],
            },
        ],
    }


def test_parse_gme_activity_returns_padded_moving_intervals_and_activity() -> None:
    context = parse_gme_activity(_run(), duration_sec=10.0)

    assert context.run_id == RUN_ID
    assert context.detected is True
    assert context.activity_sec == 3.0
    assert context.visible_sec == 8.0
    assert [
        {"start_sec": interval.start_sec, "end_sec": interval.end_sec}
        for interval in context.dense_intervals
    ] == [{"start_sec": 1.5, "end_sec": 5.5}]


def test_dense_intervals_are_deeply_immutable() -> None:
    context = parse_gme_activity(_run(), duration_sec=10.0)

    with pytest.raises(FrozenInstanceError):
        context.dense_intervals[0].start_sec = 0.0  # type: ignore[misc]


def test_only_moving_intervals_are_padded_clamped_and_merged() -> None:
    run = _run()
    run["candidate_moving_sec_any_gecko"] = 1.2
    run["visible_sec"] = 1.2
    run["state_intervals"] = [
        {
            "start_sec": 0.0,
            "end_sec": 0.4,
            "state": "moving",
            "track_ids": ["g1"],
        },
        {
            "start_sec": 0.4,
            "end_sec": 0.8,
            "state": "static",
            "track_ids": ["g1"],
        },
        {
            "start_sec": 0.8,
            "end_sec": 1.6,
            "state": "moving",
            "track_ids": ["g1"],
        },
    ]

    context = parse_gme_activity(run, duration_sec=1.8)

    assert [
        (interval.start_sec, interval.end_sec)
        for interval in context.dense_intervals
    ] == [(0.0, 1.8)]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate_moving_sec_any_gecko", True),
        ("candidate_moving_sec_any_gecko", float("nan")),
        ("candidate_moving_sec_any_gecko", float("inf")),
        ("candidate_moving_sec_any_gecko", -0.1),
        ("visible_sec", True),
        ("visible_sec", float("nan")),
        ("visible_sec", float("inf")),
        ("visible_sec", -0.1),
    ],
)
def test_parse_gme_activity_rejects_invalid_summary_numbers(
    field: str, value: object
) -> None:
    run = _run()
    run[field] = value

    with pytest.raises(GmeActivityError):
        parse_gme_activity(run, duration_sec=10.0)


@pytest.mark.parametrize("duration", [True, float("nan"), float("inf"), 0.0, -1.0])
def test_parse_gme_activity_rejects_invalid_duration(duration: object) -> None:
    with pytest.raises(GmeActivityError):
        parse_gme_activity(_run(), duration_sec=duration)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "intervals",
    [
        [
            {
                "start_sec": 0.0,
                "end_sec": 2.0,
                "state": "static",
                "track_ids": ["g1"],
            },
            {
                "start_sec": 1.9,
                "end_sec": 5.0,
                "state": "moving",
                "track_ids": ["g1"],
            },
        ],
        [
            {
                "start_sec": 2.0,
                "end_sec": 2.0,
                "state": "moving",
                "track_ids": ["g1"],
            }
        ],
        [
            {
                "start_sec": 2.0,
                "end_sec": 1.0,
                "state": "moving",
                "track_ids": ["g1"],
            }
        ],
        [
            {
                "start_sec": 9.0,
                "end_sec": 10.000002,
                "state": "moving",
                "track_ids": ["g1"],
            }
        ],
    ],
)
def test_parse_gme_activity_rejects_invalid_interval_timeline(
    intervals: list[dict[str, object]],
) -> None:
    run = _run()
    run["state_intervals"] = intervals
    run["candidate_moving_sec_any_gecko"] = sum(
        max(0.0, float(row["end_sec"]) - float(row["start_sec"]))
        for row in intervals
        if row["state"] == "moving"
    )

    with pytest.raises(GmeActivityError, match="state_interval"):
        parse_gme_activity(run, duration_sec=10.0)


@pytest.mark.parametrize(
    "interval",
    [
        {
            "start_sec": 0.0,
            "end_sec": 3.0,
            "state": "running",
            "track_ids": ["g1"],
        },
        {
            "start_sec": 0.0,
            "end_sec": 3.0,
            "state": "moving",
        },
        {
            "start_sec": 0.0,
            "end_sec": 3.0,
            "state": "moving",
            "track_ids": ["g1"],
            "confidence": 0.9,
        },
        {
            "start_sec": 0.0,
            "end_sec": 3.0,
            "state": "moving",
            "track_ids": ("g1",),
        },
        {
            "start_sec": 0.0,
            "end_sec": 3.0,
            "state": "moving",
            "track_ids": ["g2", "g1"],
        },
        {
            "start_sec": 0.0,
            "end_sec": 3.0,
            "state": "moving",
            "track_ids": ["g1", "g1"],
        },
        {
            "start_sec": 0.0,
            "end_sec": 3.0,
            "state": "moving",
            "track_ids": [1],
        },
    ],
)
def test_parse_gme_activity_enforces_exact_state_interval_schema(
    interval: dict[str, object],
) -> None:
    run = _run()
    run["state_intervals"] = [interval]

    with pytest.raises(GmeActivityError, match="state_interval"):
        parse_gme_activity(run, duration_sec=10.0)


def test_parse_gme_activity_requires_summary_to_match_raw_moving_duration() -> None:
    run = _run()
    run["candidate_moving_sec_any_gecko"] = 3.0011

    with pytest.raises(GmeActivityError, match="moving_duration_mismatch"):
        parse_gme_activity(run, duration_sec=10.0)


def test_parse_gme_activity_accepts_summary_at_one_millisecond_tolerance() -> None:
    run = _run()
    run["candidate_moving_sec_any_gecko"] = 3.001

    context = parse_gme_activity(run, duration_sec=10.0)

    assert context.activity_sec == pytest.approx(3.001)


def test_parse_gme_activity_rejects_impossible_run_contract() -> None:
    mutations = [
        ("id", "not-a-uuid"),
        ("status", "decode_error"),
        ("max_simultaneous_geckos", True),
        ("max_simultaneous_geckos", -1),
        ("candidate_moving_sec_any_gecko", 8.1),
        ("visible_sec", 10.002),
        ("state_intervals", {}),
    ]
    for field, value in mutations:
        run = _run()
        run[field] = value
        with pytest.raises(GmeActivityError):
            parse_gme_activity(run, duration_sec=10.0)

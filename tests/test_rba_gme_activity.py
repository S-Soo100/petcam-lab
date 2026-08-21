from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from scripts.rba_gme_activity import GmeActivityError, parse_gme_activity


RUN_ID = "123e4567-e89b-42d3-a456-426614174000"


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

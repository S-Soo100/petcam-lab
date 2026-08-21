from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.rba_gme_activity import GmeActivityContext, parse_gme_activity
from scripts.rba_openai_clip_aggregate import AggregateError, aggregate_clip_ledger


def _record(window_id: str, prediction: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "rba-openai-window-ledger-v1",
        "clip_ref": "smoke-abc",
        "window_id": window_id,
        "prediction": prediction,
    }


def _prediction(
    *, action: str, segments: list[dict[str, object]], count: str
) -> dict[str, object]:
    return {
        "primary_action": action,
        "observed_actions": [segment["action"] for segment in segments],
        "segments": segments,
        "max_visible_gecko_count": count,
        "count_evidence_timestamps": [0.0],
        "visibility": "visible",
        "occlusion": "none",
        "quality_flags": [],
        "uncertainty": "low" if count != "uncertain" else "high",
        "user_summary": "summary",
    }


def _gme_context() -> GmeActivityContext:
    return parse_gme_activity(
        {
            "id": "123e4567-e89b-42d3-a456-426614174000",
            "status": "ok",
            "candidate_moving_sec_any_gecko": 3.0,
            "visible_sec": 8.0,
            "max_simultaneous_geckos": 1,
            "state_intervals": [
                {
                    "start_sec": 0.0,
                    "end_sec": 3.0,
                    "state": "moving",
                    "track_ids": ["g1"],
                }
            ],
        },
        duration_sec=10.0,
    )


def test_aggregate_adds_exact_activity_candidate_provenance(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps(
            _record(
                "window-000",
                _prediction(action="resting", count="1", segments=[]),
            )
        )
        + "\n"
    )

    aggregate = aggregate_clip_ledger(
        ledger,
        clip_ref="smoke-abc",
        expected_window_ids=["window-000"],
        gme_context=_gme_context(),
        highlight_activity_priority={"camera_day_rank": 1, "camera_day_count": 4},
        output=tmp_path / "aggregate.json",
    )

    assert aggregate["gme_activity"] == {
        "run_id": "123e4567-e89b-42d3-a456-426614174000",
        "detected": True,
        "activity_sec": 3.0,
        "visible_sec": 8.0,
    }
    assert aggregate["highlight_activity_priority"] == {
        "camera_day_rank": 1,
        "camera_day_count": 4,
    }
    assert set(aggregate["gme_activity"]) == {
        "run_id",
        "detected",
        "activity_sec",
        "visible_sec",
    }
    assert set(aggregate["highlight_activity_priority"]) == {
        "camera_day_rank",
        "camera_day_count",
    }
    assert not {"include", "skip", "behavior", "highlight_recommendation"}.intersection(
        aggregate
    )


def test_aggregate_activity_provenance_is_canonical_under_reversed_ledger(
    tmp_path: Path,
) -> None:
    records = [
        _record(
            "window-000",
            _prediction(
                action="resting",
                count="1",
                segments=[
                    {
                        "action": "resting",
                        "start_sec": 0.0,
                        "end_sec": 2.0,
                        "evidence_timestamps": [1.0],
                    }
                ],
            ),
        ),
        _record(
            "window-001",
            _prediction(
                action="moving",
                count="1",
                segments=[
                    {
                        "action": "moving",
                        "start_sec": 3.0,
                        "end_sec": 4.0,
                        "evidence_timestamps": [3.5],
                    }
                ],
            ),
        ),
    ]
    first_ledger = tmp_path / "first.jsonl"
    second_ledger = tmp_path / "second.jsonl"
    first_ledger.write_text("\n".join(json.dumps(row) for row in records) + "\n")
    second_ledger.write_text(
        "\n".join(json.dumps(row) for row in reversed(records)) + "\n"
    )
    first_output = tmp_path / "first.json"
    second_output = tmp_path / "second.json"
    kwargs = {
        "clip_ref": "smoke-abc",
        "expected_window_ids": ["window-000", "window-001"],
        "gme_context": _gme_context(),
        "highlight_activity_priority": {
            "camera_day_count": 4,
            "camera_day_rank": 1,
        },
    }

    first = aggregate_clip_ledger(first_ledger, output=first_output, **kwargs)
    second = aggregate_clip_ledger(second_ledger, output=second_output, **kwargs)

    assert second == first
    assert second_output.read_bytes() == first_output.read_bytes()


@pytest.mark.parametrize(
    "priority",
    [
        {},
        {"camera_day_rank": 1},
        {"camera_day_rank": 1, "camera_day_count": 4, "include": True},
        {"camera_day_rank": True, "camera_day_count": 4},
        {"camera_day_rank": 1, "camera_day_count": False},
        {"camera_day_rank": 0, "camera_day_count": 4},
        {"camera_day_rank": 5, "camera_day_count": 4},
        {"camera_day_rank": 1, "camera_day_count": 0},
    ],
)
def test_aggregate_rejects_invalid_activity_priority_before_writing(
    tmp_path: Path, priority: dict[str, object]
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("")
    output = tmp_path / "aggregate.json"

    with pytest.raises(AggregateError, match="highlight_activity_priority"):
        aggregate_clip_ledger(
            ledger,
            clip_ref="smoke-abc",
            expected_window_ids=["window-000"],
            highlight_activity_priority=priority,
            output=output,
        )

    assert not output.exists()


def test_aggregate_rejects_non_context_gme_provenance_before_writing(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("")
    output = tmp_path / "aggregate.json"

    with pytest.raises(AggregateError, match="gme_context"):
        aggregate_clip_ledger(
            ledger,
            clip_ref="smoke-abc",
            expected_window_ids=["window-000"],
            gme_context={"activity_sec": 3.0},  # type: ignore[arg-type]
            output=output,
        )

    assert not output.exists()


def test_aggregate_rejects_overflowing_context_number_before_writing(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("")
    output = tmp_path / "aggregate.json"
    context = GmeActivityContext(
        run_id="123e4567-e89b-42d3-a456-426614174000",
        detected=True,
        activity_sec=10**1000,  # type: ignore[arg-type]
        visible_sec=10**1000,  # type: ignore[arg-type]
        dense_intervals=(),
    )

    with pytest.raises(AggregateError, match="gme_context"):
        aggregate_clip_ledger(
            ledger,
            clip_ref="smoke-abc",
            expected_window_ids=["window-000"],
            gme_context=context,
            output=output,
        )

    assert not output.exists()


def test_aggregate_merges_overlap_and_uses_deterministic_primary_action(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    records = [
        _record(
            "window-000",
            _prediction(
                action="resting",
                count="1",
                segments=[
                    {
                        "action": "resting",
                        "start_sec": 0.0,
                        "end_sec": 3.0,
                        "evidence_timestamps": [1.0],
                    }
                ],
            ),
        ),
        _record(
            "window-001",
            _prediction(
                action="moving",
                count="2",
                segments=[
                    {
                        "action": "resting",
                        "start_sec": 2.5,
                        "end_sec": 5.0,
                        "evidence_timestamps": [4.0],
                    },
                    {
                        "action": "moving",
                        "start_sec": 6.0,
                        "end_sec": 7.0,
                        "evidence_timestamps": [6.5],
                    },
                ],
            ),
        ),
    ]
    ledger.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    output = tmp_path / "aggregate.json"

    aggregate = aggregate_clip_ledger(
        ledger,
        clip_ref="smoke-abc",
        expected_window_ids=["window-000", "window-001"],
        output=output,
    )

    assert aggregate["status"] == "complete"
    assert aggregate["primary_action"] == "resting"
    assert aggregate["observed_actions"] == ["moving", "resting"]
    assert aggregate["segments"] == [
        {
            "action": "resting",
            "start_sec": 0.0,
            "end_sec": 5.0,
            "evidence_timestamps": [1.0, 4.0],
        },
        {
            "action": "moving",
            "start_sec": 6.0,
            "end_sec": 7.0,
            "evidence_timestamps": [6.5],
        },
    ]
    assert aggregate["max_visible_gecko_count"] == "2"
    assert aggregate["count_uncertain"] is False
    assert "gme_activity" not in aggregate
    assert "highlight_activity_priority" not in aggregate
    assert output.stat().st_mode & 0o777 == 0o600


def test_aggregate_marks_missing_window_incomplete(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps(
            _record(
                "window-000",
                _prediction(action="resting", count="uncertain", segments=[]),
            )
        )
        + "\n"
    )

    aggregate = aggregate_clip_ledger(
        ledger,
        clip_ref="smoke-abc",
        expected_window_ids=["window-000", "window-001"],
        output=tmp_path / "aggregate.json",
    )

    assert aggregate["status"] == "incomplete"
    assert aggregate["missing_window_ids"] == ["window-001"]
    assert aggregate["count_uncertain"] is True


def test_aggregate_marks_explicit_failed_window_incomplete(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "schema_version": "rba-openai-window-ledger-v1",
                "clip_ref": "smoke-abc",
                "window_id": "window-000",
                "status": "failed",
                "failure_code": "provider_request_failed",
            }
        )
        + "\n"
    )

    aggregate = aggregate_clip_ledger(
        ledger,
        clip_ref="smoke-abc",
        expected_window_ids=["window-000"],
        output=tmp_path / "aggregate.json",
    )

    assert aggregate["status"] == "incomplete"
    assert aggregate["missing_window_ids"] == []
    assert aggregate["failed_window_ids"] == ["window-000"]


@pytest.mark.parametrize(
    "schema_version",
    [None, "rba-openai-window-ledger-v2"],
)
def test_aggregate_rejects_non_v1_schema_for_consumed_record(
    tmp_path: Path, schema_version: str | None
) -> None:
    record = _record(
        "window-000",
        _prediction(action="resting", count="1", segments=[]),
    )
    if schema_version is None:
        record.pop("schema_version")
    else:
        record["schema_version"] = schema_version
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps(record) + "\n")

    with pytest.raises(AggregateError, match="ledger_schema_version"):
        aggregate_clip_ledger(
            ledger,
            clip_ref="smoke-abc",
            expected_window_ids=["window-000"],
            output=tmp_path / "aggregate.json",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("start_sec", float("nan")),
        ("end_sec", float("inf")),
        ("evidence_timestamps", [float("-inf")]),
    ],
)
def test_aggregate_rejects_non_finite_segment_numbers(
    tmp_path: Path, field: str, value: object
) -> None:
    segment: dict[str, object] = {
        "action": "resting",
        "start_sec": 0.0,
        "end_sec": 1.0,
        "evidence_timestamps": [0.5],
    }
    segment[field] = value
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps(
            _record(
                "window-000",
                _prediction(action="resting", count="1", segments=[segment]),
            )
        )
        + "\n"
    )
    output = tmp_path / "aggregate.json"

    with pytest.raises(AggregateError, match="finite_numeric_contract"):
        aggregate_clip_ledger(
            ledger,
            clip_ref="smoke-abc",
            expected_window_ids=["window-000"],
            output=output,
        )

    assert not output.exists()

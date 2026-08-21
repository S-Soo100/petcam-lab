from __future__ import annotations

import json
from pathlib import Path

import pytest

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

"""OpenAI window 예측을 결정론적으로 clip timeline으로 합쳐."""

from __future__ import annotations

from collections import defaultdict
import json
import math
import os
from pathlib import Path
from typing import Iterable


class AggregateError(ValueError):
    """window ledger가 합성 계약을 만족하지 않아."""


def _canonical_bytes(value: object) -> bytes:
    _require_finite_numbers(value)
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()


def _require_finite_numbers(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise AggregateError("finite_numeric_contract")
    if isinstance(value, dict):
        for child in value.values():
            _require_finite_numbers(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _require_finite_numbers(child)


def _merged_segments(raw_segments: Iterable[object]) -> list[dict[str, object]]:
    by_action: dict[str, list[dict[str, object]]] = defaultdict(list)
    for raw in raw_segments:
        if not isinstance(raw, dict):
            raise AggregateError("segment_contract")
        _require_finite_numbers(raw)
        action = raw.get("action")
        start = raw.get("start_sec")
        end = raw.get("end_sec")
        evidence = raw.get("evidence_timestamps")
        if (
            not isinstance(action, str)
            or isinstance(start, bool)
            or not isinstance(start, (int, float))
            or isinstance(end, bool)
            or not isinstance(end, (int, float))
            or float(start) < 0
            or float(end) < float(start)
            or not isinstance(evidence, list)
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                for value in evidence
            )
        ):
            raise AggregateError("segment_contract")
        by_action[action].append(
            {
                "action": action,
                "start_sec": float(start),
                "end_sec": float(end),
                "evidence_timestamps": sorted({float(value) for value in evidence}),
            }
        )

    merged: list[dict[str, object]] = []
    for action, segments in sorted(by_action.items()):
        current: dict[str, object] | None = None
        for segment in sorted(
            segments, key=lambda value: (value["start_sec"], value["end_sec"])
        ):
            if current is None:
                current = dict(segment)
                continue
            if float(segment["start_sec"]) <= float(current["end_sec"]) + 1.0:
                current["end_sec"] = max(
                    float(current["end_sec"]), float(segment["end_sec"])
                )
                current["evidence_timestamps"] = sorted(
                    {
                        *current["evidence_timestamps"],  # type: ignore[misc]
                        *segment["evidence_timestamps"],  # type: ignore[misc]
                    }
                )
            else:
                merged.append(current)
                current = dict(segment)
        if current is not None:
            merged.append(current)
    return sorted(
        merged,
        key=lambda value: (
            float(value["start_sec"]),
            float(value["end_sec"]),
            str(value["action"]),
        ),
    )


def aggregate_clip_ledger(
    ledger_path: Path,
    *,
    clip_ref: str,
    expected_window_ids: Iterable[str],
    output: Path,
) -> dict[str, object]:
    expected = tuple(expected_window_ids)
    if not expected or len(set(expected)) != len(expected):
        raise AggregateError("expected_windows")
    records: dict[str, dict[str, object]] = {}
    for line in ledger_path.read_text().splitlines():
        raw = json.loads(line)
        if not isinstance(raw, dict) or raw.get("clip_ref") != clip_ref:
            continue
        if raw.get("schema_version") != "rba-openai-window-ledger-v1":
            raise AggregateError("ledger_schema_version")
        window_id = raw.get("window_id")
        status = raw.get("status", "complete")
        prediction = raw.get("prediction")
        valid_complete = status == "complete" and isinstance(prediction, dict)
        valid_failed = status == "failed" and isinstance(
            raw.get("failure_code"), str
        )
        if not isinstance(window_id, str) or window_id in records or not (
            valid_complete or valid_failed
        ):
            raise AggregateError("ledger_contract")
        records[window_id] = raw
    extra = sorted(set(records) - set(expected))
    if extra:
        raise AggregateError("unexpected_window")
    missing = sorted(set(expected) - set(records))
    failed = sorted(
        window_id
        for window_id, record in records.items()
        if record.get("status") == "failed"
    )
    raw_segments: list[object] = []
    actions: set[str] = set()
    counts: list[str] = []
    count_uncertain = False
    for window_id in expected:
        record = records.get(window_id)
        if record is None or record.get("status") == "failed":
            continue
        prediction = record.get("prediction")
        if not isinstance(prediction, dict):
            raise AggregateError("ledger_contract")
        observed = prediction.get("observed_actions")
        segments = prediction.get("segments")
        count = prediction.get("max_visible_gecko_count")
        if (
            not isinstance(observed, list)
            or any(not isinstance(action, str) for action in observed)
            or not isinstance(segments, list)
            or count not in {"0", "1", "2", "3", "4+", "uncertain"}
        ):
            raise AggregateError("prediction_contract")
        actions.update(observed)
        raw_segments.extend(segments)
        if count == "uncertain":
            count_uncertain = True
        else:
            counts.append(str(count))
    segments = _merged_segments(raw_segments)
    duration_by_action: dict[str, float] = defaultdict(float)
    earliest_by_action: dict[str, float] = {}
    for segment in segments:
        action = str(segment["action"])
        duration_by_action[action] += float(segment["end_sec"]) - float(
            segment["start_sec"]
        )
        evidence = segment["evidence_timestamps"]
        if evidence:
            earliest_by_action[action] = min(
                earliest_by_action.get(action, float("inf")), min(evidence)  # type: ignore[arg-type]
            )
    primary_action = "uncertain"
    if duration_by_action:
        primary_action = min(
            duration_by_action,
            key=lambda action: (
                -duration_by_action[action],
                earliest_by_action.get(action, float("inf")),
                action,
            ),
        )
    count_order = {"0": 0, "1": 1, "2": 2, "3": 3, "4+": 4}
    max_count = max(counts, key=count_order.__getitem__) if counts else "uncertain"
    aggregate: dict[str, object] = {
        "schema_version": "rba-openai-clip-aggregate-v1",
        "clip_ref": clip_ref,
        "status": "incomplete" if missing or failed else "complete",
        "missing_window_ids": missing,
        "failed_window_ids": failed,
        "primary_action": primary_action,
        "observed_actions": sorted(actions),
        "segments": segments,
        "max_visible_gecko_count": max_count,
        "count_uncertain": count_uncertain or not counts,
    }
    if output.exists() or output.is_symlink():
        raise AggregateError("output_exists")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output.parent, 0o700)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(_canonical_bytes(aggregate))
        handle.flush()
        os.fsync(handle.fileno())
    output.chmod(0o600)
    return aggregate

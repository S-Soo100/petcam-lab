"""Classify aggregate YOLO v2.2 Owner-media diagnostic failures."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Mapping, Sequence


def _box(value: object) -> tuple[float, float, float, float]:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(type(item) not in (int, float) or not math.isfinite(float(item)) for item in value)
    ):
        raise ValueError("box geometry malformed")
    x1, y1, x2, y2 = map(float, value)
    if x1 >= x2 or y1 >= y2:
        raise ValueError("box geometry malformed")
    return x1, y1, x2, y2


def _iou(left: Sequence[float], right: Sequence[float]) -> float:
    width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    intersection = width * height
    union = (
        (left[2] - left[0]) * (left[3] - left[1])
        + (right[2] - right[0]) * (right[3] - right[1])
        - intersection
    )
    return intersection / union if union else 0.0


def analyze_failures(
    ledger: Mapping[str, object], *, threshold: float, iou_threshold: float
) -> dict[str, object]:
    if (
        ledger.get("schema") != "yolo26n-owner-media-external-predictions-v1"
        or ledger.get("status") != "PREDICTIONS_COMPLETE"
    ):
        raise ValueError("prediction ledger contract mismatch")
    records = ledger.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("prediction records malformed")
    seen: set[str] = set()
    counts = {
        "complete_miss": 0,
        "duplicate_box": 0,
        "false_positive_negative": 0,
        "localization_error": 0,
    }
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("prediction record malformed")
        sequence = record.get("sequence")
        if not isinstance(sequence, str) or sequence in seen:
            raise ValueError("prediction sequence malformed")
        seen.add(sequence)
        raw_gt, raw_predictions = record.get("gt_boxes"), record.get("predictions")
        if not isinstance(raw_gt, list) or not isinstance(raw_predictions, list):
            raise ValueError("prediction record malformed")
        gt = tuple(_box(value) for value in raw_gt)
        predictions = []
        for raw in raw_predictions:
            if not isinstance(raw, Mapping) or set(raw) != {"confidence", "xyxy"}:
                raise ValueError("prediction malformed")
            confidence = raw.get("confidence")
            if (
                type(confidence) not in (int, float)
                or not math.isfinite(float(confidence))
                or not 0 <= float(confidence) <= 1
            ):
                raise ValueError("prediction confidence malformed")
            box = _box(raw.get("xyxy"))
            if float(confidence) >= threshold:
                predictions.append((float(confidence), box))
        predictions.sort(key=lambda item: (-item[0], item[1]))

        matched: set[int] = set()
        has_localization_error = False
        duplicate_counted = False
        for _, prediction in predictions:
            overlaps = [(_iou(prediction, target), index) for index, target in enumerate(gt)]
            eligible = [(overlap, index) for overlap, index in overlaps if index not in matched]
            best_overlap, best_index = max(eligible, default=(0.0, -1))
            if best_index >= 0 and best_overlap >= iou_threshold:
                matched.add(best_index)
            elif overlaps and max(overlap for overlap, _ in overlaps) >= iou_threshold:
                duplicate_counted = True
            elif gt:
                has_localization_error = True

        if gt and not matched:
            counts["complete_miss"] += 1
        if duplicate_counted:
            counts["duplicate_box"] += 1
        if not gt and predictions:
            counts["false_positive_negative"] += 1
        if has_localization_error:
            counts["localization_error"] += 1

    return {
        "schema": "yolo26n-owner-media-failure-analysis-v1",
        "status": "OWNER_MEDIA_FAILURE_ANALYSIS_COMPLETE",
        "image_count": len(records),
        "threshold": threshold,
        "iou_threshold": iou_threshold,
        "failure_counts": counts,
        "priority": [
            "complete_miss",
            "false_positive_negative",
            "duplicate_box",
            "localization_error",
        ],
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def _write_private(path: Path, value: Mapping[str, object]) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(value, handle, sort_keys=True, separators=(",", ":"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    ledger = json.loads(args.ledger.read_bytes())
    report = analyze_failures(ledger, threshold=0.20, iou_threshold=0.50)
    _write_private(args.output, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

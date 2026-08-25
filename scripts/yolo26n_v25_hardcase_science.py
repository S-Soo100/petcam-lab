"""Pure hard-case bucketing and deterministic queue selection for YOLO v2.5."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence


POLICY_ID = "yolo26n-v25-blind-queue-v1"
POLICY_SEED = "yolo26n-v25-historical-hardcase-reinforcement-v1"
SIGNAL_PRIORITY = {
    "duplicate_box_signal": 0,
    "suspected_miss": 1,
    "suspected_false_positive": 2,
    "partial_occlusion_signal": 3,
    "source_diversity": 4,
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _validated_predictions(
    raw: Mapping[str, object],
) -> tuple[str, int, float, int, int, list[dict[str, object]]]:
    source = raw.get("source_video_sha256")
    frame_index = raw.get("frame_index")
    timestamp = raw.get("timestamp_sec")
    width = raw.get("width")
    height = raw.get("height")
    predictions = raw.get("predictions")
    if (
        raw.get("role") != "owner-development-video"
        or not isinstance(source, str)
        or _SHA256.fullmatch(source) is None
        or type(frame_index) is not int
        or frame_index < 0
        or not isinstance(timestamp, (int, float))
        or isinstance(timestamp, bool)
        or not math.isfinite(float(timestamp))
        or float(timestamp) < 0
        or type(width) is not int
        or type(height) is not int
        or width < 1
        or height < 1
        or not isinstance(predictions, list)
        or len(predictions) > 50
    ):
        raise ValueError("prediction frame contract mismatch")
    checked: list[dict[str, object]] = []
    for prediction in predictions:
        if not isinstance(prediction, Mapping):
            raise ValueError("prediction box contract mismatch")
        confidence = prediction.get("confidence")
        box = prediction.get("box_xyxy")
        if (
            prediction.get("class_id") != 0
            or not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not math.isfinite(float(confidence))
            or not 0 <= float(confidence) <= 1
            or not isinstance(box, list)
            or len(box) != 4
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                for value in box
            )
        ):
            raise ValueError("prediction box contract mismatch")
        left, top, right, bottom = (float(value) for value in box)
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise ValueError("prediction box contract mismatch")
        checked.append(
            {
                "class_id": 0,
                "confidence": float(confidence),
                "box_xyxy": [left, top, right, bottom],
            }
        )
    return source, frame_index, float(timestamp), width, height, checked


def _box_iou(left: Sequence[float], right: Sequence[float]) -> float:
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    union = left_area + right_area - intersection
    return 0.0 if union <= 0 else intersection / union


def classify_hardcase_signals(
    frames: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    validated = [_validated_predictions(frame) for frame in frames]
    identities = {(source, index) for source, index, *_rest in validated}
    if len(identities) != len(validated):
        raise ValueError("prediction frame identities duplicate")
    output: list[dict[str, object]] = []
    for raw, (source, _index, timestamp, width, height, predictions) in zip(
        frames, validated, strict=True
    ):
        signals: list[str] = []
        if any(
            _box_iou(
                predictions[left]["box_xyxy"], predictions[right]["box_xyxy"]
            )
            >= 0.70
            for left in range(len(predictions))
            for right in range(left + 1, len(predictions))
        ):
            signals.append("duplicate_box_signal")
        if not predictions:
            signals.append("suspected_miss")
        if len(predictions) == 1 and predictions[0]["confidence"] < 0.50:
            supported = any(
                other_source == source
                and other_timestamp != timestamp
                and abs(other_timestamp - timestamp) <= 2.0
                and bool(other_predictions)
                for (
                    other_source,
                    _other_index,
                    other_timestamp,
                    _other_width,
                    _other_height,
                    other_predictions,
                ) in validated
            )
            if not supported:
                signals.append("suspected_false_positive")
        if any(
            box[0] <= width * 0.02
            or box[1] <= height * 0.02
            or box[2] >= width * 0.98
            or box[3] >= height * 0.98
            for box in (prediction["box_xyxy"] for prediction in predictions)
        ):
            signals.append("partial_occlusion_signal")
        signals.append("source_diversity")
        row = dict(raw)
        row["predictions"] = predictions
        row["signals"] = signals
        row.pop("species", None)
        output.append(row)
    return output


def _queue_rank(row: Mapping[str, object]) -> tuple[int, str, int, str]:
    signals = row.get("signals")
    source = row.get("source_video_sha256")
    frame_index = row.get("frame_index")
    image_sha = row.get("image_sha256")
    if (
        row.get("role") != "owner-development-video"
        or not isinstance(signals, list)
        or not signals
        or any(signal not in SIGNAL_PRIORITY for signal in signals)
        or not isinstance(source, str)
        or _SHA256.fullmatch(source) is None
        or type(frame_index) is not int
        or not isinstance(image_sha, str)
        or _SHA256.fullmatch(image_sha) is None
    ):
        raise ValueError("hard-case queue record mismatch")
    return min(SIGNAL_PRIORITY[signal] for signal in signals), source, frame_index, image_sha


def select_blind_queue(
    records: Sequence[Mapping[str, object]],
    *,
    per_source_cap: int = 6,
    total_cap: int = 210,
) -> list[dict[str, object]]:
    if per_source_cap < 1 or total_cap < 1:
        raise ValueError("queue caps must be positive")
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for raw in records:
        row = dict(raw)
        _queue_rank(row)
        groups[str(row["source_video_sha256"])].append(row)
    for rows in groups.values():
        rows.sort(key=_queue_rank)
    selected: list[dict[str, object]] = []
    counts: Counter[str] = Counter()
    while len(selected) < total_cap:
        progressed = False
        for source in sorted(groups):
            if counts[source] >= per_source_cap or not groups[source]:
                continue
            selected.append(groups[source].pop(0))
            counts[source] += 1
            progressed = True
            if len(selected) == total_cap:
                break
        if not progressed:
            break
    return selected

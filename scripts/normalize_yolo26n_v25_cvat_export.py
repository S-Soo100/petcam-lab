"""Normalize the completed blind CVAT Job 164 into immutable YOLO v2.5 GT."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path


EXPECTED_TASK_ID = 167
EXPECTED_JOB_ID = 164
EXPECTED_FRAME_COUNT = 201
EXPECTED_BOX_COUNT = 219
EXPECTED_POSITIVE_COUNT = 198
EXPECTED_NEGATIVE_COUNT = 3
RAW_GECKO_LABEL_ID = 11
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHAPE_FIELDS = {
    "id",
    "type",
    "frame",
    "label_id",
    "group",
    "source",
    "occluded",
    "outside",
    "z_order",
    "rotation",
    "points",
    "attributes",
    "elements",
    "score",
}


def _strict_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be an integer")
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")
    return value


def _queue_records(queue_manifest: Mapping[str, object]) -> list[dict[str, object]]:
    records = queue_manifest.get("records")
    if (
        queue_manifest.get("schema") != "yolo26n-v25-blind-queue-manifest-v1"
        or queue_manifest.get("status") != "V25_BLIND_QUEUE_READY"
        or _strict_int(queue_manifest.get("queue_count"), "queue_count")
        != EXPECTED_FRAME_COUNT
        or queue_manifest.get("prediction_visible") is not False
        or queue_manifest.get("empty_frame_allowed") is not True
        or not isinstance(records, list)
        or len(records) != EXPECTED_FRAME_COUNT
    ):
        raise ValueError("blind queue contract mismatch")
    loaded: list[dict[str, object]] = []
    for ordinal, raw in enumerate(records, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError("queue record must be an object")
        sequence = f"V25{ordinal:04d}"
        if raw.get("sequence") != sequence or raw.get("filename") != f"{sequence}.jpg":
            raise ValueError("queue order mismatch")
        width = _strict_int(raw.get("width"), "width")
        height = _strict_int(raw.get("height"), "height")
        if width <= 0 or height <= 0:
            raise ValueError("image dimensions must be positive")
        loaded.append(
            {
                "sequence": sequence,
                "filename": f"{sequence}.jpg",
                "image_sha256": _sha(raw.get("image_sha256"), "image_sha256"),
                "width": width,
                "height": height,
                "boxes": [],
            }
        )
    return loaded


def _validate_shape(shape: Mapping[str, object], images: list[dict[str, object]]) -> tuple[int, dict[str, object]]:
    if not set(shape).issubset(_SHAPE_FIELDS):
        raise ValueError("unsupported CVAT shape field")
    frame = _strict_int(shape.get("frame"), "shape.frame")
    if not 0 <= frame < EXPECTED_FRAME_COUNT:
        raise ValueError("shape frame outside queue")
    if (
        shape.get("type") != "rectangle"
        or _strict_int(shape.get("label_id"), "shape.label_id") != RAW_GECKO_LABEL_ID
        or _strict_int(shape.get("group"), "shape.group") != 0
        or shape.get("source") != "manual"
        or shape.get("occluded") is not False
        or shape.get("outside") is not False
        or _strict_int(shape.get("z_order"), "shape.z_order") != 0
        or _number(shape.get("rotation"), "shape.rotation") != 0.0
        or shape.get("attributes") != []
        or shape.get("elements") != []
    ):
        raise ValueError("shape is not a manual static gecko rectangle")
    if "id" in shape and _strict_int(shape["id"], "shape.id") < 0:
        raise ValueError("shape id invalid")
    if "score" in shape and (type(shape["score"]) is not float or shape["score"] != 1.0):
        raise ValueError("shape score invalid")
    points = shape.get("points")
    if not isinstance(points, list) or len(points) != 4:
        raise ValueError("rectangle points invalid")
    x1, y1, x2, y2 = (_number(value, "rectangle point") for value in points)
    image = images[frame]
    width = int(image["width"])
    height = int(image["height"])
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("rectangle outside image or empty")
    return frame, {"type": "rectangle", "label_id": 0, "points": [x1, y1, x2, y2]}


def normalize_export(
    task_id: int,
    job_id: int,
    job_state: str,
    raw_annotations: Mapping[str, object],
    queue_manifest: Mapping[str, object],
    *,
    raw_annotations_sha256: str | None = None,
    queue_manifest_sha256: str | None = None,
) -> dict[str, object]:
    if (
        _strict_int(task_id, "task_id") != EXPECTED_TASK_ID
        or _strict_int(job_id, "job_id") != EXPECTED_JOB_ID
        or job_state != "completed"
    ):
        raise ValueError("CVAT task/job/state mismatch")
    if raw_annotations.get("tags") != [] or raw_annotations.get("tracks") != []:
        raise ValueError("tags and tracks are forbidden")
    shapes = raw_annotations.get("shapes")
    if not isinstance(shapes, list):
        raise ValueError("CVAT shapes missing")
    images = _queue_records(queue_manifest)
    for raw in shapes:
        if not isinstance(raw, Mapping):
            raise ValueError("shape must be an object")
        frame, box = _validate_shape(raw, images)
        images[frame]["boxes"].append(box)
    positive = sum(bool(image["boxes"]) for image in images)
    counts = Counter(len(image["boxes"]) for image in images)
    if (
        len(shapes) != EXPECTED_BOX_COUNT
        or positive != EXPECTED_POSITIVE_COUNT
        or counts[0] != EXPECTED_NEGATIVE_COUNT
    ):
        raise ValueError("human annotation aggregate mismatch")
    provenance: dict[str, object] = {
        "cvat_task_id": EXPECTED_TASK_ID,
        "cvat_job_id": EXPECTED_JOB_ID,
        "raw_gecko_label_id": RAW_GECKO_LABEL_ID,
    }
    if raw_annotations_sha256 is not None:
        provenance["raw_annotations_sha256"] = _sha(
            raw_annotations_sha256, "raw_annotations_sha256"
        )
    if queue_manifest_sha256 is not None:
        provenance["queue_manifest_sha256"] = _sha(
            queue_manifest_sha256, "queue_manifest_sha256"
        )
    return {
        "schema": "yolo26n-v25-human-snapshot-v1",
        "status": "V25_HUMAN_EXPORT_ACCEPTED",
        "labels": [{"id": 0, "name": "gecko"}],
        "frame_count": EXPECTED_FRAME_COUNT,
        "positive_frame_count": positive,
        "negative_frame_count": counts[0],
        "box_count": len(shapes),
        "images": images,
        "provenance": provenance,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "deploy_count": 0,
    }


def _read_json(path: Path) -> tuple[dict[str, object], str]:
    payload = path.read_bytes()
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value, hashlib.sha256(payload).hexdigest()


def _write_private_new(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--queue-manifest", type=Path, required=True)
    parser.add_argument("--job-state", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    annotations, annotations_sha = _read_json(args.annotations)
    queue, queue_sha = _read_json(args.queue_manifest)
    result = normalize_export(
        EXPECTED_TASK_ID,
        EXPECTED_JOB_ID,
        args.job_state,
        annotations,
        queue,
        raw_annotations_sha256=annotations_sha,
        queue_manifest_sha256=queue_sha,
    )
    _write_private_new(args.output, result)
    print("V25_HUMAN_EXPORT_ACCEPTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

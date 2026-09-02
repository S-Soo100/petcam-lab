"""Validate and normalize the blinded Owner-media CVAT annotation export."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence


MANIFEST_SCHEMA = "yolo26n-owner-media-diagnostic-v1"
SNAPSHOT_SCHEMA = "yolo26n-owner-media-cvat-snapshot-v1"
OUTPUT_STATUS = "OWNER_MEDIA_HUMAN_REVIEW_ACCEPTED"
NORMALIZED_LABEL_ID = 1
NORMALIZED_LABEL_NAME = "gecko"
PARTITIONS = ("external_diagnostic", "training_candidate")
CVAT_JOB_ID = 163
RAW_GECKO_LABEL_ID = 10
EXPECTED_IMAGE_COUNT = 240
EXPECTED_PARTITION_COUNTS = {"external_diagnostic": 60, "training_candidate": 180}
RAW_SHAPE_FIELDS = {
    "attributes",
    "elements",
    "frame",
    "group",
    "id",
    "label_id",
    "occluded",
    "outside",
    "points",
    "rotation",
    "score",
    "source",
    "type",
    "z_order",
}


def _is_int(value: object) -> bool:
    return type(value) is int


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _manifest_items(manifest: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("manifest schema mismatch")
    if manifest.get("status") != "OWNER_MEDIA_HUMAN_REVIEW_REQUIRED":
        raise ValueError("manifest status mismatch")
    if manifest.get("prediction_exposed") is not False:
        raise ValueError("manifest must remain blind")
    if any(
        type(manifest.get(field)) is not int or manifest.get(field) != 0
        for field in ("db_write_count", "r2_write_count", "service_write_count")
    ):
        raise ValueError("manifest write audit mismatch")
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("manifest items must be a nonempty list")
    if type(manifest.get("image_count")) is not int or manifest.get("image_count") != len(items):
        raise ValueError("manifest image count mismatch")
    if len(items) != EXPECTED_IMAGE_COUNT:
        raise ValueError("manifest must contain exactly 240 images")

    seen_sequences: set[str] = set()
    seen_hashes: set[str] = set()
    normalized: list[Mapping[str, object]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, Mapping):
            raise ValueError("manifest item malformed")
        sequence = item.get("sequence")
        expected_sequence = f"O{index:04d}"
        if sequence != expected_sequence or sequence in seen_sequences:
            raise ValueError("manifest sequence mismatch")
        if item.get("derived_filename") != f"{sequence}.jpg":
            raise ValueError("manifest filename mismatch")
        image_sha256 = _require_sha256(item.get("derived_sha256"), "manifest image sha256")
        width = item.get("width")
        height = item.get("height")
        if not _is_int(width) or not _is_int(height) or width <= 0 or height <= 0:
            raise ValueError("manifest image dimensions mismatch")
        if item.get("partition") not in PARTITIONS:
            raise ValueError("manifest partition mismatch")
        if image_sha256 in seen_hashes:
            raise ValueError("manifest image sha256 must be unique")
        seen_sequences.add(sequence)
        seen_hashes.add(image_sha256)
        normalized.append(item)
    declared_counts = manifest.get("partition_counts")
    actual_counts = {
        partition: sum(item.get("partition") == partition for item in normalized)
        for partition in PARTITIONS
    }
    if (
        not isinstance(declared_counts, Mapping)
        or set(declared_counts) != set(PARTITIONS)
        or any(type(declared_counts.get(partition)) is not int for partition in PARTITIONS)
        or dict(declared_counts) != EXPECTED_PARTITION_COUNTS
        or declared_counts != actual_counts
    ):
        raise ValueError("manifest partition counts mismatch")
    return tuple(normalized)


def _review_map(
    review_rows: Sequence[Mapping[str, object]], *, sequences: Sequence[str]
) -> dict[str, bool]:
    if len(review_rows) != len(sequences):
        raise ValueError("owner review count mismatch")
    result: dict[str, bool] = {}
    for expected_sequence, row in zip(sequences, review_rows, strict=True):
        if not isinstance(row, Mapping) or set(row) != {"sequence", "ambiguous"}:
            raise ValueError("owner review row malformed")
        if row.get("sequence") != expected_sequence:
            raise ValueError("owner review sequence mismatch")
        ambiguous = row.get("ambiguous")
        if ambiguous not in {"true", "false"}:
            raise ValueError("owner review ambiguous value malformed")
        if expected_sequence in result:
            raise ValueError("owner review sequences must be unique")
        result[expected_sequence] = ambiguous == "true"
    return result


def _normalized_box(
    shape: Mapping[str, object], *, width: int, height: int, raw_gecko_label_id: int
) -> dict[str, object]:
    if set(shape) != RAW_SHAPE_FIELDS:
        raise ValueError("CVAT shape fields mismatch")
    if shape.get("type") != "rectangle" or shape.get("outside") is not False:
        raise ValueError("CVAT shape contract mismatch")
    if (
        shape.get("occluded") is not False
        or type(shape.get("rotation")) not in {int, float}
        or float(shape["rotation"]) != 0.0
    ):
        raise ValueError("CVAT shape contract mismatch")
    if shape.get("attributes") != [] or shape.get("elements") != []:
        raise ValueError("CVAT shape contract mismatch")
    if (
        shape.get("source") != "manual"
        or type(shape.get("score")) is not int
        or shape["score"] != 1
    ):
        raise ValueError("CVAT shape contract mismatch")
    if (
        type(shape.get("group")) is not int
        or shape["group"] != 0
        or type(shape.get("z_order")) is not int
        or shape["z_order"] != 0
    ):
        raise ValueError("CVAT shape contract mismatch")
    if not _is_int(shape.get("id")) or shape["id"] < 0:
        raise ValueError("CVAT shape id malformed")
    if not _is_int(shape.get("label_id")) or shape["label_id"] != raw_gecko_label_id:
        raise ValueError("CVAT label mismatch")
    points = shape.get("points")
    if not isinstance(points, list) or len(points) != 4 or any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        for value in points
    ):
        raise ValueError("CVAT bbox malformed")
    x1, y1, x2, y2 = (float(value) for value in points)
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("CVAT bbox malformed")
    return {
        "id": shape["id"],
        "type": "rectangle",
        "label_id": NORMALIZED_LABEL_ID,
        "points": [x1, y1, x2, y2],
        "rotation": 0.0,
    }


def normalize_owner_media_export(
    *,
    manifest: Mapping[str, object],
    annotations: Mapping[str, object],
    review_rows: Sequence[Mapping[str, object]],
    raw_cvat_job_id: int,
) -> tuple[dict[str, object], dict[str, object]]:
    """Return a normalized snapshot and safe aggregate after validating all inputs."""
    if not _is_int(raw_cvat_job_id) or raw_cvat_job_id != CVAT_JOB_ID:
        raise ValueError("CVAT job mismatch")
    items = _manifest_items(manifest)
    sequences = tuple(str(item["sequence"]) for item in items)
    ambiguous = _review_map(review_rows, sequences=sequences)
    if not isinstance(annotations, Mapping) or type(annotations.get("version")) is not int:
        raise ValueError("CVAT annotation payload malformed")
    if annotations.get("tracks") != []:
        raise ValueError("CVAT tracks are not supported")
    if annotations.get("tags") != []:
        raise ValueError("CVAT tags are not supported")
    shapes = annotations.get("shapes")
    if not isinstance(shapes, list):
        raise ValueError("CVAT shapes must be a list")

    shapes_by_frame: dict[int, list[Mapping[str, object]]] = defaultdict(list)
    seen_shape_ids: set[int] = set()
    for shape in shapes:
        if not isinstance(shape, Mapping):
            raise ValueError("CVAT shape malformed")
        frame = shape.get("frame")
        if not _is_int(frame) or not 0 <= frame < len(items):
            raise ValueError("CVAT frame mismatch")
        shape_id = shape.get("id")
        if not _is_int(shape_id) or shape_id in seen_shape_ids:
            raise ValueError("CVAT shape id malformed")
        seen_shape_ids.add(shape_id)
        shapes_by_frame[frame].append(shape)

    images: list[dict[str, object]] = []
    partition_counts = {
        partition: {"accepted": 0, "ambiguous": 0, "positive": 0, "negative": 0, "boxes": 0}
        for partition in PARTITIONS
    }
    totals = {"accepted": 0, "ambiguous": 0, "positive": 0, "negative": 0, "boxes": 0}
    for frame, item in enumerate(items):
        sequence = str(item["sequence"])
        width = int(item["width"])
        height = int(item["height"])
        boxes = tuple(
            _normalized_box(
                shape,
                width=width,
                height=height,
                raw_gecko_label_id=RAW_GECKO_LABEL_ID,
            )
            for shape in sorted(shapes_by_frame.get(frame, ()), key=lambda row: int(row["id"]))
        )
        images.append(
            {
                "frame": frame,
                "path": f"images/{sequence}.jpg",
                "width": width,
                "height": height,
                "image_sha256": item["derived_sha256"],
                "partition": item["partition"],
                "boxes": list(boxes),
            }
        )
        counts = partition_counts[str(item["partition"])]
        if ambiguous[sequence]:
            counts["ambiguous"] += 1
            totals["ambiguous"] += 1
            continue
        counts["accepted"] += 1
        totals["accepted"] += 1
        if boxes:
            counts["positive"] += 1
            counts["boxes"] += len(boxes)
            totals["positive"] += 1
            totals["boxes"] += len(boxes)
        else:
            counts["negative"] += 1
            totals["negative"] += 1

    snapshot = {
        "schema": SNAPSHOT_SCHEMA,
        "labels": [{"id": NORMALIZED_LABEL_ID, "name": NORMALIZED_LABEL_NAME}],
        "images": images,
    }
    summary = {
        "status": OUTPUT_STATUS,
        "image_count": len(items),
        "accepted_image_count": totals["accepted"],
        "ambiguous_image_count": totals["ambiguous"],
        "positive_image_count": totals["positive"],
        "negative_image_count": totals["negative"],
        "box_count": totals["boxes"],
        "partition_counts": partition_counts,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }
    return snapshot, summary


def _read_json_bytes(payload: bytes, label: str) -> Mapping[str, object]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _read_review_csv_bytes(payload: bytes) -> list[dict[str, str]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("owner review is not UTF-8") from exc
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames != ["sequence", "ambiguous"]:
        raise ValueError("owner review header malformed")
    return list(reader)


def _write_private_json_new(path: Path, payload: Mapping[str, object]) -> None:
    if path.exists() or not path.parent.is_dir():
        raise ValueError("output must be a new file in an existing directory")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.link(temporary, path)
    except FileExistsError as exc:
        raise ValueError("output already exists") from exc
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--owner-review", type=Path, required=True)
    parser.add_argument("--cvat-job-id", type=int, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-annotations-sha256", required=True)
    parser.add_argument("--expected-owner-review-sha256", required=True)
    parser.add_argument("--snapshot-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    args = parser.parse_args(argv)

    manifest_bytes = args.manifest.read_bytes()
    annotation_bytes = args.annotations.read_bytes()
    review_bytes = args.owner_review.read_bytes()
    for payload, expected, label in (
        (manifest_bytes, args.expected_manifest_sha256, "manifest"),
        (annotation_bytes, args.expected_annotations_sha256, "annotations"),
        (review_bytes, args.expected_owner_review_sha256, "owner review"),
    ):
        if _sha256_bytes(payload) != _require_sha256(expected, f"expected {label} sha256"):
            raise ValueError(f"{label} sha256 mismatch")
    snapshot, summary = normalize_owner_media_export(
        manifest=_read_json_bytes(manifest_bytes, "manifest"),
        annotations=_read_json_bytes(annotation_bytes, "annotations"),
        review_rows=_read_review_csv_bytes(review_bytes),
        raw_cvat_job_id=args.cvat_job_id,
    )
    provenance = {
        "annotations_sha256": _sha256_bytes(annotation_bytes),
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "owner_review_sha256": _sha256_bytes(review_bytes),
        "cvat_job_id": args.cvat_job_id,
        "raw_gecko_label_id": RAW_GECKO_LABEL_ID,
    }
    snapshot["provenance"] = provenance
    summary["provenance"] = provenance
    if args.snapshot_output.exists() or args.summary_output.exists():
        raise ValueError("output already exists")
    _write_private_json_new(args.snapshot_output, snapshot)
    try:
        _write_private_json_new(args.summary_output, summary)
    except Exception:
        args.snapshot_output.unlink(missing_ok=True)
        raise
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate a blinded YOLO26n v2.2 CVAT export without producing training data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


MANIFEST_SCHEMA = "yolo26n-v22-candidate-queue-merged-v1"
SNAPSHOT_SCHEMA = "cvat-task160-owner-snapshot-v1"
APPROVED_LABEL_ID = 1
APPROVED_LABEL_NAME = "gecko"
SHA256_LENGTH = 64


@dataclass(frozen=True)
class CvatValidationResult:
    accepted_sequences: tuple[str, ...]
    ambiguous_sequences: tuple[str, ...]
    positive_image_count: int
    negative_image_count: int
    box_count: int


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != SHA256_LENGTH or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _require_positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _require_nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _require_sequence(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be a nonempty trimmed string")
    return value


def _validate_manifest(
    candidate_manifest: Mapping[str, object],
) -> dict[str, tuple[str, int | None, int | None]]:
    if candidate_manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("manifest schema mismatch")
    if candidate_manifest.get("status") != "V22_CANDIDATE_QUEUE_READY":
        raise ValueError("manifest status mismatch")
    if candidate_manifest.get("prediction_boxes_exposed_to_reviewer") is not False:
        raise ValueError("manifest must remain blind")
    if candidate_manifest.get("human_review_required") is not True:
        raise ValueError("manifest human review gate mismatch")
    if (
        type(candidate_manifest.get("db_write_count")) is not int
        or type(candidate_manifest.get("r2_write_count")) is not int
        or candidate_manifest.get("db_write_count") != 0
        or candidate_manifest.get("r2_write_count") != 0
    ):
        raise ValueError("manifest write audit mismatch")

    frames = candidate_manifest.get("frames")
    if not isinstance(frames, list):
        raise ValueError("manifest frames must be a list")
    if (
        type(candidate_manifest.get("review_frame_count")) is not int
        or candidate_manifest.get("review_frame_count") != len(frames)
    ):
        raise ValueError("manifest frame count mismatch")
    if not frames:
        raise ValueError("manifest frames must not be empty")

    expected: dict[str, tuple[str, int | None, int | None]] = {}
    for frame in frames:
        if not isinstance(frame, Mapping):
            raise ValueError("manifest frame must be an object")
        sequence = _require_sequence(frame.get("sequence"), "manifest sequence")
        if sequence in expected:
            raise ValueError("manifest sequences must be unique")
        image_sha256 = _require_sha256(frame.get("image_sha256"), "manifest image sha256")
        width_value = frame.get("width")
        height_value = frame.get("height")
        if (width_value is None) != (height_value is None):
            raise ValueError("manifest frame dimensions must be paired")
        if width_value is None:
            width = None
            height = None
        else:
            try:
                width = _require_positive_int(width_value, "manifest frame dimensions")
                height = _require_positive_int(height_value, "manifest frame dimensions")
            except ValueError as exc:
                raise ValueError("manifest frame dimensions mismatch") from exc
        expected[sequence] = (image_sha256, width, height)
    return expected


def _validate_image_metadata(
    image_metadata: Mapping[str, Mapping[str, object]],
    *,
    manifest_images: Mapping[str, tuple[str, int | None, int | None]],
) -> dict[str, tuple[str, int, int]]:
    if set(image_metadata) != set(manifest_images):
        raise ValueError("review frame sequences must match manifest")
    actual_images: dict[str, tuple[str, int, int]] = {}
    seen_hashes: set[str] = set()
    for sequence, manifest_image in manifest_images.items():
        metadata = image_metadata.get(sequence)
        if not isinstance(metadata, Mapping):
            raise ValueError("review frame metadata malformed")
        if metadata.get("filename") != f"{sequence}.jpg":
            raise ValueError("review frame filename mismatch")
        actual_sha256 = _require_sha256(metadata.get("image_sha256"), "review frame image sha256")
        try:
            actual_width = _require_positive_int(metadata.get("width"), "review frame dimensions")
            actual_height = _require_positive_int(metadata.get("height"), "review frame dimensions")
        except ValueError as exc:
            raise ValueError("review frame dimensions mismatch") from exc
        manifest_sha256, manifest_width, manifest_height = manifest_image
        if actual_sha256 != manifest_sha256:
            raise ValueError("manifest image sha256 mismatch")
        if manifest_width is not None and (actual_width, actual_height) != (
            manifest_width,
            manifest_height,
        ):
            raise ValueError("manifest image dimensions mismatch")
        if actual_sha256 in seen_hashes:
            raise ValueError("review frame image sha256 must be unique")
        seen_hashes.add(actual_sha256)
        actual_images[sequence] = (actual_sha256, actual_width, actual_height)
    return actual_images


def _validate_label_contract(snapshot: Mapping[str, object]) -> None:
    labels = snapshot.get("labels")
    if not isinstance(labels, list) or len(labels) != 1:
        raise ValueError("snapshot label contract mismatch")
    label = labels[0]
    if not isinstance(label, Mapping):
        raise ValueError("snapshot label contract mismatch")
    if (
        type(label.get("id")) is not int
        or label.get("id") != APPROVED_LABEL_ID
        or label.get("name") != APPROVED_LABEL_NAME
    ):
        raise ValueError("snapshot label contract mismatch")


def _sequence_from_image_path(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("snapshot image path malformed")
    path = Path(value)
    if path.name != value.split("/")[-1] or path.suffix.lower() != ".jpg":
        raise ValueError("snapshot image path malformed")
    return _require_sequence(path.stem, "snapshot sequence")


def _validate_box(box: object, *, width: int, height: int) -> None:
    if not isinstance(box, Mapping):
        raise ValueError("snapshot box malformed")
    allowed_fields = {"type", "label_id", "points", "id", "rotation"}
    if not set(box) <= allowed_fields:
        if "attributes" in box:
            raise ValueError("snapshot attributes are not supported")
        raise ValueError("snapshot rectangle fields are not supported")
    if box.get("type") != "rectangle":
        raise ValueError("only rectangle annotations are allowed")
    if type(box.get("label_id")) is not int or box.get("label_id") != APPROVED_LABEL_ID:
        raise ValueError("snapshot label contract mismatch")
    if "id" in box:
        _require_nonnegative_int(box["id"], "snapshot shape id")
    if "rotation" in box:
        rotation = box["rotation"]
        if (
            type(rotation) not in {int, float}
            or not math.isfinite(float(rotation))
            or float(rotation) != 0.0
        ):
            raise ValueError("snapshot rectangle rotation must be numeric zero")
    points = box.get("points")
    if not isinstance(points, list) or len(points) != 4:
        raise ValueError("snapshot bbox malformed")
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        for value in points
    ):
        raise ValueError("snapshot bbox malformed")
    x1, y1, x2, y2 = (float(value) for value in points)
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("snapshot bbox malformed")


def _validate_snapshot(
    snapshot: Mapping[str, object],
    *,
    actual_images: Mapping[str, tuple[str, int, int]],
) -> dict[str, tuple[dict[str, object], ...]]:
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError("snapshot schema mismatch")
    _validate_label_contract(snapshot)
    images = snapshot.get("images")
    if not isinstance(images, list):
        raise ValueError("snapshot images must be a list")

    boxes_by_sequence: dict[str, tuple[dict[str, object], ...]] = {}
    frame_ids: set[int] = set()
    for image in images:
        if not isinstance(image, Mapping):
            raise ValueError("snapshot image malformed")
        frame_id = image.get("frame")
        try:
            _require_nonnegative_int(frame_id, "snapshot frame identifiers")
        except ValueError as exc:
            raise ValueError("snapshot frame identifiers malformed") from exc
        if frame_id in frame_ids:
            raise ValueError("snapshot frame identifiers must be unique")
        frame_ids.add(frame_id)
        sequence = _sequence_from_image_path(image.get("path"))
        if sequence in boxes_by_sequence:
            raise ValueError("snapshot sequences must map uniquely")
        try:
            width = _require_positive_int(image.get("width"), "snapshot image dimensions")
            height = _require_positive_int(image.get("height"), "snapshot image dimensions")
        except ValueError as exc:
            raise ValueError("snapshot image dimensions mismatch") from exc
        if sequence not in actual_images:
            raise ValueError("snapshot sequences must match manifest")
        actual_sha256, actual_width, actual_height = actual_images[sequence]
        if _require_sha256(image.get("image_sha256"), "snapshot image sha256") != actual_sha256:
            raise ValueError("snapshot image sha256 mismatch")
        if (width, height) != (actual_width, actual_height):
            raise ValueError("snapshot image dimensions mismatch")
        boxes = image.get("boxes")
        if not isinstance(boxes, list):
            raise ValueError("snapshot boxes must be a list")
        normalized_boxes: list[dict[str, object]] = []
        for box in boxes:
            _validate_box(box, width=width, height=height)
            normalized_boxes.append(dict(box))
        boxes_by_sequence[sequence] = tuple(normalized_boxes)
    if set(boxes_by_sequence) != set(actual_images):
        raise ValueError("snapshot sequences must match manifest")
    return boxes_by_sequence


def _validate_review_rows(
    review_rows: Sequence[Mapping[str, object]], *, expected_sequences: set[str]
) -> dict[str, bool]:
    review_by_sequence: dict[str, bool] = {}
    for row in review_rows:
        if not isinstance(row, Mapping) or set(row) != {"sequence", "ambiguous"}:
            raise ValueError("owner review row malformed")
        sequence = _require_sequence(row.get("sequence"), "owner review sequence")
        ambiguous = row.get("ambiguous")
        if ambiguous not in {"true", "false"} or not isinstance(ambiguous, str):
            raise ValueError("owner review ambiguous must be true or false")
        if sequence in review_by_sequence:
            raise ValueError("review sequences must map uniquely")
        review_by_sequence[sequence] = ambiguous == "true"
    if set(review_by_sequence) != expected_sequences:
        raise ValueError("review sequences must match manifest")
    return review_by_sequence


def validate_export(
    *,
    candidate_manifest: Mapping[str, object],
    snapshot: Mapping[str, object],
    image_metadata: Mapping[str, Mapping[str, object]],
    review_rows: Sequence[Mapping[str, object]],
) -> CvatValidationResult:
    """Return only immutable accepted/ambiguous results after full validation."""
    if not isinstance(candidate_manifest, Mapping) or not isinstance(snapshot, Mapping):
        raise ValueError("manifest and snapshot must be objects")
    if not isinstance(image_metadata, Mapping):
        raise ValueError("review frame metadata must be an object")
    manifest_images = _validate_manifest(candidate_manifest)
    actual_images = _validate_image_metadata(image_metadata, manifest_images=manifest_images)
    boxes_by_sequence = _validate_snapshot(snapshot, actual_images=actual_images)
    review_by_sequence = _validate_review_rows(
        review_rows, expected_sequences=set(manifest_images)
    )

    accepted: list[str] = []
    ambiguous: list[str] = []
    positive_image_count = 0
    negative_image_count = 0
    box_count = 0
    for sequence in manifest_images:
        boxes = boxes_by_sequence[sequence]
        if review_by_sequence[sequence]:
            ambiguous.append(sequence)
            continue
        accepted.append(sequence)
        if boxes:
            positive_image_count += 1
            box_count += len(boxes)
        else:
            negative_image_count += 1
    return CvatValidationResult(
        accepted_sequences=tuple(accepted),
        ambiguous_sequences=tuple(ambiguous),
        positive_image_count=positive_image_count,
        negative_image_count=negative_image_count,
        box_count=box_count,
    )


def _review_frame_state(
    review_frames_dir: Path,
) -> tuple[tuple[str, int, int, int, int, int], ...]:
    paths = list(review_frames_dir.iterdir())
    state: list[tuple[str, int, int, int, int, int]] = []
    for path in paths:
        if path.is_symlink():
            raise ValueError("review frames directory contains a non-file")
        try:
            info = path.stat()
        except OSError as exc:
            raise ValueError("review frames directory changed during scan") from exc
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("review frames directory contains a non-file")
        state.append(
            (
                path.name,
                info.st_dev,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            )
        )
    return tuple(sorted(state))


def scan_review_frames(
    review_frames_dir: Path,
    *,
    expected_sequences: Sequence[str],
) -> dict[str, dict[str, object]]:
    """Read the blinded JPEG set only after its expected filenames are known."""
    if not review_frames_dir.is_dir():
        raise ValueError("review frames directory is missing")
    if len(set(expected_sequences)) != len(expected_sequences):
        raise ValueError("expected sequences must be unique")
    expected_filenames = {f"{sequence}.jpg" for sequence in expected_sequences}
    before_state = _review_frame_state(review_frames_dir)
    actual_filenames = {entry[0] for entry in before_state}
    if actual_filenames != expected_filenames or len(before_state) != len(expected_filenames):
        raise ValueError("review frame filenames must exactly match manifest")

    from PIL import Image

    metadata: dict[str, dict[str, object]] = {}
    for sequence in expected_sequences:
        filename = f"{sequence}.jpg"
        path = review_frames_dir / filename
        try:
            image_bytes = path.read_bytes()
            with Image.open(io.BytesIO(image_bytes)) as image:
                if image.format != "JPEG":
                    raise ValueError("review frame is not JPEG")
                image.load()
                width, height = image.size
        except (OSError, ValueError) as exc:
            raise ValueError("review frame JPEG decode failed") from exc
        metadata[sequence] = {
            "filename": filename,
            "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
            "width": width,
            "height": height,
        }
    if _review_frame_state(review_frames_dir) != before_state:
        raise ValueError("review frames changed during scan")
    return metadata


def _read_json_bytes(payload_bytes: bytes, label: str) -> Mapping[str, object]:
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must be an object")
    return payload


def _read_json(path: Path, label: str) -> Mapping[str, object]:
    if not path.is_file():
        raise ValueError(f"{label} is missing")
    try:
        payload_bytes = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{label} is unreadable") from exc
    return _read_json_bytes(payload_bytes, label)


def _read_review_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError("owner review is missing")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["sequence", "ambiguous"]:
            raise ValueError("owner review header malformed")
        return list(reader)


def _safe_summary(result: CvatValidationResult) -> dict[str, object]:
    return {
        "status": "V22_HUMAN_REVIEW_ACCEPTED",
        "positive_image_count": result.positive_image_count,
        "negative_image_count": result.negative_image_count,
        "ambiguous_image_count": len(result.ambiguous_sequences),
        "box_count": result.box_count,
    }


def _write_private_summary(path: Path, summary: Mapping[str, object]) -> None:
    if path.exists() or not path.parent.is_dir():
        raise ValueError("summary output must be a new path in an existing directory")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.chmod(0o600)
        try:
            os.link(temporary_path, path)
        except FileExistsError as exc:
            raise ValueError("summary output already exists") from exc
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--owner-review", type=Path, required=True)
    parser.add_argument("--review-frames-dir", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    args = parser.parse_args(argv)

    expected_manifest_sha256 = _require_sha256(
        args.expected_manifest_sha256, "expected manifest sha256"
    )
    if not args.candidate_manifest.is_file():
        raise ValueError("manifest sha256 mismatch")
    try:
        manifest_bytes = args.candidate_manifest.read_bytes()
    except OSError as exc:
        raise ValueError("manifest sha256 mismatch") from exc
    if hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha256:
        raise ValueError("manifest sha256 mismatch")
    candidate_manifest = _read_json_bytes(manifest_bytes, "candidate manifest")
    manifest_images = _validate_manifest(candidate_manifest)
    result = validate_export(
        candidate_manifest=candidate_manifest,
        snapshot=_read_json(args.snapshot, "snapshot"),
        image_metadata=scan_review_frames(
            args.review_frames_dir, expected_sequences=tuple(manifest_images)
        ),
        review_rows=_read_review_csv(args.owner_review),
    )
    summary = _safe_summary(result)
    _write_private_summary(args.summary_output, summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

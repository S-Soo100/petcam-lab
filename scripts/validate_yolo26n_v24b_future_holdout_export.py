"""Validate and freeze a blinded YOLO26n v2.4b future-holdout CVAT export."""

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
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

try:
    from scripts.run_yolo26n_v24b_postprocess import (
        _OwnedArtifact,
        _artifact_is_self_owned,
        _capture_owned_artifact,
        _cleanup_if_self_owned,
        _owned_at_path,
    )
except ModuleNotFoundError:  # Direct ``python scripts/...py`` execution.
    from run_yolo26n_v24b_postprocess import (  # type: ignore[no-redef]
        _OwnedArtifact,
        _artifact_is_self_owned,
        _capture_owned_artifact,
        _cleanup_if_self_owned,
        _owned_at_path,
    )


MANIFEST_SCHEMA = "yolo26n-v24b-future-holdout-v1"
MANIFEST_STATUS = "V24B_FUTURE_HOLDOUT_READY"
SNAPSHOT_SCHEMA = "cvat-task160-owner-snapshot-v1"
ACCEPTED_STATUS = "V24B_FUTURE_HOLDOUT_ACCEPTED"
REPLACEMENT_STATUS = "V24B_FUTURE_HOLDOUT_RESERVE_REPLACEMENT_REQUIRED"
EXPECTED_SEQUENCES = tuple(f"H{ordinal:04d}" for ordinal in range(1, 121))
REVIEW_HEADER = (
    "sequence",
    "filename",
    "presence",
    "source_ref",
    "camera_id",
    "camera_night",
    "source_sequence",
    "image_sha256",
    "width",
    "height",
    "dhash",
)
MANIFEST_FIELDS = {
    "schema",
    "status",
    "pool_ledger_sha256_pre",
    "pool_ledger_sha256_post",
    "presence_screen_sha256_pre",
    "presence_screen_sha256_post",
    "review_index_sha256",
    "image_count",
    "positive_count",
    "negative_count",
    "ambiguous_count",
    "prediction_prefill_count",
    "records",
    "db_write_count",
    "r2_get_count",
    "r2_write_count",
    "service_write_count",
    "git_write_count",
}
MANIFEST_RECORD_FIELDS = {
    "sequence",
    "filename",
    "presence",
    "image_sha256",
    "width",
    "height",
}
SNAPSHOT_FIELDS = {"schema", "labels", "images"}
SNAPSHOT_IMAGE_FIELDS = {
    "frame",
    "path",
    "width",
    "height",
    "image_sha256",
    "boxes",
}
RECTANGLE_FIELDS = {"type", "label_id", "points"}
MAX_JSON_BYTES = 1024 * 1024
MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_JPEG_BYTES = 32 * 1024 * 1024
LOCK_NAME = ".future-holdout-export.started.private.json"


def _require_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _require_exact_int(value: object, expected: int, label: str) -> int:
    if type(value) is not int or value != expected:
        raise ValueError(f"{label} mismatch")
    return value


def _require_positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} mismatch")
    return value


def _require_nonempty_string(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        raise ValueError(f"{label} malformed")
    return value


def _parse_canonical_nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError(f"{label} malformed")
    parsed = int(value)
    if str(parsed) != value:
        raise ValueError(f"{label} malformed")
    return parsed


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("JSON duplicate key")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"JSON nonfinite number: {value}")


def _reject_nonfinite_values(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON nonfinite number")
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_nonfinite_values(item)
    elif isinstance(value, list):
        for item in value:
            _reject_nonfinite_values(item)


def _parse_json_object(payload: bytes, label: str) -> Mapping[str, object]:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
        _reject_nonfinite_values(value)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"{label} is invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _stat_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read_regular_file(
    path: Path,
    *,
    label: str,
    maximum_bytes: int,
    require_mode_0600: bool = False,
) -> bytes:
    """Read one bounded regular-file payload and pin its path identity around the read."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"{label} is missing or unsafe") from exc
    try:
        before_fd = os.fstat(descriptor)
        try:
            before_path = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise ValueError(f"{label} changed during read") from exc
        if not stat.S_ISREG(before_fd.st_mode) or not stat.S_ISREG(before_path.st_mode):
            raise ValueError(f"{label} must be a regular file")
        if _stat_identity(before_fd) != _stat_identity(before_path):
            raise ValueError(f"{label} changed during read")
        if require_mode_0600 and stat.S_IMODE(before_fd.st_mode) != 0o600:
            raise ValueError(f"{label} must have mode 0600")
        if before_fd.st_size > maximum_bytes:
            raise ValueError(f"{label} exceeds size limit")
        payload = os.read(descriptor, maximum_bytes + 1)
        if len(payload) > maximum_bytes or len(payload) != before_fd.st_size:
            raise ValueError(f"{label} changed during read")
        after_fd = os.fstat(descriptor)
        try:
            after_path = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise ValueError(f"{label} changed during read") from exc
        if (
            _stat_identity(after_fd) != _stat_identity(before_fd)
            or _stat_identity(after_path) != _stat_identity(before_fd)
        ):
            raise ValueError(f"{label} changed during read")
        return payload
    finally:
        os.close(descriptor)


def _validate_manifest(candidate_manifest: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    if set(candidate_manifest) != MANIFEST_FIELDS:
        raise ValueError("manifest fields mismatch")
    if candidate_manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("manifest schema mismatch")
    if candidate_manifest.get("status") != MANIFEST_STATUS:
        raise ValueError("manifest status mismatch")
    _require_sha256(candidate_manifest.get("pool_ledger_sha256_pre"), "pool ledger sha256")
    _require_sha256(candidate_manifest.get("pool_ledger_sha256_post"), "pool ledger sha256")
    if candidate_manifest["pool_ledger_sha256_pre"] != candidate_manifest["pool_ledger_sha256_post"]:
        raise ValueError("pool ledger sha256 mismatch")
    _require_sha256(candidate_manifest.get("presence_screen_sha256_pre"), "presence screen sha256")
    _require_sha256(candidate_manifest.get("presence_screen_sha256_post"), "presence screen sha256")
    if candidate_manifest["presence_screen_sha256_pre"] != candidate_manifest["presence_screen_sha256_post"]:
        raise ValueError("presence screen sha256 mismatch")
    _require_sha256(candidate_manifest.get("review_index_sha256"), "review index sha256")
    _require_exact_int(candidate_manifest.get("image_count"), 120, "manifest count")
    _require_exact_int(candidate_manifest.get("positive_count"), 60, "positive count")
    _require_exact_int(candidate_manifest.get("negative_count"), 60, "negative count")
    _require_exact_int(candidate_manifest.get("ambiguous_count"), 0, "ambiguous count")
    _require_exact_int(
        candidate_manifest.get("prediction_prefill_count"), 0, "prediction prefill"
    )
    for field in (
        "db_write_count",
        "r2_get_count",
        "r2_write_count",
        "service_write_count",
        "git_write_count",
    ):
        _require_exact_int(candidate_manifest.get(field), 0, "manifest write audit")
    raw_records = candidate_manifest.get("records")
    if not isinstance(raw_records, list) or len(raw_records) != 120:
        raise ValueError("manifest count mismatch")
    records: list[dict[str, object]] = []
    seen_hashes: set[str] = set()
    presences: list[str] = []
    for ordinal, raw_record in enumerate(raw_records, 1):
        if not isinstance(raw_record, Mapping) or set(raw_record) != MANIFEST_RECORD_FIELDS:
            raise ValueError("manifest record fields mismatch")
        expected_sequence = EXPECTED_SEQUENCES[ordinal - 1]
        if raw_record.get("sequence") != expected_sequence:
            raise ValueError("manifest record order mismatch")
        if raw_record.get("filename") != f"{expected_sequence}.jpg":
            raise ValueError("manifest filename mismatch")
        presence = raw_record.get("presence")
        if presence not in {"positive", "negative"} or not isinstance(presence, str):
            raise ValueError("manifest presence mismatch")
        image_sha256 = _require_sha256(raw_record.get("image_sha256"), "manifest image sha256")
        if image_sha256 in seen_hashes:
            raise ValueError("manifest image sha256 must be unique")
        seen_hashes.add(image_sha256)
        width = _require_positive_int(raw_record.get("width"), "manifest dimensions")
        height = _require_positive_int(raw_record.get("height"), "manifest dimensions")
        presences.append(presence)
        records.append(
            {
                "sequence": expected_sequence,
                "filename": f"{expected_sequence}.jpg",
                "presence": presence,
                "image_sha256": image_sha256,
                "width": width,
                "height": height,
            }
        )
    if presences.count("positive") != 60:
        raise ValueError("positive count mismatch")
    if presences.count("negative") != 60:
        raise ValueError("negative count mismatch")
    return tuple(records)


def _validate_image_metadata(
    image_metadata: Mapping[str, Mapping[str, object]],
    records: Sequence[Mapping[str, object]],
) -> None:
    if set(image_metadata) != set(EXPECTED_SEQUENCES):
        raise ValueError("review frame image set mismatch")
    for record in records:
        sequence = str(record["sequence"])
        metadata = image_metadata.get(sequence)
        if not isinstance(metadata, Mapping) or set(metadata) != {
            "filename",
            "image_sha256",
            "width",
            "height",
        }:
            raise ValueError("review frame metadata malformed")
        if metadata.get("filename") != record["filename"]:
            raise ValueError("review frame filename mismatch")
        if metadata.get("image_sha256") != record["image_sha256"]:
            raise ValueError("review frame image sha256 mismatch")
        width = _require_positive_int(metadata.get("width"), "review frame dimensions")
        height = _require_positive_int(metadata.get("height"), "review frame dimensions")
        if width != record["width"] or height != record["height"]:
            raise ValueError("review frame dimensions mismatch")


def _validate_review_index(
    review_index_rows: Sequence[Mapping[str, object]],
    records: Sequence[Mapping[str, object]],
) -> None:
    if isinstance(review_index_rows, (str, bytes)) or len(review_index_rows) != 120:
        raise ValueError("review index count mismatch")
    source_counts: Counter[str] = Counter()
    night_counts: Counter[str] = Counter()
    camera_ids: set[str] = set()
    nights: set[str] = set()
    source_dhashes: dict[str, list[int]] = defaultdict(list)
    source_sequences: set[str] = set()
    for ordinal, (row, record) in enumerate(zip(review_index_rows, records, strict=True), 1):
        if not isinstance(row, Mapping) or set(row) != set(REVIEW_HEADER):
            raise ValueError("review index fields mismatch")
        expected_sequence = EXPECTED_SEQUENCES[ordinal - 1]
        if row.get("sequence") != expected_sequence:
            raise ValueError("review index order mismatch")
        try:
            width = _parse_canonical_nonnegative_int(row.get("width"), "review index dimensions")
            height = _parse_canonical_nonnegative_int(row.get("height"), "review index dimensions")
        except ValueError as exc:
            raise ValueError("review index manifest mismatch") from exc
        for field in ("sequence", "filename", "presence", "image_sha256"):
            if row.get(field) != record[field]:
                raise ValueError("review index manifest mismatch")
        if width != record["width"] or height != record["height"]:
            raise ValueError("review index manifest mismatch")
        source_ref = _require_nonempty_string(row.get("source_ref"), "source identity")
        camera_id = _require_nonempty_string(row.get("camera_id"), "source identity")
        camera_night = _require_nonempty_string(row.get("camera_night"), "source identity")
        source_sequence = _require_nonempty_string(row.get("source_sequence"), "source identity")
        if source_sequence in source_sequences:
            raise ValueError("source identity must be unique")
        source_sequences.add(source_sequence)
        dhash = _parse_canonical_nonnegative_int(row.get("dhash"), "dhash")
        if dhash > (1 << 64) - 1:
            raise ValueError("dhash malformed")
        source_counts[source_ref] += 1
        night_counts[camera_night] += 1
        camera_ids.add(camera_id)
        nights.add(camera_night)
        source_dhashes[source_ref].append(dhash)
    if len(camera_ids) < 3:
        raise ValueError("review index requires at least 3 cameras")
    if len(nights) < 6:
        raise ValueError("review index requires at least 6 nights")
    if source_counts and max(source_counts.values()) > 2:
        raise ValueError("review index source cap exceeded")
    if night_counts and max(night_counts.values()) > 20:
        raise ValueError("review index night cap exceeded")
    for hashes in source_dhashes.values():
        for left_index, left in enumerate(hashes):
            for right in hashes[left_index + 1 :]:
                if (left ^ right).bit_count() <= 2:
                    raise ValueError("review index same-source dHash distance must be >2")


def _validate_snapshot(
    snapshot: Mapping[str, object], records: Sequence[Mapping[str, object]]
) -> tuple[dict[str, object], ...]:
    if set(snapshot) != SNAPSHOT_FIELDS:
        raise ValueError("snapshot fields mismatch")
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError("snapshot schema mismatch")
    labels = snapshot.get("labels")
    if (
        not isinstance(labels, list)
        or labels != [{"id": 1, "name": "gecko"}]
        or type(labels[0].get("id")) is not int
    ):
        raise ValueError("snapshot label contract mismatch")
    raw_images = snapshot.get("images")
    if not isinstance(raw_images, list) or len(raw_images) != 120:
        raise ValueError("snapshot image set mismatch")
    normalized_records: list[dict[str, object]] = []
    for ordinal, (raw_image, record) in enumerate(zip(raw_images, records, strict=True), 1):
        if not isinstance(raw_image, Mapping) or set(raw_image) != SNAPSHOT_IMAGE_FIELDS:
            raise ValueError("snapshot image fields mismatch")
        expected_filename = str(record["filename"])
        raw_path = raw_image.get("path")
        if not isinstance(raw_path, str) or Path(raw_path).name != expected_filename:
            raise ValueError("snapshot image order mismatch")
        if raw_path != f"images/{expected_filename}":
            raise ValueError("snapshot image path malformed")
        if type(raw_image.get("frame")) is not int or raw_image.get("frame") != ordinal - 1:
            raise ValueError("snapshot frame order mismatch")
        if raw_image.get("image_sha256") != record["image_sha256"]:
            raise ValueError("snapshot image sha256 mismatch")
        width = _require_positive_int(raw_image.get("width"), "snapshot image dimensions")
        height = _require_positive_int(raw_image.get("height"), "snapshot image dimensions")
        if width != record["width"] or height != record["height"]:
            raise ValueError("snapshot image dimensions mismatch")
        boxes = raw_image.get("boxes")
        if not isinstance(boxes, list):
            raise ValueError("snapshot boxes must be a list")
        normalized_boxes: list[dict[str, object]] = []
        for box in boxes:
            if not isinstance(box, Mapping) or set(box) != RECTANGLE_FIELDS:
                raise ValueError("snapshot rectangle fields are forbidden")
            if box.get("type") != "rectangle":
                raise ValueError("only static rectangles are allowed")
            if type(box.get("label_id")) is not int or box.get("label_id") != 1:
                raise ValueError("snapshot label contract mismatch")
            points = box.get("points")
            if (
                not isinstance(points, list)
                or len(points) != 4
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    for value in points
                )
            ):
                raise ValueError("snapshot bbox malformed")
            x1, y1, x2, y2 = (float(value) for value in points)
            if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                raise ValueError("snapshot bbox malformed")
            normalized_boxes.append({"label_id": 1, "points": [x1, y1, x2, y2]})
        if record["presence"] == "positive" and not normalized_boxes:
            raise ValueError("positive image requires at least one bbox")
        if record["presence"] == "negative" and normalized_boxes:
            raise ValueError("negative image must not contain a bbox")
        normalized_records.append({**dict(record), "boxes": normalized_boxes})
    return tuple(normalized_records)


def validate_export(
    *,
    candidate_manifest: Mapping[str, object],
    snapshot: Mapping[str, object],
    image_metadata: Mapping[str, Mapping[str, object]],
    review_index_rows: Sequence[Mapping[str, object]],
    ambiguous_sequences: Sequence[str],
) -> dict[str, object]:
    """Validate the complete immutable contract without exposing private source identity."""
    if not isinstance(candidate_manifest, Mapping) or not isinstance(snapshot, Mapping):
        raise ValueError("manifest and snapshot must be objects")
    if not isinstance(image_metadata, Mapping):
        raise ValueError("review frame metadata must be an object")
    records = _validate_manifest(candidate_manifest)
    if isinstance(ambiguous_sequences, (str, bytes)):
        raise ValueError("owner ambiguous rows malformed")
    ambiguous = tuple(ambiguous_sequences)
    if len(set(ambiguous)) != len(ambiguous) or any(
        sequence not in EXPECTED_SEQUENCES for sequence in ambiguous
    ):
        raise ValueError("owner ambiguous rows malformed")
    if ambiguous:
        raise ValueError(REPLACEMENT_STATUS)
    _validate_image_metadata(image_metadata, records)
    _validate_review_index(review_index_rows, records)
    normalized_records = _validate_snapshot(snapshot, records)
    return {
        "schema": "yolo26n-v24b-future-holdout-gt-v1",
        "status": ACCEPTED_STATUS,
        "image_count": 120,
        "positive_image_count": 60,
        "negative_image_count": 60,
        "ambiguous_image_count": 0,
        "box_count": sum(len(record["boxes"]) for record in normalized_records),
        "records": list(normalized_records),
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "git_write_count": 0,
    }


def _directory_state(
    directory_descriptor: int,
) -> tuple[tuple[str, int, int, int, int, int], ...]:
    try:
        names = os.listdir(directory_descriptor)
    except OSError as exc:
        raise ValueError("review frames directory changed during scan") from exc
    state: list[tuple[str, int, int, int, int, int]] = []
    for name in names:
        try:
            info = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("review frames directory changed during scan") from exc
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("review frames directory contains a non-file")
        if info.st_size > MAX_JPEG_BYTES:
            raise ValueError("review frame exceeds size limit")
        state.append((name, *_stat_identity(info)))
    return tuple(sorted(state))


def _read_directory_file(
    directory_descriptor: int,
    filename: str,
    expected_state: tuple[str, int, int, int, int, int],
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(filename, flags, dir_fd=directory_descriptor)
    except OSError as exc:
        raise ValueError("review frames changed during scan") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or (filename, *_stat_identity(before)) != expected_state:
            raise ValueError("review frames changed during scan")
        payload = os.read(descriptor, MAX_JPEG_BYTES + 1)
        if len(payload) != before.st_size or len(payload) > MAX_JPEG_BYTES:
            raise ValueError("review frames changed during scan")
        after = os.fstat(descriptor)
        try:
            after_path = os.stat(
                filename, dir_fd=directory_descriptor, follow_symlinks=False
            )
        except OSError as exc:
            raise ValueError("review frames changed during scan") from exc
        if (
            _stat_identity(after) != _stat_identity(before)
            or _stat_identity(after_path) != _stat_identity(before)
        ):
            raise ValueError("review frames changed during scan")
        return payload
    finally:
        os.close(descriptor)


def scan_review_frames(review_frames_dir: Path) -> dict[str, dict[str, object]]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_descriptor = os.open(review_frames_dir, flags)
    except OSError as exc:
        raise ValueError("review frames directory is missing or unsafe") from exc
    try:
        directory_before = os.fstat(directory_descriptor)
        if not stat.S_ISDIR(directory_before.st_mode):
            raise ValueError("review frames directory is unsafe")
        before_state = _directory_state(directory_descriptor)
        expected_filenames = tuple(f"{sequence}.jpg" for sequence in EXPECTED_SEQUENCES)
        if tuple(entry[0] for entry in before_state) != expected_filenames:
            raise ValueError("review frame filenames must exactly match manifest")
        by_name = {entry[0]: entry for entry in before_state}
        metadata: dict[str, dict[str, object]] = {}
        for sequence in EXPECTED_SEQUENCES:
            filename = f"{sequence}.jpg"
            payload = _read_directory_file(directory_descriptor, filename, by_name[filename])
            try:
                from PIL import Image

                with Image.open(io.BytesIO(payload)) as image:
                    if image.format != "JPEG":
                        raise ValueError("review frame is not JPEG")
                    image.load()
                    width, height = image.size
            except (OSError, ValueError) as exc:
                raise ValueError("review frame JPEG decode failed") from exc
            metadata[sequence] = {
                "filename": filename,
                "image_sha256": hashlib.sha256(payload).hexdigest(),
                "width": width,
                "height": height,
            }
        directory_after = os.fstat(directory_descriptor)
        if (
            _stat_identity(directory_after) != _stat_identity(directory_before)
            or _directory_state(directory_descriptor) != before_state
        ):
            raise ValueError("review frames changed during scan")
        return metadata
    finally:
        os.close(directory_descriptor)


def _read_review_index(payload: bytes) -> list[dict[str, object]]:
    try:
        text = payload.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if tuple(reader.fieldnames or ()) != REVIEW_HEADER:
            raise ValueError("review index header mismatch")
        rows = list(reader)
    except UnicodeDecodeError as exc:
        raise ValueError("review index is invalid UTF-8") from exc
    except csv.Error as exc:
        raise ValueError("review index CSV malformed") from exc
    if any(None in row or None in row.values() for row in rows):
        raise ValueError("review index row malformed")
    return [dict(row) for row in rows]


def _read_ambiguous(payload: bytes) -> tuple[str, ...]:
    if payload == b"":
        return ()
    try:
        rows = list(
            csv.reader(
                io.StringIO(payload.decode("utf-8"), newline=""), strict=True
            )
        )
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("owner ambiguous CSV malformed") from exc
    if not rows or rows[0] != ["sequence"]:
        raise ValueError("owner ambiguous header malformed")
    sequences: list[str] = []
    for row in rows[1:]:
        if len(row) != 1 or row[0] not in EXPECTED_SEQUENCES:
            raise ValueError("owner ambiguous row malformed")
        if row[0] in sequences:
            raise ValueError("owner ambiguous row duplicate")
        sequences.append(row[0])
    return tuple(sequences)


def _json_bytes(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _write_staging_file(path: Path, payload: bytes) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.staging-", dir=path.parent
    )
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _link_new(source: Path, target: Path) -> None:
    os.link(source, target)


def _owned_identity(path: Path) -> _OwnedArtifact:
    return _capture_owned_artifact(path)


def _unlink_if_owned(path: Path, identity: _OwnedArtifact) -> None:
    # Rollback uses the repository's exchange-and-quarantine primitive. A
    # check-then-unlink could erase a rival that replaces this pathname.
    _cleanup_if_self_owned(_owned_at_path(identity, path))


def _require_owned_artifacts(
    artifacts: Sequence[tuple[_OwnedArtifact, str]],
) -> None:
    for artifact, label in artifacts:
        if not _artifact_is_self_owned(artifact):
            raise ValueError(f"{label} ownership changed")


def _cleanup_self_owned(artifacts: Sequence[_OwnedArtifact]) -> None:
    for artifact in artifacts:
        _cleanup_if_self_owned(artifact)


def _claim_one_shot_lock(path: Path) -> _OwnedArtifact:
    temporary = _write_staging_file(
        path,
        _json_bytes(
            {
                "schema": "yolo26n-v24b-future-holdout-export-started-lock-v1",
                "status": "STARTED",
            }
        ),
    )
    temporary_identity = _owned_identity(temporary)
    published_identity = _owned_at_path(temporary_identity, path)
    try:
        try:
            _link_new(temporary, path)
        except FileExistsError as exc:
            raise FileExistsError("future holdout export validation is one-shot") from exc
        _require_owned_artifacts(((published_identity, "one-shot lock"),))
        return published_identity
    finally:
        _unlink_if_owned(temporary, temporary_identity)


def _publish_json_pair(
    normalized_path: Path,
    normalized: Mapping[str, object],
    summary_path: Path,
    summary: Mapping[str, object],
    *,
    guards: Sequence[tuple[_OwnedArtifact, str]],
) -> tuple[_OwnedArtifact, _OwnedArtifact]:
    for path in (normalized_path, summary_path):
        if path.exists() or path.is_symlink():
            raise FileExistsError("future holdout export output is no-overwrite")
    normalized_temporary = _write_staging_file(normalized_path, _json_bytes(normalized))
    try:
        summary_temporary = _write_staging_file(summary_path, _json_bytes(summary))
    except BaseException:
        normalized_temporary.unlink(missing_ok=True)
        raise
    normalized_identity = _owned_identity(normalized_temporary)
    summary_identity = _owned_identity(summary_temporary)
    normalized_public = _owned_at_path(normalized_identity, normalized_path)
    summary_public = _owned_at_path(summary_identity, summary_path)
    normalized_published = False
    summary_published = False
    try:
        _require_owned_artifacts(guards)
        _link_new(normalized_temporary, normalized_path)
        normalized_published = True
        _require_owned_artifacts(
            (*guards, (normalized_public, "normalized output"))
        )
        _link_new(summary_temporary, summary_path)
        summary_published = True
        published = (
            *guards,
            (normalized_public, "normalized output"),
            (summary_public, "summary output"),
        )
        _require_owned_artifacts(published)
        for parent in {normalized_path.parent, summary_path.parent}:
            directory_descriptor = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        _require_owned_artifacts(published)
        return normalized_public, summary_public
    except BaseException:
        if summary_published:
            _unlink_if_owned(summary_path, summary_identity)
        if normalized_published:
            _unlink_if_owned(normalized_path, normalized_identity)
        raise
    finally:
        _unlink_if_owned(normalized_temporary, normalized_identity)
        _unlink_if_owned(summary_temporary, summary_identity)


def _require_absolute_paths(paths: Sequence[Path]) -> None:
    if any(not path.is_absolute() for path in paths):
        raise ValueError("all paths must be absolute")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--review-index", type=Path, required=True)
    parser.add_argument("--expected-review-index-sha256", required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--owner-ambiguous", type=Path, required=True)
    parser.add_argument("--review-frames-dir", type=Path, required=True)
    parser.add_argument("--normalized-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    args = parser.parse_args(argv)

    expected_manifest_sha256 = _require_sha256(
        args.expected_manifest_sha256, "expected manifest sha256"
    )
    expected_review_index_sha256 = _require_sha256(
        args.expected_review_index_sha256, "expected review index sha256"
    )
    paths = (
        args.candidate_manifest,
        args.review_index,
        args.snapshot,
        args.owner_ambiguous,
        args.review_frames_dir,
        args.normalized_output,
        args.summary_output,
    )
    _require_absolute_paths(paths)
    if args.normalized_output == args.summary_output:
        raise ValueError("normalized and summary outputs must be distinct")
    if not args.normalized_output.parent.is_dir() or not args.summary_output.parent.is_dir():
        raise ValueError("output parent directory is missing")
    lock_path = args.normalized_output.parent / LOCK_NAME
    lock_ownership = _claim_one_shot_lock(lock_path)
    lock_guard = ((lock_ownership, "one-shot lock"),)
    _require_owned_artifacts(lock_guard)
    if (
        args.normalized_output.exists()
        or args.normalized_output.is_symlink()
        or args.summary_output.exists()
        or args.summary_output.is_symlink()
    ):
        raise FileExistsError("future holdout export output is no-overwrite")

    manifest_bytes = _read_regular_file(
        args.candidate_manifest,
        label="candidate manifest",
        maximum_bytes=MAX_JSON_BYTES,
        require_mode_0600=True,
    )
    actual_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if actual_manifest_sha256 != expected_manifest_sha256:
        raise ValueError("candidate manifest sha256 mismatch")
    review_index_bytes = _read_regular_file(
        args.review_index,
        label="review index",
        maximum_bytes=MAX_CSV_BYTES,
        require_mode_0600=True,
    )
    actual_review_index_sha256 = hashlib.sha256(review_index_bytes).hexdigest()
    if actual_review_index_sha256 != expected_review_index_sha256:
        raise ValueError("review index sha256 mismatch")
    candidate_manifest = _parse_json_object(manifest_bytes, "candidate manifest")
    _validate_manifest(candidate_manifest)
    if candidate_manifest.get("review_index_sha256") != expected_review_index_sha256:
        raise ValueError("candidate manifest review index sha256 mismatch")
    review_index_rows = _read_review_index(review_index_bytes)
    snapshot = _parse_json_object(
        _read_regular_file(
            args.snapshot, label="snapshot", maximum_bytes=MAX_JSON_BYTES
        ),
        "snapshot",
    )
    ambiguous_sequences = _read_ambiguous(
        _read_regular_file(
            args.owner_ambiguous,
            label="owner ambiguous",
            maximum_bytes=MAX_CSV_BYTES,
        )
    )
    if ambiguous_sequences:
        raise ValueError(REPLACEMENT_STATUS)
    image_metadata = scan_review_frames(args.review_frames_dir)
    normalized = validate_export(
        candidate_manifest=candidate_manifest,
        snapshot=snapshot,
        image_metadata=image_metadata,
        review_index_rows=review_index_rows,
        ambiguous_sequences=(),
    )
    _require_owned_artifacts(lock_guard)
    normalized = {
        **normalized,
        "candidate_manifest_sha256": actual_manifest_sha256,
        "review_index_sha256": actual_review_index_sha256,
    }
    summary = {
        "schema": "yolo26n-v24b-future-holdout-acceptance-v1",
        "status": ACCEPTED_STATUS,
        "candidate_manifest_sha256": actual_manifest_sha256,
        "review_index_sha256": actual_review_index_sha256,
        "image_count": 120,
        "positive_image_count": 60,
        "negative_image_count": 60,
        "ambiguous_image_count": 0,
        "box_count": normalized["box_count"],
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "git_write_count": 0,
    }
    stdout_payload = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    output_ownership: tuple[_OwnedArtifact, ...] = ()
    try:
        output_ownership = _publish_json_pair(
            args.normalized_output,
            normalized,
            args.summary_output,
            summary,
            guards=lock_guard,
        )
        _require_owned_artifacts(
            (
                *lock_guard,
                (output_ownership[0], "normalized output"),
                (output_ownership[1], "summary output"),
            )
        )
    except BaseException:
        _cleanup_self_owned(output_ownership)
        raise
    print(stdout_payload)


if __name__ == "__main__":
    main()

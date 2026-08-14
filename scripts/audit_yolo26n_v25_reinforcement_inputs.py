"""Audit v2.5 historical reinforcement inputs without opening protected eval assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import csv
import io
import os
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

from PIL import Image, UnidentifiedImageError

try:
    from scripts.build_yolo26n_v24b_future_holdout import (
        _assert_private_snapshot_unchanged,
        _parse_strict_json_object,
        _read_private_snapshot,
    )
    from scripts.run_yolo26n_v24b_postprocess import (
        _artifact_is_self_owned,
        _cleanup_if_self_owned,
        _write_private_bytes_new as _secure_write_private_bytes_new,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from build_yolo26n_v24b_future_holdout import (  # type: ignore[no-redef]
        _assert_private_snapshot_unchanged,
        _parse_strict_json_object,
        _read_private_snapshot,
    )
    from run_yolo26n_v24b_postprocess import (  # type: ignore[no-redef]
        _artifact_is_self_owned,
        _cleanup_if_self_owned,
        _write_private_bytes_new as _secure_write_private_bytes_new,
    )


AUDIT_SCHEMA = "yolo26n-v25-reinforcement-input-audit-v1"
AUDIT_STATUS = "V25_HISTORICAL_AUDIT_READY"
OWNER_ONLY_AUDIT_SCHEMA = "yolo26n-v25-owner-only-input-audit-v1"
OWNER_ONLY_AUDIT_STATUS = "V25_OWNER_ONLY_INPUT_AUDIT_READY"
GATE_QUARANTINE_LINEAGE_SCHEMA = "yolo26n-v25-gate-quarantine-lineage-v1"
GATE_QUARANTINE_LINEAGE_STATUS = "V25_GATE_QUARANTINE_LINEAGE_READY"
HISTORICAL_SCHEMA = "yolo26n-v24b-historical-fingerprint-exclusions-v1"
HISTORICAL_STATUS = "V24B_HISTORICAL_FINGERPRINTS_FROZEN"
FINGERPRINT_POLICY = {
    "algorithm": "dhash64",
    "version": "pillow-rgb-luma-9x8-box-right-gt-left-v1",
    "pillow_version": "12.2.0",
    "scope": "global-historical",
    "hamming_reject_max_distance": 2,
}
ROLE_COUNTS = {
    "dataset": 1762,
    "internal-test151": 151,
    "owner-external60": 60,
}
REVIEW_CONTRACT = {
    "sample_positive": 40,
    "sample_negative": 20,
    "sample_positive_needs_fix": 2,
    "sample_negative_mislabeled": 0,
    "sample_accepted": 58,
    "full_review": 293,
    "full_accepted": 284,
    "full_quarantined": 9,
    "minimum_accepted": 150,
    "selected_positive": 284,
    "selected_negative": 285,
    "selected_source_clip": 419,
}
WRITE_COUNTS = {
    "db_write_count": 0,
    "r2_write_count": 0,
    "service_write_count": 0,
    "production_model_write_count": 0,
    "gme_write_count": 0,
    "labeling_web_write_count": 0,
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DHASH64 = re.compile(r"^[0-9a-f]{16}$")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _zero_writes(payload: Mapping[str, object], names: Sequence[str]) -> bool:
    return all(payload.get(name) == 0 for name in names)


def _validated_reviewed_records(
    payload: Mapping[str, object], *, expected_count: int
) -> list[dict[str, object]]:
    rows = payload.get("selected_records")
    if (
        payload.get("schema")
        != "yolo26n-gate-operational-reviewed-candidates-v24-v1"
        or payload.get("status") != "V24_GATE_REVIEWED_CANDIDATES_READY"
        or not isinstance(rows, list)
        or payload.get("selected_count") != expected_count
        or len(rows) != expected_count
        or not _zero_writes(
            payload, ("db_write_count", "r2_write_count", "service_write_count")
        )
    ):
        raise ValueError("accepted review contract mismatch")

    reviewed: list[dict[str, object]] = []
    image_shas: set[str] = set()
    source_paths: set[str] = set()
    positive_count = 0
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("reviewed Gate record contract mismatch")
        row = dict(raw)
        source_path = row.get("source_relpath")
        source_clip = row.get("source_clip_ref")
        camera_night = row.get("camera_night_ref")
        image_sha = row.get("image_sha256")
        dhash = row.get("dhash64")
        width = row.get("width")
        height = row.get("height")
        boxes = row.get("boxes_xywh")
        box_count = row.get("box_count")
        positive = row.get("positive")
        relative = PurePosixPath(str(source_path))
        if (
            not isinstance(source_path, str)
            or relative.is_absolute()
            or ".." in relative.parts
            or len(relative.parts) < 3
            or relative.parts[0] != "operational"
            or not isinstance(source_clip, str)
            or not source_clip
            or not isinstance(camera_night, str)
            or not camera_night
            or not isinstance(image_sha, str)
            or _SHA256.fullmatch(image_sha) is None
            or not isinstance(dhash, str)
            or _DHASH64.fullmatch(dhash) is None
            or not _is_int(width)
            or width <= 0
            or not _is_int(height)
            or height <= 0
            or not isinstance(boxes, list)
            or not _is_int(box_count)
            or box_count < 0
            or len(boxes) != box_count
            or not isinstance(positive, bool)
            or positive is not (box_count > 0)
            or image_sha in image_shas
            or source_path in source_paths
        ):
            raise ValueError("reviewed Gate record contract mismatch")
        for box in boxes:
            if not isinstance(box, list) or len(box) != 4:
                raise ValueError("reviewed Gate record contract mismatch")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in box
            ):
                raise ValueError("reviewed Gate record contract mismatch")
            left, top, box_width, box_height = map(float, box)
            if (
                left < 0
                or top < 0
                or box_width <= 0
                or box_height <= 0
                or left + box_width > width
                or top + box_height > height
            ):
                raise ValueError("reviewed Gate record contract mismatch")
        image_shas.add(image_sha)
        source_paths.add(source_path)
        positive_count += int(positive)
        reviewed.append(row)
    if (
        payload.get("positive_count") != positive_count
        or payload.get("negative_count") != expected_count - positive_count
    ):
        raise ValueError("accepted review contract mismatch")
    return reviewed


def _record_identity(row: Mapping[str, object]) -> tuple[object, ...]:
    return (
        row.get("source_relpath"),
        row.get("source_clip_ref"),
        row.get("camera_night_ref"),
        row.get("image_sha256"),
        row.get("dhash64"),
        row.get("width"),
        row.get("height"),
        json.dumps(row.get("boxes_xywh"), separators=(",", ":")),
        row.get("box_count"),
        row.get("positive"),
    )


def _validated_review_evidence(
    *,
    sample: Mapping[str, object],
    full: Mapping[str, object],
    accepted_manifest: Mapping[str, object],
    reviewed: Sequence[Mapping[str, object]],
    expected: Mapping[str, int],
) -> None:
    if dict(expected) != {key: expected[key] for key in REVIEW_CONTRACT}:
        raise ValueError("review evidence expected-count contract mismatch")
    sample_sha = sample.get("owner_verdict_sha256")
    full_sha = full.get("owner_verdict_sha256")
    accepted_sha = accepted_manifest.get("owner_verdict_sha256")
    if (
        sample.get("schema") != "yolo26n-gate-operational-owner-audit-v24-v1"
        or sample.get("status") != "V24_GATE_POSITIVE_FULL_REVIEW_REQUIRED"
        or sample.get("positive_count") != expected["sample_positive"]
        or sample.get("negative_count") != expected["sample_negative"]
        or sample.get("positive_needs_fix_count")
        != expected["sample_positive_needs_fix"]
        or sample.get("negative_mislabeled_count")
        != expected["sample_negative_mislabeled"]
        or sample.get("accepted_count") != expected["sample_accepted"]
        or not isinstance(sample_sha, str)
        or _SHA256.fullmatch(sample_sha) is None
        or not _zero_writes(
            sample, ("db_write_count", "r2_write_count", "service_write_count")
        )
    ):
        raise ValueError("sample audit evidence contract mismatch")

    accepted_rows = full.get("accepted_records")
    quarantined_rows = full.get("quarantined_records")
    if (
        full.get("schema")
        != "yolo26n-gate-operational-full-policy-review-result-v24-v1"
        or full.get("status") != "V24_GATE_POSITIVE_FULL_REVIEW_ACCEPTED"
        or full.get("review_class") != "positive"
        or full.get("review_count") != expected["full_review"]
        or full.get("accepted_count") != expected["full_accepted"]
        or full.get("quarantined_count") != expected["full_quarantined"]
        or full.get("minimum_accepted") != expected["minimum_accepted"]
        or not isinstance(accepted_rows, list)
        or len(accepted_rows) != expected["full_accepted"]
        or not isinstance(quarantined_rows, list)
        or len(quarantined_rows) != expected["full_quarantined"]
        or not isinstance(full_sha, str)
        or _SHA256.fullmatch(full_sha) is None
        or accepted_sha != full_sha
        or not _zero_writes(
            full, ("db_write_count", "r2_write_count", "service_write_count")
        )
    ):
        raise ValueError("positive full-review evidence contract mismatch")

    selected_positive = [row for row in reviewed if row.get("positive") is True]
    selected_negative = [row for row in reviewed if row.get("positive") is False]
    if (
        len(selected_positive) != expected["selected_positive"]
        or len(selected_negative) != expected["selected_negative"]
        or accepted_manifest.get("positive_count") != len(selected_positive)
        or accepted_manifest.get("negative_count") != len(selected_negative)
        or accepted_manifest.get("quarantined_positive_count")
        != expected["full_quarantined"]
        or accepted_manifest.get("source_clip_count")
        != expected["selected_source_clip"]
    ):
        raise ValueError("accepted review cohort contract mismatch")
    try:
        full_accepted_identities = {
            _record_identity(row)
            for row in accepted_rows
            if isinstance(row, Mapping) and row.get("positive") is True
        }
        full_quarantined_identities = {
            _record_identity(row)
            for row in quarantined_rows
            if isinstance(row, Mapping) and row.get("positive") is True
        }
    except (TypeError, ValueError):
        raise ValueError("positive full-review evidence contract mismatch") from None
    selected_positive_identities = {_record_identity(row) for row in selected_positive}
    if (
        len(full_accepted_identities) != expected["full_accepted"]
        or len(full_quarantined_identities) != expected["full_quarantined"]
        or full_accepted_identities != selected_positive_identities
        or full_accepted_identities & full_quarantined_identities
    ):
        raise ValueError("positive full-review evidence contract mismatch")


def _validated_dataset(
    payload: Mapping[str, object], *, expected_counts: Mapping[str, int]
) -> tuple[dict[str, Mapping[str, object]], set[str], set[str]]:
    rows = payload.get("records")
    expected = dict(expected_counts)
    if (
        payload.get("schema") != "yolo26n-owner-dataset-v24"
        or payload.get("evaluation_tier") != "development"
        or payload.get("future_holdout_required") is not True
        or payload.get("split_counts") != expected
        or not isinstance(rows, list)
        or payload.get("image_count") != len(rows)
        or len(rows) != sum(expected.values())
        or not _zero_writes(
            payload, ("db_write_count", "r2_write_count", "service_write_count")
        )
    ):
        raise ValueError("v2.4 dataset contract mismatch")
    actual_counts = {"train": 0, "val": 0, "test": 0}
    gate_train: dict[str, Mapping[str, object]] = {}
    all_shas: set[str] = set()
    protected_shas: set[str] = set()
    gate_count = 0
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("v2.4 dataset contract mismatch")
        split = row.get("split")
        image_sha = row.get("image_sha256")
        if (
            split not in actual_counts
            or not isinstance(image_sha, str)
            or _SHA256.fullmatch(image_sha) is None
            or image_sha in all_shas
        ):
            raise ValueError("v2.4 dataset contract mismatch")
        actual_counts[str(split)] += 1
        all_shas.add(image_sha)
        if split in {"val", "test"}:
            protected_shas.add(image_sha)
        if row.get("source_dataset") == "gate-operational-v24":
            if split != "train" or image_sha in gate_train:
                raise ValueError("v2.4 dataset contract mismatch")
            gate_train[image_sha] = row
            gate_count += 1
    if actual_counts != expected or payload.get("gate_operational_added_count") != gate_count:
        raise ValueError("v2.4 dataset contract mismatch")
    source_counts = payload.get("source_dataset_counts")
    if not isinstance(source_counts, Mapping) or source_counts.get(
        "gate-operational-v24"
    ) != gate_count:
        raise ValueError("v2.4 dataset contract mismatch")
    return gate_train, all_shas, protected_shas


def _validated_historical(
    payload: Mapping[str, object], *, expected_unique_count: int
) -> tuple[set[str], tuple[int, ...]]:
    rows = payload.get("records")
    if (
        payload.get("schema") != HISTORICAL_SCHEMA
        or payload.get("status") != HISTORICAL_STATUS
        or payload.get("role_counts") != ROLE_COUNTS
        or payload.get("unique_image_count") != expected_unique_count
        or not isinstance(rows, list)
        or len(rows) != expected_unique_count
        or payload.get("fingerprint_policy") != FINGERPRINT_POLICY
        or not _zero_writes(
            payload,
            (
                "db_write_count",
                "r2_write_count",
                "service_write_count",
                "git_write_count",
            ),
        )
    ):
        raise ValueError("historical fingerprint contract mismatch")
    shas: set[str] = set()
    hashes: list[int] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("historical fingerprint contract mismatch")
        image_sha = row.get("image_sha256")
        dhash = row.get("dhash64")
        if (
            not isinstance(image_sha, str)
            or _SHA256.fullmatch(image_sha) is None
            or image_sha in shas
            or not isinstance(dhash, str)
            or _DHASH64.fullmatch(dhash) is None
        ):
            raise ValueError("historical fingerprint contract mismatch")
        shas.add(image_sha)
        hashes.append(int(dhash, 16))
    return shas, tuple(hashes)


def _same_gate_record(
    reviewed: Mapping[str, object], dataset: Mapping[str, object]
) -> bool:
    return (
        dataset.get("split") == "train"
        and dataset.get("source_dataset") == "gate-operational-v24"
        and dataset.get("box_count") == reviewed.get("box_count")
        and dataset.get("positive") is reviewed.get("positive")
        and dataset.get("camera_night_group") == reviewed.get("camera_night_ref")
        and dataset.get("final_holdout_eligible") is False
    )


def _read_regular_bytes(path: Path) -> bytes:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
    except OSError:
        raise ValueError("Gate origin artifact contract mismatch") from None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Gate origin artifact contract mismatch")
        payload = bytearray()
        while len(payload) < metadata.st_size:
            chunk = os.read(
                descriptor, min(1024 * 1024, metadata.st_size - len(payload))
            )
            if not chunk:
                raise ValueError("Gate origin artifact contract mismatch")
            payload.extend(chunk)
        if os.read(descriptor, 1):
            raise ValueError("Gate origin artifact contract mismatch")
        confirmed = os.fstat(descriptor)
        if (
            confirmed.st_dev != metadata.st_dev
            or confirmed.st_ino != metadata.st_ino
            or confirmed.st_mode != metadata.st_mode
            or confirmed.st_size != metadata.st_size
        ):
            raise ValueError("Gate origin artifact contract mismatch")
        return bytes(payload)
    finally:
        os.close(descriptor)


def prepare_gate_quarantine_lineage(
    *,
    accepted_review: Path,
    positive_full_review_result: Path,
    expected_sha256: Mapping[str, str],
    output: Path,
    started_output: Path,
    expected_accepted_count: int = 569,
    expected_quarantined_count: int = 9,
) -> dict[str, object]:
    """Publish only preserved Gate lineage fields for exclusion evidence."""
    paths = {
        "accepted_review": accepted_review,
        "positive_full_review_result": positive_full_review_result,
    }
    if (
        set(expected_sha256) != set(paths)
        or any(not path.is_absolute() for path in (*paths.values(), output, started_output))
        or any(_SHA256.fullmatch(value) is None for value in expected_sha256.values())
        or expected_accepted_count < 0
        or expected_quarantined_count < 0
    ):
        raise ValueError("Gate quarantine lineage input contract mismatch")
    snapshots = {name: _read_private_snapshot(path) for name, path in paths.items()}
    if any(
        hashlib.sha256(snapshots[name].payload).hexdigest() != expected_sha256[name]
        for name in paths
    ):
        raise ValueError("Gate quarantine lineage input pin mismatch")
    accepted_payload = _parse_strict_json_object(
        snapshots["accepted_review"].payload, name="accepted review"
    )
    full_payload = _parse_strict_json_object(
        snapshots["positive_full_review_result"].payload,
        name="positive full review",
    )
    accepted = _validated_reviewed_records(
        accepted_payload, expected_count=expected_accepted_count
    )
    full_accepted = full_payload.get("accepted_records")
    quarantined = full_payload.get("quarantined_records")
    selected_positive = [row for row in accepted if row.get("positive") is True]
    if (
        full_payload.get("schema")
        != "yolo26n-gate-operational-full-policy-review-result-v24-v1"
        or full_payload.get("status") != "V24_GATE_POSITIVE_FULL_REVIEW_ACCEPTED"
        or full_payload.get("review_class") != "positive"
        or full_payload.get("accepted_count") != len(selected_positive)
        or full_payload.get("quarantined_count") != expected_quarantined_count
        or not isinstance(full_accepted, list)
        or not isinstance(quarantined, list)
        or len(full_accepted) != len(selected_positive)
        or len(quarantined) != expected_quarantined_count
        or full_payload.get("owner_verdict_sha256")
        != accepted_payload.get("owner_verdict_sha256")
        or not _zero_writes(
            full_payload, ("db_write_count", "r2_write_count", "service_write_count")
        )
        or {_record_identity(row) for row in full_accepted if isinstance(row, Mapping)}
        != {_record_identity(row) for row in selected_positive}
    ):
        raise ValueError("Gate quarantine lineage review contract mismatch")
    lineage_rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in [*accepted, *quarantined]:
        if not isinstance(raw, Mapping):
            raise ValueError("Gate quarantine lineage record mismatch")
        source_path = raw.get("source_relpath")
        source_clip = raw.get("source_clip_ref")
        camera_night = raw.get("camera_night_ref")
        if (
            not isinstance(source_path, str)
            or not source_path
            or source_path in seen
            or not isinstance(source_clip, str)
            or not source_clip
            or not isinstance(camera_night, str)
            or not camera_night
        ):
            raise ValueError("Gate quarantine lineage record mismatch")
        seen.add(source_path)
        lineage_rows.append(
            {
                "source_relpath": source_path,
                "source_clip_ref": source_clip,
                "camera_night_ref": camera_night,
            }
        )
    lineage_rows.sort(key=lambda row: row["source_relpath"])
    lock_payload = (
        json.dumps(
            {
                "schema": "yolo26n-v25-gate-quarantine-lineage-lock-v1",
                "status": "STARTED",
                "final_output": str(output),
                "input_sha256": dict(expected_sha256),
                **WRITE_COUNTS,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    lock = _secure_write_private_bytes_new(started_output, lock_payload)
    payload = (
        json.dumps(
            {
                "schema": GATE_QUARANTINE_LINEAGE_SCHEMA,
                "status": GATE_QUARANTINE_LINEAGE_STATUS,
                "record_count": len(lineage_rows),
                "input_sha256": dict(expected_sha256),
                "records": lineage_rows,
                **WRITE_COUNTS,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    artifact = _secure_write_private_bytes_new(output, payload)
    try:
        for name, path in paths.items():
            _assert_private_snapshot_unchanged(path, snapshots[name], name=name)
        if artifact.sha256 != hashlib.sha256(payload).hexdigest():
            raise ValueError("Gate quarantine lineage publication mismatch")
        if not _artifact_is_self_owned(lock) or not _artifact_is_self_owned(artifact):
            raise ValueError(
                "Gate quarantine lineage artifact ownership changed at success boundary"
            )
    except BaseException:
        _cleanup_if_self_owned(artifact)
        raise
    return {
        "status": GATE_QUARANTINE_LINEAGE_STATUS,
        "record_count": len(lineage_rows),
        "output_sha256": artifact.sha256,
        **WRITE_COUNTS,
    }


def validate_gate_origin_artifacts(
    *,
    reviewed: Sequence[Mapping[str, object]],
    quarantined: Sequence[Mapping[str, object]] = (),
    gate_root: Path,
    gate_manifest: Path,
    gate_coco: Sequence[Path],
    gate_lineage: Path | None,
    expected_sha256: Mapping[str, str],
    owner_only: bool = False,
    expected_lineage_input_sha256: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Bind accepted human-review rows to manifest, COCO, and raw image bytes."""
    if (
        not gate_root.is_absolute()
        or gate_root.is_symlink()
        or not gate_root.is_dir()
        or not gate_coco
        or gate_lineage is None
        or set(expected_sha256)
        != {"manifest", "lineage", *(f"coco:{path.name}" for path in gate_coco)}
        or any(_SHA256.fullmatch(value) is None for value in expected_sha256.values())
    ):
        raise ValueError("Gate origin artifact contract mismatch")
    try:
        manifest_payload = _read_regular_bytes(gate_manifest)
        lineage_payload = _read_private_snapshot(gate_lineage).payload
        if (
            hashlib.sha256(manifest_payload).hexdigest()
            != expected_sha256["manifest"]
            or hashlib.sha256(lineage_payload).hexdigest()
            != expected_sha256["lineage"]
        ):
            raise ValueError
        reader = csv.DictReader(
            io.StringIO(manifest_payload.decode("utf-8")), strict=True
        )
        if reader.fieldnames != [
            "filename",
            "source",
            "clip_id",
            "split",
            "labeled",
            "domain",
        ]:
            raise ValueError
        manifest_rows: dict[str, dict[str, str]] = {}
        for raw in reader:
            filename = raw.get("filename")
            if not filename or filename in manifest_rows:
                raise ValueError
            relative = PurePosixPath(filename)
            if (
                raw.get("source") == "operational"
                and (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or len(relative.parts) < 3
                    or relative.parts[0] != "operational"
                    or raw.get("clip_id") != relative.parts[1]
                )
            ):
                raise ValueError
            manifest_rows[filename] = raw

        lineage_value = json.loads(lineage_payload)
        lineage_rows = (
            lineage_value.get("records" if owner_only else "rows")
            if isinstance(lineage_value, dict)
            else None
        )
        if (
            not isinstance(lineage_value, dict)
            or lineage_value.get("schema")
            != (
                GATE_QUARANTINE_LINEAGE_SCHEMA
                if owner_only
                else "yolo26n-gate-lineage-v24-v1"
            )
            or (
                owner_only
                and lineage_value.get("status") != GATE_QUARANTINE_LINEAGE_STATUS
            )
            or (
                owner_only
                and (
                    lineage_value.get("record_count") != len(lineage_rows or [])
                    or not isinstance(lineage_value.get("input_sha256"), Mapping)
                    or set(lineage_value["input_sha256"])
                    != {"accepted_review", "positive_full_review_result"}
                    or expected_lineage_input_sha256 is None
                    or dict(lineage_value["input_sha256"])
                    != dict(expected_lineage_input_sha256)
                    or any(
                        _SHA256.fullmatch(value) is None
                        for value in lineage_value["input_sha256"].values()
                    )
                    or not _zero_writes(lineage_value, tuple(WRITE_COUNTS))
                )
            )
            or not isinstance(lineage_rows, list)
            or any(
                lineage_value.get(key) != 0
                for key in ("db_write_count", "r2_write_count", "service_write_count")
            )
        ):
            raise ValueError
        lineage_by_path: dict[str, tuple[str, str]] = {}
        for row in lineage_rows:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("source_relpath"), str)
                or not isinstance(row.get("source_clip_ref"), str)
                or not row["source_clip_ref"]
                or not isinstance(row.get("camera_night_ref"), str)
                or not row["camera_night_ref"]
                or row["source_relpath"] in lineage_by_path
            ):
                raise ValueError
            lineage_by_path[row["source_relpath"]] = (
                row["source_clip_ref"], row["camera_night_ref"]
            )

        coco_rows: dict[str, tuple[str, int, int, list[list[float]]]] = {}
        coco_sha: dict[str, str] = {}
        coco_splits: set[str] = set()
        for path in gate_coco:
            split = path.stem
            if split not in {"train", "val", "test"} or split in coco_splits:
                raise ValueError
            coco_splits.add(split)
            payload = _read_regular_bytes(path)
            if hashlib.sha256(payload).hexdigest() != expected_sha256[f"coco:{path.name}"]:
                raise ValueError
            coco_sha[path.name] = hashlib.sha256(payload).hexdigest()
            value = json.loads(payload)
            if (
                not isinstance(value, dict)
                or value.get("categories") != [{"id": 1, "name": "gecko"}]
                or not isinstance(value.get("images"), list)
                or not isinstance(value.get("annotations"), list)
            ):
                raise ValueError
            annotations: dict[int, list[tuple[int, list[float]]]] = {}
            annotation_ids: set[int] = set()
            for annotation in value["annotations"]:
                if (
                    not isinstance(annotation, dict)
                    or annotation.get("category_id") != 1
                    or annotation.get("iscrowd") != 0
                    or type(annotation.get("id")) is not int
                    or type(annotation.get("image_id")) is not int
                    or not isinstance(annotation.get("bbox"), list)
                    or len(annotation["bbox"]) != 4
                    or any(
                        isinstance(item, bool) or not isinstance(item, (int, float))
                        for item in annotation["bbox"]
                    )
                    or isinstance(annotation.get("area"), bool)
                    or not isinstance(annotation.get("area"), (int, float))
                    or annotation["id"] in annotation_ids
                ):
                    raise ValueError
                box = [float(item) for item in annotation["bbox"]]
                area = float(annotation["area"])
                if (
                    not all(math.isfinite(item) for item in (*box, area))
                    or box[0] < 0
                    or box[1] < 0
                    or box[2] <= 0
                    or box[3] <= 0
                    or area <= 0
                    or not math.isclose(area, box[2] * box[3], rel_tol=1e-9, abs_tol=1e-9)
                ):
                    raise ValueError
                annotation_ids.add(annotation["id"])
                annotations.setdefault(annotation["image_id"], []).append(
                    (
                        annotation["id"],
                        box,
                    )
                )
            image_ids: set[int] = set()
            for image in value["images"]:
                if (
                    not isinstance(image, dict)
                    or type(image.get("id")) is not int
                    or not isinstance(image.get("file_name"), str)
                    or type(image.get("width")) is not int
                    or type(image.get("height")) is not int
                    or image["width"] <= 0
                    or image["height"] <= 0
                    or image["id"] in image_ids
                    or image["file_name"] in coco_rows
                ):
                    raise ValueError
                image_ids.add(image["id"])
                boxes = [box for _, box in sorted(annotations.pop(image["id"], []))]
                if any(
                    box[0] + box[2] > image["width"]
                    or box[1] + box[3] > image["height"]
                    for box in boxes
                ):
                    raise ValueError
                coco_rows[image["file_name"]] = (
                    split,
                    image["width"],
                    image["height"],
                    boxes,
                )
            if annotations:
                raise ValueError

        operational_manifest = {
            name
            for name, row in manifest_rows.items()
            if row.get("source") == "operational"
            and row.get("labeled") == "yes"
            and row.get("split") in {"train", "val", "test"}
        }
        operational_coco = {
            name for name in coco_rows if PurePosixPath(name).parts[:1] == ("operational",)
        }
        if operational_manifest != operational_coco:
            raise ValueError
        if (
            (not owner_only and set(lineage_by_path) != operational_coco)
            or (owner_only and not set(lineage_by_path).issubset(operational_coco))
        ):
            raise ValueError
        if any(
            manifest_rows[name].get("split") != coco_rows[name][0]
            for name in operational_coco
        ):
            raise ValueError
        content_contract: list[tuple[str, str, int, int]] = []
        raw_by_path: dict[str, bytes] = {}
        for relative_text in sorted(operational_coco):
            relative = PurePosixPath(relative_text)
            image_payload = _read_regular_bytes(
                gate_root / "raw" / Path(*relative.parts)
            )
            _split, width, height, _boxes = coco_rows[relative_text]
            with Image.open(io.BytesIO(image_payload)) as image:
                image.load()
                if image.size != (width, height):
                    raise ValueError
            raw_by_path[relative_text] = image_payload
            content_contract.append(
                (
                    relative_text,
                    hashlib.sha256(image_payload).hexdigest(),
                    width,
                    height,
                )
            )

        for row in reviewed:
            relative_text = row.get("source_relpath")
            if not isinstance(relative_text, str):
                raise ValueError
            relative = PurePosixPath(relative_text)
            manifest_row = manifest_rows.get(relative_text)
            if (
                manifest_row is None
                or manifest_row.get("source") != "operational"
                or manifest_row.get("labeled") != "yes"
                or not manifest_row.get("clip_id")
                or lineage_by_path.get(relative_text)
                != (row.get("source_clip_ref"), row.get("camera_night_ref"))
                or coco_rows.get(relative_text)
                != (
                    manifest_row.get("split"),
                    row.get("width"),
                    row.get("height"),
                    row.get("boxes_xywh"),
                )
            ):
                raise ValueError
            image_payload = raw_by_path[relative_text]
            if hashlib.sha256(image_payload).hexdigest() != row.get("image_sha256"):
                raise ValueError
            with Image.open(io.BytesIO(image_payload)) as image:
                image.load()
                if image.size != (row.get("width"), row.get("height")):
                    raise ValueError
        if owner_only:
            expected_lineage_paths: set[str] = set()
            for row in [*reviewed, *quarantined]:
                relative_text = row.get("source_relpath")
                if (
                    not isinstance(relative_text, str)
                    or relative_text in expected_lineage_paths
                    or relative_text not in operational_coco
                    or lineage_by_path.get(relative_text)
                    != (row.get("source_clip_ref"), row.get("camera_night_ref"))
                ):
                    raise ValueError
                expected_lineage_paths.add(relative_text)
            if expected_lineage_paths != set(lineage_by_path):
                raise ValueError
            covered_count = len(lineage_by_path)
            operational_count = len(operational_coco)
            return {
                "selection_policy": "exclude-all-gate-v1",
                "operational_labeled_count": operational_count,
                "operational_content_sha256": hashlib.sha256(
                    json.dumps(content_contract, separators=(",", ":")).encode()
                ).hexdigest(),
                "lineage_covered_count": covered_count,
                "lineage_missing_count": operational_count - covered_count,
                "lineage_extra_count": 0,
                "gate_candidate_count": 0,
                "gate_quarantined_count": operational_count,
                "train_eligible_image_sha256": [],
                "manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
                "lineage_sha256": hashlib.sha256(lineage_payload).hexdigest(),
                "coco_sha256": dict(sorted(coco_sha.items())),
            }
        return {
            "validated_count": len(reviewed),
            "human_gt": True,
            "license_role": "owner-operated/private-training",
            "operational_labeled_count": len(operational_coco),
            "operational_content_sha256": hashlib.sha256(
                json.dumps(content_contract, separators=(",", ":")).encode()
            ).hexdigest(),
            "train_eligible_image_sha256": sorted(
                str(row["image_sha256"])
                for row in reviewed
                if manifest_rows[str(row["source_relpath"])].get("split") == "train"
            ),
            "manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
            "lineage_sha256": hashlib.sha256(lineage_payload).hexdigest(),
            "coco_sha256": dict(sorted(coco_sha.items())),
        }
    except (
        csv.Error,
        json.JSONDecodeError,
        UnicodeDecodeError,
        OSError,
        UnidentifiedImageError,
        ValueError,
        TypeError,
    ):
        raise ValueError("Gate origin artifact contract mismatch") from None


def audit_gate_inclusion(
    *,
    sample_audit_summary: Mapping[str, object],
    positive_full_review_result: Mapping[str, object],
    accepted_review: Mapping[str, object],
    v24_dataset: Mapping[str, object],
    historical_fingerprints: Mapping[str, object],
    expected_selected_count: int = 569,
    expected_dataset_counts: Mapping[str, int] = {
        "train": 1458,
        "val": 153,
        "test": 151,
    },
    expected_historical_unique_count: int = 1822,
    expected_review_contract: Mapping[str, int] = REVIEW_CONTRACT,
) -> dict[str, object]:
    """Return a private, canonical Gate inclusion audit.

    The configurable expected counts exist for deterministic unit fixtures; the CLI uses
    only the production defaults above.
    """

    reviewed = _validated_reviewed_records(
        accepted_review, expected_count=expected_selected_count
    )
    _validated_review_evidence(
        sample=sample_audit_summary,
        full=positive_full_review_result,
        accepted_manifest=accepted_review,
        reviewed=reviewed,
        expected=expected_review_contract,
    )
    gate_train, dataset_shas, protected_dataset_shas = _validated_dataset(
        v24_dataset, expected_counts=expected_dataset_counts
    )
    historical_shas, historical_hashes = _validated_historical(
        historical_fingerprints,
        expected_unique_count=expected_historical_unique_count,
    )

    counts = {
        "accepted_review": len(reviewed),
        "already_in_v24_train": 0,
        "new_train_eligible": 0,
        "protected_exact_overlap": 0,
        "protected_perceptual_overlap": 0,
    }
    novel: list[dict[str, object]] = []
    for row in reviewed:
        image_sha = str(row["image_sha256"])
        existing = gate_train.get(image_sha)
        if existing is not None:
            if not _same_gate_record(row, existing):
                raise ValueError("v2.4 Gate lineage join mismatch")
            counts["already_in_v24_train"] += 1
            continue
        if image_sha in protected_dataset_shas or image_sha in historical_shas:
            counts["protected_exact_overlap"] += 1
            continue
        candidate_hash = int(str(row["dhash64"]), 16)
        if any(
            (candidate_hash ^ historical_hash).bit_count()
            <= int(FINGERPRINT_POLICY["hamming_reject_max_distance"])
            for historical_hash in historical_hashes
        ):
            counts["protected_perceptual_overlap"] += 1
            continue
        if image_sha in dataset_shas:
            raise ValueError("v2.4 Gate lineage join mismatch")
        counts["new_train_eligible"] += 1
        novel.append(row)

    novel.sort(
        key=lambda row: (
            str(row["source_clip_ref"]),
            str(row["image_sha256"]),
        )
    )
    return {
        "schema": AUDIT_SCHEMA,
        "status": AUDIT_STATUS,
        "license_role": "owner-operated/private-training",
        "label_semantics": "single-gecko-visible-head-body-no-extrapolation-v1",
        "fingerprint_policy": dict(FINGERPRINT_POLICY),
        "counts": counts,
        "new_train_eligible_records": novel,
        **WRITE_COUNTS,
    }


def publish_private_audit(*, audit: Mapping[str, object], output: Path) -> str:
    if (
        (audit.get("schema"), audit.get("status")) != (AUDIT_SCHEMA, AUDIT_STATUS)
        or not _zero_writes(audit, tuple(WRITE_COUNTS))
    ):
        raise ValueError("historical audit is not publishable")
    payload = (
        json.dumps(
            dict(audit), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")
    artifact = _secure_write_private_bytes_new(output, payload)
    expected = hashlib.sha256(payload).hexdigest()
    if artifact.sha256 != expected:
        raise ValueError("private audit publication mismatch")
    return expected


def run_private_audit(
    *,
    sample_audit_summary: Path,
    positive_full_review_result: Path,
    accepted_review: Path,
    v24_dataset: Path,
    historical_fingerprints: Path,
    expected_sha256: Mapping[str, str],
    output: Path,
    started_output: Path,
    expected_selected_count: int = 569,
    expected_dataset_counts: Mapping[str, int] = {
        "train": 1458,
        "val": 153,
        "test": 151,
    },
    expected_historical_unique_count: int = 1822,
    expected_review_contract: Mapping[str, int] = REVIEW_CONTRACT,
    gate_root: Path | None = None,
    gate_manifest: Path | None = None,
    gate_coco: Sequence[Path] = (),
    gate_lineage: Path | None = None,
    expected_gate_sha256: Mapping[str, str] | None = None,
) -> dict[str, object]:
    paths = {
        "sample_audit_summary": sample_audit_summary,
        "positive_full_review_result": positive_full_review_result,
        "accepted_review": accepted_review,
        "v24_dataset": v24_dataset,
        "historical_fingerprints": historical_fingerprints,
    }
    if (
        set(expected_sha256) != set(paths)
        or any(
            not path.is_absolute()
            for path in (*paths.values(), output, started_output)
        )
        or any(
            not isinstance(value, str) or _SHA256.fullmatch(value) is None
            for value in expected_sha256.values()
        )
    ):
        raise ValueError("private input pin contract mismatch")
    lock_payload = (
        json.dumps(
            {
                "schema": "yolo26n-v25-input-audit-lock-v1",
                "status": "STARTED",
                "final_output": str(output),
                "input_sha256": dict(expected_sha256),
                "gate_input_sha256": dict(expected_gate_sha256 or {}),
                **WRITE_COUNTS,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    lock = _secure_write_private_bytes_new(started_output, lock_payload)
    if lock.sha256 != hashlib.sha256(lock_payload).hexdigest():
        raise ValueError("input audit lock publication mismatch")

    snapshots = {}
    payloads: dict[str, dict[str, object]] = {}
    for role, path in paths.items():
        snapshot = _read_private_snapshot(path)
        if hashlib.sha256(snapshot.payload).hexdigest() != expected_sha256[role]:
            raise ValueError("private input pin mismatch")
        snapshots[role] = snapshot
        payloads[role] = _parse_strict_json_object(snapshot.payload, name=role)

    historical_artifacts = payloads["historical_fingerprints"].get("artifact_sha256")
    if (
        not isinstance(historical_artifacts, Mapping)
        or historical_artifacts.get("dataset") != expected_sha256["v24_dataset"]
    ):
        raise ValueError("historical dataset raw SHA pin mismatch")

    result = audit_gate_inclusion(
        sample_audit_summary=payloads["sample_audit_summary"],
        positive_full_review_result=payloads["positive_full_review_result"],
        accepted_review=payloads["accepted_review"],
        v24_dataset=payloads["v24_dataset"],
        historical_fingerprints=payloads["historical_fingerprints"],
        expected_selected_count=expected_selected_count,
        expected_dataset_counts=expected_dataset_counts,
        expected_historical_unique_count=expected_historical_unique_count,
        expected_review_contract=expected_review_contract,
    )
    gate_inputs = (
        gate_root,
        gate_manifest,
        tuple(gate_coco),
        gate_lineage,
        expected_gate_sha256,
    )
    if any(value for value in gate_inputs):
        if (
            gate_root is None
            or gate_manifest is None
            or not gate_coco
            or gate_lineage is None
            or expected_gate_sha256 is None
        ):
            raise ValueError("Gate origin input contract mismatch")
        reviewed = _validated_reviewed_records(
            payloads["accepted_review"], expected_count=expected_selected_count
        )
        quarantined = payloads["positive_full_review_result"].get(
            "quarantined_records"
        )
        if not isinstance(quarantined, list):
            raise ValueError("Gate origin input contract mismatch")
        result["gate_origin"] = validate_gate_origin_artifacts(
            reviewed=reviewed,
            quarantined=quarantined,
            gate_root=gate_root,
            gate_manifest=gate_manifest,
            gate_coco=gate_coco,
            gate_lineage=gate_lineage,
            expected_sha256=expected_gate_sha256,
            owner_only=False,
        )
        eligible = set(result["gate_origin"]["train_eligible_image_sha256"])
        candidates = result["new_train_eligible_records"]
        kept = [row for row in candidates if row.get("image_sha256") in eligible]
        excluded = len(candidates) - len(kept)
        result["new_train_eligible_records"] = kept
        result["counts"]["new_train_eligible"] = len(kept)
        result["counts"]["gate_role_excluded"] = excluded
    result["input_sha256"] = dict(expected_sha256)
    payload = (
        json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    artifact = _secure_write_private_bytes_new(output, payload)
    output_sha = hashlib.sha256(payload).hexdigest()
    try:
        if artifact.sha256 != output_sha:
            raise ValueError("private audit publication mismatch")
        for role, path in paths.items():
            _assert_private_snapshot_unchanged(path, snapshots[role], name=role)
        if gate_root is not None and gate_manifest is not None and gate_lineage is not None:
            confirmed_origin = validate_gate_origin_artifacts(
                reviewed=reviewed,
                quarantined=quarantined,
                gate_root=gate_root,
                gate_manifest=gate_manifest,
                gate_coco=gate_coco,
                gate_lineage=gate_lineage,
                expected_sha256=expected_gate_sha256 or {},
                owner_only=False,
            )
            if confirmed_origin != result["gate_origin"]:
                raise ValueError("Gate origin changed at publication boundary")
        if not _artifact_is_self_owned(lock) or not _artifact_is_self_owned(artifact):
            raise ValueError(
                "private audit artifact ownership changed at success boundary"
            )
    except BaseException:
        _cleanup_if_self_owned(artifact)
        raise
    return {
        "status": AUDIT_STATUS,
        "counts": result["counts"],
        "output_sha256": output_sha,
        **WRITE_COUNTS,
    }


def run_owner_only_input_audit(
    *,
    v24_dataset: Path,
    historical_fingerprints: Path,
    expected_sha256: Mapping[str, str],
    output: Path,
    started_output: Path,
    expected_dataset_counts: Mapping[str, int] = {
        "train": 1458,
        "val": 153,
        "test": 151,
    },
    expected_historical_unique_count: int = 1822,
) -> dict[str, object]:
    """Publish the Gate-free Owner-only input capability.

    Gate artifacts are intentionally absent from this API. Their historical defects
    cannot become a runtime dependency of the approved Owner-only pipeline.
    """

    paths = {
        "v24_dataset": v24_dataset,
        "historical_fingerprints": historical_fingerprints,
    }
    if (
        set(expected_sha256) != set(paths)
        or any(
            not path.is_absolute()
            for path in (*paths.values(), output, started_output)
        )
        or any(
            not isinstance(value, str) or _SHA256.fullmatch(value) is None
            for value in expected_sha256.values()
        )
    ):
        raise ValueError("Owner-only private input pin contract mismatch")
    lock_payload = (
        json.dumps(
            {
                "schema": "yolo26n-v25-owner-only-input-audit-lock-v1",
                "status": "STARTED",
                "final_output": str(output),
                "input_sha256": dict(expected_sha256),
                **WRITE_COUNTS,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    lock = _secure_write_private_bytes_new(started_output, lock_payload)
    if lock.sha256 != hashlib.sha256(lock_payload).hexdigest():
        raise ValueError("Owner-only input audit lock publication mismatch")

    snapshots = {}
    payloads: dict[str, dict[str, object]] = {}
    for role, path in paths.items():
        snapshot = _read_private_snapshot(path)
        if hashlib.sha256(snapshot.payload).hexdigest() != expected_sha256[role]:
            raise ValueError("Owner-only private input pin mismatch")
        snapshots[role] = snapshot
        payloads[role] = _parse_strict_json_object(snapshot.payload, name=role)

    expected_counts = dict(expected_dataset_counts)
    _validated_dataset(payloads["v24_dataset"], expected_counts=expected_counts)
    _validated_historical(
        payloads["historical_fingerprints"],
        expected_unique_count=expected_historical_unique_count,
    )
    historical_artifacts = payloads["historical_fingerprints"].get(
        "artifact_sha256"
    )
    if (
        not isinstance(historical_artifacts, Mapping)
        or historical_artifacts.get("dataset") != expected_sha256["v24_dataset"]
    ):
        raise ValueError("historical dataset raw SHA pin mismatch")

    result = {
        "schema": OWNER_ONLY_AUDIT_SCHEMA,
        "status": OWNER_ONLY_AUDIT_STATUS,
        "gate_policy": "quarantine_all",
        "gate_candidate_count": 0,
        "gate_inputs_consumed": False,
        "protected_role_counts": {
            "validation153": expected_counts["val"],
            "internal-test151": expected_counts["test"],
            "owner-external60": ROLE_COUNTS["owner-external60"],
        },
        "historical_unique_image_count": expected_historical_unique_count,
        "input_sha256": dict(expected_sha256),
        **WRITE_COUNTS,
    }
    payload = (
        json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    artifact = _secure_write_private_bytes_new(output, payload)
    output_sha = hashlib.sha256(payload).hexdigest()
    try:
        if artifact.sha256 != output_sha:
            raise ValueError("Owner-only input audit publication mismatch")
        for role, path in paths.items():
            _assert_private_snapshot_unchanged(path, snapshots[role], name=role)
        if not _artifact_is_self_owned(lock) or not _artifact_is_self_owned(artifact):
            raise ValueError(
                "Owner-only input audit ownership changed at success boundary"
            )
    except BaseException:
        _cleanup_if_self_owned(artifact)
        raise
    return {
        "status": OWNER_ONLY_AUDIT_STATUS,
        "output_sha256": output_sha,
        **WRITE_COUNTS,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit YOLO v2.5 Gate and historical private inputs."
    )
    parser.add_argument("--gate-root", type=Path, required=True)
    parser.add_argument("--gate-manifest", type=Path, required=True)
    parser.add_argument("--gate-coco", type=Path, action="append", required=True)
    parser.add_argument("--gate-lineage", type=Path, required=True)
    parser.add_argument("--sample-audit-summary", type=Path, required=True)
    parser.add_argument("--positive-full-review-result", type=Path, required=True)
    parser.add_argument("--accepted-review", type=Path, required=True)
    parser.add_argument("--v24-dataset", type=Path, required=True)
    parser.add_argument("--historical-fingerprints", type=Path, required=True)
    parser.add_argument("--expected-sha256-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--started-output", type=Path, required=True)
    return parser


def build_owner_only_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit Gate-free YOLO v2.5 Owner-only private inputs."
    )
    parser.add_argument("--v24-dataset", type=Path, required=True)
    parser.add_argument("--historical-fingerprints", type=Path, required=True)
    parser.add_argument("--expected-sha256-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--started-output", type=Path, required=True)
    return parser


def build_lineage_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare canonical Gate quarantine lineage evidence."
    )
    parser.add_argument("--accepted-review", type=Path, required=True)
    parser.add_argument("--positive-full-review-result", type=Path, required=True)
    parser.add_argument("--expected-sha256-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--started-output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["prepare-gate-quarantine-lineage"]:
        args = build_lineage_parser().parse_args(arguments[1:])
        expected_snapshot = _read_private_snapshot(args.expected_sha256_json)
        expected_document = _parse_strict_json_object(
            expected_snapshot.payload, name="expected input SHA"
        )
        expected = expected_document.get("private_inputs")
        if set(expected_document) != {"private_inputs"} or not isinstance(
            expected, Mapping
        ):
            raise ValueError("expected input SHA contract mismatch")
        result = prepare_gate_quarantine_lineage(
            accepted_review=args.accepted_review,
            positive_full_review_result=args.positive_full_review_result,
            expected_sha256=expected,
            output=args.output,
            started_output=args.started_output,
        )
        print(
            json.dumps(
                {key: result[key] for key in ("status", "record_count", "output_sha256")},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if arguments[:1] == ["audit-owner-only"]:
        args = build_owner_only_parser().parse_args(arguments[1:])
        expected_snapshot = _read_private_snapshot(args.expected_sha256_json)
        expected_document = _parse_strict_json_object(
            expected_snapshot.payload, name="expected input SHA"
        )
        expected = expected_document.get("private_inputs")
        if set(expected_document) != {"private_inputs"} or not isinstance(
            expected, Mapping
        ):
            raise ValueError("expected input SHA contract mismatch")
        result = run_owner_only_input_audit(
            v24_dataset=args.v24_dataset,
            historical_fingerprints=args.historical_fingerprints,
            expected_sha256=expected,
            output=args.output,
            started_output=args.started_output,
        )
        print(
            json.dumps(
                {"status": result["status"], "output_sha256": result["output_sha256"]},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    args = build_parser().parse_args(arguments)
    expected_snapshot = _read_private_snapshot(args.expected_sha256_json)
    expected_document = _parse_strict_json_object(
        expected_snapshot.payload, name="expected input SHA"
    )
    expected = expected_document.get("private_inputs")
    expected_gate = expected_document.get("gate_inputs")
    if not isinstance(expected, Mapping) or not isinstance(expected_gate, Mapping):
        raise ValueError("expected input SHA contract mismatch")
    result = run_private_audit(
        sample_audit_summary=args.sample_audit_summary,
        positive_full_review_result=args.positive_full_review_result,
        accepted_review=args.accepted_review,
        v24_dataset=args.v24_dataset,
        historical_fingerprints=args.historical_fingerprints,
        expected_sha256=expected,
        output=args.output,
        started_output=args.started_output,
        gate_root=args.gate_root,
        gate_manifest=args.gate_manifest,
        gate_coco=args.gate_coco,
        gate_lineage=args.gate_lineage,
        expected_gate_sha256=expected_gate,
    )
    print(
        json.dumps(
            {"status": result["status"], "counts": result["counts"]},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

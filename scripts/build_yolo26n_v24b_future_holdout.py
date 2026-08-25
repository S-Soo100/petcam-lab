"""Build the blinded YOLO26n v2.4b future holdout from read-only inputs."""

from __future__ import annotations

import argparse
import ctypes
import csv
import errno
import hashlib
import io
import json
import math
import os
import platform
import stat
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Mapping, Sequence

import cv2
from PIL import Image, UnidentifiedImageError
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

try:
    from scripts.run_yolo26n_v24b_postprocess import (
        _write_private_bytes_new as _secure_write_private_bytes_new,
    )
except ModuleNotFoundError:  # Direct ``python scripts/...py`` execution.
    from run_yolo26n_v24b_postprocess import (  # type: ignore[no-redef]
        _write_private_bytes_new as _secure_write_private_bytes_new,
    )


SOURCE_CAP = 2
NIGHT_CAP = 20
MIN_CAMERAS = 3
MIN_NIGHTS = 6
PRESENCE_VALUES = frozenset({"positive", "negative", "ambiguous"})
WRITE_COUNTS = {
    "db_write_count": 0,
    "r2_write_count": 0,
    "service_write_count": 0,
    "git_write_count": 0,
}
OVERLAP_LEDGER_SCHEMA = "yolo26n-v24b-future-overlap-ledger-v1"
OVERLAP_LEDGER_STATUS = "V24B_FUTURE_OVERLAP_FROZEN"
OVERLAP_ROLE_COUNTS = {
    "dataset": 1762,
    "internal-test151": 151,
    "owner-external60": 60,
}
OVERLAP_ROOT_KEYS = frozenset(
    {
        "schema",
        "status",
        "role",
        "record_count",
        "records",
        "db_write_count",
        "r2_write_count",
        "service_write_count",
    }
)
OVERLAP_RECORD_KEYS = frozenset(
    {"source_ref", "image_sha256", "camera_night", "derivation_refs"}
)
PROTECTED_LINEAGE_SCHEMA = "yolo26n-v24b-protected-lineage-v1"
PROTECTED_LINEAGE_STATUS = "V24B_PROTECTED_LINEAGE_FROZEN"
PROTECTED_LINEAGE_SHORTAGE = "V24B_PROTECTED_LINEAGE_SHORTAGE"
PROTECTED_LINEAGE_ROOT_KEYS = frozenset(
    {
        "schema",
        "status",
        "role",
        "record_count",
        "records",
        "db_write_count",
        "r2_write_count",
        "service_write_count",
    }
)
PROTECTED_LINEAGE_RECORD_KEYS = frozenset(
    {
        "sequence",
        "image_sha256",
        "source_ref",
        "camera_night",
        "derivation_refs",
    }
)
DATASET_RECORD_KEYS = frozenset(
    {
        "sequence",
        "split",
        "image_path",
        "label_path",
        "image_sha256",
        "box_count",
        "positive",
        "source_dataset",
        "camera_night_group",
        "final_holdout_eligible",
    }
)
INTERNAL_LEDGER_ROOT_KEYS = frozenset(
    {
        "schema",
        "status",
        "dataset_schema",
        "evaluation_tier",
        "split",
        "candidate",
        "source_commit",
        "runner_sha256",
        "dataset_manifest_sha256",
        "checkpoint_sha256",
        "inference",
        "image_count",
        "gt_box_count",
        "prediction_count",
        "records",
        "threshold_freeze_sha256",
    }
)
INTERNAL_RECORD_KEYS = frozenset(
    {"sequence", "image_sha256", "width", "height", "gt_boxes", "predictions"}
)
EXTERNAL_LEDGER_ROOT_KEYS = frozenset(
    {
        "schema",
        "status",
        "candidate",
        "model_version",
        "threshold",
        "inference",
        "provenance",
        "records",
        "db_write_count",
        "r2_write_count",
        "service_write_count",
    }
)
EXTERNAL_RECORD_KEYS = frozenset(
    {"sequence", "image_sha256", "gt_boxes", "predictions"}
)
PREDICTION_KEYS = frozenset({"confidence", "xyxy"})
EXACT_HISTORICAL_INFERENCE = {
    "confidence": 0.001,
    "imgsz": 960,
    "nms_iou": 0.70,
    "max_det": 50,
    "device": "mps",
}
HISTORICAL_FINGERPRINT_SCHEMA = (
    "yolo26n-v24b-historical-fingerprint-exclusions-v1"
)
HISTORICAL_FINGERPRINT_STATUS = "V24B_HISTORICAL_FINGERPRINTS_FROZEN"
HISTORICAL_FINGERPRINT_SHORTAGE = "V24B_HISTORICAL_FINGERPRINT_SHORTAGE"
HISTORICAL_UNIQUE_IMAGE_COUNT = 1822
PINNED_PILLOW_VERSION = "12.2.0"
HISTORICAL_FINGERPRINT_POLICY = {
    "algorithm": "dhash64",
    "version": "pillow-rgb-luma-9x8-box-right-gt-left-v1",
    "pillow_version": PINNED_PILLOW_VERSION,
    "scope": "global-historical",
    "hamming_reject_max_distance": 2,
}
HISTORICAL_FINGERPRINT_ROOT_KEYS = frozenset(
    {
        "schema",
        "status",
        "freeze_sha256",
        "frozen_at",
        "artifact_sha256",
        "role_counts",
        "unique_image_count",
        "fingerprint_policy",
        "records",
        *WRITE_COUNTS,
    }
)


@dataclass(frozen=True)
class FutureFrame:
    source_ref: str
    camera_id: str
    camera_night: str
    recorded_at: str
    image_sha256: str
    dhash: int
    local_name: str


@dataclass(frozen=True)
class ExtractedFrame:
    frame_index: int
    jpeg_bytes: bytes
    width: int
    height: int


@dataclass(frozen=True)
class _PrivateSnapshot:
    payload: bytes
    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int


def choose_blind_reserve_pool(
    frames: Sequence[FutureFrame], *, seed: str, limit: int = 240
) -> tuple[FutureFrame, ...]:
    if not seed or limit < 1:
        raise ValueError("seed and positive limit are required")
    _validate_unique_frames(frames)
    ranked = sorted(frames, key=lambda row: _rank_key(seed, row))
    accepted: list[FutureFrame] = []
    source_counts: Counter[str] = Counter()
    night_counts: Counter[str] = Counter()
    source_dhashes: dict[str, list[int]] = {}
    for frame in ranked:
        if len(accepted) >= limit:
            break
        if source_counts[frame.source_ref] >= SOURCE_CAP:
            continue
        if night_counts[frame.camera_night] >= NIGHT_CAP:
            continue
        if any(
            (frame.dhash ^ existing).bit_count() <= 2
            for existing in source_dhashes.get(frame.source_ref, [])
        ):
            continue
        accepted.append(frame)
        source_counts[frame.source_ref] += 1
        night_counts[frame.camera_night] += 1
        source_dhashes.setdefault(frame.source_ref, []).append(frame.dhash)
    if len(accepted) >= MIN_CAMERAS and len(accepted) >= MIN_NIGHTS:
        if len({row.camera_id for row in accepted}) < MIN_CAMERAS:
            raise ValueError("blind reserve pool requires at least 3 cameras")
        if len({row.camera_night for row in accepted}) < MIN_NIGHTS:
            raise ValueError("blind reserve pool requires at least 6 nights")
    return tuple(accepted)


def choose_exact_holdout(
    pool: Sequence[FutureFrame],
    presence_rows: Sequence[Mapping[str, str]],
    *,
    positive_count: int = 60,
    negative_count: int = 60,
) -> tuple[FutureFrame, ...]:
    if positive_count < 0 or negative_count < 0 or positive_count + negative_count < 1:
        raise ValueError("positive and negative counts must be non-negative")
    _validate_unique_frames(pool)
    expected_sequences = {row.local_name for row in pool}
    labels: dict[str, str] = {}
    for raw in presence_rows:
        if set(raw) != {"sequence", "presence"}:
            raise ValueError("presence rows must contain exact sequence,presence columns")
        sequence = raw.get("sequence")
        presence = raw.get("presence")
        if not isinstance(sequence, str) or sequence not in expected_sequences:
            raise ValueError("each pool sequence must have exactly one presence row")
        if sequence in labels:
            raise ValueError("each pool sequence must have exactly one presence row")
        if presence not in PRESENCE_VALUES:
            raise ValueError("presence must be positive, negative, or ambiguous")
        labels[sequence] = presence
    if set(labels) != expected_sequences:
        raise ValueError("each pool sequence must have exactly one presence row")

    eligible = tuple(row for row in pool if labels[row.local_name] != "ambiguous")
    selected = _solve_exact_selection(
        eligible,
        labels=labels,
        positive_count=positive_count,
        negative_count=negative_count,
    )
    if selected is None:
        raise ValueError("V24B_FUTURE_HOLDOUT_SHORTAGE")
    return selected


def prepare_overlap(
    *,
    role: str,
    artifact: Path,
    expected_artifact_sha256: str,
    lineage_sot: Path,
    expected_lineage_sha256: str,
    output: Path,
) -> dict[str, object]:
    """Normalize one pinned historical artifact through protected lineage."""
    _require_absolute_paths(artifact, lineage_sot, output)
    if role not in OVERLAP_ROLE_COUNTS:
        raise ValueError("prepare-overlap role is invalid")
    _require_sha256(expected_artifact_sha256, name="artifact expected SHA-256")
    _require_sha256(expected_lineage_sha256, name="lineage expected SHA-256")
    if len({artifact, lineage_sot, output}) != 3:
        raise ValueError("prepare-overlap paths must be distinct")
    lock_path = (
        output.parent
        / ".locks"
        / f"{output.name}.prepare-overlap.started.private.json"
    )
    if output.exists() or lock_path.exists():
        raise FileExistsError("prepare-overlap is no-overwrite and one-shot")

    # Claim before opening either private input. A parse/SHA/join failure spends
    # this attempt so a concurrent loser never processes protected content.
    _write_private_json_new(
        lock_path,
        {
            "schema": "yolo26n-v24b-prepare-overlap-started-lock-v1",
            "status": "STARTED",
            "role": role,
            "artifact_sha256": expected_artifact_sha256,
            "lineage_sha256": expected_lineage_sha256,
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
            "git_write_count": 0,
        },
    )

    artifact_snapshot = _read_private_snapshot(artifact)
    lineage_snapshot = _read_private_snapshot(lineage_sot)
    if _sha_bytes(artifact_snapshot.payload) != expected_artifact_sha256:
        raise ValueError("artifact SHA-256 mismatch")
    if _sha_bytes(lineage_snapshot.payload) != expected_lineage_sha256:
        raise ValueError("lineage SHA-256 mismatch")
    artifact_payload = _parse_strict_json_object(
        artifact_snapshot.payload, name="historical artifact"
    )
    lineage_payload = _parse_strict_json_object(
        lineage_snapshot.payload, name="protected lineage"
    )
    identities = _adapt_historical_artifact(role, artifact_payload)
    lineage = _validate_protected_lineage(role, lineage_payload)
    if set(identities) != set(lineage):
        raise ValueError(PROTECTED_LINEAGE_SHORTAGE)

    normalized_records = [
        {
            "source_ref": lineage[identity]["source_ref"],
            "image_sha256": identity[1],
            "camera_night": lineage[identity]["camera_night"],
            "derivation_refs": lineage[identity]["derivation_refs"],
        }
        for identity in sorted(identities)
    ]
    _assert_private_snapshot_unchanged(
        artifact, artifact_snapshot, name="artifact"
    )
    _assert_private_snapshot_unchanged(
        lineage_sot, lineage_snapshot, name="lineage SOT"
    )
    _write_private_json_new(
        output,
        {
            "schema": OVERLAP_LEDGER_SCHEMA,
            "status": OVERLAP_LEDGER_STATUS,
            "role": role,
            "record_count": OVERLAP_ROLE_COUNTS[role],
            "records": normalized_records,
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
        },
    )
    return {
        "status": OVERLAP_LEDGER_STATUS,
        "role": role,
        "record_count": len(normalized_records),
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "git_write_count": 0,
    }


def prepare_historical_fingerprints(
    *,
    freeze: Path,
    expected_freeze_sha256: str,
    dataset_artifact: Path,
    expected_dataset_artifact_sha256: str,
    dataset_root: Path,
    internal_artifact: Path,
    expected_internal_artifact_sha256: str,
    external_artifact: Path,
    expected_external_artifact_sha256: str,
    external_snapshot: Path,
    expected_external_snapshot_sha256: str,
    external_image_root: Path,
    output: Path,
) -> dict[str, object]:
    """Freeze complete historical exact/perceptual content exclusions."""
    _assert_fingerprint_runtime()
    paths = (
        freeze,
        dataset_artifact,
        dataset_root,
        internal_artifact,
        external_artifact,
        external_snapshot,
        external_image_root,
        output,
    )
    _require_absolute_paths(*paths)
    expected_pins = {
        "freeze": _require_sha256(
            expected_freeze_sha256, name="freeze expected SHA-256"
        ),
        "dataset": _require_sha256(
            expected_dataset_artifact_sha256,
            name="dataset artifact expected SHA-256",
        ),
        "internal-test151": _require_sha256(
            expected_internal_artifact_sha256,
            name="internal artifact expected SHA-256",
        ),
        "owner-external60": _require_sha256(
            expected_external_artifact_sha256,
            name="external artifact expected SHA-256",
        ),
        "owner-external-snapshot": _require_sha256(
            expected_external_snapshot_sha256,
            name="external snapshot expected SHA-256",
        ),
    }
    lock_path = output.parent / ".locks/historical-fingerprints.started.private.json"
    if output.exists() or lock_path.exists():
        raise FileExistsError("historical fingerprints are no-overwrite and one-shot")
    _write_private_json_new(
        lock_path,
        {
            "schema": "yolo26n-v24b-historical-fingerprint-started-lock-v1",
            "status": "STARTED",
            "expected_sha256": expected_pins,
            **WRITE_COUNTS,
        },
    )

    snapshots = {
        "freeze": _read_private_snapshot(freeze),
        "dataset": _read_private_snapshot(dataset_artifact),
        "internal-test151": _read_private_snapshot(internal_artifact),
        "owner-external60": _read_private_snapshot(external_artifact),
        "owner-external-snapshot": _read_private_snapshot(external_snapshot),
    }
    for role, snapshot in snapshots.items():
        if _sha_bytes(snapshot.payload) != expected_pins[role]:
            raise ValueError(f"{role} SHA-256 mismatch")
    freeze_payload = _parse_strict_json_object(
        snapshots["freeze"].payload, name="postprocess freeze"
    )
    if (
        freeze_payload.get("schema") != "yolo26n-v24b-postprocess-freeze-v1"
        or freeze_payload.get("status")
        not in {
            "V24B_POSTPROCESS_FROZEN",
            "V24B_POSTPROCESS_FROZEN_DEVELOPMENT_ONLY",
        }
        or not isinstance(freeze_payload.get("frozen_at"), str)
        or any(
            freeze_payload.get(key) != 0
            for key in ("db_write_count", "r2_write_count", "service_write_count")
        )
    ):
        raise ValueError("postprocess freeze contract mismatch")
    frozen_at = str(freeze_payload["frozen_at"])
    _parse_timestamp(frozen_at)

    artifact_payloads = {
        role: _parse_strict_json_object(snapshots[role].payload, name=role)
        for role in ("dataset", "internal-test151", "owner-external60")
    }
    identities = {
        role: _adapt_historical_artifact(role, artifact_payloads[role])
        for role in artifact_payloads
    }
    dataset_payload = artifact_payloads["dataset"]
    dataset_test_identities = {
        (str(row["sequence"]), str(row["image_sha256"]))
        for row in dataset_payload["records"]
        if isinstance(row, Mapping) and row.get("split") == "test"
    }
    internal_payload = artifact_payloads["internal-test151"]
    if (
        set(identities["internal-test151"]) != dataset_test_identities
        or internal_payload.get("dataset_manifest_sha256") != expected_pins["dataset"]
    ):
        raise ValueError(HISTORICAL_FINGERPRINT_SHORTAGE)

    snapshot_payload = _parse_strict_json_object(
        snapshots["owner-external-snapshot"].payload,
        name="owner external snapshot",
    )
    external_snapshot_identities = _external_snapshot_identities(snapshot_payload)
    external_payload = artifact_payloads["owner-external60"]
    provenance = external_payload.get("provenance")
    if (
        not isinstance(provenance, Mapping)
        or provenance.get("snapshot_sha256")
        != expected_pins["owner-external-snapshot"]
        or set(identities["owner-external60"]) != external_snapshot_identities
    ):
        raise ValueError(HISTORICAL_FINGERPRINT_SHORTAGE)

    fingerprint_by_sha: dict[str, str] = {}
    try:
        records = dataset_payload.get("records")
        if not isinstance(records, list):
            raise ValueError("dataset records are missing")
        for row in records:
            if not isinstance(row, Mapping):
                raise ValueError("dataset record is invalid")
            relative = PurePosixPath(str(row["image_path"]))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("dataset image path is invalid")
            _capture_historical_fingerprint(
                dataset_root.joinpath(*relative.parts),
                expected_sha256=str(row["image_sha256"]),
                destination=fingerprint_by_sha,
            )
        for sequence, image_sha in sorted(identities["owner-external60"]):
            if not sequence or "/" in sequence or sequence in {".", ".."}:
                raise ValueError("external sequence is invalid")
            _capture_historical_fingerprint(
                external_image_root / f"{sequence}.jpg",
                expected_sha256=image_sha,
                destination=fingerprint_by_sha,
            )
    except (FileNotFoundError, OSError, ValueError):
        raise ValueError(HISTORICAL_FINGERPRINT_SHORTAGE) from None
    if len(fingerprint_by_sha) != HISTORICAL_UNIQUE_IMAGE_COUNT:
        raise ValueError(HISTORICAL_FINGERPRINT_SHORTAGE)

    for role, path in (
        ("freeze", freeze),
        ("dataset", dataset_artifact),
        ("internal-test151", internal_artifact),
        ("owner-external60", external_artifact),
        ("owner-external-snapshot", external_snapshot),
    ):
        _assert_private_snapshot_unchanged(
            path,
            snapshots[role],
            name=role,
        )
    ledger = {
        "schema": HISTORICAL_FINGERPRINT_SCHEMA,
        "status": HISTORICAL_FINGERPRINT_STATUS,
        "freeze_sha256": expected_pins["freeze"],
        "frozen_at": frozen_at,
        "artifact_sha256": {
            role: expected_pins[role]
            for role in (
                "dataset",
                "internal-test151",
                "owner-external60",
                "owner-external-snapshot",
            )
        },
        "role_counts": dict(OVERLAP_ROLE_COUNTS),
        "unique_image_count": HISTORICAL_UNIQUE_IMAGE_COUNT,
        "fingerprint_policy": dict(HISTORICAL_FINGERPRINT_POLICY),
        "records": [
            {"image_sha256": image_sha, "dhash64": fingerprint_by_sha[image_sha]}
            for image_sha in sorted(fingerprint_by_sha)
        ],
        **WRITE_COUNTS,
    }
    _write_private_json_new(output, ledger)
    return {
        "status": HISTORICAL_FINGERPRINT_STATUS,
        "dataset_count": OVERLAP_ROLE_COUNTS["dataset"],
        "internal_test151_count": OVERLAP_ROLE_COUNTS["internal-test151"],
        "owner_external60_count": OVERLAP_ROLE_COUNTS["owner-external60"],
        "unique_image_count": HISTORICAL_UNIQUE_IMAGE_COUNT,
        "r2_get_count": 0,
        **WRITE_COUNTS,
    }


def _external_snapshot_identities(
    payload: Mapping[str, object],
) -> set[tuple[str, str]]:
    rows = payload.get("images")
    if (
        payload.get("schema") != "yolo26n-owner-media-cvat-snapshot-v1"
        or not isinstance(rows, list)
        or len(rows) != 240
    ):
        raise ValueError("owner external snapshot contract mismatch")
    result: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        sequence = f"O{index + 1:04d}"
        if (
            not isinstance(row, Mapping)
            or row.get("frame") != index
            or row.get("path") != f"images/{sequence}.jpg"
            or row.get("partition")
            not in {"external_diagnostic", "training_candidate"}
        ):
            raise ValueError("owner external snapshot record mismatch")
        image_sha = _require_sha256(
            row.get("image_sha256"), name="external snapshot image SHA-256"
        )
        if row.get("partition") == "external_diagnostic":
            result.add((sequence, image_sha))
    if len(result) != OVERLAP_ROLE_COUNTS["owner-external60"]:
        raise ValueError("owner external snapshot count mismatch")
    return result


def _capture_historical_fingerprint(
    path: Path,
    *,
    expected_sha256: str,
    destination: dict[str, str],
) -> None:
    snapshot = _read_private_snapshot(path)
    image_sha = _sha_bytes(snapshot.payload)
    if image_sha != expected_sha256 or image_sha in destination:
        raise ValueError("historical image SHA mismatch or duplicate")
    destination[image_sha] = _historical_dhash64(snapshot.payload)


def _historical_dhash64(payload: bytes) -> str:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            rgb = image.convert("RGB")
            return f"{_dhash64_value(rgb):016x}"
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("historical image decode failed") from error


def _dhash64_value(rgb: Image.Image) -> int:
    _assert_fingerprint_runtime()
    resized = rgb.convert("L").resize((9, 8), Image.Resampling.BOX)
    pixels = resized.get_flattened_data()
    value = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            value = (value << 1) | int(
                pixels[offset + column + 1] > pixels[offset + column]
            )
    return value


def _assert_fingerprint_runtime() -> None:
    if getattr(Image, "__version__", None) != PINNED_PILLOW_VERSION:
        raise RuntimeError("historical fingerprint Pillow version mismatch")


def _validated_historical_fingerprints(
    payload: Mapping[str, object],
    *,
    freeze_sha256: str,
    frozen_at: str,
) -> tuple[tuple[dict[str, str], ...], set[str], tuple[int, ...]]:
    if (
        set(payload) != HISTORICAL_FINGERPRINT_ROOT_KEYS
        or payload.get("schema") != HISTORICAL_FINGERPRINT_SCHEMA
        or payload.get("status") != HISTORICAL_FINGERPRINT_STATUS
        or payload.get("freeze_sha256") != freeze_sha256
        or payload.get("frozen_at") != frozen_at
        or payload.get("role_counts") != OVERLAP_ROLE_COUNTS
        or payload.get("unique_image_count") != HISTORICAL_UNIQUE_IMAGE_COUNT
        or payload.get("fingerprint_policy") != HISTORICAL_FINGERPRINT_POLICY
        or any(payload.get(key) != 0 for key in WRITE_COUNTS)
    ):
        raise ValueError("historical fingerprint ledger contract mismatch")
    artifact_sha = payload.get("artifact_sha256")
    if (
        not isinstance(artifact_sha, Mapping)
        or set(artifact_sha)
        != {
            "dataset",
            "internal-test151",
            "owner-external60",
            "owner-external-snapshot",
        }
        or any(
            _require_sha256(value, name="historical artifact SHA-256") != value
            for value in artifact_sha.values()
        )
    ):
        raise ValueError("historical fingerprint artifact pins are invalid")
    raw_records = payload.get("records")
    if not isinstance(raw_records, list) or len(raw_records) != HISTORICAL_UNIQUE_IMAGE_COUNT:
        raise ValueError(HISTORICAL_FINGERPRINT_SHORTAGE)
    records: list[dict[str, str]] = []
    image_shas: set[str] = set()
    dhashes: list[int] = []
    for raw in raw_records:
        if not isinstance(raw, Mapping) or set(raw) != {"image_sha256", "dhash64"}:
            raise ValueError("historical fingerprint record is invalid")
        image_sha = _require_sha256(
            raw.get("image_sha256"), name="historical image SHA-256"
        )
        dhash = raw.get("dhash64")
        if (
            image_sha in image_shas
            or not isinstance(dhash, str)
            or len(dhash) != 16
            or dhash != dhash.lower()
            or any(character not in "0123456789abcdef" for character in dhash)
        ):
            raise ValueError("historical fingerprint record is invalid")
        image_shas.add(image_sha)
        dhashes.append(int(dhash, 16))
        records.append({"image_sha256": image_sha, "dhash64": dhash})
    return tuple(records), image_shas, tuple(dhashes)


def run_inventory(
    *,
    freeze: Path,
    output: Path,
    historical_fingerprints: Path,
    expected_historical_fingerprints_sha256: str,
    metadata_select: Callable[[str, str], Sequence[Mapping[str, object]]],
    seed: str,
    reserve_limit: int = 240,
    required_count: int = 120,
    r2_get: Callable[[str], bytes] | None = None,
    snapshot_through: str | None = None,
    dataset_source_json: Path | None = None,
    internal_test151_source_json: Path | None = None,
    owner_external60_source_json: Path | None = None,
) -> dict[str, object]:
    del r2_get  # Inventory is metadata-only by contract.
    overlap_paths = {
        role: path
        for role, path in {
            "dataset": dataset_source_json,
            "internal-test151": internal_test151_source_json,
            "owner-external60": owner_external60_source_json,
        }.items()
        if path is not None
    }
    _require_absolute_paths(
        freeze,
        historical_fingerprints,
        output,
        *overlap_paths.values(),
    )
    if len(set(overlap_paths.values())) != len(overlap_paths):
        raise ValueError("overlap ledger paths must be distinct by role")
    expected_historical_fingerprints_sha256 = _require_sha256(
        expected_historical_fingerprints_sha256,
        name="historical fingerprints expected SHA-256",
    )
    if reserve_limit < required_count or required_count < 1:
        raise ValueError("reserve_limit must cover required_count")
    freeze_snapshot = _read_private_snapshot(freeze)
    freeze_payload = _parse_json_object(freeze_snapshot.payload, name=freeze.name)
    if (
        freeze_payload.get("schema") != "yolo26n-v24b-postprocess-freeze-v1"
        or freeze_payload.get("status")
        not in {"V24B_POSTPROCESS_FROZEN", "V24B_POSTPROCESS_FROZEN_DEVELOPMENT_ONLY"}
        or any(freeze_payload.get(key) != 0 for key in WRITE_COUNTS if key != "git_write_count")
    ):
        raise ValueError("postprocess freeze contract mismatch")
    freeze_sha256 = _require_sha256(
        _sha_bytes(freeze_snapshot.payload),
        name="postprocess freeze SHA-256",
    )
    frozen_at = freeze_payload.get("frozen_at")
    if not isinstance(frozen_at, str):
        raise ValueError("postprocess freeze must pin frozen_at")
    frozen_datetime = _parse_timestamp(frozen_at)
    fingerprint_snapshot = _read_private_snapshot(historical_fingerprints)
    fingerprint_sha256 = _sha_bytes(fingerprint_snapshot.payload)
    if fingerprint_sha256 != expected_historical_fingerprints_sha256:
        raise ValueError("historical fingerprints SHA-256 mismatch")
    fingerprint_payload = _parse_strict_json_object(
        fingerprint_snapshot.payload,
        name="historical fingerprints",
    )
    historical_records, excluded_images, _historical_dhashes = (
        _validated_historical_fingerprints(
            fingerprint_payload,
            freeze_sha256=freeze_sha256,
            frozen_at=frozen_at,
        )
    )
    if snapshot_through is None:
        snapshot_through = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    through_datetime = _parse_timestamp(snapshot_through)
    if through_datetime <= frozen_datetime:
        raise ValueError("snapshot_through must be later than frozen_at")

    excluded_sources: set[str] = set()
    excluded_nights: set[str] = set()
    excluded_derivations: set[str] = set()
    overlap_snapshots: dict[str, _PrivateSnapshot] = {}
    for role, path in overlap_paths.items():
        snapshot, lineage = _read_overlap_ledger(path, expected_role=role)
        overlap_snapshots[role] = snapshot
        excluded_sources.update(lineage[0])
        excluded_images.update(lineage[1])
        excluded_nights.update(lineage[2])
        excluded_derivations.update(lineage[3])

    lock_path = output / ".locks/inventory.started.private.json"
    inventory_path = output / "inventory-selection.private.json"
    if inventory_path.exists():
        raise FileExistsError("inventory output exists")
    # Claim before the first SELECT. A failure spends this immutable attempt.
    _write_private_json_new(
        lock_path,
        {
            "schema": "yolo26n-v24b-future-inventory-started-lock-v1",
            "status": "STARTED",
            "frozen_after": frozen_at,
            "snapshot_through": snapshot_through,
            "freeze_sha256": freeze_sha256,
            "historical_fingerprint_sha256": fingerprint_sha256,
            "overlap_ledger_sha256": {
                role: _sha_bytes(snapshot.payload)
                for role, snapshot in overlap_snapshots.items()
            },
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
        },
    )

    raw_rows = metadata_select(frozen_at, snapshot_through)
    _assert_private_snapshot_unchanged(freeze, freeze_snapshot, name="freeze")
    _assert_private_snapshot_unchanged(
        historical_fingerprints,
        fingerprint_snapshot,
        name="historical fingerprints",
    )
    for role, path in overlap_paths.items():
        _assert_private_snapshot_unchanged(
            path,
            overlap_snapshots[role],
            name=f"overlap ledger {role}",
        )

    excluded_counts: Counter[str] = Counter()
    eligible: list[dict[str, object]] = []
    seen_sources: set[str] = set()
    for raw in sorted(raw_rows, key=_metadata_sort_key):
        try:
            row = _validated_metadata_source(raw)
        except ValueError:
            excluded_counts["incomplete_provenance"] += 1
            continue
        reasons: list[str] = []
        recorded_datetime = _parse_timestamp(str(row["recorded_at"]))
        if recorded_datetime <= frozen_datetime or recorded_datetime > through_datetime:
            reasons.append("freeze_boundary")
        if row["clip_purpose"] != "production":
            reasons.append("purpose")
        if _is_firmware_development(row):
            reasons.append("firmware_development")
        if row["source_ref"] in excluded_sources:
            reasons.append("source_overlap")
        if row["camera_night"] in excluded_nights:
            reasons.append("night_overlap")
        if set(row["derivation_refs"]) & excluded_derivations:
            reasons.append("derivation_overlap")
        if row["source_ref"] in seen_sources:
            reasons.append("source_overlap")
        if reasons:
            excluded_counts.update(set(reasons))
            continue
        seen_sources.add(str(row["source_ref"]))
        eligible.append(row)

    max_sources = min(len(eligible), (reserve_limit + SOURCE_CAP - 1) // SOURCE_CAP)
    selected_sources = _choose_metadata_sources(
        eligible,
        seed=seed,
        max_sources=max_sources,
        required_count=required_count,
    )
    frame_capacity = min(reserve_limit, len(selected_sources) * SOURCE_CAP)
    status = (
        "V24B_FUTURE_INVENTORY_READY"
        if frame_capacity >= required_count
        else "V24B_FUTURE_HOLDOUT_SHORTAGE"
    )
    result = {
        "status": status,
        "eligible_source_count": len(eligible),
        "selected_source_count": len(selected_sources),
        "frame_capacity": frame_capacity,
        "db_write_count": 0,
        "r2_get_count": 0,
        **{key: value for key, value in WRITE_COUNTS.items() if key != "db_write_count"},
    }
    ledger = {
        "schema": "yolo26n-v24b-future-inventory-v1",
        **result,
        "seed": seed,
        "reserve_limit": reserve_limit,
        "required_count": required_count,
        "frozen_after": frozen_at,
        "snapshot_through": snapshot_through,
        "freeze_sha256": freeze_sha256,
        "historical_fingerprint_sha256": fingerprint_sha256,
        "historical_unique_image_count": HISTORICAL_UNIQUE_IMAGE_COUNT,
        "historical_fingerprint_policy": dict(HISTORICAL_FINGERPRINT_POLICY),
        "historical_fingerprints": list(historical_records),
        "overlap_ledger_sha256": {
            role: _sha_bytes(snapshot.payload)
            for role, snapshot in overlap_snapshots.items()
        },
        "excluded_counts": dict(sorted(excluded_counts.items())),
        "sources": selected_sources,
    }
    _write_private_json_new(inventory_path, ledger)
    return result


def materialize_pool(
    *,
    output: Path,
    r2_get: Callable[[str], bytes],
    extract_frames: Callable[
        [bytes, Mapping[str, object]], Sequence[ExtractedFrame]
    ],
) -> dict[str, object]:
    _assert_fingerprint_runtime()
    _require_absolute_paths(output)
    inventory_path = output / "inventory-selection.private.json"
    lock_path = output / ".locks/materialize-pool.started.private.json"
    shortage_path = output / "materialize-shortage.private.json"
    final_dir = output / "blind-pool"
    if any(path.exists() for path in (lock_path, shortage_path, final_dir)):
        raise FileExistsError("materialize-pool is no-overwrite and one-shot")
    inventory_snapshot = _read_private_snapshot(inventory_path)
    inventory_bytes = inventory_snapshot.payload
    inventory_sha = _sha_bytes(inventory_bytes)
    inventory = _parse_json_object(inventory_bytes, name="inventory")
    if (
        inventory.get("schema") != "yolo26n-v24b-future-inventory-v1"
        or inventory.get("status") != "V24B_FUTURE_INVENTORY_READY"
    ):
        raise ValueError("ready future inventory is required")
    try:
        postprocess_freeze_sha256 = _require_sha256(
            inventory.get("freeze_sha256"),
            name="inventory freeze SHA-256",
        )
    except ValueError as error:
        raise ValueError("inventory freeze SHA-256 is invalid") from error
    historical_fingerprint_sha256 = _require_sha256(
        inventory.get("historical_fingerprint_sha256"),
        name="inventory historical fingerprint SHA-256",
    )
    historical_records = inventory.get("historical_fingerprints")
    if (
        inventory.get("historical_unique_image_count")
        != HISTORICAL_UNIQUE_IMAGE_COUNT
        or inventory.get("historical_fingerprint_policy")
        != HISTORICAL_FINGERPRINT_POLICY
        or not isinstance(historical_records, list)
        or len(historical_records) != HISTORICAL_UNIQUE_IMAGE_COUNT
    ):
        raise ValueError(HISTORICAL_FINGERPRINT_SHORTAGE)
    excluded_image_sha256: set[str] = set()
    historical_dhashes: list[int] = []
    for raw in historical_records:
        if not isinstance(raw, Mapping) or set(raw) != {"image_sha256", "dhash64"}:
            raise ValueError("inventory historical fingerprint record is invalid")
        image_sha = _require_sha256(
            raw.get("image_sha256"), name="inventory historical image SHA-256"
        )
        dhash = raw.get("dhash64")
        if (
            image_sha in excluded_image_sha256
            or not isinstance(dhash, str)
            or len(dhash) != 16
            or dhash != dhash.lower()
            or any(character not in "0123456789abcdef" for character in dhash)
        ):
            raise ValueError("inventory historical fingerprint record is invalid")
        excluded_image_sha256.add(image_sha)
        historical_dhashes.append(int(dhash, 16))
    sources = inventory.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("inventory sources are missing")
    validated_sources: list[dict[str, object]] = []
    for source in sources:
        if not isinstance(source, Mapping):
            raise ValueError("inventory source is invalid")
        validated_sources.append(_validated_metadata_source(source))

    # Claim before the first external R2 GET. A failed/short run stays spent.
    _write_private_json_new(
        lock_path,
        {
            "schema": "yolo26n-v24b-future-materialize-started-lock-v1",
            "status": "STARTED",
            "inventory_sha256": inventory_sha,
            "historical_fingerprint_sha256": historical_fingerprint_sha256,
        },
    )

    staging = _private_staging(output, "blind-pool")
    image_dir = staging / "images"
    image_dir.mkdir(mode=0o700)
    source_rows: list[dict[str, object]] = []
    source_sha_by_ref: dict[str, str] = {}
    frame_candidates: list[tuple[FutureFrame, bytes, int]] = []
    candidate_image_sha256: set[str] = set()
    rejection_counts: Counter[str] = Counter()
    r2_get_count = 0
    try:
        for row in validated_sources:
            payload = r2_get(str(row["r2_key"]))
            r2_get_count += 1
            if not isinstance(payload, bytes) or not payload:
                raise ValueError("R2 GET must return non-empty MP4 bytes")
            source_sha = _sha_bytes(payload)
            source_sha_by_ref[str(row["source_ref"])] = source_sha
            extracted = tuple(extract_frames(payload, row))
            source_rows.append(
                {
                    **row,
                    "source_mp4_sha256": source_sha,
                    "extracted_count": len(extracted),
                }
            )
            for candidate in extracted:
                if type(candidate.frame_index) is not int or candidate.frame_index < 0:
                    raise ValueError("extracted frame index is invalid")
                width, height, normalized_jpeg, dhash = _normalize_jpeg(candidate)
                raw_image_sha = _sha_bytes(candidate.jpeg_bytes)
                image_sha = _sha_bytes(normalized_jpeg)
                if raw_image_sha in excluded_image_sha256 or image_sha in excluded_image_sha256:
                    rejection_counts["historical_exact"] += 1
                    continue
                if _matches_historical_dhash(dhash, historical_dhashes):
                    rejection_counts["historical_dhash"] += 1
                    continue
                if image_sha in candidate_image_sha256:
                    rejection_counts["candidate_exact"] += 1
                    continue
                candidate_image_sha256.add(image_sha)
                frame_candidates.append(
                    (
                        FutureFrame(
                            source_ref=str(row["source_ref"]),
                            camera_id=str(row["camera_id"]),
                            camera_night=str(row["camera_night"]),
                            recorded_at=str(row["recorded_at"]),
                            image_sha256=image_sha,
                            dhash=dhash,
                            local_name=f"candidate-{len(frame_candidates) + 1}",
                        ),
                        normalized_jpeg,
                        candidate.frame_index,
                    )
                )
        if _read_private_snapshot(inventory_path) != inventory_snapshot:
            raise ValueError("inventory changed during materialization")
        candidate_by_identity = {
            _frame_identity(frame): (frame, payload, frame_index)
            for frame, payload, frame_index in frame_candidates
        }
        limit = int(inventory.get("reserve_limit", 240))
        try:
            selected = choose_blind_reserve_pool(
                [row[0] for row in candidate_by_identity.values()],
                seed=str(inventory.get("seed", "")),
                limit=limit,
            )
        except ValueError as error:
            if not str(error).startswith("blind reserve pool requires"):
                raise
            return _record_materialize_shortage(
                shortage_path,
                source_count=len(source_rows),
                r2_get_count=r2_get_count,
                reason="quota_infeasible",
                rejection_counts=rejection_counts,
            )
        if len(selected) < int(inventory.get("required_count", 120)):
            return _record_materialize_shortage(
                shortage_path,
                source_count=len(source_rows),
                r2_get_count=r2_get_count,
                reason="insufficient_feasible_frames",
                rejection_counts=rejection_counts,
            )
        private_frames: list[dict[str, object]] = []
        screen_rows: list[dict[str, str]] = []
        for ordinal, selected_frame in enumerate(selected, 1):
            _old_frame, jpeg, frame_index = candidate_by_identity[_frame_identity(selected_frame)]
            sequence = f"P{ordinal:04d}"
            filename = f"{sequence}.jpg"
            image_path = image_dir / filename
            _write_private_bytes_new(image_path, jpeg)
            private_frames.append(
                {
                    "sequence": sequence,
                    "source_ref": selected_frame.source_ref,
                    "camera_id": selected_frame.camera_id,
                    "camera_night": selected_frame.camera_night,
                    "recorded_at": selected_frame.recorded_at,
                    "frame_index": frame_index,
                    "derivation_refs": [
                        f"sha256:{source_sha_by_ref[selected_frame.source_ref]}:frame:{frame_index}"
                    ],
                    "image_sha256": selected_frame.image_sha256,
                    "dhash": selected_frame.dhash,
                    "width": _jpeg_dimensions(jpeg)[0],
                    "height": _jpeg_dimensions(jpeg)[1],
                }
            )
            screen_rows.append({"sequence": sequence, "presence": ""})
        screen_path = staging / "presence-screen.csv"
        _write_csv_new(screen_path, ["sequence", "presence"], screen_rows)
        zip_path = staging / "presence-screen.zip"
        _write_zip_new(
            zip_path,
            [(screen_path, "presence-screen.csv")]
            + [
                (
                    image_dir / f"{row['sequence']}.jpg",
                    f"images/{row['sequence']}.jpg",
                )
                for row in private_frames
            ],
        )
        ledger = {
            "schema": "yolo26n-v24b-future-pool-v1",
            "status": "V24B_FUTURE_POOL_READY",
            "postprocess_freeze_sha256": postprocess_freeze_sha256,
            "historical_fingerprint_sha256": historical_fingerprint_sha256,
            "historical_fingerprint_policy": dict(HISTORICAL_FINGERPRINT_POLICY),
            "seed": inventory.get("seed"),
            "inventory_sha256_pre": inventory_sha,
            "inventory_sha256_post": inventory_sha,
            "source_count": len(source_rows),
            "frame_count": len(private_frames),
            "sources": source_rows,
            "frames": private_frames,
            "rejection_counts": dict(sorted(rejection_counts.items())),
            "db_write_count": 0,
            "r2_get_count": r2_get_count,
            **{key: value for key, value in WRITE_COUNTS.items() if key != "db_write_count"},
        }
        _write_private_json_new(staging / "pool-ledger.private.json", ledger)
        _publish_directory_new(staging, final_dir)
    except BaseException:
        raise
    return {
        "status": "V24B_FUTURE_POOL_READY",
        "source_count": len(source_rows),
        "frame_count": len(private_frames),
        "db_write_count": 0,
        "r2_get_count": r2_get_count,
        **{key: value for key, value in WRITE_COUNTS.items() if key != "db_write_count"},
    }


def _record_materialize_shortage(
    path: Path,
    *,
    source_count: int,
    r2_get_count: int,
    reason: str,
    rejection_counts: Mapping[str, int],
) -> dict[str, object]:
    result = {
        "status": "V24B_FUTURE_HOLDOUT_SHORTAGE",
        "source_count": source_count,
        "frame_count": 0,
        "db_write_count": 0,
        "r2_get_count": r2_get_count,
        **{key: value for key, value in WRITE_COUNTS.items() if key != "db_write_count"},
    }
    _write_private_json_new(
        path,
        {
            "schema": "yolo26n-v24b-future-materialize-shortage-v1",
            **result,
            "reason": reason,
            "rejection_counts": dict(sorted(rejection_counts.items())),
        },
    )
    return result


def build_final(
    *,
    output: Path,
    presence_screen: Path,
    positive_count: int = 60,
    negative_count: int = 60,
) -> dict[str, object]:
    _require_absolute_paths(output, presence_screen)
    final_dir = output / "final-cvat"
    lock_path = output / ".locks/build-final.started.private.json"
    if final_dir.exists() or lock_path.exists():
        raise FileExistsError("build-final is no-overwrite and one-shot")
    ledger_path = output / "blind-pool/pool-ledger.private.json"
    ledger_snapshot = _read_private_snapshot(ledger_path)
    ledger_bytes = ledger_snapshot.payload
    ledger_sha = _sha_bytes(ledger_bytes)
    ledger = _parse_json_object(ledger_bytes, name="pool ledger")
    if (
        ledger.get("schema") != "yolo26n-v24b-future-pool-v1"
        or ledger.get("status") != "V24B_FUTURE_POOL_READY"
    ):
        raise ValueError("ready pool ledger is required")
    try:
        postprocess_freeze_sha256 = _require_sha256(
            ledger.get("postprocess_freeze_sha256"),
            name="pool freeze SHA-256",
        )
    except ValueError as error:
        raise ValueError("pool freeze SHA-256 is invalid") from error
    raw_frames = ledger.get("frames")
    if not isinstance(raw_frames, list):
        raise ValueError("pool frames are missing")
    pool: list[FutureFrame] = []
    private_by_sequence: dict[str, Mapping[str, object]] = {}
    for raw in raw_frames:
        if not isinstance(raw, Mapping):
            raise ValueError("pool frame is invalid")
        sequence = raw.get("sequence")
        if not isinstance(sequence, str) or sequence in private_by_sequence:
            raise ValueError("pool sequence is invalid or duplicate")
        private_by_sequence[sequence] = raw
        pool.append(
            FutureFrame(
                source_ref=str(raw.get("source_ref", "")),
                camera_id=str(raw.get("camera_id", "")),
                camera_night=str(raw.get("camera_night", "")),
                recorded_at=str(raw.get("recorded_at", "")),
                image_sha256=str(raw.get("image_sha256", "")),
                dhash=int(raw.get("dhash", -1)),
                local_name=sequence,
            )
        )
    presence_snapshot = _read_private_snapshot(presence_screen)
    presence_bytes = presence_snapshot.payload
    presence_sha = _sha_bytes(presence_bytes)
    presence_rows = _read_presence_csv(presence_bytes)
    try:
        selected = choose_exact_holdout(
            pool,
            presence_rows,
            positive_count=positive_count,
            negative_count=negative_count,
        )
    except ValueError as error:
        if str(error) != "V24B_FUTURE_HOLDOUT_SHORTAGE":
            raise
        return {
            "status": "V24B_FUTURE_HOLDOUT_SHORTAGE",
            "image_count": 0,
            "positive_count": 0,
            "negative_count": 0,
            "db_write_count": 0,
            "r2_get_count": 0,
            **{key: value for key, value in WRITE_COUNTS.items() if key != "db_write_count"},
        }

    label_by_sequence = {row["sequence"]: row["presence"] for row in presence_rows}
    # Feasibility is proven before claiming. Once claimed, any interruption is
    # a spent one-shot attempt and the lock must remain.
    _write_private_json_new(
        lock_path,
        {
            "schema": "yolo26n-v24b-future-build-final-started-lock-v1",
            "status": "STARTED",
            "pool_ledger_sha256": ledger_sha,
            "presence_screen_sha256": presence_sha,
        },
    )
    staging = _private_staging(output, "final-cvat")
    image_dir = staging / "images"
    image_dir.mkdir(mode=0o700)
    review_rows: list[dict[str, object]] = []
    manifest_rows: list[dict[str, object]] = []
    try:
        ordered = sorted(
            selected,
            key=lambda row: (label_by_sequence[row.local_name], row.local_name),
            reverse=True,
        )
        for ordinal, frame in enumerate(ordered, 1):
            private = private_by_sequence[frame.local_name]
            source_path = output / "blind-pool/images" / f"{frame.local_name}.jpg"
            payload = _read_private_bytes(source_path)
            if _sha_bytes(payload) != frame.image_sha256:
                raise ValueError("pool image SHA mismatch")
            width, height = _jpeg_dimensions(payload)
            if width != private.get("width") or height != private.get("height"):
                raise ValueError("pool image dimension mismatch")
            sequence = f"H{ordinal:04d}"
            filename = f"{sequence}.jpg"
            _write_private_bytes_new(image_dir / filename, payload)
            presence = label_by_sequence[frame.local_name]
            review_rows.append(
                {
                    "sequence": sequence,
                    "filename": filename,
                    "presence": presence,
                    "source_ref": frame.source_ref,
                    "camera_id": frame.camera_id,
                    "camera_night": frame.camera_night,
                    "source_sequence": frame.local_name,
                    "image_sha256": frame.image_sha256,
                    "width": width,
                    "height": height,
                    "dhash": frame.dhash,
                }
            )
            manifest_rows.append(
                {
                    "sequence": sequence,
                    "filename": filename,
                    "presence": presence,
                    "image_sha256": frame.image_sha256,
                    "width": width,
                    "height": height,
                }
            )
        review_index_path = staging / "review-index.csv"
        _write_csv_new(
            review_index_path,
            [
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
            ],
            review_rows,
        )
        # Pin the exact completed CSV bytes once; later checks compare path
        # identity without rereading protected source metadata.
        review_index_snapshot = _read_private_snapshot(review_index_path)
        review_index_sha = _sha_bytes(review_index_snapshot.payload)
        _write_zip_new(
            staging / "cvat-upload.zip",
            [
                (image_dir / str(row["filename"]), str(row["filename"]))
                for row in manifest_rows
            ],
        )
        manifest = {
            "schema": "yolo26n-v24b-future-holdout-v1",
            "status": "V24B_FUTURE_HOLDOUT_READY",
            "postprocess_freeze_sha256": postprocess_freeze_sha256,
            "pool_ledger_sha256_pre": ledger_sha,
            "pool_ledger_sha256_post": ledger_sha,
            "presence_screen_sha256_pre": presence_sha,
            "presence_screen_sha256_post": presence_sha,
            "review_index_sha256": review_index_sha,
            "image_count": len(manifest_rows),
            "positive_count": sum(row["presence"] == "positive" for row in manifest_rows),
            "negative_count": sum(row["presence"] == "negative" for row in manifest_rows),
            "ambiguous_count": 0,
            "prediction_prefill_count": 0,
            "records": manifest_rows,
            "db_write_count": 0,
            "r2_get_count": 0,
            **{key: value for key, value in WRITE_COUNTS.items() if key != "db_write_count"},
        }
        _write_private_json_new(staging / "manifest.private.json", manifest)
        _assert_private_snapshot_unchanged(
            review_index_path,
            review_index_snapshot,
            name="review index",
        )
        if _read_private_snapshot(ledger_path) != ledger_snapshot:
            raise ValueError("pool ledger changed during final build")
        if _read_private_snapshot(presence_screen) != presence_snapshot:
            raise ValueError("presence screen changed during final build")
        _publish_directory_new(staging, final_dir)
    except BaseException:
        raise
    return {
        "status": "V24B_FUTURE_HOLDOUT_READY",
        "image_count": len(manifest_rows),
        "positive_count": positive_count,
        "negative_count": negative_count,
        "db_write_count": 0,
        "r2_get_count": 0,
        **{key: value for key, value in WRITE_COUNTS.items() if key != "db_write_count"},
    }


def _rank_key(seed: str, frame: FutureFrame) -> tuple[str, tuple[object, ...]]:
    identity = _frame_identity(frame)
    digest = hashlib.sha256(repr((seed, identity)).encode("utf-8")).hexdigest()
    return digest, identity


def _frame_identity(frame: FutureFrame) -> tuple[object, ...]:
    return (
        frame.source_ref,
        frame.camera_id,
        frame.camera_night,
        frame.recorded_at,
        frame.image_sha256,
        frame.dhash,
        frame.local_name,
    )


def _validate_unique_frames(frames: Sequence[FutureFrame]) -> None:
    identities: set[tuple[object, ...]] = set()
    sequences: set[str] = set()
    for frame in frames:
        identity = _frame_identity(frame)
        if (
            not all(
                isinstance(value, str) and value
                for value in (
                    frame.source_ref,
                    frame.camera_id,
                    frame.camera_night,
                    frame.recorded_at,
                    frame.image_sha256,
                    frame.local_name,
                )
            )
            or type(frame.dhash) is not int
            or frame.dhash < 0
            or identity in identities
            or frame.local_name in sequences
        ):
            raise ValueError("future frame identity is invalid or duplicate")
        identities.add(identity)
        sequences.add(frame.local_name)


def _solve_exact_selection(
    frames: Sequence[FutureFrame],
    *,
    labels: Mapping[str, str],
    positive_count: int,
    negative_count: int,
) -> tuple[FutureFrame, ...] | None:
    if len(frames) < positive_count + negative_count:
        return None
    ordered = sorted(frames, key=_frame_identity)
    frame_count = len(ordered)
    cameras = sorted({row.camera_id for row in ordered})
    nights = sorted({row.camera_night for row in ordered})
    camera_offset = frame_count
    night_offset = camera_offset + len(cameras)
    variable_count = night_offset + len(nights)
    camera_variable = {
        camera: camera_offset + index for index, camera in enumerate(cameras)
    }
    night_variable = {
        night: night_offset + index for index, night in enumerate(nights)
    }
    constraints: list[tuple[list[int], float, float]] = []
    for presence, target in (("positive", positive_count), ("negative", negative_count)):
        constraints.append(
            ([index for index, row in enumerate(ordered) if labels[row.local_name] == presence], target, target)
        )
    for source in sorted({row.source_ref for row in ordered}):
        constraints.append(
            ([index for index, row in enumerate(ordered) if row.source_ref == source], 0, SOURCE_CAP)
        )
    for night in sorted({row.camera_night for row in ordered}):
        constraints.append(
            ([index for index, row in enumerate(ordered) if row.camera_night == night], 0, NIGHT_CAP)
        )
    for index, left in enumerate(ordered):
        for right_index in range(index + 1, frame_count):
            right = ordered[right_index]
            if left.source_ref == right.source_ref and (left.dhash ^ right.dhash).bit_count() <= 2:
                constraints.append(([index, right_index], 0, 1))
    signed_constraints: list[tuple[dict[int, float], float, float]] = [
        ({index: 1.0 for index in indices}, minimum, maximum)
        for indices, minimum, maximum in constraints
    ]
    for camera, variable in camera_variable.items():
        frame_indices = [
            index for index, row in enumerate(ordered) if row.camera_id == camera
        ]
        signed_constraints.append(
            ({**{index: 1.0 for index in frame_indices}, variable: -1.0}, 0, float("inf"))
        )
        signed_constraints.extend(
            ({index: 1.0, variable: -1.0}, float("-inf"), 0)
            for index in frame_indices
        )
    for night, variable in night_variable.items():
        frame_indices = [
            index for index, row in enumerate(ordered) if row.camera_night == night
        ]
        signed_constraints.append(
            ({**{index: 1.0 for index in frame_indices}, variable: -1.0}, 0, float("inf"))
        )
        signed_constraints.extend(
            ({index: 1.0, variable: -1.0}, float("-inf"), 0)
            for index in frame_indices
        )
    signed_constraints.append(
        ({variable: 1.0 for variable in camera_variable.values()}, MIN_CAMERAS, float("inf"))
    )
    signed_constraints.append(
        ({variable: 1.0 for variable in night_variable.values()}, MIN_NIGHTS, float("inf"))
    )
    matrix = lil_matrix((len(signed_constraints), variable_count), dtype=float)
    lower: list[float] = []
    upper: list[float] = []
    for row_number, (coefficients, minimum, maximum) in enumerate(signed_constraints):
        if not coefficients and minimum > 0:
            return None
        for index, coefficient in coefficients.items():
            matrix[row_number, index] = coefficient
        lower.append(minimum)
        upper.append(maximum)
    # Stable costs make the solver result deterministic without privileging input order.
    costs = [
        *(
            int(
                hashlib.sha256(repr(_frame_identity(row)).encode()).hexdigest()[:12],
                16,
            )
            / 16**12
            for row in ordered
        ),
        *([0.0] * (len(cameras) + len(nights))),
    ]
    result = milp(
        costs,
        integrality=[1] * variable_count,
        bounds=Bounds([0] * variable_count, [1] * variable_count),
        constraints=LinearConstraint(matrix.tocsr(), lower, upper),
        options={"presolve": True},
    )
    if not result.success or result.x is None:
        return None
    selected = tuple(
        row
        for row, take in zip(ordered, result.x[:frame_count], strict=True)
        if take > 0.5
    )
    if len(selected) != positive_count + negative_count:
        return None
    if len({row.camera_id for row in selected}) < MIN_CAMERAS:
        return None
    if len({row.camera_night for row in selected}) < MIN_NIGHTS:
        return None
    return selected


def _require_absolute_paths(*paths: Path) -> None:
    if any(not path.is_absolute() for path in paths):
        raise ValueError("all paths must be absolute")


def _read_private_bytes(path: Path) -> bytes:
    return _read_private_snapshot(path).payload


def _read_private_snapshot(path: Path) -> _PrivateSnapshot:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as error:
        if error.errno in {errno.ELOOP, 62}:
            raise ValueError("private input symlink is forbidden") from error
        raise
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("private input must be a regular file, not a symlink")
        if before.st_mode & 0o777 != 0o600:
            raise ValueError("private input mode must be exactly 0600")
        payload = bytearray()
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("private input changed while reading")
            payload.extend(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValueError("private input changed while reading")
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("private input changed while reading")
        return _PrivateSnapshot(
            bytes(payload),
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ValueError("private input symlink is forbidden") from error
        raise
    finally:
        os.close(descriptor)


def _assert_private_snapshot_unchanged(
    path: Path, snapshot: _PrivateSnapshot, *, name: str
) -> None:
    """Recheck identity without rereading a private payload."""
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as error:
        if error.errno in {errno.ELOOP, 62}:
            raise ValueError(f"{name} changed after validation") from error
        raise
    try:
        current = os.fstat(descriptor)
        identity = (
            current.st_dev,
            current.st_ino,
            current.st_mode,
            current.st_size,
            current.st_mtime_ns,
            current.st_ctime_ns,
        )
        expected = (
            snapshot.device,
            snapshot.inode,
            snapshot.mode,
            snapshot.size,
            snapshot.mtime_ns,
            snapshot.ctime_ns,
        )
        if not stat.S_ISREG(current.st_mode) or identity != expected:
            raise ValueError(f"{name} changed after validation")
    finally:
        os.close(descriptor)


def _read_overlap_ledger(
    path: Path, *, expected_role: str
) -> tuple[_PrivateSnapshot, tuple[set[str], set[str], set[str], set[str]]]:
    snapshot = _read_private_snapshot(path)
    payload = _parse_json_object(snapshot.payload, name="overlap ledger")
    expected_count = OVERLAP_ROLE_COUNTS[expected_role]
    if (
        set(payload) != OVERLAP_ROOT_KEYS
        or payload.get("schema") != OVERLAP_LEDGER_SCHEMA
        or payload.get("status") != OVERLAP_LEDGER_STATUS
        or payload.get("role") != expected_role
        or type(payload.get("record_count")) is not int
        or payload.get("record_count") != expected_count
        or any(
            payload.get(key) != 0
            for key in ("db_write_count", "r2_write_count", "service_write_count")
        )
    ):
        raise ValueError(f"overlap ledger {expected_role} contract mismatch")
    records = payload.get("records")
    if not isinstance(records, list) or len(records) != expected_count:
        raise ValueError(f"overlap ledger {expected_role} exact count mismatch")

    sources: set[str] = set()
    images: set[str] = set()
    nights: set[str] = set()
    derivations: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping) or set(record) != OVERLAP_RECORD_KEYS:
            raise ValueError(f"overlap ledger {expected_role} lineage is incomplete")
        source = record.get("source_ref")
        image = record.get("image_sha256")
        night = record.get("camera_night")
        raw_derivations = record.get("derivation_refs")
        if (
            not isinstance(source, str)
            or not source
            or not isinstance(image, str)
            or len(image) != 64
            or image != image.lower()
            or any(character not in "0123456789abcdef" for character in image)
            or not isinstance(night, str)
            or not night
            or not isinstance(raw_derivations, list)
            or not raw_derivations
            or any(
                not isinstance(value, str) or not value
                for value in raw_derivations
            )
            or len(set(raw_derivations)) != len(raw_derivations)
        ):
            raise ValueError(f"overlap ledger {expected_role} lineage is incomplete")
        sources.add(source)
        images.add(image)
        nights.add(night)
        derivations.update(raw_derivations)
    if len(images) != expected_count:
        raise ValueError(f"overlap ledger {expected_role} image identities are duplicate")
    return snapshot, (sources, images, nights, derivations)


def _parse_json_object(payload: bytes, *, name: str) -> dict[str, object]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{name} JSON is invalid") from error
    if not isinstance(value, dict):
        raise ValueError(f"{name} root must be an object")
    return value


def _parse_strict_json_object(payload: bytes, *, name: str) -> dict[str, object]:
    def reject_duplicate_keys(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{name} duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_raw: str) -> object:
        raise ValueError(f"{name} JSON contains non-finite constant")

    try:
        value = json.loads(
            payload,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{name} JSON is invalid") from error
    if not isinstance(value, dict):
        raise ValueError(f"{name} root must be an object")
    return value


def _require_sha256(value: object, *, name: str, length: int = 64) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} is invalid")
    return value


def _exact_zero_writes(payload: Mapping[str, object]) -> bool:
    return all(
        type(payload.get(key)) is int and payload.get(key) == 0
        for key in ("db_write_count", "r2_write_count", "service_write_count")
    )


def _adapt_historical_artifact(
    role: str, payload: Mapping[str, object]
) -> dict[tuple[str, str], None]:
    try:
        if role == "dataset":
            return _adapt_dataset_artifact(payload)
        if role == "internal-test151":
            return _adapt_internal_test_artifact(payload)
        if role == "owner-external60":
            return _adapt_owner_external_artifact(payload)
    except ValueError as error:
        raise ValueError(f"{role} artifact contract mismatch") from error
    raise ValueError("historical artifact role is invalid")


def _adapt_dataset_artifact(
    payload: Mapping[str, object],
) -> dict[tuple[str, str], None]:
    expected_splits = {"train": 1458, "val": 153, "test": 151}
    if (
        payload.get("schema") != "yolo26n-owner-dataset-v24"
        or type(payload.get("image_count")) is not int
        or payload.get("image_count") != 1762
        or payload.get("split_counts") != expected_splits
        or payload.get("evaluation_tier") != "development"
        or payload.get("future_holdout_required") is not True
        or not _exact_zero_writes(payload)
    ):
        raise ValueError("dataset artifact header is invalid")
    records = payload.get("records")
    if not isinstance(records, list) or len(records) != 1762:
        raise ValueError("dataset artifact count is invalid")
    identities: dict[tuple[str, str], None] = {}
    sequences: set[str] = set()
    images: set[str] = set()
    split_counts: Counter[str] = Counter()
    for record in records:
        if not isinstance(record, Mapping) or set(record) != DATASET_RECORD_KEYS:
            raise ValueError("dataset artifact record keys are invalid")
        sequence = record.get("sequence")
        split = record.get("split")
        image_sha = record.get("image_sha256")
        box_count = record.get("box_count")
        positive = record.get("positive")
        if (
            not isinstance(sequence, str)
            or not sequence
            or sequence in sequences
            or split not in expected_splits
            or record.get("image_path") != f"images/{split}/{sequence}.jpg"
            or record.get("label_path") != f"labels/{split}/{sequence}.txt"
            or not isinstance(image_sha, str)
            or image_sha in images
            or _require_sha256(image_sha, name="dataset image SHA-256") != image_sha
            or type(box_count) is not int
            or box_count < 0
            or type(positive) is not bool
            or positive != (box_count > 0)
            or not isinstance(record.get("source_dataset"), str)
            or not record.get("source_dataset")
            or not isinstance(record.get("camera_night_group"), str)
            or not record.get("camera_night_group")
            or type(record.get("final_holdout_eligible")) is not bool
        ):
            raise ValueError("dataset artifact record is invalid")
        sequences.add(sequence)
        images.add(image_sha)
        split_counts[str(split)] += 1
        identities[(sequence, image_sha)] = None
    if dict(split_counts) != expected_splits:
        raise ValueError("dataset artifact record split count is invalid")
    return identities


def _adapt_internal_test_artifact(
    payload: Mapping[str, object],
) -> dict[tuple[str, str], None]:
    if (
        set(payload) != INTERNAL_LEDGER_ROOT_KEYS
        or payload.get("schema") != "yolo26n-v24-prediction-ledger-v1"
        or payload.get("status") != "V24_PREDICTIONS_READY"
        or payload.get("dataset_schema") != "yolo26n-owner-dataset-v24"
        or payload.get("evaluation_tier") != "development"
        or payload.get("split") != "test"
        or payload.get("candidate") != "warm-start"
        or _require_sha256(
            payload.get("source_commit"), name="source commit", length=40
        )
        != payload.get("source_commit")
        or any(
            _require_sha256(payload.get(key), name=key) != payload.get(key)
            for key in (
                "runner_sha256",
                "dataset_manifest_sha256",
                "checkpoint_sha256",
                "threshold_freeze_sha256",
            )
        )
        or payload.get("inference") != EXACT_HISTORICAL_INFERENCE
        or type(payload.get("image_count")) is not int
        or payload.get("image_count") != 151
        or type(payload.get("gt_box_count")) is not int
        or payload.get("gt_box_count") < 0
        or type(payload.get("prediction_count")) is not int
        or payload.get("prediction_count") < 0
    ):
        raise ValueError("internal artifact header is invalid")
    records = payload.get("records")
    return _prediction_record_identities(
        records,
        expected_count=151,
        expected_gt_count=int(payload["gt_box_count"]),
        expected_prediction_count=int(payload["prediction_count"]),
        dimensions_required=True,
        exact_keys=INTERNAL_RECORD_KEYS,
    )


def _adapt_owner_external_artifact(
    payload: Mapping[str, object],
) -> dict[tuple[str, str], None]:
    threshold = payload.get("threshold")
    provenance = payload.get("provenance")
    if (
        set(payload) != EXTERNAL_LEDGER_ROOT_KEYS
        or payload.get("schema")
        != "yolo26n-owner-media-external-predictions-v1"
        or payload.get("status") != "PREDICTIONS_COMPLETE"
        or payload.get("candidate") != "warm-start"
        or payload.get("model_version") != "v24"
        or type(threshold) not in {int, float}
        or not math.isfinite(float(threshold))
        or float(threshold)
        not in {round(index * 0.05, 2) for index in range(1, 17)}
        or payload.get("inference") != EXACT_HISTORICAL_INFERENCE
        or not isinstance(provenance, Mapping)
        or set(provenance)
        != {
            "freeze_sha256",
            "snapshot_sha256",
            "summary_sha256",
            "checkpoint_sha256",
        }
        or any(
            _require_sha256(provenance.get(key), name=f"external {key}")
            != provenance.get(key)
            for key in provenance
        )
        or not _exact_zero_writes(payload)
    ):
        raise ValueError("external artifact header is invalid")
    return _prediction_record_identities(
        payload.get("records"),
        expected_count=60,
        expected_gt_count=None,
        expected_prediction_count=None,
        dimensions_required=False,
        exact_keys=EXTERNAL_RECORD_KEYS,
    )


def _prediction_record_identities(
    raw_records: object,
    *,
    expected_count: int,
    expected_gt_count: int | None,
    expected_prediction_count: int | None,
    dimensions_required: bool,
    exact_keys: frozenset[str],
) -> dict[tuple[str, str], None]:
    if not isinstance(raw_records, list) or len(raw_records) != expected_count:
        raise ValueError("prediction artifact record count is invalid")
    identities: dict[tuple[str, str], None] = {}
    sequences: set[str] = set()
    images: set[str] = set()
    gt_count = prediction_count = 0
    for record in raw_records:
        if not isinstance(record, Mapping) or set(record) != exact_keys:
            raise ValueError("prediction artifact record keys are invalid")
        sequence = record.get("sequence")
        image_sha = record.get("image_sha256")
        width = record.get("width") if dimensions_required else None
        height = record.get("height") if dimensions_required else None
        if (
            not isinstance(sequence, str)
            or not sequence
            or sequence in sequences
            or not isinstance(image_sha, str)
            or image_sha in images
            or _require_sha256(image_sha, name="prediction image SHA-256")
            != image_sha
            or (
                dimensions_required
                and (
                    type(width) is not int
                    or type(height) is not int
                    or width <= 0
                    or height <= 0
                )
            )
        ):
            raise ValueError("prediction artifact identity is invalid")
        gt_boxes = record.get("gt_boxes")
        predictions = record.get("predictions")
        if not isinstance(gt_boxes, list) or not isinstance(predictions, list):
            raise ValueError("prediction artifact boxes are invalid")
        for box in gt_boxes:
            _validate_artifact_box(box, width=width, height=height)
        for prediction in predictions:
            if not isinstance(prediction, Mapping) or set(prediction) != PREDICTION_KEYS:
                raise ValueError("prediction artifact prediction is invalid")
            confidence = prediction.get("confidence")
            if (
                type(confidence) not in {int, float}
                or not math.isfinite(float(confidence))
                or not 0.0 <= float(confidence) <= 1.0
            ):
                raise ValueError("prediction artifact confidence is invalid")
            _validate_artifact_box(
                prediction.get("xyxy"), width=width, height=height
            )
        sequences.add(sequence)
        images.add(image_sha)
        identities[(sequence, image_sha)] = None
        gt_count += len(gt_boxes)
        prediction_count += len(predictions)
    if expected_gt_count is not None and gt_count != expected_gt_count:
        raise ValueError("prediction artifact GT count is invalid")
    if (
        expected_prediction_count is not None
        and prediction_count != expected_prediction_count
    ):
        raise ValueError("prediction artifact prediction count is invalid")
    return identities


def _validate_artifact_box(
    raw: object, *, width: int | None, height: int | None
) -> None:
    if (
        not isinstance(raw, list)
        or len(raw) != 4
        or any(
            type(value) not in {int, float} or not math.isfinite(float(value))
            for value in raw
        )
    ):
        raise ValueError("prediction artifact box is invalid")
    x1, y1, x2, y2 = (float(value) for value in raw)
    if not (0 <= x1 < x2 and 0 <= y1 < y2):
        raise ValueError("prediction artifact box is invalid")
    if width is not None and height is not None and (x2 > width or y2 > height):
        raise ValueError("prediction artifact box is out of bounds")


def _validate_protected_lineage(
    role: str, payload: Mapping[str, object]
) -> dict[tuple[str, str], dict[str, object]]:
    try:
        return _validate_protected_lineage_strict(role, payload)
    except ValueError as error:
        raise ValueError(PROTECTED_LINEAGE_SHORTAGE) from error


def _validate_protected_lineage_strict(
    role: str, payload: Mapping[str, object]
) -> dict[tuple[str, str], dict[str, object]]:
    expected_count = OVERLAP_ROLE_COUNTS[role]
    if (
        set(payload) != PROTECTED_LINEAGE_ROOT_KEYS
        or payload.get("schema") != PROTECTED_LINEAGE_SCHEMA
        or payload.get("status") != PROTECTED_LINEAGE_STATUS
        or payload.get("role") != role
        or type(payload.get("record_count")) is not int
        or payload.get("record_count") != expected_count
        or not _exact_zero_writes(payload)
    ):
        raise ValueError("protected lineage header is invalid")
    records = payload.get("records")
    if not isinstance(records, list) or len(records) != expected_count:
        raise ValueError("protected lineage count is invalid")
    result: dict[tuple[str, str], dict[str, object]] = {}
    for record in records:
        if (
            not isinstance(record, Mapping)
            or set(record) != PROTECTED_LINEAGE_RECORD_KEYS
        ):
            raise ValueError("protected lineage record keys are invalid")
        sequence = record.get("sequence")
        image_sha = record.get("image_sha256")
        source_ref = record.get("source_ref")
        camera_night = record.get("camera_night")
        derivations = record.get("derivation_refs")
        identity = (sequence, image_sha)
        if (
            not isinstance(sequence, str)
            or not sequence
            or not isinstance(image_sha, str)
            or _require_sha256(image_sha, name="lineage image SHA-256")
            != image_sha
            or identity in result
            or not isinstance(source_ref, str)
            or not source_ref
            or not isinstance(camera_night, str)
            or not camera_night
            or not isinstance(derivations, list)
            or not derivations
            or any(not isinstance(value, str) or not value for value in derivations)
            or len(set(derivations)) != len(derivations)
        ):
            raise ValueError("protected lineage record is incomplete")
        result[(sequence, image_sha)] = {
            "source_ref": source_ref,
            "camera_night": camera_night,
            "derivation_refs": list(derivations),
        }
    return result


def _read_private_json(path: Path) -> dict[str, object]:
    return _parse_json_object(_read_private_bytes(path), name=path.name)


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _parse_timestamp(raw: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include an explicit offset")
    return parsed.astimezone(timezone.utc)


def _collect_overlap_values(
    payload: object,
    *,
    source_refs: set[str],
    image_sha256: set[str],
    camera_nights: set[str],
    derivation_refs: set[str],
) -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if key in {"source_ref", "source_clip_ref", "clip_id"} and isinstance(value, str) and value:
                source_refs.add(value)
            elif key in {"image_sha256", "source_image_sha256"} and isinstance(value, str) and value:
                image_sha256.add(value)
            elif key in {"camera_night", "camera_night_ref", "camera_night_group"} and isinstance(value, str) and value:
                camera_nights.add(value)
            elif key in {"derivation_ref", "parent_ref", "source_derivation_ref"} and isinstance(value, str) and value:
                derivation_refs.add(value)
            elif key == "derivation_refs" and isinstance(value, list):
                derivation_refs.update(item for item in value if isinstance(item, str) and item)
            _collect_overlap_values(
                value,
                source_refs=source_refs,
                image_sha256=image_sha256,
                camera_nights=camera_nights,
                derivation_refs=derivation_refs,
            )
    elif isinstance(payload, list):
        for value in payload:
            _collect_overlap_values(
                value,
                source_refs=source_refs,
                image_sha256=image_sha256,
                camera_nights=camera_nights,
                derivation_refs=derivation_refs,
            )


def _metadata_sort_key(row: Mapping[str, object]) -> tuple[str, str]:
    return str(row.get("recorded_at", "")), str(row.get("source_ref", row.get("id", "")))


def _validated_metadata_source(raw: Mapping[str, object]) -> dict[str, object]:
    source_ref = raw.get("source_ref", raw.get("id"))
    camera_id = raw.get("camera_id")
    recorded_at = raw.get("recorded_at", raw.get("started_at"))
    camera_night = raw.get("camera_night", raw.get("camera_night_ref"))
    clip_purpose = raw.get("clip_purpose")
    r2_key = raw.get("r2_key")
    derivations = raw.get("derivation_refs")
    if derivations is None and isinstance(source_ref, str) and source_ref:
        derivations = [f"motion_clips:{source_ref}"]
    if camera_night is None and isinstance(camera_id, str) and isinstance(recorded_at, str):
        camera_night = _camera_night(camera_id, recorded_at)
    if not isinstance(derivations, list) or any(
        not isinstance(value, str) or not value for value in derivations
    ):
        raise ValueError("source derivation refs are invalid")
    if not all(
        isinstance(value, str) and value
        for value in (source_ref, camera_id, camera_night, recorded_at, clip_purpose, r2_key)
    ):
        raise ValueError("source identity is incomplete")
    _parse_timestamp(str(recorded_at))
    return {
        "source_ref": source_ref,
        "camera_id": camera_id,
        "camera_night": camera_night,
        "recorded_at": recorded_at,
        "clip_purpose": clip_purpose,
        "r2_key": r2_key,
        "derivation_refs": list(derivations),
    }


def _camera_night(camera_id: str, recorded_at: str) -> str:
    local = _parse_timestamp(recorded_at).astimezone(
        timezone(timedelta(hours=9))
    ) - timedelta(hours=12)
    raw = f"{camera_id}:{local.date().isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _matches_historical_dhash(candidate: int, historical: Sequence[int]) -> bool:
    threshold = int(
        HISTORICAL_FINGERPRINT_POLICY["hamming_reject_max_distance"]
    )
    return any((candidate ^ fingerprint).bit_count() <= threshold for fingerprint in historical)


def _is_firmware_development(row: Mapping[str, object]) -> bool:
    r2_key = str(row.get("r2_key", "")).lower()
    purpose = str(row.get("clip_purpose", "")).lower()
    return any(token in r2_key or token in purpose for token in ("firmware-dev", "firmware_dev", "firmware/development"))


def _choose_metadata_sources(
    rows: Sequence[dict[str, object]],
    *,
    seed: str,
    max_sources: int,
    required_count: int,
) -> list[dict[str, object]]:
    ranked = sorted(
        rows,
        key=lambda row: (
            hashlib.sha256(f"{seed}:{row['source_ref']}".encode()).hexdigest(),
            str(row["source_ref"]),
        ),
    )
    max_sources = min(max_sources, len(ranked))
    if max_sources < 1:
        return []
    required_sources = (required_count + SOURCE_CAP - 1) // SOURCE_CAP
    feasible = _solve_metadata_selection(
        ranked,
        max_sources=max_sources,
        required_sources=required_sources,
    )
    if feasible is not None:
        return feasible

    # Preserve an honest below-quota capacity for a shortage result. If this
    # fallback could meet the count, its missing diversity is itself shortage.
    selected: list[dict[str, object]] = []
    night_counts: Counter[str] = Counter()
    for row in ranked:
        if len(selected) >= max_sources:
            break
        night = str(row["camera_night"])
        if night_counts[night] >= NIGHT_CAP // SOURCE_CAP:
            continue
        selected.append(row)
        night_counts[night] += 1
    if len(selected) >= required_sources:
        return []
    return selected


def _solve_metadata_selection(
    ranked: Sequence[dict[str, object]],
    *,
    max_sources: int,
    required_sources: int,
) -> list[dict[str, object]] | None:
    if required_sources < 1 or len(ranked) < required_sources:
        return None
    cameras = sorted({str(row["camera_id"]) for row in ranked})
    nights = sorted({str(row["camera_night"]) for row in ranked})
    if len(cameras) < MIN_CAMERAS or len(nights) < MIN_NIGHTS:
        return None

    source_count = len(ranked)
    camera_offset = source_count
    night_offset = camera_offset + len(cameras)
    variable_count = night_offset + len(nights)
    camera_variable = {
        camera: camera_offset + index for index, camera in enumerate(cameras)
    }
    night_variable = {
        night: night_offset + index for index, night in enumerate(nights)
    }
    constraints: list[tuple[dict[int, float], float, float]] = [
        (
            {index: 1.0 for index in range(source_count)},
            required_sources,
            max_sources,
        )
    ]
    for night in nights:
        constraints.append(
            (
                {
                    index: 1.0
                    for index, row in enumerate(ranked)
                    if str(row["camera_night"]) == night
                },
                0,
                NIGHT_CAP // SOURCE_CAP,
            )
        )
    for camera, variable in camera_variable.items():
        indices = [
            index
            for index, row in enumerate(ranked)
            if str(row["camera_id"]) == camera
        ]
        constraints.append(
            ({**{index: 1.0 for index in indices}, variable: -1.0}, 0, float("inf"))
        )
        constraints.extend(
            ({index: 1.0, variable: -1.0}, float("-inf"), 0)
            for index in indices
        )
    for night, variable in night_variable.items():
        indices = [
            index
            for index, row in enumerate(ranked)
            if str(row["camera_night"]) == night
        ]
        constraints.append(
            ({**{index: 1.0 for index in indices}, variable: -1.0}, 0, float("inf"))
        )
        constraints.extend(
            ({index: 1.0, variable: -1.0}, float("-inf"), 0)
            for index in indices
        )
    constraints.append(
        ({variable: 1.0 for variable in camera_variable.values()}, MIN_CAMERAS, float("inf"))
    )
    constraints.append(
        ({variable: 1.0 for variable in night_variable.values()}, MIN_NIGHTS, float("inf"))
    )

    matrix = lil_matrix((len(constraints), variable_count), dtype=float)
    lower: list[float] = []
    upper: list[float] = []
    for row_number, (coefficients, minimum, maximum) in enumerate(constraints):
        for index, coefficient in coefficients.items():
            matrix[row_number, index] = coefficient
        lower.append(minimum)
        upper.append(maximum)
    # One more source always wins over all tie-break costs combined.
    source_costs = [
        -(source_count + 1.0) + index / max(1, source_count)
        for index in range(source_count)
    ]
    result = milp(
        [*source_costs, *([0.0] * (len(cameras) + len(nights)))],
        integrality=[1] * variable_count,
        bounds=Bounds([0] * variable_count, [1] * variable_count),
        constraints=LinearConstraint(matrix.tocsr(), lower, upper),
        options={"presolve": True},
    )
    if not result.success or result.x is None:
        return None
    selected = [
        row
        for row, take in zip(ranked, result.x[:source_count], strict=True)
        if take > 0.5
    ]
    if (
        len(selected) < required_sources
        or len(selected) > max_sources
        or len({str(row["camera_id"]) for row in selected}) < MIN_CAMERAS
        or len({str(row["camera_night"]) for row in selected}) < MIN_NIGHTS
        or max(Counter(str(row["camera_night"]) for row in selected).values())
        > NIGHT_CAP // SOURCE_CAP
    ):
        return None
    return selected


def _private_staging(output: Path, name: str) -> Path:
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.chmod(0o700)
    path = Path(tempfile.mkdtemp(prefix=f".{name}-staging-", dir=output))
    path.chmod(0o700)
    return path


def _write_private_bytes_new(path: Path, payload: bytes) -> None:
    _secure_write_private_bytes_new(path, payload)


def _write_private_json_new(path: Path, value: object) -> None:
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    _write_private_bytes_new(path, payload)


def _write_csv_new(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    _write_private_bytes_new(path, output.getvalue().encode("utf-8"))


def _write_zip_new(path: Path, members: Sequence[tuple[Path, str]]) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, arcname in members:
            info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, _read_private_bytes(source))
    _write_private_bytes_new(path, buffer.getvalue())


def _publish_directory_new(staging: Path, destination: Path) -> None:
    if staging.parent.stat().st_dev != destination.parent.stat().st_dev:
        raise OSError(errno.EXDEV, "atomic publication requires one filesystem")
    libc = ctypes.CDLL(None, use_errno=True)
    system = platform.system()
    if system == "Darwin":
        rename = getattr(libc, "renameatx_np", None)
        at_fdcwd = -2
        flag = 0x4
    elif system == "Linux":
        rename = getattr(libc, "renameat2", None)
        at_fdcwd = -100
        flag = 0x1
    else:
        rename = None
        at_fdcwd = flag = 0
    if rename is None:
        raise OSError(errno.ENOTSUP, "atomic no-overwrite publication is unavailable")
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    if rename(
        at_fdcwd,
        os.fsencode(staging),
        at_fdcwd,
        os.fsencode(destination),
        flag,
    ) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    destination.chmod(0o700)


def _jpeg_dimensions(payload: bytes) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            if image.format != "JPEG":
                raise ValueError("extracted frame is not JPEG")
            return image.size
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("extracted JPEG decode failed") from error


def _normalize_jpeg(frame: ExtractedFrame) -> tuple[int, int, bytes, int]:
    width, height = _jpeg_dimensions(frame.jpeg_bytes)
    if width <= 0 or height <= 0:
        raise ValueError("extracted JPEG dimensions are invalid")
    if type(frame.width) is not int or type(frame.height) is not int or (frame.width, frame.height) != (width, height):
        raise ValueError("extracted JPEG dimension mismatch")
    try:
        with Image.open(io.BytesIO(frame.jpeg_bytes)) as image:
            rgb = image.convert("RGB")
            normalized = io.BytesIO()
            # Re-encoding drops EXIF/comment/source metadata before Owner exposure.
            rgb.save(normalized, format="JPEG", quality=95, optimize=False)
            normalized_jpeg = normalized.getvalue()
            value = _dhash64_value(rgb)
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("extracted JPEG decode failed") from error
    return width, height, normalized_jpeg, value


def _read_presence_csv(payload: bytes) -> list[dict[str, str]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("presence screen must be UTF-8") from error
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames != ["sequence", "presence"]:
        raise ValueError("presence CSV must have exact sequence,presence header")
    return [dict(row) for row in reader]


def _paged_metadata_select(
    client: object,
    *,
    frozen_after: str,
    snapshot_through: str,
    page_size: int = 1000,
) -> list[Mapping[str, object]]:
    if page_size < 1:
        raise ValueError("pagination page_size must be positive")
    lower = _parse_timestamp(frozen_after)
    upper = _parse_timestamp(snapshot_through)
    if upper <= lower:
        raise ValueError("pagination snapshot cutoff is invalid")

    rows: list[Mapping[str, object]] = []
    seen_ids: set[str] = set()
    previous_key: tuple[datetime, str] | None = None
    total_count: int | None = None
    start = 0
    while total_count is None or start < total_count:
        response = (
            client.table("motion_clips")
            .select("id,camera_id,started_at,r2_key,clip_purpose", count="exact")
            .gt("started_at", frozen_after)
            .lte("started_at", snapshot_through)
            .eq("clip_purpose", "production")
            .not_.is_("r2_key", "null")
            .order("started_at")
            .order("id")
            .range(start, start + page_size - 1)
            .execute()
        )
        count = getattr(response, "count", None)
        if type(count) is not int or count < 0:
            raise ValueError("pagination exact count is missing")
        if total_count is None:
            total_count = count
        elif count != total_count:
            raise ValueError("pagination snapshot count changed")
        page = getattr(response, "data", None) or []
        if not isinstance(page, list):
            raise ValueError("pagination page is invalid")
        expected_page_count = min(page_size, max(0, total_count - start))
        if len(page) != expected_page_count:
            raise ValueError("pagination page is missing rows")
        for raw in page:
            if not isinstance(raw, Mapping):
                raise ValueError("pagination row is invalid")
            row_id = raw.get("id")
            started_at = raw.get("started_at")
            if not isinstance(row_id, str) or not row_id or not isinstance(started_at, str):
                raise ValueError("pagination snapshot identity is incomplete")
            started = _parse_timestamp(started_at)
            key = (started, row_id)
            if (
                row_id in seen_ids
                or (previous_key is not None and key <= previous_key)
                or started <= lower
                or started > upper
            ):
                raise ValueError("pagination snapshot is duplicate or out of order")
            seen_ids.add(row_id)
            previous_key = key
            rows.append(raw)
        start += len(page)
        if total_count == 0:
            break
    if total_count is None or len(rows) != total_count:
        raise ValueError("pagination snapshot count mismatch")
    return rows


def _default_metadata_select(
    frozen_after: str, snapshot_through: str
) -> Sequence[Mapping[str, object]]:
    from backend.supabase_client import get_supabase_client

    return _paged_metadata_select(
        get_supabase_client(),
        frozen_after=frozen_after,
        snapshot_through=snapshot_through,
    )


def _default_r2_get(key: str) -> bytes:
    from backend.r2_uploader import get_r2_bucket, get_r2_client

    body = get_r2_client().get_object(Bucket=get_r2_bucket(), Key=key)["Body"]
    return body.read()


def _default_extract_frames(payload: bytes, _source: Mapping[str, object]) -> tuple[ExtractedFrame, ...]:
    with tempfile.NamedTemporaryFile(suffix=".mp4") as handle:
        handle.write(payload)
        handle.flush()
        capture = cv2.VideoCapture(handle.name)
        try:
            total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            if total <= 0:
                return ()
            indices = sorted({max(0, round((total - 1) * ratio)) for ratio in (1 / 3, 2 / 3)})
            result: list[ExtractedFrame] = []
            for frame_index in indices:
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = capture.read()
                if not ok or frame is None:
                    continue
                encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                if not encoded:
                    continue
                height, width = frame.shape[:2]
                result.append(ExtractedFrame(frame_index, jpeg.tobytes(), width, height))
            return tuple(result)
        finally:
            capture.release()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fingerprint_parser = commands.add_parser("prepare-historical-fingerprints")
    fingerprint_parser.add_argument("--freeze", type=Path, required=True)
    fingerprint_parser.add_argument("--expected-freeze-sha256", required=True)
    fingerprint_parser.add_argument("--dataset-artifact", type=Path, required=True)
    fingerprint_parser.add_argument(
        "--expected-dataset-artifact-sha256", required=True
    )
    fingerprint_parser.add_argument("--dataset-root", type=Path, required=True)
    fingerprint_parser.add_argument("--internal-artifact", type=Path, required=True)
    fingerprint_parser.add_argument(
        "--expected-internal-artifact-sha256", required=True
    )
    fingerprint_parser.add_argument("--external-artifact", type=Path, required=True)
    fingerprint_parser.add_argument(
        "--expected-external-artifact-sha256", required=True
    )
    fingerprint_parser.add_argument("--external-snapshot", type=Path, required=True)
    fingerprint_parser.add_argument(
        "--expected-external-snapshot-sha256", required=True
    )
    fingerprint_parser.add_argument("--external-image-root", type=Path, required=True)
    fingerprint_parser.add_argument("--output", type=Path, required=True)
    prepare_parser = commands.add_parser("prepare-overlap")
    prepare_parser.add_argument(
        "--role", choices=tuple(OVERLAP_ROLE_COUNTS), required=True
    )
    prepare_parser.add_argument("--artifact", type=Path, required=True)
    prepare_parser.add_argument("--expected-artifact-sha256", required=True)
    prepare_parser.add_argument("--lineage-sot", type=Path, required=True)
    prepare_parser.add_argument("--expected-lineage-sha256", required=True)
    prepare_parser.add_argument("--output", type=Path, required=True)
    inventory_parser = commands.add_parser("inventory")
    inventory_parser.add_argument("--freeze", type=Path, required=True)
    inventory_parser.add_argument("--output", type=Path, required=True)
    inventory_parser.add_argument(
        "--historical-fingerprints", type=Path, required=True
    )
    inventory_parser.add_argument(
        "--expected-historical-fingerprints-sha256", required=True
    )
    inventory_parser.add_argument("--dataset-source-json", type=Path)
    inventory_parser.add_argument(
        "--internal-test151-source-json", type=Path
    )
    inventory_parser.add_argument(
        "--owner-external60-source-json", type=Path
    )
    inventory_parser.add_argument("--seed", default="yolo26n-v24b-future-v1")
    materialize_parser = commands.add_parser("materialize-pool")
    materialize_parser.add_argument("--output", type=Path, required=True)
    final_parser = commands.add_parser("build-final")
    final_parser.add_argument("--output", type=Path, required=True)
    final_parser.add_argument("--presence-screen", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare-historical-fingerprints":
        result = prepare_historical_fingerprints(
            freeze=args.freeze,
            expected_freeze_sha256=args.expected_freeze_sha256,
            dataset_artifact=args.dataset_artifact,
            expected_dataset_artifact_sha256=args.expected_dataset_artifact_sha256,
            dataset_root=args.dataset_root,
            internal_artifact=args.internal_artifact,
            expected_internal_artifact_sha256=args.expected_internal_artifact_sha256,
            external_artifact=args.external_artifact,
            expected_external_artifact_sha256=args.expected_external_artifact_sha256,
            external_snapshot=args.external_snapshot,
            expected_external_snapshot_sha256=args.expected_external_snapshot_sha256,
            external_image_root=args.external_image_root,
            output=args.output,
        )
    elif args.command == "prepare-overlap":
        result = prepare_overlap(
            role=args.role,
            artifact=args.artifact,
            expected_artifact_sha256=args.expected_artifact_sha256,
            lineage_sot=args.lineage_sot,
            expected_lineage_sha256=args.expected_lineage_sha256,
            output=args.output,
        )
    elif args.command == "inventory":
        result = run_inventory(
            freeze=args.freeze,
            output=args.output,
            historical_fingerprints=args.historical_fingerprints,
            expected_historical_fingerprints_sha256=(
                args.expected_historical_fingerprints_sha256
            ),
            dataset_source_json=args.dataset_source_json,
            internal_test151_source_json=args.internal_test151_source_json,
            owner_external60_source_json=args.owner_external60_source_json,
            metadata_select=_default_metadata_select,
            seed=args.seed,
        )
    elif args.command == "materialize-pool":
        result = materialize_pool(
            output=args.output,
            r2_get=_default_r2_get,
            extract_frames=_default_extract_frames,
        )
    else:
        result = build_final(output=args.output, presence_screen=args.presence_screen)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

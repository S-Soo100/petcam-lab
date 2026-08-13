"""Build the blinded YOLO26n v2.4b future holdout from read-only inputs."""

from __future__ import annotations

import argparse
import ctypes
import csv
import errno
import hashlib
import io
import json
import os
import platform
import shutil
import stat
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import cv2
from PIL import Image, UnidentifiedImageError
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix


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


def run_inventory(
    *,
    freeze: Path,
    output: Path,
    existing_source_json: Sequence[Path],
    metadata_select: Callable[[str], Sequence[Mapping[str, object]]],
    seed: str,
    reserve_limit: int = 240,
    required_count: int = 120,
    r2_get: Callable[[str], bytes] | None = None,
) -> dict[str, object]:
    del r2_get  # Inventory is metadata-only by contract.
    _require_absolute_paths(freeze, output, *existing_source_json)
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
    frozen_at = freeze_payload.get("frozen_at")
    if not isinstance(frozen_at, str):
        raise ValueError("postprocess freeze must pin frozen_at")
    _parse_timestamp(frozen_at)
    if (output / "inventory-selection.private.json").exists():
        raise FileExistsError("inventory output exists")

    excluded_sources: set[str] = set()
    excluded_images: set[str] = set()
    excluded_nights: set[str] = set()
    excluded_derivations: set[str] = set()
    for path in existing_source_json:
        payload = _read_private_json(path)
        _collect_overlap_values(
            payload,
            source_refs=excluded_sources,
            image_sha256=excluded_images,
            camera_nights=excluded_nights,
            derivation_refs=excluded_derivations,
        )

    excluded_counts: Counter[str] = Counter()
    eligible: list[dict[str, object]] = []
    seen_sources: set[str] = set()
    for raw in sorted(metadata_select(frozen_at), key=_metadata_sort_key):
        row = _validated_metadata_source(raw)
        reasons: list[str] = []
        if _parse_timestamp(str(row["recorded_at"])) <= _parse_timestamp(frozen_at):
            reasons.append("freeze_boundary")
        if row["clip_purpose"] != "production":
            reasons.append("purpose")
        if _is_firmware_development(row):
            reasons.append("firmware_development")
        if row["source_ref"] in excluded_sources:
            reasons.append("source_overlap")
        if row["image_sha256"] in excluded_images:
            reasons.append("image_overlap")
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
    frame_capacity = len(selected_sources) * SOURCE_CAP
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
        "freeze_sha256": _sha_bytes(freeze_snapshot.payload),
        "excluded_counts": dict(sorted(excluded_counts.items())),
        "excluded_image_sha256": sorted(excluded_images),
        "sources": selected_sources,
    }
    _write_private_json_new(output / "inventory-selection.private.json", ledger)
    return result


def materialize_pool(
    *,
    output: Path,
    r2_get: Callable[[str], bytes],
    extract_frames: Callable[
        [bytes, Mapping[str, object]], Sequence[ExtractedFrame]
    ],
) -> dict[str, object]:
    _require_absolute_paths(output)
    inventory_path = output / "inventory-selection.private.json"
    lock_path = output / ".locks/materialize-pool.started.private.json"
    final_dir = output / "blind-pool"
    if any(path.exists() for path in (lock_path, final_dir)):
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
    sources = inventory.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("inventory sources are missing")
    excluded_images = inventory.get("excluded_image_sha256", [])
    if not isinstance(excluded_images, list) or any(
        not isinstance(value, str) or not value for value in excluded_images
    ):
        raise ValueError("inventory excluded image SHA set is invalid")
    excluded_image_sha256 = set(excluded_images)
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
        },
    )

    staging = _private_staging(output, "blind-pool")
    image_dir = staging / "images"
    image_dir.mkdir(mode=0o700)
    source_rows: list[dict[str, object]] = []
    frame_candidates: list[tuple[FutureFrame, bytes, int]] = []
    candidate_image_sha256: set[str] = set()
    r2_get_count = 0
    try:
        for row in validated_sources:
            payload = r2_get(str(row["r2_key"]))
            r2_get_count += 1
            if not isinstance(payload, bytes) or not payload:
                raise ValueError("R2 GET must return non-empty MP4 bytes")
            source_sha = _sha_bytes(payload)
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
                if (
                    raw_image_sha in excluded_image_sha256
                    or image_sha in excluded_image_sha256
                    or image_sha in candidate_image_sha256
                ):
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
        selected = choose_blind_reserve_pool(
            [row[0] for row in candidate_by_identity.values()],
            seed=str(inventory.get("seed", "")),
            limit=limit,
        )
        if len(selected) < int(inventory.get("required_count", 120)):
            shutil.rmtree(staging, ignore_errors=True)
            return {
                "status": "V24B_FUTURE_HOLDOUT_SHORTAGE",
                "source_count": len(source_rows),
                "frame_count": 0,
                "db_write_count": 0,
                "r2_get_count": r2_get_count,
                **{
                    key: value
                    for key, value in WRITE_COUNTS.items()
                    if key != "db_write_count"
                },
            }
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
            "seed": inventory.get("seed"),
            "inventory_sha256_pre": inventory_sha,
            "inventory_sha256_post": inventory_sha,
            "source_count": len(source_rows),
            "frame_count": len(private_frames),
            "sources": source_rows,
            "frames": private_frames,
            "db_write_count": 0,
            "r2_get_count": r2_get_count,
            **{key: value for key, value in WRITE_COUNTS.items() if key != "db_write_count"},
        }
        _write_private_json_new(staging / "pool-ledger.private.json", ledger)
        _publish_directory_new(staging, final_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "status": "V24B_FUTURE_POOL_READY",
        "source_count": len(source_rows),
        "frame_count": len(private_frames),
        "db_write_count": 0,
        "r2_get_count": r2_get_count,
        **{key: value for key, value in WRITE_COUNTS.items() if key != "db_write_count"},
    }


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
        _write_csv_new(
            staging / "review-index.csv",
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
            ],
            review_rows,
        )
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
            "pool_ledger_sha256_pre": ledger_sha,
            "pool_ledger_sha256_post": ledger_sha,
            "presence_screen_sha256_pre": presence_sha,
            "presence_screen_sha256_post": presence_sha,
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
        if _read_private_snapshot(ledger_path) != ledger_snapshot:
            raise ValueError("pool ledger changed during final build")
        if _read_private_snapshot(presence_screen) != presence_snapshot:
            raise ValueError("presence screen changed during final build")
        _publish_directory_new(staging, final_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
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


def _parse_json_object(payload: bytes, *, name: str) -> dict[str, object]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{name} JSON is invalid") from error
    if not isinstance(value, dict):
        raise ValueError(f"{name} root must be an object")
    return value


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
    image_sha = raw.get("image_sha256")
    derivations = raw.get("derivation_refs", [])
    if camera_night is None and isinstance(camera_id, str) and isinstance(recorded_at, str):
        camera_night = _camera_night(camera_id, recorded_at)
    if image_sha is None:
        image_sha = _sha_bytes(str((source_ref, r2_key)).encode())
    if not isinstance(derivations, list) or any(not isinstance(value, str) or not value for value in derivations):
        raise ValueError("source derivation refs are invalid")
    if not all(
        isinstance(value, str) and value
        for value in (source_ref, camera_id, camera_night, recorded_at, clip_purpose, r2_key, image_sha)
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
        "image_sha256": image_sha,
        "derivation_refs": list(derivations),
    }


def _camera_night(camera_id: str, recorded_at: str) -> str:
    local = _parse_timestamp(recorded_at).astimezone(timezone(timedelta(hours=9))) - timedelta(hours=12)
    raw = f"{camera_id}:{local.date().isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


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
    if len(selected) * SOURCE_CAP >= required_count:
        if len({str(row["camera_id"]) for row in selected}) < MIN_CAMERAS:
            return []
        if len({str(row["camera_night"]) for row in selected}) < MIN_NIGHTS:
            return []
    return selected


def _private_staging(output: Path, name: str) -> Path:
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.chmod(0o700)
    path = Path(tempfile.mkdtemp(prefix=f".{name}-staging-", dir=output))
    path.chmod(0o700)
    return path


def _write_private_bytes_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    quarantine = Path(tempfile.mkdtemp(prefix=".quarantine-", dir=path.parent))
    quarantine.chmod(0o700)
    complete = quarantine / "complete.private"
    descriptor = os.open(complete, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.link(complete, path, follow_symlinks=False)
    finally:
        shutil.rmtree(quarantine, ignore_errors=True)


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
            resized = rgb.convert("L").resize((9, 8), Image.Resampling.BOX)
            pixels = resized.get_flattened_data()
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("extracted JPEG decode failed") from error
    value = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            value = (value << 1) | int(
                pixels[offset + column + 1] > pixels[offset + column]
            )
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


def _default_metadata_select(_frozen_after: str) -> Sequence[Mapping[str, object]]:
    from backend.supabase_client import get_supabase_client

    client = get_supabase_client()
    response = (
        client.table("motion_clips")
        .select("id,camera_id,started_at,r2_key,clip_purpose")
        .gte("started_at", _frozen_after)
        .not_.is_("r2_key", "null")
        .order("started_at")
        .execute()
    )
    return response.data or []


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
    inventory_parser = commands.add_parser("inventory")
    inventory_parser.add_argument("--freeze", type=Path, required=True)
    inventory_parser.add_argument("--output", type=Path, required=True)
    inventory_parser.add_argument("--existing-source-json", type=Path, nargs="+", default=[])
    inventory_parser.add_argument("--seed", default="yolo26n-v24b-future-v1")
    materialize_parser = commands.add_parser("materialize-pool")
    materialize_parser.add_argument("--output", type=Path, required=True)
    final_parser = commands.add_parser("build-final")
    final_parser.add_argument("--output", type=Path, required=True)
    final_parser.add_argument("--presence-screen", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "inventory":
        result = run_inventory(
            freeze=args.freeze,
            output=args.output,
            existing_source_json=args.existing_source_json,
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

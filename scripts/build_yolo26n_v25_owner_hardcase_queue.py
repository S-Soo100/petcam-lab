"""Build deterministic, private Owner hard-case candidates for YOLO v2.5."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import os
import re
import stat
import sys
import zipfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import PIL
from PIL import Image, UnidentifiedImageError

try:
    from scripts.build_yolo26n_v24b_future_holdout import (
        _assert_private_snapshot_unchanged,
        _parse_strict_json_object,
        _private_staging,
        _publish_directory_new,
        _read_private_snapshot,
    )
    from scripts.run_yolo26n_v24b_postprocess import (
        _atomic_exchange_paths,
        _atomic_rename_no_overwrite,
        _write_private_bytes_new as _secure_write_private_bytes_new,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from build_yolo26n_v24b_future_holdout import (  # type: ignore[no-redef]
        _assert_private_snapshot_unchanged,
        _parse_strict_json_object,
        _private_staging,
        _publish_directory_new,
        _read_private_snapshot,
    )
    from run_yolo26n_v24b_postprocess import (  # type: ignore[no-redef]
        _atomic_exchange_paths,
        _atomic_rename_no_overwrite,
        _write_private_bytes_new as _secure_write_private_bytes_new,
    )


FINGERPRINT_POLICY = {
    "algorithm": "dhash64",
    "version": "pillow-rgb-luma-9x8-box-right-gt-left-v1",
    "pillow_version": "12.2.0",
    "scope": "global-historical-and-owner-pool",
    "hamming_reject_max_distance": 2,
}
HISTORICAL_FINGERPRINT_POLICY = {
    **FINGERPRINT_POLICY,
    "scope": "global-historical",
}
HISTORICAL_ROLE_COUNTS = {
    "dataset": 1762,
    "internal-test151": 151,
    "owner-external60": 60,
}
OWNER_ONLY_AUDIT_SCHEMA = "yolo26n-v25-owner-only-input-audit-v1"
OWNER_ONLY_AUDIT_STATUS = "V25_OWNER_ONLY_INPUT_AUDIT_READY"
FROZEN_POSTPROCESS = {"confidence": 0.25, "nms_iou": 0.40, "duplicate": 4}
RUNTIME_FINGERPRINT_KEYS = {
    "python_binary_sha256",
    "uv_lock_sha256",
    "distributions_sha256",
    "site_packages_tree_sha256",
    "ultralytics_version",
    "ultralytics_tree_sha256",
    "torch_version",
    "torch_tree_sha256",
    "torchvision_version",
    "torchvision_tree_sha256",
    "numpy_version",
    "numpy_tree_sha256",
    "opencv_version",
    "opencv_tree_sha256",
    "pillow_version",
    "pillow_tree_sha256",
}
BBOX_RULES_BYTES = (
    "# Blind bbox rules\n\n"
    "- 보이는 각 게코의 머리·몸통 중심으로 tight bbox를 그려.\n"
    "- 가린 부분, 화면 밖 꼬리는 추정하지 마.\n"
    "- 여러 마리면 각 개체를 따로 그려.\n"
    "- 게코가 없거나 확신할 수 없으면 빈 frame 제출을 허용해.\n"
    "- 모델 예측은 제공되지 않아.\n"
).encode("utf-8")
BLIND_JPEG_INFO = {
    "jfif": 257,
    "jfif_version": (1, 1),
    "jfif_unit": 0,
    "jfif_density": (1, 1),
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class _VerifiedCheckpoint:
    payload: bytes
    sha256: str


def _read_regular_file_bytes(path: Path) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("runtime fingerprint input is not regular")
        remaining = before.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("runtime fingerprint input changed")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValueError("runtime fingerprint input changed")
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
            raise ValueError("runtime fingerprint input changed")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _hash_regular_file(path: Path) -> str:
    return hashlib.sha256(_read_regular_file_bytes(path)).hexdigest()


def _hash_regular_tree(root: Path) -> str:
    tree = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError("runtime package tree contains non-regular entry")
        relative = path.relative_to(root).as_posix().encode()
        payload = _read_regular_file_bytes(path)
        tree.update(len(relative).to_bytes(4, "big"))
        tree.update(relative)
        tree.update(len(payload).to_bytes(8, "big"))
        tree.update(payload)
    return tree.hexdigest()


def current_runtime_fingerprint() -> dict[str, str]:
    """Recalculate the same immutable runtime contract frozen by v2.4b."""
    import torch
    import torchvision
    import ultralytics

    python_binary = Path(sys._base_executable)
    uv_lock = Path(sys.prefix).parent / "uv.lock"
    rows = sorted(
        (
            distribution.metadata.get("Name", "").lower(),
            distribution.version,
        )
        for distribution in importlib.metadata.distributions()
    )
    distributions = hashlib.sha256()
    for name, version in rows:
        distributions.update(f"{name}=={version}\n".encode())

    ultralytics_root = Path(ultralytics.__file__).resolve().parent
    opencv_root = Path(cv2.__file__).resolve().parent
    torch_root = Path(torch.__file__).resolve().parent
    torchvision_root = Path(torchvision.__file__).resolve().parent
    numpy_root = Path(np.__file__).resolve().parent
    pillow_root = Path(PIL.__file__).resolve().parent
    site_packages_root = torch_root.parent

    return {
        "python_binary_sha256": _hash_regular_file(python_binary),
        "uv_lock_sha256": _hash_regular_file(uv_lock),
        "distributions_sha256": distributions.hexdigest(),
        "site_packages_tree_sha256": _hash_regular_tree(site_packages_root),
        "ultralytics_version": str(ultralytics.__version__),
        "ultralytics_tree_sha256": _hash_regular_tree(ultralytics_root),
        "torch_version": str(torch.__version__),
        "torch_tree_sha256": _hash_regular_tree(torch_root),
        "torchvision_version": str(torchvision.__version__),
        "torchvision_tree_sha256": _hash_regular_tree(torchvision_root),
        "numpy_version": str(np.__version__),
        "numpy_tree_sha256": _hash_regular_tree(numpy_root),
        "opencv_version": str(cv2.__version__),
        "opencv_tree_sha256": _hash_regular_tree(opencv_root),
        "pillow_version": str(importlib.metadata.version("Pillow")),
        "pillow_tree_sha256": _hash_regular_tree(pillow_root),
    }


def validate_runtime_preflight(
    payload: Mapping[str, object],
    *,
    expected_checkpoint_sha256: str,
    expected_code_sha256: str,
    expected_dataset_manifest_sha256: str,
    runtime_probe: Callable[[], Mapping[str, str]] = current_runtime_fingerprint,
) -> dict[str, str]:
    runtime = payload.get("runtime")
    if (
        set(payload)
        != {
            "schema",
            "status",
            "implementation_commit",
            "code_bundle_sha256",
            "checkpoint_sha256",
            "dataset_manifest_sha256",
            "runtime",
            "prohibited_inputs",
            "writes",
        }
        or payload.get("schema") != "yolo26n-v24b-runtime-preflight-v1"
        or payload.get("status") != "PREFLIGHT_OK"
        or not isinstance(payload.get("implementation_commit"), str)
        or re.fullmatch(r"[0-9a-f]{40}", str(payload["implementation_commit"])) is None
        or _SHA256.fullmatch(str(payload.get("code_bundle_sha256"))) is None
        or payload.get("code_bundle_sha256") != expected_code_sha256
        or payload.get("checkpoint_sha256") != expected_checkpoint_sha256
        or _SHA256.fullmatch(str(payload.get("dataset_manifest_sha256"))) is None
        or payload.get("dataset_manifest_sha256")
        != expected_dataset_manifest_sha256
        or payload.get("prohibited_inputs")
        != ["internal-test151", "owner-external60"]
        or payload.get("writes") != ["private-local-artifacts-only"]
        or not isinstance(runtime, Mapping)
        or set(runtime) != RUNTIME_FINGERPRINT_KEYS
    ):
        raise ValueError("runtime fingerprint contract mismatch")
    expected = {key: runtime[key] for key in sorted(runtime)}
    if (
        any(not isinstance(value, str) or not value for value in expected.values())
        or any(
            _SHA256.fullmatch(expected[key]) is None
            for key in (
                "python_binary_sha256",
                "uv_lock_sha256",
                "distributions_sha256",
                "site_packages_tree_sha256",
                "ultralytics_tree_sha256",
                "torch_tree_sha256",
                "torchvision_tree_sha256",
                "numpy_tree_sha256",
                "opencv_tree_sha256",
                "pillow_tree_sha256",
            )
        )
        or dict(runtime_probe()) != expected
    ):
        raise ValueError("runtime fingerprint contract mismatch")
    return expected


def validate_historical_fingerprints(
    payload: Mapping[str, object],
    *,
    expected_freeze_sha256: str,
    expected_unique_count: int = 1822,
    expected_role_counts: Mapping[str, int] = HISTORICAL_ROLE_COUNTS,
) -> list[dict[str, object]]:
    rows = payload.get("records")
    artifacts = payload.get("artifact_sha256")
    if (
        payload.get("schema")
        != "yolo26n-v24b-historical-fingerprint-exclusions-v1"
        or payload.get("status") != "V24B_HISTORICAL_FINGERPRINTS_FROZEN"
        or payload.get("freeze_sha256") != expected_freeze_sha256
        or payload.get("role_counts") != dict(expected_role_counts)
        or sum(expected_role_counts.values()) not in {0, 1973}
        or payload.get("unique_image_count") != expected_unique_count
        or not isinstance(rows, list)
        or len(rows) != expected_unique_count
        or payload.get("fingerprint_policy") != HISTORICAL_FINGERPRINT_POLICY
        or not isinstance(artifacts, Mapping)
        or set(artifacts)
        != {
            "dataset",
            "internal-test151",
            "owner-external60",
            "owner-external-snapshot",
        }
        or any(
            not isinstance(value, str) or _SHA256.fullmatch(value) is None
            for value in artifacts.values()
        )
        or any(
            payload.get(key) != 0
            for key in (
                "db_write_count",
                "r2_write_count",
                "service_write_count",
                "git_write_count",
            )
        )
    ):
        raise ValueError("historical fingerprint contract mismatch")
    validated: list[dict[str, object]] = []
    shas: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("historical fingerprint contract mismatch")
        row = dict(raw)
        image_sha = row.get("image_sha256")
        dhash = row.get("dhash64")
        if (
            not isinstance(image_sha, str)
            or _SHA256.fullmatch(image_sha) is None
            or image_sha in shas
            or not isinstance(dhash, str)
            or re.fullmatch(r"[0-9a-f]{16}", dhash) is None
        ):
            raise ValueError("historical fingerprint contract mismatch")
        shas.add(image_sha)
        validated.append(row)
    return validated


def _validate_owner_only_audit(
    payload: Mapping[str, object],
    *,
    expected_historical_fingerprint_sha256: str,
    expected_historical_unique_count: int = 1822,
    expected_protected_role_counts: Mapping[str, int] = {
        "validation153": 153,
        "internal-test151": 151,
        "owner-external60": 60,
    },
) -> None:
    exact_keys = {
        "schema",
        "status",
        "gate_policy",
        "gate_candidate_count",
        "gate_inputs_consumed",
        "protected_role_counts",
        "historical_unique_image_count",
        "input_sha256",
        "db_write_count",
        "r2_write_count",
        "service_write_count",
        "production_model_write_count",
        "gme_write_count",
        "labeling_web_write_count",
    }
    inputs = payload.get("input_sha256")
    protected = payload.get("protected_role_counts")
    if (
        set(payload) != exact_keys
        or payload.get("schema") != OWNER_ONLY_AUDIT_SCHEMA
        or payload.get("status") != OWNER_ONLY_AUDIT_STATUS
        or payload.get("gate_policy") != "quarantine_all"
        or type(payload.get("gate_candidate_count")) is not int
        or payload.get("gate_candidate_count") != 0
        or payload.get("gate_inputs_consumed") is not False
        or protected != dict(expected_protected_role_counts)
        or type(payload.get("historical_unique_image_count")) is not int
        or payload.get("historical_unique_image_count")
        != expected_historical_unique_count
        or not isinstance(inputs, Mapping)
        or set(inputs) != {"v24_dataset", "historical_fingerprints"}
        or any(
            not isinstance(value, str) or _SHA256.fullmatch(value) is None
            for value in inputs.values()
        )
        or inputs.get("historical_fingerprints")
        != expected_historical_fingerprint_sha256
        or any(
            payload.get(name) != 0
            for name in (
                "db_write_count",
                "r2_write_count",
                "service_write_count",
                "production_model_write_count",
                "gme_write_count",
                "labeling_web_write_count",
            )
        )
    ):
        raise ValueError("owner pipeline private input contract mismatch")


def uniform_indices(total_frames: int, *, limit: int = 8) -> tuple[int, ...]:
    if (
        not isinstance(total_frames, int)
        or isinstance(total_frames, bool)
        or total_frames < 1
        or not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit < 1
    ):
        raise ValueError("frame count and limit must be positive integers")
    count = min(limit, total_frames)
    return tuple(
        sorted(
            {
                round((index + 1) * (total_frames - 1) / (count + 1))
                for index in range(count)
            }
        )
    )


def select_scene_anchors(
    scans: Sequence[Mapping[str, object]],
    *,
    uniform_timestamps: Sequence[float],
    limit: int = 4,
) -> tuple[int, ...]:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("scene limit must be positive")
    validated: list[tuple[float, int, float]] = []
    seen_indices: set[int] = set()
    for row in scans:
        frame_index = row.get("frame_index")
        timestamp = row.get("timestamp_sec")
        score = row.get("score")
        if (
            not isinstance(frame_index, int)
            or isinstance(frame_index, bool)
            or frame_index < 0
            or frame_index in seen_indices
            or isinstance(timestamp, bool)
            or not isinstance(timestamp, (int, float))
            or timestamp < 0
            or isinstance(score, bool)
            or not isinstance(score, (int, float))
            or score < 0
        ):
            raise ValueError("scene scan contract mismatch")
        seen_indices.add(frame_index)
        validated.append((float(score), frame_index, float(timestamp)))
    selected: list[tuple[int, float]] = []
    for _score, frame_index, timestamp in sorted(
        validated, key=lambda item: (-item[0], item[1])
    ):
        if any(abs(timestamp - float(anchor)) <= 1.0 for anchor in uniform_timestamps):
            continue
        if any(abs(timestamp - chosen_time) <= 2.0 for _, chosen_time in selected):
            continue
        selected.append((frame_index, timestamp))
        if len(selected) == limit:
            break
    return tuple(sorted(frame_index for frame_index, _ in selected))


def encode_jpeg(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.convert("RGB").save(
        output,
        format="JPEG",
        quality=95,
        subsampling=0,
        optimize=False,
        progressive=False,
        exif=b"",
    )
    return output.getvalue()


def _validate_blind_jpeg_payload(payload: bytes, *, width: int, height: int) -> None:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            if (
                image.format != "JPEG"
                or image.size != (width, height)
                or image.info != BLIND_JPEG_INFO
                or len(image.getexif()) != 0
            ):
                raise ValueError("blind image must be canonical metadata-free JPEG")
    except (OSError, UnidentifiedImageError):
        raise ValueError("blind image must be canonical metadata-free JPEG") from None


def historical_dhash64(payload: bytes) -> str:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            grayscale = image.convert("RGB").convert("L").resize(
                (9, 8), Image.Resampling.BOX
            )
            pixels = list(grayscale.get_flattened_data())
    except (OSError, UnidentifiedImageError):
        raise ValueError("candidate image decode failed") from None
    bits = 0
    for row in range(8):
        for column in range(8):
            bits = (bits << 1) | int(
                pixels[row * 9 + column + 1] > pixels[row * 9 + column]
            )
    return f"{bits:016x}"


def _canonical_frame_key(row: Mapping[str, object]) -> tuple[str, int, str]:
    source_sha = row.get("source_video_sha256")
    frame_index = row.get("frame_index")
    image_sha = row.get("image_sha256")
    if (
        not isinstance(source_sha, str)
        or len(source_sha) != 64
        or not isinstance(frame_index, int)
        or isinstance(frame_index, bool)
        or frame_index < 0
        or not isinstance(image_sha, str)
        or len(image_sha) != 64
    ):
        raise ValueError("candidate frame contract mismatch")
    return source_sha, frame_index, image_sha


def deduplicate_frames(
    records: Sequence[Mapping[str, object]],
    historical_fingerprints: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    historical_shas: set[str] = set()
    historical_hashes: list[int] = []
    for row in historical_fingerprints:
        image_sha = row.get("image_sha256")
        dhash = row.get("dhash64")
        if (
            not isinstance(image_sha, str)
            or len(image_sha) != 64
            or image_sha in historical_shas
            or not isinstance(dhash, str)
            or len(dhash) != 16
        ):
            raise ValueError("historical fingerprint record mismatch")
        try:
            parsed = int(dhash, 16)
        except ValueError:
            raise ValueError("historical fingerprint record mismatch") from None
        historical_shas.add(image_sha)
        historical_hashes.append(parsed)

    counts = {
        "input": len(records),
        "historical_exact": 0,
        "historical_perceptual": 0,
        "pool_exact": 0,
        "pool_perceptual": 0,
        "accepted": 0,
    }
    accepted: list[dict[str, object]] = []
    accepted_shas: set[str] = set()
    accepted_hashes: list[int] = []
    threshold = int(FINGERPRINT_POLICY["hamming_reject_max_distance"])
    for raw in sorted(records, key=_canonical_frame_key):
        row = dict(raw)
        image_sha = row.get("image_sha256")
        dhash = row.get("dhash64")
        if not isinstance(dhash, str) or len(dhash) != 16:
            raise ValueError("candidate frame contract mismatch")
        try:
            parsed = int(dhash, 16)
        except ValueError:
            raise ValueError("candidate frame contract mismatch") from None
        if image_sha in historical_shas:
            counts["historical_exact"] += 1
        elif any((parsed ^ value).bit_count() <= threshold for value in historical_hashes):
            counts["historical_perceptual"] += 1
        elif image_sha in accepted_shas:
            counts["pool_exact"] += 1
        elif any((parsed ^ value).bit_count() <= threshold for value in accepted_hashes):
            counts["pool_perceptual"] += 1
        else:
            accepted.append(row)
            accepted_shas.add(str(image_sha))
            accepted_hashes.append(parsed)
    counts["accepted"] = len(accepted)
    return {
        "schema": "yolo26n-v25-mined-frame-dedup-v1",
        "status": "V25_MINED_FRAMES_READY",
        "fingerprint_policy": dict(FINGERPRINT_POLICY),
        "counts": counts,
        "records": accepted,
    }


def _snapshot_source_descriptor(descriptor: int, path: Path) -> dict[str, object]:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("source is not a regular file")
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    remaining = before.st_size
    while remaining:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            raise ValueError("source changed during inventory")
        digest.update(chunk)
        remaining -= len(chunk)
    if os.read(descriptor, 1):
        raise ValueError("source changed during inventory")
    after = os.fstat(descriptor)

    def identity(value: os.stat_result) -> tuple[int, ...]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    if identity(before) != identity(after):
        raise ValueError("source changed during inventory")
    os.lseek(descriptor, 0, os.SEEK_SET)
    return {
        "role": "owner-development-video",
        "source_path": str(path.resolve()),
        "source_video_sha256": digest.hexdigest(),
        "byte_size": before.st_size,
        "device": before.st_dev,
        "inode": before.st_ino,
        "mtime_ns": before.st_mtime_ns,
        "ctime_ns": before.st_ctime_ns,
    }


def _open_source_descriptor(path: Path) -> int:
    return os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
    )


def _snapshot_source(path: Path) -> dict[str, object]:
    descriptor = _open_source_descriptor(path)
    try:
        return _snapshot_source_descriptor(descriptor, path)
    finally:
        os.close(descriptor)


def inventory_owner_sources(root: Path, *, expected_count: int = 35) -> dict[str, object]:
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError("owner source root contract mismatch")
    if not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count < 0:
        raise ValueError("expected source count contract mismatch")
    records: list[dict[str, object]] = []
    symlink_excluded = 0
    other_excluded = 0
    for path in root.iterdir():
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            symlink_excluded += 1
            continue
        if path.suffix.lower() != ".mov" or not stat.S_ISREG(info.st_mode):
            other_excluded += 1
            continue
        records.append(_snapshot_source(path))
    records.sort(key=lambda row: str(row["source_video_sha256"]))
    count = len(records)
    return {
        "schema": "yolo26n-v25-owner-source-inventory-v1",
        "status": "V25_OWNER_SOURCES_AUDITED",
        "counts": {
            "expected": expected_count,
            "actual_regular_mov": count,
            "missing": max(0, expected_count - count),
            "symlink_excluded": symlink_excluded,
            "other_excluded": other_excluded,
        },
        "records": records,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def _source_snapshot_matches(
    expected: Mapping[str, object], actual: Mapping[str, object]
) -> bool:
    keys = (
        "source_path",
        "source_video_sha256",
        "byte_size",
        "device",
        "inode",
        "mtime_ns",
        "ctime_ns",
    )
    return all(expected.get(key) == actual.get(key) for key in keys)


def _source_capability_matches(
    expected: Mapping[str, object], actual: Mapping[str, object]
) -> bool:
    # Namespace-only rename activity may update ctime.  The immutable decode
    # capability is the already-open regular inode plus its exact bytes.
    keys = (
        "source_video_sha256",
        "byte_size",
        "device",
        "inode",
        "mtime_ns",
    )
    return all(expected.get(key) == actual.get(key) for key in keys)


def mine_owner_video(
    source: Mapping[str, object],
    *,
    uniform_limit: int = 8,
    scene_limit: int = 4,
) -> dict[str, object]:
    source_path = source.get("source_path")
    source_sha = source.get("source_video_sha256")
    if (
        not isinstance(source_path, str)
        or not Path(source_path).is_absolute()
        or not isinstance(source_sha, str)
        or len(source_sha) != 64
    ):
        raise ValueError("source inventory record mismatch")
    path = Path(source_path)
    descriptor = _open_source_descriptor(path)
    try:
        before = _snapshot_source_descriptor(descriptor, path)
        if not _source_snapshot_matches(source, before):
            raise ValueError("source changed before mining")
        decode_path = f"/dev/fd/{descriptor}"
        os.lseek(descriptor, 0, os.SEEK_SET)
        capture = cv2.VideoCapture(decode_path)
        scans: list[dict[str, object]] = []
        previous_gray: np.ndarray | None = None
        try:
            if not capture.isOpened():
                raise ValueError("video decode open failed")
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            reported_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if fps <= 0 or reported_count <= 0 or width <= 0 or height <= 0:
                raise ValueError("video metadata contract mismatch")
            scan_step = max(1, round(fps))
            decoded_count = 0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if (
                    not isinstance(frame, np.ndarray)
                    or frame.ndim != 3
                    or frame.shape[:2] != (height, width)
                ):
                    raise ValueError("video frame dimensions changed")
                if decoded_count % scan_step == 0:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    gray = cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA)
                    score = (
                        0.0
                        if previous_gray is None
                        else float(
                            np.mean(
                                np.abs(
                                    gray.astype(np.int16)
                                    - previous_gray.astype(np.int16)
                                )
                            )
                        )
                    )
                    scans.append(
                        {
                            "frame_index": decoded_count,
                            "timestamp_sec": decoded_count / fps,
                            "score": score,
                        }
                    )
                    previous_gray = gray
                decoded_count += 1
        finally:
            capture.release()
        if decoded_count != reported_count:
            raise ValueError("video frame count changed during decode")

        uniform = uniform_indices(decoded_count, limit=uniform_limit)
        uniform_timestamps = tuple(index / fps for index in uniform)
        scene = select_scene_anchors(
            scans,
            uniform_timestamps=uniform_timestamps,
            limit=scene_limit,
        )
        selected = tuple(sorted(set(uniform) | set(scene)))
        selected_set = set(selected)
        records: list[dict[str, object]] = []
        os.lseek(descriptor, 0, os.SEEK_SET)
        capture = cv2.VideoCapture(decode_path)
        try:
            if not capture.isOpened():
                raise ValueError("video second decode open failed")
            frame_index = 0
            while frame_index <= selected[-1]:
                ok, frame = capture.read()
                if not ok:
                    raise ValueError("video changed during second decode")
                if frame_index in selected_set:
                    if frame.shape[:2] != (height, width):
                        raise ValueError("video frame dimensions changed")
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    payload = encode_jpeg(Image.fromarray(rgb))
                    reasons = []
                    if frame_index in uniform:
                        reasons.append("uniform")
                    if frame_index in scene:
                        reasons.append("scene-aware")
                    records.append(
                        {
                            "role": "owner-development-video",
                            "source_video_sha256": source_sha,
                            "frame_index": frame_index,
                            "timestamp_sec": frame_index / fps,
                            "image_sha256": hashlib.sha256(payload).hexdigest(),
                            "dhash64": historical_dhash64(payload),
                            "width": width,
                            "height": height,
                            "jpeg_bytes": payload,
                            "selection_reasons": reasons,
                        }
                    )
                frame_index += 1
        finally:
            capture.release()
        after = _snapshot_source_descriptor(descriptor, path)
        if not _source_capability_matches(before, after):
            raise ValueError("source changed during mining")
    finally:
        os.close(descriptor)
    if len(records) != len(selected):
        raise ValueError("selected frame decode incomplete")
    return {
        "schema": "yolo26n-v25-owner-video-mining-v1",
        "status": "V25_OWNER_VIDEO_MINED",
        "source_video_sha256": source_sha,
        "decoded_frame_count": decoded_count,
        "fps": fps,
        "width": width,
        "height": height,
        "records": records,
    }


def _validated_predictions(
    frame: Mapping[str, object]
) -> tuple[str, int, float, int, int, list[dict[str, object]]]:
    source = frame.get("source_video_sha256")
    frame_index = frame.get("frame_index")
    timestamp = frame.get("timestamp_sec")
    width = frame.get("width")
    height = frame.get("height")
    predictions = frame.get("predictions")
    if (
        not isinstance(source, str)
        or len(source) != 64
        or not isinstance(frame_index, int)
        or isinstance(frame_index, bool)
        or frame_index < 0
        or isinstance(timestamp, bool)
        or not isinstance(timestamp, (int, float))
        or timestamp < 0
        or not isinstance(width, int)
        or isinstance(width, bool)
        or width <= 0
        or not isinstance(height, int)
        or isinstance(height, bool)
        or height <= 0
        or not isinstance(predictions, list)
        or len(predictions) > 50
    ):
        raise ValueError("prediction frame contract mismatch")
    checked: list[dict[str, object]] = []
    for prediction in predictions:
        if not isinstance(prediction, Mapping):
            raise ValueError("prediction box contract mismatch")
        class_id = prediction.get("class_id")
        confidence = prediction.get("confidence")
        box = prediction.get("box_xyxy")
        if (
            class_id != 0
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= float(confidence) <= 1
            or not isinstance(box, list)
            or len(box) != 4
            or any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in box
            )
        ):
            raise ValueError("prediction box contract mismatch")
        left, top, right, bottom = map(float, box)
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
    result: list[dict[str, object]] = []
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
        result.append(row)
    return result


def _default_verified_model(checkpoint: _VerifiedCheckpoint) -> object:
    try:
        from scripts.evaluate_yolo26n_v24b_future_holdout import (
            _VerifiedCheckpoint as EvaluatorCheckpoint,
            _load_ultralytics_from_verified_bytes,
        )
    except ModuleNotFoundError:  # pragma: no cover - direct script execution
        from evaluate_yolo26n_v24b_future_holdout import (  # type: ignore[no-redef]
            _VerifiedCheckpoint as EvaluatorCheckpoint,
            _load_ultralytics_from_verified_bytes,
        )
    return _load_ultralytics_from_verified_bytes(
        EvaluatorCheckpoint(checkpoint.payload, checkpoint.sha256)
    )


def run_shadow_inference(
    frames: Sequence[Mapping[str, object]],
    *,
    checkpoint: Path,
    expected_checkpoint_sha256: str,
    freeze: Path,
    expected_freeze_sha256: str,
    expected_runtime_fingerprint: Mapping[str, str],
    runtime_probe: Callable[[], Mapping[str, str]] = current_runtime_fingerprint,
    model_factory: Callable[[_VerifiedCheckpoint], object] | None = None,
) -> list[dict[str, object]]:
    expected_runtime = dict(expected_runtime_fingerprint)
    if (
        len(expected_checkpoint_sha256) != 64
        or len(expected_freeze_sha256) != 64
        or not checkpoint.is_absolute()
        or not freeze.is_absolute()
        or set(expected_runtime) != RUNTIME_FINGERPRINT_KEYS
        or dict(runtime_probe()) != expected_runtime
    ):
        raise ValueError("shadow inference pin or runtime contract mismatch")
    if any(frame.get("role") != "owner-development-video" for frame in frames):
        raise ValueError("protected role is forbidden from shadow inference")
    checkpoint_snapshot = _read_private_snapshot(checkpoint)
    freeze_snapshot = _read_private_snapshot(freeze)
    checkpoint_sha = hashlib.sha256(checkpoint_snapshot.payload).hexdigest()
    freeze_sha = hashlib.sha256(freeze_snapshot.payload).hexdigest()
    if (
        checkpoint_sha != expected_checkpoint_sha256
        or freeze_sha != expected_freeze_sha256
        or len(checkpoint_snapshot.payload) > 256 * 1024 * 1024
    ):
        raise ValueError("shadow inference raw SHA pin mismatch")
    freeze_payload = _parse_strict_json_object(
        freeze_snapshot.payload, name="postprocess freeze"
    )
    if (
        freeze_payload.get("schema") != "yolo26n-v24b-postprocess-freeze-v1"
        or freeze_payload.get("status")
        not in {
            "V24B_POSTPROCESS_FROZEN",
            "V24B_POSTPROCESS_FROZEN_DEVELOPMENT_ONLY",
        }
        or freeze_payload.get("checkpoint_sha256") != checkpoint_sha
        or freeze_payload.get("selected") != FROZEN_POSTPROCESS
        or any(
            freeze_payload.get(key) != 0
            for key in (
                "db_write_count",
                "r2_write_count",
                "service_write_count",
                "git_write_count",
            )
        )
    ):
        raise ValueError("frozen postprocess contract mismatch")

    images: list[Image.Image] = []
    prepared: list[dict[str, object]] = []
    try:
        for raw in frames:
            row = dict(raw)
            payload = row.get("jpeg_bytes")
            width = row.get("width")
            height = row.get("height")
            if (
                not isinstance(payload, bytes)
                or hashlib.sha256(payload).hexdigest() != row.get("image_sha256")
                or historical_dhash64(payload) != row.get("dhash64")
                or not isinstance(width, int)
                or isinstance(width, bool)
                or not isinstance(height, int)
                or isinstance(height, bool)
            ):
                raise ValueError("shadow inference frame contract mismatch")
            with Image.open(io.BytesIO(payload)) as decoded:
                decoded.load()
                image = decoded.convert("RGB")
            if image.size != (width, height):
                image.close()
                raise ValueError("shadow inference frame dimensions mismatch")
            images.append(image)
            prepared.append(row)

        capability = _VerifiedCheckpoint(checkpoint_snapshot.payload, checkpoint_sha)
        model = (
            _default_verified_model(capability)
            if model_factory is None
            else model_factory(capability)
        )
        raw_results = model.predict(
            source=images,
            conf=FROZEN_POSTPROCESS["confidence"],
            imgsz=960,
            iou=FROZEN_POSTPROCESS["nms_iou"],
            max_det=50,
            device="mps",
            verbose=False,
            stream=False,
            save=False,
        )
        if (
            not isinstance(raw_results, Sequence)
            or isinstance(raw_results, (str, bytes))
            or len(raw_results) != len(prepared)
        ):
            raise ValueError("shadow prediction result count mismatch")
        output: list[dict[str, object]] = []
        for index, (row, result) in enumerate(
            zip(prepared, raw_results, strict=True)
        ):
            if str(getattr(result, "path", "")) != f"image{index}.jpg":
                raise ValueError("shadow prediction order mismatch")
            if tuple(getattr(result, "orig_shape", ())) != (
                row["height"],
                row["width"],
            ):
                raise ValueError("shadow prediction dimensions mismatch")
            boxes = getattr(result, "boxes", None)
            if boxes is None or not hasattr(boxes, "xyxy") or not hasattr(boxes, "conf"):
                raise ValueError("shadow prediction boxes missing")
            xyxy = boxes.xyxy.cpu().tolist()
            confidences = boxes.conf.cpu().tolist()
            if (
                not isinstance(xyxy, list)
                or not isinstance(confidences, list)
                or len(xyxy) != len(confidences)
                or len(xyxy) > 50
            ):
                raise ValueError("shadow prediction tensors mismatch")
            predictions = [
                {
                    "class_id": 0,
                    "confidence": float(confidence),
                    "box_xyxy": [float(value) for value in box],
                }
                for box, confidence in zip(xyxy, confidences, strict=True)
            ]
            checked = _validated_predictions({**row, "predictions": predictions})[-1]
            output.append({**row, "predictions": checked})
        if dict(runtime_probe()) != expected_runtime:
            raise ValueError("runtime changed during inference")
        _assert_private_snapshot_unchanged(
            checkpoint, checkpoint_snapshot, name="checkpoint"
        )
        _assert_private_snapshot_unchanged(freeze, freeze_snapshot, name="freeze")
        return output
    finally:
        for image in images:
            image.close()


_SIGNAL_PRIORITY = {
    "duplicate_box_signal": 0,
    "suspected_miss": 1,
    "suspected_false_positive": 2,
    "partial_occlusion_signal": 3,
    "source_diversity": 4,
}


def _queue_rank(row: Mapping[str, object]) -> tuple[int, str, int, str]:
    signals = row.get("signals")
    source = row.get("source_video_sha256")
    frame_index = row.get("frame_index")
    image_sha = row.get("image_sha256")
    if (
        row.get("role") != "owner-development-video"
        or not isinstance(signals, list)
        or not signals
        or any(signal not in _SIGNAL_PRIORITY for signal in signals)
        or not isinstance(source, str)
        or len(source) != 64
        or not isinstance(frame_index, int)
        or isinstance(frame_index, bool)
        or not isinstance(image_sha, str)
        or len(image_sha) != 64
    ):
        raise ValueError("hard-case queue record mismatch")
    return min(_SIGNAL_PRIORITY[signal] for signal in signals), source, frame_index, image_sha


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
        payload = row.get("jpeg_bytes")
        if (
            not isinstance(payload, bytes)
            or hashlib.sha256(payload).hexdigest() != row.get("image_sha256")
        ):
            raise ValueError("hard-case queue image mismatch")
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


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def publish_stage_lock(
    *,
    stage: str,
    output: Path,
    final_output: Path,
    provenance: Mapping[str, str],
) -> str:
    if (
        stage
        not in {"inventory", "mining", "dedup", "bundle", "prediction", "queue"}
        or not output.is_absolute()
        or not final_output.is_absolute()
        or any(_SHA256.fullmatch(value) is None for value in provenance.values())
    ):
        raise ValueError("stage lock contract mismatch")
    payload = _json_bytes(
        {
            "schema": "yolo26n-v25-private-stage-lock-v1",
            "status": "STARTED",
            "stage": stage,
            "final_output": str(final_output),
            "provenance": dict(provenance),
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
        }
    )
    artifact = _secure_write_private_bytes_new(output, payload)
    expected = hashlib.sha256(payload).hexdigest()
    if artifact.sha256 != expected:
        raise ValueError("stage lock publication mismatch")
    return expected


def publish_stage_ledger(
    *,
    stage: str,
    status: str,
    records: Sequence[Mapping[str, object]],
    counts: Mapping[str, object],
    output: Path,
    provenance: Mapping[str, str],
) -> str:
    if (
        stage not in {"inventory", "mining", "dedup"}
        or not status.startswith("V25_")
        or not output.is_absolute()
        or any(_SHA256.fullmatch(value) is None for value in provenance.values())
        or any(row.get("role") != "owner-development-video" for row in records)
    ):
        raise ValueError("private stage ledger contract mismatch")
    safe_records = [
        {key: value for key, value in row.items() if key != "jpeg_bytes"}
        for row in records
    ]
    payload = _json_bytes(
        {
            "schema": f"yolo26n-v25-{stage}-ledger-v1",
            "status": status,
            "role": "owner-development-video",
            "record_count": len(safe_records),
            "counts": dict(counts),
            "provenance": dict(provenance),
            "records": safe_records,
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
            "production_model_write_count": 0,
        }
    )
    artifact = _secure_write_private_bytes_new(output, payload)
    expected = hashlib.sha256(payload).hexdigest()
    if artifact.sha256 != expected:
        raise ValueError("private stage ledger publication mismatch")
    return expected


def publish_prediction_ledger(
    *,
    records: Sequence[Mapping[str, object]],
    output: Path,
    input_audit_sha256: str,
    historical_fingerprint_sha256: str,
    checkpoint_sha256: str,
    freeze_sha256: str,
    code_sha256: str,
    runtime_sha256: str,
    dedup_bundle_sha256: str | None = None,
) -> str:
    provenance = {
        "input_audit_sha256": input_audit_sha256,
        "historical_fingerprint_sha256": historical_fingerprint_sha256,
        "checkpoint_sha256": checkpoint_sha256,
        "freeze_sha256": freeze_sha256,
        "code_sha256": code_sha256,
        "runtime_sha256": runtime_sha256,
    }
    if dedup_bundle_sha256 is not None:
        provenance["dedup_bundle_sha256"] = dedup_bundle_sha256
    if (
        not output.is_absolute()
        or any(_SHA256.fullmatch(value) is None for value in provenance.values())
        or any(row.get("role") != "owner-development-video" for row in records)
    ):
        raise ValueError("prediction ledger provenance contract mismatch")
    private_records = []
    for row in records:
        private = {key: value for key, value in row.items() if key != "jpeg_bytes"}
        if not isinstance(private.get("predictions"), list) or not isinstance(
            private.get("signals"), list
        ):
            raise ValueError("prediction ledger record contract mismatch")
        private_records.append(private)
    value = {
        "schema": "yolo26n-v25-shadow-prediction-ledger-v1",
        "status": "V25_SHADOW_PREDICTIONS_READY",
        "role": "owner-development-video",
        "record_count": len(private_records),
        "provenance": provenance,
        "postprocess_selected": dict(FROZEN_POSTPROCESS),
        "records": private_records,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "production_model_write_count": 0,
    }
    payload = _json_bytes(value)
    artifact = _secure_write_private_bytes_new(output, payload)
    expected = hashlib.sha256(payload).hexdigest()
    if artifact.sha256 != expected:
        raise ValueError("prediction ledger publication mismatch")
    return expected


def build_blind_queue_from_prediction_ledger(
    *,
    records: Sequence[Mapping[str, object]],
    prediction_ledger: Path,
    expected_prediction_ledger_sha256: str,
    expected_provenance: Mapping[str, str],
    output_dir: Path,
) -> dict[str, object]:
    snapshot = _read_private_snapshot(prediction_ledger)
    if (
        hashlib.sha256(snapshot.payload).hexdigest()
        != expected_prediction_ledger_sha256
    ):
        raise ValueError("prediction ledger raw SHA mismatch")
    ledger = _parse_strict_json_object(snapshot.payload, name="prediction ledger")
    expected_records = [
        {key: value for key, value in row.items() if key != "jpeg_bytes"}
        for row in records
    ]
    if (
        ledger.get("schema") != "yolo26n-v25-shadow-prediction-ledger-v1"
        or ledger.get("status") != "V25_SHADOW_PREDICTIONS_READY"
        or ledger.get("role") != "owner-development-video"
        or ledger.get("postprocess_selected") != FROZEN_POSTPROCESS
        or set(expected_provenance)
        not in ({
            "input_audit_sha256",
            "historical_fingerprint_sha256",
            "checkpoint_sha256",
            "freeze_sha256",
            "code_sha256",
            "runtime_sha256",
        }, {
            "input_audit_sha256",
            "historical_fingerprint_sha256",
            "checkpoint_sha256",
            "freeze_sha256",
            "code_sha256",
            "runtime_sha256",
            "dedup_bundle_sha256",
        })
        or any(_SHA256.fullmatch(value) is None for value in expected_provenance.values())
        or ledger.get("provenance") != dict(expected_provenance)
        or ledger.get("records") != expected_records
        or ledger.get("record_count") != len(expected_records)
        or any(
            ledger.get(key) != 0
            for key in (
                "db_write_count",
                "r2_write_count",
                "service_write_count",
                "production_model_write_count",
            )
        )
    ):
        raise ValueError("prediction ledger frame mismatch")
    # The verified descriptor snapshot above is the linearization point. Queue bytes
    # come from the already cross-pinned in-memory records, never from the pathname.
    return build_blind_queue(records, output_dir=output_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the private YOLO v2.5 Owner hard-case queue."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run-owner-pipeline")
    run.add_argument("--help-contract", action="store_true")
    run.add_argument("--source-root", type=Path)
    run.add_argument("--attempt-root", type=Path)
    run.add_argument("--input-audit", type=Path)
    run.add_argument("--historical-fingerprints", type=Path)
    run.add_argument("--checkpoint", type=Path)
    run.add_argument("--freeze", type=Path)
    run.add_argument("--runtime-preflight", type=Path)
    for name in (
        "input-audit",
        "historical-fingerprint",
        "checkpoint",
        "freeze",
        "runtime",
        "code",
    ):
        run.add_argument(f"--expected-{name}-sha256")
    prepare = subparsers.add_parser("prepare-owner-bundle")
    prepare.add_argument("--help-contract", action="store_true")
    prepare.add_argument("--source-root", type=Path)
    prepare.add_argument("--attempt-root", type=Path)
    prepare.add_argument("--input-audit", type=Path)
    prepare.add_argument("--historical-fingerprints", type=Path)
    for name in ("input-audit", "historical-fingerprint", "freeze", "code"):
        prepare.add_argument(f"--expected-{name}-sha256")
    consume = subparsers.add_parser("infer-build-queue")
    consume.add_argument("--help-contract", action="store_true")
    consume.add_argument("--bundle-dir", type=Path)
    consume.add_argument("--attempt-root", type=Path)
    consume.add_argument("--input-audit", type=Path)
    consume.add_argument("--historical-fingerprints", type=Path)
    consume.add_argument("--checkpoint", type=Path)
    consume.add_argument("--freeze", type=Path)
    consume.add_argument("--runtime-preflight", type=Path)
    consume.add_argument("--expected-runtime-build-sha256")
    consume.add_argument("--expected-inference-code-bundle-sha256")
    for name in (
        "bundle",
        "dedup-ledger",
        "input-audit",
        "historical-fingerprint",
        "checkpoint",
        "freeze",
        "runtime",
        "code",
    ):
        consume.add_argument(f"--expected-{name}-sha256")
    return parser


def _consume_launcher_capability(args: argparse.Namespace) -> None:
    descriptor_text = os.environ.pop("V25_LAUNCH_CAPABILITY_FD", "")
    try:
        descriptor = int(descriptor_text)
        payload = bytearray()
        while len(payload) <= 4096:
            chunk = os.read(descriptor, 4097 - len(payload))
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) > 4096:
            raise ValueError
        capability = json.loads(payload)
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        raise ValueError("verified launcher capability required") from None
    finally:
        if descriptor_text:
            try:
                os.close(int(descriptor_text))
            except (OSError, ValueError):
                pass
    if (
        not isinstance(capability, dict)
        or set(capability)
        != {
            "schema",
            "status",
            "runtime_build_sha256",
            "runtime_preflight_sha256",
            "inference_code_sha256",
            "inference_code_bundle_sha256",
            "nonce",
        }
        or capability.get("schema") != "yolo26n-v25-launch-capability-v1"
        or capability.get("status") != "LAUNCH_VERIFIED"
        or capability.get("runtime_build_sha256")
        != args.expected_runtime_build_sha256
        or capability.get("runtime_preflight_sha256")
        != args.expected_runtime_sha256
        or capability.get("inference_code_sha256") != args.expected_code_sha256
        or capability.get("inference_code_bundle_sha256")
        != args.expected_inference_code_bundle_sha256
        or _SHA256.fullmatch(str(capability.get("nonce"))) is None
    ):
        raise ValueError("verified launcher capability required")


def run_owner_pipeline(
    *,
    source_root: Path,
    attempt_root: Path,
    input_audit: Path,
    expected_input_audit_sha256: str,
    historical_fingerprints: Path,
    expected_historical_fingerprint_sha256: str,
    checkpoint: Path,
    expected_checkpoint_sha256: str,
    freeze: Path,
    expected_freeze_sha256: str,
    runtime_preflight: Path,
    expected_runtime_sha256: str,
    expected_code_sha256: str,
    expected_historical_unique_count: int = 1822,
    expected_historical_role_counts: Mapping[str, int] = HISTORICAL_ROLE_COUNTS,
    runtime_probe: Callable[[], Mapping[str, str]] = current_runtime_fingerprint,
    model_factory: Callable[[_VerifiedCheckpoint], object] | None = None,
) -> dict[str, object]:
    pins = {
        "input_audit_sha256": expected_input_audit_sha256,
        "historical_fingerprint_sha256": expected_historical_fingerprint_sha256,
        "checkpoint_sha256": expected_checkpoint_sha256,
        "freeze_sha256": expected_freeze_sha256,
        "runtime_sha256": expected_runtime_sha256,
        "code_sha256": expected_code_sha256,
    }
    if (
        any(_SHA256.fullmatch(value) is None for value in pins.values())
        or any(
            not path.is_absolute()
            for path in (
                source_root,
                attempt_root,
                input_audit,
                historical_fingerprints,
                checkpoint,
                freeze,
                runtime_preflight,
            )
        )
        or attempt_root.exists()
        or attempt_root.is_symlink()
        or _hash_regular_file(Path(__file__)) != expected_code_sha256
    ):
        raise ValueError("owner pipeline preflight contract mismatch")
    snapshots = {
        "input_audit": _read_private_snapshot(input_audit),
        "historical": _read_private_snapshot(historical_fingerprints),
        "runtime": _read_private_snapshot(runtime_preflight),
    }
    if (
        hashlib.sha256(snapshots["input_audit"].payload).hexdigest()
        != expected_input_audit_sha256
        or hashlib.sha256(snapshots["historical"].payload).hexdigest()
        != expected_historical_fingerprint_sha256
        or hashlib.sha256(snapshots["runtime"].payload).hexdigest()
        != expected_runtime_sha256
    ):
        raise ValueError("owner pipeline raw SHA pin mismatch")
    audit_payload = _parse_strict_json_object(
        snapshots["input_audit"].payload, name="input audit"
    )
    historical_payload = _parse_strict_json_object(
        snapshots["historical"].payload, name="historical fingerprints"
    )
    runtime_payload = _parse_strict_json_object(
        snapshots["runtime"].payload, name="runtime preflight"
    )
    _validate_owner_only_audit(
        audit_payload,
        expected_historical_fingerprint_sha256=expected_historical_fingerprint_sha256,
        expected_historical_unique_count=expected_historical_unique_count,
        expected_protected_role_counts={
            "validation153": 153,
            "internal-test151": expected_historical_role_counts["internal-test151"],
            "owner-external60": expected_historical_role_counts["owner-external60"],
        },
    )
    if (
        runtime_payload.get("schema") != "yolo26n-v24b-runtime-preflight-v1"
        or runtime_payload.get("status") != "PREFLIGHT_OK"
    ):
        raise ValueError("owner pipeline private input contract mismatch")
    runtime_fingerprint = validate_runtime_preflight(
        runtime_payload,
        expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_code_sha256=expected_code_sha256,
        expected_dataset_manifest_sha256=str(
            audit_payload["input_sha256"]["v24_dataset"]  # type: ignore[index]
        ),
        runtime_probe=runtime_probe,
    )
    historical_records = validate_historical_fingerprints(
        historical_payload,
        expected_freeze_sha256=expected_freeze_sha256,
        expected_unique_count=expected_historical_unique_count,
        expected_role_counts=expected_historical_role_counts,
    )

    attempt_root.mkdir(mode=0o700)
    os.chmod(attempt_root, 0o700)
    publish_stage_lock(
        stage="inventory",
        output=attempt_root / "inventory.started.private.json",
        final_output=attempt_root / "inventory.private.json",
        provenance=pins,
    )
    inventory = inventory_owner_sources(source_root, expected_count=35)
    inventory_sha = publish_stage_ledger(
        stage="inventory",
        status=str(inventory["status"]),
        records=inventory["records"],
        counts=inventory["counts"],
        output=attempt_root / "inventory.private.json",
        provenance=pins,
    )
    publish_stage_lock(
        stage="mining",
        output=attempt_root / "mining.started.private.json",
        final_output=attempt_root / "mining.private.json",
        provenance={**pins, "inventory_sha256": inventory_sha},
    )
    mined: list[dict[str, object]] = []
    for source in inventory["records"]:
        result = mine_owner_video(source)
        mined.extend(result["records"])
    mining_sha = publish_stage_ledger(
        stage="mining",
        status="V25_OWNER_MINING_READY",
        records=mined,
        counts={"source_count": len(inventory["records"]), "frame_count": len(mined)},
        output=attempt_root / "mining.private.json",
        provenance={**pins, "inventory_sha256": inventory_sha},
    )
    publish_stage_lock(
        stage="dedup",
        output=attempt_root / "dedup.started.private.json",
        final_output=attempt_root / "dedup.private.json",
        provenance={**pins, "mining_sha256": mining_sha},
    )
    dedup = deduplicate_frames(mined, historical_records)
    dedup_sha = publish_stage_ledger(
        stage="dedup",
        status=str(dedup["status"]),
        records=dedup["records"],
        counts=dedup["counts"],
        output=attempt_root / "dedup.private.json",
        provenance={**pins, "mining_sha256": mining_sha},
    )
    bundle_provenance = {
        "input_audit_sha256": expected_input_audit_sha256,
        "historical_fingerprint_sha256": expected_historical_fingerprint_sha256,
        "freeze_sha256": expected_freeze_sha256,
        "code_sha256": expected_code_sha256,
        "dedup_ledger_sha256": dedup_sha,
    }
    publish_stage_lock(
        stage="bundle",
        output=attempt_root / "bundle.started.private.json",
        final_output=attempt_root / "dedup-frame-bundle",
        provenance=bundle_provenance,
    )
    bundle_sha = materialize_dedup_frame_bundle(
        records=dedup["records"],
        output_dir=attempt_root / "dedup-frame-bundle",
        provenance=bundle_provenance,
    )
    verified_frames = load_dedup_frame_bundle(
        bundle_dir=attempt_root / "dedup-frame-bundle",
        expected_bundle_sha256=bundle_sha,
        expected_provenance=bundle_provenance,
    )
    prediction_pins = {**pins, "dedup_bundle_sha256": bundle_sha}
    publish_stage_lock(
        stage="prediction",
        output=attempt_root / "prediction.started.private.json",
        final_output=attempt_root / "prediction.private.json",
        provenance=prediction_pins,
    )
    predicted = (
        run_shadow_inference(
            verified_frames,
            checkpoint=checkpoint,
            expected_checkpoint_sha256=expected_checkpoint_sha256,
            freeze=freeze,
            expected_freeze_sha256=expected_freeze_sha256,
            expected_runtime_fingerprint=runtime_fingerprint,
            runtime_probe=runtime_probe,
            model_factory=model_factory,
        )
        if verified_frames
        else []
    )
    classified = classify_hardcase_signals(predicted)
    prediction_sha = publish_prediction_ledger(
        records=classified,
        output=attempt_root / "prediction.private.json",
        **pins,
        dedup_bundle_sha256=bundle_sha,
    )
    publish_stage_lock(
        stage="queue",
        output=attempt_root / "queue.started.private.json",
        final_output=attempt_root / "blind-queue",
        provenance={**prediction_pins, "prediction_sha256": prediction_sha},
    )
    queue = build_blind_queue_from_prediction_ledger(
        records=classified,
        prediction_ledger=attempt_root / "prediction.private.json",
        expected_prediction_ledger_sha256=prediction_sha,
        expected_provenance=prediction_pins,
        output_dir=attempt_root / "blind-queue",
    )
    return {
        "status": queue["status"],
        "source_count": len(inventory["records"]),
        "mined_count": len(mined),
        "dedup_count": len(dedup["records"]),
        "queue_count": queue.get("queue_count", 0),
        "prediction_ledger_sha256": prediction_sha,
        "queue_sha256": queue.get("queue_sha256"),
        "dedup_ledger_sha256": dedup_sha,
        "dedup_bundle_sha256": bundle_sha,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def _validated_cross_runtime_inputs(
    *,
    input_audit: Path,
    expected_input_audit_sha256: str,
    historical_fingerprints: Path,
    expected_historical_fingerprint_sha256: str,
    expected_freeze_sha256: str,
    expected_code_sha256: str,
    expected_historical_unique_count: int,
    expected_historical_role_counts: Mapping[str, int],
) -> list[dict[str, object]]:
    if (
        any(
            _SHA256.fullmatch(value) is None
            for value in (
                expected_input_audit_sha256,
                expected_historical_fingerprint_sha256,
                expected_freeze_sha256,
                expected_code_sha256,
            )
        )
        or _hash_regular_file(Path(__file__)) != expected_code_sha256
    ):
        raise ValueError("cross-runtime code/input pin mismatch")
    audit_snapshot = _read_private_snapshot(input_audit)
    historical_snapshot = _read_private_snapshot(historical_fingerprints)
    if (
        hashlib.sha256(audit_snapshot.payload).hexdigest()
        != expected_input_audit_sha256
        or hashlib.sha256(historical_snapshot.payload).hexdigest()
        != expected_historical_fingerprint_sha256
    ):
        raise ValueError("cross-runtime raw SHA mismatch")
    audit_payload = _parse_strict_json_object(audit_snapshot.payload, name="input audit")
    historical_payload = _parse_strict_json_object(
        historical_snapshot.payload, name="historical fingerprints"
    )
    try:
        _validate_owner_only_audit(
            audit_payload,
            expected_historical_fingerprint_sha256=expected_historical_fingerprint_sha256,
            expected_historical_unique_count=expected_historical_unique_count,
            expected_protected_role_counts={
                "validation153": 153,
                "internal-test151": expected_historical_role_counts[
                    "internal-test151"
                ],
                "owner-external60": expected_historical_role_counts[
                    "owner-external60"
                ],
            },
        )
    except ValueError:
        raise ValueError("cross-runtime audit contract mismatch") from None
    return validate_historical_fingerprints(
        historical_payload,
        expected_freeze_sha256=expected_freeze_sha256,
        expected_unique_count=expected_historical_unique_count,
        expected_role_counts=expected_historical_role_counts,
    )


def _assert_private_path_sha(path: Path, expected_sha256: str, *, name: str) -> None:
    snapshot = _read_private_snapshot(path)
    if hashlib.sha256(snapshot.payload).hexdigest() != expected_sha256:
        raise ValueError(f"{name} changed before publication boundary")


def prepare_owner_bundle(
    *,
    source_root: Path,
    attempt_root: Path,
    input_audit: Path,
    expected_input_audit_sha256: str,
    historical_fingerprints: Path,
    expected_historical_fingerprint_sha256: str,
    expected_freeze_sha256: str,
    expected_code_sha256: str,
    expected_historical_unique_count: int = 1822,
    expected_historical_role_counts: Mapping[str, int] = HISTORICAL_ROLE_COUNTS,
) -> dict[str, object]:
    if (
        any(not path.is_absolute() for path in (source_root, attempt_root, input_audit, historical_fingerprints))
        or attempt_root.exists()
        or attempt_root.is_symlink()
    ):
        raise ValueError("bundle preparation path contract mismatch")
    historical_records = _validated_cross_runtime_inputs(
        input_audit=input_audit,
        expected_input_audit_sha256=expected_input_audit_sha256,
        historical_fingerprints=historical_fingerprints,
        expected_historical_fingerprint_sha256=expected_historical_fingerprint_sha256,
        expected_freeze_sha256=expected_freeze_sha256,
        expected_code_sha256=expected_code_sha256,
        expected_historical_unique_count=expected_historical_unique_count,
        expected_historical_role_counts=expected_historical_role_counts,
    )
    pins = {
        "input_audit_sha256": expected_input_audit_sha256,
        "historical_fingerprint_sha256": expected_historical_fingerprint_sha256,
        "freeze_sha256": expected_freeze_sha256,
        "code_sha256": expected_code_sha256,
    }
    attempt_root.mkdir(mode=0o700)
    publish_stage_lock(
        stage="inventory",
        output=attempt_root / "inventory.started.private.json",
        final_output=attempt_root / "inventory.private.json",
        provenance=pins,
    )
    inventory = inventory_owner_sources(source_root, expected_count=35)
    inventory_sha = publish_stage_ledger(
        stage="inventory",
        status=str(inventory["status"]),
        records=inventory["records"],
        counts=inventory["counts"],
        output=attempt_root / "inventory.private.json",
        provenance=pins,
    )
    publish_stage_lock(
        stage="mining",
        output=attempt_root / "mining.started.private.json",
        final_output=attempt_root / "mining.private.json",
        provenance={**pins, "inventory_sha256": inventory_sha},
    )
    mined: list[dict[str, object]] = []
    for source in inventory["records"]:
        mined.extend(mine_owner_video(source)["records"])
    mining_sha = publish_stage_ledger(
        stage="mining",
        status="V25_OWNER_MINING_READY",
        records=mined,
        counts={"source_count": len(inventory["records"]), "frame_count": len(mined)},
        output=attempt_root / "mining.private.json",
        provenance={**pins, "inventory_sha256": inventory_sha},
    )
    publish_stage_lock(
        stage="dedup",
        output=attempt_root / "dedup.started.private.json",
        final_output=attempt_root / "dedup.private.json",
        provenance={**pins, "mining_sha256": mining_sha},
    )
    dedup = deduplicate_frames(mined, historical_records)
    dedup_sha = publish_stage_ledger(
        stage="dedup",
        status=str(dedup["status"]),
        records=dedup["records"],
        counts=dedup["counts"],
        output=attempt_root / "dedup.private.json",
        provenance={**pins, "mining_sha256": mining_sha},
    )
    bundle_provenance = {**pins, "dedup_ledger_sha256": dedup_sha}
    _assert_private_path_sha(
        input_audit, expected_input_audit_sha256, name="input audit"
    )
    _assert_private_path_sha(
        historical_fingerprints,
        expected_historical_fingerprint_sha256,
        name="historical fingerprints",
    )
    publish_stage_lock(
        stage="bundle",
        output=attempt_root / "bundle.started.private.json",
        final_output=attempt_root / "dedup-frame-bundle",
        provenance=bundle_provenance,
    )
    bundle_sha = materialize_dedup_frame_bundle(
        records=dedup["records"],
        output_dir=attempt_root / "dedup-frame-bundle",
        provenance=bundle_provenance,
    )
    return {
        "status": "V25_DEDUP_FRAME_BUNDLE_READY",
        "source_count": len(inventory["records"]),
        "mined_count": len(mined),
        "dedup_count": len(dedup["records"]),
        "dedup_ledger_sha256": dedup_sha,
        "bundle_sha256": bundle_sha,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def infer_build_queue_from_bundle(
    *,
    bundle_dir: Path,
    expected_bundle_sha256: str,
    expected_dedup_ledger_sha256: str,
    attempt_root: Path,
    input_audit: Path,
    expected_input_audit_sha256: str,
    historical_fingerprints: Path,
    expected_historical_fingerprint_sha256: str,
    checkpoint: Path,
    expected_checkpoint_sha256: str,
    freeze: Path,
    expected_freeze_sha256: str,
    runtime_preflight: Path,
    expected_runtime_sha256: str,
    expected_code_sha256: str,
    expected_historical_unique_count: int = 1822,
    expected_historical_role_counts: Mapping[str, int] = HISTORICAL_ROLE_COUNTS,
    runtime_probe: Callable[[], Mapping[str, str]] = current_runtime_fingerprint,
    model_factory: Callable[[_VerifiedCheckpoint], object] | None = None,
) -> dict[str, object]:
    if (
        any(
            not path.is_absolute()
            for path in (
                bundle_dir,
                attempt_root,
                input_audit,
                historical_fingerprints,
                checkpoint,
                freeze,
                runtime_preflight,
            )
        )
        or attempt_root.exists()
        or attempt_root.is_symlink()
    ):
        raise ValueError("bundle inference path contract mismatch")
    _validated_cross_runtime_inputs(
        input_audit=input_audit,
        expected_input_audit_sha256=expected_input_audit_sha256,
        historical_fingerprints=historical_fingerprints,
        expected_historical_fingerprint_sha256=expected_historical_fingerprint_sha256,
        expected_freeze_sha256=expected_freeze_sha256,
        expected_code_sha256=expected_code_sha256,
        expected_historical_unique_count=expected_historical_unique_count,
        expected_historical_role_counts=expected_historical_role_counts,
    )
    audit_snapshot = _read_private_snapshot(input_audit)
    audit_payload = _parse_strict_json_object(
        audit_snapshot.payload, name="input audit"
    )
    runtime_snapshot = _read_private_snapshot(runtime_preflight)
    runtime_payload = _parse_strict_json_object(runtime_snapshot.payload, name="runtime preflight")
    if (
        hashlib.sha256(runtime_snapshot.payload).hexdigest() != expected_runtime_sha256
        or runtime_payload.get("schema") != "yolo26n-v24b-runtime-preflight-v1"
        or runtime_payload.get("status") != "PREFLIGHT_OK"
    ):
        raise ValueError("bundle inference runtime contract mismatch")
    runtime_fingerprint = validate_runtime_preflight(
        runtime_payload,
        expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_code_sha256=expected_code_sha256,
        expected_dataset_manifest_sha256=str(
            audit_payload["input_sha256"]["v24_dataset"]  # type: ignore[index]
        ),
        runtime_probe=runtime_probe,
    )
    bundle_provenance = {
        "input_audit_sha256": expected_input_audit_sha256,
        "historical_fingerprint_sha256": expected_historical_fingerprint_sha256,
        "freeze_sha256": expected_freeze_sha256,
        "code_sha256": expected_code_sha256,
        "dedup_ledger_sha256": expected_dedup_ledger_sha256,
    }
    frames = load_dedup_frame_bundle(
        bundle_dir=bundle_dir,
        expected_bundle_sha256=expected_bundle_sha256,
        expected_provenance=bundle_provenance,
    )
    _assert_private_path_sha(
        input_audit, expected_input_audit_sha256, name="input audit"
    )
    _assert_private_path_sha(
        historical_fingerprints,
        expected_historical_fingerprint_sha256,
        name="historical fingerprints",
    )
    _assert_private_path_sha(
        runtime_preflight, expected_runtime_sha256, name="runtime preflight"
    )
    attempt_root.mkdir(mode=0o700)
    pins = {
        "input_audit_sha256": expected_input_audit_sha256,
        "historical_fingerprint_sha256": expected_historical_fingerprint_sha256,
        "checkpoint_sha256": expected_checkpoint_sha256,
        "freeze_sha256": expected_freeze_sha256,
        "code_sha256": expected_code_sha256,
        "runtime_sha256": expected_runtime_sha256,
        "dedup_bundle_sha256": expected_bundle_sha256,
    }
    publish_stage_lock(
        stage="prediction",
        output=attempt_root / "prediction.started.private.json",
        final_output=attempt_root / "prediction.private.json",
        provenance=pins,
    )
    predicted = (
        run_shadow_inference(
            frames,
            checkpoint=checkpoint,
            expected_checkpoint_sha256=expected_checkpoint_sha256,
            freeze=freeze,
            expected_freeze_sha256=expected_freeze_sha256,
            expected_runtime_fingerprint=runtime_fingerprint,
            runtime_probe=runtime_probe,
            model_factory=model_factory,
        )
        if frames
        else []
    )
    # Bind the published ledger/queue to the same tracked inference code that
    # passed the preflight. Persistent code drift during model execution must
    # fail before any prediction artifact is published.
    if _hash_regular_file(Path(__file__)) != expected_code_sha256:
        raise ValueError("inference code changed during execution")
    classified = classify_hardcase_signals(predicted)
    prediction_sha = publish_prediction_ledger(
        records=classified,
        output=attempt_root / "prediction.private.json",
        input_audit_sha256=expected_input_audit_sha256,
        historical_fingerprint_sha256=expected_historical_fingerprint_sha256,
        checkpoint_sha256=expected_checkpoint_sha256,
        freeze_sha256=expected_freeze_sha256,
        code_sha256=expected_code_sha256,
        runtime_sha256=expected_runtime_sha256,
        dedup_bundle_sha256=expected_bundle_sha256,
    )
    publish_stage_lock(
        stage="queue",
        output=attempt_root / "queue.started.private.json",
        final_output=attempt_root / "blind-queue",
        provenance={**pins, "prediction_sha256": prediction_sha},
    )
    queue = build_blind_queue_from_prediction_ledger(
        records=classified,
        prediction_ledger=attempt_root / "prediction.private.json",
        expected_prediction_ledger_sha256=prediction_sha,
        expected_provenance=pins,
        output_dir=attempt_root / "blind-queue",
    )
    return {
        "status": queue["status"],
        "queue_count": queue.get("queue_count", 0),
        "prediction_ledger_sha256": prediction_sha,
        "queue_sha256": queue.get("queue_sha256"),
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.help_contract:
        print(f"V25_{args.command.upper().replace('-', '_')}_CONTRACT_OK")
        return 0
    if args.command == "run-owner-pipeline":
        raise ValueError(
            "run-owner-pipeline is superseded; use the verified launcher"
        )
    if args.command == "prepare-owner-bundle":
        required = (
            "source_root",
            "attempt_root",
            "input_audit",
            "historical_fingerprints",
            "expected_input_audit_sha256",
            "expected_historical_fingerprint_sha256",
            "expected_freeze_sha256",
            "expected_code_sha256",
        )
        if any(getattr(args, name) is None for name in required):
            raise ValueError("owner bundle CLI contract mismatch")
        result = prepare_owner_bundle(
            **{name: getattr(args, name) for name in required}
        )
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in (
                        "status",
                        "source_count",
                        "mined_count",
                        "dedup_count",
                        "dedup_ledger_sha256",
                        "bundle_sha256",
                    )
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if args.command == "infer-build-queue":
        _consume_launcher_capability(args)
        required = (
            "bundle_dir",
            "attempt_root",
            "input_audit",
            "historical_fingerprints",
            "checkpoint",
            "freeze",
            "runtime_preflight",
            "expected_bundle_sha256",
            "expected_dedup_ledger_sha256",
            "expected_input_audit_sha256",
            "expected_historical_fingerprint_sha256",
            "expected_checkpoint_sha256",
            "expected_freeze_sha256",
            "expected_runtime_sha256",
            "expected_code_sha256",
        )
        if any(getattr(args, name) is None for name in required):
            raise ValueError("bundle inference CLI contract mismatch")
        result = infer_build_queue_from_bundle(
            **{name: getattr(args, name) for name in required}
        )
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in (
                        "status",
                        "queue_count",
                        "prediction_ledger_sha256",
                        "queue_sha256",
                    )
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    raise AssertionError("unreachable owner pipeline command")


def _write_staging_bytes_new(path: Path, payload: bytes) -> None:
    """Write inside a not-yet-public self-owned staging directory."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _zip_bytes(members: Mapping[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, members[name])
    return output.getvalue()


def directory_contract_sha256(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("queue result must be a real directory")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("queue result symlink is forbidden")
        digest.update(relative)
        if stat.S_ISDIR(metadata.st_mode):
            digest.update(b"\0D\0")
        elif stat.S_ISREG(metadata.st_mode):
            digest.update(b"\0F\0")
            digest.update(_read_private_snapshot(path).payload)
        else:
            raise ValueError("queue child must be a regular file or directory")
    return digest.hexdigest()


def directory_identity_snapshot(root: Path) -> tuple[object, ...]:
    metadata = root.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("queue result must be a real directory")
    entries: list[tuple[object, ...]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        child = path.lstat()
        if stat.S_ISLNK(child.st_mode):
            raise ValueError("queue result symlink is forbidden")
        if not (stat.S_ISDIR(child.st_mode) or stat.S_ISREG(child.st_mode)):
            raise ValueError("queue child must be a regular file or directory")
        entries.append(
            (
                path.relative_to(root).as_posix(),
                child.st_dev,
                child.st_ino,
                child.st_mode,
                child.st_size,
            )
        )
    return metadata.st_dev, metadata.st_ino, metadata.st_mode, tuple(entries)


def _quarantine_owned_directory(
    public: Path, expected_identity: tuple[object, ...]
) -> bool:
    """Move only the exact published directory inode away from its success name."""
    quarantine = _private_staging(public.parent, f"{public.name}-failed")
    sentinel = quarantine / "sentinel"
    sentinel.mkdir(mode=0o700)
    sentinel_identity = directory_identity_snapshot(sentinel)
    try:
        _atomic_exchange_paths(public, sentinel)
    except (FileNotFoundError, OSError):
        return False
    if directory_identity_snapshot(sentinel) != expected_identity:
        _atomic_exchange_paths(public, sentinel)
        if directory_identity_snapshot(sentinel) != sentinel_identity:
            raise RuntimeError("directory cleanup rollback ownership mismatch")
        return False
    captured = quarantine / "public-sentinel"
    _atomic_rename_no_overwrite(public, captured)
    if directory_identity_snapshot(captured) != sentinel_identity:
        raise RuntimeError("directory cleanup sentinel ownership mismatch")
    return True


def _publish_verified_directory_new(
    staging: Path,
    destination: Path,
    expected_identity: tuple[object, ...],
) -> None:
    """Publish through an owned reservation so a staging ABA can be rolled back."""
    reservation_root = _private_staging(
        destination.parent, f"{destination.name}-reservation"
    )
    reservation = reservation_root / "reservation"
    reservation.mkdir(mode=0o700)
    reservation_identity = directory_identity_snapshot(reservation)
    _atomic_rename_no_overwrite(reservation, destination)
    exchanged = False
    try:
        if directory_identity_snapshot(staging) != expected_identity:
            raise ValueError("blind queue staging identity changed")
        _atomic_exchange_paths(staging, destination)
        exchanged = True
        if (
            directory_identity_snapshot(destination) != expected_identity
            or directory_identity_snapshot(staging) != reservation_identity
        ):
            raise ValueError("blind queue publication identity changed")
    except BaseException:
        if exchanged:
            destination_is_expected = (
                directory_identity_snapshot(destination) == expected_identity
            )
            staging_is_reservation = (
                directory_identity_snapshot(staging) == reservation_identity
            )
            if destination_is_expected or staging_is_reservation:
                _atomic_exchange_paths(staging, destination)
        _quarantine_owned_directory(destination, reservation_identity)
        raise


def materialize_dedup_frame_bundle(
    *,
    records: Sequence[Mapping[str, object]],
    output_dir: Path,
    provenance: Mapping[str, str],
) -> str:
    if (
        not output_dir.is_absolute()
        or output_dir.exists()
        or output_dir.is_symlink()
        or not provenance
        or any(_SHA256.fullmatch(value) is None for value in provenance.values())
        or any(row.get("role") != "owner-development-video" for row in records)
    ):
        raise ValueError("dedup frame bundle contract mismatch")
    output_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(output_dir.parent, 0o700)
    staging = _private_staging(output_dir.parent, output_dir.name)
    images = staging / "images"
    images.mkdir(mode=0o700)
    manifest_rows: list[dict[str, object]] = []
    for index, raw in enumerate(records, start=1):
        row = dict(raw)
        payload = row.pop("jpeg_bytes", None)
        filename = f"F{index:06d}.jpg"
        if (
            not isinstance(payload, bytes)
            or hashlib.sha256(payload).hexdigest() != row.get("image_sha256")
            or historical_dhash64(payload) != row.get("dhash64")
        ):
            raise ValueError("dedup frame bundle record mismatch")
        _write_staging_bytes_new(images / filename, payload)
        row["filename"] = filename
        manifest_rows.append(row)
    manifest = {
        "schema": "yolo26n-v25-dedup-frame-bundle-v1",
        "status": "V25_DEDUP_FRAME_BUNDLE_READY",
        "role": "owner-development-video",
        "record_count": len(manifest_rows),
        "provenance": dict(provenance),
        "records": manifest_rows,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }
    _write_staging_bytes_new(staging / "manifest.private.json", _json_bytes(manifest))
    for path in staging.rglob("*"):
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    expected_identity = directory_identity_snapshot(staging)
    expected_sha = directory_contract_sha256(staging)
    _publish_verified_directory_new(staging, output_dir, expected_identity)
    try:
        if (
            directory_identity_snapshot(output_dir) != expected_identity
            or directory_contract_sha256(output_dir) != expected_sha
        ):
            raise ValueError("dedup frame bundle publication mismatch")
    except BaseException:
        _quarantine_owned_directory(output_dir, expected_identity)
        raise
    return expected_sha


def load_dedup_frame_bundle(
    *,
    bundle_dir: Path,
    expected_bundle_sha256: str,
    expected_provenance: Mapping[str, str],
) -> list[dict[str, object]]:
    if (
        not bundle_dir.is_absolute()
        or _SHA256.fullmatch(expected_bundle_sha256) is None
        or not expected_provenance
        or any(_SHA256.fullmatch(value) is None for value in expected_provenance.values())
    ):
        raise ValueError("dedup frame bundle pin mismatch")
    identity = directory_identity_snapshot(bundle_dir)
    if directory_contract_sha256(bundle_dir) != expected_bundle_sha256:
        raise ValueError("dedup frame bundle raw SHA mismatch")
    if {path.name for path in bundle_dir.iterdir()} != {"images", "manifest.private.json"}:
        raise ValueError("dedup frame bundle member mismatch")
    manifest_path = bundle_dir / "manifest.private.json"
    if stat.S_IMODE(bundle_dir.lstat().st_mode) != 0o700:
        raise ValueError("dedup frame bundle mode mismatch")
    for path in bundle_dir.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            expected_mode = 0o700
        elif stat.S_ISREG(metadata.st_mode):
            expected_mode = 0o600
        else:
            raise ValueError("dedup frame bundle regular-file mismatch")
        if stat.S_IMODE(metadata.st_mode) != expected_mode:
            raise ValueError("dedup frame bundle mode mismatch")
    manifest = _parse_strict_json_object(
        _read_private_snapshot(manifest_path).payload,
        name="dedup frame bundle manifest",
    )
    rows = manifest.get("records")
    if (
        manifest.get("schema") != "yolo26n-v25-dedup-frame-bundle-v1"
        or manifest.get("status") != "V25_DEDUP_FRAME_BUNDLE_READY"
        or manifest.get("role") != "owner-development-video"
        or manifest.get("provenance") != dict(expected_provenance)
        or not isinstance(rows, list)
        or manifest.get("record_count") != len(rows)
        or any(
            manifest.get(key) != 0
            for key in ("db_write_count", "r2_write_count", "service_write_count")
        )
    ):
        raise ValueError("dedup frame bundle manifest mismatch")
    loaded: list[dict[str, object]] = []
    expected_names: set[str] = set()
    for index, raw in enumerate(rows, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError("dedup frame bundle record mismatch")
        row = dict(raw)
        filename = row.pop("filename", None)
        expected_name = f"F{index:06d}.jpg"
        if filename != expected_name or row.get("role") != "owner-development-video":
            raise ValueError("dedup frame bundle record mismatch")
        payload = _read_private_snapshot(
            bundle_dir / "images" / expected_name
        ).payload
        if (
            hashlib.sha256(payload).hexdigest() != row.get("image_sha256")
            or historical_dhash64(payload) != row.get("dhash64")
        ):
            raise ValueError("dedup frame bundle image mismatch")
        try:
            with Image.open(io.BytesIO(payload)) as image:
                image.load()
                if image.size != (row.get("width"), row.get("height")):
                    raise ValueError("dedup frame bundle dimensions mismatch")
        except (OSError, UnidentifiedImageError):
            raise ValueError("dedup frame bundle image decode failed") from None
        row["jpeg_bytes"] = payload
        loaded.append(row)
        expected_names.add(expected_name)
    if {path.name for path in (bundle_dir / "images").iterdir()} != expected_names:
        raise ValueError("dedup frame bundle image set mismatch")
    if (
        directory_identity_snapshot(bundle_dir) != identity
        or directory_contract_sha256(bundle_dir) != expected_bundle_sha256
    ):
        raise ValueError("dedup frame bundle changed during load")
    return loaded


def build_blind_queue(
    records: Sequence[Mapping[str, object]], *, output_dir: Path
) -> dict[str, object]:
    if not output_dir.is_absolute():
        raise ValueError("queue output path must be absolute")
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(output_dir)
    selected = select_blind_queue(records)
    if not selected:
        return {
            "status": "V25_HARDCASE_QUEUE_SHORTAGE",
            "queue_count": 0,
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
        }
    output_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(output_dir.parent, 0o700)
    staging = _private_staging(output_dir.parent, output_dir.name)
    cvat = staging / "cvat"
    images = cvat / "images"
    cvat.mkdir(mode=0o700)
    images.mkdir(mode=0o700)
    members: dict[str, bytes] = {}
    public_records: list[dict[str, object]] = []
    private_records: list[dict[str, object]] = []
    coco_images: list[dict[str, object]] = []
    for index, row in enumerate(selected, start=1):
        sequence = f"V25{index:04d}"
        filename = f"{sequence}.jpg"
        payload = row["jpeg_bytes"]
        _validate_blind_jpeg_payload(
            payload, width=int(row["width"]), height=int(row["height"])
        )
        _write_staging_bytes_new(images / filename, payload)
        members[f"images/{filename}"] = payload
        public_records.append(
            {
                "sequence": sequence,
                "filename": filename,
                "image_sha256": row["image_sha256"],
                "width": row["width"],
                "height": row["height"],
                "annotation_policy": "human-blind-empty-frame-allowed",
            }
        )
        coco_images.append(
            {
                "id": index,
                "file_name": f"images/{filename}",
                "width": row["width"],
                "height": row["height"],
            }
        )
        private = {key: value for key, value in row.items() if key != "jpeg_bytes"}
        private["sequence"] = sequence
        private_records.append(private)
    manifest = {
        "schema": "yolo26n-v25-blind-queue-manifest-v1",
        "status": "V25_BLIND_QUEUE_READY",
        "queue_count": len(public_records),
        "records": public_records,
        "prediction_visible": False,
        "empty_frame_allowed": True,
    }
    coco = {
        "images": coco_images,
        "annotations": [],
        "categories": [{"id": 1, "name": "gecko"}],
    }
    rules = BBOX_RULES_BYTES
    members["queue-manifest.json"] = _json_bytes(manifest)
    members["annotations.coco.json"] = _json_bytes(coco)
    members["BBOX-RULES.md"] = rules
    for name in ("queue-manifest.json", "annotations.coco.json", "BBOX-RULES.md"):
        _write_staging_bytes_new(cvat / name, members[name])
    _write_staging_bytes_new(staging / "cvat-upload.zip", _zip_bytes(members))
    review_index = {
        "schema": "yolo26n-v25-blind-review-index-v1",
        "status": "V25_BLIND_QUEUE_READY",
        "queue_count": len(private_records),
        "records": private_records,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }
    _write_staging_bytes_new(
        staging / "review-index.private.json", _json_bytes(review_index)
    )
    _write_staging_bytes_new(
        staging / "build.started.private.json",
        _json_bytes(
            {
                "schema": "yolo26n-v25-blind-queue-build-lock-v1",
                "status": "STARTED",
                "queue_count": len(private_records),
                "db_write_count": 0,
                "r2_write_count": 0,
                "service_write_count": 0,
            }
        ),
    )
    for path in staging.rglob("*"):
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    expected_identity = directory_identity_snapshot(staging)
    expected_contract_sha = directory_contract_sha256(staging)
    _publish_verified_directory_new(staging, output_dir, expected_identity)
    try:
        if (
            directory_identity_snapshot(output_dir) != expected_identity
            or directory_contract_sha256(output_dir) != expected_contract_sha
        ):
            raise ValueError("blind queue publication identity changed")
    except BaseException:
        _quarantine_owned_directory(output_dir, expected_identity)
        raise
    return {
        "status": "V25_BLIND_QUEUE_READY",
        "queue_count": len(selected),
        "source_video_count": len(
            {str(row["source_video_sha256"]) for row in selected}
        ),
        "queue_sha256": expected_contract_sha,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

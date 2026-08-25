"""Evaluate the frozen YOLO26n v2.4b candidate on its future holdout once.

The evaluator deliberately has no threshold or NMS option.  Those values come
only from the development freeze, and this script consumes the accepted blind
holdout exactly once.  The started lock remains for the full attempt lifetime;
the atomic staging-directory rename is the linearization point for a completed
ledger/report pair.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Callable, Mapping, Sequence

from PIL import Image

try:
    from scripts import run_yolo26n_v24b_postprocess as validation_runner
    from scripts import select_yolo26n_v24b_postprocess as selector
    from scripts import validate_yolo26n_v24b_future_holdout_export as export_validator
except ModuleNotFoundError:  # Direct ``python scripts/...py`` execution.
    import run_yolo26n_v24b_postprocess as validation_runner  # type: ignore[no-redef]
    import select_yolo26n_v24b_postprocess as selector  # type: ignore[no-redef]
    import validate_yolo26n_v24b_future_holdout_export as export_validator  # type: ignore[no-redef]


APPROVED_CHECKPOINT_SHA256 = (
    "3c9f752b9369b30be4083f837676271640cfd1f4cbfa6027382a380efc4212c4"
)
IMAGE_COUNT = 120
POSITIVE_IMAGE_COUNT = 60
NEGATIVE_IMAGE_COUNT = 60
INFERENCE_IMAGE_SIZE = 960
INFERENCE_MAX_DETECTIONS = 50
INFERENCE_DEVICE = "mps"
LEDGER_NAME = "v24b-future-holdout-predictions.private.json"
REPORT_NAME = "v24b-future-holdout-report.private.json"
LEDGER_SCHEMA = "yolo26n-v24b-future-holdout-prediction-ledger-v1"
REPORT_SCHEMA = "yolo26n-v24b-future-holdout-evaluation-report-v1"
LOCK_NAME = "evaluate.started.private.json"
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_JPEG_BYTES = 32 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 256 * 1024 * 1024

_FREEZE_FIELDS = {
    "schema",
    "status",
    "evaluation_tier",
    "future_holdout_required",
    "match_iou",
    "threshold_grid",
    "nms_grid",
    "baseline",
    "validation_ledger_sha256",
    "validation_ground_truth_sha256",
    "metrics",
    "checkpoint_sha256",
    "dataset_manifest_sha256",
    "source_commit",
    "runner_sha256",
    "selector_sha256",
    "selected",
    "input_sha256",
    "frozen_at",
    "db_write_count",
    "r2_write_count",
    "service_write_count",
    "git_write_count",
}
_FREEZE_METRIC_FIELDS = {
    "nms_iou",
    "confidence",
    "tp",
    "fp",
    "fn",
    "duplicate",
    "precision",
    "recall",
    "positive_image_recall",
}
_GT_FIELDS = {
    "schema",
    "status",
    "image_count",
    "positive_image_count",
    "negative_image_count",
    "ambiguous_image_count",
    "box_count",
    "records",
    "db_write_count",
    "r2_write_count",
    "service_write_count",
    "git_write_count",
    "candidate_manifest_sha256",
    "review_index_sha256",
}
_GT_RECORD_FIELDS = {
    "sequence",
    "filename",
    "presence",
    "image_sha256",
    "width",
    "height",
    "boxes",
}
_GT_BOX_FIELDS = {"label_id", "points"}
_WRITE_AUDIT = {
    "db": 0,
    "r2": 0,
    "service": 0,
    "gme": 0,
    "labeling_web": 0,
    "git": 0,
}

_OwnedArtifact = validation_runner._OwnedArtifact
_artifact_is_self_owned = validation_runner._artifact_is_self_owned
_atomic_replace_owned_json = validation_runner._atomic_replace_owned_json
_cleanup_if_self_owned = validation_runner._cleanup_if_self_owned
_write_private_bytes_new = validation_runner._write_private_bytes_new
_write_private_new = validation_runner._write_private_new


@dataclass(frozen=True)
class _InputSnapshot:
    path: Path
    payload: bytes
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    sha256: str


@dataclass(frozen=True)
class _DirectorySnapshot:
    path: Path
    device: int
    inode: int
    mode: int
    mtime_ns: int
    ctime_ns: int
    entries: tuple[tuple[str, int, int, int, int, int, int], ...]


@dataclass(frozen=True)
class _HoldoutSample:
    sequence: str
    width: int
    height: int
    image_snapshot: _InputSnapshot
    image: Image.Image
    gt_boxes: tuple[tuple[float, float, float, float], ...]


@dataclass(frozen=True)
class _VerifiedCheckpoint:
    """Immutable capability handed to the deserializer after SHA verification."""

    payload: bytes
    sha256: str


def _is_sha(value: object, *, length: int = 64) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_sha(value: object, label: str, *, length: int = 64) -> str:
    if not _is_sha(value, length=length):
        raise ValueError(f"{label} must be an independent lowercase SHA-256 pin")
    return str(value)


def _finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def _exact_positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _validate_runtime_inference_contract() -> None:
    """Reject an injected future-inference contract before any model call."""
    if (
        type(INFERENCE_IMAGE_SIZE) is not int
        or INFERENCE_IMAGE_SIZE != 960
        or type(INFERENCE_MAX_DETECTIONS) is not int
        or INFERENCE_MAX_DETECTIONS != 50
        or INFERENCE_DEVICE != "mps"
        or validation_runner.INFERENCE_CONTRACT
        != {"confidence": 0.001, "imgsz": 960, "max_det": 50, "device": "mps"}
    ):
        raise ValueError("frozen inference contract was changed or injected")


def _read_regular_snapshot(
    path: Path, *, label: str, maximum_bytes: int, require_0600: bool = True
) -> _InputSnapshot:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"{label} must be a regular file")
        if require_0600 and before.st_mode & 0o777 != 0o600:
            raise ValueError(f"{label} mode must be exactly 0600")
        if before.st_size <= 0 or before.st_size > maximum_bytes:
            raise ValueError(f"{label} size is invalid or exceeds the bound")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError(f"{label} changed during bounded read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValueError(f"{label} changed during bounded read")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if identity_before != identity_after:
        raise ValueError(f"{label} identity changed during bounded read")
    payload = b"".join(chunks)
    return _InputSnapshot(
        path=path,
        payload=payload,
        device=before.st_dev,
        inode=before.st_ino,
        size=before.st_size,
        mtime_ns=before.st_mtime_ns,
        ctime_ns=before.st_ctime_ns,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _require_snapshot_unchanged(
    snapshot: _InputSnapshot,
    *,
    label: str,
    maximum_bytes: int,
    require_0600: bool = True,
) -> None:
    current = _read_regular_snapshot(
        snapshot.path,
        label=label,
        maximum_bytes=maximum_bytes,
        require_0600=require_0600,
    )
    if current != snapshot:
        raise ValueError(f"{label} identity, ctime, mtime, size, or SHA changed (ABA)")


def _parse_object(payload: bytes, label: str) -> Mapping[str, object]:
    def reject_duplicate(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} contains a duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload,
            object_pairs_hook=reject_duplicate,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ValueError(f"{label} contains nonfinite JSON {constant}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} JSON is malformed") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} root must be an object")
    return value


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_freeze(
    freeze: Mapping[str, object], *, checkpoint_sha256: str
) -> dict[str, object]:
    if set(freeze) != _FREEZE_FIELDS:
        raise ValueError("freeze exact schema fields mismatch")
    if (
        freeze.get("schema") != "yolo26n-v24b-postprocess-freeze-v1"
        or freeze.get("status") != "V24B_POSTPROCESS_FROZEN_DEVELOPMENT_ONLY"
        or freeze.get("evaluation_tier") != "development"
        or freeze.get("future_holdout_required") is not True
        or freeze.get("match_iou") != selector.MATCH_IOU
        or freeze.get("threshold_grid") != list(selector.THRESHOLD_GRID)
        or freeze.get("nms_grid") != list(selector.NMS_GRID)
    ):
        raise ValueError("freeze exact frozen contract mismatch")
    if any(
        type(value) not in (int, float)
        for value in (*freeze["threshold_grid"], *freeze["nms_grid"])  # type: ignore[misc]
    ):
        raise ValueError("freeze grids reject boolean values")
    for field in ("db_write_count", "r2_write_count", "service_write_count", "git_write_count"):
        if type(freeze.get(field)) is not int or freeze[field] != 0:
            raise ValueError("freeze write audit mismatch")
    if freeze.get("checkpoint_sha256") != checkpoint_sha256:
        raise ValueError("freeze checkpoint pin mismatch")
    dataset_sha = _require_sha(freeze.get("dataset_manifest_sha256"), "freeze dataset")
    source_commit = _require_sha(freeze.get("source_commit"), "freeze commit", length=40)
    runner_sha = _require_sha(freeze.get("runner_sha256"), "freeze runner code")
    selector_sha = _require_sha(freeze.get("selector_sha256"), "freeze selector code")
    if runner_sha != _sha_file(Path(validation_runner.__file__)):
        raise ValueError("freeze runner code SHA does not match loaded code")
    if selector_sha != _sha_file(Path(selector.__file__)):
        raise ValueError("freeze selector code SHA does not match loaded code")
    input_sha = freeze.get("input_sha256")
    if not isinstance(input_sha, Mapping) or set(input_sha) != {
        "checkpoint", "dataset_manifest", "runner", "selector", "frames"
    }:
        raise ValueError("freeze input SHA contract mismatch")
    if (
        input_sha.get("checkpoint") != checkpoint_sha256
        or input_sha.get("dataset_manifest") != dataset_sha
        or input_sha.get("runner") != runner_sha
        or input_sha.get("selector") != selector_sha
    ):
        raise ValueError("freeze checkpoint, dataset, or code input cross-pin mismatch")
    frames = input_sha.get("frames")
    if not isinstance(frames, list) or len(frames) != validation_runner.VALIDATION_IMAGE_COUNT:
        raise ValueError("freeze validation dataset frame pin mismatch")
    sequences: set[str] = set()
    images: set[str] = set()
    for frame in frames:
        if (
            not isinstance(frame, Mapping)
            or set(frame) != {"sequence", "image_sha256", "label_sha256"}
            or not isinstance(frame.get("sequence"), str)
            or not frame["sequence"]
            or frame["sequence"] in sequences
            or not _is_sha(frame.get("image_sha256"))
            or frame["image_sha256"] in images
            or not _is_sha(frame.get("label_sha256"))
        ):
            raise ValueError("freeze validation dataset pins are malformed or duplicate")
        sequences.add(str(frame["sequence"]))
        images.add(str(frame["image_sha256"]))
    ledgers = freeze.get("validation_ledger_sha256")
    if not isinstance(ledgers, Mapping) or set(ledgers) != {
        str(value) for value in selector.NMS_GRID
    } or not all(_is_sha(value) for value in ledgers.values()):
        raise ValueError("freeze validation ledger SHA map mismatch")
    _require_sha(freeze.get("validation_ground_truth_sha256"), "freeze validation GT")
    baseline = freeze.get("baseline")
    if (
        not isinstance(baseline, Mapping)
        or set(baseline) != {"confidence", "nms_iou", "duplicate"}
        or baseline.get("confidence") != selector.BASELINE_CONFIDENCE
        or baseline.get("nms_iou") != selector.BASELINE_NMS_IOU
        or type(baseline.get("duplicate")) is not int
        or baseline["duplicate"] < 0
    ):
        raise ValueError("freeze baseline mismatch")
    raw_metrics = freeze.get("metrics")
    expected_pairs = [
        (nms_iou, confidence)
        for nms_iou in selector.NMS_GRID
        for confidence in selector.THRESHOLD_GRID
    ]
    if not isinstance(raw_metrics, list) or len(raw_metrics) != len(expected_pairs):
        raise ValueError("freeze metric grid mismatch")
    metrics: list[selector.PostprocessMetric] = []
    for raw, pair in zip(raw_metrics, expected_pairs, strict=True):
        if not isinstance(raw, Mapping) or set(raw) != _FREEZE_METRIC_FIELDS:
            raise ValueError("freeze metric schema mismatch")
        if (raw.get("nms_iou"), raw.get("confidence")) != pair:
            raise ValueError("freeze metric order mismatch")
        try:
            metric = selector.PostprocessMetric(**raw)
            selector._validate_metric(metric)
        except (TypeError, ValueError) as exc:
            raise ValueError("freeze metric value mismatch") from exc
        metrics.append(metric)
    selected = freeze.get("selected")
    if (
        not isinstance(selected, Mapping)
        or set(selected) != {"confidence", "nms_iou", "duplicate"}
        or type(selected.get("confidence")) not in (int, float)
        or type(selected.get("nms_iou")) not in (int, float)
        or type(selected.get("duplicate")) is not int
    ):
        raise ValueError("freeze selected contract mismatch")
    recomputed = selector.select_postprocess_candidate(
        metrics, baseline_duplicate=int(baseline["duplicate"])
    )
    if recomputed is None or selected != {
        "confidence": recomputed.confidence,
        "nms_iou": recomputed.nms_iou,
        "duplicate": recomputed.duplicate,
    }:
        raise ValueError("freeze selected confidence or NMS mismatch")
    frozen_at = freeze.get("frozen_at")
    if not isinstance(frozen_at, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", frozen_at
    ) is None:
        raise ValueError("freeze frozen_at is malformed")
    parsed = datetime.fromisoformat(frozen_at.replace("Z", "+00:00"))
    if parsed > datetime.now(timezone.utc):
        raise ValueError("freeze frozen_at cannot be in the future")
    return {
        "confidence": float(selected["confidence"]),
        "nms_iou": float(selected["nms_iou"]),
        "dataset_manifest_sha256": dataset_sha,
        "source_commit": source_commit,
        "runner_sha256": runner_sha,
        "selector_sha256": selector_sha,
        "frozen_at": frozen_at,
    }


def _validate_gt(
    gt: Mapping[str, object],
    *,
    manifest_records: Sequence[Mapping[str, object]],
    manifest_sha256: str,
    review_index_sha256: str,
) -> tuple[tuple[tuple[float, float, float, float], ...], ...]:
    if set(gt) != _GT_FIELDS:
        raise ValueError("GT exact schema fields mismatch")
    if (
        gt.get("schema") != "yolo26n-v24b-future-holdout-gt-v1"
        or gt.get("status") != export_validator.ACCEPTED_STATUS
        or gt.get("candidate_manifest_sha256") != manifest_sha256
        or gt.get("review_index_sha256") != review_index_sha256
    ):
        raise ValueError("GT accepted manifest/review-index cross-pin mismatch")
    expected_counts = {
        "image_count": IMAGE_COUNT,
        "positive_image_count": POSITIVE_IMAGE_COUNT,
        "negative_image_count": NEGATIVE_IMAGE_COUNT,
        "ambiguous_image_count": 0,
    }
    for field, expected in expected_counts.items():
        if type(gt.get(field)) is not int or gt[field] != expected:
            raise ValueError("GT count contract mismatch")
    for field in ("db_write_count", "r2_write_count", "service_write_count", "git_write_count"):
        if type(gt.get(field)) is not int or gt[field] != 0:
            raise ValueError("GT write audit mismatch")
    records = gt.get("records")
    if not isinstance(records, list) or len(records) != IMAGE_COUNT:
        raise ValueError("GT records count mismatch")
    result: list[tuple[tuple[float, float, float, float], ...]] = []
    box_count = 0
    for raw, manifest in zip(records, manifest_records, strict=True):
        if not isinstance(raw, Mapping) or set(raw) != _GT_RECORD_FIELDS:
            raise ValueError("GT record schema mismatch")
        for field in ("sequence", "filename", "presence", "image_sha256", "width", "height"):
            if raw.get(field) != manifest.get(field):
                raise ValueError("GT record does not match holdout manifest")
        width = _exact_positive_int(raw.get("width"), "GT dimension")
        height = _exact_positive_int(raw.get("height"), "GT dimension")
        raw_boxes = raw.get("boxes")
        if not isinstance(raw_boxes, list):
            raise ValueError("GT boxes must be a list")
        boxes: list[tuple[float, float, float, float]] = []
        for raw_box in raw_boxes:
            if (
                not isinstance(raw_box, Mapping)
                or set(raw_box) != _GT_BOX_FIELDS
                or type(raw_box.get("label_id")) is not int
                or raw_box.get("label_id") != 1
            ):
                raise ValueError("GT box schema or label mismatch")
            points = raw_box.get("points")
            if (
                not isinstance(points, list)
                or len(points) != 4
                or not all(_finite_number(value) for value in points)
            ):
                raise ValueError("GT box is malformed or nonfinite")
            x1, y1, x2, y2 = map(float, points)
            if not (0.0 <= x1 < x2 <= width and 0.0 <= y1 < y2 <= height):
                raise ValueError("GT box is out of bounds or has nonpositive area")
            boxes.append((x1, y1, x2, y2))
        presence = raw.get("presence")
        if (presence == "positive" and not boxes) or (presence == "negative" and boxes):
            raise ValueError("GT positive/negative box contract mismatch")
        box_count += len(boxes)
        result.append(tuple(boxes))
    if type(gt.get("box_count")) is not int or gt["box_count"] != box_count:
        raise ValueError("GT box count mismatch")
    return tuple(result)


def _validate_holdout_manifest(
    manifest: Mapping[str, object], *, freeze_sha256: str
) -> tuple[dict[str, object], ...]:
    """Require Task 4's freeze lineage before accepting any holdout record."""
    lineage_field = "postprocess_freeze_sha256"
    if manifest.get(lineage_field) != freeze_sha256:
        raise ValueError("holdout manifest freeze cross-pin mismatch")
    validator_fields = set(export_validator.MANIFEST_FIELDS)
    if lineage_field in validator_fields:
        return export_validator._validate_manifest(manifest)
    # This exact-union branch keeps Task 6 fail-closed while Task 4's producer
    # and validator change lands in the shared worktree.
    if set(manifest) != validator_fields | {lineage_field}:
        raise ValueError("holdout manifest exact schema fields mismatch")
    upstream_view = dict(manifest)
    del upstream_view[lineage_field]
    return export_validator._validate_manifest(upstream_view)


def _directory_snapshot(path: Path) -> _DirectorySnapshot:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("holdout images path must be a real directory")
    if metadata.st_mode & 0o777 != 0o700:
        raise ValueError("holdout images directory mode must be exactly 0700")
    entries: list[tuple[str, int, int, int, int, int, int]] = []
    for name in sorted(os.listdir(path)):
        item = (path / name).lstat()
        entries.append(
            (
                name,
                item.st_dev,
                item.st_ino,
                item.st_mode,
                item.st_size,
                item.st_mtime_ns,
                item.st_ctime_ns,
            )
        )
    confirmed = path.lstat()
    return _DirectorySnapshot(
        path=path,
        device=confirmed.st_dev,
        inode=confirmed.st_ino,
        mode=confirmed.st_mode,
        mtime_ns=confirmed.st_mtime_ns,
        ctime_ns=confirmed.st_ctime_ns,
        entries=tuple(entries),
    )


def _same_directory_snapshot(
    expected: _DirectorySnapshot, path: Path, *, after_rename: bool = False
) -> bool:
    current = _directory_snapshot(path)
    stable = (
        current.device,
        current.inode,
        current.mode,
        current.entries,
    ) == (
        expected.device,
        expected.inode,
        expected.mode,
        expected.entries,
    )
    # A legitimate rename can change the directory's own ctime.  Before the
    # rename, mtime/ctime are also identity guards; after it, the inode and its
    # exact child set are the stable publication capability.
    return stable and (
        after_rename
        or (
            current.mtime_ns == expected.mtime_ns
            and current.ctime_ns == expected.ctime_ns
        )
    )


def _relocate_owned(artifact: _OwnedArtifact, path: Path) -> _OwnedArtifact:
    return _OwnedArtifact(
        path=path,
        device=artifact.device,
        inode=artifact.inode,
        size=artifact.size,
        sha256=artifact.sha256,
    )


def _require_publication_boundary(
    *,
    directory: _DirectorySnapshot,
    output: Path,
    coordinator: _OwnedArtifact,
    public_artifacts: Sequence[tuple[_OwnedArtifact, str]],
) -> None:
    """Observe the one success boundary after the durable parent fsync.

    This is a single linearization observation, not a retry loop or a claim
    that external actors cannot mutate the private paths after this function
    returns.
    """
    if not _same_directory_snapshot(directory, output, after_rename=True):
        raise ValueError("publication directory identity changed at success boundary")
    _require_owned(
        ((coordinator, "one-shot coordinator"), *public_artifacts)
    )


def _prepare_private_output_directory(path: Path, *, label: str) -> None:
    """Create or open one output directory without following a final symlink."""
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"{label} must be a real output directory, not a symlink") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"{label} must be an output directory")
        os.fchmod(descriptor, 0o700)
    finally:
        os.close(descriptor)


def _load_samples(
    *,
    images_dir: Path,
    manifest_records: Sequence[Mapping[str, object]],
    gt_boxes: Sequence[tuple[tuple[float, float, float, float], ...]],
) -> tuple[_DirectorySnapshot, tuple[_HoldoutSample, ...], str]:
    directory = _directory_snapshot(images_dir)
    expected_names = tuple(str(record["filename"]) for record in manifest_records)
    if tuple(entry[0] for entry in directory.entries) != tuple(sorted(expected_names)):
        raise ValueError("holdout image set does not exactly match H sequence")
    samples: list[_HoldoutSample] = []
    contract: list[dict[str, object]] = []
    try:
        for record, boxes in zip(manifest_records, gt_boxes, strict=True):
            sequence = str(record["sequence"])
            snapshot = _read_regular_snapshot(
                images_dir / str(record["filename"]),
                label=f"holdout JPEG {sequence}",
                maximum_bytes=MAX_JPEG_BYTES,
            )
            if snapshot.sha256 != record["image_sha256"]:
                raise ValueError("holdout JPEG SHA does not match manifest")
            try:
                with Image.open(BytesIO(snapshot.payload)) as decoded:
                    if decoded.format != "JPEG":
                        raise ValueError("holdout image must decode as JPEG")
                    decoded.load()
                    image = decoded.convert("RGB")
            except (OSError, ValueError) as exc:
                raise ValueError("holdout JPEG decode failed") from exc
            width = _exact_positive_int(record.get("width"), "holdout dimension")
            height = _exact_positive_int(record.get("height"), "holdout dimension")
            if image.size != (width, height):
                image.close()
                raise ValueError("holdout JPEG dimensions do not match manifest")
            samples.append(_HoldoutSample(sequence, width, height, snapshot, image, boxes))
            contract.append(
                {
                    "sequence": sequence,
                    "image_sha256": snapshot.sha256,
                    "width": width,
                    "height": height,
                }
            )
    except BaseException:
        for sample in samples:
            sample.image.close()
        raise
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    return directory, tuple(samples), hashlib.sha256(encoded).hexdigest()


def _load_ultralytics_from_verified_bytes(checkpoint: _VerifiedCheckpoint) -> object:
    """Build YOLO from the verified bytes without reopening a mutable pathname."""
    import torch
    from ultralytics import YOLO
    from ultralytics.nn.tasks import guess_model_task
    from ultralytics.utils import DEFAULT_CFG_DICT, callbacks

    # PyTorch checkpoints are pickle-bearing.  Deserialization is permitted
    # only because these immutable bytes already match the approved SHA pin.
    loaded = torch.load(
        BytesIO(checkpoint.payload), map_location="cpu", weights_only=False
    )
    if not isinstance(loaded, dict):
        raise TypeError("verified Ultralytics checkpoint must contain a dictionary")
    candidate = loaded.get("ema") or loaded.get("model")
    if not isinstance(candidate, torch.nn.Module):
        raise TypeError("verified Ultralytics checkpoint contains no model module")
    arguments = {**DEFAULT_CFG_DICT, **loaded.get("train_args", {})}
    module = candidate.float()
    module.args = arguments
    module.pt_path = f"sha256:{checkpoint.sha256}"
    module.task = getattr(module, "task", guess_model_task(module))
    if not hasattr(module, "stride"):
        module.stride = torch.tensor([32.0])
    module = module.to("cpu").float().eval()
    for layer in module.modules():
        if hasattr(layer, "inplace"):
            layer.inplace = True
        elif isinstance(layer, torch.nn.Upsample) and not hasattr(
            layer, "recompute_scale_factor"
        ):
            layer.recompute_scale_factor = None

    wrapper = YOLO.__new__(YOLO)
    torch.nn.Module.__init__(wrapper)
    wrapper.callbacks = callbacks.get_default_callbacks()
    wrapper.predictor = None
    wrapper.model = module
    wrapper.trainer = None
    wrapper.ckpt = loaded
    wrapper.cfg = None
    wrapper.ckpt_path = f"sha256:{checkpoint.sha256}"
    wrapper.overrides = wrapper._reset_ckpt_args(module.args)
    wrapper.overrides.update({"model": "verified-private-checkpoint.pt", "task": module.task})
    wrapper.metrics = None
    wrapper.session = None
    wrapper.task = module.task
    wrapper.model_name = "verified-private-checkpoint.pt"
    del wrapper.training
    return wrapper


def _make_model(
    checkpoint: _VerifiedCheckpoint,
    factory: Callable[[_VerifiedCheckpoint], object] | None,
) -> object:
    return (
        _load_ultralytics_from_verified_bytes(checkpoint)
        if factory is None
        else factory(checkpoint)
    )


def _prediction_records(
    model: object,
    samples: Sequence[_HoldoutSample],
    *,
    confidence: float,
    nms_iou: float,
) -> tuple[dict[str, object], ...]:
    raw_results = model.predict(
        source=[sample.image for sample in samples],
        conf=confidence,
        imgsz=INFERENCE_IMAGE_SIZE,
        iou=nms_iou,
        max_det=INFERENCE_MAX_DETECTIONS,
        device=INFERENCE_DEVICE,
        verbose=False,
        stream=False,
        save=False,
    )
    if not isinstance(raw_results, Sequence) or isinstance(raw_results, (str, bytes)):
        raise ValueError("prediction results must be an ordered sequence")
    if len(raw_results) != len(samples):
        raise ValueError("prediction result count does not match holdout")
    records: list[dict[str, object]] = []
    for index, (sample, result) in enumerate(zip(samples, raw_results, strict=True)):
        if str(getattr(result, "path", "")) != f"image{index}.jpg":
            raise ValueError("prediction result order does not match input order")
        shape = getattr(result, "orig_shape", None)
        if (
            not isinstance(shape, Sequence)
            or isinstance(shape, (str, bytes))
            or len(shape) != 2
            or any(type(value) is not int for value in shape)
            or tuple(shape) != (sample.height, sample.width)
        ):
            raise ValueError("prediction result dimensions are malformed")
        boxes = getattr(result, "boxes", None)
        if boxes is None or not hasattr(boxes, "xyxy") or not hasattr(boxes, "conf"):
            raise ValueError("prediction boxes are missing or malformed")
        raw_xyxy = boxes.xyxy.cpu().tolist()
        raw_confidences = boxes.conf.cpu().tolist()
        if not isinstance(raw_xyxy, list) or not isinstance(raw_confidences, list):
            raise ValueError("prediction tensors are malformed")
        if len(raw_xyxy) != len(raw_confidences):
            raise ValueError("prediction box/confidence counts mismatch")
        if len(raw_xyxy) > INFERENCE_MAX_DETECTIONS:
            raise ValueError("prediction count exceeds frozen max_det")
        predictions: list[dict[str, object]] = []
        for raw_confidence, raw_box in zip(raw_confidences, raw_xyxy, strict=True):
            if not _finite_number(raw_confidence) or not 0.0 <= float(raw_confidence) <= 1.0:
                raise ValueError("prediction confidence is bool, nonfinite, or out of range")
            if (
                not isinstance(raw_box, Sequence)
                or isinstance(raw_box, (str, bytes))
                or len(raw_box) != 4
                or not all(_finite_number(value) for value in raw_box)
            ):
                raise ValueError("prediction box is malformed or nonfinite")
            x1, y1, x2, y2 = map(float, raw_box)
            if not (0.0 <= x1 < x2 <= sample.width and 0.0 <= y1 < y2 <= sample.height):
                raise ValueError("prediction box is out of bounds or has nonpositive area")
            predictions.append(
                {"confidence": float(raw_confidence), "xyxy": [x1, y1, x2, y2]}
            )
        records.append({"sequence": sample.sequence, "predictions": predictions})
    return tuple(records)


def _score_with_task2_semantics(
    *,
    samples: Sequence[_HoldoutSample],
    prediction_records: Sequence[Mapping[str, object]],
    confidence: float,
    nms_iou: float,
    checkpoint_sha256: str,
    freeze_contract: Mapping[str, object],
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for sample, prediction_record in zip(samples, prediction_records, strict=True):
        records.append(
            {
                "sequence": sample.sequence,
                "image_sha256": sample.image_snapshot.sha256,
                "width": sample.width,
                "height": sample.height,
                "gt_boxes": [list(box) for box in sample.gt_boxes],
                "predictions": list(prediction_record["predictions"]),
            }
        )
    task2_ledger = {
        "schema": "yolo26n-v24b-postprocess-prediction-ledger-v1",
        "status": "V24B_POSTPROCESS_PREDICTIONS_READY",
        "dataset_schema": "yolo26n-owner-dataset-v24",
        "evaluation_tier": "development",
        "split": "val",
        "candidate": "warm-start",
        "source_commit": freeze_contract["source_commit"],
        "runner_sha256": freeze_contract["runner_sha256"],
        "dataset_manifest_sha256": freeze_contract["dataset_manifest_sha256"],
        "checkpoint_sha256": checkpoint_sha256,
        # Task 2 validates raw-ledger inference at .001, then applies the
        # selected threshold in score_prediction_ledger.  Future predictions
        # are already requested at that threshold but use the same scorer.
        "inference": {
            "confidence": 0.001,
            "imgsz": INFERENCE_IMAGE_SIZE,
            "nms_iou": nms_iou,
            "max_det": INFERENCE_MAX_DETECTIONS,
            "device": INFERENCE_DEVICE,
        },
        "image_count": len(records),
        "gt_box_count": sum(len(record["gt_boxes"]) for record in records),
        "prediction_count": sum(len(record["predictions"]) for record in records),
        "records": records,
    }
    metric = selector.score_prediction_ledger(task2_ledger, confidence=confidence)
    false_positive_negative_images = sum(
        not sample.gt_boxes
        and any(
            float(prediction["confidence"]) >= confidence
            for prediction in record["predictions"]  # type: ignore[union-attr]
        )
        for sample, record in zip(samples, prediction_records, strict=True)
    )
    return {
        "tp": metric.tp,
        "fp": metric.fp,
        "fn": metric.fn,
        "duplicate": metric.duplicate,
        "precision": metric.precision,
        "recall": metric.recall,
        "positive_image_recall": metric.positive_image_recall,
        "false_positive_negative_images": false_positive_negative_images,
    }


def classify_shadow_status(
    *,
    precision: float,
    recall: float,
    positive_image_recall: float,
    false_positive_negative_images: int,
    duplicate: int,
    integrity_violations: int,
    overlap_violations: int,
    one_shot_violations: int,
    write_violations: int,
) -> dict[str, object]:
    """Apply the pre-registered future-holdout gates without any retuning."""
    probabilities = (precision, recall, positive_image_recall)
    counts = (
        false_positive_negative_images,
        duplicate,
        integrity_violations,
        overlap_violations,
        one_shot_violations,
        write_violations,
    )
    if any(not _finite_number(value) or not 0.0 <= float(value) <= 1.0 for value in probabilities):
        raise ValueError("gate metrics must be finite probabilities")
    if any(type(value) is not int or value < 0 for value in counts):
        raise ValueError("gate counts must be nonnegative integers")
    gates = {
        "precision": {"actual": float(precision), "operator": ">=", "threshold": 0.60, "passed": precision >= 0.60},
        "recall": {"actual": float(recall), "operator": ">=", "threshold": 0.60, "passed": recall >= 0.60},
        "positive_image_recall": {"actual": float(positive_image_recall), "operator": ">=", "threshold": 0.60, "passed": positive_image_recall >= 0.60},
        "false_positive_negative_images": {"actual": false_positive_negative_images, "operator": "<=", "threshold": 6, "denominator": 60, "passed": false_positive_negative_images <= 6},
        "duplicate": {"actual": duplicate, "operator": "<=", "threshold": 4, "passed": duplicate <= 4},
        "integrity_violations": {"actual": integrity_violations, "operator": "==", "threshold": 0, "passed": integrity_violations == 0},
        "overlap_violations": {"actual": overlap_violations, "operator": "==", "threshold": 0, "passed": overlap_violations == 0},
        "one_shot_violations": {"actual": one_shot_violations, "operator": "==", "threshold": 0, "passed": one_shot_violations == 0},
        "write_violations": {"actual": write_violations, "operator": "==", "threshold": 0, "passed": write_violations == 0},
    }
    return {
        "status": (
            "V24B_SHADOW_CANDIDATE"
            if all(bool(gate["passed"]) for gate in gates.values())
            else "V24B_FUTURE_HOLDOUT_REJECTED"
        ),
        "gates": gates,
    }


def _require_owned(artifacts: Sequence[tuple[_OwnedArtifact, str]]) -> None:
    for artifact, label in artifacts:
        if not _artifact_is_self_owned(artifact):
            raise ValueError(f"{label} ownership changed")


def _cleanup_owned(artifacts: Sequence[_OwnedArtifact]) -> None:
    for artifact in artifacts:
        _cleanup_if_self_owned(artifact)


def evaluate_future_holdout(
    *,
    freeze: Path,
    expected_freeze_sha256: str,
    holdout_manifest: Path,
    expected_holdout_manifest_sha256: str,
    holdout_gt: Path,
    expected_holdout_gt_sha256: str,
    checkpoint: Path,
    expected_checkpoint_sha256: str,
    expected_evaluator_sha256: str,
    output: Path,
    model_factory: Callable[[_VerifiedCheckpoint], object] | None = None,
) -> dict[str, object]:
    """Run the accepted H0001..H0120 test exactly once and publish both outputs."""
    paths = (freeze, holdout_manifest, holdout_gt, checkpoint, output)
    if any(not path.is_absolute() for path in paths):
        raise ValueError("all evaluator paths must be absolute")
    expected_freeze_sha256 = _require_sha(expected_freeze_sha256, "freeze sha256")
    expected_holdout_manifest_sha256 = _require_sha(
        expected_holdout_manifest_sha256, "holdout manifest sha256"
    )
    expected_holdout_gt_sha256 = _require_sha(expected_holdout_gt_sha256, "holdout GT sha256")
    expected_checkpoint_sha256 = _require_sha(expected_checkpoint_sha256, "checkpoint sha256")
    expected_evaluator_sha256 = _require_sha(expected_evaluator_sha256, "evaluator code sha256")
    if expected_checkpoint_sha256 != APPROVED_CHECKPOINT_SHA256:
        raise ValueError("checkpoint SHA must be the exact approved v2.4 checkpoint")
    _validate_runtime_inference_contract()
    evaluator_code = _read_regular_snapshot(
        Path(__file__),
        label="evaluator code",
        maximum_bytes=MAX_JSON_BYTES,
        require_0600=False,
    )
    runner_code = _read_regular_snapshot(
        Path(validation_runner.__file__),
        label="validation runner code",
        maximum_bytes=MAX_JSON_BYTES,
        require_0600=False,
    )
    selector_code = _read_regular_snapshot(
        Path(selector.__file__),
        label="selector code",
        maximum_bytes=MAX_JSON_BYTES,
        require_0600=False,
    )
    evaluator_sha_pre = evaluator_code.sha256
    if evaluator_sha_pre != expected_evaluator_sha256:
        raise ValueError("evaluator code sha256 pin mismatch")

    freeze_snapshot = _read_regular_snapshot(
        freeze, label="freeze", maximum_bytes=MAX_JSON_BYTES
    )
    manifest_snapshot = _read_regular_snapshot(
        holdout_manifest, label="holdout manifest", maximum_bytes=MAX_JSON_BYTES
    )
    gt_snapshot = _read_regular_snapshot(
        holdout_gt, label="holdout GT", maximum_bytes=MAX_JSON_BYTES
    )
    checkpoint_snapshot = _read_regular_snapshot(
        checkpoint, label="checkpoint", maximum_bytes=MAX_CHECKPOINT_BYTES
    )
    expected_actual = (
        (freeze_snapshot, expected_freeze_sha256, "freeze"),
        (manifest_snapshot, expected_holdout_manifest_sha256, "holdout manifest"),
        (gt_snapshot, expected_holdout_gt_sha256, "holdout GT"),
        (checkpoint_snapshot, expected_checkpoint_sha256, "checkpoint"),
    )
    for snapshot, expected, label in expected_actual:
        if snapshot.sha256 != expected:
            raise ValueError(f"{label} sha256 mismatch")

    freeze_value = _parse_object(freeze_snapshot.payload, "freeze")
    freeze_contract = _validate_freeze(
        freeze_value, checkpoint_sha256=expected_checkpoint_sha256
    )
    manifest_value = _parse_object(manifest_snapshot.payload, "holdout manifest")
    manifest_records = _validate_holdout_manifest(
        manifest_value, freeze_sha256=freeze_snapshot.sha256
    )
    review_index_sha = _require_sha(
        manifest_value.get("review_index_sha256"), "holdout review-index"
    )
    gt_value = _parse_object(gt_snapshot.payload, "holdout GT")
    gt_boxes = _validate_gt(
        gt_value,
        manifest_records=manifest_records,
        manifest_sha256=manifest_snapshot.sha256,
        review_index_sha256=review_index_sha,
    )

    try:
        output_metadata = output.lstat()
    except FileNotFoundError:
        output_metadata = None
    if output_metadata is not None:
        if stat.S_ISLNK(output_metadata.st_mode):
            raise ValueError("output must be a real directory target, not a symlink")
        raise FileExistsError("output already exists for this evaluation attempt")
    _prepare_private_output_directory(output.parent, label="output parent")

    # The claim is keyed by immutable holdout identity, never by caller-chosen
    # output.  O_EXCL therefore closes output-path retry and concurrency bypasses.
    claim_directory = holdout_manifest.parent / ".locks"
    _prepare_private_output_directory(claim_directory, label="holdout one-shot lock")
    coordinator_path = claim_directory / (
        "evaluate-"
        f"{freeze_snapshot.sha256}-{manifest_snapshot.sha256}-{gt_snapshot.sha256}"
        ".started.private.json"
    )

    coordinator: _OwnedArtifact | None = None
    staging: Path | None = None
    staging_snapshot: _DirectorySnapshot | None = None
    reservations: list[_OwnedArtifact] = []
    pinned: _OwnedArtifact | None = None
    published: list[_OwnedArtifact] = []
    public_artifacts: tuple[tuple[_OwnedArtifact, str], ...] = ()
    samples: tuple[_HoldoutSample, ...] = ()
    try:
        # O_EXCL coordinator closes retry/concurrent races before model load or
        # predictor invocation.  It intentionally remains after every claimed attempt.
        coordinator = _write_private_new(
            coordinator_path,
            {
                "schema": "yolo26n-v24b-future-holdout-evaluation-started-lock-v1",
                "status": "STARTED",
                "freeze_sha256": freeze_snapshot.sha256,
                "holdout_manifest_sha256": manifest_snapshot.sha256,
                "holdout_gt_sha256": gt_snapshot.sha256,
                "checkpoint_sha256": checkpoint_snapshot.sha256,
                "evaluator_sha256": evaluator_sha_pre,
            },
        )
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{output.name}.quarantine-", dir=output.parent
            )
        )
        os.chmod(staging, 0o700)
        pinned_dir = staging / ".pinned"
        _prepare_private_output_directory(
            pinned_dir, label="staging pinned checkpoint"
        )
        ledger_path = staging / LEDGER_NAME
        report_path = staging / REPORT_NAME
        pinned_path = pinned_dir / "v24-best.private.pt"
        owner_token = os.urandom(32).hex()
        for path, artifact_kind in (
            (ledger_path, "prediction-ledger"),
            (report_path, "evaluation-report"),
        ):
            reservations.append(
                _write_private_new(
                    path,
                    {
                        "schema": "yolo26n-v24b-future-holdout-output-reservation-v1",
                        "status": "RESERVED",
                        "artifact": artifact_kind,
                        "owner_token": owner_token,
                    },
                )
            )
        guards = (
            (coordinator, "one-shot coordinator"),
            (reservations[0], "ledger reservation"),
            (reservations[1], "report reservation"),
        )
        _require_owned(guards)
        pinned = _write_private_bytes_new(pinned_path, checkpoint_snapshot.payload)
        if pinned.sha256 != checkpoint_snapshot.sha256:
            raise ValueError("pinned checkpoint bytes changed")
        checkpoint_capability = _VerifiedCheckpoint(
            payload=checkpoint_snapshot.payload,
            sha256=checkpoint_snapshot.sha256,
        )
        model = _make_model(checkpoint_capability, model_factory)
        _require_owned(((pinned, "pinned checkpoint"),))

        images_dir = holdout_manifest.parent / "images"
        directory_pre, samples, image_contract_sha = _load_samples(
            images_dir=images_dir,
            manifest_records=manifest_records,
            gt_boxes=gt_boxes,
        )
        confidence = float(freeze_contract["confidence"])
        nms_iou = float(freeze_contract["nms_iou"])
        prediction_records = _prediction_records(
            model,
            samples,
            confidence=confidence,
            nms_iou=nms_iou,
        )

        for snapshot, _, label in expected_actual:
            _require_snapshot_unchanged(
                snapshot,
                label=label,
                maximum_bytes=(MAX_CHECKPOINT_BYTES if label == "checkpoint" else MAX_JSON_BYTES),
            )
        for sample in samples:
            _require_snapshot_unchanged(
                sample.image_snapshot,
                label=f"holdout JPEG {sample.sequence}",
                maximum_bytes=MAX_JPEG_BYTES,
            )
        if _directory_snapshot(images_dir) != directory_pre:
            raise ValueError("holdout image directory identity or image set changed (ABA)")
        evaluator_sha_post = _sha_file(Path(__file__))
        if evaluator_sha_post != evaluator_sha_pre:
            raise ValueError("evaluator code changed during inference")
        for code_snapshot, label in (
            (evaluator_code, "evaluator code"),
            (runner_code, "validation runner code"),
            (selector_code, "selector code"),
        ):
            _require_snapshot_unchanged(
                code_snapshot,
                label=label,
                maximum_bytes=MAX_JSON_BYTES,
                require_0600=False,
            )
        if runner_code.sha256 != freeze_contract["runner_sha256"]:
            raise ValueError("validation runner code changed during inference")
        if selector_code.sha256 != freeze_contract["selector_sha256"]:
            raise ValueError("selector code changed during inference")
        _require_owned(
            (
                (coordinator, "one-shot coordinator"),
                (reservations[0], "ledger reservation"),
                (reservations[1], "report reservation"),
                (pinned, "pinned checkpoint"),
            )
        )

        metrics = _score_with_task2_semantics(
            samples=samples,
            prediction_records=prediction_records,
            confidence=confidence,
            nms_iou=nms_iou,
            checkpoint_sha256=checkpoint_snapshot.sha256,
            freeze_contract=freeze_contract,
        )
        decision = classify_shadow_status(
            precision=float(metrics["precision"]),
            recall=float(metrics["recall"]),
            positive_image_recall=float(metrics["positive_image_recall"]),
            false_positive_negative_images=int(metrics["false_positive_negative_images"]),
            duplicate=int(metrics["duplicate"]),
            integrity_violations=0,
            overlap_violations=0,
            one_shot_violations=0,
            write_violations=0,
        )
        provenance = {
            "checkpoint_sha256": checkpoint_snapshot.sha256,
            "freeze_sha256": freeze_snapshot.sha256,
            "holdout_manifest_sha256": manifest_snapshot.sha256,
            "holdout_gt_sha256": gt_snapshot.sha256,
            "evaluator_sha256": evaluator_sha_pre,
            "validation_runner_sha256": freeze_contract["runner_sha256"],
            "selector_sha256": freeze_contract["selector_sha256"],
            "development_dataset_manifest_sha256": freeze_contract["dataset_manifest_sha256"],
            "review_index_sha256": review_index_sha,
            "image_contract_sha256": image_contract_sha,
        }
        inference = {
            "confidence": confidence,
            "imgsz": INFERENCE_IMAGE_SIZE,
            "nms_iou": nms_iou,
            "max_det": INFERENCE_MAX_DETECTIONS,
            "device": INFERENCE_DEVICE,
        }
        counts = {
            "image_count": IMAGE_COUNT,
            "positive_image_count": POSITIVE_IMAGE_COUNT,
            "negative_image_count": NEGATIVE_IMAGE_COUNT,
            "gt_box_count": sum(len(sample.gt_boxes) for sample in samples),
            "raw_prediction_count": sum(
                len(record["predictions"]) for record in prediction_records
            ),
        }
        violations = {"integrity": 0, "overlap": 0, "one_shot": 0, "write": 0}
        common = {
            "evaluation_tier": "future_holdout",
            "shadow_only": True,
            "production_change_authorized": False,
            "provenance": provenance,
            "inference": inference,
            "counts": counts,
            "metrics": metrics,
            "gates": decision["gates"],
            "violations": violations,
            "write_audit": dict(_WRITE_AUDIT),
        }
        ledger: dict[str, object] = {
            "schema": LEDGER_SCHEMA,
            "status": "V24B_FUTURE_HOLDOUT_PREDICTIONS_READY",
            "decision_status": decision["status"],
            **common,
            "records": list(prediction_records),
        }
        report: dict[str, object] = {
            "schema": REPORT_SCHEMA,
            "status": decision["status"],
            **common,
        }

        published.append(_atomic_replace_owned_json(reservations[0], ledger))
        _require_owned(
            (
                (coordinator, "one-shot coordinator"),
                (published[0], "prediction ledger"),
                (reservations[1], "report reservation"),
                (pinned, "pinned checkpoint"),
            )
        )
        published.append(_atomic_replace_owned_json(reservations[1], report))
        # Both complete artifacts remain inside a private sibling directory.
        # Renaming that directory is the single public pair-publication point.
        _require_owned(
            (
                (coordinator, "one-shot coordinator"),
                (published[0], "prediction ledger"),
                (published[1], "evaluation report"),
                (pinned, "pinned checkpoint"),
            )
        )
        assert staging is not None
        staging_snapshot = _directory_snapshot(staging)
        validation_runner._fsync_directory(staging)
        if not _same_directory_snapshot(staging_snapshot, staging):
            raise ValueError("staging directory identity changed before publication")
        public_artifacts = (
            (
                _relocate_owned(published[0], output / LEDGER_NAME),
                "published prediction ledger",
            ),
            (
                _relocate_owned(published[1], output / REPORT_NAME),
                "published evaluation report",
            ),
            (
                _relocate_owned(
                    pinned, output / ".pinned" / "v24-best.private.pt"
                ),
                "published pinned checkpoint",
            ),
        )
        validation_runner._atomic_rename_no_overwrite(staging, output)
        staging = None
        validation_runner._fsync_directory(output.parent)
        _require_publication_boundary(
            directory=staging_snapshot,
            output=output,
            coordinator=coordinator,
            public_artifacts=public_artifacts,
        )
        return report
    except BaseException:
        if (
            staging is None
            and staging_snapshot is not None
            and _same_directory_snapshot(staging_snapshot, output, after_rename=True)
        ):
            _cleanup_owned(tuple(artifact for artifact, _ in public_artifacts))
        _cleanup_owned(tuple(published))
        _cleanup_owned(tuple(reservations))
        if pinned is not None:
            _cleanup_owned((pinned,))
        raise
    finally:
        for sample in samples:
            sample.image.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--expected-freeze-sha256", required=True)
    parser.add_argument("--holdout-manifest", type=Path, required=True)
    parser.add_argument("--expected-holdout-manifest-sha256", required=True)
    parser.add_argument("--holdout-gt", type=Path, required=True)
    parser.add_argument("--expected-holdout-gt-sha256", required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--expected-checkpoint-sha256", required=True)
    parser.add_argument("--expected-evaluator-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = evaluate_future_holdout(
        freeze=args.freeze,
        expected_freeze_sha256=args.expected_freeze_sha256,
        holdout_manifest=args.holdout_manifest,
        expected_holdout_manifest_sha256=args.expected_holdout_manifest_sha256,
        holdout_gt=args.holdout_gt,
        expected_holdout_gt_sha256=args.expected_holdout_gt_sha256,
        checkpoint=args.checkpoint,
        expected_checkpoint_sha256=args.expected_checkpoint_sha256,
        expected_evaluator_sha256=args.expected_evaluator_sha256,
        output=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

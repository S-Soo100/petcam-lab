"""Run the v2.4 validation NMS grid once, then freeze one postprocess rule."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Sequence

from PIL import Image

try:
    from scripts import select_yolo26n_v24b_postprocess as selector
except ModuleNotFoundError:  # Direct ``python scripts/...py`` execution.
    import select_yolo26n_v24b_postprocess as selector  # type: ignore[no-redef]


V24_CHECKPOINT_SHA256 = (
    "3c9f752b9369b30be4083f837676271640cfd1f4cbfa6027382a380efc4212c4"
)
VALIDATION_IMAGE_COUNT = 153
INFERENCE_CONTRACT = {
    "confidence": 0.001,
    "imgsz": 960,
    "max_det": 50,
    "device": "mps",
}


@dataclass(frozen=True)
class _Sample:
    sequence: str
    image_path: Path
    label_path: Path
    image_sha256: str
    label_sha256: str
    width: int
    height: int
    gt_boxes: tuple[tuple[float, float, float, float], ...]
    image: Image.Image


@dataclass(frozen=True)
class _OwnedArtifact:
    path: Path
    device: int
    inode: int
    sha256: str


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha(value: object, *, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _publish_json_fd(descriptor: int, value: dict[str, object]) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.ftruncate(descriptor, 0)
    written = 0
    while written < len(payload):
        written += os.write(descriptor, payload[written:])
    os.fsync(descriptor)


def _write_private_new(path: Path, value: dict[str, object]) -> None:
    _atomic_write_private_json_new(path, value)


def _write_private_bytes_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.tmp-", dir=path.parent
    )
    temporary = Path(temporary_name)
    published = False
    try:
        os.fchmod(descriptor, 0o600)
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(temporary, path, follow_symlinks=False)
        published = True
        temporary.unlink()
        _fsync_directory(path.parent)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        if published:
            path.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError as error:
        if error.errno in {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
            return
        raise
    try:
        try:
            os.fsync(descriptor)
        except OSError as error:
            if error.errno not in {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
                raise
    finally:
        os.close(descriptor)


def _atomic_write_private_json_new(path: Path, value: dict[str, object]) -> None:
    """Build a 0600 sibling file, then atomically link it at a new final path."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.tmp-", dir=path.parent
    )
    temporary = Path(temporary_name)
    published = False
    try:
        os.fchmod(descriptor, 0o600)
        _publish_json_fd(descriptor, value)
        os.close(descriptor)
        descriptor = -1
        # A same-filesystem hard link exposes the fully fsynced inode in one
        # step and fails with EEXIST instead of replacing an existing final.
        os.link(temporary, path, follow_symlinks=False)
        published = True
        temporary.unlink()
        _fsync_directory(path.parent)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        if published:
            path.unlink(missing_ok=True)
        raise


def _capture_owned_artifact(path: Path) -> _OwnedArtifact:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
    finally:
        os.close(descriptor)
    if metadata.st_mode & 0o777 != 0o600:
        raise ValueError("owned private artifact mode must be exactly 0600")
    return _OwnedArtifact(path, metadata.st_dev, metadata.st_ino, digest.hexdigest())


def _artifact_is_self_owned(artifact: _OwnedArtifact) -> bool:
    try:
        return _capture_owned_artifact(artifact.path) == artifact
    except (FileNotFoundError, OSError, ValueError):
        return False


def _cleanup_if_self_owned(artifact: _OwnedArtifact) -> None:
    if _artifact_is_self_owned(artifact):
        artifact.path.unlink(missing_ok=True)


def _atomic_replace_owned_json(
    reservation: _OwnedArtifact, value: dict[str, object]
) -> _OwnedArtifact:
    """Replace only this call's exact reservation with a complete sibling JSON."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{reservation.path.name}.tmp-", dir=reservation.path.parent
    )
    temporary = Path(temporary_name)
    replacement: _OwnedArtifact | None = None
    try:
        os.fchmod(descriptor, 0o600)
        _publish_json_fd(descriptor, value)
        os.close(descriptor)
        descriptor = -1
        temporary_artifact = _capture_owned_artifact(temporary)
        replacement = _OwnedArtifact(
            reservation.path,
            temporary_artifact.device,
            temporary_artifact.inode,
            temporary_artifact.sha256,
        )
        if not _artifact_is_self_owned(reservation):
            raise ValueError("ledger reservation ownership changed before finalization")
        os.replace(temporary, reservation.path)
        _fsync_directory(reservation.path.parent)
        if not _artifact_is_self_owned(replacement):
            raise ValueError("ledger final ownership changed during finalization")
        return replacement
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        if replacement is not None:
            _cleanup_if_self_owned(replacement)
        raise


def _safe_dataset_path(root: Path, raw: object, *, expected: str) -> Path:
    if not isinstance(raw, str):
        raise ValueError("validation path is invalid")
    relative = PurePosixPath(raw)
    if relative.is_absolute() or ".." in relative.parts or raw != expected:
        raise ValueError("validation path must be the exact val sequence path")
    if any(part.lower() in {"test", "external"} for part in relative.parts):
        raise ValueError("validation path must not use test or external data")
    path = root.joinpath(*relative.parts)
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as error:
        raise ValueError("validation path escapes or is missing") from error
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _load_gt_boxes(payload: bytes, *, width: int, height: int) -> tuple[tuple[float, float, float, float], ...]:
    boxes: list[tuple[float, float, float, float]] = []
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("validation label is not UTF-8") from error
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 5 or fields[0] != "0":
            raise ValueError(f"validation label line {line_number} is invalid")
        try:
            center_x, center_y, box_width, box_height = map(float, fields[1:])
        except ValueError as error:
            raise ValueError(f"validation label line {line_number} is invalid") from error
        if not all(
            math.isfinite(value) and 0.0 <= value <= 1.0
            for value in (center_x, center_y, box_width, box_height)
        ) or box_width <= 0.0 or box_height <= 0.0:
            raise ValueError(f"validation label line {line_number} is invalid")
        x1 = (center_x - box_width / 2.0) * width
        y1 = (center_y - box_height / 2.0) * height
        x2 = (center_x + box_width / 2.0) * width
        y2 = (center_y + box_height / 2.0) * height
        if not (0.0 <= x1 < x2 <= width and 0.0 <= y1 < y2 <= height):
            raise ValueError(f"validation label line {line_number} is out of bounds")
        boxes.append((x1, y1, x2, y2))
    return tuple(boxes)


def _decode_image(payload: bytes, *, expected_width: object, expected_height: object) -> tuple[Image.Image, int, int]:
    try:
        with Image.open(BytesIO(payload)) as decoded:
            decoded.load()
            image = decoded.convert("RGB")
    except Exception as error:
        raise ValueError("validation image decode failed") from error
    width, height = image.size
    if width <= 0 or height <= 0:
        image.close()
        raise ValueError("validation image dimensions are invalid")
    for expected, actual, name in (
        (expected_width, width, "width"),
        (expected_height, height, "height"),
    ):
        if expected is not None and (type(expected) is not int or expected != actual):
            image.close()
            raise ValueError(f"validation image {name} mismatch")
    return image, width, height


def _load_validation_samples(
    *, dataset_root: Path, manifest: Mapping[str, object]
) -> tuple[_Sample, ...]:
    if (
        manifest.get("schema") != "yolo26n-owner-dataset-v24"
        or manifest.get("evaluation_tier") != "development"
        or manifest.get("future_holdout_required") is not True
        or any(
            manifest.get(key) != 0
            for key in ("db_write_count", "r2_write_count", "service_write_count")
        )
    ):
        raise ValueError("v2.4 dataset manifest contract mismatch")
    split_counts = manifest.get("split_counts")
    if not isinstance(split_counts, Mapping) or split_counts.get("val") != VALIDATION_IMAGE_COUNT:
        raise ValueError("dataset manifest must pin exactly 153 validation images")
    records = manifest.get("records")
    if not isinstance(records, list):
        raise ValueError("dataset manifest records are invalid")
    validation_records = [
        record
        for record in records
        if isinstance(record, Mapping) and record.get("split") == "val"
    ]
    if len(validation_records) != VALIDATION_IMAGE_COUNT:
        raise ValueError("dataset manifest must contain exactly 153 validation records")

    samples: list[_Sample] = []
    sequences: set[str] = set()
    image_hashes: set[str] = set()
    try:
        for record in validation_records:
            sequence = record.get("sequence")
            expected_image_sha = record.get("image_sha256")
            if (
                not isinstance(sequence, str)
                or not sequence
                or sequence in sequences
                or not _is_sha(expected_image_sha, length=64)
                or expected_image_sha in image_hashes
            ):
                raise ValueError("validation record identity is invalid or duplicate")
            image_path = _safe_dataset_path(
                dataset_root,
                record.get("image_path"),
                expected=f"images/val/{sequence}.jpg",
            )
            label_path = _safe_dataset_path(
                dataset_root,
                record.get("label_path"),
                expected=f"labels/val/{sequence}.txt",
            )
            # Read once before inference: these exact bytes feed both hashing and PIL.
            image_payload = image_path.read_bytes()
            label_payload = label_path.read_bytes()
            image_sha = _sha_bytes(image_payload)
            label_sha = _sha_bytes(label_payload)
            if image_sha != expected_image_sha:
                raise ValueError("validation image SHA-256 mismatch")
            image, width, height = _decode_image(
                image_payload,
                expected_width=record.get("width"),
                expected_height=record.get("height"),
            )
            gt_boxes = _load_gt_boxes(label_payload, width=width, height=height)
            if type(record.get("box_count")) is not int or record["box_count"] != len(gt_boxes):
                image.close()
                raise ValueError("validation label box count mismatch")
            samples.append(
                _Sample(
                    sequence=sequence,
                    image_path=image_path,
                    label_path=label_path,
                    image_sha256=image_sha,
                    label_sha256=label_sha,
                    width=width,
                    height=height,
                    gt_boxes=gt_boxes,
                    image=image,
                )
            )
            sequences.add(sequence)
            image_hashes.add(image_sha)
    except BaseException:
        for sample in samples:
            sample.image.close()
        raise
    return tuple(samples)


def _make_model(checkpoint_path: Path, model_factory: Callable[[str], object] | None) -> object:
    if model_factory is None:
        from ultralytics import YOLO

        model_factory = YOLO
    return model_factory(str(checkpoint_path))


def _prediction_rows(
    model: object, samples: Sequence[_Sample], *, nms_iou: float
) -> list[dict[str, object]]:
    raw_results = model.predict(
        source=[sample.image for sample in samples],
        conf=INFERENCE_CONTRACT["confidence"],
        imgsz=INFERENCE_CONTRACT["imgsz"],
        iou=nms_iou,
        max_det=INFERENCE_CONTRACT["max_det"],
        device=INFERENCE_CONTRACT["device"],
        verbose=False,
        stream=False,
        save=False,
    )
    if not isinstance(raw_results, Sequence) or len(raw_results) != len(samples):
        raise ValueError("Ultralytics result count does not match input count")
    rows: list[dict[str, object]] = []
    for index, (sample, result) in enumerate(zip(samples, raw_results, strict=True)):
        if str(result.path) != f"image{index}.jpg":
            raise ValueError("Ultralytics result order does not match input order")
        height, width = result.orig_shape
        if (int(width), int(height)) != (sample.width, sample.height):
            raise ValueError("Ultralytics result dimensions do not match input")
        boxes = result.boxes
        xyxy = boxes.xyxy.cpu().tolist() if boxes is not None else []
        confidences = boxes.conf.cpu().tolist() if boxes is not None else []
        if len(xyxy) != len(confidences):
            raise ValueError("Ultralytics box and confidence counts differ")
        predictions: list[dict[str, object]] = []
        for confidence, raw_box in zip(confidences, xyxy, strict=True):
            if (
                type(confidence) not in (int, float)
                or not math.isfinite(float(confidence))
                or not 0.0 <= float(confidence) <= 1.0
                or not isinstance(raw_box, Sequence)
                or isinstance(raw_box, (str, bytes))
                or len(raw_box) != 4
                or any(type(value) not in (int, float) or not math.isfinite(float(value)) for value in raw_box)
            ):
                raise ValueError("Ultralytics prediction is malformed")
            x1, y1, x2, y2 = map(float, raw_box)
            if not (0.0 <= x1 < x2 <= sample.width and 0.0 <= y1 < y2 <= sample.height):
                raise ValueError("Ultralytics prediction box is out of bounds")
            predictions.append(
                {"confidence": float(confidence), "xyxy": [x1, y1, x2, y2]}
            )
        rows.append(
            {
                "sequence": sample.sequence,
                "image_sha256": sample.image_sha256,
                "label_sha256": sample.label_sha256,
                "width": sample.width,
                "height": sample.height,
                "gt_boxes": [list(box) for box in sample.gt_boxes],
                "predictions": predictions,
            }
        )
    return rows


def _input_sha256(
    *,
    checkpoint_sha256: str,
    manifest_sha256: str,
    runner_sha256: str,
    selector_sha256: str,
    samples: Sequence[_Sample],
) -> dict[str, object]:
    return {
        "checkpoint": checkpoint_sha256,
        "dataset_manifest": manifest_sha256,
        "runner": runner_sha256,
        "selector": selector_sha256,
        "frames": [
            {
                "sequence": sample.sequence,
                "image_sha256": sample.image_sha256,
                "label_sha256": sample.label_sha256,
            }
            for sample in samples
        ],
    }


def _post_input_sha256(
    *, checkpoint: Path, dataset_manifest: Path, samples: Sequence[_Sample]
) -> dict[str, object]:
    return {
        "checkpoint": _sha_file(checkpoint),
        "dataset_manifest": _sha_file(dataset_manifest),
        "runner": _sha_file(Path(__file__)),
        "selector": _sha_file(Path(selector.__file__)),
        "frames": [
            {
                "sequence": sample.sequence,
                "image_sha256": _sha_file(sample.image_path),
                "label_sha256": _sha_file(sample.label_path),
            }
            for sample in samples
        ],
    }


def _ledger_path(output: Path, nms_iou: float) -> Path:
    return output / f"prediction-ledgers/nms-{round(nms_iou * 100):02d}.private.json"


def _lock_path(output: Path, nms_iou: float) -> Path:
    return output / f".locks/predict-nms-{round(nms_iou * 100):02d}.started.private.json"


def run_prediction_grid(
    *,
    dataset_manifest: Path,
    expected_dataset_manifest_sha256: str,
    checkpoint: Path,
    expected_checkpoint_sha256: str,
    output: Path,
    source_commit: str,
    model_factory: Callable[[str], object] | None = None,
) -> dict[str, object]:
    """Claim and run all seven validation NMS calls without publishing partial ledgers."""
    if not output.is_absolute() or not dataset_manifest.is_absolute() or not checkpoint.is_absolute():
        raise ValueError("runner paths must be absolute")
    if not dataset_manifest.is_file() or not checkpoint.is_file():
        raise FileNotFoundError("dataset manifest or checkpoint is missing")
    if not _is_sha(source_commit, length=40):
        raise ValueError("source commit SHA is malformed")
    if (
        not _is_sha(expected_checkpoint_sha256, length=64)
        or expected_checkpoint_sha256 != V24_CHECKPOINT_SHA256
    ):
        raise ValueError("expected SHA must be the exact v2.4 checkpoint")

    manifest_payload = dataset_manifest.read_bytes()
    checkpoint_payload = checkpoint.read_bytes()
    manifest_sha = _sha_bytes(manifest_payload)
    checkpoint_sha = _sha_bytes(checkpoint_payload)
    if (
        not _is_sha(expected_dataset_manifest_sha256, length=64)
        or manifest_sha != expected_dataset_manifest_sha256
    ):
        raise ValueError("dataset manifest SHA mismatch")
    if checkpoint_sha != expected_checkpoint_sha256:
        raise ValueError("exact v2.4 checkpoint SHA mismatch")
    try:
        manifest = json.loads(manifest_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("dataset manifest JSON is invalid") from error
    if not isinstance(manifest, Mapping):
        raise ValueError("dataset manifest root must be an object")

    # Dataset paths and count are rejected before the irreversible one-shot claim.
    dataset_root = dataset_manifest.parent
    if not dataset_manifest.name.endswith(".private.json") or any(
        part.lower() in {"test", "external"} for part in dataset_manifest.parts
    ):
        raise ValueError("dataset manifest must be an approved private validation path")
    validation_records = manifest.get("records")
    if not isinstance(validation_records, list):
        raise ValueError("dataset manifest records are invalid")
    val_records = [
        row for row in validation_records if isinstance(row, Mapping) and row.get("split") == "val"
    ]
    if len(val_records) != VALIDATION_IMAGE_COUNT:
        raise ValueError("dataset manifest must contain exactly 153 validation records")
    for row in val_records:
        sequence = row.get("sequence")
        if not isinstance(sequence, str) or not sequence:
            raise ValueError("validation sequence is invalid")
        _safe_dataset_path(dataset_root, row.get("image_path"), expected=f"images/val/{sequence}.jpg")
        _safe_dataset_path(dataset_root, row.get("label_path"), expected=f"labels/val/{sequence}.txt")

    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(output, 0o700)
    ledger_paths = [_ledger_path(output, nms) for nms in selector.NMS_GRID]
    lock_paths = [_lock_path(output, nms) for nms in selector.NMS_GRID]
    coordinator = output / ".locks/predict-grid.started.private.json"
    pinned_checkpoint = output / ".pinned/v24-best.private.pt"
    if any(
        path.exists()
        for path in (*ledger_paths, *lock_paths, coordinator, pinned_checkpoint)
    ):
        raise FileExistsError("prediction grid output, lock, or pinned checkpoint exists")

    # This single claim closes the precheck race for the whole attempt. A loser
    # owns nothing and therefore must not clean paths created by the winner.
    _write_private_new(
        coordinator,
        {
            "schema": "yolo26n-v24b-postprocess-grid-started-lock-v1",
            "status": "STARTED",
            "operation": "predict-grid",
            "checkpoint_sha256": checkpoint_sha,
            "dataset_manifest_sha256": manifest_sha,
            "source_commit": source_commit,
        },
    )

    reservations: list[_OwnedArtifact] = []
    finalized_ledgers: list[_OwnedArtifact] = []
    claimed_locks: list[Path] = []
    samples: tuple[_Sample, ...] = ()
    inference_started = False
    pinned_owned = False
    try:
        owner_token = os.urandom(32).hex()
        for nms_iou, path in zip(selector.NMS_GRID, ledger_paths, strict=True):
            _atomic_write_private_json_new(
                path,
                {
                    "schema": "yolo26n-v24b-postprocess-ledger-reservation-v1",
                    "status": "RESERVED",
                    "operation": f"predict-nms-{round(nms_iou * 100):02d}",
                    "nms_iou": nms_iou,
                    "owner_token": owner_token,
                    "checkpoint_sha256": checkpoint_sha,
                    "dataset_manifest_sha256": manifest_sha,
                    "source_commit": source_commit,
                },
            )
            reservations.append(_capture_owned_artifact(path))
        # Every final reservation and NMS lock exists before model loading.
        for nms_iou, path in zip(selector.NMS_GRID, lock_paths, strict=True):
            _write_private_new(
                path,
                {
                    "schema": "yolo26n-v24b-postprocess-started-lock-v1",
                    "status": "STARTED",
                    "operation": f"predict-nms-{round(nms_iou * 100):02d}",
                    "nms_iou": nms_iou,
                    "checkpoint_sha256": checkpoint_sha,
                    "dataset_manifest_sha256": manifest_sha,
                    "source_commit": source_commit,
                },
            )
            claimed_locks.append(path)
        _write_private_bytes_new(pinned_checkpoint, checkpoint_payload)
        pinned_owned = True
        if _sha_file(pinned_checkpoint) != checkpoint_sha:
            raise ValueError("pinned checkpoint SHA mismatch")
        model = _make_model(pinned_checkpoint, model_factory)
        samples = _load_validation_samples(dataset_root=dataset_root, manifest=manifest)
        runner_sha = _sha_file(Path(__file__))
        selector_sha = _sha_file(Path(selector.__file__))
        pre_sha = _input_sha256(
            checkpoint_sha256=checkpoint_sha,
            manifest_sha256=manifest_sha,
            runner_sha256=runner_sha,
            selector_sha256=selector_sha,
            samples=samples,
        )
        ledgers: list[dict[str, object]] = []
        inference_started = True
        for nms_iou in selector.NMS_GRID:
            records = _prediction_rows(model, samples, nms_iou=nms_iou)
            ledgers.append(
                {
                    "schema": "yolo26n-v24b-postprocess-prediction-ledger-v1",
                    "status": "V24B_POSTPROCESS_PREDICTIONS_READY",
                    "dataset_schema": "yolo26n-owner-dataset-v24",
                    "evaluation_tier": "development",
                    "split": "val",
                    "candidate": "warm-start",
                    "source_commit": source_commit,
                    "runner_sha256": runner_sha,
                    "selector_sha256": selector_sha,
                    "dataset_manifest_sha256": manifest_sha,
                    "checkpoint_sha256": checkpoint_sha,
                    "inference": {**INFERENCE_CONTRACT, "nms_iou": nms_iou},
                    "image_count": len(records),
                    "gt_box_count": sum(len(row["gt_boxes"]) for row in records),
                    "prediction_count": sum(len(row["predictions"]) for row in records),
                    "records": records,
                    "input_sha256_pre": pre_sha,
                    "input_sha256_post": None,
                    "db_write_count": 0,
                    "r2_write_count": 0,
                    "service_write_count": 0,
                    "git_write_count": 0,
                }
            )
        post_sha = _post_input_sha256(
            checkpoint=checkpoint, dataset_manifest=dataset_manifest, samples=samples
        )
        if post_sha != pre_sha:
            raise ValueError("checkpoint, dataset, image, label, or code input changed during inference")
        for ledger in ledgers:
            ledger["input_sha256_post"] = post_sha
        if not all(_artifact_is_self_owned(item) for item in reservations):
            raise ValueError("ledger reservation ownership changed before finalization")
        for reservation, ledger in zip(reservations, ledgers, strict=True):
            finalized_ledgers.append(_atomic_replace_owned_json(reservation, ledger))
    except BaseException:
        for artifact in (*finalized_ledgers, *reservations):
            _cleanup_if_self_owned(artifact)
        if pinned_owned:
            pinned_checkpoint.unlink(missing_ok=True)
        if not inference_started:
            for path in claimed_locks:
                path.unlink(missing_ok=True)
        raise
    finally:
        for sample in samples:
            sample.image.close()

    return {
        "status": "V24B_POSTPROCESS_PREDICTIONS_READY",
        "image_count": VALIDATION_IMAGE_COUNT,
        "ledger_count": len(selector.NMS_GRID),
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "git_write_count": 0,
    }


def _validate_runner_ledger(
    ledger: Mapping[str, object], *, expected_nms: float, actual_sha256: str
) -> None:
    if not _is_sha(actual_sha256, length=64):
        raise ValueError("prediction ledger SHA is invalid")
    pre = ledger.get("input_sha256_pre")
    post = ledger.get("input_sha256_post")
    if not isinstance(pre, Mapping) or pre != post:
        raise ValueError("prediction ledger provenance pre/post mismatch")
    if (
        pre.get("checkpoint") != ledger.get("checkpoint_sha256")
        or pre.get("dataset_manifest") != ledger.get("dataset_manifest_sha256")
        or pre.get("runner") != ledger.get("runner_sha256")
        or pre.get("selector") != ledger.get("selector_sha256")
        or pre.get("runner") != _sha_file(Path(__file__))
        or pre.get("selector") != _sha_file(Path(selector.__file__))
        or ledger.get("image_count") != VALIDATION_IMAGE_COUNT
        or any(ledger.get(key) != 0 for key in ("db_write_count", "r2_write_count", "service_write_count", "git_write_count"))
    ):
        raise ValueError("prediction ledger provenance contract mismatch")
    frames = pre.get("frames")
    records = ledger.get("records")
    if not isinstance(frames, list) or not isinstance(records, list) or len(frames) != len(records):
        raise ValueError("prediction ledger frame provenance mismatch")
    for frame, record in zip(frames, records, strict=True):
        if not isinstance(frame, Mapping) or not isinstance(record, Mapping) or any(
            frame.get(key) != record.get(key)
            for key in ("sequence", "image_sha256", "label_sha256")
        ):
            raise ValueError("prediction ledger frame provenance mismatch")
    inference = ledger.get("inference")
    if not isinstance(inference, Mapping) or inference.get("nms_iou") != expected_nms:
        raise ValueError("prediction ledger NMS path mismatch")


def freeze_prediction_grid(*, output: Path) -> dict[str, object]:
    """Verify all seven immutable ledgers before publishing one no-overwrite freeze."""
    if not output.is_absolute():
        raise ValueError("output path must be absolute")
    freeze_path = output / "v24b-postprocess-freeze.private.json"
    freeze_lock = output / ".locks/freeze.started.private.json"
    if freeze_path.exists() or freeze_lock.exists():
        raise FileExistsError("postprocess freeze or its one-shot lock exists")
    ledgers: dict[float, Mapping[str, object]] = {}
    ledger_sha256: dict[float, str] = {}
    common_pre: Mapping[str, object] | None = None
    for nms_iou in selector.NMS_GRID:
        path = _ledger_path(output, nms_iou)
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_mode & 0o777 != 0o600:
            raise ValueError("prediction ledger mode must be exactly 0600")
        payload = path.read_bytes()
        actual_sha = _sha_bytes(payload)
        try:
            ledger = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("prediction ledger JSON is invalid") from error
        if not isinstance(ledger, Mapping):
            raise ValueError("prediction ledger root must be an object")
        _validate_runner_ledger(ledger, expected_nms=nms_iou, actual_sha256=actual_sha)
        if common_pre is None:
            common_pre = ledger["input_sha256_pre"]
        elif ledger["input_sha256_pre"] != common_pre:
            raise ValueError("prediction ledgers have different provenance")
        ledgers[nms_iou] = ledger
        ledger_sha256[nms_iou] = actual_sha
    freeze = selector.build_postprocess_freeze(
        ledgers, ledger_sha256=ledger_sha256
    )
    freeze.update(
        {
            "selector_sha256": _sha_file(Path(selector.__file__)),
            "input_sha256": dict(common_pre or {}),
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
            "git_write_count": 0,
        }
    )

    # Validation is complete. Claim the immutable final and lock, then guard
    # the validation/read-to-publish window with one last exact byte check.
    _write_private_new(
        freeze_lock,
        {
            "schema": "yolo26n-v24b-postprocess-freeze-started-lock-v1",
            "status": "STARTED",
            "operation": "freeze",
        },
    )
    if any(
        _sha_file(_ledger_path(output, nms_iou)) != ledger_sha256[nms_iou]
        for nms_iou in selector.NMS_GRID
    ):
        raise ValueError("prediction ledger changed during freeze")
    _atomic_write_private_json_new(freeze_path, freeze)
    return freeze


def _source_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    value = completed.stdout.strip()
    if not _is_sha(value, length=40):
        raise ValueError("git HEAD is not a full commit SHA")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    predict = commands.add_parser("predict-grid")
    predict.add_argument("--dataset-manifest", required=True, type=Path)
    predict.add_argument("--expected-dataset-manifest-sha256", required=True)
    predict.add_argument("--checkpoint", required=True, type=Path)
    predict.add_argument("--expected-checkpoint-sha256", required=True)
    predict.add_argument("--output", required=True, type=Path)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "predict-grid":
        result = run_prediction_grid(
            dataset_manifest=args.dataset_manifest,
            expected_dataset_manifest_sha256=args.expected_dataset_manifest_sha256,
            checkpoint=args.checkpoint,
            expected_checkpoint_sha256=args.expected_checkpoint_sha256,
            output=args.output,
            source_commit=_source_commit(),
        )
    else:
        result = freeze_prediction_grid(output=args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

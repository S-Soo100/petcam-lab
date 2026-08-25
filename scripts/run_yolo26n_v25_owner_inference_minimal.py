"""Run frozen v2.4 inference over the accepted Owner-280 bundle."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import stat
import sys
import zipfile
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

try:
    from scripts.yolo26n_v25_hardcase_science import (
        POLICY_ID,
        POLICY_SEED,
        classify_hardcase_signals,
        select_blind_queue,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from yolo26n_v25_hardcase_science import (  # type: ignore[no-redef]
        POLICY_ID,
        POLICY_SEED,
        classify_hardcase_signals,
        select_blind_queue,
    )


EXPECTED_BUNDLE_COUNT = 280
FROZEN_SELECTED = {"confidence": 0.25, "nms_iou": 0.40, "duplicate": 4}
INFERENCE_PARAMS = {"imgsz": 960, "max_det": 50}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_PUBLIC_KEYS = {
    "source",
    "source_video_sha256",
    "source_ref",
    "predictions",
    "prediction",
    "confidence",
    "signals",
    "signal",
    "bucket",
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


@dataclass(frozen=True)
class VerifiedCheckpoint:
    payload: bytes
    sha256: str


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _read_regular_bytes(path: Path) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("input must be a regular file")
        remaining = metadata.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("input changed while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _parse_json(payload: bytes, *, name: str) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"{name} duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(payload, object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError(f"{name} JSON invalid") from None
    if not isinstance(value, dict):
        raise ValueError(f"{name} root invalid")
    return value


def directory_contract_sha256(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("bundle must be a real directory")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("bundle symlink is forbidden")
        digest.update(relative)
        if stat.S_ISDIR(metadata.st_mode):
            digest.update(b"\0D\0")
        elif stat.S_ISREG(metadata.st_mode):
            digest.update(b"\0F\0")
            digest.update(_read_regular_bytes(path))
        else:
            raise ValueError("bundle child must be a regular file or directory")
    return digest.hexdigest()


def _load_bundle(
    bundle_dir: Path, expected_bundle_sha256: str
) -> tuple[list[dict[str, object]], str, str]:
    if (
        not bundle_dir.is_absolute()
        or _SHA256.fullmatch(expected_bundle_sha256) is None
        or directory_contract_sha256(bundle_dir) != expected_bundle_sha256
    ):
        raise ValueError("bundle SHA mismatch")
    if {path.name for path in bundle_dir.iterdir()} != {
        "images",
        "manifest.private.json",
    }:
        raise ValueError("bundle member set mismatch")
    manifest_payload = _read_regular_bytes(bundle_dir / "manifest.private.json")
    manifest = _parse_json(manifest_payload, name="bundle manifest")
    records = manifest.get("records")
    provenance = manifest.get("provenance")
    if (
        manifest.get("schema") != "yolo26n-v25-dedup-frame-bundle-v1"
        or manifest.get("status") != "V25_DEDUP_FRAME_BUNDLE_READY"
        or manifest.get("role") != "owner-development-video"
        or not isinstance(records, list)
        or manifest.get("record_count") != EXPECTED_BUNDLE_COUNT
        or len(records) != EXPECTED_BUNDLE_COUNT
        or not isinstance(provenance, Mapping)
        or any(
            manifest.get(key) != 0
            for key in ("db_write_count", "r2_write_count", "service_write_count")
        )
    ):
        raise ValueError("bundle count or manifest mismatch")
    producer_code_sha = provenance.get("code_sha256")
    if not isinstance(producer_code_sha, str) or _SHA256.fullmatch(producer_code_sha) is None:
        producer_code_sha = "unavailable"
    images_dir = bundle_dir / "images"
    expected_names: set[str] = set()
    loaded: list[dict[str, object]] = []
    for index, raw in enumerate(records, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError("bundle record mismatch")
        row = dict(raw)
        filename = f"F{index:06d}.jpg"
        if row.get("filename") != filename:
            raise ValueError("bundle member order mismatch")
        if row.get("role") != "owner-development-video":
            raise ValueError("protected role is forbidden")
        payload = _read_regular_bytes(images_dir / filename)
        image_sha = hashlib.sha256(payload).hexdigest()
        if row.get("image_sha256") != image_sha:
            raise ValueError("bundle image SHA mismatch")
        row["jpeg_bytes"] = payload
        loaded.append(row)
        expected_names.add(filename)
    if {path.name for path in images_dir.iterdir()} != expected_names:
        raise ValueError("bundle image member set mismatch")
    return loaded, producer_code_sha, hashlib.sha256(manifest_payload).hexdigest()


def _load_checkpoint_and_freeze(
    *,
    checkpoint: Path,
    expected_checkpoint_sha256: str,
    freeze: Path,
    expected_freeze_sha256: str,
) -> tuple[VerifiedCheckpoint, dict[str, object]]:
    if (
        not checkpoint.is_absolute()
        or not freeze.is_absolute()
        or _SHA256.fullmatch(expected_checkpoint_sha256) is None
        or _SHA256.fullmatch(expected_freeze_sha256) is None
    ):
        raise ValueError("checkpoint or freeze pin invalid")
    checkpoint_payload = _read_regular_bytes(checkpoint)
    checkpoint_sha = hashlib.sha256(checkpoint_payload).hexdigest()
    freeze_payload = _read_regular_bytes(freeze)
    if checkpoint_sha != expected_checkpoint_sha256:
        raise ValueError("checkpoint SHA mismatch")
    if hashlib.sha256(freeze_payload).hexdigest() != expected_freeze_sha256:
        raise ValueError("freeze SHA mismatch")
    value = _parse_json(freeze_payload, name="freeze")
    if (
        value.get("schema") != "yolo26n-v24b-postprocess-freeze-v1"
        or value.get("status")
        not in {
            "V24B_POSTPROCESS_FROZEN",
            "V24B_POSTPROCESS_FROZEN_DEVELOPMENT_ONLY",
        }
        or value.get("checkpoint_sha256") != checkpoint_sha
        or value.get("selected") != FROZEN_SELECTED
        or any(
            value.get(key) != 0
            for key in (
                "db_write_count",
                "r2_write_count",
                "service_write_count",
                "git_write_count",
            )
        )
    ):
        raise ValueError("freeze contract mismatch")
    return VerifiedCheckpoint(checkpoint_payload, checkpoint_sha), value


def current_runtime_versions() -> dict[str, str]:
    import cv2
    import numpy
    import PIL
    import torch
    import torchvision
    import ultralytics

    return {
        "python": sys.version.split()[0],
        "ultralytics": str(ultralytics.__version__),
        "torch": str(torch.__version__),
        "torchvision": str(torchvision.__version__),
        "numpy": str(numpy.__version__),
        "opencv": str(cv2.__version__),
        "pillow": str(PIL.__version__),
    }


def _default_model_factory(checkpoint: VerifiedCheckpoint) -> object:
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


def _valid_frame_metadata(row: Mapping[str, object]) -> bool:
    source = row.get("source_video_sha256")
    timestamp = row.get("timestamp_sec")
    return (
        row.get("role") == "owner-development-video"
        and isinstance(source, str)
        and _SHA256.fullmatch(source) is not None
        and type(row.get("frame_index")) is int
        and isinstance(timestamp, (int, float))
        and not isinstance(timestamp, bool)
        and math.isfinite(float(timestamp))
        and float(timestamp) >= 0
        and type(row.get("width")) is int
        and type(row.get("height")) is int
        and int(row["width"]) > 0
        and int(row["height"]) > 0
    )


def _result_predictions(result: object, row: Mapping[str, object]) -> list[dict[str, object]]:
    if tuple(getattr(result, "orig_shape", ())) != (row["height"], row["width"]):
        raise ValueError("prediction dimensions mismatch")
    path = str(getattr(result, "path", ""))
    if path and path != "image0.jpg":
        raise ValueError("prediction order mismatch")
    boxes = getattr(result, "boxes", None)
    if boxes is None or not hasattr(boxes, "xyxy") or not hasattr(boxes, "conf"):
        raise ValueError("prediction boxes missing")
    xyxy = boxes.xyxy.cpu().tolist()
    confidences = boxes.conf.cpu().tolist()
    if (
        not isinstance(xyxy, list)
        or not isinstance(confidences, list)
        or len(xyxy) != len(confidences)
        or len(xyxy) > INFERENCE_PARAMS["max_det"]
    ):
        raise ValueError("prediction tensors mismatch")
    predictions: list[dict[str, object]] = []
    for box, confidence in zip(xyxy, confidences, strict=True):
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError("prediction box mismatch")
        predictions.append(
            {
                "class_id": 0,
                "confidence": float(confidence),
                "box_xyxy": [float(value) for value in box],
            }
        )
    return predictions


def _infer_frames(
    rows: Sequence[Mapping[str, object]], model: object
) -> tuple[list[dict[str, object]], Counter[str]]:
    output: list[dict[str, object]] = []
    counts: Counter[str] = Counter()
    for raw in rows:
        row = dict(raw)
        if not _valid_frame_metadata(row):
            counts["result_invalid"] += 1
            continue
        payload = row.get("jpeg_bytes")
        if not isinstance(payload, bytes):
            counts["decode_failed"] += 1
            continue
        try:
            with Image.open(io.BytesIO(payload)) as decoded:
                decoded.load()
                image = decoded.convert("RGB")
            if image.size != (row["width"], row["height"]):
                raise ValueError("decoded dimensions mismatch")
        except (OSError, UnidentifiedImageError, ValueError):
            counts["decode_failed"] += 1
            continue
        try:
            results = model.predict(
                source=[image],
                conf=FROZEN_SELECTED["confidence"],
                iou=FROZEN_SELECTED["nms_iou"],
                imgsz=INFERENCE_PARAMS["imgsz"],
                max_det=INFERENCE_PARAMS["max_det"],
                device="mps",
                verbose=False,
                stream=False,
                save=False,
            )
        except Exception:
            counts["inference_failed"] += 1
            image.close()
            continue
        image.close()
        try:
            if (
                not isinstance(results, Sequence)
                or isinstance(results, (str, bytes))
                or len(results) != 1
            ):
                raise ValueError("prediction result count mismatch")
            row["predictions"] = _result_predictions(results[0], row)
            output.append(row)
        except (AttributeError, TypeError, ValueError, OverflowError):
            counts["result_invalid"] += 1
    return output, counts


def _canonical_jpeg(payload: bytes) -> tuple[bytes, int, int]:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            rgb = image.convert("RGB")
    except (OSError, UnidentifiedImageError):
        raise ValueError("blind JPEG decode failed") from None
    output = io.BytesIO()
    rgb.save(
        output,
        format="JPEG",
        quality=95,
        subsampling=0,
        optimize=False,
        progressive=False,
        exif=b"",
    )
    rgb.close()
    canonical = output.getvalue()
    with Image.open(io.BytesIO(canonical)) as verified:
        verified.load()
        if (
            verified.format != "JPEG"
            or verified.info != BLIND_JPEG_INFO
            or len(verified.getexif()) != 0
        ):
            raise ValueError("blind JPEG metadata strip failed")
        width, height = verified.size
    return canonical, width, height


def _dhash64(payload: bytes) -> str:
    with Image.open(io.BytesIO(payload)) as image:
        grayscale = image.convert("RGB").convert("L").resize((9, 8), Image.Resampling.BOX)
        pixels = list(grayscale.get_flattened_data())
    bits = 0
    for row in range(8):
        for column in range(8):
            bits = (bits << 1) | int(
                pixels[row * 9 + column + 1] > pixels[row * 9 + column]
            )
    return f"{bits:016x}"


def _write_new(path: Path, payload: bytes) -> None:
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


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return bool(set(value) & _FORBIDDEN_PUBLIC_KEYS) or any(
            _contains_forbidden_key(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(child) for child in value)
    return False


def _build_queue(selected: Sequence[Mapping[str, object]], queue_dir: Path) -> str:
    queue_dir.mkdir(mode=0o700)
    cvat = queue_dir / "cvat"
    images = cvat / "images"
    cvat.mkdir(mode=0o700)
    images.mkdir(mode=0o700)
    public_records: list[dict[str, object]] = []
    private_records: list[dict[str, object]] = []
    coco_images: list[dict[str, object]] = []
    members: dict[str, bytes] = {}
    for index, raw in enumerate(selected, start=1):
        row = dict(raw)
        payload, width, height = _canonical_jpeg(row["jpeg_bytes"])
        image_sha = hashlib.sha256(payload).hexdigest()
        sequence = f"V25{index:04d}"
        filename = f"{sequence}.jpg"
        _write_new(images / filename, payload)
        members[f"images/{filename}"] = payload
        public_records.append(
            {
                "sequence": sequence,
                "filename": filename,
                "image_sha256": image_sha,
                "width": width,
                "height": height,
                "annotation_policy": "human-blind-empty-frame-allowed",
            }
        )
        coco_images.append(
            {
                "id": index,
                "file_name": f"images/{filename}",
                "width": width,
                "height": height,
            }
        )
        private = {key: value for key, value in row.items() if key != "jpeg_bytes"}
        private["bundle_image_sha256"] = private["image_sha256"]
        private["image_sha256"] = image_sha
        private["dhash64"] = _dhash64(payload)
        private["width"] = width
        private["height"] = height
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
    if _contains_forbidden_key(manifest) or _contains_forbidden_key(coco):
        raise ValueError("blind public metadata leak")
    members["queue-manifest.json"] = _json_bytes(manifest)
    members["annotations.coco.json"] = _json_bytes(coco)
    members["BBOX-RULES.md"] = BBOX_RULES_BYTES
    for name in ("queue-manifest.json", "annotations.coco.json", "BBOX-RULES.md"):
        _write_new(cvat / name, members[name])
    _write_new(queue_dir / "cvat-upload.zip", _zip_bytes(members))
    _write_new(
        queue_dir / "review-index.private.json",
        _json_bytes(
            {
                "schema": "yolo26n-v25-blind-review-index-v1",
                "status": "V25_BLIND_QUEUE_READY",
                "queue_count": len(private_records),
                "records": private_records,
                "db_write_count": 0,
                "r2_write_count": 0,
                "service_write_count": 0,
            }
        ),
    )
    _write_new(
        queue_dir / "build.started.private.json",
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
    return directory_contract_sha256(queue_dir)


def _default_validator(
    *,
    queue_dir: Path,
    expected_queue_sha256: str,
    acceptance_output: Path,
    started_output: Path,
) -> dict[str, object]:
    try:
        from scripts.validate_yolo26n_v25_blind_queue import validate_blind_queue
    except ModuleNotFoundError:  # pragma: no cover - direct script execution
        from validate_yolo26n_v25_blind_queue import validate_blind_queue
    return validate_blind_queue(
        queue_dir=queue_dir,
        expected_queue_sha256=expected_queue_sha256,
        acceptance_output=acceptance_output,
        started_output=started_output,
    )


def run_minimal_owner_inference(
    *,
    bundle_dir: Path,
    expected_bundle_sha256: str,
    checkpoint: Path,
    expected_checkpoint_sha256: str,
    freeze: Path,
    expected_freeze_sha256: str,
    output_root: Path,
    model_factory: Callable[[VerifiedCheckpoint], object] = _default_model_factory,
    runtime_probe: Callable[[], Mapping[str, str]] = current_runtime_versions,
    validator: Callable[..., dict[str, object]] = _default_validator,
) -> dict[str, object]:
    if not output_root.is_absolute():
        raise ValueError("output root must be absolute")
    if output_root.exists() or output_root.is_symlink():
        raise FileExistsError(output_root)
    rows, producer_code_sha, bundle_manifest_sha = _load_bundle(
        bundle_dir, expected_bundle_sha256
    )
    capability, _freeze_value = _load_checkpoint_and_freeze(
        checkpoint=checkpoint,
        expected_checkpoint_sha256=expected_checkpoint_sha256,
        freeze=freeze,
        expected_freeze_sha256=expected_freeze_sha256,
    )
    runtime_versions = dict(runtime_probe())
    model = model_factory(capability)
    inferred, exclusion_counts = _infer_frames(rows, model)
    classified = classify_hardcase_signals(inferred)
    selected = select_blind_queue(classified, per_source_cap=6, total_cap=210)
    if not selected:
        return {
            "status": "V25_HARDCASE_QUEUE_SHORTAGE",
            "input_count": len(rows),
            "surviving_count": len(classified),
            "selected_count": 0,
            "exclusion_counts": dict(exclusion_counts),
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
        }

    output_root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(output_root.parent, 0o700)
    output_root.mkdir(mode=0o700)
    queue_dir = output_root / "blind-queue"
    queue_sha = _build_queue(selected, queue_dir)
    counts = {
        "input": len(rows),
        "surviving": len(classified),
        "selected": len(selected),
        "decode_failed": exclusion_counts["decode_failed"],
        "inference_failed": exclusion_counts["inference_failed"],
        "result_invalid": exclusion_counts["result_invalid"],
    }
    inference_code_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    ledger = {
        "schema": "yolo26n-v25-owner-minimal-inference-ledger-v1",
        "status": "V25_BLIND_QUEUE_READY",
        "role": "owner-development-video",
        "policy_id": POLICY_ID,
        "policy_seed": POLICY_SEED,
        "bundle_sha256": expected_bundle_sha256,
        "bundle_manifest_sha256": bundle_manifest_sha,
        "checkpoint_sha256": expected_checkpoint_sha256,
        "freeze_sha256": expected_freeze_sha256,
        "producer_code_sha256": producer_code_sha,
        "inference_code_sha256": inference_code_sha,
        "producer_inference_code_equal": producer_code_sha == inference_code_sha,
        "postprocess_selected": FROZEN_SELECTED,
        "inference_params": INFERENCE_PARAMS,
        "runtime_versions": runtime_versions,
        "counts": counts,
        "source_video_count": len(
            {str(row["source_video_sha256"]) for row in selected}
        ),
        "queue_sha256": queue_sha,
        "gate_policy": "quarantine_all",
        "gate_candidate_count": 0,
        "gate_inputs_consumed": False,
        "protected_access_count": 0,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "production_model_write_count": 0,
        "gme_write_count": 0,
        "labeling_web_write_count": 0,
        "deploy_count": 0,
    }
    _write_new(output_root / "provenance-ledger.private.json", _json_bytes(ledger))
    acceptance = validator(
        queue_dir=queue_dir,
        expected_queue_sha256=queue_sha,
        acceptance_output=output_root / "acceptance.private.json",
        started_output=output_root / "acceptance.started.private.json",
    )
    if acceptance.get("status") != "V25_BLIND_QUEUE_ACCEPTED":
        raise ValueError("blind queue independent acceptance failed")
    return {
        "status": "V25_BLIND_CVAT_QUEUE_READY",
        "input_count": len(rows),
        "surviving_count": len(classified),
        "selected_count": len(selected),
        "source_video_count": ledger["source_video_count"],
        "queue_sha256": queue_sha,
        "zip_sha256": acceptance["zip_sha256"],
        "provenance_ledger_sha256": hashlib.sha256(
            (output_root / "provenance-ledger.private.json").read_bytes()
        ).hexdigest(),
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run minimal frozen v2.4 inference for the Owner-280 bundle."
    )
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--expected-bundle-sha256", required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--expected-checkpoint-sha256", required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--expected-freeze-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_minimal_owner_inference(
        bundle_dir=args.bundle_dir,
        expected_bundle_sha256=args.expected_bundle_sha256,
        checkpoint=args.checkpoint,
        expected_checkpoint_sha256=args.expected_checkpoint_sha256,
        freeze=args.freeze,
        expected_freeze_sha256=args.expected_freeze_sha256,
        output_root=args.output_root,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "V25_BLIND_CVAT_QUEUE_READY" else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

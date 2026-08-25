"""Independently validate the anonymous YOLO v2.5 blind bbox queue."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import stat
import zipfile
from collections.abc import Mapping
from pathlib import Path

from PIL import Image, UnidentifiedImageError

try:
    from scripts import build_yolo26n_v25_owner_hardcase_queue as builder
    from scripts.run_yolo26n_v24b_postprocess import (
        _cleanup_if_self_owned,
        _write_private_bytes_new as _secure_write_private_bytes_new,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import build_yolo26n_v25_owner_hardcase_queue as builder  # type: ignore[no-redef]
    from run_yolo26n_v24b_postprocess import (  # type: ignore[no-redef]
        _cleanup_if_self_owned,
        _write_private_bytes_new as _secure_write_private_bytes_new,
    )


_PUBLIC_FORBIDDEN_KEYS = {
    "predictions",
    "confidence",
    "signals",
    "source_video_sha256",
    "source_path",
    "frame_index",
    "timestamp_sec",
    "dhash64",
    "selection_reasons",
}


def _strict_json(payload: bytes, *, name: str) -> dict[str, object]:
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


def _read_private_bytes(path: Path) -> bytes:
    return builder._read_private_snapshot(path).payload


def _assert_private_tree(root: Path) -> None:
    if root.is_symlink() or not root.is_dir() or stat.S_IMODE(root.lstat().st_mode) != 0o700:
        raise ValueError("queue directory contract mismatch")
    for path in root.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("queue symlink forbidden")
        if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
            raise ValueError("queue child must be a regular file or directory")
        expected = 0o700 if stat.S_ISDIR(metadata.st_mode) else 0o600
        if stat.S_IMODE(metadata.st_mode) != expected:
            raise ValueError("queue mode contract mismatch")


def _has_forbidden_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return bool(set(value) & _PUBLIC_FORBIDDEN_KEYS) or any(
            _has_forbidden_key(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(_has_forbidden_key(child) for child in value)
    return False


def validate_blind_queue(
    *,
    queue_dir: Path,
    expected_queue_sha256: str,
    acceptance_output: Path,
    started_output: Path,
) -> dict[str, object]:
    if (
        not queue_dir.is_absolute()
        or not acceptance_output.is_absolute()
        or not started_output.is_absolute()
        or len(expected_queue_sha256) != 64
    ):
        raise ValueError("blind queue validation pin mismatch")
    lock_payload = (
        json.dumps(
            {
                "schema": "yolo26n-v25-blind-queue-acceptance-lock-v1",
                "status": "STARTED",
                "queue_sha256": expected_queue_sha256,
                "final_output": str(acceptance_output),
                "db_write_count": 0,
                "r2_write_count": 0,
                "service_write_count": 0,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    lock = _secure_write_private_bytes_new(started_output, lock_payload)
    if lock.sha256 != hashlib.sha256(lock_payload).hexdigest():
        raise ValueError("acceptance lock publication mismatch")
    _assert_private_tree(queue_dir)
    initial_identity = builder.directory_identity_snapshot(queue_dir)
    if builder.directory_contract_sha256(queue_dir) != expected_queue_sha256:
        raise ValueError("blind queue raw SHA mismatch")
    if {path.name for path in queue_dir.iterdir()} != {
        "build.started.private.json",
        "cvat",
        "cvat-upload.zip",
        "review-index.private.json",
    }:
        raise ValueError("blind queue root member mismatch")
    cvat = queue_dir / "cvat"
    if {path.name for path in cvat.iterdir()} != {
        "images",
        "annotations.coco.json",
        "BBOX-RULES.md",
        "queue-manifest.json",
    }:
        raise ValueError("public queue member mismatch")

    manifest_bytes = _read_private_bytes(cvat / "queue-manifest.json")
    manifest = _strict_json(manifest_bytes, name="public queue manifest")
    records = manifest.get("records")
    if (
        set(manifest)
        != {
            "schema",
            "status",
            "queue_count",
            "records",
            "prediction_visible",
            "empty_frame_allowed",
        }
        or manifest.get("schema") != "yolo26n-v25-blind-queue-manifest-v1"
        or manifest.get("status") != "V25_BLIND_QUEUE_READY"
        or manifest.get("prediction_visible") is not False
        or manifest.get("empty_frame_allowed") is not True
        or not isinstance(records, list)
        or manifest.get("queue_count") != len(records)
        or len(records) < 1
        or _has_forbidden_key(manifest)
    ):
        raise ValueError("public queue manifest contract mismatch")

    images_dir = cvat / "images"
    expected_names: set[str] = set()
    image_contract: list[tuple[str, str, int, int]] = []
    for index, row in enumerate(records, start=1):
        if not isinstance(row, Mapping) or set(row) != {
            "sequence",
            "filename",
            "image_sha256",
            "width",
            "height",
            "annotation_policy",
        }:
            raise ValueError("public queue record contract mismatch")
        sequence = f"V25{index:04d}"
        filename = f"{sequence}.jpg"
        if (
            row.get("sequence") != sequence
            or row.get("filename") != filename
            or row.get("annotation_policy")
            != "human-blind-empty-frame-allowed"
            or type(row.get("width")) is not int
            or type(row.get("height")) is not int
        ):
            raise ValueError("public queue record contract mismatch")
        payload = _read_private_bytes(images_dir / filename)
        image_sha = hashlib.sha256(payload).hexdigest()
        if row.get("image_sha256") != image_sha:
            raise ValueError("public queue image SHA mismatch")
        try:
            with Image.open(io.BytesIO(payload)) as image:
                image.load()
                size = image.size
                if (
                    image.format != "JPEG"
                    or image.info != builder.BLIND_JPEG_INFO
                    or len(image.getexif()) != 0
                ):
                    raise ValueError(
                        "public queue JPEG format or metadata contract mismatch"
                    )
        except (OSError, UnidentifiedImageError):
            raise ValueError("public queue image decode failed") from None
        if size != (row["width"], row["height"]):
            raise ValueError("public queue image dimensions mismatch")
        expected_names.add(filename)
        image_contract.append((sequence, image_sha, row["width"], row["height"]))
    if {path.name for path in images_dir.iterdir()} != expected_names:
        raise ValueError("public queue image set mismatch")

    coco_bytes = _read_private_bytes(cvat / "annotations.coco.json")
    coco = _strict_json(coco_bytes, name="public queue COCO")
    if (
        set(coco) != {"images", "annotations", "categories"}
        or coco.get("annotations") != []
        or coco.get("categories") != [{"id": 1, "name": "gecko"}]
        or not isinstance(coco.get("images"), list)
        or len(coco["images"]) != len(records)
        or _has_forbidden_key(coco)
    ):
        raise ValueError("public queue COCO contract mismatch")
    for index, (row, manifest_row) in enumerate(
        zip(coco["images"], records, strict=True), start=1
    ):
        if row != {
            "id": index,
            "file_name": f"images/{manifest_row['filename']}",
            "width": manifest_row["width"],
            "height": manifest_row["height"],
        }:
            raise ValueError("public queue COCO image mismatch")

    rules_bytes = _read_private_bytes(cvat / "BBOX-RULES.md")
    if rules_bytes != builder.BBOX_RULES_BYTES:
        raise ValueError("public bbox rules contract mismatch")

    review_bytes = _read_private_bytes(queue_dir / "review-index.private.json")
    review = _strict_json(review_bytes, name="private review index")
    private_records = review.get("records")
    if (
        review.get("schema") != "yolo26n-v25-blind-review-index-v1"
        or review.get("status") != "V25_BLIND_QUEUE_READY"
        or review.get("queue_count") != len(records)
        or not isinstance(private_records, list)
        or len(private_records) != len(records)
        or any(review.get(key) != 0 for key in ("db_write_count", "r2_write_count", "service_write_count"))
    ):
        raise ValueError("private review index contract mismatch")
    for public, private in zip(records, private_records, strict=True):
        if (
            not isinstance(private, Mapping)
            or private.get("sequence") != public["sequence"]
            or private.get("image_sha256") != public["image_sha256"]
            or not isinstance(private.get("predictions"), list)
            or not isinstance(private.get("signals"), list)
        ):
            raise ValueError("private review record cross-pin mismatch")

    member_bytes = {
        "queue-manifest.json": manifest_bytes,
        "annotations.coco.json": coco_bytes,
        "BBOX-RULES.md": rules_bytes,
        **{
            f"images/{name}": _read_private_bytes(images_dir / name)
            for name in sorted(expected_names)
        },
    }
    zip_payload = _read_private_bytes(queue_dir / "cvat-upload.zip")
    with zipfile.ZipFile(io.BytesIO(zip_payload)) as archive:
        if sorted(archive.namelist()) != sorted(member_bytes):
            raise ValueError("CVAT zip member set mismatch")
        for name, payload in member_bytes.items():
            if archive.read(name) != payload:
                raise ValueError("CVAT zip member bytes mismatch")

    if builder.directory_contract_sha256(queue_dir) != expected_queue_sha256:
        raise ValueError("blind queue changed during validation")
    if builder.directory_identity_snapshot(queue_dir) != initial_identity:
        raise ValueError("blind queue identity changed during validation")
    acceptance = {
        "schema": "yolo26n-v25-blind-queue-acceptance-v1",
        "status": "V25_BLIND_QUEUE_ACCEPTED",
        "queue_count": len(records),
        "queue_sha256": expected_queue_sha256,
        "zip_sha256": hashlib.sha256(zip_payload).hexdigest(),
        "image_contract_sha256": hashlib.sha256(
            json.dumps(image_contract, separators=(",", ":")).encode()
        ).hexdigest(),
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }
    payload = (
        json.dumps(acceptance, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    artifact = _secure_write_private_bytes_new(acceptance_output, payload)
    try:
        if artifact.sha256 != hashlib.sha256(payload).hexdigest():
            raise ValueError("acceptance publication mismatch")
        if builder.directory_contract_sha256(queue_dir) != expected_queue_sha256:
            raise ValueError("blind queue changed at acceptance boundary")
        if builder.directory_identity_snapshot(queue_dir) != initial_identity:
            raise ValueError("blind queue identity changed at acceptance boundary")
    except BaseException:
        _cleanup_if_self_owned(artifact)
        raise
    return acceptance


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Independently validate a YOLO v2.5 blind queue."
    )
    parser.add_argument("--queue-dir", type=Path, required=True)
    parser.add_argument("--expected-queue-sha256", required=True)
    parser.add_argument("--acceptance-output", type=Path, required=True)
    parser.add_argument("--started-output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    validate_blind_queue(
        queue_dir=args.queue_dir,
        expected_queue_sha256=args.expected_queue_sha256,
        acceptance_output=args.acceptance_output,
        started_output=args.started_output,
    )
    print("V25_BLIND_QUEUE_ACCEPTED")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

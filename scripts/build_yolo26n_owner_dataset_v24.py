"""Build a fail-closed YOLO v2.4 plan from v2.3 plus accepted Gate GT."""

from __future__ import annotations

import math
import ctypes
import errno
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

from PIL import Image, UnidentifiedImageError


PARENT_COUNTS = {"train": 889, "val": 153, "test": 151}
GATE_MINIMUMS = {"total": 300, "positive": 150, "negative": 100, "source_clip": 200}


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _strict_number(value: object) -> float:
    if isinstance(value, bool) or type(value) not in {int, float}:
        raise ValueError("Gate bbox malformed")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Gate bbox malformed")
    return number


def _yolo_label(
    boxes: Sequence[Sequence[object]], *, width: int, height: int
) -> str:
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError("Gate dimensions malformed")
    lines: list[str] = []
    for raw in boxes:
        if not isinstance(raw, list) or len(raw) != 4:
            raise ValueError("Gate bbox malformed")
        x, y, box_width, box_height = map(_strict_number, raw)
        if not (
            0 <= x < width
            and 0 <= y < height
            and box_width > 0
            and box_height > 0
            and x + box_width <= width
            and y + box_height <= height
        ):
            raise ValueError("Gate bbox malformed")
        lines.append(
            "0 "
            f"{(x + box_width / 2) / width:.9f} "
            f"{(y + box_height / 2) / height:.9f} "
            f"{box_width / width:.9f} "
            f"{box_height / height:.9f}"
        )
    return "\n".join(lines) + ("\n" if lines else "")


def build_v24_plan(
    *,
    base_records: Sequence[Mapping[str, object]],
    candidate_records: Sequence[Mapping[str, object]],
    audit_summary: Mapping[str, object],
) -> dict[str, object]:
    if audit_summary.get("status") not in {
        "V24_GATE_AUDIT_ACCEPTED",
        "V24_GATE_POSITIVE_FULL_REVIEW_ACCEPTED",
        "V24_GATE_NEGATIVE_FULL_REVIEW_ACCEPTED",
        "V24_GATE_POSITIVE_AND_NEGATIVE_FULL_REVIEW_ACCEPTED",
    }:
        raise PermissionError("Owner audit is not accepted")

    parent_counts = {split: 0 for split in PARENT_COUNTS}
    parent_shas: set[str] = set()
    parent_sequences: set[str] = set()
    for row in base_records:
        split = row.get("split")
        sequence = row.get("sequence")
        image_sha = row.get("image_sha256")
        box_count = row.get("box_count")
        positive = row.get("positive")
        if (
            split not in parent_counts
            or not isinstance(sequence, str)
            or not sequence
            or sequence in parent_sequences
            or row.get("image_path") != f"images/{split}/{sequence}.jpg"
            or row.get("label_path") != f"labels/{split}/{sequence}.txt"
            or not _is_sha256(image_sha)
            or image_sha in parent_shas
            or type(box_count) is not int
            or box_count < 0
            or type(positive) is not bool
            or positive != (box_count > 0)
            or not isinstance(row.get("source_dataset"), str)
        ):
            raise ValueError("parent dataset contract mismatch")
        parent_counts[str(split)] += 1
        parent_shas.add(str(image_sha))
        parent_sequences.add(sequence)
    if parent_counts != PARENT_COUNTS:
        raise ValueError("parent split count mismatch")

    candidate_shas: set[str] = set()
    candidate_paths: set[str] = set()
    clip_counts: Counter[str] = Counter()
    prepared: list[dict[str, object]] = []
    for row in candidate_records:
        source_path = row.get("source_relpath")
        source_clip = row.get("source_clip_ref")
        camera_night = row.get("camera_night_ref")
        image_sha = row.get("image_sha256")
        positive = row.get("positive")
        boxes = row.get("boxes_xywh")
        box_count = row.get("box_count")
        width = row.get("width")
        height = row.get("height")
        if (
            not isinstance(source_path, str)
            or not source_path.startswith("operational/")
            or source_path in candidate_paths
            or not isinstance(source_clip, str)
            or not source_clip
            or not isinstance(camera_night, str)
            or not camera_night
            or not _is_sha256(image_sha)
            or image_sha in candidate_shas
            or type(positive) is not bool
            or type(box_count) is not int
            or box_count < 0
            or not isinstance(boxes, list)
            or box_count != len(boxes)
            or positive != (box_count > 0)
        ):
            raise ValueError("Gate candidate contract mismatch")
        if image_sha in parent_shas:
            raise ValueError("Gate candidate overlaps parent dataset")
        label = _yolo_label(boxes, width=width, height=height)
        candidate_paths.add(source_path)
        candidate_shas.add(str(image_sha))
        clip_counts[source_clip] += 1
        prepared.append({**dict(row), "yolo_label": label})
    if clip_counts and max(clip_counts.values()) > 2:
        raise ValueError("Gate source clip cap exceeded")
    positive_count = sum(row["positive"] is True for row in prepared)
    negative_count = len(prepared) - positive_count
    if (
        len(prepared) < GATE_MINIMUMS["total"]
        or positive_count < GATE_MINIMUMS["positive"]
        or negative_count < GATE_MINIMUMS["negative"]
        or len(clip_counts) < GATE_MINIMUMS["source_clip"]
    ):
        raise ValueError("Gate candidate minimum not met")

    prepared.sort(key=lambda row: (str(row["source_clip_ref"]), str(row["image_sha256"])))
    gate_records = []
    for index, row in enumerate(prepared, 1):
        sequence = f"G{index:05d}"
        gate_records.append(
            {
                **row,
                "sequence": sequence,
                "split": "train",
                "image_path": f"images/train/{sequence}.jpg",
                "label_path": f"labels/train/{sequence}.txt",
                "source_dataset": "gate-operational-v24",
            }
        )
    v24_counts = dict(parent_counts)
    v24_counts["train"] += len(gate_records)
    return {
        "schema": "yolo26n-owner-dataset-v24-plan-v1",
        "status": "V24_MATERIALIZATION_REQUIRED",
        "parent_split_counts": parent_counts,
        "v24_split_counts": v24_counts,
        "gate_added_count": len(gate_records),
        "gate_positive_count": positive_count,
        "gate_negative_count": negative_count,
        "gate_source_clip_count": len(clip_counts),
        "gate_records": gate_records,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def _validate_yolo_label(payload: str, expected_count: int) -> None:
    lines = [line for line in payload.splitlines() if line]
    if type(expected_count) is not int or expected_count < 0 or len(lines) != expected_count:
        raise ValueError("YOLO label count mismatch")
    for line in lines:
        parts = line.split()
        if len(parts) != 5 or parts[0] != "0":
            raise ValueError("YOLO label malformed")
        coordinates = [float(value) for value in parts[1:]]
        if not all(math.isfinite(value) for value in coordinates):
            raise ValueError("YOLO label malformed")
        x, y, width, height = coordinates
        if not (
            0 <= x <= 1
            and 0 <= y <= 1
            and 0 < width <= 1
            and 0 < height <= 1
            and x - width / 2 >= -1e-6
            and y - height / 2 >= -1e-6
            and x + width / 2 <= 1 + 1e-6
            and y + height / 2 <= 1 + 1e-6
        ):
            raise ValueError("YOLO label malformed")


def _decode_size(payload: bytes) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(payload)) as image:
            image.load()
            return image.size
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError("dataset image decode failed") from error


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
    finally:
        os.close(descriptor)


def _rename_exclusive(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renamex = getattr(libc, "renamex_np", None)
    if renamex is None:
        if destination.exists():
            raise FileExistsError(destination)
        os.rename(source, destination)
        return
    renamex.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    renamex.restype = ctypes.c_int
    if renamex(os.fsencode(source), os.fsencode(destination), 0x00000004) != 0:
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(destination)
        raise OSError(error, os.strerror(error), destination)


def _validate_materialized(
    root: Path, records: Sequence[Mapping[str, object]]
) -> None:
    expected: set[Path] = set()
    seen_shas: set[str] = set()
    for record in records:
        image_relative = Path(str(record["image_path"]))
        label_relative = Path(str(record["label_path"]))
        image_payload = (root / image_relative).read_bytes()
        label_payload = (root / label_relative).read_text(encoding="utf-8")
        image_sha = hashlib.sha256(image_payload).hexdigest()
        if image_sha != record.get("image_sha256") or image_sha in seen_shas:
            raise ValueError("materialized image SHA mismatch")
        _decode_size(image_payload)
        _validate_yolo_label(label_payload, int(record["box_count"]))
        seen_shas.add(image_sha)
        expected.update({image_relative, label_relative})
    actual = {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".jpg", ".txt"}
    }
    if actual != expected:
        raise ValueError("materialized file set mismatch")


def materialize_v24_dataset(
    *,
    base_dataset: Path,
    base_manifest: Mapping[str, object],
    candidate_records: Sequence[Mapping[str, object]],
    audit_summary: Mapping[str, object],
    gate_image_root: Path,
    output_dir: Path,
) -> dict[str, object]:
    if output_dir.exists():
        raise FileExistsError(output_dir)
    if (
        base_manifest.get("schema") != "yolo26n-owner-dataset-v23"
        or base_manifest.get("split_counts") != PARENT_COUNTS
        or not isinstance(base_manifest.get("records"), list)
        or any(base_manifest.get(key) != 0 for key in ("db_write_count", "r2_write_count", "service_write_count"))
    ):
        raise ValueError("v2.3 parent manifest contract mismatch")
    plan = build_v24_plan(
        base_records=base_manifest["records"],
        candidate_records=candidate_records,
        audit_summary=audit_summary,
    )
    output_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.staging-", dir=output_dir.parent)
    )
    try:
        records: list[dict[str, object]] = []
        parent_val_test_digest = hashlib.sha256()
        for raw in base_manifest["records"]:
            record = dict(raw)
            image_relative = Path(str(record["image_path"]))
            label_relative = Path(str(record["label_path"]))
            image_payload = (base_dataset / image_relative).read_bytes()
            label_payload = (base_dataset / label_relative).read_bytes()
            if hashlib.sha256(image_payload).hexdigest() != record["image_sha256"]:
                raise ValueError("parent source bytes changed")
            _decode_size(image_payload)
            _validate_yolo_label(label_payload.decode("utf-8"), int(record["box_count"]))
            _write_new(staging / image_relative, image_payload)
            _write_new(staging / label_relative, label_payload)
            if record["split"] in {"val", "test"}:
                parent_val_test_digest.update(image_payload)
                parent_val_test_digest.update(label_payload)
            records.append(record)

        gate_root = gate_image_root.resolve()
        for planned in plan["gate_records"]:
            relative = PurePosixPath(str(planned["source_relpath"]))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Gate source path malformed")
            image_payload = gate_root.joinpath(*relative.parts).read_bytes()
            if hashlib.sha256(image_payload).hexdigest() != planned["image_sha256"]:
                raise ValueError("Gate source bytes changed")
            if _decode_size(image_payload) != (planned["width"], planned["height"]):
                raise ValueError("Gate source dimensions changed")
            image_relative = Path(str(planned["image_path"]))
            label_relative = Path(str(planned["label_path"]))
            label_payload = str(planned["yolo_label"]).encode("utf-8")
            _validate_yolo_label(label_payload.decode("utf-8"), int(planned["box_count"]))
            _write_new(staging / image_relative, image_payload)
            _write_new(staging / label_relative, label_payload)
            records.append(
                {
                    "sequence": planned["sequence"],
                    "split": "train",
                    "image_path": str(image_relative),
                    "label_path": str(label_relative),
                    "image_sha256": planned["image_sha256"],
                    "box_count": planned["box_count"],
                    "positive": planned["positive"],
                    "source_dataset": "gate-operational-v24",
                    "camera_night_group": planned["camera_night_ref"],
                    "final_holdout_eligible": False,
                }
            )

        split_counts = Counter(str(record["split"]) for record in records)
        box_counts = {
            split: sum(int(record["box_count"]) for record in records if record["split"] == split)
            for split in PARENT_COUNTS
        }
        positive_counts = {
            split: sum(record["positive"] is True for record in records if record["split"] == split)
            for split in PARENT_COUNTS
        }
        source_counts = Counter(str(record["source_dataset"]) for record in records)
        manifest = {
            **dict(base_manifest),
            "schema": "yolo26n-owner-dataset-v24",
            "image_count": len(records),
            "split_counts": dict(split_counts),
            "box_count": sum(box_counts.values()),
            "box_counts": box_counts,
            "positive_image_count": sum(positive_counts.values()),
            "positive_counts": positive_counts,
            "source_dataset_counts": dict(source_counts),
            "records": records,
            "gate_operational_added_count": plan["gate_added_count"],
            "parent_val_test_sha256": parent_val_test_digest.hexdigest(),
            "future_holdout_required": True,
            "evaluation_tier": "development",
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
        }
        _write_new(
            staging / "manifest.private.json",
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )
        _write_new(
            staging / "data.yaml",
            (
                f"path: {output_dir.resolve()}\n"
                "train: images/train\n"
                "val: images/val\n"
                "test: images/test\n"
                "names:\n"
                "  0: gecko\n"
            ).encode("utf-8"),
        )
        for path in staging.rglob("*"):
            os.chmod(path, 0o600 if path.is_file() else 0o700)
        os.chmod(staging, 0o700)
        _validate_materialized(staging, records)
        _rename_exclusive(staging, output_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "status": "V24_DATASET_READY",
        "image_count": len(records),
        "split_counts": dict(split_counts),
        "gate_added_count": plan["gate_added_count"],
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }

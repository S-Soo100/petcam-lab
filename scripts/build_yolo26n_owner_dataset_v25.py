"""Build the immutable YOLO26n v2.5 dataset plan from v2.4 + human hard cases."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

from scripts.build_yolo26n_owner_dataset_v24 import (
    _decode_size,
    _rename_exclusive,
    _validate_materialized,
    _validate_yolo_label,
    _write_new,
)


PARENT_SPLITS = {"train": 1458, "val": 153, "test": 151}
FINAL_SPLITS = {"train": 1659, "val": 153, "test": 151}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError("image SHA malformed")
    return value


def _strict_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} malformed")
    return value


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("bbox malformed")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("bbox malformed")
    return result


def _label(boxes: object, width: int, height: int) -> str:
    if not isinstance(boxes, list) or width <= 0 or height <= 0:
        raise ValueError("human snapshot malformed")
    lines = []
    for box in boxes:
        if (
            not isinstance(box, Mapping)
            or box.get("type") != "rectangle"
            or _strict_int(box.get("label_id"), "label id") != 0
            or not isinstance(box.get("points"), list)
            or len(box["points"]) != 4
        ):
            raise ValueError("bbox malformed")
        x1, y1, x2, y2 = map(_number, box["points"])
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ValueError("bbox malformed")
        lines.append(
            "0 "
            f"{((x1 + x2) / 2) / width:.9f} "
            f"{((y1 + y2) / 2) / height:.9f} "
            f"{(x2 - x1) / width:.9f} "
            f"{(y2 - y1) / height:.9f}"
        )
    return "\n".join(lines) + ("\n" if lines else "")


def build_v25_plan(
    parent_records: Sequence[Mapping[str, object]],
    human_snapshot: Mapping[str, object],
) -> dict[str, object]:
    parent_counts: Counter[str] = Counter()
    parent_shas: set[str] = set()
    parent_sequences: set[str] = set()
    for row in parent_records:
        split = row.get("split")
        sequence = row.get("sequence")
        image_sha = _sha(row.get("image_sha256"))
        box_count = _strict_int(row.get("box_count"), "parent box count")
        if (
            split not in PARENT_SPLITS
            or not isinstance(sequence, str)
            or not sequence
            or sequence in parent_sequences
            or row.get("image_path") != f"images/{split}/{sequence}.jpg"
            or row.get("label_path") != f"labels/{split}/{sequence}.txt"
            or image_sha in parent_shas
            or box_count < 0
            or type(row.get("positive")) is not bool
            or row.get("positive") != (box_count > 0)
        ):
            raise ValueError("v2.4 parent contract mismatch")
        parent_counts[str(split)] += 1
        parent_shas.add(image_sha)
        parent_sequences.add(sequence)
    if dict(parent_counts) != PARENT_SPLITS:
        raise ValueError("v2.4 parent split mismatch")

    images = human_snapshot.get("images")
    if (
        human_snapshot.get("schema") != "yolo26n-v25-human-snapshot-v1"
        or human_snapshot.get("status") != "V25_HUMAN_EXPORT_ACCEPTED"
        or _strict_int(human_snapshot.get("frame_count"), "frame count") != 201
        or _strict_int(human_snapshot.get("positive_frame_count"), "positive count") != 198
        or _strict_int(human_snapshot.get("negative_frame_count"), "negative count") != 3
        or _strict_int(human_snapshot.get("box_count"), "box count") != 219
        or not isinstance(images, list)
        or len(images) != 201
    ):
        raise ValueError("human snapshot aggregate mismatch")
    hardcase_records: list[dict[str, object]] = []
    hardcase_shas: set[str] = set()
    actual_boxes = 0
    actual_positive = 0
    for ordinal, image in enumerate(images, start=1):
        if not isinstance(image, Mapping):
            raise ValueError("human image record malformed")
        sequence = f"V25{ordinal:04d}"
        image_sha = _sha(image.get("image_sha256"))
        if sequence in parent_sequences or image_sha in parent_shas or image_sha in hardcase_shas:
            raise ValueError("hard-case overlaps existing data")
        if image.get("sequence") != sequence or image.get("filename") != f"{sequence}.jpg":
            raise ValueError("human image order mismatch")
        width = _strict_int(image.get("width"), "width")
        height = _strict_int(image.get("height"), "height")
        yolo_label = _label(image.get("boxes"), width, height)
        box_count = len(image["boxes"])
        actual_boxes += box_count
        actual_positive += box_count > 0
        hardcase_shas.add(image_sha)
        hardcase_records.append(
            {
                "sequence": sequence,
                "split": "train",
                "image_path": f"images/train/{sequence}.jpg",
                "label_path": f"labels/train/{sequence}.txt",
                "image_sha256": image_sha,
                "width": width,
                "height": height,
                "box_count": box_count,
                "positive": box_count > 0,
                "source_dataset": "owner-hardcase-v25",
                "yolo_label": yolo_label,
                "source_filename": image["filename"],
            }
        )
    if actual_boxes != 219 or actual_positive != 198:
        raise ValueError("human image aggregate mismatch")
    return {
        "schema": "yolo26n-owner-dataset-v25-plan-v1",
        "status": "V25_MATERIALIZATION_REQUIRED",
        "parent_split_counts": dict(parent_counts),
        "split_counts": FINAL_SPLITS,
        "image_count": sum(FINAL_SPLITS.values()),
        "hardcase_added_count": 201,
        "hardcase_positive_count": 198,
        "hardcase_negative_count": 3,
        "hardcase_box_count": 219,
        "hardcase_records": hardcase_records,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "deploy_count": 0,
    }


def materialize_v25_dataset(
    *,
    parent_dataset: Path,
    parent_manifest: Mapping[str, object],
    human_snapshot: Mapping[str, object],
    queue_images: Path,
    output_dir: Path,
    parent_manifest_sha256: str,
    human_snapshot_sha256: str,
    queue_manifest_sha256: str,
) -> dict[str, object]:
    if output_dir.exists():
        raise FileExistsError(output_dir)
    records = parent_manifest.get("records")
    if (
        parent_manifest.get("schema") != "yolo26n-owner-dataset-v24"
        or parent_manifest.get("split_counts") != PARENT_SPLITS
        or parent_manifest.get("image_count") != sum(PARENT_SPLITS.values())
        or not isinstance(records, list)
        or any(parent_manifest.get(key) != 0 for key in ("db_write_count", "r2_write_count", "service_write_count"))
    ):
        raise ValueError("v2.4 parent manifest mismatch")
    for value in (parent_manifest_sha256, human_snapshot_sha256, queue_manifest_sha256):
        _sha(value)
    plan = build_v25_plan(records, human_snapshot)
    output_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.staging-", dir=output_dir.parent))
    materialized: list[dict[str, object]] = []
    try:
        val_test_digest = hashlib.sha256()
        for raw in records:
            record = dict(raw)
            image_relative = Path(str(record["image_path"]))
            label_relative = Path(str(record["label_path"]))
            image_payload = (parent_dataset / image_relative).read_bytes()
            label_payload = (parent_dataset / label_relative).read_bytes()
            if hashlib.sha256(image_payload).hexdigest() != record["image_sha256"]:
                raise ValueError("parent source bytes changed")
            _decode_size(image_payload)
            _validate_yolo_label(label_payload.decode("utf-8"), int(record["box_count"]))
            _write_new(staging / image_relative, image_payload)
            _write_new(staging / label_relative, label_payload)
            if record["split"] in {"val", "test"}:
                val_test_digest.update(image_payload)
                val_test_digest.update(label_payload)
            materialized.append(record)

        for planned in plan["hardcase_records"]:
            source = queue_images / str(planned["source_filename"])
            image_payload = source.read_bytes()
            if hashlib.sha256(image_payload).hexdigest() != planned["image_sha256"]:
                raise ValueError("hard-case source bytes changed")
            if _decode_size(image_payload) != (planned["width"], planned["height"]):
                raise ValueError("hard-case dimensions changed")
            image_relative = Path(str(planned["image_path"]))
            label_relative = Path(str(planned["label_path"]))
            label_payload = str(planned["yolo_label"]).encode()
            _validate_yolo_label(label_payload.decode(), int(planned["box_count"]))
            _write_new(staging / image_relative, image_payload)
            _write_new(staging / label_relative, label_payload)
            materialized.append(
                {
                    "sequence": planned["sequence"],
                    "split": "train",
                    "image_path": str(image_relative),
                    "label_path": str(label_relative),
                    "image_sha256": planned["image_sha256"],
                    "box_count": planned["box_count"],
                    "positive": planned["positive"],
                    "source_dataset": "owner-hardcase-v25",
                    "final_holdout_eligible": False,
                }
            )

        split_counts = dict(Counter(str(row["split"]) for row in materialized))
        if split_counts != FINAL_SPLITS:
            raise ValueError("materialized split count mismatch")
        manifest = {
            "schema": "yolo26n-owner-dataset-v25",
            "status": "V25_DATASET_READY",
            "evaluation_tier": "development",
            "future_holdout_required": True,
            "image_count": len(materialized),
            "split_counts": split_counts,
            "hardcase_added_count": 201,
            "hardcase_positive_count": 198,
            "hardcase_negative_count": 3,
            "hardcase_box_count": 219,
            "parent_val_test_sha256": val_test_digest.hexdigest(),
            "input_sha256": {
                "parent_manifest": parent_manifest_sha256,
                "human_snapshot": human_snapshot_sha256,
                "queue_manifest": queue_manifest_sha256,
            },
            "hardcase_dedup_provenance": {
                "policy": "inherited_from_frozen_owner_280_queue",
                "exact_sha_overlap_rechecked": True,
                "dhash_distance_le_2_recheck": "inherited_via_queue_manifest_sha256",
            },
            "records": materialized,
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
            "deploy_count": 0,
        }
        _write_new(staging / "manifest.private.json", json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())
        _write_new(
            staging / "data.yaml",
            (f"path: {output_dir.resolve()}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: gecko\n").encode(),
        )
        for path in staging.rglob("*"):
            os.chmod(path, 0o600 if path.is_file() else 0o700)
        _validate_materialized(staging, materialized)
        _rename_exclusive(staging, output_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"status": "V25_DATASET_READY", "image_count": 1963, "split_counts": FINAL_SPLITS}


def _load_json(path: Path) -> tuple[dict[str, object], str]:
    payload = path.read_bytes()
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be object")
    return value, hashlib.sha256(payload).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-dataset", type=Path, required=True)
    parser.add_argument("--human-snapshot", type=Path, required=True)
    parser.add_argument("--queue-manifest", type=Path, required=True)
    parser.add_argument("--queue-images", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    parent, parent_sha = _load_json(args.parent_dataset / "manifest.private.json")
    snapshot, snapshot_sha = _load_json(args.human_snapshot)
    _, queue_sha = _load_json(args.queue_manifest)
    result = materialize_v25_dataset(
        parent_dataset=args.parent_dataset,
        parent_manifest=parent,
        human_snapshot=snapshot,
        queue_images=args.queue_images,
        output_dir=args.output,
        parent_manifest_sha256=parent_sha,
        human_snapshot_sha256=snapshot_sha,
        queue_manifest_sha256=queue_sha,
    )
    print(result["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.freeze_yolo26n_v25_parent_integrity import (
    build_parent_integrity_manifest,
    canonical_sha256,
)


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "parent"
    records: list[dict[str, object]] = []
    val_test = hashlib.sha256()
    for index, split in enumerate(("train", "val", "test"), start=1):
        image = root / "images" / split / f"sample-{index}.jpg"
        label = root / "labels" / split / f"sample-{index}.txt"
        image.parent.mkdir(parents=True, exist_ok=True)
        label.parent.mkdir(parents=True, exist_ok=True)
        image_payload = f"image-{index}".encode()
        label_payload = b"0 0.5 0.5 0.2 0.2\n" if split != "test" else b""
        image.write_bytes(image_payload)
        label.write_bytes(label_payload)
        if split in {"val", "test"}:
            val_test.update(image_payload)
            val_test.update(label_payload)
        records.append(
            {
                "sequence": f"S{index}",
                "split": split,
                "image_path": str(image.relative_to(root)),
                "label_path": str(label.relative_to(root)),
                "image_sha256": hashlib.sha256(image_payload).hexdigest(),
                "box_count": 0 if split == "test" else 1,
            }
        )
    manifest = {
        "schema": "yolo26n-owner-dataset-v25",
        "status": "V25_DATASET_READY",
        "image_count": 3,
        "split_counts": {"train": 1, "val": 1, "test": 1},
        "parent_val_test_sha256": val_test.hexdigest(),
        "records": records,
    }
    (root / "manifest.private.json").write_text(json.dumps(manifest))
    return root, manifest


def test_builds_approved_full_image_and_label_integrity_manifest(tmp_path: Path) -> None:
    root, parent = _fixture(tmp_path)
    frozen = build_parent_integrity_manifest(
        root,
        parent,
        expected_split_counts={"train": 1, "val": 1, "test": 1},
    )

    assert frozen["status"] == "V25_PARENT_INTEGRITY_APPROVED"
    assert frozen["parent_manifest_sha256"] == canonical_sha256(parent)
    assert frozen["image_count"] == 3
    assert frozen["records_sha256"] == canonical_sha256(frozen["records"])
    assert all(len(row["image_sha256"]) == 64 for row in frozen["records"])
    assert all(len(row["label_sha256"]) == 64 for row in frozen["records"])


@pytest.mark.parametrize("target", ("image", "label"))
def test_rejects_parent_byte_drift(tmp_path: Path, target: str) -> None:
    root, parent = _fixture(tmp_path)
    record = parent["records"][0]
    path = root / record[f"{target}_path"]
    path.write_bytes(path.read_bytes() + b"drift")

    expected = "parent image.*drift" if target == "image" else "parent label"
    with pytest.raises(ValueError, match=expected):
        build_parent_integrity_manifest(
            root,
            parent,
            expected_split_counts={"train": 1, "val": 1, "test": 1},
        )


def test_rejects_path_escape_and_val_test_aggregate_drift(tmp_path: Path) -> None:
    root, parent = _fixture(tmp_path)
    escaped = json.loads(json.dumps(parent))
    escaped["records"][0]["label_path"] = "../outside.txt"
    with pytest.raises(ValueError, match="path"):
        build_parent_integrity_manifest(
            root,
            escaped,
            expected_split_counts={"train": 1, "val": 1, "test": 1},
        )

    broken = json.loads(json.dumps(parent))
    broken["parent_val_test_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="val/test"):
        build_parent_integrity_manifest(
            root,
            broken,
            expected_split_counts={"train": 1, "val": 1, "test": 1},
        )

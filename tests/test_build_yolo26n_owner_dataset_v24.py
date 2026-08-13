from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest

import scripts.build_yolo26n_owner_dataset_v24 as builder
from scripts.build_yolo26n_owner_dataset_v24 import (
    build_v24_plan,
    materialize_v24_dataset,
)


def _sha(index: int) -> str:
    return f"{index:064x}"[-64:]


def _base_records() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    index = 1
    for split, count in (("train", 889), ("val", 153), ("test", 151)):
        for _ in range(count):
            rows.append(
                {
                    "sequence": f"B{index:05d}",
                    "split": split,
                    "image_sha256": _sha(index),
                    "image_path": f"images/{split}/B{index:05d}.jpg",
                    "label_path": f"labels/{split}/B{index:05d}.txt",
                    "box_count": int(index % 3 != 0),
                    "positive": index % 3 != 0,
                    "source_dataset": "base-v23",
                }
            )
            index += 1
    return rows


def _candidates(count: int = 300) -> list[dict[str, object]]:
    return [
        {
            "source_relpath": f"operational/clip-{index:04d}/f000.jpg",
            "source_clip_ref": f"clip-{index:04d}",
            "camera_night_ref": f"night-{index % 20:02d}",
            "image_sha256": _sha(10_000 + index),
            "dhash64": f"{index:016x}",
            "positive": index <= 170,
            "box_count": int(index <= 170),
            "width": 100,
            "height": 80,
            "boxes_xywh": [[10.0, 20.0, 30.0, 20.0]] if index <= 170 else [],
        }
        for index in range(1, count + 1)
    ]


def test_v24_preserves_parent_val_test_and_adds_gate_only_to_train() -> None:
    plan = build_v24_plan(
        base_records=_base_records(),
        candidate_records=_candidates(),
        audit_summary={"status": "V24_GATE_AUDIT_ACCEPTED"},
    )

    assert plan["parent_split_counts"] == {"train": 889, "val": 153, "test": 151}
    assert plan["v24_split_counts"] == {"train": 1189, "val": 153, "test": 151}
    assert {row["split"] for row in plan["gate_records"]} == {"train"}
    assert plan["gate_added_count"] == 300
    assert plan["status"] == "V24_MATERIALIZATION_REQUIRED"
    assert plan["db_write_count"] == 0


def test_v24_rejects_unaccepted_audit_and_parent_overlap() -> None:
    with pytest.raises(PermissionError, match="Owner audit"):
        build_v24_plan(
            base_records=_base_records(),
            candidate_records=_candidates(),
            audit_summary={"status": "V24_GATE_POSITIVE_FULL_REVIEW_REQUIRED"},
        )

    candidates = _candidates()
    candidates[0]["image_sha256"] = _base_records()[0]["image_sha256"]
    with pytest.raises(ValueError, match="overlap"):
        build_v24_plan(
            base_records=_base_records(),
            candidate_records=candidates,
            audit_summary={"status": "V24_GATE_AUDIT_ACCEPTED"},
        )


def _jpeg(path: Path, color: tuple[int, int, int]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 12), color).save(path, format="JPEG", quality=95)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_materializer_preserves_parent_val_test_and_publishes_exclusively(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder, "PARENT_COUNTS", {"train": 1, "val": 1, "test": 1})
    monkeypatch.setattr(
        builder,
        "GATE_MINIMUMS",
        {"total": 3, "positive": 1, "negative": 1, "source_clip": 2},
    )
    base = tmp_path / "base"
    records: list[dict[str, object]] = []
    for index, split in enumerate(("train", "val", "test"), 1):
        sequence = f"B{index:05d}"
        image = base / f"images/{split}/{sequence}.jpg"
        image_sha = _jpeg(image, (index * 40, 0, 0))
        label = base / f"labels/{split}/{sequence}.txt"
        label.parent.mkdir(parents=True, exist_ok=True)
        label.write_text("0 0.500000000 0.500000000 0.500000000 0.500000000\n")
        records.append(
            {
                "sequence": sequence,
                "split": split,
                "image_path": f"images/{split}/{sequence}.jpg",
                "label_path": f"labels/{split}/{sequence}.txt",
                "image_sha256": image_sha,
                "box_count": 1,
                "positive": True,
                "source_dataset": "base-v23",
                "camera_night_group": f"base-night-{index}",
                "final_holdout_eligible": split != "train",
            }
        )
    base_manifest = {
        "schema": "yolo26n-owner-dataset-v23",
        "split_counts": {"train": 1, "val": 1, "test": 1},
        "records": records,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }
    gate = tmp_path / "gate"
    candidates: list[dict[str, object]] = []
    for index, positive in enumerate((True, False, True), 1):
        relative = f"operational/clip-{index}/f000.jpg"
        sha = _jpeg(gate / relative, (0, index * 40, 0))
        candidates.append(
            {
                "source_relpath": relative,
                "source_clip_ref": f"clip-{index}",
                "camera_night_ref": f"night-{index}",
                "image_sha256": sha,
                "positive": positive,
                "box_count": int(positive),
                "width": 16,
                "height": 12,
                "boxes_xywh": [[2.0, 2.0, 6.0, 6.0]] if positive else [],
            }
        )
    val_before = (base / "images/val/B00002.jpg").read_bytes()
    test_before = (base / "images/test/B00003.jpg").read_bytes()
    output = tmp_path / "v24"

    result = materialize_v24_dataset(
        base_dataset=base,
        base_manifest=base_manifest,
        candidate_records=candidates,
        audit_summary={"status": "V24_GATE_POSITIVE_FULL_REVIEW_ACCEPTED"},
        gate_image_root=gate,
        output_dir=output,
    )

    assert result["status"] == "V24_DATASET_READY"
    assert result["split_counts"] == {"train": 4, "val": 1, "test": 1}
    assert (output / "images/val/B00002.jpg").read_bytes() == val_before
    assert (output / "images/test/B00003.jpg").read_bytes() == test_before
    manifest = json.loads((output / "manifest.private.json").read_text())
    assert manifest["schema"] == "yolo26n-owner-dataset-v24"
    assert manifest["gate_operational_added_count"] == 3
    with pytest.raises(FileExistsError):
        materialize_v24_dataset(
            base_dataset=base,
            base_manifest=base_manifest,
            candidate_records=candidates,
            audit_summary={"status": "V24_GATE_POSITIVE_FULL_REVIEW_ACCEPTED"},
            gate_image_root=gate,
            output_dir=output,
        )


def test_materializer_rejects_changed_gate_bytes_without_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder, "PARENT_COUNTS", {"train": 0, "val": 0, "test": 0})
    monkeypatch.setattr(
        builder,
        "GATE_MINIMUMS",
        {"total": 1, "positive": 1, "negative": 0, "source_clip": 1},
    )
    base = tmp_path / "base"
    base.mkdir()
    gate = tmp_path / "gate"
    relative = "operational/clip-1/f000.jpg"
    original_sha = _jpeg(gate / relative, (1, 2, 3))
    candidate = {
        "source_relpath": relative,
        "source_clip_ref": "clip-1",
        "camera_night_ref": "night-1",
        "image_sha256": original_sha,
        "positive": True,
        "box_count": 1,
        "width": 16,
        "height": 12,
        "boxes_xywh": [[2.0, 2.0, 6.0, 6.0]],
    }
    _jpeg(gate / relative, (9, 9, 9))
    output = tmp_path / "v24"

    with pytest.raises(ValueError, match="changed"):
        materialize_v24_dataset(
            base_dataset=base,
            base_manifest={
                "schema": "yolo26n-owner-dataset-v23",
                "split_counts": {"train": 0, "val": 0, "test": 0},
                "records": [],
                "db_write_count": 0,
                "r2_write_count": 0,
                "service_write_count": 0,
            },
            candidate_records=[candidate],
            audit_summary={"status": "V24_GATE_POSITIVE_FULL_REVIEW_ACCEPTED"},
            gate_image_root=gate,
            output_dir=output,
        )
    assert not output.exists()

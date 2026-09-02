import hashlib
import json
from pathlib import Path

import pytest

from scripts.build_yolo26n_owner_dataset_v23 import (
    _rename_exclusive,
    _snapshot_rows_by_sequence,
    build_v23_plan,
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_plan_preserves_base_splits_and_adds_only_accepted_training_candidates(tmp_path: Path):
    base = [
        {"sequence": "B1", "split": "train", "image_sha256": "a" * 64},
        {"sequence": "B2", "split": "val", "image_sha256": "b" * 64},
        {"sequence": "B3", "split": "test", "image_sha256": "c" * 64},
    ]
    images = []
    review = []
    source = []
    for index in range(1, 241):
        sequence = f"O{index:04d}"
        partition = "external_diagnostic" if index <= 60 else "training_candidate"
        image_sha = f"{index:064x}"[-64:]
        images.append({
            "frame": index - 1, "path": f"images/{sequence}.jpg",
            "partition": partition, "width": 100, "height": 80,
            "image_sha256": image_sha,
            "boxes": [] if index % 2 else [{"id": index, "label_id": 1, "type": "rectangle", "rotation": 0.0, "points": [10, 10, 50, 50]}],
        })
        review.append((sequence, index in {160, 171, 209}))
        source.append({"sequence": sequence, "capture_day": f"2026-01-{(index % 28)+1:02d}"})

    plan = build_v23_plan(
        base_records=base,
        snapshot={"images": images},
        owner_review=dict(review),
        source_items=source,
    )

    assert plan["base_split_counts"] == {"train": 1, "val": 1, "test": 1}
    assert plan["v23_split_counts"] == {"train": 178, "val": 1, "test": 1}
    assert plan["owner_added_count"] == 177
    assert plan["owner_ambiguous_excluded_count"] == 3
    assert plan["external_diagnostic_excluded_count"] == 60
    assert all(row["split"] == "train" for row in plan["owner_records"])
    assert not {row["image_sha256"] for row in plan["owner_records"]} & {"a" * 64, "b" * 64, "c" * 64}


def test_plan_rejects_overlap_or_wrong_counts():
    base = [{"sequence": "B1", "split": "train", "image_sha256": "a" * 64}]
    snapshot = {"images": []}
    for index in range(240):
        snapshot["images"].append({
            "frame": index, "path": f"images/O{index+1:04d}.jpg",
            "partition": "external_diagnostic" if index < 60 else "training_candidate",
            "width": 100, "height": 80,
            "image_sha256": "a" * 64 if index == 60 else f"{index+1:064x}"[-64:],
            "boxes": [],
        })
    review = {f"O{index+1:04d}": index in {159, 170, 208} for index in range(240)}
    source = [{"sequence": f"O{index+1:04d}", "capture_day": "2026-01-01"} for index in range(240)]
    with pytest.raises(ValueError, match="overlap"):
        build_v23_plan(base_records=base, snapshot=snapshot, owner_review=review, source_items=source)


def test_snapshot_rows_are_indexed_from_the_frozen_path_not_a_missing_field():
    rows = [
        {
            "frame": 0,
            "path": "images/O0001.jpg",
            "partition": "external_diagnostic",
            "width": 100,
            "height": 80,
            "image_sha256": "a" * 64,
            "boxes": [],
        }
    ]

    indexed = _snapshot_rows_by_sequence(rows)

    assert indexed == {"O0001": rows[0]}
    with pytest.raises(ValueError, match="path"):
        _snapshot_rows_by_sequence([{**rows[0], "path": "images/not-an-owner-sequence.jpg"}])


def test_exclusive_publish_never_replaces_even_an_empty_destination(tmp_path: Path):
    source = tmp_path / "staging"
    destination = tmp_path / "final"
    source.mkdir()
    (source / "complete").write_text("yes")
    destination.mkdir()

    with pytest.raises(FileExistsError):
        _rename_exclusive(source, destination)

    assert source.is_dir()
    assert destination.is_dir()
    assert not (destination / "complete").exists()

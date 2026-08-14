from __future__ import annotations

import copy

import pytest

from scripts.build_yolo26n_owner_dataset_v25 import build_v25_plan


def _parent_records() -> list[dict[str, object]]:
    rows = []
    ordinal = 0
    for split, count in (("train", 1458), ("val", 153), ("test", 151)):
        for _ in range(count):
            ordinal += 1
            sequence = f"P{ordinal:05d}"
            rows.append(
                {
                    "sequence": sequence,
                    "split": split,
                    "image_path": f"images/{split}/{sequence}.jpg",
                    "label_path": f"labels/{split}/{sequence}.txt",
                    "image_sha256": f"{ordinal:064x}",
                    "box_count": 1,
                    "positive": True,
                    "source_dataset": "v24-parent",
                }
            )
    return rows


def _snapshot() -> dict[str, object]:
    images = []
    for ordinal in range(1, 202):
        boxes = [] if ordinal > 198 else [{"type": "rectangle", "label_id": 0, "points": [1.0, 2.0, 101.0, 202.0]}]
        if ordinal <= 21:
            boxes.append({"type": "rectangle", "label_id": 0, "points": [120.0, 20.0, 220.0, 220.0]})
        images.append(
            {
                "sequence": f"V25{ordinal:04d}",
                "filename": f"V25{ordinal:04d}.jpg",
                "image_sha256": f"{2000 + ordinal:064x}",
                "width": 960,
                "height": 720,
                "boxes": boxes,
            }
        )
    return {
        "schema": "yolo26n-v25-human-snapshot-v1",
        "status": "V25_HUMAN_EXPORT_ACCEPTED",
        "frame_count": 201,
        "positive_frame_count": 198,
        "negative_frame_count": 3,
        "box_count": 219,
        "images": images,
    }


def test_build_plan_is_append_only_and_train_only() -> None:
    snapshot = _snapshot()
    plan = build_v25_plan(_parent_records(), snapshot)
    assert plan["split_counts"] == {"train": 1659, "val": 153, "test": 151}
    assert plan["image_count"] == 1963
    assert len(plan["hardcase_records"]) == 201
    assert all(row["split"] == "train" for row in plan["hardcase_records"])
    assert plan["hardcase_negative_count"] == 3


def test_build_plan_rejects_parent_count_and_overlap() -> None:
    parent = _parent_records()
    with pytest.raises(ValueError):
        build_v25_plan(parent[:-1], _snapshot())

    snapshot = _snapshot()
    snapshot["images"][0]["image_sha256"] = parent[0]["image_sha256"]
    with pytest.raises(ValueError):
        build_v25_plan(parent, snapshot)


def test_build_plan_rejects_nonaccepted_or_wrong_aggregate() -> None:
    snapshot = _snapshot()
    snapshot["status"] = "REJECTED"
    with pytest.raises(ValueError):
        build_v25_plan(_parent_records(), snapshot)

    snapshot = _snapshot()
    snapshot["images"][-1]["boxes"] = [{"type": "rectangle", "label_id": 0, "points": [1, 1, 2, 2]}]
    with pytest.raises(ValueError):
        build_v25_plan(_parent_records(), snapshot)

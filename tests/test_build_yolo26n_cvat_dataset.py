import csv
import json
from pathlib import Path

from scripts.build_yolo26n_cvat_dataset import (
    build_dataset,
    choose_group_splits,
    normalize_bbox,
)


def test_normalize_bbox_converts_visible_rectangle_to_yolo_coordinates():
    assert normalize_bbox([10, 20, 50, 60], width=100, height=80) == (
        0.3,
        0.5,
        0.4,
        0.5,
    )


def test_choose_group_splits_never_splits_a_camera_night():
    records = [
        {"sequence": "B0001", "camera_night_group": "night-a", "box_count": 1},
        {"sequence": "B0002", "camera_night_group": "night-a", "box_count": 0},
        {"sequence": "B0003", "camera_night_group": "night-b", "box_count": 1},
        {"sequence": "B0004", "camera_night_group": "night-c", "box_count": 0},
        {"sequence": "B0005", "camera_night_group": "night-d", "box_count": 1},
        {"sequence": "B0006", "camera_night_group": "night-e", "box_count": 0},
    ]

    assignments = choose_group_splits(records, seed=26, trials=500)

    assert assignments["B0001"] == assignments["B0002"]
    assert set(assignments.values()) == {"train", "val", "test"}


def test_build_dataset_writes_empty_negative_label_and_positive_yolo_label(
    tmp_path: Path,
):
    images_dir = tmp_path / "source-images"
    images_dir.mkdir()
    (images_dir / "B0001.jpg").write_bytes(b"positive")
    (images_dir / "B0002.jpg").write_bytes(b"negative")

    snapshot = {
        "schema": "cvat-task160-owner-snapshot-v1",
        "task_id": 160,
        "job_id": 160,
        "images": [
            {
                "frame": 0,
                "path": "images/B0001.jpg",
                "width": 100,
                "height": 80,
                "boxes": [
                    {"points": [10, 20, 50, 60], "label_id": 1, "type": "rectangle"}
                ],
            },
            {
                "frame": 1,
                "path": "images/B0002.jpg",
                "width": 100,
                "height": 80,
                "boxes": [],
            },
        ],
    }
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    review_path = tmp_path / "review.csv"
    with review_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["sequence", "camera_night_group"],
        )
        writer.writeheader()
        writer.writerow({"sequence": "B0001", "camera_night_group": "night-a"})
        writer.writerow({"sequence": "B0002", "camera_night_group": "night-b"})

    output_dir = tmp_path / "dataset"
    manifest = build_dataset(
        snapshot_path=snapshot_path,
        review_csv_path=review_path,
        images_dir=images_dir,
        output_dir=output_dir,
        assignments={"B0001": "train", "B0002": "test"},
    )

    assert (output_dir / "labels/train/B0001.txt").read_text() == (
        "0 0.300000 0.500000 0.400000 0.500000\n"
    )
    assert (output_dir / "labels/test/B0002.txt").read_text() == ""
    assert (output_dir / "images/train/B0001.jpg").read_bytes() == b"positive"
    assert manifest["split_counts"] == {"train": 1, "val": 0, "test": 1}

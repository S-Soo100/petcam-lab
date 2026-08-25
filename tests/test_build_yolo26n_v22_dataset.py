import hashlib
import csv
import json
from pathlib import Path

import pytest

from scripts.build_yolo26n_v22_dataset import (
    BoundingBox,
    DatasetRecord,
    build_v22_dataset,
    load_v21_records,
    load_v22_reinforcement_records,
)


def _record(
    tmp_path: Path,
    sequence: str,
    *,
    camera_night: str,
    source_dataset: str = "base-v21",
    boxes: tuple[BoundingBox, ...] = (),
    content: bytes | None = None,
) -> DatasetRecord:
    image_path = tmp_path / f"{sequence}.jpg"
    image_bytes = content if content is not None else sequence.encode("ascii")
    image_path.write_bytes(image_bytes)
    return DatasetRecord(
        sequence=sequence,
        image_path=image_path,
        image_sha256=hashlib.sha256(image_bytes).hexdigest(),
        width=100,
        height=80,
        boxes=boxes,
        camera_night_group=camera_night,
        source_dataset=source_dataset,
        final_holdout_eligible=False,
    )


def _records(tmp_path: Path) -> tuple[list[DatasetRecord], list[DatasetRecord]]:
    positive = (BoundingBox(10, 20, 50, 60),)
    base = [
        _record(tmp_path, "B0001", camera_night="night-a", boxes=positive),
        _record(tmp_path, "B0002", camera_night="night-a"),
        _record(tmp_path, "B0003", camera_night="night-b", boxes=positive),
        _record(tmp_path, "B0004", camera_night="night-c"),
    ]
    reinforcement = [
        _record(
            tmp_path,
            "V0001",
            camera_night="night-d",
            source_dataset="reinforcement-v22",
            boxes=positive,
        ),
        _record(
            tmp_path,
            "V0002",
            camera_night="night-e",
            source_dataset="reinforcement-v22",
        ),
    ]
    return base, reinforcement


def test_v22_builder_never_places_one_camera_night_in_multiple_splits(
    tmp_path: Path,
):
    base, reinforcement = _records(tmp_path)

    manifest = build_v22_dataset(
        base_records=base,
        reinforcement_records=reinforcement,
        output_dir=tmp_path / "dataset",
        seed=26,
    )

    split_by_night: dict[str, set[str]] = {}
    for row in manifest["records"]:
        split_by_night.setdefault(row["camera_night_group"], set()).add(row["split"])
    assert all(len(splits) == 1 for splits in split_by_night.values())
    assert set(manifest["split_counts"]) == {"train", "val", "test"}


def test_v22_builder_writes_empty_negative_and_single_class_yolo_labels(
    tmp_path: Path,
):
    base, reinforcement = _records(tmp_path)
    output_dir = tmp_path / "dataset"

    manifest = build_v22_dataset(
        base_records=base,
        reinforcement_records=reinforcement,
        output_dir=output_dir,
        seed=26,
    )

    by_sequence = {row["sequence"]: row for row in manifest["records"]}
    positive = by_sequence["B0001"]
    negative = by_sequence["B0002"]
    assert (output_dir / positive["label_path"]).read_text() == (
        "0 0.300000 0.500000 0.400000 0.500000\n"
    )
    assert (output_dir / negative["label_path"]).read_text() == ""
    assert manifest["class_names"] == ["gecko"]


def test_v22_builder_rejects_duplicate_sha_even_with_different_sequences(
    tmp_path: Path,
):
    duplicate = b"same-image"
    base = [_record(tmp_path, "B0001", camera_night="night-a", content=duplicate)]
    reinforcement = [
        _record(
            tmp_path,
            "V0001",
            camera_night="night-b",
            source_dataset="reinforcement-v22",
            content=duplicate,
        )
    ]

    with pytest.raises(ValueError, match="duplicate image sha256"):
        build_v22_dataset(
            base_records=base,
            reinforcement_records=reinforcement,
            output_dir=tmp_path / "dataset",
        )

    assert not (tmp_path / "dataset").exists()


@pytest.mark.parametrize(
    "box",
    [
        BoundingBox(0, 0, 0, 10),
        BoundingBox(-1, 0, 10, 10),
        BoundingBox(0, 0, 101, 10),
    ],
)
def test_v22_builder_rejects_invalid_geometry_before_materialization(
    tmp_path: Path, box: BoundingBox
):
    records = [_record(tmp_path, "B0001", camera_night="night-a", boxes=(box,))]

    with pytest.raises(ValueError, match="bbox"):
        build_v22_dataset(
            base_records=records,
            reinforcement_records=[],
            output_dir=tmp_path / "dataset",
        )

    assert not (tmp_path / "dataset").exists()


def test_v22_builder_marks_reinforcement_as_development_only(tmp_path: Path):
    base, reinforcement = _records(tmp_path)

    manifest = build_v22_dataset(
        base_records=base,
        reinforcement_records=reinforcement,
        output_dir=tmp_path / "dataset",
    )

    reinforced = [
        row for row in manifest["records"] if row["source_dataset"] == "reinforcement-v22"
    ]
    assert len(reinforced) == 2
    assert all(row["final_holdout_eligible"] is False for row in reinforced)
    assert manifest["evaluation_tier"] == "development"
    assert manifest["future_holdout_required"] is True


def test_v22_manifest_counts_match_materialized_files(tmp_path: Path):
    base, reinforcement = _records(tmp_path)
    output_dir = tmp_path / "dataset"

    manifest = build_v22_dataset(
        base_records=base,
        reinforcement_records=reinforcement,
        output_dir=output_dir,
    )

    image_files = list((output_dir / "images").glob("*/*.jpg"))
    label_files = list((output_dir / "labels").glob("*/*.txt"))
    positive_labels = [path for path in label_files if path.read_text().strip()]
    box_count = sum(len(path.read_text().splitlines()) for path in label_files)
    assert manifest["image_count"] == len(image_files) == len(label_files) == 6
    assert manifest["positive_image_count"] == len(positive_labels) == 3
    assert manifest["box_count"] == box_count == 3
    assert manifest["source_dataset_counts"] == {
        "base-v21": 4,
        "reinforcement-v22": 2,
    }
    assert (output_dir / "development-exclusions.private.json").is_file()
    assert (output_dir / "data.yaml").is_file()


def test_reinforcement_loader_excludes_ambiguous_and_namespaces_sequences(
    tmp_path: Path,
):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    image_hashes = {}
    for sequence in ("V0001", "V0002"):
        image_bytes = sequence.encode("ascii")
        (images_dir / f"{sequence}.jpg").write_bytes(image_bytes)
        image_hashes[sequence] = hashlib.sha256(image_bytes).hexdigest()

    candidate = {
        "status": "V22_CANDIDATE_QUEUE_READY",
        "frames": [
            {
                "sequence": sequence,
                "camera_night": f"night-{index}",
                "image_sha256": image_hashes[sequence],
            }
            for index, sequence in enumerate(("V0001", "V0002"), start=1)
        ],
    }
    snapshot = {
        "schema": "cvat-task160-owner-snapshot-v1",
        "images": [
            {
                "path": f"images/{sequence}.jpg",
                "width": 100,
                "height": 80,
                "image_sha256": image_hashes[sequence],
                "boxes": (
                    [
                        {
                            "type": "rectangle",
                            "label_id": 1,
                            "points": [10, 20, 50, 60],
                        }
                    ]
                    if sequence == "V0001"
                    else []
                ),
            }
            for sequence in ("V0001", "V0002")
        ],
    }
    summary = {
        "status": "V22_HUMAN_REVIEW_ACCEPTED",
        "ambiguous_image_count": 1,
        "positive_image_count": 1,
        "negative_image_count": 0,
        "box_count": 1,
    }
    candidate_path = tmp_path / "candidate.json"
    snapshot_path = tmp_path / "snapshot.json"
    summary_path = tmp_path / "summary.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    review_path = tmp_path / "review.csv"
    with review_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["sequence", "ambiguous"])
        writer.writeheader()
        writer.writerow({"sequence": "V0001", "ambiguous": "false"})
        writer.writerow({"sequence": "V0002", "ambiguous": "true"})

    records = load_v22_reinforcement_records(
        candidate_manifest_path=candidate_path,
        snapshot_path=snapshot_path,
        review_path=review_path,
        accepted_summary_path=summary_path,
        images_dir=images_dir,
    )

    assert len(records) == 1
    assert records[0].sequence == "R22_V0001"
    assert records[0].source_dataset == "reinforcement-v22"
    assert records[0].final_holdout_eligible is False


def test_v21_loader_maps_historical_gecko_label_id_nine(tmp_path: Path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "B0001.jpg").write_bytes(b"base")
    snapshot_path = tmp_path / "snapshot.json"
    review_path = tmp_path / "review.csv"
    snapshot_path.write_text(
        json.dumps(
            {
                "schema": "cvat-task160-owner-snapshot-v1",
                "images": [
                    {
                        "path": "images/B0001.jpg",
                        "width": 100,
                        "height": 80,
                        "boxes": [
                            {
                                "type": "rectangle",
                                "label_id": 9,
                                "points": [10, 20, 50, 60],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    review_path.write_text(
        "sequence,camera_night_group\nB0001,night-a\n", encoding="utf-8"
    )

    records = load_v21_records(
        snapshot_path=snapshot_path,
        review_path=review_path,
        images_dir=images_dir,
    )

    assert records[0].boxes == (BoundingBox(10, 20, 50, 60),)


def test_reinforcement_loader_rejects_summary_count_drift(tmp_path: Path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    image_bytes = b"one"
    image_sha = hashlib.sha256(image_bytes).hexdigest()
    (images_dir / "V0001.jpg").write_bytes(image_bytes)
    candidate_path = tmp_path / "candidate.json"
    snapshot_path = tmp_path / "snapshot.json"
    summary_path = tmp_path / "summary.json"
    review_path = tmp_path / "review.csv"
    candidate_path.write_text(
        json.dumps(
            {
                "status": "V22_CANDIDATE_QUEUE_READY",
                "frames": [
                    {
                        "sequence": "V0001",
                        "camera_night": "night-a",
                        "image_sha256": image_sha,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    snapshot_path.write_text(
        json.dumps(
            {
                "schema": "cvat-task160-owner-snapshot-v1",
                "images": [
                    {
                        "path": "images/V0001.jpg",
                        "width": 100,
                        "height": 80,
                        "image_sha256": image_sha,
                        "boxes": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(
            {
                "status": "V22_HUMAN_REVIEW_ACCEPTED",
                "ambiguous_image_count": 0,
                "positive_image_count": 1,
                "negative_image_count": 0,
                "box_count": 0,
            }
        ),
        encoding="utf-8",
    )
    review_path.write_text("sequence,ambiguous\nV0001,false\n", encoding="utf-8")

    with pytest.raises(ValueError, match="summary counts"):
        load_v22_reinforcement_records(
            candidate_manifest_path=candidate_path,
            snapshot_path=snapshot_path,
            review_path=review_path,
            accepted_summary_path=summary_path,
            images_dir=images_dir,
        )

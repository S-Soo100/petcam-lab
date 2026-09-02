import csv
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

import scripts.build_yolo26n_owner_media_diagnostic as diagnostic
from scripts.build_yolo26n_owner_media_diagnostic import (
    main,
    materialize_review_queue,
    select_owner_media,
)


def _rows(day_count: int = 90, per_day: int = 4) -> list[dict]:
    return [
        {
            "source_name": f"photo-{day:03d}-{index}.jpg",
            "source_sha256": f"{day * per_day + index:064x}",
            "capture_day": f"2026-01-{day + 1:03d}",
            "camera_model": "phone",
        }
        for day in range(day_count)
        for index in range(per_day)
    ]


def test_selector_is_exact_day_bounded_partitioned_and_order_independent():
    rows = _rows()

    selected = select_owner_media(rows, total=240, diagnostic=60, per_day_cap=3)
    reversed_selected = select_owner_media(
        list(reversed(rows)), total=240, diagnostic=60, per_day_cap=3
    )

    assert selected == reversed_selected
    assert len(selected) == 240
    assert sum(row["partition"] == "external_diagnostic" for row in selected) == 60
    assert sum(row["partition"] == "training_candidate" for row in selected) == 180
    counts: dict[str, int] = {}
    partitions: dict[str, set[str]] = {}
    for row in selected:
        counts[row["capture_day"]] = counts.get(row["capture_day"], 0) + 1
        partitions.setdefault(row["capture_day"], set()).add(row["partition"])
    assert max(counts.values()) <= 3
    assert all(len(value) == 1 for value in partitions.values())
    assert [row["sequence"] for row in selected] == [
        f"O{index:04d}" for index in range(1, 241)
    ]


def test_selector_fails_closed_when_capacity_or_sha_contract_is_invalid():
    with pytest.raises(ValueError, match="capacity"):
        select_owner_media(_rows(day_count=10), total=240, diagnostic=60)

    rows = _rows()
    rows[1]["source_sha256"] = rows[0]["source_sha256"]
    with pytest.raises(ValueError, match="duplicate source sha"):
        select_owner_media(rows, total=240, diagnostic=60)


def test_materializer_strips_metadata_and_binds_csv_zip_and_manifest(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    rows = []
    for index in range(1, 5):
        path = source / f"photo-{index}.jpg"
        image = Image.new("RGB", (2400, 1200), (index * 50, 20, 30))
        exif = Image.Exif()
        exif[271] = "Apple"
        exif[272] = "iPhone"
        image.save(path, exif=exif)
        rows.append(
            {
                "sequence": f"O{index:04d}",
                "source_name": path.name,
                "source_sha256": "",
                "capture_day": f"2026-01-{index:02d}",
                "camera_model": "iPhone",
                "partition": (
                    "external_diagnostic" if index == 1 else "training_candidate"
                ),
            }
        )

    output = tmp_path / "output"
    manifest = materialize_review_queue(rows, source_dir=source, output_dir=output)

    assert manifest["status"] == "OWNER_MEDIA_HUMAN_REVIEW_REQUIRED"
    assert manifest["image_count"] == 4
    assert list((output / "review-frames").glob("*.jpg"))
    for path in (output / "review-frames").glob("*.jpg"):
        with Image.open(path) as image:
            assert max(image.size) <= 1920
            assert not image.getexif()
    with (output / "review-index.csv").open(newline="", encoding="utf-8") as f:
        review = list(csv.DictReader(f))
    assert [row["sequence"] for row in review] == [f"O{i:04d}" for i in range(1, 5)]
    assert set(review[0]) == {"sequence", "filename", "instruction"}
    with (output / "ambiguous.csv").open(newline="", encoding="utf-8") as f:
        ambiguous = list(csv.DictReader(f))
    assert [row["ambiguous"] for row in ambiguous] == ["false"] * 4
    with zipfile.ZipFile(output / "cvat-upload.zip") as archive:
        assert archive.namelist() == [f"O{i:04d}.jpg" for i in range(1, 5)]
    private = json.loads((output / "manifest.private.json").read_text())
    assert all("source_name" in row for row in private["items"])
    assert all("source_name" not in row for row in review)


def test_materializer_refuses_existing_output_and_duplicate_source_bytes(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("a.jpg", "b.jpg"):
        Image.new("RGB", (10, 10), "white").save(source / name)
    rows = [
        {
            "sequence": f"O{index:04d}",
            "source_name": name,
            "source_sha256": "",
            "capture_day": f"2026-01-0{index}",
            "camera_model": "phone",
            "partition": "training_candidate",
        }
        for index, name in enumerate(("a.jpg", "b.jpg"), start=1)
    ]

    with pytest.raises(ValueError, match="duplicate source sha"):
        materialize_review_queue(rows, source_dir=source, output_dir=tmp_path / "out")
    assert not (tmp_path / "out" / "cvat-upload.zip").exists()


def test_cli_refuses_non_release_sample_counts_before_reading_sources(tmp_path: Path):
    with pytest.raises(ValueError, match="exactly 240 total and 60 diagnostic"):
        main(
            [
                "--source-dir",
                str(tmp_path / "missing-source"),
                "--output-dir",
                str(tmp_path / "output"),
                "--total",
                "4",
                "--diagnostic",
                "1",
            ]
        )


def test_exclusive_publish_never_replaces_an_empty_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "source"
    source.mkdir()
    image = source / "photo.jpg"
    Image.new("RGB", (10, 10), "white").save(image)
    destination = tmp_path / "published"

    def convert_and_create_racing_destination(
        _source: Path, target: Path
    ) -> tuple[int, int]:
        Image.new("RGB", (10, 10), "white").save(target)
        destination.mkdir()
        return (10, 10)

    monkeypatch.setattr(
        diagnostic, "_convert_stripped_jpeg", convert_and_create_racing_destination
    )

    with pytest.raises(FileExistsError):
        materialize_review_queue(
            [
                {
                    "sequence": "O0001",
                    "source_name": image.name,
                    "source_sha256": "",
                    "capture_day": "2026-01-01",
                    "camera_model": "phone",
                    "partition": "training_candidate",
                }
            ],
            source_dir=source,
            output_dir=destination,
        )

    assert destination.is_dir()
    assert list(destination.iterdir()) == []

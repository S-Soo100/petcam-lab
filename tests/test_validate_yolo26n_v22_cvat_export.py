import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.validate_yolo26n_v22_cvat_export import (
    CvatValidationResult,
    main,
    scan_review_frames,
    validate_export,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _manifest(sequences: list[str], *, include_dimensions: bool = False) -> dict[str, object]:
    frames = [
        {
            "sequence": sequence,
            "image_sha256": _digest(sequence),
            **({"width": 100, "height": 80} if include_dimensions else {}),
        }
        for sequence in sequences
    ]
    return {
        "schema": "yolo26n-v22-candidate-queue-merged-v1",
        "status": "V22_CANDIDATE_QUEUE_READY",
        "prediction_boxes_exposed_to_reviewer": False,
        "human_review_required": True,
        "db_write_count": 0,
        "r2_write_count": 0,
        "review_frame_count": len(frames),
        "frames": frames,
    }


def _image_metadata(sequences: list[str]) -> dict[str, dict[str, object]]:
    return {
        sequence: {
            "filename": f"{sequence}.jpg",
            "image_sha256": _digest(sequence),
            "width": 100,
            "height": 80,
        }
        for sequence in sequences
    }


def _snapshot(boxes_by_sequence: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    return {
        "schema": "cvat-task160-owner-snapshot-v1",
        "labels": [{"id": 1, "name": "gecko"}],
        "images": [
            {
                "frame": index,
                "path": f"images/{sequence}.jpg",
                "width": 100,
                "height": 80,
                "image_sha256": _digest(sequence),
                "boxes": boxes,
            }
            for index, (sequence, boxes) in enumerate(boxes_by_sequence.items())
        ],
    }


def _rectangle(*, points: list[object] | None = None, **extra: object) -> dict[str, object]:
    return {
        "type": "rectangle",
        "label_id": 1,
        "points": points or [10, 20, 50, 60],
        **extra,
    }


def _review_rows(sequences: list[str]) -> list[dict[str, str]]:
    return [{"sequence": sequence, "ambiguous": "false"} for sequence in sequences]


def _write_jpeg(path: Path, *, color: int = 0) -> str:
    Image.new("RGB", (100, 80), color=(color, color, color)).save(path, format="JPEG")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_ambiguous_frame_is_excluded_instead_of_becoming_negative() -> None:
    result = validate_export(
        candidate_manifest=_manifest(["H0001", "H0002"]),
        snapshot=_snapshot({"H0001": [], "H0002": []}),
        image_metadata=_image_metadata(["H0001", "H0002"]),
        review_rows=[
            {"sequence": "H0001", "ambiguous": "false"},
            {"sequence": "H0002", "ambiguous": "true"},
        ],
    )

    assert result == CvatValidationResult(
        accepted_sequences=("H0001",),
        ambiguous_sequences=("H0002",),
        positive_image_count=0,
        negative_image_count=1,
        box_count=0,
    )


def test_multiple_gecko_boxes_are_accepted_and_counted_as_one_positive_image() -> None:
    result = validate_export(
        candidate_manifest=_manifest(["H0001", "H0002"]),
        snapshot=_snapshot(
            {"H0001": [_rectangle(), _rectangle(points=[51, 1, 99, 79])], "H0002": []}
        ),
        image_metadata=_image_metadata(["H0001", "H0002"]),
        review_rows=_review_rows(["H0001", "H0002"]),
    )

    assert result == CvatValidationResult(
        accepted_sequences=("H0001", "H0002"),
        ambiguous_sequences=(),
        positive_image_count=1,
        negative_image_count=1,
        box_count=2,
    )


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda manifest: manifest.update({"schema": "unknown"}),
            "manifest schema",
        ),
        (
            lambda manifest: manifest.update({"review_frame_count": 3}),
            "manifest frame count",
        ),
        (
            lambda manifest: (
                manifest["frames"].append(dict(manifest["frames"][0])),
                manifest.__setitem__("review_frame_count", 3),
            ),
            "manifest sequences",
        ),
        (
            lambda manifest: manifest["frames"][0].update({"width": 101}),
            "image dimensions",
        ),
    ],
)
def test_manifest_schema_count_unique_sequences_and_dimensions_are_required(mutate, match) -> None:
    manifest = _manifest(["H0001", "H0002"], include_dimensions=True)
    mutate(manifest)

    with pytest.raises(ValueError, match=match):
        validate_export(
            candidate_manifest=manifest,
            snapshot=_snapshot({"H0001": [], "H0002": []}),
            image_metadata=_image_metadata(["H0001", "H0002"]),
            review_rows=_review_rows(["H0001", "H0002"]),
        )


@pytest.mark.parametrize(
    ("snapshot", "review_rows", "match"),
    [
        (
            _snapshot({"H0001": []}),
            _review_rows(["H0001", "H0002"]),
            "snapshot sequences",
        ),
        (
            _snapshot({"H0001": [], "H9999": []}),
            _review_rows(["H0001", "H0002"]),
            "snapshot sequences",
        ),
        (
            _snapshot({"H0001": [], "H0002": []}),
            [{"sequence": "H0001", "ambiguous": "false"}],
            "review sequences",
        ),
        (
            _snapshot({"H0001": [], "H0002": []}),
            [
                {"sequence": "H0001", "ambiguous": "false"},
                {"sequence": "H0001", "ambiguous": "false"},
            ],
            "review sequences",
        ),
    ],
)
def test_snapshot_and_owner_review_each_require_the_exact_manifest_sequence_set(
    snapshot, review_rows, match
) -> None:
    with pytest.raises(ValueError, match=match):
        validate_export(
            candidate_manifest=_manifest(["H0001", "H0002"]),
            snapshot=snapshot,
            image_metadata=_image_metadata(["H0001", "H0002"]),
            review_rows=review_rows,
        )


def test_snapshot_rejects_a_second_distinct_label_class() -> None:
    snapshot = _snapshot({"H0001": []})
    snapshot["labels"].append({"id": 2, "name": "leaf"})

    with pytest.raises(ValueError, match="label contract"):
        validate_export(
            candidate_manifest=_manifest(["H0001"]),
            snapshot=snapshot,
            image_metadata=_image_metadata(["H0001"]),
            review_rows=_review_rows(["H0001"]),
        )


@pytest.mark.parametrize(
    ("box", "match"),
    [
        ({"type": "polygon", "label_id": 1, "points": [1, 2, 3, 4]}, "rectangle"),
        (_rectangle(attributes={"name": "bad"}), "attributes"),
        (_rectangle(points=[-1, 2, 3, 4]), "bbox"),
        (_rectangle(points=[20, 2, 20, 4]), "bbox"),
        (_rectangle(points=[20, 4, 10, 5]), "bbox"),
        (_rectangle(points=[1, 2, 101, 4]), "bbox"),
        (_rectangle(points=[1, float("nan"), 3, 4]), "bbox"),
    ],
)
def test_snapshot_rejects_unsupported_shapes_malformed_attributes_and_invalid_bbox(box, match) -> None:
    with pytest.raises(ValueError, match=match):
        validate_export(
            candidate_manifest=_manifest(["H0001"]),
            snapshot=_snapshot({"H0001": [box]}),
            image_metadata=_image_metadata(["H0001"]),
            review_rows=_review_rows(["H0001"]),
        )


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda snapshot: snapshot["images"][0].update({"image_sha256": "f" * 64}),
            "image sha256",
        ),
        (lambda snapshot: snapshot["images"][0].update({"width": 101}), "image dimensions"),
        (
            lambda snapshot: snapshot["images"].append(
                {**snapshot["images"][0], "frame": 1}
            ),
            "snapshot sequences",
        ),
    ],
)
def test_snapshot_requires_exact_manifest_image_hash_dimensions_and_unique_mapping(mutate, match) -> None:
    snapshot = _snapshot({"H0001": []})
    mutate(snapshot)

    with pytest.raises(ValueError, match=match):
        validate_export(
            candidate_manifest=_manifest(["H0001"]),
            snapshot=snapshot,
            image_metadata=_image_metadata(["H0001"]),
            review_rows=_review_rows(["H0001"]),
        )


def test_snapshot_rejects_duplicate_cvat_frame_identifiers() -> None:
    snapshot = _snapshot({"H0001": [], "H0002": []})
    snapshot["images"][1]["frame"] = 0

    with pytest.raises(ValueError, match="snapshot frame identifiers"):
        validate_export(
            candidate_manifest=_manifest(["H0001", "H0002"]),
            snapshot=snapshot,
            image_metadata=_image_metadata(["H0001", "H0002"]),
            review_rows=_review_rows(["H0001", "H0002"]),
        )


def test_scan_review_frames_rejects_duplicate_expected_sequence(tmp_path: Path) -> None:
    _write_jpeg(tmp_path / "H0001.jpg")
    with pytest.raises(ValueError, match="expected sequence"):
        scan_review_frames(tmp_path, expected_sequences=("H0001", "H0001"))


def test_scan_review_frames_reads_exact_jpeg_set_with_bytes_hash_and_dimensions(tmp_path: Path) -> None:
    image_sha256 = _write_jpeg(tmp_path / "H0001.jpg")

    assert scan_review_frames(tmp_path, expected_sequences=("H0001",)) == {
        "H0001": {
            "filename": "H0001.jpg",
            "image_sha256": image_sha256,
            "width": 100,
            "height": 80,
        }
    }


@pytest.mark.parametrize(
    ("setup", "match"),
    [
        (lambda root: _write_jpeg(root / "H0002.jpg"), "filenames"),
        (lambda root: (root / "H0001.jpg").write_bytes(b"not a JPEG"), "JPEG decode"),
    ],
)
def test_scan_review_frames_rejects_extra_or_undecodable_files(setup, match, tmp_path: Path) -> None:
    _write_jpeg(tmp_path / "H0001.jpg")
    setup(tmp_path)

    with pytest.raises(ValueError, match=match):
        scan_review_frames(tmp_path, expected_sequences=("H0001",))


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda metadata: metadata["H0001"].update({"filename": "wrong.jpg"}),
            "filename mismatch",
        ),
        (
            lambda metadata: metadata["H0001"].update({"image_sha256": "f" * 64}),
            "manifest image sha256",
        ),
        (
            lambda metadata: metadata["H0001"].update({"height": 81}),
            "image dimensions",
        ),
    ],
)
def test_actual_image_metadata_must_match_manifest_filename_hash_and_optional_dimensions(
    mutate, match
) -> None:
    manifest = _manifest(["H0001"], include_dimensions=True)
    metadata = _image_metadata(["H0001"])
    mutate(metadata)

    with pytest.raises(ValueError, match=match):
        validate_export(
            candidate_manifest=manifest,
            snapshot=_snapshot({"H0001": []}),
            image_metadata=metadata,
            review_rows=_review_rows(["H0001"]),
        )


@pytest.mark.parametrize("ambiguous", ["True", "false ", "", "0"])
def test_review_ambiguous_value_must_be_a_strict_lowercase_boolean(ambiguous) -> None:
    with pytest.raises(ValueError, match="ambiguous"):
        validate_export(
            candidate_manifest=_manifest(["H0001"]),
            snapshot=_snapshot({"H0001": []}),
            image_metadata=_image_metadata(["H0001"]),
            review_rows=[{"sequence": "H0001", "ambiguous": ambiguous}],
        )


def test_ambiguous_frame_with_boxes_is_excluded_from_all_accepted_counts() -> None:
    result = validate_export(
        candidate_manifest=_manifest(["H0001"]),
        snapshot=_snapshot({"H0001": [_rectangle()]}),
        image_metadata=_image_metadata(["H0001"]),
        review_rows=[{"sequence": "H0001", "ambiguous": "true"}],
    )

    assert result == CvatValidationResult(
        accepted_sequences=(),
        ambiguous_sequences=("H0001",),
        positive_image_count=0,
        negative_image_count=0,
        box_count=0,
    )


def test_cli_pins_the_manifest_and_writes_only_safe_atomic_private_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _manifest(["H0001"])
    snapshot = _snapshot({"H0001": []})
    manifest_path = tmp_path / "candidate-manifest.private.json"
    snapshot_path = tmp_path / "snapshot.json"
    review_path = tmp_path / "owner-review.private.csv"
    review_frames_dir = tmp_path / "review-frames"
    summary_path = tmp_path / "accepted-summary.private.json"
    review_frames_dir.mkdir()
    image_sha256 = _write_jpeg(review_frames_dir / "H0001.jpg")
    manifest["frames"][0]["image_sha256"] = image_sha256
    snapshot["images"][0]["image_sha256"] = image_sha256
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    review_path.write_text("sequence,ambiguous\nH0001,false\n", encoding="utf-8")
    expected_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    main(
        [
            "--candidate-manifest",
            str(manifest_path),
            "--snapshot",
            str(snapshot_path),
            "--owner-review",
            str(review_path),
            "--review-frames-dir",
            str(review_frames_dir),
            "--expected-manifest-sha256",
            expected_sha256,
            "--summary-output",
            str(summary_path),
        ]
    )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary == {
        "ambiguous_image_count": 0,
        "box_count": 0,
        "negative_image_count": 1,
        "positive_image_count": 0,
        "status": "V22_HUMAN_REVIEW_ACCEPTED",
    }
    assert "H0001" not in capsys.readouterr().out


def test_cli_failure_never_creates_summary_output(tmp_path: Path) -> None:
    manifest_path = tmp_path / "candidate-manifest.private.json"
    snapshot_path = tmp_path / "snapshot.json"
    review_path = tmp_path / "owner-review.private.csv"
    review_frames_dir = tmp_path / "review-frames"
    summary_path = tmp_path / "accepted-summary.private.json"
    manifest_path.write_text(json.dumps(_manifest(["H0001"])), encoding="utf-8")
    snapshot_path.write_text(json.dumps(_snapshot({"H0001": []})), encoding="utf-8")
    review_path.write_text("sequence,ambiguous\nH0001,false\n", encoding="utf-8")
    review_frames_dir.mkdir()

    with pytest.raises(ValueError, match="manifest sha256"):
        main(
            [
                "--candidate-manifest",
                str(manifest_path),
                "--snapshot",
                str(snapshot_path),
                "--owner-review",
                str(review_path),
                "--review-frames-dir",
                str(review_frames_dir),
                "--expected-manifest-sha256",
                "0" * 64,
                "--summary-output",
                str(summary_path),
            ]
        )

    assert not summary_path.exists()

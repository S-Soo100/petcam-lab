import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts.validate_yolo26n_owner_media_export import main, normalize_owner_media_export


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _manifest() -> dict:
    return {
        "schema": "yolo26n-owner-media-diagnostic-v1",
        "status": "OWNER_MEDIA_HUMAN_REVIEW_REQUIRED",
        "prediction_exposed": False,
        "image_count": 240,
        "partition_counts": {"external_diagnostic": 60, "training_candidate": 180},
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "items": [
            {
                "sequence": f"O{index:04d}",
                "partition": "external_diagnostic" if index <= 60 else "training_candidate",
                "derived_filename": f"O{index:04d}.jpg",
                "derived_sha256": _sha(str(index)),
                "width": 100,
                "height": 80,
            }
            for index in range(1, 241)
        ],
    }


def _shape(frame: int) -> dict:
    return {
        "id": frame + 1,
        "type": "rectangle",
        "frame": frame,
        "label_id": 10,
        "points": [10, 20, 50, 60],
        "rotation": 0.0,
        "outside": False,
        "occluded": False,
        "attributes": [],
        "elements": [],
        "group": 0,
        "source": "manual",
        "z_order": 0,
        # CVAT Job annotation GET serializes manually saved rectangles with
        # the canonical confidence sentinel 1 (not null).
        "score": 1,
    }


def _review_rows(*, ambiguous: set[str] | None = None) -> list[dict[str, str]]:
    marked = ambiguous or set()
    return [
        {
            "sequence": f"O{index:04d}",
            "ambiguous": "true" if f"O{index:04d}" in marked else "false",
        }
        for index in range(1, 241)
    ]


def test_normalizer_binds_manifest_frames_and_excludes_ambiguous_even_with_box():
    snapshot, summary = normalize_owner_media_export(
        manifest=_manifest(),
        annotations={"version": 0, "tags": [], "tracks": [], "shapes": [_shape(0), _shape(1)]},
        review_rows=_review_rows(ambiguous={"O0002"}),
        raw_cvat_job_id=163,
    )

    assert snapshot["schema"] == "yolo26n-owner-media-cvat-snapshot-v1"
    assert [len(image["boxes"]) for image in snapshot["images"][:3]] == [1, 1, 0]
    assert summary["status"] == "OWNER_MEDIA_HUMAN_REVIEW_ACCEPTED"
    assert summary["image_count"] == 240
    assert summary["accepted_image_count"] == 239
    assert summary["ambiguous_image_count"] == 1
    assert summary["positive_image_count"] == 1
    assert summary["negative_image_count"] == 238
    assert summary["box_count"] == 1
    assert summary["partition_counts"]["external_diagnostic"] == {
        "accepted": 59, "ambiguous": 1, "positive": 1, "negative": 58, "boxes": 1
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda annotations: annotations.update(tracks=[{}]), "tracks"),
        (lambda annotations: annotations["shapes"][0].update(label_id=11), "label"),
        (lambda annotations: annotations["shapes"][0].update(frame=240), "frame"),
        (lambda annotations: annotations["shapes"][0].update(outside=True), "shape"),
        (lambda annotations: annotations["shapes"][0].update(points=[-1, 0, 5, 5]), "bbox"),
    ],
)
def test_normalizer_fails_closed_on_cvat_contract_drift(mutate, message):
    annotations = {"version": 0, "tags": [], "tracks": [], "shapes": [_shape(0)]}
    mutate(annotations)
    with pytest.raises(ValueError, match=message):
        normalize_owner_media_export(
            manifest=_manifest(),
            annotations=annotations,
            review_rows=_review_rows(),
            raw_cvat_job_id=163,
        )


def test_normalizer_rejects_wrong_job_or_label_and_boolean_numeric_fields():
    annotations = {"version": 0, "tags": [], "tracks": [], "shapes": [_shape(0)]}
    with pytest.raises(ValueError, match="job"):
        normalize_owner_media_export(
            manifest=_manifest(),
            annotations=annotations,
            review_rows=_review_rows(),
            raw_cvat_job_id=164,
        )

    for field, value, message in (
        ("label_id", 11, "label"),
        ("rotation", False, "shape"),
        ("group", False, "shape"),
        ("z_order", False, "shape"),
    ):
        mutated = {"version": 0, "tags": [], "tracks": [], "shapes": [_shape(0)]}
        mutated["shapes"][0][field] = value
        with pytest.raises(ValueError, match=message):
            normalize_owner_media_export(
                manifest=_manifest(),
                annotations=mutated,
                review_rows=_review_rows(),
                raw_cvat_job_id=163,
            )


def test_normalizer_requires_exact_fixed_queue_size_and_integer_partition_counts():
    manifest = _manifest()
    manifest["items"] = manifest["items"][:1]
    manifest["image_count"] = 1
    manifest["partition_counts"] = {"external_diagnostic": 1, "training_candidate": 0}
    with pytest.raises(ValueError, match="exactly 240"):
        normalize_owner_media_export(
            manifest=manifest,
            annotations={"version": 0, "tags": [], "tracks": [], "shapes": []},
            review_rows=[{"sequence": "O0001", "ambiguous": "false"}],
            raw_cvat_job_id=163,
        )

    manifest = _manifest()
    manifest["partition_counts"] = {
        "external_diagnostic": True,
        "training_candidate": False,
    }
    with pytest.raises(ValueError, match="partition counts"):
        normalize_owner_media_export(
            manifest=manifest,
            annotations={"version": 0, "tags": [], "tracks": [], "shapes": []},
            review_rows=_review_rows(),
            raw_cvat_job_id=163,
        )


def test_cli_pins_all_inputs_and_writes_private_outputs_once(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    annotations_path = tmp_path / "annotations.json"
    review_path = tmp_path / "review.csv"
    snapshot_path = tmp_path / "snapshot.private.json"
    summary_path = tmp_path / "summary.private.json"
    manifest_bytes = json.dumps(_manifest()).encode()
    annotations_bytes = json.dumps(
        {"version": 0, "tags": [], "tracks": [], "shapes": [_shape(0)]}
    ).encode()
    review_bytes = (
        "sequence,ambiguous\n"
        + "".join(f"O{index:04d},false\n" for index in range(1, 241))
    ).encode()
    manifest_path.write_bytes(manifest_bytes)
    annotations_path.write_bytes(annotations_bytes)
    review_path.write_bytes(review_bytes)

    args = [
        "--manifest", str(manifest_path),
        "--annotations", str(annotations_path),
        "--owner-review", str(review_path),
        "--cvat-job-id", "163",
        "--expected-manifest-sha256", hashlib.sha256(manifest_bytes).hexdigest(),
        "--expected-annotations-sha256", hashlib.sha256(annotations_bytes).hexdigest(),
        "--expected-owner-review-sha256", hashlib.sha256(review_bytes).hexdigest(),
        "--snapshot-output", str(snapshot_path),
        "--summary-output", str(summary_path),
    ]
    assert main(args) == 0
    snapshot = json.loads(snapshot_path.read_text())
    summary = json.loads(summary_path.read_text())
    assert snapshot["provenance"] == summary["provenance"]
    assert snapshot["provenance"] == {
        "annotations_sha256": hashlib.sha256(annotations_bytes).hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "owner_review_sha256": hashlib.sha256(review_bytes).hexdigest(),
        "cvat_job_id": 163,
        "raw_gecko_label_id": 10,
    }
    assert oct(os.stat(snapshot_path).st_mode & 0o777) == "0o600"
    assert oct(os.stat(summary_path).st_mode & 0o777) == "0o600"
    with pytest.raises(ValueError, match="output already exists"):
        main(args)

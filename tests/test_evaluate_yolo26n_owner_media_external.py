import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.evaluate_yolo26n_owner_media_external import (
    build_external_diagnostic_report,
    load_external_diagnostic_samples,
    make_external_predictor,
    validate_frozen_inputs,
    validate_prediction_result,
)
from scripts.evaluate_yolo26n_v24_gate_reuse import select_v24_threshold


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _snapshot(frame_count: int = 240) -> dict[str, object]:
    return {
        "schema": "yolo26n-owner-media-cvat-snapshot-v1",
        "labels": [{"id": 1, "name": "gecko"}],
        "provenance": {"cvat_job_id": 163},
        "images": [
            {
                "frame": index,
                "path": f"images/O{index + 1:04d}.jpg",
                "partition": "external_diagnostic" if index < 60 else "training_candidate",
                "width": 100,
                "height": 80,
                "image_sha256": "0" * 64,
                "boxes": []
                if index == 0
                else [
                    {
                        "id": index,
                        "label_id": 1,
                        "type": "rectangle",
                        "rotation": 0.0,
                        "points": [10.0, 10.0, 50.0, 50.0],
                    }
                ],
            }
            for index in range(frame_count)
        ],
    }


def _v24_freeze(checkpoint_sha: str) -> dict[str, object]:
    return select_v24_threshold(
        {
            "schema": "yolo26n-v24-prediction-ledger-v1",
            "status": "V24_PREDICTIONS_READY",
            "dataset_schema": "yolo26n-owner-dataset-v24",
            "evaluation_tier": "development",
            "split": "val",
            "candidate": "warm-start",
            "source_commit": "a" * 40,
            "runner_sha256": "b" * 64,
            "dataset_manifest_sha256": "c" * 64,
            "checkpoint_sha256": checkpoint_sha,
            "inference": {
                "confidence": 0.001,
                "imgsz": 960,
                "nms_iou": 0.70,
                "max_det": 50,
                "device": "mps",
            },
            "image_count": 1,
            "gt_box_count": 1,
            "prediction_count": 1,
            "records": [
                {
                    "sequence": "V0001",
                    "image_sha256": "1" * 64,
                    "width": 100,
                    "height": 100,
                    "gt_boxes": [[10.0, 10.0, 50.0, 50.0]],
                    "predictions": [
                        {
                            "confidence": 0.35,
                            "xyxy": [10.0, 10.0, 50.0, 50.0],
                        }
                    ],
                }
            ],
        },
        validation_ledger_sha256="d" * 64,
    )


def test_loader_binds_exact_60_images_and_bytes(tmp_path: Path):
    snapshot = _snapshot()
    # The frozen diagnostic partition is intentionally interleaved across the
    # 240-frame queue by capture-day; it is not necessarily O0001..O0060.
    for index, row in enumerate(snapshot["images"]):
        row["partition"] = "external_diagnostic" if index % 4 == 0 else "training_candidate"
    for row in snapshot["images"]:
        payload = f"jpeg-{row['frame']}".encode()
        path = tmp_path / Path(row["path"]).name
        path.write_bytes(payload)
        row["image_sha256"] = _sha(payload)

    samples = load_external_diagnostic_samples(
        snapshot=snapshot,
        review_frames_dir=tmp_path,
    )

    assert len(samples) == 60
    assert samples[0].sequence == "O0001"
    assert samples[1].sequence == "O0005"
    assert samples[1].gt_boxes == ((10.0, 10.0, 50.0, 50.0),)

    snapshot["images"][0]["partition"] = "training_candidate"
    with pytest.raises(ValueError, match="partition"):
        load_external_diagnostic_samples(snapshot=snapshot, review_frames_dir=tmp_path)

    snapshot = _snapshot()
    snapshot["labels"] = [{"id": 999, "name": "not-gecko"}]
    with pytest.raises(ValueError, match="label"):
        load_external_diagnostic_samples(snapshot=snapshot, review_frames_dir=tmp_path)

    snapshot = _snapshot()
    for row in snapshot["images"]:
        payload = f"jpeg-{row['frame']}".encode()
        row["image_sha256"] = _sha(payload)
    snapshot["images"][100]["boxes"][0]["rotation"] = 45
    with pytest.raises(ValueError, match="box"):
        load_external_diagnostic_samples(snapshot=snapshot, review_frames_dir=tmp_path)

    for field, value in (("frame", True), ("box_label", True)):
        snapshot = _snapshot()
        for row in snapshot["images"]:
            payload = f"jpeg-{row['frame']}".encode()
            row["image_sha256"] = _sha(payload)
        if field == "frame":
            snapshot["images"][1]["frame"] = value
        else:
            snapshot["images"][1]["boxes"][0]["label_id"] = value
        with pytest.raises(ValueError):
            load_external_diagnostic_samples(snapshot=snapshot, review_frames_dir=tmp_path)


def test_frozen_inputs_require_independent_sha_and_full_contract(tmp_path: Path):
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    freeze = {
        "schema": "yolo26n-v22-candidate-threshold-freeze-v1",
        "status": "V22_THRESHOLD_FROZEN_DEVELOPMENT_ONLY",
        "evaluation_tier": "development",
        "future_holdout_required": True,
        "candidate": "warm-start",
        "threshold": 0.20,
        "precision_floor": 0.60,
        "checkpoint_sha256": _sha(b"checkpoint"),
        "candidate_checkpoint_sha256": {
            "warm-start": _sha(b"checkpoint"),
            "clean-reference": "c" * 64,
        },
        "inference": {
            "confidence": 0.001,
            "imgsz": 960,
            "nms_iou": 0.70,
            "max_det": 50,
            "device": "mps",
        },
    }
    freeze_bytes = json.dumps(freeze, sort_keys=True).encode()
    snapshot_bytes = json.dumps(_snapshot(), sort_keys=True).encode()
    summary = {
        "status": "OWNER_MEDIA_HUMAN_REVIEW_ACCEPTED",
        "image_count": 240,
        "accepted_image_count": 237,
        "ambiguous_image_count": 3,
        "partition_counts": {
            "external_diagnostic": {"accepted": 60, "ambiguous": 0},
            "training_candidate": {"accepted": 177, "ambiguous": 3},
        },
        "provenance": {"cvat_job_id": 163, "raw_gecko_label_id": 10},
    }
    summary_bytes = json.dumps(summary, sort_keys=True).encode()

    validate_frozen_inputs(
        freeze=json.loads(freeze_bytes), freeze_bytes=freeze_bytes,
        expected_freeze_sha256=_sha(freeze_bytes), checkpoint_path=checkpoint,
        snapshot=json.loads(snapshot_bytes), snapshot_bytes=snapshot_bytes,
        expected_snapshot_sha256=_sha(snapshot_bytes), summary=json.loads(summary_bytes),
        summary_bytes=summary_bytes, expected_summary_sha256=_sha(summary_bytes),
    )

    with pytest.raises(ValueError, match="freeze SHA"):
        validate_frozen_inputs(
            freeze=json.loads(freeze_bytes), freeze_bytes=freeze_bytes,
            expected_freeze_sha256="f" * 64, checkpoint_path=checkpoint,
            snapshot=json.loads(snapshot_bytes), snapshot_bytes=snapshot_bytes,
            expected_snapshot_sha256=_sha(snapshot_bytes), summary=json.loads(summary_bytes),
            summary_bytes=summary_bytes, expected_summary_sha256=_sha(summary_bytes),
        )


def test_frozen_inputs_accept_v23_selection_and_return_its_threshold(tmp_path: Path):
    """Catches silently evaluating v2.3 with the old v2.2 threshold."""
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"v23-checkpoint")
    checkpoint_sha = _sha(b"v23-checkpoint")
    freeze = {
        "schema": "yolo26n-v23-candidate-threshold-freeze-v1",
        "status": "V23_THRESHOLD_FROZEN_DEVELOPMENT_ONLY",
        "evaluation_tier": "development",
        "future_holdout_required": True,
        "candidate": "warm-start",
        "threshold": 0.25,
        "precision_floor": 0.60,
        "checkpoint_sha256": checkpoint_sha,
        "candidate_checkpoint_sha256": {
            "warm-start": checkpoint_sha,
            "clean-reference": "c" * 64,
        },
        "inference": {
            "confidence": 0.001,
            "imgsz": 960,
            "nms_iou": 0.70,
            "max_det": 50,
            "device": "mps",
        },
    }
    freeze_bytes = json.dumps(freeze, sort_keys=True).encode()
    snapshot_bytes = json.dumps(_snapshot(), sort_keys=True).encode()
    summary = {
        "status": "OWNER_MEDIA_HUMAN_REVIEW_ACCEPTED",
        "image_count": 240,
        "accepted_image_count": 237,
        "ambiguous_image_count": 3,
        "partition_counts": {
            "external_diagnostic": {"accepted": 60, "ambiguous": 0},
            "training_candidate": {"accepted": 177, "ambiguous": 3},
        },
        "provenance": {"cvat_job_id": 163, "raw_gecko_label_id": 10},
    }
    summary_bytes = json.dumps(summary, sort_keys=True).encode()

    selection = validate_frozen_inputs(
        freeze=freeze,
        freeze_bytes=freeze_bytes,
        expected_freeze_sha256=_sha(freeze_bytes),
        checkpoint_path=checkpoint,
        snapshot=json.loads(snapshot_bytes),
        snapshot_bytes=snapshot_bytes,
        expected_snapshot_sha256=_sha(snapshot_bytes),
        summary=summary,
        summary_bytes=summary_bytes,
        expected_summary_sha256=_sha(summary_bytes),
    )

    assert selection.version == "v23"
    assert selection.threshold == 0.25
    assert selection.checkpoint_sha256 == checkpoint_sha


def test_frozen_inputs_accept_v24_warm_only_dynamic_threshold(tmp_path: Path):
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"v24-checkpoint")
    checkpoint_sha = _sha(b"v24-checkpoint")
    freeze = _v24_freeze(checkpoint_sha)
    freeze_bytes = json.dumps(freeze, sort_keys=True).encode()
    snapshot_bytes = json.dumps(_snapshot(), sort_keys=True).encode()
    summary = {
        "status": "OWNER_MEDIA_HUMAN_REVIEW_ACCEPTED",
        "image_count": 240,
        "accepted_image_count": 237,
        "ambiguous_image_count": 3,
        "partition_counts": {
            "external_diagnostic": {"accepted": 60, "ambiguous": 0},
            "training_candidate": {"accepted": 177, "ambiguous": 3},
        },
        "provenance": {"cvat_job_id": 163, "raw_gecko_label_id": 10},
    }
    summary_bytes = json.dumps(summary, sort_keys=True).encode()

    selection = validate_frozen_inputs(
        freeze=freeze,
        freeze_bytes=freeze_bytes,
        expected_freeze_sha256=_sha(freeze_bytes),
        checkpoint_path=checkpoint,
        snapshot=json.loads(snapshot_bytes),
        snapshot_bytes=snapshot_bytes,
        expected_snapshot_sha256=_sha(snapshot_bytes),
        summary=summary,
        summary_bytes=summary_bytes,
        expected_summary_sha256=_sha(summary_bytes),
    )

    assert selection.version == "v24"
    assert selection.threshold == 0.35
    assert selection.checkpoint_sha256 == checkpoint_sha

    forged = json.loads(json.dumps(freeze))
    forged["threshold"] = 0.30
    forged_bytes = json.dumps(forged, sort_keys=True).encode()
    with pytest.raises(ValueError, match="frozen threshold"):
        validate_frozen_inputs(
            freeze=forged,
            freeze_bytes=forged_bytes,
            expected_freeze_sha256=_sha(forged_bytes),
            checkpoint_path=checkpoint,
            snapshot=json.loads(snapshot_bytes),
            snapshot_bytes=snapshot_bytes,
            expected_snapshot_sha256=_sha(snapshot_bytes),
            summary=summary,
            summary_bytes=summary_bytes,
            expected_summary_sha256=_sha(summary_bytes),
        )


@pytest.mark.parametrize(
    "prediction",
    [
        {},
        {"confidence": "0.9", "xyxy": [1, 1, 5, 5]},
        {"confidence": float("nan"), "xyxy": [1, 1, 5, 5]},
        {"confidence": 0.9, "xyxy": [5, 1, 1, 5]},
        {"confidence": 0.9, "xyxy": [1, 1, float("inf"), 5]},
    ],
)
def test_prediction_parser_rejects_malformed_values(prediction):
    with pytest.raises(ValueError, match="prediction"):
        validate_prediction_result(
            {"width": 100, "height": 80, "predictions": [prediction]},
            expected_width=100,
            expected_height=80,
        )


def test_external_predictor_passes_pil_images_without_stringifying(monkeypatch, tmp_path):
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    captured = {}

    class FakeBoxes:
        xyxy = type("Tensor", (), {"cpu": lambda self: self, "tolist": lambda self: []})()
        conf = type("Tensor", (), {"cpu": lambda self: self, "tolist": lambda self: []})()

    class FakeModel:
        def predict(self, *, source, **kwargs):
            captured["source"] = source
            return [type("Result", (), {"path": "image0.jpg", "orig_shape": (8, 10), "boxes": FakeBoxes()})()]

    predictor = make_external_predictor(
        checkpoint_path=checkpoint, model_factory=lambda _: FakeModel()
    )
    image = Image.new("RGB", (10, 8))
    rows = predictor(
        [image], confidence=0.001, imgsz=960, nms_iou=0.70,
        max_det=50, device="mps",
    )

    assert captured["source"] == [image]
    assert rows == [{"width": 10, "height": 8, "predictions": []}]


def test_report_separates_recall_from_underpowered_precision():
    snapshot_sha = "a" * 64
    ledger_sha = "b" * 64
    ledger = {
        "records": [
            {
                "sequence": "O0001",
                "gt_boxes": [],
                "predictions": [{"confidence": 0.8, "xyxy": [1, 1, 5, 5]}],
            },
            {
                "sequence": "O0002",
                "gt_boxes": [[10, 10, 50, 50]],
                "predictions": [
                    {"confidence": 0.9, "xyxy": [10, 10, 50, 50]},
                    {"confidence": 0.7, "xyxy": [11, 11, 49, 49]},
                ],
            },
            {
                "sequence": "O0003",
                "gt_boxes": [[10, 10, 50, 50]],
                "predictions": [],
            },
        ]
    }

    report = build_external_diagnostic_report(
        ledger=ledger,
        threshold=0.20,
        snapshot_sha256=snapshot_sha,
        ledger_sha256=ledger_sha,
        expected_image_count=3,
    )

    assert report["status"] == "OWNER_MEDIA_EXTERNAL_DIAGNOSTIC_COMPLETE"
    assert report["box_recall"] == 0.5
    assert report["positive_image_recall"] == 0.5
    assert report["negative_image_count"] == 1
    assert report["precision_status"] == "UNDERPOWERED_NEGATIVE"
    assert report["duplicate_prediction_count"] == 1
    assert report["false_positive_on_negative_count"] == 1
    assert report["provenance"] == {
        "snapshot_sha256": snapshot_sha,
        "prediction_ledger_sha256": ledger_sha,
    }


def test_report_rejects_duplicate_or_malformed_records():
    ledger = {
        "records": [
            {"sequence": "O0001", "gt_boxes": [], "predictions": []},
            {"sequence": "O0001", "gt_boxes": [], "predictions": []},
        ]
    }
    with pytest.raises(ValueError, match="sequence"):
        build_external_diagnostic_report(
            ledger=ledger,
            threshold=0.20,
            snapshot_sha256="a" * 64,
            ledger_sha256="b" * 64,
            expected_image_count=2,
        )

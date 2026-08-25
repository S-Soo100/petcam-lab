from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.evaluate_yolo26n_v22 import (
    EXACT_INFERENCE_CONTRACT,
    SplitSample,
    build_fixed_test_report,
)
from scripts.evaluate_yolo26n_v24_gate_reuse import (
    build_v24_comparison_report,
    build_fixed_evaluation_plan,
    classify_v24_result,
    run_prediction_once,
    select_v24_threshold,
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validation_ledger() -> dict[str, object]:
    return {
        "schema": "yolo26n-v24-prediction-ledger-v1",
        "status": "V24_PREDICTIONS_READY",
        "dataset_schema": "yolo26n-owner-dataset-v24",
        "evaluation_tier": "development",
        "split": "val",
        "candidate": "warm-start",
        "source_commit": "a" * 40,
        "runner_sha256": "b" * 64,
        "dataset_manifest_sha256": "c" * 64,
        "checkpoint_sha256": "d" * 64,
        "inference": dict(EXACT_INFERENCE_CONTRACT),
        "image_count": 2,
        "gt_box_count": 1,
        "prediction_count": 2,
        "records": [
            {
                "sequence": "V0001",
                "image_sha256": "1" * 64,
                "width": 100,
                "height": 100,
                "gt_boxes": [[10.0, 10.0, 40.0, 40.0]],
                "predictions": [
                    {"confidence": 0.70, "xyxy": [10.0, 10.0, 40.0, 40.0]}
                ],
            },
            {
                "sequence": "V0002",
                "image_sha256": "2" * 64,
                "width": 100,
                "height": 100,
                "gt_boxes": [],
                "predictions": [
                    {"confidence": 0.30, "xyxy": [50.0, 50.0, 80.0, 80.0]}
                ],
            },
        ],
    }


def test_threshold_uses_validation_only_and_fixed_precision_floor() -> None:
    freeze = select_v24_threshold(
        _validation_ledger(),
        validation_ledger_sha256="e" * 64,
        precision_floor=0.60,
    )

    assert freeze["status"] == "V24_THRESHOLD_FROZEN_DEVELOPMENT_ONLY"
    assert freeze["candidate"] == "warm-start"
    assert freeze["precision_floor"] == 0.60
    assert freeze["validation_precision"] >= 0.60
    assert freeze["threshold"] == 0.70
    assert freeze["candidate_checkpoint_sha256"] == {"warm-start": "d" * 64}
    assert freeze["validation_ledger_sha256"] == {"warm-start": "e" * 64}


def test_threshold_rejects_test_ledger_and_nonfixed_precision_floor() -> None:
    ledger = _validation_ledger()
    ledger["split"] = "test"
    with pytest.raises(ValueError, match="validation"):
        select_v24_threshold(ledger, validation_ledger_sha256="e" * 64)
    with pytest.raises(ValueError, match="exactly 0.60"):
        select_v24_threshold(
            _validation_ledger(),
            validation_ledger_sha256="e" * 64,
            precision_floor=0.59,
        )


def test_test_and_external_are_blocked_before_freeze() -> None:
    with pytest.raises(PermissionError, match="threshold freeze"):
        build_fixed_evaluation_plan(freeze=None)


def test_adoption_requires_all_internal_and_external_gates() -> None:
    assert (
        classify_v24_result(
            {"recall": 0.64, "precision": 0.61},
            {"recall": 0.43, "false_positive": 20, "duplicate": 4},
        )
        == "V24_TRAINED_DEVELOPMENT_ONLY"
    )
    assert (
        classify_v24_result(
            {"recall": 0.63, "precision": 0.61},
            {"recall": 0.43, "false_positive": 20, "duplicate": 4},
        )
        == "V24_GATE_REUSE_REJECTED"
    )
    assert (
        classify_v24_result(
            {"recall": 0.64, "precision": 0.61},
            {"recall": 0.43, "false_positive": 21, "duplicate": 4},
        )
        == "V24_GATE_REUSE_REJECTED"
    )


def test_comparison_report_binds_internal_external_and_remains_development_only() -> None:
    report = build_v24_comparison_report(
        internal_report={
            "schema": "yolo26n-v24-fixed-test-report-v1",
            "status": "V24_FIXED_TEST_COMPLETED",
            "evaluation_tier": "development",
            "future_holdout_required": True,
            "candidate": "warm-start",
            "threshold": 0.35,
            "precision": 0.61,
            "recall": 0.64,
        },
        internal_report_sha256="a" * 64,
        external_report={
            "schema": "yolo26n-owner-media-external-diagnostic-report-v1",
            "status": "OWNER_MEDIA_EXTERNAL_DIAGNOSTIC_COMPLETE",
            "threshold": 0.35,
            "image_count": 60,
            "box_recall": 0.43,
            "fp": 20,
            "duplicate_prediction_count": 4,
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
        },
        external_report_sha256="b" * 64,
    )

    assert report["status"] == "V24_TRAINED_DEVELOPMENT_ONLY"
    assert report["production_adoption"] is False
    assert report["future_holdout_required"] is True
    assert report["internal_report_sha256"] == "a" * 64
    assert report["external_report_sha256"] == "b" * 64


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -1])
def test_classification_rejects_nonfinite_or_bool_counts(bad: object) -> None:
    with pytest.raises(ValueError):
        classify_v24_result(
            {"recall": 0.64, "precision": 0.61},
            {"recall": 0.43, "false_positive": bad, "duplicate": 4},
        )


def test_v24_fixed_test_report_consumes_single_candidate_freeze() -> None:
    freeze = select_v24_threshold(
        _validation_ledger(), validation_ledger_sha256="e" * 64
    )
    test_ledger = json.loads(json.dumps(_validation_ledger()))
    test_ledger["split"] = "test"
    test_ledger["threshold_freeze_sha256"] = "f" * 64

    report = build_fixed_test_report(
        test_ledger=test_ledger,
        test_ledger_sha256="1" * 64,
        freeze=freeze,
        freeze_sha256="f" * 64,
    )

    assert report["schema"] == "yolo26n-v24-fixed-test-report-v1"
    assert report["status"] == "V24_FIXED_TEST_COMPLETED"
    assert report["threshold"] == 0.70


def test_prediction_phase_claims_before_inference_and_is_one_shot(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset"
    image = dataset / "images/val/V0001.jpg"
    label = dataset / "labels/val/V0001.txt"
    image.parent.mkdir(parents=True)
    label.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    label.write_text("0 0.5 0.5 0.4 0.4\n")
    manifest = dataset / "manifest.private.json"
    manifest.write_text(json.dumps({"schema": "yolo26n-owner-dataset-v24"}))
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    sample = SplitSample(
        sequence="V0001",
        image_path=image,
        label_path=label,
        image_sha256=_sha(image.read_bytes()),
        label_sha256=_sha(label.read_bytes()),
        normalized_gt_boxes=((0.3, 0.3, 0.7, 0.7),),
    )
    calls = 0

    def predictor(paths, **contract):
        nonlocal calls
        calls += 1
        assert tuple(paths) == (image,)
        assert contract == EXACT_INFERENCE_CONTRACT
        return [
            {
                "width": 100,
                "height": 100,
                "predictions": [
                    {"confidence": 0.7, "xyxy": [30.0, 30.0, 70.0, 70.0]}
                ],
            }
        ]

    evaluation_root = tmp_path / "evaluation"
    output = run_prediction_once(
        evaluation_root=evaluation_root,
        samples=(sample,),
        split="val",
        checkpoint_path=checkpoint,
        dataset_manifest_path=manifest,
        source_commit="a" * 40,
        predictor=predictor,
    )

    assert output["status"] == "V24_PREDICTIONS_READY"
    assert calls == 1
    assert (evaluation_root / "prediction-ledgers/warm-start-val.private.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        run_prediction_once(
            evaluation_root=evaluation_root,
            samples=(sample,),
            split="val",
            checkpoint_path=checkpoint,
            dataset_manifest_path=manifest,
            source_commit="a" * 40,
            predictor=predictor,
        )
    assert calls == 1


def test_test_prediction_rejects_missing_freeze_before_claim_or_inference(
    tmp_path: Path,
) -> None:
    image = tmp_path / "T0001.jpg"
    label = tmp_path / "T0001.txt"
    checkpoint = tmp_path / "best.pt"
    manifest = tmp_path / "manifest.private.json"
    image.write_bytes(b"image")
    label.write_text("0 0.5 0.5 0.4 0.4\n")
    checkpoint.write_bytes(b"checkpoint")
    manifest.write_text(json.dumps({"schema": "yolo26n-owner-dataset-v24"}))
    sample = SplitSample(
        sequence="T0001",
        image_path=image,
        label_path=label,
        image_sha256=_sha(image.read_bytes()),
        label_sha256=_sha(label.read_bytes()),
        normalized_gt_boxes=((0.3, 0.3, 0.7, 0.7),),
    )
    calls = 0

    def predictor(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return []

    evaluation_root = tmp_path / "evaluation"
    with pytest.raises(ValueError, match="frozen threshold"):
        run_prediction_once(
            evaluation_root=evaluation_root,
            samples=(sample,),
            split="test",
            checkpoint_path=checkpoint,
            dataset_manifest_path=manifest,
            source_commit="a" * 40,
            predictor=predictor,
        )

    assert calls == 0
    assert not (evaluation_root / ".locks/predict-warm-start-test.started.private.json").exists()

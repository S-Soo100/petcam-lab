import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.evaluate_yolo26n_v22 import (
    CandidateEvaluation,
    EvaluationRecord,
    PredictionBox,
    SplitSample,
    build_fixed_test_report,
    build_prediction_ledger,
    build_selection_freeze,
    evaluate_threshold,
    expected_prediction_ledger_path,
    expected_test_ledger_path,
    load_split_samples,
    main,
    make_ultralytics_predictor,
    score_prediction_ledger,
    select_development_candidate,
    threshold_grid,
    write_private_json_new,
)


def _prediction_ledger(
    *,
    split: str = "val",
    checkpoint: str = "b" * 64,
    confidence: float = 0.7,
    dataset_sha: str = "4" * 64,
    candidate: str = "warm-start",
):
    return {
        "schema": "yolo26n-v22-prediction-ledger-v1",
        "status": "V22_PREDICTIONS_READY",
        "evaluation_tier": "development",
        "split": split,
        "candidate": candidate,
        "source_commit": "2" * 40,
        "runner_sha256": "3" * 64,
        "dataset_manifest_sha256": dataset_sha,
        "checkpoint_sha256": checkpoint,
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
                "sequence": "A0001",
                "image_sha256": "a" * 64,
                "width": 100,
                "height": 100,
                "gt_boxes": [[0, 0, 10, 10]],
                "predictions": [
                    {"confidence": confidence, "xyxy": [0, 0, 10, 10]},
                ],
            }
        ],
    }


def test_fixed_threshold_counts_tp_fp_fn_without_double_matching():
    records = (
        EvaluationRecord(
            image_sha256="a" * 64,
            gt_boxes=((0.0, 0.0, 10.0, 10.0), (20.0, 20.0, 30.0, 30.0)),
            predictions=(
                PredictionBox(0.90, (0.0, 0.0, 10.0, 10.0)),
                PredictionBox(0.80, (1.0, 1.0, 9.0, 9.0)),
                PredictionBox(0.70, (40.0, 40.0, 50.0, 50.0)),
            ),
        ),
    )

    result = evaluate_threshold(records, threshold=0.50, iou_threshold=0.50)

    assert (result.tp, result.fp, result.fn) == (1, 2, 1)
    assert result.precision == pytest.approx(1 / 3)
    assert result.recall == pytest.approx(1 / 2)


def test_fixed_threshold_is_deterministic_and_excludes_lower_confidence():
    first = EvaluationRecord(
        image_sha256="a" * 64,
        gt_boxes=((0.0, 0.0, 10.0, 10.0),),
        predictions=(
            PredictionBox(0.49, (0.0, 0.0, 10.0, 10.0)),
            PredictionBox(0.90, (20.0, 20.0, 30.0, 30.0)),
        ),
    )
    negative = EvaluationRecord(
        image_sha256="b" * 64,
        gt_boxes=(),
        predictions=(PredictionBox(0.80, (1.0, 1.0, 2.0, 2.0)),),
    )

    forward = evaluate_threshold((first, negative), threshold=0.50)
    reverse = evaluate_threshold((negative, first), threshold=0.50)

    assert forward == reverse
    assert (forward.tp, forward.fp, forward.fn) == (0, 2, 1)
    assert forward.precision == 0.0
    assert forward.recall == 0.0

    invalid = EvaluationRecord(
        image_sha256="c" * 64,
        gt_boxes=(),
        predictions=(PredictionBox(-0.1, (1.0, 1.0, 2.0, 2.0)),),
    )
    with pytest.raises(ValueError, match="confidence"):
        evaluate_threshold((invalid,), threshold=0.50)


def test_threshold_grid_is_exact_from_point_zero_five_through_point_eight():
    assert threshold_grid() == tuple(round(index * 0.05, 2) for index in range(1, 17))


def test_load_split_samples_binds_image_hash_and_rejects_bad_geometry(tmp_path: Path):
    dataset = tmp_path / "dataset"
    image = dataset / "images" / "val" / "A0001.jpg"
    label = dataset / "labels" / "val" / "A0001.txt"
    image.parent.mkdir(parents=True)
    label.parent.mkdir(parents=True)
    image.write_bytes(b"jpeg fixture")
    label.write_text("0 0.5 0.5 0.4 0.2\n")
    manifest = dataset / "manifest.private.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "yolo26n-owner-dataset-v22",
                "records": [
                    {
                        "sequence": "A0001",
                        "split": "val",
                        "image_path": "images/val/A0001.jpg",
                        "label_path": "labels/val/A0001.txt",
                        "image_sha256": hashlib.sha256(b"jpeg fixture").hexdigest(),
                    }
                ],
            }
        )
    )

    samples = load_split_samples(dataset_root=dataset, manifest_path=manifest, split="val")

    assert len(samples) == 1
    assert samples[0].normalized_gt_boxes == ((0.3, 0.4, 0.7, 0.6),)

    label.write_text("0 0.5 0.5 1.2 0.2\n")
    with pytest.raises(ValueError, match="geometry"):
        load_split_samples(dataset_root=dataset, manifest_path=manifest, split="val")

    label.write_text("0 0.5 0.5 0.4 0.2\n")
    payload = json.loads(manifest.read_text())
    payload["records"][0]["image_path"] = "images/test/A0001.jpg"
    payload["records"][0]["label_path"] = "labels/test/A0001.txt"
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="split path"):
        load_split_samples(dataset_root=dataset, manifest_path=manifest, split="val")


def test_private_json_writer_is_mode_0600_and_refuses_overwrite(tmp_path: Path):
    output = tmp_path / "ledger.private.json"

    previous_umask = os.umask(0o777)
    try:
        write_private_json_new(output, {"status": "READY"})
    finally:
        os.umask(previous_umask)

    assert json.loads(output.read_text()) == {"status": "READY"}
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_private_json_new(output, {"status": "OVERWRITE"})


def test_prediction_ledger_runs_inference_once_with_exact_contract(tmp_path: Path):
    image = tmp_path / "A0001.jpg"
    label = tmp_path / "A0001.txt"
    checkpoint = tmp_path / "best.pt"
    manifest = tmp_path / "manifest.private.json"
    image.write_bytes(b"image")
    label.write_text("0 0.5 0.5 0.5 0.5\n")
    checkpoint.write_bytes(b"checkpoint")
    manifest.write_bytes(b"manifest")
    sample = SplitSample(
        sequence="A0001",
        image_path=image,
        label_path=label,
        image_sha256=hashlib.sha256(b"image").hexdigest(),
        label_sha256=hashlib.sha256(label.read_bytes()).hexdigest(),
        normalized_gt_boxes=((0.25, 0.25, 0.75, 0.75),),
    )
    calls = []

    def fake_predictor(paths, **kwargs):
        calls.append((tuple(paths), kwargs))
        return [
            {
                "width": 200,
                "height": 100,
                "predictions": [
                    {"confidence": 0.4, "xyxy": [50, 25, 150, 75]},
                ],
            }
        ]

    ledger = build_prediction_ledger(
        samples=(sample,),
        split="val",
        checkpoint_path=checkpoint,
        dataset_manifest_path=manifest,
        source_commit="a" * 40,
        candidate="warm-start",
        predictor=fake_predictor,
    )

    assert len(calls) == 1
    assert calls[0][0] == (image,)
    assert calls[0][1] == {
        "confidence": 0.001,
        "imgsz": 960,
        "nms_iou": 0.70,
        "max_det": 50,
        "device": "mps",
    }
    assert ledger["image_count"] == 1
    assert ledger["gt_box_count"] == 1
    assert ledger["prediction_count"] == 1
    assert ledger["records"][0]["gt_boxes"] == [[50.0, 25.0, 150.0, 75.0]]

    with pytest.raises(ValueError, match="frozen threshold"):
        build_prediction_ledger(
            samples=(sample,),
            split="test",
            checkpoint_path=checkpoint,
            dataset_manifest_path=manifest,
            source_commit="a" * 40,
            candidate="warm-start",
            predictor=fake_predictor,
        )

    clean_ledger = json.loads(json.dumps(ledger))
    clean_ledger["candidate"] = "clean-reference"
    freeze = build_selection_freeze(
        {"warm-start": ledger, "clean-reference": clean_ledger},
        ledger_sha256={"warm-start": "d" * 64, "clean-reference": "e" * 64},
    )
    test_ledger = build_prediction_ledger(
        samples=(sample,),
        split="test",
        checkpoint_path=checkpoint,
        dataset_manifest_path=manifest,
        source_commit="a" * 40,
        candidate="warm-start",
        predictor=fake_predictor,
        threshold_freeze=freeze,
        threshold_freeze_sha256="f" * 64,
    )
    assert test_ledger["threshold_freeze_sha256"] == "f" * 64

    bad_freeze = dict(freeze, schema="wrong")
    with pytest.raises(ValueError, match="frozen threshold"):
        build_prediction_ledger(
            samples=(sample,),
            split="test",
            checkpoint_path=checkpoint,
            dataset_manifest_path=manifest,
            source_commit="a" * 40,
            candidate="warm-start",
            predictor=fake_predictor,
            threshold_freeze=bad_freeze,
            threshold_freeze_sha256="f" * 64,
        )

    def mutating_predictor(paths, **kwargs):
        checkpoint.write_bytes(b"changed checkpoint")
        return fake_predictor(paths, **kwargs)

    with pytest.raises(ValueError, match="changed during inference"):
        build_prediction_ledger(
            samples=(sample,),
            split="val",
            checkpoint_path=checkpoint,
            dataset_manifest_path=manifest,
            source_commit="a" * 40,
            candidate="warm-start",
            predictor=mutating_predictor,
        )

    checkpoint.write_bytes(b"checkpoint")

    def mutating_image_predictor(paths, **kwargs):
        image.write_bytes(b"changed image")
        return fake_predictor(paths, **kwargs)

    with pytest.raises(ValueError, match="changed during inference"):
        build_prediction_ledger(
            samples=(sample,),
            split="val",
            checkpoint_path=checkpoint,
            dataset_manifest_path=manifest,
            source_commit="a" * 40,
            candidate="warm-start",
            predictor=mutating_image_predictor,
        )


def test_score_ledger_and_select_candidate_without_test_peeking():
    ledger = _prediction_ledger()
    ledger["records"][0]["predictions"].append(
        {"confidence": 0.4, "xyxy": [20, 20, 30, 30]}
    )
    ledger["prediction_count"] = 2

    metrics = score_prediction_ledger(ledger)
    selected = select_development_candidate(
        (
            CandidateEvaluation("warm-start", "b" * 64, metrics),
            CandidateEvaluation(
                "clean-reference",
                "c" * 64,
                tuple(
                    row.__class__(
                        threshold=row.threshold,
                        tp=row.tp,
                        fp=row.fp,
                        fn=row.fn,
                        precision=row.precision,
                        recall=max(0.0, row.recall - 0.1),
                    )
                    for row in metrics
                ),
            ),
        ),
        precision_floor=0.60,
    )

    assert selected.candidate == "warm-start"
    assert selected.threshold == 0.7
    assert selected.validation_recall == 1.0


def test_selection_freeze_precedes_and_binds_one_shot_test():
    warm_val = _prediction_ledger(checkpoint="b" * 64, confidence=0.7)
    clean_val = _prediction_ledger(
        checkpoint="c" * 64, confidence=0.4, candidate="clean-reference"
    )
    freeze = build_selection_freeze(
        {"warm-start": warm_val, "clean-reference": clean_val},
        ledger_sha256={"warm-start": "d" * 64, "clean-reference": "e" * 64},
        precision_floor=0.60,
    )

    assert freeze["status"] == "V22_THRESHOLD_FROZEN_DEVELOPMENT_ONLY"
    assert freeze["candidate"] == "warm-start"
    assert freeze["threshold"] == 0.7

    test_ledger = _prediction_ledger(
        split="test", checkpoint="b" * 64, confidence=0.7
    )
    test_ledger["threshold_freeze_sha256"] = "1" * 64
    report = build_fixed_test_report(
        test_ledger=test_ledger,
        test_ledger_sha256="f" * 64,
        freeze=freeze,
        freeze_sha256="1" * 64,
    )
    assert report["status"] == "V22_FIXED_TEST_COMPLETED"
    assert (report["tp"], report["fp"], report["fn"]) == (1, 0, 0)

    tampered_freeze = json.loads(json.dumps(freeze))
    tampered_freeze["validation_recall"] = 0.123
    with pytest.raises(ValueError, match="selection metrics"):
        build_fixed_test_report(
            test_ledger=test_ledger,
            test_ledger_sha256="f" * 64,
            freeze=tampered_freeze,
            freeze_sha256="1" * 64,
        )

    arbitrary_checkpoint_freeze = json.loads(json.dumps(freeze))
    arbitrary_checkpoint_freeze["checkpoint_sha256"] = "9" * 64
    arbitrary_test_ledger = _prediction_ledger(
        split="test", checkpoint="9" * 64, confidence=0.7
    )
    arbitrary_test_ledger["threshold_freeze_sha256"] = "1" * 64
    with pytest.raises(ValueError, match="checkpoint lineage"):
        build_fixed_test_report(
            test_ledger=arbitrary_test_ledger,
            test_ledger_sha256="f" * 64,
            freeze=arbitrary_checkpoint_freeze,
            freeze_sha256="1" * 64,
        )

    test_ledger["checkpoint_sha256"] = "9" * 64
    with pytest.raises(ValueError, match="checkpoint"):
        build_fixed_test_report(
            test_ledger=test_ledger,
            test_ledger_sha256="f" * 64,
            freeze=freeze,
            freeze_sha256="1" * 64,
        )


def test_freeze_rejects_contract_mismatch_duplicate_counts_and_floor_override():
    warm = _prediction_ledger(checkpoint="b" * 64)
    clean = _prediction_ledger(
        checkpoint="c" * 64, dataset_sha="5" * 64, candidate="clean-reference"
    )
    with pytest.raises(ValueError, match="evaluation contract"):
        build_selection_freeze(
            {"warm-start": warm, "clean-reference": clean},
            ledger_sha256={"warm-start": "d" * 64, "clean-reference": "e" * 64},
        )
    clean = _prediction_ledger(checkpoint="c" * 64, candidate="clean-reference")
    with pytest.raises(ValueError, match="exactly 0.60"):
        build_selection_freeze(
            {"warm-start": warm, "clean-reference": clean},
            ledger_sha256={"warm-start": "d" * 64, "clean-reference": "e" * 64},
            precision_floor=0.0,
        )
    warm["records"].append(dict(warm["records"][0]))
    with pytest.raises(ValueError, match="count|duplicate"):
        score_prediction_ledger(warm)


def test_fixed_test_rejects_different_dataset_or_inference():
    warm = _prediction_ledger(checkpoint="b" * 64)
    clean = _prediction_ledger(checkpoint="c" * 64, candidate="clean-reference")
    freeze = build_selection_freeze(
        {"warm-start": warm, "clean-reference": clean},
        ledger_sha256={"warm-start": "d" * 64, "clean-reference": "e" * 64},
    )
    test_ledger = _prediction_ledger(
        split="test", checkpoint=freeze["checkpoint_sha256"], dataset_sha="9" * 64
    )
    test_ledger["threshold_freeze_sha256"] = "1" * 64
    with pytest.raises(ValueError, match="evaluation contract"):
        build_fixed_test_report(
            test_ledger=test_ledger,
            test_ledger_sha256="f" * 64,
            freeze=freeze,
            freeze_sha256="1" * 64,
        )


def test_test_ledger_has_one_exact_output_path(tmp_path: Path):
    freeze_path = tmp_path / "threshold-freeze.private.json"
    freeze = {"candidate": "warm-start"}
    assert expected_test_ledger_path(freeze_path, freeze) == (
        tmp_path / "prediction-ledgers" / "warm-start-test.private.json"
    )
    with pytest.raises(ValueError, match="candidate"):
        expected_test_ledger_path(freeze_path, {"candidate": "../escape"})

    assert expected_prediction_ledger_path(
        tmp_path, candidate="clean-reference", split="val"
    ) == (tmp_path / "prediction-ledgers" / "clean-reference-val.private.json")


def test_cli_entrypoints_show_help():
    root = Path(__file__).resolve().parents[1]
    for command in (
        [sys.executable, str(root / "scripts/evaluate_yolo26n_v22.py"), "--help"],
        [sys.executable, "-m", "scripts.evaluate_yolo26n_v22", "--help"],
    ):
        completed = subprocess.run(
            command, cwd=root, capture_output=True, text=True, check=False
        )
        assert completed.returncode == 0, completed.stderr


def test_predict_claims_one_shot_before_second_inference(tmp_path: Path, monkeypatch):
    dataset = tmp_path / "dataset"
    image = dataset / "images/val/A0001.jpg"
    label = dataset / "labels/val/A0001.txt"
    image.parent.mkdir(parents=True)
    label.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    label.write_text("0 0.5 0.5 0.4 0.2\n")
    manifest = dataset / "manifest.private.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "yolo26n-owner-dataset-v22",
                "records": [
                    {
                        "sequence": "A0001",
                        "split": "val",
                        "image_path": "images/val/A0001.jpg",
                        "label_path": "labels/val/A0001.txt",
                        "image_sha256": hashlib.sha256(b"image").hexdigest(),
                    }
                ],
            }
        )
    )
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    calls = []

    def predictor(paths, **kwargs):
        calls.append(tuple(paths))
        return [{"width": 100, "height": 100, "predictions": []}]

    monkeypatch.setattr(
        "scripts.evaluate_yolo26n_v22.make_ultralytics_predictor",
        lambda **_: predictor,
    )
    argv = [
        "predict",
        "--dataset-root",
        str(dataset),
        "--manifest",
        str(manifest),
        "--split",
        "val",
        "--checkpoint",
        str(checkpoint),
        "--source-commit",
        "a" * 40,
        "--candidate",
        "warm-start",
        "--evaluation-root",
        str(tmp_path / "evaluation"),
    ]

    assert main(argv) == 0
    assert len(calls) == 1
    with pytest.raises(FileExistsError):
        main(argv)
    assert len(calls) == 1


def test_ultralytics_adapter_preserves_input_order_and_contract(tmp_path: Path):
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    calls = []

    class FakeBoxes:
        xyxy = type(
            "Tensor",
            (),
            {"cpu": lambda self: self, "tolist": lambda self: [[1, 2, 3, 4]]},
        )()
        conf = type("Tensor", (), {"cpu": lambda self: self, "tolist": lambda self: [0.25]})()

    class FakeResult:
        def __init__(self, path):
            self.path = str(path)
            self.orig_shape = (100, 200)
            self.boxes = FakeBoxes()

    class FakeModel:
        def predict(self, **kwargs):
            calls.append(kwargs)
            return [FakeResult(path) for path in kwargs["source"]]

    predictor = make_ultralytics_predictor(
        checkpoint_path=tmp_path / "best.pt",
        model_factory=lambda _: FakeModel(),
    )
    rows = predictor(
        [first, second],
        confidence=0.001,
        imgsz=960,
        nms_iou=0.70,
        max_det=50,
        device="mps",
    )

    assert len(calls) == 1
    assert calls[0]["source"] == [str(first), str(second)]
    assert calls[0]["conf"] == 0.001
    assert calls[0]["iou"] == 0.70
    assert rows[0]["width"] == 200
    assert rows[0]["height"] == 100
    assert rows[0]["predictions"] == [{"confidence": 0.25, "xyxy": [1, 2, 3, 4]}]

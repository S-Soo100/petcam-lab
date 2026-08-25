import hashlib
import json
from pathlib import Path

import pytest

from scripts.evaluate_yolo26n_v25 import (
    INFERENCE_CONTRACT,
    build_fixed_test_report,
    build_selection_freeze,
    run_prediction_once,
    select_v25_candidate,
)


def _ledger(candidate: str, predictions: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema": "yolo26n-v25-prediction-ledger-v1",
        "status": "V25_PREDICTIONS_READY",
        "evaluation_tier": "development",
        "split": "val",
        "candidate": candidate,
        "source_commit": "a" * 40,
        "runner_sha256": "b" * 64,
        "dataset_manifest_sha256": "c" * 64,
        "checkpoint_sha256": {"baseline-v24": "d", "warm-start": "e", "clean-reference": "f"}[candidate] * 64,
        "inference": INFERENCE_CONTRACT,
        "image_count": 1,
        "gt_box_count": 1,
        "prediction_count": len(predictions),
        "records": [
            {
                "sequence": "S0001",
                "image_sha256": "1" * 64,
                "width": 100,
                "height": 100,
                "gt_boxes": [[10, 10, 50, 50]],
                "predictions": predictions,
            }
        ],
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "deploy_count": 0,
    }


def test_selects_highest_recall_above_fixed_precision_floor() -> None:
    freeze = select_v25_candidate(
        {
            "warm-start": [
                {"threshold": 0.20, "precision": 0.61, "recall": 0.70, "fp": 20, "duplicate": 3},
                {"threshold": 0.25, "precision": 0.70, "recall": 0.65, "fp": 10, "duplicate": 1},
            ],
            "clean-reference": [
                {"threshold": 0.30, "precision": 0.62, "recall": 0.68, "fp": 9, "duplicate": 0},
            ],
        }
    )
    assert freeze["candidate"] == "warm-start"
    assert freeze["threshold"] == 0.20
    assert "baseline_remeasured_same_protocol" not in freeze


def test_freeze_requires_actual_same_protocol_baseline_ledger() -> None:
    ledgers = {
        "baseline-v24": _ledger("baseline-v24", [{"confidence": 0.9, "xyxy": [10, 10, 50, 50]}]),
        "warm-start": _ledger("warm-start", [{"confidence": 0.9, "xyxy": [10, 10, 50, 50]}]),
        "clean-reference": _ledger("clean-reference", []),
    }
    freeze = build_selection_freeze(ledgers, ledger_sha256={name: str(index) * 64 for index, name in enumerate(ledgers, 2)})
    assert freeze["baseline_remeasured_same_protocol"] is True
    assert set(freeze["validation_ledger_sha256"]) == set(ledgers)
    assert freeze["candidate"] == "warm-start"

    del ledgers["baseline-v24"]
    with pytest.raises(ValueError, match="baseline"):
        build_selection_freeze(ledgers, ledger_sha256={"warm-start": "3" * 64, "clean-reference": "4" * 64})


def test_global_tie_break_prefers_duplicate_then_fp_then_warm() -> None:
    freeze = select_v25_candidate(
        {
            "warm-start": [{"threshold": 0.20, "precision": 0.60, "recall": 0.70, "fp": 4, "duplicate": 1}],
            "clean-reference": [{"threshold": 0.20, "precision": 0.60, "recall": 0.70, "fp": 3, "duplicate": 1}],
        }
    )
    assert freeze["candidate"] == "clean-reference"


def test_rejects_floor_override_and_shortage() -> None:
    with pytest.raises(ValueError):
        select_v25_candidate({"warm-start": []}, precision_floor=0.5)
    with pytest.raises(ValueError, match="V25_VALIDATION_SHORTAGE"):
        select_v25_candidate(
            {
                "warm-start": [{"threshold": 0.2, "precision": 0.59, "recall": 0.9, "fp": 1, "duplicate": 0}],
                "clean-reference": [{"threshold": 0.2, "precision": 0.58, "recall": 0.9, "fp": 1, "duplicate": 0}],
            }
        )


def test_prediction_claims_before_inference_and_cannot_repeat(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    (dataset / "images/val").mkdir(parents=True)
    (dataset / "labels/val").mkdir(parents=True)
    records = []
    for index in range(1, 154):
        sequence = f"S{index:04d}"
        payload = f"image-{index}".encode()
        image = dataset / f"images/val/{sequence}.jpg"
        label = dataset / f"labels/val/{sequence}.txt"
        image.write_bytes(payload)
        label.write_text("0 0.5 0.5 0.4 0.4\n")
        records.append({"sequence": sequence, "split": "val", "image_path": f"images/val/{sequence}.jpg", "label_path": f"labels/val/{sequence}.txt", "image_sha256": hashlib.sha256(payload).hexdigest()})
    manifest = dataset / "manifest.private.json"
    manifest.write_text(json.dumps({
        "schema": "yolo26n-owner-dataset-v25", "status": "V25_DATASET_READY",
        "evaluation_tier": "development", "split_counts": {"train": 1659, "val": 153, "test": 151},
        "records": records,
    }))
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model")
    calls = 0

    def predictor(_paths, **_contract):
        nonlocal calls
        calls += 1
        return [{"width": 100, "height": 100, "predictions": []} for _ in range(153)]

    kwargs = dict(
        dataset_root=dataset, manifest_path=manifest, split="val", candidate="baseline-v24",
        checkpoint_path=checkpoint, source_commit="a" * 40, evaluation_root=tmp_path / "evaluation",
        predictor=predictor,
    )
    run_prediction_once(**kwargs)
    with pytest.raises(FileExistsError):
        run_prediction_once(**kwargs)
    assert calls == 1


def test_fixed_report_compares_baseline_and_selected_under_frozen_threshold() -> None:
    ledgers = {
        "baseline-v24": _ledger("baseline-v24", [{"confidence": 0.9, "xyxy": [10, 10, 50, 50]}]),
        "warm-start": _ledger("warm-start", [{"confidence": 0.9, "xyxy": [10, 10, 50, 50]}]),
        "clean-reference": _ledger("clean-reference", []),
    }
    freeze = build_selection_freeze(ledgers, ledger_sha256={name: str(index) * 64 for index, name in enumerate(ledgers, 2)})
    freeze_sha = hashlib.sha256(json.dumps(freeze, sort_keys=True).encode()).hexdigest()
    tests = {}
    for name in ("baseline-v24", freeze["candidate"]):
        value = json.loads(json.dumps(ledgers[name]))
        value["split"] = "test"
        value["threshold_freeze_sha256"] = freeze_sha
        tests[name] = value
    report = build_fixed_test_report(
        test_ledgers=tests,
        test_ledger_sha256={name: ("8" if name == "baseline-v24" else "9") * 64 for name in tests},
        freeze=freeze,
        freeze_sha256=freeze_sha,
    )
    assert report["status"] == "V25_FIXED_TEST_COMPLETED_DEVELOPMENT_ONLY"
    assert set(report["metrics"]) == {"baseline-v24", freeze["candidate"]}

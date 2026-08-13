"""Freeze and evaluate the single YOLO26n v2.4 warm-start candidate."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Callable, Mapping, Sequence

try:
    from scripts.evaluate_yolo26n_v22 import (
        EXACT_INFERENCE_CONTRACT,
        SplitSample,
        _claim_started,
        _ground_truth_contract_sha256,
        _is_sha,
        _read_json_and_sha,
        _validate_threshold_freeze,
        build_fixed_test_report,
        build_prediction_ledger,
        load_split_samples,
        make_ultralytics_predictor,
        score_prediction_ledger,
        write_private_json_new,
    )
    from scripts.select_yolo26n_v22_threshold import (
        ThresholdMetric,
        select_threshold,
    )
except ModuleNotFoundError:  # Direct ``python scripts/...py`` execution.
    from evaluate_yolo26n_v22 import (  # type: ignore[no-redef]
        EXACT_INFERENCE_CONTRACT,
        SplitSample,
        _claim_started,
        _ground_truth_contract_sha256,
        _is_sha,
        _read_json_and_sha,
        _validate_threshold_freeze,
        build_fixed_test_report,
        build_prediction_ledger,
        load_split_samples,
        make_ultralytics_predictor,
        score_prediction_ledger,
        write_private_json_new,
    )
    from select_yolo26n_v22_threshold import (  # type: ignore[no-redef]
        ThresholdMetric,
        select_threshold,
    )


INTERNAL_RECALL_FLOOR = 0.6389
INTERNAL_PRECISION_FLOOR = 0.60
EXTERNAL_RECALL_FLOOR = 0.4211
EXTERNAL_FALSE_POSITIVE_CEILING = 20
EXTERNAL_DUPLICATE_CEILING = 4


def _metric_payload(row: object) -> dict[str, object]:
    return {
        "threshold": row.threshold,
        "tp": row.tp,
        "fp": row.fp,
        "fn": row.fn,
        "precision": row.precision,
        "recall": row.recall,
    }


def select_v24_threshold(
    validation_ledger: Mapping[str, object],
    *,
    validation_ledger_sha256: str,
    precision_floor: float = 0.60,
) -> dict[str, object]:
    """Freeze one validation-only threshold without introducing a clean model."""
    if precision_floor != 0.60:
        raise ValueError("precision floor must be exactly 0.60")
    if not _is_sha(validation_ledger_sha256):
        raise ValueError("validation ledger SHA-256 is invalid")
    if (
        validation_ledger.get("dataset_schema") != "yolo26n-owner-dataset-v24"
        or validation_ledger.get("split") != "val"
        or validation_ledger.get("candidate") != "warm-start"
    ):
        raise ValueError("v2.4 threshold selection accepts one warm validation ledger only")
    checkpoint_sha256 = validation_ledger.get("checkpoint_sha256")
    if not _is_sha(checkpoint_sha256):
        raise ValueError("validation checkpoint SHA-256 is invalid")
    metrics = score_prediction_ledger(validation_ledger)
    selected = select_threshold(
        (
            ThresholdMetric(row.threshold, row.precision, row.recall)
            for row in metrics
        ),
        precision_floor=precision_floor,
    )
    freeze: dict[str, object] = {
        "schema": "yolo26n-v24-candidate-threshold-freeze-v1",
        "status": "V24_THRESHOLD_FROZEN_DEVELOPMENT_ONLY",
        "dataset_schema": "yolo26n-owner-dataset-v24",
        "evaluation_tier": "development",
        "future_holdout_required": True,
        "precision_floor": precision_floor,
        "candidate": "warm-start",
        "checkpoint_sha256": checkpoint_sha256,
        "candidate_checkpoint_sha256": {"warm-start": checkpoint_sha256},
        "threshold": selected.threshold,
        "validation_precision": selected.precision,
        "validation_recall": selected.recall,
        "validation_ledger_sha256": {
            "warm-start": validation_ledger_sha256
        },
        "dataset_manifest_sha256": validation_ledger.get(
            "dataset_manifest_sha256"
        ),
        "source_commit": validation_ledger.get("source_commit"),
        "runner_sha256": validation_ledger.get("runner_sha256"),
        "inference": validation_ledger.get("inference"),
        "validation_ground_truth_sha256": _ground_truth_contract_sha256(
            validation_ledger
        ),
        "candidate_metrics": {
            "warm-start": [_metric_payload(row) for row in metrics]
        },
    }
    _validate_threshold_freeze(freeze)
    return freeze


def build_fixed_evaluation_plan(
    *, freeze: Mapping[str, object] | None
) -> dict[str, object]:
    if freeze is None:
        raise PermissionError("threshold freeze is required before fixed evaluation")
    _validate_threshold_freeze(freeze)
    return {
        "status": "V24_FIXED_EVALUATION_READY",
        "candidate": "warm-start",
        "threshold": freeze["threshold"],
        "internal_test_inference_count": 1,
        "external_inference_count": 1,
    }


def _strict_metric(
    metrics: Mapping[str, object], key: str, *, probability: bool = False
) -> float:
    value = metrics.get(key)
    if type(value) not in (int, float):
        raise ValueError(f"{key} metric is invalid")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{key} metric is invalid")
    if probability and not 0.0 <= number <= 1.0:
        raise ValueError(f"{key} metric is invalid")
    if not probability and number < 0:
        raise ValueError(f"{key} metric is invalid")
    return number


def classify_v24_result(
    internal_metrics: Mapping[str, object], external_metrics: Mapping[str, object]
) -> str:
    internal_recall = _strict_metric(internal_metrics, "recall", probability=True)
    internal_precision = _strict_metric(
        internal_metrics, "precision", probability=True
    )
    external_recall = _strict_metric(external_metrics, "recall", probability=True)
    false_positive = _strict_metric(external_metrics, "false_positive")
    duplicate = _strict_metric(external_metrics, "duplicate")
    if (
        internal_recall >= INTERNAL_RECALL_FLOOR
        and internal_precision >= INTERNAL_PRECISION_FLOOR
        and external_recall >= EXTERNAL_RECALL_FLOOR
        and false_positive <= EXTERNAL_FALSE_POSITIVE_CEILING
        and duplicate <= EXTERNAL_DUPLICATE_CEILING
    ):
        return "V24_TRAINED_DEVELOPMENT_ONLY"
    return "V24_GATE_REUSE_REJECTED"


def build_v24_comparison_report(
    *,
    internal_report: Mapping[str, object],
    internal_report_sha256: str,
    external_report: Mapping[str, object],
    external_report_sha256: str,
) -> dict[str, object]:
    if not _is_sha(internal_report_sha256) or not _is_sha(external_report_sha256):
        raise ValueError("comparison input SHA-256 is invalid")
    if (
        internal_report.get("schema") != "yolo26n-v24-fixed-test-report-v1"
        or internal_report.get("status") != "V24_FIXED_TEST_COMPLETED"
        or internal_report.get("evaluation_tier") != "development"
        or internal_report.get("future_holdout_required") is not True
        or internal_report.get("candidate") != "warm-start"
    ):
        raise ValueError("internal fixed-test report contract mismatch")
    if (
        external_report.get("schema")
        != "yolo26n-owner-media-external-diagnostic-report-v1"
        or external_report.get("status")
        != "OWNER_MEDIA_EXTERNAL_DIAGNOSTIC_COMPLETE"
        or external_report.get("image_count") != 60
        or any(
            external_report.get(key) != 0
            for key in ("db_write_count", "r2_write_count", "service_write_count")
        )
        or external_report.get("threshold") != internal_report.get("threshold")
    ):
        raise ValueError("external diagnostic report contract mismatch")
    internal = {
        "recall": internal_report.get("recall"),
        "precision": internal_report.get("precision"),
    }
    external = {
        "recall": external_report.get("box_recall"),
        "false_positive": external_report.get("fp"),
        "duplicate": external_report.get("duplicate_prediction_count"),
    }
    decision = classify_v24_result(internal, external)
    return {
        "schema": "yolo26n-v24-gate-reuse-comparison-v1",
        "status": decision,
        "evaluation_tier": "development",
        "production_adoption": False,
        "future_holdout_required": True,
        "candidate": "warm-start",
        "threshold": internal_report["threshold"],
        "internal": dict(internal),
        "external": dict(external),
        "internal_report_sha256": internal_report_sha256,
        "external_report_sha256": external_report_sha256,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def _prediction_path(evaluation_root: Path, *, split: str) -> Path:
    if split not in {"val", "test"}:
        raise ValueError("prediction split must be val or test")
    return evaluation_root / "prediction-ledgers" / f"warm-start-{split}.private.json"


def run_prediction_once(
    *,
    evaluation_root: Path,
    samples: Sequence[SplitSample],
    split: str,
    checkpoint_path: Path,
    dataset_manifest_path: Path,
    source_commit: str,
    predictor: Callable[..., Sequence[Mapping[str, object]]],
    threshold_freeze: Mapping[str, object] | None = None,
    threshold_freeze_sha256: str | None = None,
) -> dict[str, object]:
    output = _prediction_path(evaluation_root, split=split)
    if output.exists():
        raise FileExistsError(output)
    if split == "test":
        if threshold_freeze is None or not _is_sha(threshold_freeze_sha256):
            raise ValueError("test prediction requires a frozen threshold artifact")
        build_fixed_evaluation_plan(freeze=threshold_freeze)
    elif threshold_freeze is not None or threshold_freeze_sha256 is not None:
        raise ValueError("validation prediction must not consume a threshold freeze")
    _claim_started(
        evaluation_root,
        operation=f"predict-warm-start-{split}",
        details={"candidate": "warm-start", "split": split},
    )
    ledger = build_prediction_ledger(
        samples=samples,
        split=split,
        checkpoint_path=checkpoint_path,
        dataset_manifest_path=dataset_manifest_path,
        source_commit=source_commit,
        candidate="warm-start",
        predictor=predictor,
        threshold_freeze=threshold_freeze,
        threshold_freeze_sha256=threshold_freeze_sha256,
    )
    write_private_json_new(output, ledger)
    return ledger


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    predict = commands.add_parser("predict")
    predict.add_argument("--dataset-root", type=Path, required=True)
    predict.add_argument("--manifest", type=Path, required=True)
    predict.add_argument("--split", choices=("val", "test"), required=True)
    predict.add_argument("--checkpoint", type=Path, required=True)
    predict.add_argument("--source-commit", required=True)
    predict.add_argument("--evaluation-root", type=Path, required=True)
    predict.add_argument("--freeze", type=Path)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--evaluation-root", type=Path, required=True)
    fixed = commands.add_parser("fixed-test")
    fixed.add_argument("--evaluation-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "predict":
        freeze = freeze_sha = None
        if args.split == "test":
            expected = args.evaluation_root / "threshold-freeze.private.json"
            if args.freeze is None or args.freeze.resolve() != expected.resolve():
                raise ValueError("test prediction requires the exact v2.4 freeze")
            freeze, freeze_sha = _read_json_and_sha(expected)
            build_fixed_evaluation_plan(freeze=freeze)
        elif args.freeze is not None:
            raise ValueError("validation prediction must not use a freeze")
        samples = load_split_samples(
            dataset_root=args.dataset_root,
            manifest_path=args.manifest,
            split=args.split,
        )
        ledger = run_prediction_once(
            evaluation_root=args.evaluation_root,
            samples=samples,
            split=args.split,
            checkpoint_path=args.checkpoint,
            dataset_manifest_path=args.manifest,
            source_commit=args.source_commit,
            predictor=make_ultralytics_predictor(
                checkpoint_path=args.checkpoint
            ),
            threshold_freeze=freeze,
            threshold_freeze_sha256=freeze_sha,
        )
        print(json.dumps({"status": ledger["status"], "image_count": ledger["image_count"]}))
        return 0
    if args.command == "freeze":
        output = args.evaluation_root / "threshold-freeze.private.json"
        if output.exists():
            raise FileExistsError(output)
        ledger_path = _prediction_path(args.evaluation_root, split="val")
        ledger, ledger_sha = _read_json_and_sha(ledger_path)
        _claim_started(
            args.evaluation_root,
            operation="freeze-warm-start",
            details={"candidate": "warm-start", "split": "val"},
        )
        freeze = select_v24_threshold(
            ledger, validation_ledger_sha256=ledger_sha
        )
        write_private_json_new(output, freeze)
        print(json.dumps({"status": freeze["status"], "threshold": freeze["threshold"]}))
        return 0
    freeze_path = args.evaluation_root / "threshold-freeze.private.json"
    freeze, freeze_sha = _read_json_and_sha(freeze_path)
    build_fixed_evaluation_plan(freeze=freeze)
    output = args.evaluation_root / "fixed-test-report.private.json"
    if output.exists():
        raise FileExistsError(output)
    ledger_path = _prediction_path(args.evaluation_root, split="test")
    ledger, ledger_sha = _read_json_and_sha(ledger_path)
    _claim_started(
        args.evaluation_root,
        operation="fixed-test",
        details={"candidate": "warm-start", "split": "test"},
    )
    report = build_fixed_test_report(
        test_ledger=ledger,
        test_ledger_sha256=ledger_sha,
        freeze=freeze,
        freeze_sha256=freeze_sha,
    )
    write_private_json_new(output, report)
    print(json.dumps({"status": report["status"], "precision": report["precision"], "recall": report["recall"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

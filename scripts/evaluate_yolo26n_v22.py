"""Evaluate YOLO26n v2.2 prediction ledgers at fixed thresholds.

The pure helpers in this module deliberately keep inference separate from scoring:
one low-confidence prediction ledger can be rescored without running the model again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

try:
    from scripts.select_yolo26n_v22_threshold import (
        ThresholdMetric,
        ThresholdSelectionError,
        select_threshold,
    )
except ModuleNotFoundError:  # Direct `python scripts/...py` execution.
    from select_yolo26n_v22_threshold import (  # type: ignore[no-redef]
        ThresholdMetric,
        ThresholdSelectionError,
        select_threshold,
    )


Box = tuple[float, float, float, float]
EXACT_INFERENCE_CONTRACT: dict[str, object] = {
    "confidence": 0.001,
    "imgsz": 960,
    "nms_iou": 0.70,
    "max_det": 50,
    "device": "mps",
}


@dataclass(frozen=True)
class PredictionBox:
    confidence: float
    xyxy: Box


@dataclass(frozen=True)
class EvaluationRecord:
    image_sha256: str
    gt_boxes: tuple[Box, ...]
    predictions: tuple[PredictionBox, ...]


@dataclass(frozen=True)
class ThresholdEvaluation:
    threshold: float
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float


@dataclass(frozen=True)
class SplitSample:
    sequence: str
    image_path: Path
    label_path: Path
    image_sha256: str
    label_sha256: str
    normalized_gt_boxes: tuple[Box, ...]


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate: str
    checkpoint_sha256: str
    metrics: tuple[ThresholdEvaluation, ...]


@dataclass(frozen=True)
class CandidateSelection:
    candidate: str
    checkpoint_sha256: str
    threshold: float
    validation_precision: float
    validation_recall: float


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def _validate_box(box: Sequence[float], *, normalized: bool = False) -> Box:
    if len(box) != 4 or not all(_finite_number(value) for value in box):
        raise ValueError("box geometry must contain four finite numbers")
    x1, y1, x2, y2 = (float(value) for value in box)
    if x1 >= x2 or y1 >= y2:
        raise ValueError("box geometry must have positive width and height")
    if normalized and not all(0.0 <= value <= 1.0 for value in (x1, y1, x2, y2)):
        raise ValueError("normalized box geometry must stay inside the image")
    return x1, y1, x2, y2


def _iou(left: Box, right: Box) -> float:
    intersection_width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    intersection_height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    intersection = intersection_width * intersection_height
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def evaluate_threshold(
    records: Iterable[EvaluationRecord],
    *,
    threshold: float,
    iou_threshold: float = 0.50,
) -> ThresholdEvaluation:
    if not _finite_number(threshold) or not 0.0 <= float(threshold) <= 1.0:
        raise ValueError("threshold must be a finite probability")
    if not _finite_number(iou_threshold) or not 0.0 <= float(iou_threshold) <= 1.0:
        raise ValueError("IoU threshold must be a finite probability")

    tp = fp = fn = 0
    ordered_records = sorted(tuple(records), key=lambda record: record.image_sha256)
    for record in ordered_records:
        gt_boxes = tuple(_validate_box(box) for box in record.gt_boxes)
        for prediction in record.predictions:
            if (
                not _finite_number(prediction.confidence)
                or not 0.0 <= float(prediction.confidence) <= 1.0
            ):
                raise ValueError("prediction confidence must be a finite probability")
            _validate_box(prediction.xyxy)
        predictions = sorted(
            (
                prediction
                for prediction in record.predictions
                if prediction.confidence >= float(threshold)
            ),
            key=lambda prediction: (-prediction.confidence, prediction.xyxy),
        )
        matched: set[int] = set()
        for prediction in predictions:
            prediction_box = _validate_box(prediction.xyxy)
            eligible = [
                (_iou(prediction_box, gt_box), index)
                for index, gt_box in enumerate(gt_boxes)
                if index not in matched
            ]
            best_iou, best_index = max(eligible, default=(0.0, -1))
            if best_index >= 0 and best_iou >= float(iou_threshold):
                matched.add(best_index)
                tp += 1
            else:
                fp += 1
        fn += len(gt_boxes) - len(matched)

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return ThresholdEvaluation(
        threshold=float(threshold),
        tp=tp,
        fp=fp,
        fn=fn,
        precision=precision,
        recall=recall,
    )


def threshold_grid() -> tuple[float, ...]:
    return tuple(round(index * 0.05, 2) for index in range(1, 17))


def _is_sha(value: object, *, length: int = 64) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def build_prediction_ledger(
    *,
    samples: Sequence[SplitSample],
    split: str,
    checkpoint_path: Path,
    dataset_manifest_path: Path,
    source_commit: str,
    candidate: str,
    predictor: Callable[..., Sequence[Mapping[str, object]]],
    threshold_freeze: Mapping[str, object] | None = None,
    threshold_freeze_sha256: str | None = None,
) -> dict[str, object]:
    if split not in {"val", "test"}:
        raise ValueError("prediction split must be val or test")
    if candidate not in {"warm-start", "clean-reference"}:
        raise ValueError("prediction candidate is invalid")
    if not samples:
        raise ValueError("prediction samples must not be empty")
    if not _is_sha(source_commit, length=40):
        raise ValueError("source commit must be a lowercase 40-character SHA")
    if not checkpoint_path.is_file() or not dataset_manifest_path.is_file():
        raise FileNotFoundError("checkpoint or dataset manifest is missing")

    runner_sha256 = _sha256(Path(__file__))
    manifest_sha256 = _sha256(dataset_manifest_path)
    checkpoint_sha256 = _sha256(checkpoint_path)
    sample_input_hashes = tuple(
        (_sha256(sample.image_path), _sha256(sample.label_path)) for sample in samples
    )
    if any(
        image_sha != sample.image_sha256 or label_sha != sample.label_sha256
        for sample, (image_sha, label_sha) in zip(
            samples, sample_input_hashes, strict=True
        )
    ):
        raise ValueError("evaluation sample input SHA-256 mismatch")
    if split == "test":
        if (
            threshold_freeze is None
            or not _is_sha(threshold_freeze_sha256)
        ):
            raise ValueError("test prediction requires a frozen threshold artifact")
        _validate_threshold_freeze(threshold_freeze)
        expected = {
            "checkpoint_sha256": checkpoint_sha256,
            "dataset_manifest_sha256": manifest_sha256,
            "source_commit": source_commit,
            "runner_sha256": runner_sha256,
            "inference": EXACT_INFERENCE_CONTRACT,
            "candidate": candidate,
        }
        if any(threshold_freeze.get(key) != value for key, value in expected.items()):
            raise ValueError("test prediction does not match the frozen evaluation contract")
    elif threshold_freeze is not None or threshold_freeze_sha256 is not None:
        raise ValueError("validation prediction must not consume a threshold freeze")

    inference_contract = dict(EXACT_INFERENCE_CONTRACT)
    raw_results = tuple(
        predictor(
            [sample.image_path for sample in samples],
            **inference_contract,
        )
    )
    if len(raw_results) != len(samples):
        raise ValueError("predictor result count does not match samples")
    if (
        _sha256(Path(__file__)) != runner_sha256
        or _sha256(dataset_manifest_path) != manifest_sha256
        or _sha256(checkpoint_path) != checkpoint_sha256
        or tuple(
            (_sha256(sample.image_path), _sha256(sample.label_path))
            for sample in samples
        )
        != sample_input_hashes
    ):
        raise ValueError("evaluation input changed during inference")

    records: list[dict[str, object]] = []
    total_gt = total_predictions = 0
    for sample, raw_result in zip(samples, raw_results, strict=True):
        width = raw_result.get("width")
        height = raw_result.get("height")
        if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
            raise ValueError("predictor dimensions must be positive integers")
        raw_predictions = raw_result.get("predictions")
        if not isinstance(raw_predictions, list):
            raise ValueError("predictor predictions must be a list")
        gt_boxes = [
            [x1 * width, y1 * height, x2 * width, y2 * height]
            for x1, y1, x2, y2 in sample.normalized_gt_boxes
        ]
        predictions: list[dict[str, object]] = []
        for raw_prediction in raw_predictions:
            if not isinstance(raw_prediction, Mapping):
                raise ValueError("prediction rows must be mappings")
            confidence = raw_prediction.get("confidence")
            xyxy = raw_prediction.get("xyxy")
            if (
                not _finite_number(confidence)
                or not 0.0 <= float(confidence) <= 1.0
                or not isinstance(xyxy, Sequence)
            ):
                raise ValueError("prediction row is invalid")
            predictions.append(
                {
                    "confidence": float(confidence),
                    "xyxy": list(_validate_box(xyxy)),
                }
            )
        predictions.sort(key=lambda row: (-row["confidence"], row["xyxy"]))
        total_gt += len(gt_boxes)
        total_predictions += len(predictions)
        records.append(
            {
                "sequence": sample.sequence,
                "image_sha256": sample.image_sha256,
                "width": width,
                "height": height,
                "gt_boxes": gt_boxes,
                "predictions": predictions,
            }
        )

    ledger = {
        "schema": "yolo26n-v22-prediction-ledger-v1",
        "status": "V22_PREDICTIONS_READY",
        "evaluation_tier": "development",
        "split": split,
        "candidate": candidate,
        "source_commit": source_commit,
        "runner_sha256": runner_sha256,
        "dataset_manifest_sha256": manifest_sha256,
        "checkpoint_sha256": checkpoint_sha256,
        "inference": inference_contract,
        "image_count": len(records),
        "gt_box_count": total_gt,
        "prediction_count": total_predictions,
        "records": records,
    }
    if split == "test":
        ledger["threshold_freeze_sha256"] = threshold_freeze_sha256
    return ledger


def score_prediction_ledger(
    ledger: Mapping[str, object], *, iou_threshold: float = 0.50
) -> tuple[ThresholdEvaluation, ...]:
    records = _validate_prediction_ledger(ledger)
    return tuple(
        evaluate_threshold(records, threshold=threshold, iou_threshold=iou_threshold)
        for threshold in threshold_grid()
    )


def _validate_prediction_ledger(
    ledger: Mapping[str, object],
) -> tuple[EvaluationRecord, ...]:
    if ledger.get("schema") != "yolo26n-v22-prediction-ledger-v1":
        raise ValueError("unexpected prediction ledger contract")
    exact_scalars = {
        "status": "V22_PREDICTIONS_READY",
        "evaluation_tier": "development",
    }
    if any(ledger.get(key) != value for key, value in exact_scalars.items()):
        raise ValueError("unexpected prediction ledger contract")
    if ledger.get("split") not in {"val", "test"}:
        raise ValueError("prediction ledger split is invalid")
    if ledger.get("candidate") not in {"warm-start", "clean-reference"}:
        raise ValueError("prediction ledger candidate is invalid")
    if (
        not _is_sha(ledger.get("source_commit"), length=40)
        or not _is_sha(ledger.get("runner_sha256"))
        or not _is_sha(ledger.get("dataset_manifest_sha256"))
        or not _is_sha(ledger.get("checkpoint_sha256"))
        or ledger.get("inference") != EXACT_INFERENCE_CONTRACT
    ):
        raise ValueError("prediction ledger evaluation contract is invalid")
    for count_name in ("image_count", "gt_box_count", "prediction_count"):
        if type(ledger.get(count_name)) is not int or ledger[count_name] < 0:
            raise ValueError("prediction ledger count is invalid")
    raw_records = ledger.get("records")
    if not isinstance(raw_records, list):
        raise ValueError("prediction ledger records must be a list")
    records: list[EvaluationRecord] = []
    seen_sequences: set[str] = set()
    seen_images: set[str] = set()
    gt_count = prediction_count = 0
    for raw_record in raw_records:
        if not isinstance(raw_record, Mapping):
            raise ValueError("prediction ledger record must be a mapping")
        image_sha256 = raw_record.get("image_sha256")
        sequence = raw_record.get("sequence")
        width = raw_record.get("width")
        height = raw_record.get("height")
        raw_gt = raw_record.get("gt_boxes")
        raw_predictions = raw_record.get("predictions")
        if (
            not isinstance(sequence, str)
            or not sequence
            or sequence in seen_sequences
            or not _is_sha(image_sha256)
            or image_sha256 in seen_images
            or type(width) is not int
            or type(height) is not int
            or width <= 0
            or height <= 0
            or not isinstance(raw_gt, list)
            or not isinstance(raw_predictions, list)
        ):
            raise ValueError("prediction ledger record is invalid, duplicate, or count unsafe")
        predictions: list[PredictionBox] = []
        for raw_prediction in raw_predictions:
            if not isinstance(raw_prediction, Mapping):
                raise ValueError("prediction ledger prediction is invalid")
            confidence = raw_prediction.get("confidence")
            xyxy = raw_prediction.get("xyxy")
            if not _finite_number(confidence) or not isinstance(xyxy, Sequence):
                raise ValueError("prediction ledger prediction is invalid")
            predictions.append(
                PredictionBox(float(confidence), _validate_box(xyxy))
            )
        records.append(
            EvaluationRecord(
                image_sha256=image_sha256,
                gt_boxes=tuple(_validate_box(box) for box in raw_gt),
                predictions=tuple(predictions),
            )
        )
        seen_sequences.add(sequence)
        seen_images.add(image_sha256)
        gt_count += len(raw_gt)
        prediction_count += len(raw_predictions)
    if (
        ledger["image_count"] != len(records)
        or ledger["gt_box_count"] != gt_count
        or ledger["prediction_count"] != prediction_count
    ):
        raise ValueError("prediction ledger count mismatch or duplicate record")
    return tuple(records)


def _ground_truth_contract_sha256(ledger: Mapping[str, object]) -> str:
    _validate_prediction_ledger(ledger)
    records = ledger["records"]
    ground_truth = [
        {
            "sequence": record["sequence"],
            "image_sha256": record["image_sha256"],
            "width": record["width"],
            "height": record["height"],
            "gt_boxes": record["gt_boxes"],
        }
        for record in records
    ]
    canonical = json.dumps(
        ground_truth, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def select_development_candidate(
    candidates: Iterable[CandidateEvaluation], *, precision_floor: float = 0.60
) -> CandidateSelection:
    eligible: list[CandidateSelection] = []
    for candidate in candidates:
        if not candidate.candidate or not _is_sha(candidate.checkpoint_sha256):
            raise ValueError("candidate identity is invalid")
        try:
            selected = select_threshold(
                (
                    ThresholdMetric(row.threshold, row.precision, row.recall)
                    for row in candidate.metrics
                ),
                precision_floor=precision_floor,
            )
        except ThresholdSelectionError:
            continue
        eligible.append(
            CandidateSelection(
                candidate=candidate.candidate,
                checkpoint_sha256=candidate.checkpoint_sha256,
                threshold=selected.threshold,
                validation_precision=selected.precision,
                validation_recall=selected.recall,
            )
        )
    if not eligible:
        raise ThresholdSelectionError("no candidate reaches the precision floor")
    return max(
        eligible,
        key=lambda row: (
            row.validation_recall,
            row.validation_precision,
            row.threshold,
            row.candidate,
        ),
    )


def build_selection_freeze(
    ledgers: Mapping[str, Mapping[str, object]],
    *,
    ledger_sha256: Mapping[str, str],
    precision_floor: float = 0.60,
) -> dict[str, object]:
    if precision_floor != 0.60:
        raise ValueError("precision floor must be exactly 0.60")
    if set(ledgers) != {"warm-start", "clean-reference"}:
        raise ValueError("exact warm-start and clean-reference ledgers are required")
    if set(ledger_sha256) != set(ledgers) or not all(
        _is_sha(value) for value in ledger_sha256.values()
    ):
        raise ValueError("validation ledger SHA-256 map is invalid")
    candidates: list[CandidateEvaluation] = []
    metric_payload: dict[str, list[dict[str, object]]] = {}
    candidate_checkpoint_sha256: dict[str, str] = {}
    shared_contract: dict[str, object] | None = None
    validation_ground_truth_sha256: str | None = None
    for name in sorted(ledgers):
        ledger = ledgers[name]
        checkpoint_sha256 = ledger.get("checkpoint_sha256")
        if ledger.get("split") != "val" or not _is_sha(checkpoint_sha256):
            raise ValueError("candidate selection accepts validation ledgers only")
        if ledger.get("candidate") != name:
            raise ValueError("candidate ledger identity does not match its exact path")
        current_contract = {
            "dataset_manifest_sha256": ledger.get("dataset_manifest_sha256"),
            "source_commit": ledger.get("source_commit"),
            "runner_sha256": ledger.get("runner_sha256"),
            "inference": ledger.get("inference"),
        }
        current_ground_truth = _ground_truth_contract_sha256(ledger)
        if shared_contract is None:
            shared_contract = current_contract
            validation_ground_truth_sha256 = current_ground_truth
        elif (
            current_contract != shared_contract
            or current_ground_truth != validation_ground_truth_sha256
        ):
            raise ValueError("candidate ledgers have different evaluation contracts")
        metrics = score_prediction_ledger(ledger)
        candidates.append(CandidateEvaluation(name, checkpoint_sha256, metrics))
        candidate_checkpoint_sha256[name] = checkpoint_sha256
        metric_payload[name] = [
            {
                "threshold": row.threshold,
                "tp": row.tp,
                "fp": row.fp,
                "fn": row.fn,
                "precision": row.precision,
                "recall": row.recall,
            }
            for row in metrics
        ]
    selected = select_development_candidate(
        candidates, precision_floor=precision_floor
    )
    assert shared_contract is not None and validation_ground_truth_sha256 is not None
    return {
        "schema": "yolo26n-v22-candidate-threshold-freeze-v1",
        "status": "V22_THRESHOLD_FROZEN_DEVELOPMENT_ONLY",
        "evaluation_tier": "development",
        "future_holdout_required": True,
        "precision_floor": precision_floor,
        "candidate": selected.candidate,
        "checkpoint_sha256": selected.checkpoint_sha256,
        "candidate_checkpoint_sha256": candidate_checkpoint_sha256,
        "threshold": selected.threshold,
        "validation_precision": selected.validation_precision,
        "validation_recall": selected.validation_recall,
        "validation_ledger_sha256": dict(sorted(ledger_sha256.items())),
        **shared_contract,
        "validation_ground_truth_sha256": validation_ground_truth_sha256,
        "candidate_metrics": metric_payload,
    }


def build_fixed_test_report(
    *,
    test_ledger: Mapping[str, object],
    test_ledger_sha256: str,
    freeze: Mapping[str, object],
    freeze_sha256: str,
) -> dict[str, object]:
    if not _is_sha(test_ledger_sha256) or not _is_sha(freeze_sha256):
        raise ValueError("test or freeze SHA-256 is invalid")
    _validate_threshold_freeze(freeze)
    if test_ledger.get("split") != "test":
        raise ValueError("fixed test accepts a test ledger only")
    if test_ledger.get("checkpoint_sha256") != freeze.get("checkpoint_sha256"):
        raise ValueError("test checkpoint does not match the frozen checkpoint")
    if test_ledger.get("candidate") != freeze.get("candidate"):
        raise ValueError("test candidate does not match the frozen candidate")
    if test_ledger.get("threshold_freeze_sha256") != freeze_sha256:
        raise ValueError("test ledger does not bind the supplied threshold freeze")
    _validate_prediction_ledger(test_ledger)
    for key in (
        "dataset_manifest_sha256",
        "source_commit",
        "runner_sha256",
        "inference",
    ):
        if test_ledger.get(key) != freeze.get(key):
            raise ValueError("test ledger has a different evaluation contract")
    threshold = freeze.get("threshold")
    if not _finite_number(threshold):
        raise ValueError("frozen threshold is invalid")
    metrics = score_prediction_ledger(test_ledger)
    selected = next(
        (row for row in metrics if row.threshold == float(threshold)), None
    )
    if selected is None:
        raise ValueError("frozen threshold is outside the exact threshold grid")
    return {
        "schema": "yolo26n-v22-fixed-test-report-v1",
        "status": "V22_FIXED_TEST_COMPLETED",
        "evaluation_tier": "development",
        "future_holdout_required": True,
        "candidate": freeze.get("candidate"),
        "checkpoint_sha256": freeze.get("checkpoint_sha256"),
        "threshold": selected.threshold,
        "tp": selected.tp,
        "fp": selected.fp,
        "fn": selected.fn,
        "precision": selected.precision,
        "recall": selected.recall,
        "test_ledger_sha256": test_ledger_sha256,
        "threshold_freeze_sha256": freeze_sha256,
    }


def _validate_threshold_freeze(freeze: Mapping[str, object]) -> None:
    if (
        freeze.get("schema") != "yolo26n-v22-candidate-threshold-freeze-v1"
        or freeze.get("status") != "V22_THRESHOLD_FROZEN_DEVELOPMENT_ONLY"
        or freeze.get("evaluation_tier") != "development"
        or freeze.get("future_holdout_required") is not True
        or freeze.get("precision_floor") != 0.60
        or freeze.get("candidate") not in {"warm-start", "clean-reference"}
        or freeze.get("threshold") not in threshold_grid()
        or not _is_sha(freeze.get("checkpoint_sha256"))
        or not _is_sha(freeze.get("dataset_manifest_sha256"))
        or not _is_sha(freeze.get("source_commit"), length=40)
        or not _is_sha(freeze.get("runner_sha256"))
        or freeze.get("inference") != EXACT_INFERENCE_CONTRACT
        or not _is_sha(freeze.get("validation_ground_truth_sha256"))
    ):
        raise ValueError("frozen threshold contract is invalid")
    validation_ledgers = freeze.get("validation_ledger_sha256")
    if (
        not isinstance(validation_ledgers, Mapping)
        or set(validation_ledgers) != {"warm-start", "clean-reference"}
        or not all(_is_sha(value) for value in validation_ledgers.values())
    ):
        raise ValueError("frozen threshold validation lineage is invalid")
    candidate_checkpoints = freeze.get("candidate_checkpoint_sha256")
    if (
        not isinstance(candidate_checkpoints, Mapping)
        or set(candidate_checkpoints) != {"warm-start", "clean-reference"}
        or not all(_is_sha(value) for value in candidate_checkpoints.values())
        or freeze.get("checkpoint_sha256")
        != candidate_checkpoints.get(freeze.get("candidate"))
    ):
        raise ValueError("frozen threshold checkpoint lineage is invalid")
    candidate_metrics = freeze.get("candidate_metrics")
    if (
        not isinstance(candidate_metrics, Mapping)
        or set(candidate_metrics) != {"warm-start", "clean-reference"}
    ):
        raise ValueError("frozen threshold selection metrics are invalid")
    selections: list[tuple[str, ThresholdMetric]] = []
    expected_thresholds = threshold_grid()
    for candidate in sorted(candidate_metrics):
        raw_rows = candidate_metrics[candidate]
        if not isinstance(raw_rows, list) or len(raw_rows) != len(expected_thresholds):
            raise ValueError("frozen threshold selection metrics are invalid")
        metrics: list[ThresholdMetric] = []
        for expected_threshold, row in zip(expected_thresholds, raw_rows, strict=True):
            if not isinstance(row, Mapping) or set(row) != {
                "threshold",
                "tp",
                "fp",
                "fn",
                "precision",
                "recall",
            }:
                raise ValueError("frozen threshold selection metrics are invalid")
            if (
                row.get("threshold") != expected_threshold
                or any(type(row.get(key)) is not int or row[key] < 0 for key in ("tp", "fp", "fn"))
                or any(
                    not _finite_number(row.get(key))
                    or not 0.0 <= float(row[key]) <= 1.0
                    for key in ("precision", "recall")
                )
            ):
                raise ValueError("frozen threshold selection metrics are invalid")
            metrics.append(
                ThresholdMetric(
                    threshold=float(row["threshold"]),
                    precision=float(row["precision"]),
                    recall=float(row["recall"]),
                )
            )
        try:
            selections.append(
                (candidate, select_threshold(metrics, precision_floor=0.60))
            )
        except ThresholdSelectionError:
            continue
    if not selections:
        raise ValueError("frozen threshold selection metrics are invalid")
    selected_candidate, selected_metric = max(
        selections,
        key=lambda item: (
            item[1].recall,
            item[1].precision,
            item[1].threshold,
            item[0],
        ),
    )
    if (
        freeze.get("candidate") != selected_candidate
        or freeze.get("threshold") != selected_metric.threshold
        or freeze.get("validation_precision") != selected_metric.precision
        or freeze.get("validation_recall") != selected_metric.recall
    ):
        raise ValueError("frozen threshold selection metrics are inconsistent")


def make_ultralytics_predictor(
    *,
    checkpoint_path: Path,
    model_factory: Callable[[str], object] | None = None,
) -> Callable[..., list[dict[str, object]]]:
    if model_factory is None:
        from ultralytics import YOLO

        model_factory = YOLO
    model = model_factory(str(checkpoint_path))

    def predict(
        paths: Sequence[Path],
        *,
        confidence: float,
        imgsz: int,
        nms_iou: float,
        max_det: int,
        device: str,
    ) -> list[dict[str, object]]:
        raw_results = model.predict(
            source=[str(path) for path in paths],
            conf=confidence,
            imgsz=imgsz,
            iou=nms_iou,
            max_det=max_det,
            device=device,
            verbose=False,
            stream=False,
            save=False,
        )
        if len(raw_results) != len(paths):
            raise ValueError("Ultralytics result count does not match input count")
        rows: list[dict[str, object]] = []
        for index, result in enumerate(raw_results):
            # A list source is converted to PIL images in-order; ImageOps strips
            # their filenames, so this loader contract returns image{index}.jpg.
            if str(result.path) != f"image{index}.jpg":
                raise ValueError("Ultralytics result order does not match input order")
            height, width = result.orig_shape
            boxes = result.boxes
            xyxy_rows = boxes.xyxy.cpu().tolist() if boxes is not None else []
            confidences = boxes.conf.cpu().tolist() if boxes is not None else []
            if len(xyxy_rows) != len(confidences):
                raise ValueError("Ultralytics box and confidence counts differ")
            rows.append(
                {
                    "width": int(width),
                    "height": int(height),
                    "predictions": [
                        {"confidence": confidence_value, "xyxy": xyxy}
                        for confidence_value, xyxy in zip(
                            confidences, xyxy_rows, strict=True
                        )
                    ],
                }
            )
        return rows

    return predict


def _read_json_and_sha(path: Path) -> tuple[dict[str, object], str]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("JSON artifact root must be an object")
    return value, hashlib.sha256(raw).hexdigest()


def expected_test_ledger_path(
    freeze_path: Path, freeze: Mapping[str, object]
) -> Path:
    candidate = freeze.get("candidate")
    return expected_prediction_ledger_path(
        freeze_path.parent, candidate=candidate, split="test"
    )


def expected_prediction_ledger_path(
    evaluation_root: Path, *, candidate: object, split: str
) -> Path:
    if candidate not in {"warm-start", "clean-reference"}:
        raise ValueError("frozen candidate is invalid")
    if split not in {"val", "test"}:
        raise ValueError("prediction ledger split is invalid")
    return (
        evaluation_root
        / "prediction-ledgers"
        / f"{candidate}-{split}.private.json"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    predict = commands.add_parser("predict")
    predict.add_argument("--dataset-root", type=Path, required=True)
    predict.add_argument("--manifest", type=Path, required=True)
    predict.add_argument("--split", choices=("val", "test"), required=True)
    predict.add_argument("--checkpoint", type=Path, required=True)
    predict.add_argument("--source-commit", required=True)
    predict.add_argument("--freeze", type=Path)
    predict.add_argument("--candidate", choices=("warm-start", "clean-reference"))
    predict.add_argument("--evaluation-root", type=Path, required=True)

    freeze = commands.add_parser("freeze")
    freeze.add_argument("--evaluation-root", type=Path, required=True)

    fixed_test = commands.add_parser("fixed-test")
    fixed_test.add_argument("--evaluation-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "predict":
        threshold_freeze = threshold_freeze_sha256 = None
        if args.split == "test":
            exact_freeze_path = args.evaluation_root / "threshold-freeze.private.json"
            if args.freeze is None or args.freeze.resolve() != exact_freeze_path.resolve():
                raise ValueError("test prediction requires the exact evaluation freeze")
            threshold_freeze, threshold_freeze_sha256 = _read_json_and_sha(args.freeze)
            if args.candidate is not None:
                raise ValueError("test candidate comes only from the frozen selection")
            candidate = threshold_freeze.get("candidate")
        elif args.freeze is not None:
            raise ValueError("validation prediction must not use --freeze")
        else:
            if args.candidate is None:
                raise ValueError("validation prediction requires --candidate")
            candidate = args.candidate
        output_path = expected_prediction_ledger_path(
            args.evaluation_root, candidate=candidate, split=args.split
        )
        if output_path.exists():
            raise FileExistsError(output_path)
        samples = load_split_samples(
            dataset_root=args.dataset_root,
            manifest_path=args.manifest,
            split=args.split,
        )
        _claim_started(
            args.evaluation_root,
            operation=f"predict-{candidate}-{args.split}",
            details={"candidate": candidate, "split": args.split},
        )
        ledger = build_prediction_ledger(
            samples=samples,
            split=args.split,
            checkpoint_path=args.checkpoint,
            dataset_manifest_path=args.manifest,
            source_commit=args.source_commit,
            candidate=candidate,
            predictor=make_ultralytics_predictor(checkpoint_path=args.checkpoint),
            threshold_freeze=threshold_freeze,
            threshold_freeze_sha256=threshold_freeze_sha256,
        )
        write_private_json_new(output_path, ledger)
        print(json.dumps({"status": ledger["status"], "image_count": ledger["image_count"]}))
        return 0
    if args.command == "freeze":
        warm_path = expected_prediction_ledger_path(
            args.evaluation_root, candidate="warm-start", split="val"
        )
        clean_path = expected_prediction_ledger_path(
            args.evaluation_root, candidate="clean-reference", split="val"
        )
        warm, warm_sha = _read_json_and_sha(warm_path)
        clean, clean_sha = _read_json_and_sha(clean_path)
        freeze_output = args.evaluation_root / "threshold-freeze.private.json"
        if freeze_output.exists():
            raise FileExistsError(freeze_output)
        _claim_started(
            args.evaluation_root,
            operation="freeze-validation",
            details={"split": "val"},
        )
        freeze = build_selection_freeze(
            {"warm-start": warm, "clean-reference": clean},
            ledger_sha256={"warm-start": warm_sha, "clean-reference": clean_sha},
            precision_floor=0.60,
        )
        write_private_json_new(
            freeze_output, freeze
        )
        print(
            json.dumps(
                {
                    "status": freeze["status"],
                    "candidate": freeze["candidate"],
                    "threshold": freeze["threshold"],
                }
            )
        )
        return 0
    if args.command == "fixed-test":
        freeze_path = args.evaluation_root / "threshold-freeze.private.json"
        freeze, freeze_sha = _read_json_and_sha(freeze_path)
        test_path = expected_test_ledger_path(freeze_path, freeze)
        test_ledger, test_sha = _read_json_and_sha(test_path)
        report_output = args.evaluation_root / "fixed-test-report.private.json"
        if report_output.exists():
            raise FileExistsError(report_output)
        _claim_started(
            args.evaluation_root,
            operation="score-fixed-test",
            details={"split": "test"},
        )
        report = build_fixed_test_report(
            test_ledger=test_ledger,
            test_ledger_sha256=test_sha,
            freeze=freeze,
            freeze_sha256=freeze_sha,
        )
        write_private_json_new(
            report_output, report
        )
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "precision": report["precision"],
                    "recall": report["recall"],
                }
            )
        )
        return 0
    raise AssertionError("unreachable command")


def _resolve_dataset_path(dataset_root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("dataset paths must be non-empty relative strings")
    root = dataset_root.resolve()
    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("dataset path escapes dataset root")
    return resolved


def _load_yolo_boxes(raw: bytes) -> tuple[Box, ...]:
    boxes: list[Box] = []
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError("YOLO label is not UTF-8") from error
    for line_number, line in enumerate(lines, start=1):
        fields = line.split()
        if len(fields) != 5 or fields[0] != "0":
            raise ValueError(f"invalid YOLO label at line {line_number}")
        try:
            center_x, center_y, width, height = (float(value) for value in fields[1:])
        except ValueError as error:
            raise ValueError(f"invalid label geometry at line {line_number}") from error
        if not all(math.isfinite(value) for value in (center_x, center_y, width, height)):
            raise ValueError(f"invalid label geometry at line {line_number}")
        boxes.append(
            _validate_box(
                (
                    center_x - width / 2,
                    center_y - height / 2,
                    center_x + width / 2,
                    center_y + height / 2,
                ),
                normalized=True,
            )
        )
    return tuple(boxes)


def load_split_samples(
    *, dataset_root: Path, manifest_path: Path, split: str
) -> tuple[SplitSample, ...]:
    if split not in {"train", "val", "test"}:
        raise ValueError("split must be train, val, or test")
    payload = json.loads(manifest_path.read_bytes())
    if payload.get("schema") != "yolo26n-owner-dataset-v22":
        raise ValueError("unexpected dataset manifest schema")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("dataset manifest records must be a list")

    samples: list[SplitSample] = []
    seen_sequences: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or record.get("split") != split:
            continue
        sequence = record.get("sequence")
        image_sha256 = record.get("image_sha256")
        if not isinstance(sequence, str) or not sequence or sequence in seen_sequences:
            raise ValueError("split sequences must be unique non-empty strings")
        if not (
            isinstance(image_sha256, str)
            and len(image_sha256) == 64
            and image_sha256 == image_sha256.lower()
            and all(character in "0123456789abcdef" for character in image_sha256)
        ):
            raise ValueError("image SHA-256 is invalid")
        expected_image_path = f"images/{split}/{sequence}.jpg"
        expected_label_path = f"labels/{split}/{sequence}.txt"
        if (
            record.get("image_path") != expected_image_path
            or record.get("label_path") != expected_label_path
        ):
            raise ValueError("dataset split path does not match sequence and split")
        image_path = _resolve_dataset_path(dataset_root, record.get("image_path"))
        label_path = _resolve_dataset_path(dataset_root, record.get("label_path"))
        if not image_path.is_file() or not label_path.is_file():
            raise FileNotFoundError("dataset image or label is missing")
        if _sha256(image_path) != image_sha256:
            raise ValueError("dataset image SHA-256 mismatch")
        label_bytes = label_path.read_bytes()
        samples.append(
            SplitSample(
                sequence=sequence,
                image_path=image_path,
                label_path=label_path,
                image_sha256=image_sha256,
                label_sha256=hashlib.sha256(label_bytes).hexdigest(),
                normalized_gt_boxes=_load_yolo_boxes(label_bytes),
            )
        )
        seen_sequences.add(sequence)
    if not samples:
        raise ValueError("requested split is empty")
    return tuple(samples)


def write_private_json_new(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _claim_started(
    evaluation_root: Path, *, operation: str, details: Mapping[str, object]
) -> None:
    if not operation or any(character not in "abcdefghijklmnopqrstuvwxyz-" for character in operation):
        raise ValueError("one-shot operation name is invalid")
    write_private_json_new(
        evaluation_root / ".locks" / f"{operation}.started.private.json",
        {
            "schema": "yolo26n-v22-one-shot-claim-v1",
            "status": "STARTED",
            "operation": operation,
            **dict(details),
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())

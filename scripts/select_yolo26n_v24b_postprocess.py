"""Score and freeze deterministic YOLO26n v2.4b postprocess settings.

Inference belongs to the one-shot runner.  These pure helpers only validate its
immutable validation ledgers, then rescore their low-confidence predictions.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Mapping, Sequence


Box = tuple[float, float, float, float]
THRESHOLD_GRID = tuple(round(step * 0.05, 2) for step in range(1, 17))
NMS_GRID = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70)
MATCH_IOU = 0.50
BASELINE_CONFIDENCE = 0.20
BASELINE_NMS_IOU = 0.70
_LEDGER_SCHEMA = "yolo26n-v24b-postprocess-prediction-ledger-v1"
_LEDGER_STATUS = "V24B_POSTPROCESS_PREDICTIONS_READY"


@dataclass(frozen=True)
class PostprocessMetric:
    nms_iou: float
    confidence: float
    tp: int
    fp: int
    fn: int
    duplicate: int
    precision: float
    recall: float
    positive_image_recall: float


@dataclass(frozen=True)
class _Prediction:
    confidence: float
    xyxy: Box


@dataclass(frozen=True)
class _Record:
    sequence: str
    image_sha256: str
    width: int
    height: int
    gt_boxes: tuple[Box, ...]
    predictions: tuple[_Prediction, ...]


def _finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def _probability(value: object, *, name: str) -> float:
    if not _finite_number(value) or not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{name} must be a finite probability")
    return float(value)


def _sha256(value: object, *, length: int = 64) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _box(value: object) -> Box:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        raise ValueError("box geometry must contain four finite numbers")
    if not all(_finite_number(coordinate) for coordinate in value):
        raise ValueError("box geometry must contain four finite numbers")
    x1, y1, x2, y2 = (float(coordinate) for coordinate in value)
    if x1 >= x2 or y1 >= y2:
        raise ValueError("box geometry must have positive width and height")
    return x1, y1, x2, y2


def _iou(left: Box, right: Box) -> float:
    width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    intersection = width * height
    union = (left[2] - left[0]) * (left[3] - left[1]) + (
        right[2] - right[0]
    ) * (right[3] - right[1]) - intersection
    return intersection / union if union > 0.0 else 0.0


def _validate_prediction_ledger(ledger: Mapping[str, object]) -> tuple[float, tuple[_Record, ...]]:
    if not isinstance(ledger, Mapping):
        raise ValueError("prediction ledger must be a mapping")
    if (
        ledger.get("schema") != _LEDGER_SCHEMA
        or ledger.get("status") != _LEDGER_STATUS
        or ledger.get("dataset_schema") != "yolo26n-owner-dataset-v24"
        or ledger.get("evaluation_tier") != "development"
        or ledger.get("split") != "val"
        or ledger.get("candidate") != "warm-start"
    ):
        raise ValueError("unexpected prediction ledger contract")
    if not all(
        (
            _sha256(ledger.get("source_commit"), length=40),
            _sha256(ledger.get("runner_sha256")),
            _sha256(ledger.get("dataset_manifest_sha256")),
            _sha256(ledger.get("checkpoint_sha256")),
        )
    ):
        raise ValueError("prediction ledger SHA contract is invalid")
    inference = ledger.get("inference")
    if not isinstance(inference, Mapping) or set(inference) != {
        "confidence", "imgsz", "nms_iou", "max_det", "device"
    }:
        raise ValueError("prediction ledger inference contract is invalid")
    if (
        _probability(inference.get("confidence"), name="inference confidence") != 0.001
        or _probability(inference.get("nms_iou"), name="inference NMS IoU") not in NMS_GRID
        or type(inference.get("imgsz")) is not int
        or inference["imgsz"] != 960
        or type(inference.get("max_det")) is not int
        or inference["max_det"] != 50
        or inference.get("device") != "mps"
    ):
        raise ValueError("prediction ledger inference contract is invalid")
    for name in ("image_count", "gt_box_count", "prediction_count"):
        if type(ledger.get(name)) is not int or ledger[name] < 0:
            raise ValueError("prediction ledger count is invalid")
    raw_records = ledger.get("records")
    if not isinstance(raw_records, list):
        raise ValueError("prediction ledger records must be a list")
    records: list[_Record] = []
    sequences: set[str] = set()
    images: set[str] = set()
    gt_count = prediction_count = 0
    for raw_record in raw_records:
        if not isinstance(raw_record, Mapping):
            raise ValueError("prediction ledger record is invalid")
        sequence = raw_record.get("sequence")
        image_sha256 = raw_record.get("image_sha256")
        raw_gt = raw_record.get("gt_boxes")
        raw_predictions = raw_record.get("predictions")
        if (
            not isinstance(sequence, str)
            or not sequence
            or sequence in sequences
            or not _sha256(image_sha256)
            or image_sha256 in images
            or type(raw_record.get("width")) is not int
            or type(raw_record.get("height")) is not int
            or raw_record["width"] <= 0
            or raw_record["height"] <= 0
            or not isinstance(raw_gt, list)
            or not isinstance(raw_predictions, list)
        ):
            raise ValueError("prediction ledger record is invalid, duplicate, or count unsafe")
        predictions: list[_Prediction] = []
        for raw_prediction in raw_predictions:
            if not isinstance(raw_prediction, Mapping):
                raise ValueError("prediction ledger prediction is invalid")
            predictions.append(
                _Prediction(
                    _probability(raw_prediction.get("confidence"), name="prediction confidence"),
                    _box(raw_prediction.get("xyxy")),
                )
            )
        records.append(
            _Record(
                sequence,
                image_sha256,
                raw_record["width"],
                raw_record["height"],
                tuple(_box(box) for box in raw_gt),
                tuple(predictions),
            )
        )
        sequences.add(sequence)
        images.add(image_sha256)
        gt_count += len(raw_gt)
        prediction_count += len(predictions)
    if (
        ledger["image_count"] != len(records)
        or ledger["gt_box_count"] != gt_count
        or ledger["prediction_count"] != prediction_count
    ):
        raise ValueError("prediction ledger count mismatch or duplicate record")
    return float(inference["nms_iou"]), tuple(records)


def _ground_truth_contract_sha256(records: Sequence[_Record]) -> str:
    """Bind every NMS ledger to the same ordered GT-box contract."""
    canonical = [
        {
            "sequence": record.sequence,
            "image_sha256": record.image_sha256,
            "width": record.width,
            "height": record.height,
            # Preserve schema list order: matching uses its stable GT indices on ties.
            "gt_boxes": [list(box) for box in record.gt_boxes],
        }
        for record in sorted(records, key=lambda record: record.sequence)
    ]
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def score_prediction_ledger(
    ledger: Mapping[str, object], *, confidence: float, match_iou: float = MATCH_IOU
) -> PostprocessMetric:
    """Rescore one NMS ledger at a threshold with stable greedy one-to-one matches."""
    threshold = _probability(confidence, name="confidence")
    required_iou = _probability(match_iou, name="match IoU")
    if threshold not in THRESHOLD_GRID:
        raise ValueError("confidence must be in the frozen threshold grid")
    if required_iou != MATCH_IOU:
        raise ValueError("match IoU must be exactly 0.50")
    nms_iou, records = _validate_prediction_ledger(ledger)
    tp = fp = fn = duplicate = positive_images = recalled_positive_images = 0
    for record in sorted(records, key=lambda row: row.image_sha256):
        predictions = sorted(
            (row for row in record.predictions if row.confidence >= threshold),
            key=lambda row: (-row.confidence, row.xyxy),
        )
        matched: set[int] = set()
        image_has_tp = False
        for prediction in predictions:
            all_matches = [
                (index, _iou(prediction.xyxy, gt_box))
                for index, gt_box in enumerate(record.gt_boxes)
            ]
            eligible = [(iou, index) for index, iou in all_matches if index not in matched]
            best_iou, best_index = max(eligible, default=(0.0, -1))
            if best_index >= 0 and best_iou >= required_iou:
                matched.add(best_index)
                tp += 1
                image_has_tp = True
            else:
                fp += 1
                if any(iou >= required_iou for _, iou in all_matches):
                    duplicate += 1
        fn += len(record.gt_boxes) - len(matched)
        if record.gt_boxes:
            positive_images += 1
            recalled_positive_images += int(image_has_tp)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    positive_image_recall = (
        recalled_positive_images / positive_images if positive_images else 0.0
    )
    return PostprocessMetric(
        nms_iou=nms_iou,
        confidence=threshold,
        tp=tp,
        fp=fp,
        fn=fn,
        duplicate=duplicate,
        precision=precision,
        recall=recall,
        positive_image_recall=positive_image_recall,
    )


def _validate_metric(metric: PostprocessMetric) -> None:
    if not isinstance(metric, PostprocessMetric):
        raise ValueError("metric is invalid")
    if (
        metric.nms_iou not in NMS_GRID
        or metric.confidence not in THRESHOLD_GRID
        or any(type(value) is not int or value < 0 for value in (metric.tp, metric.fp, metric.fn, metric.duplicate))
        or any(
            not _finite_number(value) or not 0.0 <= float(value) <= 1.0
            for value in (metric.precision, metric.recall, metric.positive_image_recall)
        )
    ):
        raise ValueError("metric is invalid")
def select_postprocess_candidate(
    metrics: Sequence[PostprocessMetric], *, baseline_duplicate: int
) -> PostprocessMetric | None:
    if type(baseline_duplicate) is not int or baseline_duplicate < 0:
        raise ValueError("baseline duplicate is invalid")
    for metric in metrics:
        _validate_metric(metric)
    eligible = [
        metric
        for metric in metrics
        if metric.precision >= 0.60 and metric.recall >= 0.65 and metric.duplicate <= baseline_duplicate
    ]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda row: (row.duplicate, -row.recall, row.fp, -row.confidence, row.nms_iou),
    )


def build_postprocess_freeze(
    ledgers: Mapping[float, Mapping[str, object]], *, ledger_sha256: Mapping[float, str]
) -> dict[str, object]:
    """Build the validation-only metric table and selected v2.4b postprocess rule."""
    if set(ledgers) != set(NMS_GRID) or set(ledger_sha256) != set(NMS_GRID):
        raise ValueError("all exact NMS ledgers and their SHA-256 values are required")
    if not all(_sha256(value) for value in ledger_sha256.values()):
        raise ValueError("validation ledger SHA-256 map is invalid")
    all_metrics: list[PostprocessMetric] = []
    common_contract: dict[str, object] | None = None
    ground_truth_contract_sha256: str | None = None
    for nms_iou in NMS_GRID:
        ledger = ledgers[nms_iou]
        actual_nms, records = _validate_prediction_ledger(ledger)
        if actual_nms != nms_iou:
            raise ValueError("ledger NMS path and inference contract mismatch")
        current_ground_truth_contract = _ground_truth_contract_sha256(records)
        if ground_truth_contract_sha256 is None:
            ground_truth_contract_sha256 = current_ground_truth_contract
        elif current_ground_truth_contract != ground_truth_contract_sha256:
            raise ValueError("NMS ledgers have different ground truth contracts")
        contract = {
            key: ledger.get(key)
            for key in ("checkpoint_sha256", "dataset_manifest_sha256", "source_commit", "runner_sha256")
        }
        if common_contract is None:
            common_contract = contract
        elif contract != common_contract:
            raise ValueError("NMS ledgers have different evaluation contracts")
        all_metrics.extend(
            score_prediction_ledger(ledger, confidence=confidence)
            for confidence in THRESHOLD_GRID
        )
    baseline = next(
        metric
        for metric in all_metrics
        if metric.confidence == BASELINE_CONFIDENCE and metric.nms_iou == BASELINE_NMS_IOU
    )
    selected = select_postprocess_candidate(all_metrics, baseline_duplicate=baseline.duplicate)
    result: dict[str, object] = {
        "schema": "yolo26n-v24b-postprocess-freeze-v1",
        "status": "V24B_POSTPROCESS_FROZEN_DEVELOPMENT_ONLY" if selected else "V24B_POSTPROCESS_SHORTAGE",
        "evaluation_tier": "development",
        "future_holdout_required": True,
        "match_iou": MATCH_IOU,
        "threshold_grid": list(THRESHOLD_GRID),
        "nms_grid": list(NMS_GRID),
        "baseline": {"confidence": BASELINE_CONFIDENCE, "nms_iou": BASELINE_NMS_IOU, "duplicate": baseline.duplicate},
        "validation_ledger_sha256": {str(nms_iou): ledger_sha256[nms_iou] for nms_iou in NMS_GRID},
        "validation_ground_truth_sha256": ground_truth_contract_sha256,
        "metrics": [asdict(metric) for metric in all_metrics],
        **(common_contract or {}),
    }
    if selected is not None:
        result["selected"] = {
            "confidence": selected.confidence,
            "nms_iou": selected.nms_iou,
            "duplicate": selected.duplicate,
        }
    return result

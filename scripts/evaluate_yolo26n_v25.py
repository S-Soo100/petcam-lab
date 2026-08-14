"""Run the YOLO26n v2.5 same-protocol development comparison.

The baseline, warm-start, and clean-reference checkpoints first produce one
low-confidence validation ledger each.  Only after those three ledgers are
bound to the same GT and inference contract can a threshold be frozen.  The
frozen v2.4 baseline and selected v2.5 candidate then consume test once.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from scripts.evaluate_yolo26n_v22 import (
    EvaluationRecord,
    PredictionBox,
    SplitSample,
    _load_yolo_boxes,
    evaluate_threshold,
    make_ultralytics_predictor,
)


PRECISION_FLOOR = 0.60
THRESHOLDS = tuple(round(index * 0.05, 2) for index in range(1, 17))
VALIDATION_CANDIDATES = ("baseline-v24", "warm-start", "clean-reference")
TRAINED_CANDIDATES = ("warm-start", "clean-reference")
INFERENCE_CONTRACT: dict[str, object] = {
    "confidence": 0.001,
    "imgsz": 960,
    "nms_iou": 0.70,
    "max_det": 50,
    "device": "mps",
    "match_iou": 0.50,
}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha(value: object, length: int = 64) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} malformed")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} malformed")
    return result


def _metric(row: Mapping[str, object]) -> dict[str, object]:
    threshold = _number(row.get("threshold"), "threshold")
    precision = _number(row.get("precision"), "precision")
    recall = _number(row.get("recall"), "recall")
    fp = _number(row.get("fp"), "fp")
    duplicate = _number(row.get("duplicate"), "duplicate")
    if (
        threshold not in THRESHOLDS
        or not 0 <= precision <= 1
        or not 0 <= recall <= 1
        or fp < 0
        or duplicate < 0
    ):
        raise ValueError("metric outside contract")
    return {
        "threshold": threshold,
        "precision": precision,
        "recall": recall,
        "fp": int(fp),
        "duplicate": int(duplicate),
        **({"tp": row["tp"], "fn": row["fn"]} if "tp" in row and "fn" in row else {}),
    }


def select_v25_candidate(
    candidate_metrics: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    precision_floor: float = PRECISION_FLOOR,
) -> dict[str, object]:
    """Select only between trained candidates; baseline proof is added later."""
    if precision_floor != PRECISION_FLOOR:
        raise ValueError("precision floor must be exactly 0.60")
    if set(candidate_metrics) - set(TRAINED_CANDIDATES):
        raise ValueError("unknown candidate")
    selected: dict[str, dict[str, object]] = {}
    normalized: dict[str, list[dict[str, object]]] = {}
    for candidate in TRAINED_CANDIDATES:
        rows = [_metric(row) for row in candidate_metrics.get(candidate, ())]
        normalized[candidate] = rows
        eligible = [row for row in rows if float(row["precision"]) >= PRECISION_FLOOR]
        if eligible:
            selected[candidate] = min(
                eligible,
                key=lambda row: (
                    -float(row["recall"]),
                    int(row["duplicate"]),
                    int(row["fp"]),
                    -float(row["threshold"]),
                ),
            )
    if not selected:
        raise ValueError("V25_VALIDATION_SHORTAGE")
    candidate, metric = min(
        selected.items(),
        key=lambda item: (
            -float(item[1]["recall"]),
            int(item[1]["duplicate"]),
            int(item[1]["fp"]),
            0 if item[0] == "warm-start" else 1,
        ),
    )
    return {
        "candidate": candidate,
        "threshold": metric["threshold"],
        "validation_precision": metric["precision"],
        "validation_recall": metric["recall"],
        "precision_floor": PRECISION_FLOOR,
        "candidate_metrics": normalized,
    }


def _resolve(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("dataset path must be relative")
    resolved_root = root.resolve()
    result = (resolved_root / relative).resolve()
    if result != resolved_root and resolved_root not in result.parents:
        raise ValueError("dataset path escapes root")
    return result


def load_v25_samples(
    *, dataset_root: Path, manifest_path: Path, split: str
) -> tuple[SplitSample, ...]:
    if split not in {"val", "test"}:
        raise ValueError("evaluation split must be val or test")
    payload = json.loads(manifest_path.read_bytes())
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "yolo26n-owner-dataset-v25"
        or payload.get("status") != "V25_DATASET_READY"
        or payload.get("evaluation_tier") != "development"
        or payload.get("split_counts") != {"train": 1659, "val": 153, "test": 151}
    ):
        raise ValueError("v2.5 dataset manifest contract mismatch")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("dataset records missing")
    samples: list[SplitSample] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or record.get("split") != split:
            continue
        sequence = record.get("sequence")
        image_sha = record.get("image_sha256")
        if not isinstance(sequence, str) or not sequence or sequence in seen or not _is_sha(image_sha):
            raise ValueError("dataset sequence or image SHA invalid")
        image_relative = f"images/{split}/{sequence}.jpg"
        label_relative = f"labels/{split}/{sequence}.txt"
        if record.get("image_path") != image_relative or record.get("label_path") != label_relative:
            raise ValueError("dataset split path mismatch")
        image_path = _resolve(dataset_root, image_relative)
        label_path = _resolve(dataset_root, label_relative)
        if not image_path.is_file() or not label_path.is_file() or _sha(image_path) != image_sha:
            raise ValueError("dataset evaluation bytes mismatch")
        label_bytes = label_path.read_bytes()
        samples.append(
            SplitSample(
                sequence=sequence,
                image_path=image_path,
                label_path=label_path,
                image_sha256=image_sha,
                label_sha256=hashlib.sha256(label_bytes).hexdigest(),
                normalized_gt_boxes=_load_yolo_boxes(label_bytes),
            )
        )
        seen.add(sequence)
    expected_count = 153 if split == "val" else 151
    if len(samples) != expected_count:
        raise ValueError("evaluation split count mismatch")
    return tuple(samples)


def _write_private_new(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, payload)
        os.fsync(descriptor)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)


def _claim(root: Path, operation: str) -> None:
    if not operation or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in operation):
        raise ValueError("operation name invalid")
    _write_private_new(
        root / ".locks" / f"{operation}.started.private.json",
        {"schema": "yolo26n-v25-one-shot-claim-v1", "status": "STARTED", "operation": operation},
    )


def _prediction_path(root: Path, candidate: str, split: str) -> Path:
    if candidate not in VALIDATION_CANDIDATES or split not in {"val", "test"}:
        raise ValueError("prediction identity invalid")
    return root / "prediction-ledgers" / f"{candidate}-{split}.private.json"


def _validate_freeze(freeze: Mapping[str, object]) -> None:
    if (
        freeze.get("schema") != "yolo26n-v25-selection-freeze-v1"
        or freeze.get("status") != "V25_THRESHOLD_FROZEN_DEVELOPMENT_ONLY"
        or freeze.get("candidate") not in TRAINED_CANDIDATES
        or freeze.get("threshold") not in THRESHOLDS
        or freeze.get("precision_floor") != PRECISION_FLOOR
        or freeze.get("baseline_remeasured_same_protocol") is not True
        or freeze.get("inference") != INFERENCE_CONTRACT
        or freeze.get("future_holdout_required") is not True
    ):
        raise ValueError("v2.5 freeze contract invalid")
    for field in ("validation_ledger_sha256", "candidate_checkpoint_sha256"):
        value = freeze.get(field)
        if not isinstance(value, Mapping) or set(value) != set(VALIDATION_CANDIDATES) or not all(_is_sha(item) for item in value.values()):
            raise ValueError("v2.5 freeze lineage invalid")
    if freeze.get("checkpoint_sha256") != freeze["candidate_checkpoint_sha256"][freeze["candidate"]]:
        raise ValueError("selected checkpoint lineage invalid")
    for field, length in (("dataset_manifest_sha256", 64), ("source_commit", 40), ("runner_sha256", 64), ("validation_ground_truth_sha256", 64)):
        if not _is_sha(freeze.get(field), length):
            raise ValueError("freeze provenance invalid")
    metrics = freeze.get("candidate_metrics")
    if not isinstance(metrics, Mapping) or set(metrics) != set(VALIDATION_CANDIDATES):
        raise ValueError("freeze metrics invalid")
    if not all(isinstance(metrics[name], Sequence) for name in VALIDATION_CANDIDATES):
        raise ValueError("freeze metrics invalid")
    selection = select_v25_candidate({name: metrics[name] for name in TRAINED_CANDIDATES})
    for field in ("candidate", "threshold", "validation_precision", "validation_recall"):
        if freeze.get(field) != selection[field]:
            raise ValueError("freeze selection is inconsistent")


def build_prediction_ledger(
    *,
    samples: Sequence[SplitSample],
    split: str,
    candidate: str,
    checkpoint_path: Path,
    manifest_path: Path,
    source_commit: str,
    predictor: Callable[..., Sequence[Mapping[str, object]]],
    freeze: Mapping[str, object] | None = None,
    freeze_sha256: str | None = None,
) -> dict[str, object]:
    if candidate not in VALIDATION_CANDIDATES or split not in {"val", "test"} or not samples:
        raise ValueError("prediction identity invalid")
    if not _is_sha(source_commit, 40):
        raise ValueError("source commit invalid")
    runner_sha = _sha(Path(__file__))
    manifest_sha = _sha(manifest_path)
    checkpoint_sha = _sha(checkpoint_path)
    sample_hashes = tuple((_sha(item.image_path), _sha(item.label_path)) for item in samples)
    if any(pair != (item.image_sha256, item.label_sha256) for item, pair in zip(samples, sample_hashes, strict=True)):
        raise ValueError("evaluation sample hash mismatch")
    if split == "test":
        if freeze is None or not _is_sha(freeze_sha256):
            raise ValueError("test prediction requires freeze")
        _validate_freeze(freeze)
        allowed = {"baseline-v24", str(freeze["candidate"])}
        if candidate not in allowed or checkpoint_sha != freeze["candidate_checkpoint_sha256"][candidate]:
            raise ValueError("test candidate is not frozen")
        for key, value in {
            "dataset_manifest_sha256": manifest_sha,
            "source_commit": source_commit,
            "runner_sha256": runner_sha,
            "inference": INFERENCE_CONTRACT,
        }.items():
            if freeze.get(key) != value:
                raise ValueError("test evaluation contract differs from freeze")
    elif freeze is not None or freeze_sha256 is not None:
        raise ValueError("validation must not consume freeze")

    raw_results = tuple(
        predictor(
            [item.image_path for item in samples],
            confidence=INFERENCE_CONTRACT["confidence"],
            imgsz=INFERENCE_CONTRACT["imgsz"],
            nms_iou=INFERENCE_CONTRACT["nms_iou"],
            max_det=INFERENCE_CONTRACT["max_det"],
            device=INFERENCE_CONTRACT["device"],
        )
    )
    if len(raw_results) != len(samples):
        raise ValueError("prediction result count mismatch")
    if (
        _sha(Path(__file__)) != runner_sha
        or _sha(manifest_path) != manifest_sha
        or _sha(checkpoint_path) != checkpoint_sha
        or tuple((_sha(item.image_path), _sha(item.label_path)) for item in samples) != sample_hashes
    ):
        raise ValueError("evaluation input changed during inference")

    records: list[dict[str, object]] = []
    gt_count = prediction_count = 0
    for sample, raw in zip(samples, raw_results, strict=True):
        width, height = raw.get("width"), raw.get("height")
        predictions = raw.get("predictions")
        if type(width) is not int or type(height) is not int or width <= 0 or height <= 0 or not isinstance(predictions, list):
            raise ValueError("prediction row malformed")
        gt_boxes = [[x1 * width, y1 * height, x2 * width, y2 * height] for x1, y1, x2, y2 in sample.normalized_gt_boxes]
        normalized_predictions: list[dict[str, object]] = []
        for prediction in predictions:
            if not isinstance(prediction, Mapping):
                raise ValueError("prediction malformed")
            confidence = _number(prediction.get("confidence"), "confidence")
            xyxy = prediction.get("xyxy")
            if not 0 <= confidence <= 1 or not isinstance(xyxy, Sequence) or len(xyxy) != 4:
                raise ValueError("prediction malformed")
            box = [_number(value, "coordinate") for value in xyxy]
            if box[0] >= box[2] or box[1] >= box[3]:
                raise ValueError("prediction geometry invalid")
            normalized_predictions.append({"confidence": confidence, "xyxy": box})
        normalized_predictions.sort(key=lambda row: (-float(row["confidence"]), row["xyxy"]))
        gt_count += len(gt_boxes)
        prediction_count += len(normalized_predictions)
        records.append({
            "sequence": sample.sequence,
            "image_sha256": sample.image_sha256,
            "width": width,
            "height": height,
            "gt_boxes": gt_boxes,
            "predictions": normalized_predictions,
        })
    ledger: dict[str, object] = {
        "schema": "yolo26n-v25-prediction-ledger-v1",
        "status": "V25_PREDICTIONS_READY",
        "evaluation_tier": "development",
        "split": split,
        "candidate": candidate,
        "source_commit": source_commit,
        "runner_sha256": runner_sha,
        "dataset_manifest_sha256": manifest_sha,
        "checkpoint_sha256": checkpoint_sha,
        "inference": INFERENCE_CONTRACT,
        "image_count": len(records),
        "gt_box_count": gt_count,
        "prediction_count": prediction_count,
        "records": records,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "deploy_count": 0,
    }
    if split == "test":
        ledger["threshold_freeze_sha256"] = freeze_sha256
    return ledger


def _records(ledger: Mapping[str, object]) -> tuple[EvaluationRecord, ...]:
    if (
        ledger.get("schema") != "yolo26n-v25-prediction-ledger-v1"
        or ledger.get("status") != "V25_PREDICTIONS_READY"
        or ledger.get("evaluation_tier") != "development"
        or ledger.get("split") not in {"val", "test"}
        or ledger.get("candidate") not in VALIDATION_CANDIDATES
        or ledger.get("inference") != INFERENCE_CONTRACT
    ):
        raise ValueError("prediction ledger contract invalid")
    for field, length in (("source_commit", 40), ("runner_sha256", 64), ("dataset_manifest_sha256", 64), ("checkpoint_sha256", 64)):
        if not _is_sha(ledger.get(field), length):
            raise ValueError("prediction ledger provenance invalid")
    raw_records = ledger.get("records")
    if not isinstance(raw_records, list):
        raise ValueError("prediction ledger records missing")
    result: list[EvaluationRecord] = []
    seen_sequence: set[str] = set()
    seen_image: set[str] = set()
    gt_count = prediction_count = 0
    for raw in raw_records:
        if not isinstance(raw, Mapping):
            raise ValueError("prediction record malformed")
        sequence, image_sha = raw.get("sequence"), raw.get("image_sha256")
        width, height = raw.get("width"), raw.get("height")
        gt_boxes, predictions = raw.get("gt_boxes"), raw.get("predictions")
        if (
            not isinstance(sequence, str) or not sequence or sequence in seen_sequence
            or not _is_sha(image_sha) or image_sha in seen_image
            or type(width) is not int or type(height) is not int or width <= 0 or height <= 0
            or not isinstance(gt_boxes, list) or not isinstance(predictions, list)
        ):
            raise ValueError("prediction record identity malformed")
        parsed_predictions: list[PredictionBox] = []
        for prediction in predictions:
            if not isinstance(prediction, Mapping) or not isinstance(prediction.get("xyxy"), list):
                raise ValueError("prediction malformed")
            confidence = _number(prediction.get("confidence"), "confidence")
            box = tuple(_number(value, "coordinate") for value in prediction["xyxy"])
            if len(box) != 4 or box[0] >= box[2] or box[1] >= box[3]:
                raise ValueError("prediction geometry invalid")
            parsed_predictions.append(PredictionBox(confidence, box))
        parsed_gt = []
        for box_value in gt_boxes:
            if not isinstance(box_value, list):
                raise ValueError("GT geometry invalid")
            box = tuple(_number(value, "GT coordinate") for value in box_value)
            if len(box) != 4 or box[0] >= box[2] or box[1] >= box[3]:
                raise ValueError("GT geometry invalid")
            parsed_gt.append(box)
        result.append(EvaluationRecord(image_sha, tuple(parsed_gt), tuple(parsed_predictions)))
        seen_sequence.add(sequence)
        seen_image.add(image_sha)
        gt_count += len(parsed_gt)
        prediction_count += len(parsed_predictions)
    for field, actual in (("image_count", len(result)), ("gt_box_count", gt_count), ("prediction_count", prediction_count)):
        if type(ledger.get(field)) is not int or ledger[field] != actual:
            raise ValueError("prediction ledger count mismatch")
    return tuple(result)


def _iou(left: Sequence[float], right: Sequence[float]) -> float:
    width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    intersection = width * height
    union = (left[2] - left[0]) * (left[3] - left[1]) + (right[2] - right[0]) * (right[3] - right[1]) - intersection
    return intersection / union if union else 0.0


def score_ledger(ledger: Mapping[str, object]) -> list[dict[str, object]]:
    records = _records(ledger)
    rows: list[dict[str, object]] = []
    for threshold in THRESHOLDS:
        metric = evaluate_threshold(records, threshold=threshold, iou_threshold=0.50)
        duplicate = 0
        for record in records:
            matched: set[int] = set()
            for prediction in sorted((item for item in record.predictions if item.confidence >= threshold), key=lambda item: (-item.confidence, item.xyxy)):
                overlaps = sorted(((_iou(prediction.xyxy, gt), index) for index, gt in enumerate(record.gt_boxes)), reverse=True)
                if overlaps and overlaps[0][0] >= 0.50:
                    if overlaps[0][1] in matched:
                        duplicate += 1
                    else:
                        matched.add(overlaps[0][1])
        rows.append({
            "threshold": threshold,
            "tp": metric.tp,
            "fp": metric.fp,
            "fn": metric.fn,
            "precision": metric.precision,
            "recall": metric.recall,
            "duplicate": duplicate,
        })
    return rows


def _gt_digest(ledger: Mapping[str, object]) -> str:
    _records(ledger)
    payload = [
        {key: row[key] for key in ("sequence", "image_sha256", "width", "height", "gt_boxes")}
        for row in ledger["records"]
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_selection_freeze(
    ledgers: Mapping[str, Mapping[str, object]],
    *, ledger_sha256: Mapping[str, str],
) -> dict[str, object]:
    if set(ledgers) != set(VALIDATION_CANDIDATES) or set(ledger_sha256) != set(VALIDATION_CANDIDATES):
        raise ValueError("baseline and both trained validation ledgers are required")
    if not all(_is_sha(value) for value in ledger_sha256.values()):
        raise ValueError("validation ledger SHA invalid")
    shared: dict[str, object] | None = None
    gt_digest: str | None = None
    metrics: dict[str, list[dict[str, object]]] = {}
    checkpoints: dict[str, str] = {}
    for candidate in VALIDATION_CANDIDATES:
        ledger = ledgers[candidate]
        _records(ledger)
        if ledger.get("split") != "val" or ledger.get("candidate") != candidate:
            raise ValueError("validation ledger identity mismatch")
        contract = {key: ledger.get(key) for key in ("dataset_manifest_sha256", "source_commit", "runner_sha256", "inference")}
        digest = _gt_digest(ledger)
        if shared is None:
            shared, gt_digest = contract, digest
        elif shared != contract or gt_digest != digest:
            raise ValueError("validation ledgers do not share one protocol and GT")
        checkpoints[candidate] = str(ledger["checkpoint_sha256"])
        metrics[candidate] = score_ledger(ledger)
    assert shared is not None and gt_digest is not None
    selection = select_v25_candidate({name: metrics[name] for name in TRAINED_CANDIDATES})
    return {
        "schema": "yolo26n-v25-selection-freeze-v1",
        "status": "V25_THRESHOLD_FROZEN_DEVELOPMENT_ONLY",
        "evaluation_tier": "development",
        **selection,
        **shared,
        "checkpoint_sha256": checkpoints[str(selection["candidate"])],
        "candidate_checkpoint_sha256": checkpoints,
        "validation_ledger_sha256": dict(ledger_sha256),
        "validation_ground_truth_sha256": gt_digest,
        "candidate_metrics": metrics,
        "baseline_remeasured_same_protocol": True,
        "owner_external60_rerun": False,
        "future_holdout_required": True,
        "production_adoption": False,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "deploy_count": 0,
    }


def run_prediction_once(
    *,
    dataset_root: Path,
    manifest_path: Path,
    split: str,
    candidate: str,
    checkpoint_path: Path,
    source_commit: str,
    evaluation_root: Path,
    predictor: Callable[..., Sequence[Mapping[str, object]]] | None = None,
    freeze: Mapping[str, object] | None = None,
    freeze_sha256: str | None = None,
) -> dict[str, object]:
    output = _prediction_path(evaluation_root, candidate, split)
    if output.exists():
        raise FileExistsError(output)
    samples = load_v25_samples(dataset_root=dataset_root, manifest_path=manifest_path, split=split)
    _claim(evaluation_root, f"predict-{candidate}-{split}")
    actual_predictor = predictor or make_ultralytics_predictor(checkpoint_path=checkpoint_path)
    ledger = build_prediction_ledger(
        samples=samples,
        split=split,
        candidate=candidate,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        source_commit=source_commit,
        predictor=actual_predictor,
        freeze=freeze,
        freeze_sha256=freeze_sha256,
    )
    _write_private_new(output, ledger)
    return ledger


def build_fixed_test_report(
    *,
    test_ledgers: Mapping[str, Mapping[str, object]],
    test_ledger_sha256: Mapping[str, str],
    freeze: Mapping[str, object],
    freeze_sha256: str,
) -> dict[str, object]:
    _validate_freeze(freeze)
    expected = {"baseline-v24", str(freeze["candidate"])}
    if set(test_ledgers) != expected or set(test_ledger_sha256) != expected or not _is_sha(freeze_sha256) or not all(_is_sha(value) for value in test_ledger_sha256.values()):
        raise ValueError("fixed test requires baseline and selected ledgers")
    gt_digest: str | None = None
    output_metrics: dict[str, dict[str, object]] = {}
    threshold = float(freeze["threshold"])
    for candidate in sorted(expected):
        ledger = test_ledgers[candidate]
        _records(ledger)
        if (
            ledger.get("split") != "test"
            or ledger.get("candidate") != candidate
            or ledger.get("threshold_freeze_sha256") != freeze_sha256
            or ledger.get("checkpoint_sha256") != freeze["candidate_checkpoint_sha256"][candidate]
        ):
            raise ValueError("fixed test ledger lineage mismatch")
        for field in ("dataset_manifest_sha256", "source_commit", "runner_sha256", "inference"):
            if ledger.get(field) != freeze.get(field):
                raise ValueError("fixed test protocol mismatch")
        digest = _gt_digest(ledger)
        if gt_digest is None:
            gt_digest = digest
        elif gt_digest != digest:
            raise ValueError("fixed test GT differs between models")
        output_metrics[candidate] = next(row for row in score_ledger(ledger) if row["threshold"] == threshold)
    return {
        "schema": "yolo26n-v25-fixed-test-report-v1",
        "status": "V25_FIXED_TEST_COMPLETED_DEVELOPMENT_ONLY",
        "evaluation_tier": "development",
        "candidate": freeze["candidate"],
        "threshold": threshold,
        "metrics": output_metrics,
        "test_ledger_sha256": dict(test_ledger_sha256),
        "threshold_freeze_sha256": freeze_sha256,
        "regression_only_old_distribution": True,
        "warm_clean_recipe_difference_included": True,
        "mps_one_shot_not_bitwise_deterministic": True,
        "future_holdout_required": True,
        "production_adoption": False,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "deploy_count": 0,
    }


def _read(path: Path) -> tuple[dict[str, object], str]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("artifact root must be object")
    return value, hashlib.sha256(raw).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    predict = commands.add_parser("predict")
    predict.add_argument("--dataset-root", type=Path, required=True)
    predict.add_argument("--manifest", type=Path, required=True)
    predict.add_argument("--split", choices=("val", "test"), required=True)
    predict.add_argument("--candidate", choices=VALIDATION_CANDIDATES, required=True)
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
            exact = args.evaluation_root / "threshold-freeze.private.json"
            if args.freeze is None or args.freeze.resolve() != exact.resolve():
                raise ValueError("test prediction requires exact freeze path")
            freeze, freeze_sha = _read(exact)
        elif args.freeze is not None:
            raise ValueError("validation prediction must not use freeze")
        result = run_prediction_once(
            dataset_root=args.dataset_root,
            manifest_path=args.manifest,
            split=args.split,
            candidate=args.candidate,
            checkpoint_path=args.checkpoint,
            source_commit=args.source_commit,
            evaluation_root=args.evaluation_root,
            freeze=freeze,
            freeze_sha256=freeze_sha,
        )
        print(json.dumps({"status": result["status"], "image_count": result["image_count"]}))
        return 0
    if args.command == "freeze":
        output = args.evaluation_root / "threshold-freeze.private.json"
        if output.exists():
            raise FileExistsError(output)
        ledgers: dict[str, dict[str, object]] = {}
        hashes: dict[str, str] = {}
        for candidate in VALIDATION_CANDIDATES:
            ledgers[candidate], hashes[candidate] = _read(_prediction_path(args.evaluation_root, candidate, "val"))
        _claim(args.evaluation_root, "freeze-validation")
        freeze = build_selection_freeze(ledgers, ledger_sha256=hashes)
        _write_private_new(output, freeze)
        print(json.dumps({"status": freeze["status"], "candidate": freeze["candidate"], "threshold": freeze["threshold"]}))
        return 0
    freeze_path = args.evaluation_root / "threshold-freeze.private.json"
    freeze, freeze_sha = _read(freeze_path)
    _validate_freeze(freeze)
    output = args.evaluation_root / "fixed-test-report.private.json"
    if output.exists():
        raise FileExistsError(output)
    expected = {"baseline-v24", str(freeze["candidate"])}
    ledgers, hashes = {}, {}
    for candidate in expected:
        ledgers[candidate], hashes[candidate] = _read(_prediction_path(args.evaluation_root, candidate, "test"))
    _claim(args.evaluation_root, "score-fixed-test")
    report = build_fixed_test_report(test_ledgers=ledgers, test_ledger_sha256=hashes, freeze=freeze, freeze_sha256=freeze_sha)
    _write_private_new(output, report)
    print(json.dumps({"status": report["status"], "candidate": report["candidate"], "threshold": report["threshold"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

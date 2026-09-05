"""Evaluate and freeze YOLO26n v2.6.1 candidates without reusing test data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

LEDGER_SCHEMA = "yolo26n-v261-prediction-ledger-v1"
LEDGER_STATUS = "V261_PREDICTIONS_READY"
FREEZE_SCHEMA = "yolo26n-v261-detector-freeze-v1"
FREEZE_STATUS = "V261_DETECTOR_FROZEN"
VALIDATION_CANDIDATES = (
    "baseline-v26",
    "warm-start-s26",
    "warm-start-s27",
    "warm-start-s28",
    "clean-reference-s26",
    "clean-reference-s27",
    "clean-reference-s28",
)
DEFAULT_CONFIDENCE_GRID = tuple(round(index * 0.05, 2) for index in range(1, 17))
DEFAULT_NMS_GRID = (0.40, 0.55, 0.70)
INFERENCE_PROTOCOL = {
    "raw_confidence": 0.001,
    "model_nms_iou": 0.70,
    "max_det": 50,
    "imgsz": 960,
    "device": "mps",
    "resize_mode": "ultralytics_letterbox",
    "input_color": "bgr_file_decode_to_rgb_model",
    "coordinate_space": "normalized_xyxy_original_image",
}
PROTECTION_SCHEMA = "yolo26n-v261-protection-evidence-v1"
PROTECTION_STATUS = "V261_PROTECTED_INPUTS_VERIFIED"
BINDINGS_SCHEMA = "yolo26n-v261-evaluation-bindings-v1"
BINDINGS_STATUS = "V261_EVALUATION_PREFLIGHT_READY"
REGRESSION_BINDINGS_SCHEMA = "yolo26n-v261-regression-bindings-v1"
REGRESSION_BINDINGS_STATUS = "V261_REGRESSION_PREFLIGHT_READY"
REGRESSION_SUITES = {
    "v26-recent-val505": {"source_split": "val", "sample_count": 505},
    "old-internal-test151": {
        "source_split": "regression-test",
        "sample_count": 151,
    },
}


class ValidationShortage(RuntimeError):
    """Raised when no v2.6.1 candidate satisfies the preregistered validation gate."""


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_new(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    data = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
    os.chmod(path, 0o600)


def _is_sha(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _canonical_digest(value: object) -> str:
    return _sha_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _require_evaluation_root(attempt_root: Path, evaluation_root: Path) -> None:
    if evaluation_root.resolve().parent != attempt_root.resolve():
        raise ValueError(
            "evaluation root must be a direct child of the private attempt"
        )


def claim_once(root: Path, operation: str) -> Path:
    if not operation or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
        for character in operation
    ):
        raise ValueError("invalid one-shot operation")
    path = root / ".locks" / f"{operation}.started.private.json"
    _write_json_new(
        path,
        {
            "schema": "yolo26n-v261-one-shot-claim-v1",
            "status": "V261_OPERATION_CLAIMED",
            "operation": operation,
        },
    )
    return path


def _strict_box(value: object, *, label: str) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{label} must be xyxy")
    try:
        x1, y1, x2, y2 = (float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} contains a non-number") from exc
    if not all(math.isfinite(item) for item in (x1, y1, x2, y2)):
        raise ValueError(f"{label} contains a non-finite number")
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise ValueError(f"{label} is outside normalized bounds")
    return x1, y1, x2, y2


def _iou(left: Sequence[float], right: Sequence[float]) -> float:
    lx1, ly1, lx2, ly2 = left
    rx1, ry1, rx2, ry2 = right
    intersection = max(0.0, min(lx2, rx2) - max(lx1, rx1)) * max(
        0.0, min(ly2, ry2) - max(ly1, ry1)
    )
    union = (lx2 - lx1) * (ly2 - ly1) + (rx2 - rx1) * (ry2 - ry1) - intersection
    return intersection / union if union else 0.0


def _offline_nms(
    predictions: Iterable[tuple[tuple[float, float, float, float], float]],
    *,
    threshold: float,
) -> list[tuple[tuple[float, float, float, float], float]]:
    ordered = sorted(predictions, key=lambda item: (-item[1], item[0]))
    kept: list[tuple[tuple[float, float, float, float], float]] = []
    for candidate in ordered:
        if all(_iou(candidate[0], existing[0]) <= threshold for existing in kept):
            kept.append(candidate)
    return kept


def _match_boxes(
    gt_boxes: Sequence[tuple[float, float, float, float]],
    predictions: Sequence[tuple[tuple[float, float, float, float], float]],
) -> tuple[list[tuple[int, int, float]], int]:
    candidates: list[tuple[float, int, int]] = []
    for gt_index, gt in enumerate(gt_boxes):
        for prediction_index, prediction in enumerate(predictions):
            overlap = _iou(gt, prediction[0])
            if overlap >= 0.5:
                candidates.append((overlap, gt_index, prediction_index))
    matched_gt: set[int] = set()
    matched_prediction: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for overlap, gt_index, prediction_index in sorted(candidates, reverse=True):
        if gt_index in matched_gt or prediction_index in matched_prediction:
            continue
        matched_gt.add(gt_index)
        matched_prediction.add(prediction_index)
        matches.append((gt_index, prediction_index, overlap))
    return matches, max(0, len(predictions) - len(matched_prediction))


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _validated_records(ledger: Mapping[str, Any]) -> list[dict[str, Any]]:
    if ledger.get("schema") != LEDGER_SCHEMA or ledger.get("status") != LEDGER_STATUS:
        raise ValueError("prediction ledger is not ready")
    raw_records = ledger.get("records")
    if not isinstance(raw_records, list) or not raw_records:
        raise ValueError("prediction ledger has no records")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_records:
        if not isinstance(raw, dict):
            raise TypeError("invalid prediction record")
        sample = raw.get("sample_id")
        if not isinstance(sample, str) or not sample or sample in seen:
            raise ValueError("invalid or duplicate sample id")
        seen.add(sample)
        gt = [_strict_box(box, label="GT box") for box in raw.get("gt_boxes", [])]
        predictions: list[tuple[tuple[float, float, float, float], float]] = []
        for prediction in raw.get("predictions", []):
            if not isinstance(prediction, dict):
                raise TypeError("invalid prediction")
            confidence = prediction.get("confidence")
            if (
                not isinstance(confidence, (int, float))
                or isinstance(confidence, bool)
                or not 0 <= confidence <= 1
            ):
                raise ValueError("invalid prediction confidence")
            predictions.append(
                (
                    _strict_box(prediction.get("box"), label="prediction box"),
                    float(confidence),
                )
            )
        camera_night = raw.get("camera_night")
        episode = raw.get("episode_id")
        if not isinstance(camera_night, str) or not isinstance(episode, str):
            raise TypeError("record lacks camera-night or episode")
        result.append(
            {
                "sample_id": sample,
                "camera_night": camera_night,
                "episode_id": episode,
                "gt_boxes": gt,
                "predictions": predictions,
            }
        )
    return result


def _score_row(
    records: Sequence[Mapping[str, Any]], *, threshold: float, nms_iou: float
) -> dict[str, Any]:
    tp = fp = fn = tn = duplicate = matched = total_gt_boxes = 0
    matched_ious: list[float] = []
    center_offsets: list[float] = []
    by_night: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for record in records:
        gt_boxes = record["gt_boxes"]
        predictions = _offline_nms(
            (item for item in record["predictions"] if item[1] >= threshold),
            threshold=nms_iou,
        )
        gt_present = bool(gt_boxes)
        predicted_present = bool(predictions)
        matches, unmatched_predictions = _match_boxes(gt_boxes, predictions)
        matched_present = bool(matches)
        if gt_present and matched_present:
            tp += 1
        elif not gt_present and predicted_present:
            fp += 1
        elif gt_present:
            fn += 1
            if predicted_present:
                fp += 1
        else:
            tn += 1
        if gt_present:
            by_night[record["camera_night"]][1] += 1
            if matched_present:
                by_night[record["camera_night"]][0] += 1
        if gt_present and matched_present:
            duplicate += unmatched_predictions
        total_gt_boxes += len(gt_boxes)
        matched += len(matches)
        for gt_index, prediction_index, overlap in matches:
            matched_ious.append(overlap)
            gt = gt_boxes[gt_index]
            prediction = predictions[prediction_index][0]
            gt_center = ((gt[0] + gt[2]) / 2, (gt[1] + gt[3]) / 2)
            prediction_center = (
                (prediction[0] + prediction[2]) / 2,
                (prediction[1] + prediction[3]) / 2,
            )
            center_offsets.append(
                math.dist(gt_center, prediction_center) / math.sqrt(2)
            )
    night_recalls = [_ratio(values[0], values[1]) for values in by_night.values()]
    return {
        "threshold": threshold,
        "nms_iou": nms_iou,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": _ratio(tp, tp + fp),
        "recall": _ratio(tp, tp + fn),
        "specificity": _ratio(tn, tn + fp),
        "duplicate": duplicate,
        "matched_box_recall": _ratio(matched, total_gt_boxes),
        "median_matched_iou": statistics.median(matched_ious) if matched_ious else 0.0,
        "median_center_offset": statistics.median(center_offsets)
        if center_offsets
        else 1.0,
        "camera_night_min_recall": min(night_recalls) if night_recalls else 0.0,
    }


def score_ledger(
    ledger: Mapping[str, Any],
    *,
    confidence_grid: Sequence[float] = DEFAULT_CONFIDENCE_GRID,
    nms_grid: Sequence[float] = DEFAULT_NMS_GRID,
) -> list[dict[str, Any]]:
    records = _validated_records(ledger)
    return [
        _score_row(records, threshold=float(threshold), nms_iou=float(nms_iou))
        for nms_iou in nms_grid
        for threshold in confidence_grid
    ]


def _gt_digest(ledger: Mapping[str, Any]) -> str:
    records = _validated_records(ledger)
    canonical = [
        {
            "sample_id": row["sample_id"],
            "camera_night": row["camera_night"],
            "episode_id": row["episode_id"],
            "gt_boxes": row["gt_boxes"],
        }
        for row in records
    ]
    return _sha_bytes(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    )


def _validate_same_protocol(
    ledgers: Mapping[str, Mapping[str, Any]], *, exact_seven: bool
) -> None:
    if exact_seven and set(ledgers) != set(VALIDATION_CANDIDATES):
        raise ValueError("validation requires exactly seven candidates")
    if not ledgers:
        raise ValueError("no ledgers")
    first: tuple[dict[str, Any], str] | None = None
    for candidate, ledger in ledgers.items():
        if ledger.get("candidate") != candidate:
            raise ValueError("candidate/ledger mismatch")
        checkpoint_sha = ledger.get("checkpoint_sha256")
        source_commit = ledger.get("source_commit")
        if not _is_sha(checkpoint_sha, 64) or not _is_sha(source_commit, 40):
            raise ValueError("prediction ledger binding is invalid")
        protocol = ledger.get("protocol")
        if protocol != INFERENCE_PROTOCOL:
            raise ValueError("prediction ledger inference protocol mismatch")
        lineage = ledger.get("lineage")
        if not isinstance(lineage, dict):
            raise TypeError("ledger lacks lineage")
        if lineage.get("evaluator_sha256") != _sha(Path(__file__)):
            raise ValueError("prediction ledger evaluator SHA mismatch")
        if lineage.get("source_sha256") != _sha_bytes(source_commit.encode()):
            raise ValueError("prediction ledger source SHA mismatch")
        if lineage.get("inference_protocol_sha256") != _canonical_digest(protocol):
            raise ValueError("prediction ledger inference protocol SHA mismatch")
        if any(
            not _is_sha(lineage.get(key), 64) for key in ("dataset_sha256", "gt_sha256")
        ):
            raise ValueError("prediction ledger lineage SHA is invalid")
        gt_digest = _gt_digest(ledger)
        if lineage.get("gt_sha256") != gt_digest:
            raise ValueError("prediction ledger GT SHA mismatch")
        binding = (lineage, gt_digest)
        if first is None:
            first = binding
        elif binding != first:
            raise ValueError("prediction ledger lineage mismatch")


def _passes_gate(row: Mapping[str, Any]) -> bool:
    return (
        row["precision"] >= 0.80
        and row["recall"] >= 0.90
        and row["specificity"] >= 0.90
        and row["camera_night_min_recall"] >= 0.85
    )


def select_candidate(
    ledgers: Mapping[str, Mapping[str, Any]],
    *,
    confidence_grid: Sequence[float] = DEFAULT_CONFIDENCE_GRID,
    nms_grid: Sequence[float] = DEFAULT_NMS_GRID,
) -> dict[str, Any]:
    _validate_same_protocol(ledgers, exact_seven=True)
    baseline_rows = {
        (row["threshold"], row["nms_iou"]): row
        for row in score_ledger(
            ledgers["baseline-v26"], confidence_grid=confidence_grid, nms_grid=nms_grid
        )
    }
    passing: list[dict[str, Any]] = []
    for candidate in VALIDATION_CANDIDATES[1:]:
        for row in score_ledger(
            ledgers[candidate], confidence_grid=confidence_grid, nms_grid=nms_grid
        ):
            baseline = baseline_rows[(row["threshold"], row["nms_iou"])]
            if not _passes_gate(row):
                continue
            if row["matched_box_recall"] < baseline["matched_box_recall"] - 0.02:
                continue
            if row["median_matched_iou"] < baseline["median_matched_iou"] - 0.02:
                continue
            passing.append({"candidate": candidate, **row})
    if not passing:
        raise ValidationShortage("V261_VALIDATION_SHORTAGE")

    def rank(row: Mapping[str, Any]) -> tuple[Any, ...]:
        candidate = str(row["candidate"])
        warm_rank = 0 if candidate.startswith("warm-start") else 1
        seed_rank = int(candidate.rsplit("s", 1)[-1])
        return (
            -row["recall"],
            -row["specificity"],
            -row["median_matched_iou"],
            row["duplicate"],
            row["fp"],
            -row["threshold"],
            warm_rank,
            seed_rank,
            row["nms_iou"],
        )

    return min(passing, key=rank)


def validate_evaluation_bindings(
    *,
    dataset_manifest_path: Path,
    checkpoints: Mapping[str, Path],
    completion_manifests: Mapping[str, Path],
    source_commit: str,
    approved_baseline_sha256: str,
) -> dict[str, str]:
    expected_training = set(VALIDATION_CANDIDATES[1:])
    if set(checkpoints) != set(VALIDATION_CANDIDATES):
        raise ValueError("evaluation checkpoints must cover exactly seven candidates")
    if set(completion_manifests) != expected_training:
        raise ValueError("evaluation requires exactly six completion manifests")
    if not _is_sha(source_commit, 40):
        raise ValueError("evaluation source commit is invalid")
    if not _is_sha(approved_baseline_sha256, 64):
        raise ValueError("approved baseline checkpoint SHA is invalid")
    dataset = _load(dataset_manifest_path)
    if (
        dataset.get("schema") != "yolo26n-owner-dataset-v261"
        or dataset.get("status") != "V261_DATASET_READY"
    ):
        raise ValueError("evaluation dataset is not ready")
    dataset_sha = _sha(dataset_manifest_path)
    bindings: dict[str, str] = {}
    for candidate, checkpoint in checkpoints.items():
        if not checkpoint.is_file():
            raise ValueError(f"missing evaluation checkpoint: {candidate}")
        bindings[candidate] = _sha(checkpoint)
    if bindings["baseline-v26"] != approved_baseline_sha256:
        raise ValueError("baseline checkpoint does not match the approved v2.6 SHA")
    for candidate, manifest_path in completion_manifests.items():
        manifest = _load(manifest_path)
        family, seed = candidate.rsplit("-s", 1)
        if (
            manifest.get("schema") != "yolo26n-v261-training-run-v1"
            or manifest.get("status") != "V261_TRAINING_COMPLETE"
            or manifest.get("candidate") != family
            or manifest.get("seed") != int(seed)
            or manifest.get("source_commit") != source_commit
            or manifest.get("dataset_sha256") != dataset_sha
            or manifest.get("best_pt_sha256") != bindings[candidate]
        ):
            raise ValueError(f"training completion binding mismatch: {candidate}")
    return bindings


def build_evaluation_preflight(
    *,
    dataset_manifest_path: Path,
    checkpoints: Mapping[str, Path],
    completion_manifests: Mapping[str, Path],
    source_commit: str,
    approved_baseline_sha256: str,
) -> dict[str, Any]:
    checkpoint_sha256 = validate_evaluation_bindings(
        dataset_manifest_path=dataset_manifest_path,
        checkpoints=checkpoints,
        completion_manifests=completion_manifests,
        source_commit=source_commit,
        approved_baseline_sha256=approved_baseline_sha256,
    )
    return {
        "schema": BINDINGS_SCHEMA,
        "status": BINDINGS_STATUS,
        "source_commit": source_commit,
        "approved_baseline_sha256": approved_baseline_sha256,
        "dataset_sha256": _sha(dataset_manifest_path),
        "evaluator_sha256": _sha(Path(__file__)),
        "checkpoint_sha256": dict(sorted(checkpoint_sha256.items())),
        "completion_manifest_sha256": {
            candidate: _sha(path)
            for candidate, path in sorted(completion_manifests.items())
        },
    }


def _regression_record_set(
    manifest: Mapping[str, Any], *, suite: str
) -> tuple[list[Mapping[str, Any]], str]:
    contract = REGRESSION_SUITES.get(suite)
    if contract is None:
        raise ValueError("unapproved regression suite")
    records = manifest.get("records")
    if not isinstance(records, list):
        raise TypeError("regression dataset manifest lacks records")
    selected = [row for row in records if row.get("split") == contract["source_split"]]
    if len(selected) != contract["sample_count"]:
        raise ValueError("regression suite sample count mismatch")
    canonical: list[dict[str, Any]] = []
    image_shas: set[str] = set()
    for row in selected:
        image_sha = row.get("image_sha256")
        label_sha = row.get("label_sha256")
        if not _is_sha(image_sha, 64) or not _is_sha(label_sha, 64):
            raise ValueError("regression suite record SHA is invalid")
        if image_sha in image_shas:
            raise ValueError("regression suite contains duplicate images")
        image_shas.add(image_sha)
        canonical.append(
            {
                "image_sha256": image_sha,
                "label_sha256": label_sha,
                "split": row.get("split"),
                "camera_night": row.get("camera_night"),
                "episode_id": row.get("episode_id"),
            }
        )
    return selected, _canonical_digest(canonical)


def build_regression_preflight(
    *,
    freeze: Mapping[str, Any],
    suite: str,
    dataset_manifest_path: Path,
    checkpoints: Mapping[str, Path],
    source_commit: str,
) -> dict[str, Any]:
    if freeze.get("schema") != FREEZE_SCHEMA or freeze.get("status") != FREEZE_STATUS:
        raise PermissionError("detector freeze is required before regression preflight")
    if not _is_sha(source_commit, 40):
        raise ValueError("regression source commit is invalid")
    contract = REGRESSION_SUITES.get(suite)
    if contract is None:
        raise ValueError("unapproved regression suite")
    selected_candidate = freeze.get("selected_candidate")
    expected_candidates = {"baseline-v26", selected_candidate}
    if (
        not isinstance(selected_candidate, str)
        or selected_candidate not in VALIDATION_CANDIDATES[1:]
        or set(checkpoints) != expected_candidates
    ):
        raise ValueError("regression checkpoints must be baseline and frozen candidate")
    frozen_checkpoints = freeze.get("checkpoint_sha256")
    if not isinstance(frozen_checkpoints, dict):
        raise TypeError("freeze checkpoint binding is missing")
    checkpoint_sha256: dict[str, str] = {}
    for candidate, checkpoint in checkpoints.items():
        if not checkpoint.is_file():
            raise ValueError(f"missing regression checkpoint: {candidate}")
        checkpoint_sha256[candidate] = _sha(checkpoint)
        if checkpoint_sha256[candidate] != frozen_checkpoints.get(candidate):
            raise ValueError("regression checkpoint does not match detector freeze")
    manifest = _load(dataset_manifest_path)
    if (
        manifest.get("schema") != "yolo26n-owner-dataset-v26"
        or manifest.get("status") != "V26_DATASET_READY"
    ):
        raise ValueError("regression dataset is not the frozen v2.6 parent dataset")
    records, record_set_sha256 = _regression_record_set(manifest, suite=suite)
    return {
        "schema": REGRESSION_BINDINGS_SCHEMA,
        "status": REGRESSION_BINDINGS_STATUS,
        "suite": suite,
        "source_split": contract["source_split"],
        "expected_sample_count": contract["sample_count"],
        "actual_sample_count": len(records),
        "dataset_sha256": _sha(dataset_manifest_path),
        "record_set_sha256": record_set_sha256,
        "source_commit": source_commit,
        "evaluator_sha256": _sha(Path(__file__)),
        "checkpoint_sha256": dict(sorted(checkpoint_sha256.items())),
        "freeze_sha256": _canonical_digest(freeze),
    }


def _validate_prediction_binding(
    *,
    bindings: Mapping[str, Any],
    candidate: str,
    checkpoint: Path,
    manifest_path: Path,
    source_commit: str,
    role: str,
    regression_suite: str | None,
) -> None:
    checkpoint_bindings = bindings.get("checkpoint_sha256")
    if role == "regression":
        contract = REGRESSION_SUITES.get(regression_suite or "")
        if (
            contract is None
            or bindings.get("schema") != REGRESSION_BINDINGS_SCHEMA
            or bindings.get("status") != REGRESSION_BINDINGS_STATUS
            or bindings.get("suite") != regression_suite
            or bindings.get("source_split") != contract["source_split"]
            or bindings.get("expected_sample_count") != contract["sample_count"]
            or bindings.get("actual_sample_count") != contract["sample_count"]
            or not _is_sha(bindings.get("record_set_sha256"), 64)
            or not _is_sha(bindings.get("freeze_sha256"), 64)
        ):
            raise ValueError("regression preflight binding mismatch")
        expected_schema = REGRESSION_BINDINGS_SCHEMA
        expected_status = REGRESSION_BINDINGS_STATUS
    else:
        if regression_suite is not None:
            raise ValueError("validation prediction cannot name a regression suite")
        expected_schema = BINDINGS_SCHEMA
        expected_status = BINDINGS_STATUS
    if (
        bindings.get("schema") != expected_schema
        or bindings.get("status") != expected_status
        or bindings.get("source_commit") != source_commit
        or bindings.get("dataset_sha256") != _sha(manifest_path)
        or bindings.get("evaluator_sha256") != _sha(Path(__file__))
        or not isinstance(checkpoint_bindings, dict)
    ):
        raise ValueError("evaluation preflight binding mismatch")
    if _sha(checkpoint) != checkpoint_bindings.get(candidate):
        raise ValueError("preflight checkpoint binding mismatch")


def _validate_protection_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    if (
        value.get("schema") != PROTECTION_SCHEMA
        or value.get("status") != PROTECTION_STATUS
        or not _is_sha(value.get("future_holdout_manifest_sha256"), 64)
        or value.get("future_holdout_access_count") != 0
        or not _is_sha(value.get("old_validation_manifest_sha256"), 64)
        or value.get("old_validation_inference_count") != 0
    ):
        raise ValueError("protected input evidence is invalid")
    return dict(value)


def build_protection_evidence(
    *,
    future_holdout_manifest_path: Path,
    queue_completion_path: Path,
    old_validation_manifest_path: Path,
    evaluation_root: Path,
) -> dict[str, Any]:
    if not future_holdout_manifest_path.is_file():
        raise ValueError("sealed future holdout manifest is missing")
    if not old_validation_manifest_path.is_file():
        raise ValueError("old validation manifest is missing")
    completion = _load(queue_completion_path)
    if (
        completion.get("schema") != "yolo26n-v261-blind-queue-completion-v1"
        or completion.get("status") != "BLIND_QUEUE_READY"
        or completion.get("future_holdout_access_count") != 0
    ):
        raise ValueError("future holdout zero-access receipt is invalid")
    old_validation_ledgers = [
        path
        for path in evaluation_root.rglob("*")
        if path.is_file()
        and (
            "old-validation" in path.name.lower()
            or "validation153" in path.name.lower()
        )
    ]
    if old_validation_ledgers:
        raise ValueError("old validation inference artifact already exists")
    return {
        "schema": PROTECTION_SCHEMA,
        "status": PROTECTION_STATUS,
        "future_holdout_manifest_sha256": _sha(future_holdout_manifest_path),
        "future_holdout_access_count": completion["future_holdout_access_count"],
        "queue_completion_sha256": _sha(queue_completion_path),
        "old_validation_manifest_sha256": _sha(old_validation_manifest_path),
        "old_validation_inference_count": len(old_validation_ledgers),
    }


def build_detector_freeze(
    ledgers: Mapping[str, Mapping[str, Any]],
    *,
    checkpoint_sha256: Mapping[str, str],
    protection_evidence: Mapping[str, Any],
    confidence_grid: Sequence[float] = DEFAULT_CONFIDENCE_GRID,
    nms_grid: Sequence[float] = DEFAULT_NMS_GRID,
) -> dict[str, Any]:
    if set(checkpoint_sha256) != set(VALIDATION_CANDIDATES) or any(
        not _is_sha(value, 64) for value in checkpoint_sha256.values()
    ):
        raise ValueError("checkpoint binding must cover seven candidates")
    _validate_same_protocol(ledgers, exact_seven=True)
    for candidate, ledger in ledgers.items():
        if ledger.get("checkpoint_sha256") != checkpoint_sha256[candidate]:
            raise ValueError("checkpoint binding does not match prediction ledger")
    protected = _validate_protection_evidence(protection_evidence)
    selected = select_candidate(
        ledgers, confidence_grid=confidence_grid, nms_grid=nms_grid
    )
    candidate = selected["candidate"]
    return {
        "schema": FREEZE_SCHEMA,
        "status": FREEZE_STATUS,
        "selected_candidate": candidate,
        "selected_checkpoint_sha256": checkpoint_sha256[candidate],
        "checkpoint_sha256": dict(sorted(checkpoint_sha256.items())),
        "validation_ledger_sha256": {
            name: _canonical_digest(ledger) for name, ledger in sorted(ledgers.items())
        },
        "threshold": selected["threshold"],
        "nms_iou": selected["nms_iou"],
        "validation_metrics": selected,
        "validation_gt_sha256": _gt_digest(ledgers["baseline-v26"]),
        "inference_contract": dict(INFERENCE_PROTOCOL),
        "temporal_rule": {
            "analysis_fps": 10,
            "window_frames": 5,
            "required_positive_frames": 3,
        },
        "clip_level_acceptance_pending": True,
        "protection_evidence": protected,
    }


def build_regression_report(
    *,
    freeze: Mapping[str, Any],
    suites: Mapping[str, Mapping[str, Mapping[str, Any]]],
    suite_bindings: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if freeze.get("schema") != FREEZE_SCHEMA or freeze.get("status") != FREEZE_STATUS:
        raise PermissionError("detector freeze is required before regression")
    selected = freeze.get("selected_candidate")
    if not isinstance(selected, str) or selected not in VALIDATION_CANDIDATES[1:]:
        raise ValueError("freeze selected candidate is invalid")
    expected_suites = set(REGRESSION_SUITES)
    if set(suites) != expected_suites or set(suite_bindings) != expected_suites:
        raise ValueError("regression requires the two fixed suites")
    reports: dict[str, Any] = {}
    passed = True
    for suite, ledgers in suites.items():
        contract = REGRESSION_SUITES[suite]
        binding = suite_bindings[suite]
        binding_sha256 = _canonical_digest(binding)
        if (
            binding.get("schema") != REGRESSION_BINDINGS_SCHEMA
            or binding.get("status") != REGRESSION_BINDINGS_STATUS
            or binding.get("suite") != suite
            or binding.get("source_split") != contract["source_split"]
            or binding.get("expected_sample_count") != contract["sample_count"]
            or binding.get("actual_sample_count") != contract["sample_count"]
            or binding.get("freeze_sha256") != _canonical_digest(freeze)
            or not _is_sha(binding.get("dataset_sha256"), 64)
            or not _is_sha(binding.get("record_set_sha256"), 64)
        ):
            raise ValueError("regression suite preflight is invalid")
        if set(ledgers) != {"baseline-v26", selected}:
            raise ValueError("regression suite requires baseline and selected ledgers")
        _validate_same_protocol(ledgers, exact_seven=False)
        if any(
            ledger.get("evaluation_role") != "regression"
            or ledger.get("source_split") != contract["source_split"]
            or ledger.get("regression_suite") != suite
            or ledger.get("evaluation_binding_sha256") != binding_sha256
            or len(ledger.get("records", [])) != contract["sample_count"]
            or not isinstance(ledger.get("lineage"), dict)
            or ledger["lineage"].get("dataset_sha256") != binding.get("dataset_sha256")
            for ledger in ledgers.values()
        ):
            raise ValueError("regression ledger does not match its fixed suite")
        checkpoint_bindings = freeze.get("checkpoint_sha256")
        if not isinstance(checkpoint_bindings, dict) or any(
            ledger.get("checkpoint_sha256") != checkpoint_bindings.get(candidate)
            for candidate, ledger in ledgers.items()
        ):
            raise ValueError("regression checkpoint does not match detector freeze")
        baseline = score_ledger(
            ledgers["baseline-v26"],
            confidence_grid=(float(freeze["threshold"]),),
            nms_grid=(float(freeze["nms_iou"]),),
        )[0]
        candidate = score_ledger(
            ledgers[selected],
            confidence_grid=(float(freeze["threshold"]),),
            nms_grid=(float(freeze["nms_iou"]),),
        )[0]
        suite_passed = (
            candidate["precision"] >= baseline["precision"] - 0.02
            and candidate["recall"] >= baseline["recall"] - 0.02
        )
        passed &= suite_passed
        reports[suite] = {
            "binding_sha256": binding_sha256,
            "dataset_sha256": binding["dataset_sha256"],
            "record_set_sha256": binding["record_set_sha256"],
            "gt_sha256": ledgers["baseline-v26"]["lineage"]["gt_sha256"],
            "sample_count": contract["sample_count"],
            "ledger_sha256": {
                candidate_name: _canonical_digest(ledger)
                for candidate_name, ledger in sorted(ledgers.items())
            },
            "baseline": baseline,
            "selected": candidate,
            "precision_delta": candidate["precision"] - baseline["precision"],
            "recall_delta": candidate["recall"] - baseline["recall"],
            "passed": suite_passed,
        }
    return {
        "schema": "yolo26n-v261-regression-report-v1",
        "status": "V261_DEVELOPMENT_CANDIDATE_READY"
        if passed
        else "V261_REGRESSION_FAILED",
        "selected_candidate": selected,
        "suites": reports,
        "regression_only": True,
        "future_holdout_pending": True,
    }


def _resolve_under(root: Path, relative: object) -> Path:
    if not isinstance(relative, str):
        raise TypeError("dataset record path is missing")
    path = (root / relative).resolve()
    if root.resolve() not in path.parents:
        raise ValueError("dataset record path escapes root")
    return path


def _read_gt_labels(path: Path) -> list[list[float]]:
    boxes: list[list[float]] = []
    for raw in path.read_text().splitlines():
        if not raw.strip():
            continue
        values = raw.split()
        if len(values) != 5 or values[0] != "0":
            raise ValueError("invalid YOLO GT label")
        x, y, width, height = (float(value) for value in values[1:])
        boxes.append([x - width / 2, y - height / 2, x + width / 2, y + height / 2])
    return [list(_strict_box(box, label="GT label box")) for box in boxes]


def _ultralytics_predictor(checkpoint: Path) -> Callable[[Path], list[dict[str, Any]]]:
    from ultralytics import YOLO

    model = YOLO(str(checkpoint))

    def predict(image: Path) -> list[dict[str, Any]]:
        results = model.predict(
            source=str(image),
            conf=0.001,
            iou=0.70,
            max_det=50,
            imgsz=960,
            device="mps",
            verbose=False,
        )
        if len(results) != 1:
            raise RuntimeError("YOLO returned an unexpected result count")
        boxes = results[0].boxes
        if boxes is None:
            return []
        coords = boxes.xyxyn.cpu().tolist()
        confidences = boxes.conf.cpu().tolist()
        return [
            {
                "box": list(_strict_box(box, label="prediction box")),
                "confidence": float(confidence),
            }
            for box, confidence in zip(coords, confidences, strict=True)
        ]

    return predict


def run_prediction_once(
    *,
    dataset_root: Path,
    manifest_path: Path,
    split: str,
    evaluation_role: str | None = None,
    candidate: str,
    checkpoint: Path,
    source_commit: str,
    evaluation_root: Path,
    bindings: Mapping[str, Any],
    freeze: Mapping[str, Any] | None = None,
    regression_suite: str | None = None,
    predictor: Callable[[Path], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    if candidate not in VALIDATION_CANDIDATES:
        raise ValueError("unapproved evaluation candidate")
    if split not in {"val", "regression-test"}:
        raise ValueError("unapproved evaluation split")
    role = evaluation_role or ("validation" if split == "val" else "regression")
    if role not in {"validation", "regression"}:
        raise ValueError("unapproved evaluation role")
    if role == "validation" and split != "val":
        raise ValueError("validation role requires the new validation split")
    if not _is_sha(source_commit, 40):
        raise ValueError("evaluation source commit is invalid")
    if role == "regression":
        contract = REGRESSION_SUITES.get(regression_suite or "")
        if contract is None or split != contract["source_split"]:
            raise ValueError("regression prediction requires its fixed suite and split")
        if (
            freeze is None
            or freeze.get("schema") != FREEZE_SCHEMA
            or freeze.get("status") != FREEZE_STATUS
        ):
            raise PermissionError(
                "detector freeze is required before regression prediction"
            )
        selected = freeze.get("selected_candidate")
        if candidate not in {"baseline-v26", selected}:
            raise PermissionError(
                "regression prediction is limited to baseline and selected candidate"
            )
        checkpoint_bindings = freeze.get("checkpoint_sha256")
        if not isinstance(checkpoint_bindings, dict) or _sha(
            checkpoint
        ) != checkpoint_bindings.get(candidate):
            raise ValueError("checkpoint does not match detector freeze")
        if bindings.get("freeze_sha256") != _canonical_digest(freeze):
            raise ValueError("regression preflight does not match detector freeze")
    _validate_prediction_binding(
        bindings=bindings,
        candidate=candidate,
        checkpoint=checkpoint,
        manifest_path=manifest_path,
        source_commit=source_commit,
        role=role,
        regression_suite=regression_suite,
    )
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict) or not isinstance(manifest.get("records"), list):
        raise TypeError("invalid dataset manifest")
    selected_rows = [row for row in manifest["records"] if row.get("split") == split]
    if not selected_rows:
        raise ValueError("evaluation split is empty")
    if role == "regression":
        expected_count = bindings.get("expected_sample_count")
        _, record_set_sha256 = _regression_record_set(
            manifest, suite=regression_suite or ""
        )
        if len(selected_rows) != expected_count or record_set_sha256 != bindings.get(
            "record_set_sha256"
        ):
            raise ValueError("regression dataset does not match fixed preflight")
    claim_once(evaluation_root, f"predict-{candidate}-{role}-{split}")
    active_predictor = predictor or _ultralytics_predictor(checkpoint)
    records: list[dict[str, Any]] = []
    for row in selected_rows:
        image = _resolve_under(dataset_root, row.get("image_path"))
        label = _resolve_under(dataset_root, row.get("label_path"))
        if _sha(image) != row.get("image_sha256") or _sha(label) != row.get(
            "label_sha256"
        ):
            raise ValueError("evaluation dataset byte drift")
        records.append(
            {
                "sample_id": str(row.get("image_sha256")),
                "camera_night": str(row.get("camera_night", "regression")),
                "episode_id": str(row.get("episode_id", row.get("image_sha256"))),
                "gt_boxes": _read_gt_labels(label),
                "predictions": active_predictor(image),
            }
        )
    protocol = dict(INFERENCE_PROTOCOL)
    ledger = {
        "schema": LEDGER_SCHEMA,
        "status": LEDGER_STATUS,
        "candidate": candidate,
        "source_split": split,
        "evaluation_role": role,
        "regression_suite": regression_suite,
        "evaluation_binding_sha256": _canonical_digest(bindings),
        "checkpoint_sha256": _sha(checkpoint),
        "source_commit": source_commit,
        "lineage": {
            "dataset_sha256": _sha(manifest_path),
            "gt_sha256": "pending",
            "source_sha256": _sha_bytes(source_commit.encode()),
            "evaluator_sha256": _sha(Path(__file__)),
            "inference_protocol_sha256": _canonical_digest(protocol),
        },
        "protocol": protocol,
        "records": records,
    }
    ledger["lineage"]["gt_sha256"] = _gt_digest(ledger)
    suffix = "val" if role == "validation" else "regression"
    output = (
        evaluation_root / "prediction-ledgers" / f"{candidate}-{suffix}.private.json"
    )
    _write_json_new(output, ledger)
    return ledger


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    predict = commands.add_parser("predict")
    predict.add_argument("--dataset-root", type=Path, required=True)
    predict.add_argument("--manifest", type=Path, required=True)
    predict.add_argument("--split", choices=("val", "regression-test"), required=True)
    predict.add_argument("--evaluation-role", choices=("validation", "regression"))
    predict.add_argument("--candidate", choices=VALIDATION_CANDIDATES, required=True)
    predict.add_argument("--checkpoint", type=Path, required=True)
    predict.add_argument("--source-commit", required=True)
    predict.add_argument("--evaluation-root", type=Path, required=True)
    predict.add_argument("--attempt-root", type=Path, required=True)
    predict.add_argument("--bindings", type=Path, required=True)
    predict.add_argument("--freeze", type=Path)
    predict.add_argument("--regression-suite", choices=tuple(REGRESSION_SUITES))

    preflight = commands.add_parser("preflight")
    preflight.add_argument("--evaluation-root", type=Path, required=True)
    preflight.add_argument("--attempt-root", type=Path, required=True)
    preflight.add_argument("--dataset-manifest", type=Path, required=True)
    preflight.add_argument("--checkpoint-path-json", type=Path, required=True)
    preflight.add_argument("--training-manifest-root", type=Path, required=True)
    preflight.add_argument("--source-commit", required=True)
    preflight.add_argument("--approved-baseline-sha256", required=True)
    preflight.add_argument("--future-holdout-manifest", type=Path, required=True)
    preflight.add_argument("--queue-completion", type=Path, required=True)
    preflight.add_argument("--old-validation-manifest", type=Path, required=True)

    freeze_parser = commands.add_parser("freeze")
    freeze_parser.add_argument("--evaluation-root", type=Path, required=True)
    freeze_parser.add_argument("--attempt-root", type=Path, required=True)
    freeze_parser.add_argument("--bindings", type=Path, required=True)
    freeze_parser.add_argument("--protection-evidence", type=Path, required=True)

    regression_preflight = commands.add_parser("regression-preflight")
    regression_preflight.add_argument("--evaluation-root", type=Path, required=True)
    regression_preflight.add_argument("--attempt-root", type=Path, required=True)
    regression_preflight.add_argument("--freeze", type=Path, required=True)
    regression_preflight.add_argument(
        "--suite", choices=tuple(REGRESSION_SUITES), required=True
    )
    regression_preflight.add_argument("--dataset-manifest", type=Path, required=True)
    regression_preflight.add_argument(
        "--checkpoint-path-json", type=Path, required=True
    )
    regression_preflight.add_argument("--source-commit", required=True)

    regression = commands.add_parser("regression")
    regression.add_argument("--evaluation-root", type=Path, required=True)
    regression.add_argument("--attempt-root", type=Path, required=True)
    regression.add_argument("--freeze", type=Path, required=True)
    regression.add_argument("--recent-suite-root", type=Path, required=True)
    regression.add_argument("--old-suite-root", type=Path, required=True)
    regression.add_argument("--recent-bindings", type=Path, required=True)
    regression.add_argument("--old-bindings", type=Path, required=True)
    args = parser.parse_args(argv)
    _require_evaluation_root(args.attempt_root, args.evaluation_root)

    if args.command == "preflight":
        checkpoint_paths_raw = _load(args.checkpoint_path_json)
        if not all(isinstance(value, str) for value in checkpoint_paths_raw.values()):
            raise TypeError("checkpoint path map must contain strings")
        artifact = build_evaluation_preflight(
            dataset_manifest_path=args.dataset_manifest,
            checkpoints={
                candidate: Path(path)
                for candidate, path in checkpoint_paths_raw.items()
            },
            completion_manifests={
                candidate: args.training_manifest_root / f"{candidate}.private.json"
                for candidate in VALIDATION_CANDIDATES[1:]
            },
            source_commit=args.source_commit,
            approved_baseline_sha256=args.approved_baseline_sha256,
        )
        protection = build_protection_evidence(
            future_holdout_manifest_path=args.future_holdout_manifest,
            queue_completion_path=args.queue_completion,
            old_validation_manifest_path=args.old_validation_manifest,
            evaluation_root=args.evaluation_root,
        )
        _write_json_new(
            args.evaluation_root / "evaluation-bindings.private.json", artifact
        )
        _write_json_new(
            args.evaluation_root / "protection-evidence.private.json", protection
        )
        print(BINDINGS_STATUS)
        return 0
    if args.command == "predict":
        run_prediction_once(
            dataset_root=args.dataset_root,
            manifest_path=args.manifest,
            split=args.split,
            evaluation_role=args.evaluation_role,
            candidate=args.candidate,
            checkpoint=args.checkpoint,
            source_commit=args.source_commit,
            evaluation_root=args.evaluation_root,
            bindings=_load(args.bindings),
            freeze=_load(args.freeze) if args.freeze else None,
            regression_suite=args.regression_suite,
        )
        print(LEDGER_STATUS)
        return 0
    if args.command == "freeze":
        bindings = _load(args.bindings)
        if (
            bindings.get("schema") != BINDINGS_SCHEMA
            or bindings.get("status") != BINDINGS_STATUS
            or not isinstance(bindings.get("checkpoint_sha256"), dict)
        ):
            raise ValueError("evaluation bindings are not ready")
        ledgers = {
            candidate: _load(
                args.evaluation_root
                / "prediction-ledgers"
                / f"{candidate}-val.private.json"
            )
            for candidate in VALIDATION_CANDIDATES
        }
        if any(
            ledger.get("source_commit") != bindings.get("source_commit")
            or not isinstance(ledger.get("lineage"), dict)
            or ledger["lineage"].get("dataset_sha256") != bindings.get("dataset_sha256")
            or ledger["lineage"].get("evaluator_sha256")
            != bindings.get("evaluator_sha256")
            for ledger in ledgers.values()
        ):
            raise ValueError("validation ledger does not match evaluation preflight")
        claim_once(args.evaluation_root, "freeze-validation")
        freeze = build_detector_freeze(
            ledgers,
            checkpoint_sha256=bindings["checkpoint_sha256"],
            protection_evidence=_load(args.protection_evidence),
        )
        _write_json_new(args.evaluation_root / "detector-freeze.private.json", freeze)
        print(FREEZE_STATUS)
        return 0
    if args.command == "regression-preflight":
        checkpoint_paths_raw = _load(args.checkpoint_path_json)
        if not all(isinstance(value, str) for value in checkpoint_paths_raw.values()):
            raise TypeError("checkpoint path map must contain strings")
        artifact = build_regression_preflight(
            freeze=_load(args.freeze),
            suite=args.suite,
            dataset_manifest_path=args.dataset_manifest,
            checkpoints={
                candidate: Path(path)
                for candidate, path in checkpoint_paths_raw.items()
            },
            source_commit=args.source_commit,
        )
        _write_json_new(
            args.evaluation_root / "regression-bindings.private.json", artifact
        )
        print(REGRESSION_BINDINGS_STATUS)
        return 0

    freeze = _load(args.freeze)
    selected = freeze.get("selected_candidate")
    suites = {
        "v26-recent-val505": {
            candidate: _load(
                args.recent_suite_root / f"{candidate}-regression.private.json"
            )
            for candidate in ("baseline-v26", selected)
        },
        "old-internal-test151": {
            candidate: _load(
                args.old_suite_root / f"{candidate}-regression.private.json"
            )
            for candidate in ("baseline-v26", selected)
        },
    }
    claim_once(args.evaluation_root, "score-regression")
    report = build_regression_report(
        freeze=freeze,
        suites=suites,
        suite_bindings={
            "v26-recent-val505": _load(args.recent_bindings),
            "old-internal-test151": _load(args.old_bindings),
        },
    )
    _write_json_new(args.evaluation_root / "regression-report.private.json", report)
    print(report["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

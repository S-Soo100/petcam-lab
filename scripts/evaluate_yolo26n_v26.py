"""Evaluate YOLO26n v2.6 candidates under one development-only protocol.

The module deliberately separates sparse-frame detector selection from the
still-pending contiguous 10fps clip acceptance.  It never deploys a model or
writes outside an explicitly supplied private evaluation root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import subprocess
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from scripts.evaluate_yolo26n_v22 import PredictionBox, _load_yolo_boxes, make_ultralytics_predictor


THRESHOLDS = tuple(round(index * 0.05, 2) for index in range(1, 17))
NMS_IOUS = (0.40, 0.55, 0.70)
VALIDATION_CANDIDATES = (
    "baseline-v25",
    "warm-start-s26",
    "warm-start-s27",
    "warm-start-s28",
    "clean-reference-s26",
    "clean-reference-s27",
    "clean-reference-s28",
)
TRAINED_CANDIDATES = VALIDATION_CANDIDATES[1:]
INFERENCE_CONTRACT: dict[str, object] = {
    "confidence": 0.001,
    "imgsz": 960,
    "nms_iou": 0.70,
    "max_det": 50,
    "device": "mps",
    "match_iou": 0.50,
}
SELECTION_GATES: dict[str, float] = {
    "precision": 0.80,
    "recall": 0.90,
    "specificity": 0.90,
    "camera_night_recall_min": 0.85,
}
TEMPORAL_CONTRACT: dict[str, object] = {
    "max_analysis_fps": 10.0,
    "window_frames": 5,
    "min_positive_frames": 3,
}


@dataclass(frozen=True, slots=True)
class V26Sample:
    sequence: str
    image_path: Path
    label_path: Path
    image_sha256: str
    label_sha256: str
    normalized_gt_boxes: tuple[tuple[float, float, float, float], ...]
    camera_night: str
    episode_id: str
    clip_ref: str


@dataclass(frozen=True, slots=True)
class V26EvaluationRecord:
    sequence: str
    image_sha256: str
    camera_night: str
    episode_id: str
    clip_ref: str
    gt_boxes: tuple[tuple[float, float, float, float], ...]
    predictions: tuple[PredictionBox, ...]


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


def _resolve(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("dataset path must be relative")
    resolved_root = root.resolve()
    result = (resolved_root / relative).resolve()
    if result != resolved_root and resolved_root not in result.parents:
        raise ValueError("dataset path escapes root")
    return result


def _load_object(path: Path, *, label: str) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{label} root must be object")
    return value


def verify_evaluator_source_commit(
    *,
    source_commit: str,
    repo_root: Path | None = None,
    runner_path: Path = Path(__file__),
) -> None:
    """Prove that the running evaluator bytes are present in the named commit."""
    if not _is_sha(source_commit, 40):
        raise ValueError("v2.6 evaluator source commit invalid")
    runner = runner_path.resolve()
    if repo_root is None:
        result = subprocess.run(
            ["git", "-C", str(runner.parent), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
        root = Path(result.stdout.strip()).resolve()
    else:
        root = repo_root.resolve()
    try:
        relative = runner.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("v2.6 evaluator runner is outside repository") from error
    try:
        committed = subprocess.run(
            ["git", "-C", str(root), "show", f"{source_commit}:{relative}"],
            check=True,
            capture_output=True,
        ).stdout
    except subprocess.CalledProcessError as error:
        raise ValueError("v2.6 evaluator source commit does not contain runner") from error
    if committed != runner.read_bytes():
        raise ValueError("v2.6 evaluator runner bytes differ from source commit")


def verify_prediction_checkpoint_binding(
    *,
    candidate: str,
    checkpoint_path: Path,
    verified: Mapping[str, Path],
) -> None:
    expected = verified.get(candidate)
    if expected is None or checkpoint_path.resolve() != expected.resolve():
        raise ValueError("v2.6 checkpoint is not the verified training artifact")


def _validate_dataset_manifest(payload: Mapping[str, object]) -> list[dict[str, object]]:
    if (
        payload.get("schema") != "yolo26n-owner-dataset-v26"
        or payload.get("status") != "V26_DATASET_READY"
        or payload.get("evaluation_tier") != "development"
        or payload.get("image_count") != 4471
        or payload.get("active_image_count") != 4167
        or payload.get("active_split_counts") != {"train": 3662, "val": 505}
        or payload.get("regression_split_counts")
        != {"regression-test": 151, "regression-val": 153}
        or not _is_sha(payload.get("source_commit"), 40)
        or not _is_sha(payload.get("recent_split_sha256"))
        or any(
            payload.get(field) != 0
            for field in ("db_write_count", "r2_write_count", "service_write_count", "deploy_count")
        )
    ):
        raise ValueError("v2.6 dataset manifest contract mismatch")
    records = payload.get("records")
    if not isinstance(records, list) or len(records) != 4471 or not all(isinstance(row, dict) for row in records):
        raise ValueError("v2.6 dataset records missing")
    split_counts = Counter(str(row.get("split")) for row in records)
    if split_counts != Counter({"train": 3662, "val": 505, "regression-val": 153, "regression-test": 151}):
        raise ValueError("v2.6 dataset record split count mismatch")
    return records


def _recent_val_index(payload: Mapping[str, object]) -> dict[str, dict[str, object]]:
    if (
        payload.get("schema") != "yolo26n-v26-recent-split-plan-v1"
        or payload.get("status") != "V26_RECENT_SPLIT_READY"
        or payload.get("recent_image_count") != 2508
        or payload.get("recent_split_counts") != {"train": 2003, "val": 505}
        or payload.get("episode_count") != 314
    ):
        raise ValueError("v2.6 recent split contract mismatch")
    records = payload.get("recent_records")
    if not isinstance(records, list) or len(records) != 2508:
        raise ValueError("v2.6 recent split records missing")
    index: dict[str, dict[str, object]] = {}
    split_counts: Counter[str] = Counter()
    for raw in records:
        if not isinstance(raw, dict):
            raise ValueError("v2.6 recent split record malformed")
        split = raw.get("split")
        image_sha = raw.get("image_sha256")
        if split not in {"train", "val"} or not _is_sha(image_sha):
            raise ValueError("v2.6 recent split identity malformed")
        split_counts[str(split)] += 1
        if split == "val":
            if image_sha in index:
                raise ValueError("v2.6 recent validation duplicate")
            for field in ("camera_night", "episode_id", "clip_ref"):
                if not isinstance(raw.get(field), str) or not raw[field]:
                    raise ValueError("v2.6 recent validation metadata missing")
            index[str(image_sha)] = raw
    if split_counts != Counter({"train": 2003, "val": 505}) or len(index) != 505:
        raise ValueError("v2.6 recent split count mismatch")
    return index


def load_v26_samples(
    *,
    dataset_root: Path,
    manifest_path: Path,
    recent_split_path: Path,
    split: str,
) -> tuple[V26Sample, ...]:
    if split not in {"val", "regression-test"}:
        raise ValueError("evaluation split must be val or regression-test")
    manifest = _load_object(manifest_path, label="dataset manifest")
    records = _validate_dataset_manifest(manifest)
    if _sha(recent_split_path) != manifest["recent_split_sha256"]:
        raise ValueError("v2.6 recent split SHA mismatch")
    recent_index = _recent_val_index(_load_object(recent_split_path, label="recent split"))
    samples: list[V26Sample] = []
    seen_sequence: set[str] = set()
    seen_image: set[str] = set()
    for record in records:
        if record.get("split") != split:
            continue
        sequence = record.get("sequence")
        image_sha = record.get("image_sha256")
        label_sha = record.get("label_sha256")
        if (
            not isinstance(sequence, str)
            or not sequence
            or sequence in seen_sequence
            or not _is_sha(image_sha)
            or image_sha in seen_image
            or not _is_sha(label_sha)
        ):
            raise ValueError("v2.6 evaluation record identity malformed")
        image_path = _resolve(dataset_root, record.get("image_path"))
        label_path = _resolve(dataset_root, record.get("label_path"))
        if (
            not image_path.is_file()
            or not label_path.is_file()
            or _sha(image_path) != image_sha
            or _sha(label_path) != label_sha
        ):
            raise ValueError("v2.6 evaluation bytes mismatch")
        if split == "val":
            recent = recent_index.get(str(image_sha))
            if recent is None:
                raise ValueError("v2.6 validation is not bound to recent split")
            camera_night = recent["camera_night"]
            episode_id = recent["episode_id"]
            clip_ref = recent["clip_ref"]
            if record.get("camera_night") != camera_night or record.get("episode_id") != episode_id:
                raise ValueError("v2.6 validation metadata drift")
        else:
            camera_night = record.get("camera_night_group", "old-regression")
            episode_id = sequence
            clip_ref = sequence
        if not all(isinstance(value, str) and value for value in (camera_night, episode_id, clip_ref)):
            raise ValueError("v2.6 evaluation strata malformed")
        label_bytes = label_path.read_bytes()
        samples.append(
            V26Sample(
                sequence=sequence,
                image_path=image_path,
                label_path=label_path,
                image_sha256=str(image_sha),
                label_sha256=str(label_sha),
                normalized_gt_boxes=_load_yolo_boxes(label_bytes),
                camera_night=str(camera_night),
                episode_id=str(episode_id),
                clip_ref=str(clip_ref),
            )
        )
        seen_sequence.add(sequence)
        seen_image.add(str(image_sha))
    expected = 505 if split == "val" else 151
    if len(samples) != expected:
        raise ValueError("v2.6 evaluation split count mismatch")
    return tuple(samples)


def verify_v26_training_artifacts(
    *,
    attempt_root: Path,
    training_source_commit: str,
) -> dict[str, Path]:
    if not _is_sha(training_source_commit, 40):
        raise ValueError("v2.6 training source commit invalid")
    dataset_manifest = attempt_root / "dataset-v26-v1/manifest.private.json"
    warm_initializer = attempt_root / "inputs/v25-warm-start-best.pt"
    clean_initializer = attempt_root / "inputs/yolo26n-clean-reference.pt"
    for path in (dataset_manifest, warm_initializer, clean_initializer):
        if not path.is_file():
            raise ValueError("v2.6 training input missing")
    dataset_sha = _sha(dataset_manifest)
    initializer_sha = {
        "warm-start": _sha(warm_initializer),
        "clean-reference": _sha(clean_initializer),
    }
    verified: dict[str, Path] = {"baseline-v25": warm_initializer}
    for candidate in ("warm-start", "clean-reference"):
        for seed in (26, 27, 28):
            run_name = f"{candidate}-s{seed}"
            manifest_path = attempt_root / "run-manifests-v26-v2" / f"{run_name}.private.json"
            results_path = attempt_root / "runs-v26-comparison-v2" / run_name / "results.csv"
            best_path = attempt_root / "runs-v26-comparison-v2" / run_name / "weights/best.pt"
            if not manifest_path.is_file() or not results_path.is_file() or not best_path.is_file():
                raise ValueError("v2.6 training artifact missing")
            manifest = _load_object(manifest_path, label="training manifest")
            if (
                manifest.get("schema") != "yolo26n-v26-training-run-v1"
                or manifest.get("status") != "V26_TRAINING_COMPLETED"
                or manifest.get("run_name") != run_name
                or manifest.get("candidate") != candidate
                or manifest.get("seed") != seed
                or manifest.get("returncode") != 0
                or manifest.get("source_commit") != training_source_commit
                or manifest.get("dataset_manifest_sha256") != dataset_sha
                or manifest.get("initializer_sha256") != initializer_sha[candidate]
                or any(
                    manifest.get(field) != 0
                    for field in ("db_write_count", "r2_write_count", "service_write_count", "deploy_count")
                )
            ):
                raise ValueError("v2.6 training manifest contract mismatch")
            if manifest.get("results_csv_sha256") != _sha(results_path):
                raise ValueError("v2.6 results.csv SHA mismatch")
            if manifest.get("best_pt_sha256") != _sha(best_path):
                raise ValueError("v2.6 best.pt SHA mismatch")
            with results_path.open("rb") as handle:
                if sum(1 for _line in handle) < 2:
                    raise ValueError("v2.6 results.csv partial")
            verified[run_name] = best_path
    if set(verified) != set(VALIDATION_CANDIDATES):
        raise ValueError("v2.6 training candidate set mismatch")
    return verified


def _iou(left: Sequence[float], right: Sequence[float]) -> float:
    width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    intersection = width * height
    union = (
        (left[2] - left[0]) * (left[3] - left[1])
        + (right[2] - right[0]) * (right[3] - right[1])
        - intersection
    )
    return intersection / union if union else 0.0


def _offline_nms(predictions: Sequence[PredictionBox], *, threshold: float, nms_iou: float) -> tuple[PredictionBox, ...]:
    ordered = sorted(
        (prediction for prediction in predictions if prediction.confidence >= threshold),
        key=lambda prediction: (-prediction.confidence, prediction.xyxy),
    )
    kept: list[PredictionBox] = []
    for prediction in ordered:
        if all(_iou(prediction.xyxy, existing.xyxy) <= nms_iou for existing in kept):
            kept.append(prediction)
    return tuple(kept)


def _records(ledger: Mapping[str, object]) -> tuple[V26EvaluationRecord, ...]:
    if (
        ledger.get("schema") != "yolo26n-v26-prediction-ledger-v1"
        or ledger.get("status") != "V26_PREDICTIONS_READY"
        or ledger.get("evaluation_tier") != "development"
        or ledger.get("split") not in {"val", "regression-test"}
        or ledger.get("candidate") not in VALIDATION_CANDIDATES
        or ledger.get("inference") != INFERENCE_CONTRACT
    ):
        raise ValueError("v2.6 prediction ledger contract invalid")
    for field, length in (
        ("source_commit", 40),
        ("runner_sha256", 64),
        ("dataset_manifest_sha256", 64),
        ("recent_split_manifest_sha256", 64),
        ("checkpoint_sha256", 64),
    ):
        if not _is_sha(ledger.get(field), length):
            raise ValueError("v2.6 prediction ledger provenance invalid")
    if any(ledger.get(field) != 0 for field in ("db_write_count", "r2_write_count", "service_write_count", "deploy_count")):
        raise ValueError("v2.6 prediction ledger forbidden write")
    raw_records = ledger.get("records")
    if not isinstance(raw_records, list):
        raise ValueError("v2.6 prediction records missing")
    parsed: list[V26EvaluationRecord] = []
    seen_sequence: set[str] = set()
    seen_image: set[str] = set()
    gt_count = prediction_count = 0
    for raw in raw_records:
        if not isinstance(raw, Mapping):
            raise ValueError("v2.6 prediction record malformed")
        sequence = raw.get("sequence")
        image_sha = raw.get("image_sha256")
        if (
            not isinstance(sequence, str)
            or not sequence
            or sequence in seen_sequence
            or not _is_sha(image_sha)
            or image_sha in seen_image
        ):
            raise ValueError("v2.6 prediction record identity malformed")
        strata = tuple(raw.get(field) for field in ("camera_night", "episode_id", "clip_ref"))
        if not all(isinstance(value, str) and value for value in strata):
            raise ValueError("v2.6 prediction strata missing")
        raw_gt = raw.get("gt_boxes")
        raw_predictions = raw.get("predictions")
        if not isinstance(raw_gt, list) or not isinstance(raw_predictions, list):
            raise ValueError("v2.6 prediction geometry missing")
        gt_boxes: list[tuple[float, float, float, float]] = []
        for value in raw_gt:
            if not isinstance(value, list) or len(value) != 4:
                raise ValueError("v2.6 GT geometry malformed")
            box = tuple(_number(item, "GT coordinate") for item in value)
            if box[0] >= box[2] or box[1] >= box[3]:
                raise ValueError("v2.6 GT geometry malformed")
            gt_boxes.append(box)
        predictions: list[PredictionBox] = []
        for value in raw_predictions:
            if not isinstance(value, Mapping) or not isinstance(value.get("xyxy"), list) or len(value["xyxy"]) != 4:
                raise ValueError("v2.6 prediction geometry malformed")
            confidence = _number(value.get("confidence"), "confidence")
            box = tuple(_number(item, "prediction coordinate") for item in value["xyxy"])
            if not 0 <= confidence <= 1 or box[0] >= box[2] or box[1] >= box[3]:
                raise ValueError("v2.6 prediction geometry malformed")
            predictions.append(PredictionBox(confidence, box))
        parsed.append(
            V26EvaluationRecord(
                sequence=sequence,
                image_sha256=str(image_sha),
                camera_night=str(strata[0]),
                episode_id=str(strata[1]),
                clip_ref=str(strata[2]),
                gt_boxes=tuple(gt_boxes),
                predictions=tuple(predictions),
            )
        )
        seen_sequence.add(sequence)
        seen_image.add(str(image_sha))
        gt_count += len(gt_boxes)
        prediction_count += len(predictions)
    for field, actual in (
        ("image_count", len(parsed)),
        ("gt_box_count", gt_count),
        ("prediction_count", prediction_count),
    ):
        if type(ledger.get(field)) is not int or ledger[field] != actual:
            raise ValueError("v2.6 prediction ledger count mismatch")
    return tuple(parsed)


def _score_row(
    records: Sequence[V26EvaluationRecord], *, threshold: float, nms_iou: float
) -> dict[str, object]:
    tp = fp = fn = duplicate = 0
    empty_count = empty_correct = 0
    camera_tp: defaultdict[str, int] = defaultdict(int)
    camera_fn: defaultdict[str, int] = defaultdict(int)
    for record in records:
        predictions = _offline_nms(record.predictions, threshold=threshold, nms_iou=nms_iou)
        if not record.gt_boxes:
            empty_count += 1
            if not predictions:
                empty_correct += 1
            fp += len(predictions)
            continue
        unmatched = set(range(len(record.gt_boxes)))
        for prediction in predictions:
            overlaps = sorted(
                ((_iou(prediction.xyxy, record.gt_boxes[index]), index) for index in range(len(record.gt_boxes))),
                reverse=True,
            )
            if overlaps and overlaps[0][0] >= float(INFERENCE_CONTRACT["match_iou"]):
                index = overlaps[0][1]
                if index in unmatched:
                    unmatched.remove(index)
                    tp += 1
                    camera_tp[record.camera_night] += 1
                else:
                    duplicate += 1
                    fp += 1
            else:
                fp += 1
        fn += len(unmatched)
        camera_fn[record.camera_night] += len(unmatched)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    specificity = empty_correct / empty_count if empty_count else 0.0
    camera_recalls = [
        camera_tp[camera] / (camera_tp[camera] + camera_fn[camera])
        for camera in sorted(set(camera_tp) | set(camera_fn))
        if camera_tp[camera] + camera_fn[camera]
    ]
    return {
        "threshold": threshold,
        "nms_iou": nms_iou,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "duplicate": duplicate,
        "camera_night_recall_min": min(camera_recalls) if camera_recalls else 0.0,
    }


def score_v26_ledger(ledger: Mapping[str, object]) -> list[dict[str, object]]:
    records = _records(ledger)
    return [
        _score_row(records, threshold=threshold, nms_iou=nms_iou)
        for threshold in THRESHOLDS
        for nms_iou in NMS_IOUS
    ]


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values or not 0 <= probability <= 1:
        raise ValueError("bootstrap percentile input invalid")
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * probability)]


def paired_episode_bootstrap(
    baseline_ledger: Mapping[str, object],
    candidate_ledger: Mapping[str, object],
    *,
    threshold: float,
    nms_iou: float,
    seed: int = 260831,
    repetitions: int = 2000,
) -> dict[str, object]:
    if threshold not in THRESHOLDS or nms_iou not in NMS_IOUS:
        raise ValueError("bootstrap metric grid mismatch")
    if type(seed) is not int or type(repetitions) is not int or repetitions < 100:
        raise ValueError("bootstrap contract invalid")
    baseline_records = _records(baseline_ledger)
    candidate_records = _records(candidate_ledger)
    if _gt_digest(baseline_ledger) != _gt_digest(candidate_ledger):
        raise ValueError("bootstrap ledgers do not share GT")
    baseline_by_image = {record.image_sha256: record for record in baseline_records}
    candidate_by_image = {record.image_sha256: record for record in candidate_records}
    if set(baseline_by_image) != set(candidate_by_image):
        raise ValueError("bootstrap ledgers do not share images")
    episode_images: defaultdict[str, list[str]] = defaultdict(list)
    for record in baseline_records:
        episode_images[record.episode_id].append(record.image_sha256)
    episodes = sorted(episode_images)
    if not episodes:
        raise ValueError("bootstrap episodes missing")

    baseline_point = _score_row(baseline_records, threshold=threshold, nms_iou=nms_iou)
    candidate_point = _score_row(candidate_records, threshold=threshold, nms_iou=nms_iou)
    randomizer = random.Random(seed)
    recall_deltas: list[float] = []
    specificity_deltas: list[float] = []
    for _ in range(repetitions):
        sampled = [episodes[randomizer.randrange(len(episodes))] for _index in episodes]
        baseline_sample: list[V26EvaluationRecord] = []
        candidate_sample: list[V26EvaluationRecord] = []
        for episode in sampled:
            for image_sha in episode_images[episode]:
                baseline_sample.append(baseline_by_image[image_sha])
                candidate_sample.append(candidate_by_image[image_sha])
        baseline_metric = _score_row(baseline_sample, threshold=threshold, nms_iou=nms_iou)
        candidate_metric = _score_row(candidate_sample, threshold=threshold, nms_iou=nms_iou)
        recall_deltas.append(float(candidate_metric["recall"]) - float(baseline_metric["recall"]))
        specificity_deltas.append(
            float(candidate_metric["specificity"]) - float(baseline_metric["specificity"])
        )
    return {
        "seed": seed,
        "repetitions": repetitions,
        "cluster": "episode_id",
        "recall_delta": float(candidate_point["recall"]) - float(baseline_point["recall"]),
        "recall_delta_ci95": [
            _percentile(recall_deltas, 0.025),
            _percentile(recall_deltas, 0.975),
        ],
        "specificity_delta": float(candidate_point["specificity"]) - float(baseline_point["specificity"]),
        "specificity_delta_ci95": [
            _percentile(specificity_deltas, 0.025),
            _percentile(specificity_deltas, 0.975),
        ],
    }


def _normalize_metric(row: Mapping[str, object]) -> dict[str, object]:
    threshold = _number(row.get("threshold"), "threshold")
    nms_iou = _number(row.get("nms_iou"), "nms_iou")
    result = {
        "threshold": threshold,
        "nms_iou": nms_iou,
        "precision": _number(row.get("precision"), "precision"),
        "recall": _number(row.get("recall"), "recall"),
        "specificity": _number(row.get("specificity"), "specificity"),
        "camera_night_recall_min": _number(row.get("camera_night_recall_min"), "camera recall"),
        "fp": int(_number(row.get("fp"), "fp")),
        "duplicate": int(_number(row.get("duplicate"), "duplicate")),
    }
    if threshold not in THRESHOLDS or nms_iou not in NMS_IOUS:
        raise ValueError("v2.6 metric grid mismatch")
    if any(not 0 <= float(result[field]) <= 1 for field in ("precision", "recall", "specificity", "camera_night_recall_min")):
        raise ValueError("v2.6 metric outside contract")
    if int(result["fp"]) < 0 or int(result["duplicate"]) < 0:
        raise ValueError("v2.6 metric outside contract")
    for field in ("tp", "fn"):
        if field in row:
            result[field] = int(_number(row[field], field))
    return result


def select_v26_candidate(
    candidate_metrics: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, object]:
    if set(candidate_metrics) != set(TRAINED_CANDIDATES):
        raise ValueError("all six v2.6 candidate metrics are required")
    normalized: dict[str, list[dict[str, object]]] = {}
    best: dict[str, dict[str, object]] = {}
    for candidate in TRAINED_CANDIDATES:
        rows = [_normalize_metric(row) for row in candidate_metrics[candidate]]
        normalized[candidate] = rows
        eligible = [
            row
            for row in rows
            if all(float(row[field]) >= floor for field, floor in SELECTION_GATES.items())
        ]
        if eligible:
            best[candidate] = min(
                eligible,
                key=lambda row: (
                    -float(row["recall"]),
                    -float(row["specificity"]),
                    int(row["duplicate"]),
                    int(row["fp"]),
                    -float(row["threshold"]),
                    float(row["nms_iou"]),
                ),
            )
    if not best:
        raise ValueError("V26_VALIDATION_SHORTAGE")
    candidate, metric = min(
        best.items(),
        key=lambda item: (
            -float(item[1]["recall"]),
            -float(item[1]["specificity"]),
            int(item[1]["duplicate"]),
            int(item[1]["fp"]),
            0 if item[0].startswith("warm-start") else 1,
            item[0],
        ),
    )
    return {
        "candidate": candidate,
        "threshold": metric["threshold"],
        "nms_iou": metric["nms_iou"],
        "validation_precision": metric["precision"],
        "validation_recall": metric["recall"],
        "validation_specificity": metric["specificity"],
        "validation_camera_night_recall_min": metric["camera_night_recall_min"],
        "selection_gates": dict(SELECTION_GATES),
        "candidate_metrics": normalized,
    }


def _gt_digest(ledger: Mapping[str, object]) -> str:
    _records(ledger)
    payload = [
        {
            key: row[key]
            for key in (
                "sequence",
                "image_sha256",
                "camera_night",
                "episode_id",
                "clip_ref",
                "width",
                "height",
                "gt_boxes",
            )
        }
        for row in ledger["records"]
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_detector_freeze(
    ledgers: Mapping[str, Mapping[str, object]],
    *,
    ledger_sha256: Mapping[str, str],
) -> dict[str, object]:
    if set(ledgers) != set(VALIDATION_CANDIDATES) or set(ledger_sha256) != set(VALIDATION_CANDIDATES):
        raise ValueError("baseline and all seven validation ledgers are required")
    if not all(_is_sha(value) for value in ledger_sha256.values()):
        raise ValueError("v2.6 validation ledger SHA invalid")
    shared: dict[str, object] | None = None
    gt_digest: str | None = None
    checkpoints: dict[str, str] = {}
    metrics: dict[str, list[dict[str, object]]] = {}
    for candidate in VALIDATION_CANDIDATES:
        ledger = ledgers[candidate]
        _records(ledger)
        if ledger.get("split") != "val" or ledger.get("candidate") != candidate:
            raise ValueError("v2.6 validation ledger identity mismatch")
        contract = {
            key: ledger.get(key)
            for key in (
                "dataset_manifest_sha256",
                "recent_split_manifest_sha256",
                "source_commit",
                "runner_sha256",
                "inference",
            )
        }
        digest = _gt_digest(ledger)
        if shared is None:
            shared = contract
            gt_digest = digest
        elif shared != contract or gt_digest != digest:
            raise ValueError("v2.6 validation ledgers do not share one protocol and GT")
        checkpoints[candidate] = str(ledger["checkpoint_sha256"])
        metrics[candidate] = score_v26_ledger(ledger)
    assert shared is not None and gt_digest is not None
    if shared["runner_sha256"] != _sha(Path(__file__)):
        raise ValueError("v2.6 validation runner differs from current evaluator")
    selection = select_v26_candidate({candidate: metrics[candidate] for candidate in TRAINED_CANDIDATES})
    selected = str(selection["candidate"])
    episode_bootstrap = paired_episode_bootstrap(
        ledgers["baseline-v25"],
        ledgers[selected],
        threshold=float(selection["threshold"]),
        nms_iou=float(selection["nms_iou"]),
    )
    return {
        "schema": "yolo26n-v26-detector-freeze-v1",
        "status": "V26_DETECTOR_FROZEN_DEVELOPMENT_ONLY",
        "evaluation_tier": "development",
        **selection,
        **shared,
        "checkpoint_sha256": checkpoints[selected],
        "candidate_checkpoint_sha256": checkpoints,
        "validation_ledger_sha256": dict(ledger_sha256),
        "validation_ground_truth_sha256": gt_digest,
        "candidate_metrics": metrics,
        "episode_cluster_bootstrap": episode_bootstrap,
        "baseline_remeasured_same_protocol": True,
        "temporal_contract": dict(TEMPORAL_CONTRACT),
        "clip_level_acceptance_pending": True,
        "future_holdout_required": True,
        "production_adoption": False,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "deploy_count": 0,
    }


def _write_private_new(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("v2.6 private artifact short write")
            written += count
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
        {
            "schema": "yolo26n-v26-one-shot-claim-v1",
            "status": "STARTED",
            "operation": operation,
        },
    )


def _prediction_path(root: Path, candidate: str, split: str) -> Path:
    if candidate not in VALIDATION_CANDIDATES or split not in {"val", "regression-test"}:
        raise ValueError("v2.6 prediction identity invalid")
    return root / "prediction-ledgers" / f"{candidate}-{split}.private.json"


def _validate_detector_freeze(freeze: Mapping[str, object]) -> None:
    if (
        freeze.get("schema") != "yolo26n-v26-detector-freeze-v1"
        or freeze.get("status") != "V26_DETECTOR_FROZEN_DEVELOPMENT_ONLY"
        or freeze.get("candidate") not in TRAINED_CANDIDATES
        or freeze.get("threshold") not in THRESHOLDS
        or freeze.get("nms_iou") not in NMS_IOUS
        or freeze.get("selection_gates") != SELECTION_GATES
        or freeze.get("baseline_remeasured_same_protocol") is not True
        or freeze.get("temporal_contract") != TEMPORAL_CONTRACT
        or freeze.get("clip_level_acceptance_pending") is not True
        or freeze.get("future_holdout_required") is not True
        or freeze.get("production_adoption") is not False
        or freeze.get("inference") != INFERENCE_CONTRACT
        or freeze.get("runner_sha256") != _sha(Path(__file__))
    ):
        raise ValueError("v2.6 detector freeze contract invalid")
    for field in ("candidate_checkpoint_sha256", "validation_ledger_sha256"):
        value = freeze.get(field)
        if (
            not isinstance(value, Mapping)
            or set(value) != set(VALIDATION_CANDIDATES)
            or not all(_is_sha(item) for item in value.values())
        ):
            raise ValueError("v2.6 detector freeze lineage invalid")
    if freeze.get("checkpoint_sha256") != freeze["candidate_checkpoint_sha256"][freeze["candidate"]]:
        raise ValueError("v2.6 selected checkpoint lineage invalid")
    for field, length in (
        ("dataset_manifest_sha256", 64),
        ("recent_split_manifest_sha256", 64),
        ("source_commit", 40),
        ("runner_sha256", 64),
        ("validation_ground_truth_sha256", 64),
    ):
        if not _is_sha(freeze.get(field), length):
            raise ValueError("v2.6 detector freeze provenance invalid")
    metrics = freeze.get("candidate_metrics")
    if not isinstance(metrics, Mapping) or set(metrics) != set(VALIDATION_CANDIDATES):
        raise ValueError("v2.6 detector freeze metrics invalid")
    selection = select_v26_candidate({candidate: metrics[candidate] for candidate in TRAINED_CANDIDATES})
    for field in (
        "candidate",
        "threshold",
        "nms_iou",
        "validation_precision",
        "validation_recall",
        "validation_specificity",
        "validation_camera_night_recall_min",
    ):
        if freeze.get(field) != selection[field]:
            raise ValueError("v2.6 detector freeze selection inconsistent")


def build_prediction_ledger(
    *,
    samples: Sequence[V26Sample],
    split: str,
    candidate: str,
    checkpoint_path: Path,
    manifest_path: Path,
    recent_split_path: Path,
    source_commit: str,
    predictor: Callable[..., Sequence[Mapping[str, object]]],
    freeze: Mapping[str, object] | None = None,
    freeze_sha256: str | None = None,
) -> dict[str, object]:
    if candidate not in VALIDATION_CANDIDATES or split not in {"val", "regression-test"} or not samples:
        raise ValueError("v2.6 prediction identity invalid")
    if not _is_sha(source_commit, 40):
        raise ValueError("v2.6 source commit invalid")
    runner_sha = _sha(Path(__file__))
    manifest_sha = _sha(manifest_path)
    recent_split_sha = _sha(recent_split_path)
    checkpoint_sha = _sha(checkpoint_path)
    sample_hashes = tuple((_sha(sample.image_path), _sha(sample.label_path)) for sample in samples)
    if any(
        pair != (sample.image_sha256, sample.label_sha256)
        for sample, pair in zip(samples, sample_hashes, strict=True)
    ):
        raise ValueError("v2.6 evaluation sample hash mismatch")
    if split == "regression-test":
        if freeze is None or not _is_sha(freeze_sha256):
            raise ValueError("v2.6 regression prediction requires freeze")
        _validate_detector_freeze(freeze)
        if candidate not in {"baseline-v25", str(freeze["candidate"])}:
            raise ValueError("v2.6 regression candidate is not frozen")
        if checkpoint_sha != freeze["candidate_checkpoint_sha256"][candidate]:
            raise ValueError("v2.6 regression checkpoint is not frozen")
        for key, value in {
            "dataset_manifest_sha256": manifest_sha,
            "recent_split_manifest_sha256": recent_split_sha,
            "source_commit": source_commit,
            "runner_sha256": runner_sha,
            "inference": INFERENCE_CONTRACT,
        }.items():
            if freeze.get(key) != value:
                raise ValueError("v2.6 regression protocol differs from freeze")
    elif freeze is not None or freeze_sha256 is not None:
        raise ValueError("v2.6 validation must not consume freeze")

    raw_results = tuple(
        predictor(
            [sample.image_path for sample in samples],
            confidence=INFERENCE_CONTRACT["confidence"],
            imgsz=INFERENCE_CONTRACT["imgsz"],
            nms_iou=INFERENCE_CONTRACT["nms_iou"],
            max_det=INFERENCE_CONTRACT["max_det"],
            device=INFERENCE_CONTRACT["device"],
        )
    )
    if len(raw_results) != len(samples):
        raise ValueError("v2.6 prediction result count mismatch")
    if (
        _sha(Path(__file__)) != runner_sha
        or _sha(manifest_path) != manifest_sha
        or _sha(recent_split_path) != recent_split_sha
        or _sha(checkpoint_path) != checkpoint_sha
        or tuple((_sha(sample.image_path), _sha(sample.label_path)) for sample in samples) != sample_hashes
    ):
        raise ValueError("v2.6 evaluation input changed during inference")

    records: list[dict[str, object]] = []
    gt_count = prediction_count = 0
    for sample, raw in zip(samples, raw_results, strict=True):
        width = raw.get("width")
        height = raw.get("height")
        predictions = raw.get("predictions")
        if type(width) is not int or type(height) is not int or width <= 0 or height <= 0 or not isinstance(predictions, list):
            raise ValueError("v2.6 prediction row malformed")
        gt_boxes = [
            [x1 * width, y1 * height, x2 * width, y2 * height]
            for x1, y1, x2, y2 in sample.normalized_gt_boxes
        ]
        normalized_predictions: list[dict[str, object]] = []
        for prediction in predictions:
            if not isinstance(prediction, Mapping) or not isinstance(prediction.get("xyxy"), Sequence):
                raise ValueError("v2.6 prediction malformed")
            confidence = _number(prediction.get("confidence"), "confidence")
            xyxy = prediction["xyxy"]
            if not 0 <= confidence <= 1 or len(xyxy) != 4:
                raise ValueError("v2.6 prediction malformed")
            box = [_number(value, "coordinate") for value in xyxy]
            if box[0] >= box[2] or box[1] >= box[3]:
                raise ValueError("v2.6 prediction geometry invalid")
            normalized_predictions.append({"confidence": confidence, "xyxy": box})
        normalized_predictions.sort(key=lambda row: (-float(row["confidence"]), row["xyxy"]))
        records.append(
            {
                "sequence": sample.sequence,
                "image_sha256": sample.image_sha256,
                "camera_night": sample.camera_night,
                "episode_id": sample.episode_id,
                "clip_ref": sample.clip_ref,
                "width": width,
                "height": height,
                "gt_boxes": gt_boxes,
                "predictions": normalized_predictions,
            }
        )
        gt_count += len(gt_boxes)
        prediction_count += len(normalized_predictions)
    ledger: dict[str, object] = {
        "schema": "yolo26n-v26-prediction-ledger-v1",
        "status": "V26_PREDICTIONS_READY",
        "evaluation_tier": "development",
        "split": split,
        "candidate": candidate,
        "source_commit": source_commit,
        "runner_sha256": runner_sha,
        "dataset_manifest_sha256": manifest_sha,
        "recent_split_manifest_sha256": recent_split_sha,
        "checkpoint_sha256": checkpoint_sha,
        "inference": dict(INFERENCE_CONTRACT),
        "image_count": len(records),
        "gt_box_count": gt_count,
        "prediction_count": prediction_count,
        "records": records,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "deploy_count": 0,
    }
    if split == "regression-test":
        ledger["threshold_freeze_sha256"] = freeze_sha256
    return ledger


def run_prediction_once(
    *,
    dataset_root: Path,
    manifest_path: Path,
    recent_split_path: Path,
    split: str,
    candidate: str,
    checkpoint_path: Path,
    source_commit: str,
    evaluation_root: Path,
    predictor: Callable[..., Sequence[Mapping[str, object]]] | None = None,
    sample_loader: Callable[..., Sequence[V26Sample]] = load_v26_samples,
    freeze: Mapping[str, object] | None = None,
    freeze_sha256: str | None = None,
    source_verifier: Callable[..., None] = verify_evaluator_source_commit,
) -> dict[str, object]:
    output = _prediction_path(evaluation_root, candidate, split)
    if output.exists():
        raise FileExistsError(output)
    source_verifier(source_commit=source_commit)
    samples = tuple(
        sample_loader(
            dataset_root=dataset_root,
            manifest_path=manifest_path,
            recent_split_path=recent_split_path,
            split=split,
        )
    )
    _claim(evaluation_root, f"predict-{candidate}-{split}")
    actual_predictor = predictor or make_ultralytics_predictor(checkpoint_path=checkpoint_path)
    ledger = build_prediction_ledger(
        samples=samples,
        split=split,
        candidate=candidate,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        recent_split_path=recent_split_path,
        source_commit=source_commit,
        predictor=actual_predictor,
        freeze=freeze,
        freeze_sha256=freeze_sha256,
    )
    _write_private_new(output, ledger)
    return ledger


def build_regression_report(
    *,
    test_ledgers: Mapping[str, Mapping[str, object]],
    test_ledger_sha256: Mapping[str, str],
    freeze: Mapping[str, object],
    freeze_sha256: str,
) -> dict[str, object]:
    _validate_detector_freeze(freeze)
    selected = str(freeze["candidate"])
    expected = {"baseline-v25", selected}
    if (
        set(test_ledgers) != expected
        or set(test_ledger_sha256) != expected
        or not _is_sha(freeze_sha256)
        or not all(_is_sha(value) for value in test_ledger_sha256.values())
    ):
        raise ValueError("v2.6 old regression requires baseline and selected ledgers")
    gt_digest: str | None = None
    metrics: dict[str, dict[str, object]] = {}
    threshold = float(freeze["threshold"])
    nms_iou = float(freeze["nms_iou"])
    for candidate in sorted(expected):
        ledger = test_ledgers[candidate]
        _records(ledger)
        if (
            ledger.get("split") != "regression-test"
            or ledger.get("candidate") != candidate
            or ledger.get("threshold_freeze_sha256") != freeze_sha256
            or ledger.get("checkpoint_sha256") != freeze["candidate_checkpoint_sha256"][candidate]
        ):
            raise ValueError("v2.6 old regression ledger lineage mismatch")
        for field in (
            "dataset_manifest_sha256",
            "recent_split_manifest_sha256",
            "source_commit",
            "runner_sha256",
            "inference",
        ):
            if ledger.get(field) != freeze.get(field):
                raise ValueError("v2.6 old regression protocol mismatch")
        digest = _gt_digest(ledger)
        if gt_digest is None:
            gt_digest = digest
        elif gt_digest != digest:
            raise ValueError("v2.6 old regression GT differs between models")
        metrics[candidate] = _score_row(_records(ledger), threshold=threshold, nms_iou=nms_iou)
    baseline = metrics["baseline-v25"]
    candidate_metric = metrics[selected]
    regression_pass = (
        float(candidate_metric["precision"]) >= float(baseline["precision"]) - 0.02
        and float(candidate_metric["recall"]) >= float(baseline["recall"]) - 0.02
    )
    return {
        "schema": "yolo26n-v26-old-regression-report-v1",
        "status": "V26_OLD_REGRESSION_COMPLETED_DEVELOPMENT_ONLY",
        "evaluation_tier": "development",
        "candidate": selected,
        "threshold": threshold,
        "nms_iou": nms_iou,
        "metrics": metrics,
        "regression_tolerance": {"precision_delta_min": -0.02, "recall_delta_min": -0.02},
        "regression_pass": regression_pass,
        "test_ledger_sha256": dict(test_ledger_sha256),
        "threshold_freeze_sha256": freeze_sha256,
        "regression_only_old_distribution": True,
        "clip_level_acceptance_pending": True,
        "future_holdout_required": True,
        "production_adoption": False,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "deploy_count": 0,
    }


def _read_with_sha(path: Path) -> tuple[dict[str, object], str]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("v2.6 artifact root must be object")
    return value, hashlib.sha256(raw).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    preflight = commands.add_parser("preflight")
    preflight.add_argument("--attempt-root", type=Path, required=True)
    preflight.add_argument("--training-source-commit", required=True)

    predict = commands.add_parser("predict")
    predict.add_argument("--dataset-root", type=Path, required=True)
    predict.add_argument("--manifest", type=Path, required=True)
    predict.add_argument("--recent-split", type=Path, required=True)
    predict.add_argument("--split", choices=("val", "regression-test"), required=True)
    predict.add_argument("--candidate", choices=VALIDATION_CANDIDATES, required=True)
    predict.add_argument("--checkpoint", type=Path, required=True)
    predict.add_argument("--source-commit", required=True)
    predict.add_argument("--attempt-root", type=Path, required=True)
    predict.add_argument("--training-source-commit", required=True)
    predict.add_argument("--evaluation-root", type=Path, required=True)
    predict.add_argument("--freeze", type=Path)

    freeze = commands.add_parser("freeze")
    freeze.add_argument("--evaluation-root", type=Path, required=True)

    fixed = commands.add_parser("fixed-test")
    fixed.add_argument("--evaluation-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "preflight":
        checkpoints = verify_v26_training_artifacts(
            attempt_root=args.attempt_root,
            training_source_commit=args.training_source_commit,
        )
        print(json.dumps({"status": "V26_TRAINING_PREFLIGHT_OK", "candidate_count": len(checkpoints)}))
        return 0
    if args.command == "predict":
        expected_dataset_root = args.attempt_root / "dataset-v26-v1"
        expected_manifest = expected_dataset_root / "manifest.private.json"
        if (
            args.dataset_root.resolve() != expected_dataset_root.resolve()
            or args.manifest.resolve() != expected_manifest.resolve()
        ):
            raise ValueError("v2.6 prediction dataset is not the verified training dataset")
        verified = verify_v26_training_artifacts(
            attempt_root=args.attempt_root,
            training_source_commit=args.training_source_commit,
        )
        verify_prediction_checkpoint_binding(
            candidate=args.candidate,
            checkpoint_path=args.checkpoint,
            verified=verified,
        )
        freeze = freeze_sha = None
        if args.split == "regression-test":
            exact = args.evaluation_root / "detector-freeze.private.json"
            if args.freeze is None or args.freeze.resolve() != exact.resolve():
                raise ValueError("v2.6 regression prediction requires exact freeze path")
            freeze, freeze_sha = _read_with_sha(exact)
        elif args.freeze is not None:
            raise ValueError("v2.6 validation prediction must not use freeze")
        ledger = run_prediction_once(
            dataset_root=args.dataset_root,
            manifest_path=args.manifest,
            recent_split_path=args.recent_split,
            split=args.split,
            candidate=args.candidate,
            checkpoint_path=args.checkpoint,
            source_commit=args.source_commit,
            evaluation_root=args.evaluation_root,
            freeze=freeze,
            freeze_sha256=freeze_sha,
        )
        print(
            json.dumps(
                {
                    "status": ledger["status"],
                    "candidate": ledger["candidate"],
                    "split": ledger["split"],
                    "image_count": ledger["image_count"],
                }
            )
        )
        return 0
    if args.command == "freeze":
        output = args.evaluation_root / "detector-freeze.private.json"
        if output.exists():
            raise FileExistsError(output)
        ledgers: dict[str, dict[str, object]] = {}
        hashes: dict[str, str] = {}
        for candidate in VALIDATION_CANDIDATES:
            ledgers[candidate], hashes[candidate] = _read_with_sha(
                _prediction_path(args.evaluation_root, candidate, "val")
            )
        verify_evaluator_source_commit(source_commit=str(ledgers["baseline-v25"].get("source_commit")))
        _claim(args.evaluation_root, "freeze-validation")
        freeze = build_detector_freeze(ledgers, ledger_sha256=hashes)
        _write_private_new(output, freeze)
        print(
            json.dumps(
                {
                    "status": freeze["status"],
                    "candidate": freeze["candidate"],
                    "threshold": freeze["threshold"],
                    "nms_iou": freeze["nms_iou"],
                }
            )
        )
        return 0

    freeze_path = args.evaluation_root / "detector-freeze.private.json"
    freeze, freeze_sha = _read_with_sha(freeze_path)
    _validate_detector_freeze(freeze)
    verify_evaluator_source_commit(source_commit=str(freeze.get("source_commit")))
    output = args.evaluation_root / "old-regression-report.private.json"
    if output.exists():
        raise FileExistsError(output)
    expected = {"baseline-v25", str(freeze["candidate"])}
    ledgers: dict[str, dict[str, object]] = {}
    hashes: dict[str, str] = {}
    for candidate in expected:
        ledgers[candidate], hashes[candidate] = _read_with_sha(
            _prediction_path(args.evaluation_root, candidate, "regression-test")
        )
    _claim(args.evaluation_root, "score-old-regression")
    report = build_regression_report(
        test_ledgers=ledgers,
        test_ledger_sha256=hashes,
        freeze=freeze,
        freeze_sha256=freeze_sha,
    )
    _write_private_new(output, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "candidate": report["candidate"],
                "regression_pass": report["regression_pass"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

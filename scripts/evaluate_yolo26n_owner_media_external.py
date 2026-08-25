"""Run a frozen YOLO development model on the Owner external diagnostic partition."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from io import BytesIO
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from PIL import Image

try:
    from scripts.evaluate_yolo26n_v22 import _validate_threshold_freeze
except ModuleNotFoundError:  # Direct ``python scripts/...py`` execution.
    from evaluate_yolo26n_v22 import _validate_threshold_freeze  # type: ignore[no-redef]

@dataclass(frozen=True)
class ExternalSample:
    sequence: str
    image_path: Path
    image_sha256: str
    width: int
    height: int
    gt_boxes: tuple[tuple[float, float, float, float], ...]
    image_bytes: bytes


@dataclass(frozen=True)
class FrozenExternalSelection:
    version: str
    threshold: float
    checkpoint_sha256: str


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def load_external_diagnostic_samples(
    *, snapshot: Mapping[str, object], review_frames_dir: Path
) -> tuple[ExternalSample, ...]:
    if snapshot.get("schema") != "yolo26n-owner-media-cvat-snapshot-v1":
        raise ValueError("snapshot schema mismatch")
    labels = snapshot.get("labels")
    if (
        not isinstance(labels, list)
        or len(labels) != 1
        or not isinstance(labels[0], Mapping)
        or set(labels[0]) != {"id", "name"}
        or type(labels[0].get("id")) is not int
        or labels[0]["id"] != 1
        or labels[0].get("name") != "gecko"
    ):
        raise ValueError("snapshot label contract mismatch")
    provenance = snapshot.get("provenance")
    if not isinstance(provenance, Mapping) or provenance.get("cvat_job_id") != 163:
        raise ValueError("snapshot provenance mismatch")
    rows = snapshot.get("images")
    if not isinstance(rows, list) or len(rows) != 240:
        raise ValueError("snapshot must contain exact 240 images")
    if any(
        not isinstance(row, Mapping)
        or row.get("partition") not in {"external_diagnostic", "training_candidate"}
        for row in rows
    ):
        raise ValueError("snapshot partition contract mismatch")
    selected_sequences = {
        f"O{index + 1:04d}"
        for index, row in enumerate(rows)
        if row.get("partition") == "external_diagnostic"
    }
    if len(selected_sequences) != 60 or sum(row.get("partition") == "training_candidate" for row in rows) != 180:
        raise ValueError("external diagnostic partition must contain exact 60 images")
    samples: list[ExternalSample] = []
    for index, row in enumerate(rows):
        expected = f"O{index + 1:04d}"
        if type(row.get("frame")) is not int or row["frame"] != index or row.get("path") != f"images/{expected}.jpg":
            raise ValueError("external diagnostic sequence mismatch")
        image_sha = row.get("image_sha256")
        if not _is_sha(image_sha):
            raise ValueError("external diagnostic image SHA malformed")
        width, height = row.get("width"), row.get("height")
        if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
            raise ValueError("external diagnostic dimensions malformed")
        raw_boxes = row.get("boxes")
        if not isinstance(raw_boxes, list):
            raise ValueError("external diagnostic boxes malformed")
        boxes = []
        for box in raw_boxes:
            if (
                not isinstance(box, Mapping)
                or set(box) != {"id", "label_id", "points", "rotation", "type"}
                or type(box.get("id")) is not int
                or box["id"] < 0
                or type(box.get("label_id")) is not int
                or box["label_id"] != 1
                or box.get("type") != "rectangle"
                or type(box.get("rotation")) not in (int, float)
                or float(box["rotation"]) != 0.0
            ):
                raise ValueError("external diagnostic box malformed")
            points = box.get("points")
            if not isinstance(points, list) or len(points) != 4 or any(type(v) not in (int, float) or not math.isfinite(float(v)) for v in points):
                raise ValueError("external diagnostic box malformed")
            x1, y1, x2, y2 = map(float, points)
            if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                raise ValueError("external diagnostic box malformed")
            boxes.append((x1, y1, x2, y2))
        if expected in selected_sequences:
            image_path = review_frames_dir / f"{expected}.jpg"
            image_bytes = image_path.read_bytes() if image_path.is_file() else b""
            if _sha_bytes(image_bytes) != image_sha:
                raise ValueError("external diagnostic image SHA mismatch")
            samples.append(ExternalSample(expected, image_path, image_sha, width, height, tuple(boxes), image_bytes))
    return tuple(samples)


def validate_frozen_inputs(
    *, freeze: Mapping[str, object], freeze_bytes: bytes,
    expected_freeze_sha256: str, checkpoint_path: Path,
    snapshot: Mapping[str, object], snapshot_bytes: bytes,
    expected_snapshot_sha256: str, summary: Mapping[str, object],
    summary_bytes: bytes, expected_summary_sha256: str,
) -> FrozenExternalSelection:
    if _sha_bytes(freeze_bytes) != expected_freeze_sha256:
        raise ValueError("freeze SHA mismatch")
    if _sha_bytes(snapshot_bytes) != expected_snapshot_sha256:
        raise ValueError("snapshot SHA mismatch")
    if _sha_bytes(summary_bytes) != expected_summary_sha256:
        raise ValueError("summary SHA mismatch")
    expected_inference = {
        "confidence": 0.001, "imgsz": 960, "nms_iou": 0.70,
        "max_det": 50, "device": "mps",
    }
    checkpoint_sha = _sha_file(checkpoint_path)
    candidate_map = freeze.get("candidate_checkpoint_sha256")
    version_contracts: dict[str, tuple[str, str, float | None, set[str]]] = {
        "v22": (
            "yolo26n-v22-candidate-threshold-freeze-v1",
            "V22_THRESHOLD_FROZEN_DEVELOPMENT_ONLY",
            0.20,
            {"warm-start", "clean-reference"},
        ),
        "v23": (
            "yolo26n-v23-candidate-threshold-freeze-v1",
            "V23_THRESHOLD_FROZEN_DEVELOPMENT_ONLY",
            0.25,
            {"warm-start", "clean-reference"},
        ),
        "v24": (
            "yolo26n-v24-candidate-threshold-freeze-v1",
            "V24_THRESHOLD_FROZEN_DEVELOPMENT_ONLY",
            None,
            {"warm-start"},
        ),
    }
    matching_versions = [
        version
        for version, (schema, status, threshold, _candidates) in version_contracts.items()
        if freeze.get("schema") == schema
        and freeze.get("status") == status
        and (threshold is None or freeze.get("threshold") == threshold)
    ]
    selected_version = matching_versions[0] if len(matching_versions) == 1 else None
    selected_contract = version_contracts.get(selected_version) if selected_version else None
    threshold = freeze.get("threshold")
    if (
        selected_contract is None
        or freeze.get("evaluation_tier") != "development"
        or freeze.get("future_holdout_required") is not True
        or freeze.get("candidate") != "warm-start"
        or freeze.get("precision_floor") != 0.60
        or type(threshold) not in (int, float)
        or isinstance(threshold, bool)
        or not math.isfinite(float(threshold))
        or float(threshold) not in {round(index * 0.05, 2) for index in range(1, 17)}
        or freeze.get("inference") != expected_inference
        or freeze.get("checkpoint_sha256") != checkpoint_sha
        or not isinstance(candidate_map, Mapping)
        or set(candidate_map) != selected_contract[3]
        or any(not _is_sha(value) for value in candidate_map.values())
        or candidate_map.get("warm-start") != checkpoint_sha
    ):
        raise ValueError("frozen model selection mismatch")
    if selected_version == "v24":
        _validate_threshold_freeze(freeze)
    if (
        summary.get("status") != "OWNER_MEDIA_HUMAN_REVIEW_ACCEPTED"
        or summary.get("image_count") != 240
        or summary.get("accepted_image_count") != 237
        or summary.get("ambiguous_image_count") != 3
        or not isinstance(summary.get("provenance"), Mapping)
        or summary["provenance"].get("cvat_job_id") != 163
        or summary["provenance"].get("raw_gecko_label_id") != 10
    ):
        raise ValueError("human review summary contract mismatch")
    # The frozen diagnostic partition contains no ambiguous images; the three
    # excluded images are all in the later training-candidate partition.
    partition_counts = summary.get("partition_counts")
    if (
        not isinstance(partition_counts, Mapping)
        or partition_counts.get("external_diagnostic", {}).get("accepted") != 60
        or partition_counts.get("external_diagnostic", {}).get("ambiguous") != 0
        or partition_counts.get("training_candidate", {}).get("accepted") != 177
        or partition_counts.get("training_candidate", {}).get("ambiguous") != 3
    ):
        raise ValueError("human review partition contract mismatch")
    version = matching_versions[0]
    return FrozenExternalSelection(
        version=version,
        threshold=float(threshold),
        checkpoint_sha256=checkpoint_sha,
    )


def validate_prediction_result(
    result: Mapping[str, object], *, expected_width: int, expected_height: int
) -> list[dict[str, object]]:
    if result.get("width") != expected_width or result.get("height") != expected_height:
        raise ValueError("prediction dimensions mismatch")
    raw_predictions = result.get("predictions")
    if not isinstance(raw_predictions, list):
        raise ValueError("predictions malformed")
    predictions: list[dict[str, object]] = []
    for raw in raw_predictions:
        if not isinstance(raw, Mapping) or set(raw) != {"confidence", "xyxy"}:
            raise ValueError("prediction malformed")
        confidence, box = raw.get("confidence"), raw.get("xyxy")
        if type(confidence) not in (int, float) or not math.isfinite(float(confidence)) or not 0 <= float(confidence) <= 1:
            raise ValueError("prediction confidence malformed")
        if not isinstance(box, list) or len(box) != 4 or any(type(v) not in (int, float) or not math.isfinite(float(v)) for v in box):
            raise ValueError("prediction box malformed")
        x1, y1, x2, y2 = map(float, box)
        if not (0 <= x1 < x2 <= expected_width and 0 <= y1 < y2 <= expected_height):
            raise ValueError("prediction box malformed")
        predictions.append({"confidence": float(confidence), "xyxy": [x1, y1, x2, y2]})
    return predictions


def make_external_predictor(*, checkpoint_path: Path, model_factory=None):
    if model_factory is None:
        from ultralytics import YOLO

        model_factory = YOLO

    model = model_factory(str(checkpoint_path))

    def predict(images: Sequence[Image.Image], **contract: object) -> list[dict[str, object]]:
        raw_results = model.predict(
            source=list(images),
            conf=contract["confidence"],
            imgsz=contract["imgsz"],
            iou=contract["nms_iou"],
            max_det=contract["max_det"],
            device=contract["device"],
            verbose=False,
            stream=False,
            save=False,
        )
        if len(raw_results) != len(images):
            raise ValueError("Ultralytics result count does not match input count")
        rows = []
        for index, result in enumerate(raw_results):
            if str(result.path) != f"image{index}.jpg":
                raise ValueError("Ultralytics result order does not match input order")
            height, width = result.orig_shape
            boxes = result.boxes
            xyxy = boxes.xyxy.cpu().tolist() if boxes is not None else []
            confidence = boxes.conf.cpu().tolist() if boxes is not None else []
            if len(xyxy) != len(confidence):
                raise ValueError("Ultralytics box and confidence counts differ")
            rows.append({
                "width": int(width), "height": int(height),
                "predictions": [
                    {"confidence": c, "xyxy": b}
                    for c, b in zip(confidence, xyxy, strict=True)
                ],
            })
        return rows

    return predict


def _iou(a: Sequence[float], b: Sequence[float]) -> float:
    iw = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iw * ih
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / union if union else 0.0


def build_external_diagnostic_report(
    *, ledger: Mapping[str, object], threshold: float, snapshot_sha256: str,
    ledger_sha256: str, expected_image_count: int = 60,
) -> dict[str, object]:
    if not _is_sha(snapshot_sha256) or not _is_sha(ledger_sha256):
        raise ValueError("provenance SHA malformed")
    records = ledger.get("records")
    if not isinstance(records, list) or len(records) != expected_image_count:
        raise ValueError("prediction record count mismatch")
    seen: set[str] = set()
    tp = fp = fn = duplicate = false_negative_images = false_positive_negative = 0
    positive_images = negative_images = detected_positive_images = 0
    for record in records:
        if not isinstance(record, Mapping) or not isinstance(record.get("sequence"), str) or record["sequence"] in seen:
            raise ValueError("prediction sequence mismatch")
        seen.add(record["sequence"])
        gt, preds = record.get("gt_boxes"), record.get("predictions")
        if not isinstance(gt, list) or not isinstance(preds, list):
            raise ValueError("prediction record malformed")
        validated_predictions = validate_prediction_result(
            {"width": 1_000_000_000, "height": 1_000_000_000, "predictions": preds},
            expected_width=1_000_000_000,
            expected_height=1_000_000_000,
        )
        filtered = [p for p in validated_predictions if float(p["confidence"]) >= threshold]
        filtered.sort(key=lambda p: -float(p["confidence"]))
        matched: set[int] = set()
        for pred in filtered:
            box = pred.get("xyxy")
            if not isinstance(box, list) or len(box) != 4:
                raise ValueError("prediction box malformed")
            overlaps = [(_iou(box, g), i) for i, g in enumerate(gt)]
            eligible = [(v, i) for v, i in overlaps if i not in matched]
            best, idx = max(eligible, default=(0.0, -1))
            if best >= 0.5:
                matched.add(idx); tp += 1
            else:
                if overlaps and max(v for v, _ in overlaps) >= 0.5:
                    duplicate += 1
                fp += 1
        fn += len(gt) - len(matched)
        if gt:
            positive_images += 1
            if matched: detected_positive_images += 1
            else: false_negative_images += 1
        else:
            negative_images += 1
            if filtered: false_positive_negative += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "schema": "yolo26n-owner-media-external-diagnostic-report-v1",
        "status": "OWNER_MEDIA_EXTERNAL_DIAGNOSTIC_COMPLETE",
        "threshold": threshold,
        "iou_threshold": 0.50,
        "image_count": expected_image_count,
        "positive_image_count": positive_images,
        "negative_image_count": negative_images,
        "tp": tp, "fp": fp, "fn": fn,
        "box_recall": recall,
        "precision_reference": precision,
        "precision_status": "MEASURED" if negative_images >= 30 else "UNDERPOWERED_NEGATIVE",
        "positive_image_recall": detected_positive_images / positive_images if positive_images else 0.0,
        "false_negative_image_count": false_negative_images,
        "false_positive_on_negative_count": false_positive_negative,
        "duplicate_prediction_count": duplicate,
        "provenance": {"snapshot_sha256": snapshot_sha256, "prediction_ledger_sha256": ledger_sha256},
        "db_write_count": 0, "r2_write_count": 0, "service_write_count": 0,
    }


def _write_private_new(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _claim_started(path: Path, *, input_sha256: Mapping[str, str]) -> None:
    _write_private_new(
        path,
        {
            "schema": "yolo26n-owner-media-external-diagnostic-lock-v1",
            "status": "STARTED",
            "input_sha256": dict(input_sha256),
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--review-frames-dir", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--expected-freeze-sha256", required=True)
    parser.add_argument("--expected-snapshot-sha256", required=True)
    parser.add_argument("--expected-summary-sha256", required=True)
    parser.add_argument("--ledger-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.ledger_output.exists() or args.report_output.exists():
        raise FileExistsError("diagnostic output already exists")
    if args.ledger_output.parent.resolve() != args.report_output.parent.resolve():
        raise ValueError("diagnostic outputs must share one directory")
    started_lock = args.ledger_output.parent / ".owner-media-external-diagnostic.started.private.json"
    snapshot_bytes, freeze_bytes, summary_bytes = (
        args.snapshot.read_bytes(), args.freeze.read_bytes(), args.summary.read_bytes()
    )
    snapshot, freeze, summary = (
        json.loads(snapshot_bytes), json.loads(freeze_bytes), json.loads(summary_bytes)
    )
    selection = validate_frozen_inputs(
        freeze=freeze, freeze_bytes=freeze_bytes,
        expected_freeze_sha256=args.expected_freeze_sha256,
        checkpoint_path=args.checkpoint, snapshot=snapshot,
        snapshot_bytes=snapshot_bytes,
        expected_snapshot_sha256=args.expected_snapshot_sha256,
        summary=summary, summary_bytes=summary_bytes,
        expected_summary_sha256=args.expected_summary_sha256,
    )
    samples = load_external_diagnostic_samples(snapshot=snapshot, review_frames_dir=args.review_frames_dir)
    checkpoint_bytes = args.checkpoint.read_bytes()
    checkpoint_sha_before = _sha_bytes(checkpoint_bytes)
    if checkpoint_sha_before != selection.checkpoint_sha256:
        raise ValueError("checkpoint changed before inference")
    _claim_started(
        started_lock,
        input_sha256={
            "freeze": args.expected_freeze_sha256,
            "snapshot": args.expected_snapshot_sha256,
            "summary": args.expected_summary_sha256,
            "checkpoint": checkpoint_sha_before,
        },
    )
    with tempfile.TemporaryDirectory(prefix=f"owner-media-{selection.version}-") as temp_dir:
        pinned_checkpoint = Path(temp_dir) / "verified-best.pt"
        fd = os.open(pinned_checkpoint, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(checkpoint_bytes)
        predictor = make_external_predictor(checkpoint_path=pinned_checkpoint)
        # Feed the exact verified JPEG bytes through decoded PIL objects so a
        # path-level ABA swap cannot change what the model consumes.
        image_inputs = []
        for sample in samples:
            image = Image.open(BytesIO(sample.image_bytes))
            image.load()
            image_inputs.append(image)
        raw = predictor(image_inputs, confidence=0.001, imgsz=960, nms_iou=0.70, max_det=50, device="mps")
    records = []
    for sample, result in zip(samples, raw, strict=True):
        predictions = validate_prediction_result(
            result, expected_width=sample.width, expected_height=sample.height
        )
        records.append({"sequence": sample.sequence, "image_sha256": sample.image_sha256, "gt_boxes": [list(b) for b in sample.gt_boxes], "predictions": predictions})
    if (
        args.snapshot.read_bytes() != snapshot_bytes
        or args.freeze.read_bytes() != freeze_bytes
        or args.summary.read_bytes() != summary_bytes
        or _sha_file(args.checkpoint) != checkpoint_sha_before
    ):
        raise ValueError("diagnostic input changed during inference")
    ledger = {
        "schema": "yolo26n-owner-media-external-predictions-v1",
        "status": "PREDICTIONS_COMPLETE", "candidate": "warm-start",
        "model_version": selection.version,
        "threshold": selection.threshold,
        "inference": freeze["inference"],
        "provenance": {
            "freeze_sha256": args.expected_freeze_sha256,
            "snapshot_sha256": args.expected_snapshot_sha256,
            "summary_sha256": args.expected_summary_sha256,
            "checkpoint_sha256": checkpoint_sha_before,
        },
        "records": records, "db_write_count": 0, "r2_write_count": 0,
        "service_write_count": 0,
    }
    ledger_bytes = json.dumps(ledger, sort_keys=True, separators=(",", ":")).encode()
    ledger_sha = _sha_bytes(ledger_bytes)
    report = build_external_diagnostic_report(
        ledger=ledger,
        threshold=selection.threshold,
        snapshot_sha256=_sha_bytes(snapshot_bytes),
        ledger_sha256=ledger_sha,
    )
    _write_private_new(args.ledger_output, ledger)
    try:
        _write_private_new(args.report_output, report)
    except BaseException:
        args.ledger_output.unlink(missing_ok=True)
        raise
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Adversarial tests for the immutable v2.4b future-holdout evaluator."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Mapping, Sequence

import pytest
from PIL import Image

import scripts.evaluate_yolo26n_v24b_future_holdout as evaluator
from scripts import run_yolo26n_v24b_postprocess as validation_runner
from scripts import select_yolo26n_v24b_postprocess as selector


APPROVED_CHECKPOINT_SHA256 = (
    "3c9f752b9369b30be4083f837676271640cfd1f4cbfa6027382a380efc4212c4"
)
ZERO_SHA = "0" * 64


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes())


def _private_bytes(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(0o600)
    return path


def _private_json(path: Path, value: Mapping[str, object]) -> Path:
    return _private_bytes(
        path,
        (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )


def _jpeg(index: int, *, width: int = 16, height: int = 16) -> bytes:
    buffer = BytesIO()
    Image.new(
        "RGB",
        (width, height),
        color=((index * 17) % 256, (index * 29) % 256, (index * 43) % 256),
    ).save(buffer, format="JPEG", quality=91)
    return buffer.getvalue()


def _freeze(*, checkpoint_sha256: str) -> dict[str, object]:
    runner_sha = _file_sha(Path(validation_runner.__file__))
    selector_sha = _file_sha(Path(selector.__file__))
    metrics: list[dict[str, object]] = []
    for nms_iou in selector.NMS_GRID:
        for confidence in selector.THRESHOLD_GRID:
            selected = nms_iou == 0.50 and confidence == 0.25
            baseline = nms_iou == 0.70 and confidence == 0.20
            metrics.append(
                {
                    "nms_iou": nms_iou,
                    "confidence": confidence,
                    "tp": 70 if selected else 50,
                    "fp": 20 if selected else 50,
                    "fn": 30 if selected else 50,
                    "duplicate": 2 if selected else (5 if baseline else 6),
                    "precision": 70 / 90 if selected else 0.5,
                    "recall": 0.7 if selected else 0.5,
                    "positive_image_recall": 0.7 if selected else 0.5,
                }
            )
    input_sha = {
        "checkpoint": checkpoint_sha256,
        "dataset_manifest": "1" * 64,
        "runner": runner_sha,
        "selector": selector_sha,
        "frames": [
            {
                "sequence": f"V{index:04d}",
                "image_sha256": hashlib.sha256(f"val-image-{index}".encode()).hexdigest(),
                "label_sha256": hashlib.sha256(f"val-label-{index}".encode()).hexdigest(),
            }
            for index in range(1, 154)
        ],
    }
    return {
        "schema": "yolo26n-v24b-postprocess-freeze-v1",
        "status": "V24B_POSTPROCESS_FROZEN_DEVELOPMENT_ONLY",
        "evaluation_tier": "development",
        "future_holdout_required": True,
        "match_iou": 0.50,
        "threshold_grid": list(selector.THRESHOLD_GRID),
        "nms_grid": list(selector.NMS_GRID),
        "baseline": {"confidence": 0.20, "nms_iou": 0.70, "duplicate": 5},
        "validation_ledger_sha256": {
            str(nms_iou): hashlib.sha256(f"ledger-{nms_iou}".encode()).hexdigest()
            for nms_iou in selector.NMS_GRID
        },
        "validation_ground_truth_sha256": "2" * 64,
        "metrics": metrics,
        "checkpoint_sha256": checkpoint_sha256,
        "dataset_manifest_sha256": "1" * 64,
        "source_commit": "3" * 40,
        "runner_sha256": runner_sha,
        "selector_sha256": selector_sha,
        "selected": {"confidence": 0.25, "nms_iou": 0.50, "duplicate": 2},
        "input_sha256": input_sha,
        "frozen_at": "2026-08-13T12:34:56Z",
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "git_write_count": 0,
    }


class _Tensor:
    def __init__(self, value: object) -> None:
        self._value = value

    def cpu(self) -> _Tensor:
        return self

    def tolist(self) -> object:
        return self._value


class _Boxes:
    def __init__(self, predictions: Sequence[tuple[object, object]]) -> None:
        self.conf = _Tensor([confidence for confidence, _ in predictions])
        self.xyxy = _Tensor([box for _, box in predictions])


PredictionBuilder = Callable[[int], list[tuple[object, object]]]


class _Model:
    def __init__(
        self,
        prediction_builder: PredictionBuilder,
        *,
        before_results: Callable[[], None] | None = None,
        entered: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> None:
        self.prediction_builder = prediction_builder
        self.before_results = before_results
        self.entered = entered
        self.release = release
        self.predict_calls = 0
        self.sources: list[Image.Image] = []
        self.kwargs: dict[str, object] = {}

    def predict(self, *, source: Sequence[Image.Image], **kwargs: object) -> list[object]:
        self.predict_calls += 1
        self.sources = list(source)
        self.kwargs = kwargs
        if self.before_results is not None:
            self.before_results()
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            assert self.release.wait(timeout=10)
        return [
            SimpleNamespace(
                path=f"image{index}.jpg",
                orig_shape=(image.height, image.width),
                boxes=_Boxes(self.prediction_builder(index)),
            )
            for index, image in enumerate(source)
        ]


def _passing_predictions(index: int) -> list[tuple[object, object]]:
    if index < 45:
        predictions: list[tuple[object, object]] = [(0.90, [1.0, 1.0, 5.0, 5.0])]
        if index < 2:
            predictions.append((0.80, [1.0, 1.0, 5.0, 5.0]))
        return predictions
    if 60 <= index < 64:
        return [(0.70, [8.0, 8.0, 12.0, 12.0])]
    return []


def _rejected_predictions(index: int) -> list[tuple[object, object]]:
    if index < 30:
        return [(0.90, [1.0, 1.0, 5.0, 5.0])]
    if 60 <= index < 67:
        return [(0.70, [8.0, 8.0, 12.0, 12.0])]
    return []


@dataclass
class _Case:
    root: Path
    freeze: Path
    manifest: Path
    gt: Path
    checkpoint: Path
    images: Path
    output: Path
    kwargs: dict[str, object]
    manifest_value: dict[str, object]
    gt_value: dict[str, object]
    checkpoint_payload: bytes
    models: list[_Model]


def _case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    prediction_builder: PredictionBuilder = _passing_predictions,
    model: _Model | None = None,
) -> _Case:
    root = tmp_path / "private-case"
    root.mkdir(mode=0o700, parents=True)
    checkpoint_payload = b"synthetic-v24-checkpoint"
    checkpoint_sha = _sha(checkpoint_payload)
    monkeypatch.setattr(evaluator, "APPROVED_CHECKPOINT_SHA256", checkpoint_sha)
    freeze = _private_json(root / "v24b-postprocess-freeze.private.json", _freeze(checkpoint_sha256=checkpoint_sha))
    checkpoint = _private_bytes(root / "best.private.pt", checkpoint_payload)
    images = root / "images"
    images.mkdir(mode=0o700)
    records: list[dict[str, object]] = []
    gt_records: list[dict[str, object]] = []
    for index in range(120):
        sequence = f"H{index + 1:04d}"
        payload = _jpeg(index)
        image_sha = _sha(payload)
        _private_bytes(images / f"{sequence}.jpg", payload)
        presence = "positive" if index < 60 else "negative"
        record = {
            "sequence": sequence,
            "filename": f"{sequence}.jpg",
            "presence": presence,
            "image_sha256": image_sha,
            "width": 16,
            "height": 16,
        }
        records.append(record)
        gt_records.append(
            {
                **record,
                "boxes": ([{"label_id": 1, "points": [1.0, 1.0, 5.0, 5.0]}] if index < 60 else []),
            }
        )
    review_index_sha = "4" * 64
    manifest_value: dict[str, object] = {
        "schema": "yolo26n-v24b-future-holdout-v1",
        "status": "V24B_FUTURE_HOLDOUT_READY",
        "postprocess_freeze_sha256": _file_sha(freeze),
        "pool_ledger_sha256_pre": "5" * 64,
        "pool_ledger_sha256_post": "5" * 64,
        "presence_screen_sha256_pre": "6" * 64,
        "presence_screen_sha256_post": "6" * 64,
        "review_index_sha256": review_index_sha,
        "image_count": 120,
        "positive_count": 60,
        "negative_count": 60,
        "ambiguous_count": 0,
        "prediction_prefill_count": 0,
        "records": records,
        "db_write_count": 0,
        "r2_get_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "git_write_count": 0,
    }
    manifest = _private_json(root / "future-holdout-manifest.private.json", manifest_value)
    manifest_sha = _file_sha(manifest)
    gt_value: dict[str, object] = {
        "schema": "yolo26n-v24b-future-holdout-gt-v1",
        "status": "V24B_FUTURE_HOLDOUT_ACCEPTED",
        "image_count": 120,
        "positive_image_count": 60,
        "negative_image_count": 60,
        "ambiguous_image_count": 0,
        "box_count": 60,
        "records": gt_records,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "git_write_count": 0,
        "candidate_manifest_sha256": manifest_sha,
        "review_index_sha256": review_index_sha,
    }
    gt = _private_json(root / "future-holdout-gt.private.json", gt_value)
    output = root / "evaluation-v1"
    selected_model = model or _Model(prediction_builder)
    models: list[_Model] = []

    def model_factory(checkpoint_capability: evaluator._VerifiedCheckpoint) -> _Model:
        assert checkpoint_capability.payload == checkpoint_payload
        assert checkpoint_capability.sha256 == checkpoint_sha
        models.append(selected_model)
        return selected_model

    kwargs: dict[str, object] = {
        "freeze": freeze,
        "expected_freeze_sha256": _file_sha(freeze),
        "holdout_manifest": manifest,
        "expected_holdout_manifest_sha256": manifest_sha,
        "holdout_gt": gt,
        "expected_holdout_gt_sha256": _file_sha(gt),
        "checkpoint": checkpoint,
        "expected_checkpoint_sha256": checkpoint_sha,
        "expected_evaluator_sha256": _file_sha(Path(evaluator.__file__)),
        "output": output,
        "model_factory": model_factory,
    }
    return _Case(
        root,
        freeze,
        manifest,
        gt,
        checkpoint,
        images,
        output,
        kwargs,
        manifest_value,
        gt_value,
        checkpoint_payload,
        models,
    )


def _rewrite_json(case: _Case, name: str, value: Mapping[str, object]) -> None:
    path = getattr(case, name)
    _private_json(path, value)
    case.kwargs[f"expected_{'holdout_' if name in {'manifest', 'gt'} else ''}{name}_sha256"] = _file_sha(path)


def _read_output(case: _Case) -> tuple[dict[str, object], dict[str, object]]:
    ledger_path = case.output / evaluator.LEDGER_NAME
    report_path = case.output / evaluator.REPORT_NAME
    assert ledger_path.stat().st_mode & 0o777 == 0o600
    assert report_path.stat().st_mode & 0o777 == 0o600
    return json.loads(ledger_path.read_bytes()), json.loads(report_path.read_bytes())


def _claim_path(case: _Case) -> Path:
    return case.manifest.parent / ".locks" / (
        "evaluate-"
        f"{case.kwargs['expected_freeze_sha256']}-"
        f"{case.kwargs['expected_holdout_manifest_sha256']}-"
        f"{case.kwargs['expected_holdout_gt_sha256']}.started.private.json"
    )


def _staging_directories(case: _Case) -> list[Path]:
    return list(case.output.parent.glob(f".{case.output.name}.quarantine-*"))


def _independent_metrics(
    records: Sequence[Mapping[str, object]],
    predictions: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Independent literal greedy-IoU recomputation; it never imports Task 2 helpers."""

    def iou(left: Sequence[float], right: Sequence[float]) -> float:
        intersection = max(0.0, min(left[2], right[2]) - max(left[0], right[0])) * max(
            0.0, min(left[3], right[3]) - max(left[1], right[1])
        )
        union = (
            (left[2] - left[0]) * (left[3] - left[1])
            + (right[2] - right[0]) * (right[3] - right[1])
            - intersection
        )
        return intersection / union if union else 0.0

    tp = fp = fn = duplicate = positive_recalled = false_positive_negative = 0
    for gt_record, prediction_record in zip(records, predictions, strict=True):
        gt_boxes = [box["points"] for box in gt_record["boxes"]]  # type: ignore[index]
        matched: set[int] = set()
        image_tp = False
        image_predictions = sorted(
            prediction_record["predictions"],  # type: ignore[arg-type]
            key=lambda row: (-row["confidence"], row["xyxy"]),
        )
        for prediction in image_predictions:
            overlaps = [iou(prediction["xyxy"], box) for box in gt_boxes]
            candidates = [
                (overlap, index)
                for index, overlap in enumerate(overlaps)
                if index not in matched
            ]
            best_overlap, best_index = max(candidates, default=(0.0, -1))
            if best_index >= 0 and best_overlap >= 0.50:
                matched.add(best_index)
                tp += 1
                image_tp = True
            else:
                fp += 1
                duplicate += int(any(overlap >= 0.50 for overlap in overlaps))
        fn += len(gt_boxes) - len(matched)
        positive_recalled += int(bool(gt_boxes) and image_tp)
        false_positive_negative += int(not gt_boxes and bool(image_predictions))
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "duplicate": duplicate,
        "precision": tp / (tp + fp),
        "recall": tp / (tp + fn),
        "positive_image_recall": positive_recalled / 60,
        "false_positive_negative_images": false_positive_negative,
    }


def test_approved_checkpoint_pin_is_the_exact_v24_checkpoint() -> None:
    assert evaluator.APPROVED_CHECKPOINT_SHA256 == APPROVED_CHECKPOINT_SHA256


def test_fixed_gate_boundaries_are_inclusive_and_statuses_are_exact() -> None:
    accepted = evaluator.classify_shadow_status(
        precision=0.60,
        recall=0.60,
        positive_image_recall=0.60,
        false_positive_negative_images=6,
        duplicate=4,
        integrity_violations=0,
        overlap_violations=0,
        one_shot_violations=0,
        write_violations=0,
    )
    assert accepted["status"] == "V24B_SHADOW_CANDIDATE"
    for field, failing in (
        ("precision", 0.599999),
        ("recall", 0.599999),
        ("positive_image_recall", 0.599999),
        ("false_positive_negative_images", 7),
        ("duplicate", 5),
        ("integrity_violations", 1),
        ("overlap_violations", 1),
        ("one_shot_violations", 1),
        ("write_violations", 1),
    ):
        values = {
            "precision": 0.60,
            "recall": 0.60,
            "positive_image_recall": 0.60,
            "false_positive_negative_images": 6,
            "duplicate": 4,
            "integrity_violations": 0,
            "overlap_violations": 0,
            "one_shot_violations": 0,
            "write_violations": 0,
        }
        values[field] = failing
        assert evaluator.classify_shadow_status(**values)["status"] == "V24B_FUTURE_HOLDOUT_REJECTED"


def test_one_shot_evaluation_uses_frozen_contract_and_matches_independent_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)

    result = evaluator.evaluate_future_holdout(**case.kwargs)

    ledger, report = _read_output(case)
    assert result == report
    assert report["status"] == "V24B_SHADOW_CANDIDATE"
    assert ledger["decision_status"] == "V24B_SHADOW_CANDIDATE"
    assert len(case.models) == 1 and case.models[0].predict_calls == 1
    assert len(case.models[0].sources) == 120
    assert case.models[0].kwargs == {
        "conf": 0.25,
        "imgsz": 960,
        "iou": 0.50,
        "max_det": 50,
        "device": "mps",
        "verbose": False,
        "stream": False,
        "save": False,
    }
    independent = _independent_metrics(case.gt_value["records"], ledger["records"])  # type: ignore[arg-type]
    assert independent == {
        "tp": 45,
        "fp": 6,
        "fn": 15,
        "duplicate": 2,
        "precision": 45 / 51,
        "recall": 0.75,
        "positive_image_recall": 0.75,
        "false_positive_negative_images": 4,
    }
    assert report["metrics"] == independent
    assert ledger["metrics"] == independent
    assert report["counts"] == {
        "image_count": 120,
        "positive_image_count": 60,
        "negative_image_count": 60,
        "gt_box_count": 60,
        "raw_prediction_count": 51,
    }
    assert report["violations"] == {
        "integrity": 0,
        "overlap": 0,
        "one_shot": 0,
        "write": 0,
    }
    assert report["write_audit"] == {
        "db": 0,
        "r2": 0,
        "service": 0,
        "gme": 0,
        "labeling_web": 0,
        "git": 0,
    }


def test_metric_failure_is_rejected_without_retuning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch, prediction_builder=_rejected_predictions)

    result = evaluator.evaluate_future_holdout(**case.kwargs)

    ledger, report = _read_output(case)
    assert result["status"] == report["status"] == "V24B_FUTURE_HOLDOUT_REJECTED"
    assert ledger["decision_status"] == "V24B_FUTURE_HOLDOUT_REJECTED"
    assert report["metrics"]["recall"] == 0.50
    assert report["metrics"]["false_positive_negative_images"] == 7
    assert report["gates"]["recall"]["passed"] is False
    assert report["gates"]["false_positive_negative_images"]["passed"] is False


@pytest.mark.parametrize(
    ("pin_name", "bad_value"),
    [
        ("expected_freeze_sha256", ZERO_SHA),
        ("expected_holdout_manifest_sha256", ZERO_SHA),
        ("expected_holdout_gt_sha256", ZERO_SHA),
        ("expected_checkpoint_sha256", ZERO_SHA),
        ("expected_evaluator_sha256", ZERO_SHA),
    ],
)
def test_every_private_input_and_code_requires_an_independent_sha_pin_before_predictor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pin_name: str,
    bad_value: str,
) -> None:
    case = _case(tmp_path, monkeypatch)
    case.kwargs[pin_name] = bad_value

    with pytest.raises(ValueError, match="sha256|SHA-256|approved"):
        evaluator.evaluate_future_holdout(**case.kwargs)

    assert case.models == []


@pytest.mark.parametrize("mutation", ["checkpoint", "confidence", "nms", "code", "dataset"])
def test_freeze_rejects_checkpoint_postprocess_code_or_dataset_injection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    case = _case(tmp_path, monkeypatch)
    freeze = json.loads(case.freeze.read_bytes())
    if mutation == "checkpoint":
        freeze["checkpoint_sha256"] = "7" * 64
    elif mutation == "confidence":
        freeze["selected"]["confidence"] = 0.30
    elif mutation == "nms":
        freeze["selected"]["nms_iou"] = 0.55
    elif mutation == "code":
        freeze["runner_sha256"] = "7" * 64
    else:
        freeze["dataset_manifest_sha256"] = "7" * 64
    _rewrite_json(case, "freeze", freeze)

    with pytest.raises(ValueError, match="freeze|checkpoint|selected|code|dataset"):
        evaluator.evaluate_future_holdout(**case.kwargs)

    assert case.models == []


@pytest.mark.parametrize(
    ("name", "value"),
    [("INFERENCE_IMAGE_SIZE", 640), ("INFERENCE_MAX_DETECTIONS", 51), ("INFERENCE_DEVICE", "cpu")],
)
def test_runtime_inference_contract_injection_fails_before_predictor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: object,
) -> None:
    case = _case(tmp_path, monkeypatch)
    monkeypatch.setattr(evaluator, name, value)

    with pytest.raises(ValueError, match="inference contract"):
        evaluator.evaluate_future_holdout(**case.kwargs)

    assert case.models == []


@pytest.mark.parametrize(
    "prediction",
    [
        (True, [1.0, 1.0, 5.0, 5.0]),
        (float("nan"), [1.0, 1.0, 5.0, 5.0]),
        (float("inf"), [1.0, 1.0, 5.0, 5.0]),
        (0.9, [1.0, 1.0, 5.0]),
        (0.9, [1.0, 1.0, 17.0, 5.0]),
        (0.9, [5.0, 1.0, 1.0, 5.0]),
        (0.9, [1.0, 1.0, 1.0, 5.0]),
        (0.9, [1.0, -1.0, 5.0, 5.0]),
        (0.9, [1.0, 1.0, float("nan"), 5.0]),
    ],
)
def test_bool_nonfinite_malformed_oob_and_nonpositive_predictions_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prediction: tuple[object, object],
) -> None:
    case = _case(tmp_path, monkeypatch, prediction_builder=lambda _index: [prediction])

    with pytest.raises(ValueError, match="prediction|box|bounds"):
        evaluator.evaluate_future_holdout(**case.kwargs)

    assert not (case.output / evaluator.LEDGER_NAME).exists()


def test_missing_boxes_and_more_than_frozen_max_det_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_model = _Model(_passing_predictions)
    missing = _case(tmp_path / "missing", monkeypatch, model=missing_model)
    real_predict = missing_model.predict

    def missing_boxes(**kwargs: object) -> list[object]:
        results = real_predict(**kwargs)
        results[0].boxes = None
        return results

    monkeypatch.setattr(missing_model, "predict", missing_boxes)
    with pytest.raises(ValueError, match="boxes|prediction"):
        evaluator.evaluate_future_holdout(**missing.kwargs)

    too_many = _case(
        tmp_path / "max-det",
        monkeypatch,
        prediction_builder=lambda _index: [
            (0.9, [1.0, 1.0, 5.0, 5.0])
            for _ in range(evaluator.INFERENCE_MAX_DETECTIONS + 1)
        ],
    )
    with pytest.raises(ValueError, match="max_det|prediction"):
        evaluator.evaluate_future_holdout(**too_many.kwargs)


def test_boolean_or_nonfinite_gt_and_cross_pin_mismatch_fail_before_predictor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    gt = json.loads(case.gt.read_bytes())
    gt["records"][0]["width"] = True
    _rewrite_json(case, "gt", gt)
    with pytest.raises(ValueError, match="GT|ground truth|dimension"):
        evaluator.evaluate_future_holdout(**case.kwargs)
    assert case.models == []

    second = _case(tmp_path / "cross-pin", monkeypatch)
    gt = json.loads(second.gt.read_bytes())
    gt["candidate_manifest_sha256"] = "8" * 64
    _rewrite_json(second, "gt", gt)
    with pytest.raises(ValueError, match="manifest|cross-pin"):
        evaluator.evaluate_future_holdout(**second.kwargs)
    assert second.models == []


@pytest.mark.parametrize("mutation", ["missing", "mismatch"])
def test_manifest_must_cross_pin_the_exact_postprocess_freeze_before_predictor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    case = _case(tmp_path, monkeypatch)
    manifest = json.loads(case.manifest.read_bytes())
    if mutation == "missing":
        del manifest["postprocess_freeze_sha256"]
    else:
        manifest["postprocess_freeze_sha256"] = "a" * 64
    _rewrite_json(case, "manifest", manifest)

    with pytest.raises(ValueError, match="freeze.*cross-pin|manifest.*freeze"):
        evaluator.evaluate_future_holdout(**case.kwargs)

    assert case.models == []


def test_reversed_result_order_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _Model(_passing_predictions)
    case = _case(tmp_path, monkeypatch, model=model)
    real_predict = model.predict

    def reversed_predict(**kwargs: object) -> list[object]:
        return list(reversed(real_predict(**kwargs)))

    monkeypatch.setattr(model, "predict", reversed_predict)
    with pytest.raises(ValueError, match="order"):
        evaluator.evaluate_future_holdout(**case.kwargs)
    assert not (case.output / evaluator.LEDGER_NAME).exists()


@pytest.mark.parametrize("target", ["checkpoint", "image"])
def test_checkpoint_and_image_aba_are_detected_after_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    mutation: dict[str, Callable[[], None]] = {}
    model = _Model(_passing_predictions, before_results=lambda: mutation["run"]())
    case = _case(tmp_path, monkeypatch, model=model)

    def replace(path: Path) -> None:
        attacker = path.with_name(f".{path.name}.replacement")
        _private_bytes(attacker, path.read_bytes())
        os.replace(attacker, path)

    mutation["run"] = lambda: replace(
        case.checkpoint if target == "checkpoint" else case.images / "H0001.jpg"
    )
    with pytest.raises(ValueError, match="changed|identity|ABA"):
        evaluator.evaluate_future_holdout(**case.kwargs)
    assert model.predict_calls == 1
    assert not (case.output / evaluator.LEDGER_NAME).exists()
    assert not (case.output / evaluator.REPORT_NAME).exists()


def test_model_factory_receives_only_verified_immutable_checkpoint_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    model = _Model(_passing_predictions)
    received: list[bytes] = []
    attacker_payload = b"attacker-checkpoint-bytes"

    def replacing_factory(
        checkpoint_capability: evaluator._VerifiedCheckpoint,
    ) -> _Model:
        staging = _staging_directories(case)
        assert len(staging) == 1
        pinned = staging[0] / ".pinned" / "v24-best.private.pt"
        attacker = pinned.with_name("attacker.private.pt")
        _private_bytes(attacker, attacker_payload)
        os.replace(attacker, pinned)
        received.append(checkpoint_capability.payload)
        assert not hasattr(checkpoint_capability, "path")
        return model

    case.kwargs["model_factory"] = replacing_factory
    with pytest.raises(ValueError, match="pinned checkpoint.*ownership"):
        evaluator.evaluate_future_holdout(**case.kwargs)

    assert received == [case.checkpoint_payload]
    assert attacker_payload not in received
    assert model.predict_calls == 0


def test_retry_after_success_calls_no_model_or_predictor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    evaluator.evaluate_future_holdout(**case.kwargs)
    second_calls = 0

    def forbidden_factory(_checkpoint: evaluator._VerifiedCheckpoint) -> object:
        nonlocal second_calls
        second_calls += 1
        raise AssertionError("retry must stop before model construction")

    case.kwargs["model_factory"] = forbidden_factory
    with pytest.raises(FileExistsError, match="one-shot|exists|output"):
        evaluator.evaluate_future_holdout(**case.kwargs)
    assert second_calls == 0
    assert case.models[0].predict_calls == 1


def test_changing_output_cannot_bypass_the_holdout_identity_one_shot_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    evaluator.evaluate_future_holdout(**case.kwargs)
    second_factory_calls = 0

    def forbidden_factory(_checkpoint: evaluator._VerifiedCheckpoint) -> object:
        nonlocal second_factory_calls
        second_factory_calls += 1
        raise AssertionError("same holdout cannot be evaluated under a new output")

    second_kwargs = {
        **case.kwargs,
        "output": case.root / "evaluation-v2",
        "model_factory": forbidden_factory,
    }
    with pytest.raises(FileExistsError, match="one-shot|exists"):
        evaluator.evaluate_future_holdout(**second_kwargs)

    assert second_factory_calls == 0
    assert case.models[0].predict_calls == 1


def test_concurrent_loser_calls_no_model_or_predictor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = threading.Event()
    release = threading.Event()
    model = _Model(_passing_predictions, entered=entered, release=release)
    case = _case(tmp_path, monkeypatch, model=model)
    failures: list[BaseException] = []

    def first() -> None:
        try:
            evaluator.evaluate_future_holdout(**case.kwargs)
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    thread = threading.Thread(target=first)
    thread.start()
    assert entered.wait(timeout=10)
    loser_factory_calls = 0

    def loser_factory(_checkpoint: evaluator._VerifiedCheckpoint) -> object:
        nonlocal loser_factory_calls
        loser_factory_calls += 1
        raise AssertionError("concurrent loser must stop before model construction")

    loser_kwargs = {**case.kwargs, "model_factory": loser_factory}
    with pytest.raises(FileExistsError, match="one-shot|exists|output"):
        evaluator.evaluate_future_holdout(**loser_kwargs)
    assert loser_factory_calls == 0
    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert failures == []
    assert model.predict_calls == 1


def test_coordinator_and_both_final_reservations_exist_before_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    model = _Model(_passing_predictions)

    def observing_factory(
        checkpoint_capability: evaluator._VerifiedCheckpoint,
    ) -> _Model:
        staging = _staging_directories(case)
        assert len(staging) == 1
        lock = _claim_path(case)
        ledger = staging[0] / evaluator.LEDGER_NAME
        report = staging[0] / evaluator.REPORT_NAME
        assert json.loads(lock.read_bytes())["status"] == "STARTED"
        assert json.loads(ledger.read_bytes())["status"] == "RESERVED"
        assert json.loads(report.read_bytes())["status"] == "RESERVED"
        assert checkpoint_capability.payload == case.checkpoint_payload
        assert (staging[0] / ".pinned" / "v24-best.private.pt").stat().st_mode & 0o777 == 0o600
        assert not case.output.exists()
        return model

    case.kwargs["model_factory"] = observing_factory
    evaluator.evaluate_future_holdout(**case.kwargs)
    assert model.predict_calls == 1


def test_lock_replacement_during_prediction_fails_closed_and_preserves_rival(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mutation: dict[str, Callable[[], None]] = {}
    model = _Model(_passing_predictions, before_results=lambda: mutation["run"]())
    case = _case(tmp_path, monkeypatch, model=model)
    rival_payload = b'{"owner":"rival-lock"}\n'

    def replace_lock() -> None:
        lock = _claim_path(case)
        rival = lock.with_name(".rival-lock.private.json")
        _private_bytes(rival, rival_payload)
        os.replace(rival, lock)

    mutation["run"] = replace_lock
    with pytest.raises(ValueError, match="coordinator.*ownership"):
        evaluator.evaluate_future_holdout(**case.kwargs)
    assert _claim_path(case).read_bytes() == rival_payload
    assert not (case.output / evaluator.LEDGER_NAME).exists()
    assert not (case.output / evaluator.REPORT_NAME).exists()


def test_duplicate_nonfinite_json_and_nonprivate_mode_fail_before_predictor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    duplicate = _case(tmp_path / "duplicate", monkeypatch)
    payload = duplicate.gt.read_bytes().rstrip()[:-1] + b',"image_count":120}\n'
    _private_bytes(duplicate.gt, payload)
    duplicate.kwargs["expected_holdout_gt_sha256"] = _file_sha(duplicate.gt)
    with pytest.raises(ValueError, match="duplicate JSON key"):
        evaluator.evaluate_future_holdout(**duplicate.kwargs)
    assert duplicate.models == []

    nonfinite = _case(tmp_path / "nonfinite", monkeypatch)
    payload = nonfinite.gt.read_bytes().replace(b'"box_count":60', b'"box_count":NaN')
    _private_bytes(nonfinite.gt, payload)
    nonfinite.kwargs["expected_holdout_gt_sha256"] = _file_sha(nonfinite.gt)
    with pytest.raises(ValueError, match="nonfinite JSON"):
        evaluator.evaluate_future_holdout(**nonfinite.kwargs)
    assert nonfinite.models == []

    public = _case(tmp_path / "public", monkeypatch)
    public.freeze.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        evaluator.evaluate_future_holdout(**public.kwargs)
    assert public.models == []


def test_output_symlink_is_rejected_before_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    attacker = case.root / "attacker-output"
    attacker.mkdir(mode=0o700)
    case.output.symlink_to(attacker, target_is_directory=True)

    with pytest.raises(ValueError, match="output.*directory|symlink"):
        evaluator.evaluate_future_holdout(**case.kwargs)

    assert case.models == []
    assert list(attacker.iterdir()) == []


def test_report_publish_failure_leaves_no_ledger_only_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    real_replace = evaluator._atomic_replace_owned_json
    saw_final_ledger_while_public_output_absent = False

    def fail_report(reservation: object, value: Mapping[str, object]) -> object:
        nonlocal saw_final_ledger_while_public_output_absent
        if reservation.path.name == evaluator.REPORT_NAME:  # type: ignore[attr-defined]
            private_ledger = reservation.path.parent / evaluator.LEDGER_NAME  # type: ignore[attr-defined]
            assert json.loads(private_ledger.read_bytes())["schema"] == evaluator.LEDGER_SCHEMA
            saw_final_ledger_while_public_output_absent = not case.output.exists()
            raise OSError("injected report publication failure")
        return real_replace(reservation, value)

    monkeypatch.setattr(evaluator, "_atomic_replace_owned_json", fail_report)
    with pytest.raises(OSError, match="report publication"):
        evaluator.evaluate_future_holdout(**case.kwargs)

    assert saw_final_ledger_while_public_output_absent is True
    assert not case.output.exists()


def test_publish_cleanup_never_removes_a_rival_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    real_replace = evaluator._atomic_replace_owned_json
    rival_payload = b'{"owner":"rival"}\n'
    rival_ledger_paths: list[Path] = []

    def replace_then_fail(reservation: object, value: Mapping[str, object]) -> object:
        if reservation.path.name == evaluator.REPORT_NAME:  # type: ignore[attr-defined]
            ledger_path = reservation.path.parent / evaluator.LEDGER_NAME  # type: ignore[attr-defined]
            rival = ledger_path.with_name(".rival.private.json")
            _private_bytes(rival, rival_payload)
            os.replace(rival, ledger_path)
            rival_ledger_paths.append(ledger_path)
            raise OSError("injected rival publication failure")
        return real_replace(reservation, value)

    monkeypatch.setattr(evaluator, "_atomic_replace_owned_json", replace_then_fail)
    with pytest.raises(OSError, match="rival publication"):
        evaluator.evaluate_future_holdout(**case.kwargs)
    assert len(rival_ledger_paths) == 1
    assert rival_ledger_paths[0].read_bytes() == rival_payload
    assert not case.output.exists()


def test_staging_directory_aba_cannot_publish_a_rival_pair_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    real_fsync = validation_runner._fsync_directory
    rival_ledger = b'{"owner":"rival-ledger"}\n'
    rival_report = b'{"owner":"rival-report"}\n'
    swapped = False
    final_staging_fsyncs = 0

    def swap_at_final_staging_fsync(path: Path) -> None:
        nonlocal swapped, final_staging_fsyncs
        if (
            not swapped
            and path.name.startswith(f".{case.output.name}.quarantine-")
            and (path / evaluator.LEDGER_NAME).exists()
            and json.loads((path / evaluator.LEDGER_NAME).read_bytes()).get("schema")
            == evaluator.LEDGER_SCHEMA
            and json.loads((path / evaluator.REPORT_NAME).read_bytes()).get("schema")
            == evaluator.REPORT_SCHEMA
        ):
            final_staging_fsyncs += 1
            if final_staging_fsyncs == 2:
                captured = path.with_name(f"{path.name}.captured-owned")
                os.rename(path, captured)
                path.mkdir(mode=0o700)
                _private_bytes(path / evaluator.LEDGER_NAME, rival_ledger)
                _private_bytes(path / evaluator.REPORT_NAME, rival_report)
                swapped = True
        real_fsync(path)

    monkeypatch.setattr(validation_runner, "_fsync_directory", swap_at_final_staging_fsync)
    with pytest.raises(ValueError, match="staging.*identity|publication.*identity"):
        evaluator.evaluate_future_holdout(**case.kwargs)

    assert swapped is True
    if case.output.exists():
        assert (case.output / evaluator.LEDGER_NAME).read_bytes() == rival_ledger
        assert (case.output / evaluator.REPORT_NAME).read_bytes() == rival_report


def test_coordinator_ownership_is_checked_at_pair_publication_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    real_fsync = validation_runner._fsync_directory
    rival_lock = b'{"owner":"late-rival-lock"}\n'
    final_staging_fsyncs = 0

    def replace_late(path: Path) -> None:
        nonlocal final_staging_fsyncs
        if (
            path.name.startswith(f".{case.output.name}.quarantine-")
            and (path / evaluator.LEDGER_NAME).exists()
            and (path / evaluator.REPORT_NAME).exists()
            and json.loads((path / evaluator.LEDGER_NAME).read_bytes()).get("schema")
            == evaluator.LEDGER_SCHEMA
            and json.loads((path / evaluator.REPORT_NAME).read_bytes()).get("schema")
            == evaluator.REPORT_SCHEMA
        ):
            final_staging_fsyncs += 1
            if final_staging_fsyncs == 2:
                lock = _claim_path(case)
                rival = lock.with_name("late-rival.private.json")
                _private_bytes(rival, rival_lock)
                os.replace(rival, lock)
        real_fsync(path)

    monkeypatch.setattr(validation_runner, "_fsync_directory", replace_late)
    with pytest.raises(ValueError, match="coordinator.*ownership"):
        evaluator.evaluate_future_holdout(**case.kwargs)

    assert _claim_path(case).read_bytes() == rival_lock
    assert not (case.output / evaluator.LEDGER_NAME).exists()
    assert not (case.output / evaluator.REPORT_NAME).exists()
    assert not (case.output / ".pinned" / "v24-best.private.pt").exists()


def test_public_output_directory_is_reverified_after_parent_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    real_fsync = validation_runner._fsync_directory
    rival_ledger = b'{"owner":"late-rival-ledger"}\n'
    rival_report = b'{"owner":"late-rival-report"}\n'
    swapped = False

    def swap_during_parent_fsync(path: Path) -> None:
        nonlocal swapped
        if (
            not swapped
            and path == case.output.parent
            and case.output.exists()
            and (case.output / evaluator.LEDGER_NAME).exists()
            and json.loads((case.output / evaluator.LEDGER_NAME).read_bytes()).get(
                "schema"
            )
            == evaluator.LEDGER_SCHEMA
            and json.loads((case.output / evaluator.REPORT_NAME).read_bytes()).get(
                "schema"
            )
            == evaluator.REPORT_SCHEMA
        ):
            captured = case.output.with_name(f"{case.output.name}.captured-owned")
            os.rename(case.output, captured)
            case.output.mkdir(mode=0o700)
            _private_bytes(case.output / evaluator.LEDGER_NAME, rival_ledger)
            _private_bytes(case.output / evaluator.REPORT_NAME, rival_report)
            swapped = True
        real_fsync(path)

    monkeypatch.setattr(
        validation_runner, "_fsync_directory", swap_during_parent_fsync
    )
    with pytest.raises(ValueError, match="publication.*identity|published.*ownership"):
        evaluator.evaluate_future_holdout(**case.kwargs)

    assert swapped is True
    assert (case.output / evaluator.LEDGER_NAME).read_bytes() == rival_ledger
    assert (case.output / evaluator.REPORT_NAME).read_bytes() == rival_report


def test_outputs_hide_source_identity_raw_images_and_ground_truth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    evaluator.evaluate_future_holdout(**case.kwargs)
    ledger, report = _read_output(case)

    assert all(set(record) == {"sequence", "predictions"} for record in ledger["records"])
    encoded = json.dumps({"ledger": ledger, "report": report}, sort_keys=True)
    for forbidden in (
        "source_ref",
        "source_sequence",
        "camera_id",
        "camera_night",
        "gt_boxes",
        "presence",
        "filename",
        "raw_image",
    ):
        assert forbidden not in encoded
    assert case.checkpoint_payload.hex() not in encoded


def test_cli_has_no_confidence_or_nms_retune_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    argv = [
        "--freeze", str(case.freeze),
        "--expected-freeze-sha256", str(case.kwargs["expected_freeze_sha256"]),
        "--holdout-manifest", str(case.manifest),
        "--expected-holdout-manifest-sha256", str(case.kwargs["expected_holdout_manifest_sha256"]),
        "--holdout-gt", str(case.gt),
        "--expected-holdout-gt-sha256", str(case.kwargs["expected_holdout_gt_sha256"]),
        "--checkpoint", str(case.checkpoint),
        "--expected-checkpoint-sha256", str(case.kwargs["expected_checkpoint_sha256"]),
        "--expected-evaluator-sha256", str(case.kwargs["expected_evaluator_sha256"]),
        "--output", str(case.output),
        "--confidence", "0.30",
    ]
    with pytest.raises(SystemExit) as exc_info:
        evaluator.main(argv)
    assert exc_info.value.code == 2

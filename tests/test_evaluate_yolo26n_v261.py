from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.evaluate_yolo26n_v261 import (
    VALIDATION_CANDIDATES,
    ValidationShortage,
    build_detector_freeze,
    build_evaluation_preflight,
    build_protection_evidence,
    build_regression_preflight,
    build_regression_report,
    claim_once,
    run_prediction_once,
    score_ledger,
    select_candidate,
    validate_evaluation_bindings,
)


def _record(
    sample: str,
    *,
    gt: list[list[float]],
    prediction: list[tuple[list[float], float]],
    night: str = "night-a",
) -> dict[str, object]:
    return {
        "sample_id": sample,
        "camera_night": night,
        "episode_id": f"episode-{sample}",
        "gt_boxes": gt,
        "predictions": [
            {"box": box, "confidence": confidence} for box, confidence in prediction
        ],
    }


def _ledger(
    candidate: str,
    *,
    miss: bool = False,
    false_positive: bool = False,
    sample_count: int = 18,
) -> dict[str, object]:
    positive_predictions = [] if miss else [([0.1, 0.1, 0.5, 0.5], 0.9)]
    empty_predictions = [([0.2, 0.2, 0.4, 0.4], 0.9)] if false_positive else []
    records = []
    positive_count = sample_count // 2
    negative_count = sample_count - positive_count
    for index in range(positive_count):
        records.append(
            _record(
                f"p{index}",
                gt=[[0.1, 0.1, 0.5, 0.5]],
                prediction=positive_predictions,
                night="night-a" if index < 5 else "night-b",
            )
        )
    for index in range(negative_count):
        records.append(
            _record(
                f"n{index}",
                gt=[],
                prediction=empty_predictions,
                night="night-a" if index < 5 else "night-b",
            )
        )
    protocol = {
        "raw_confidence": 0.001,
        "model_nms_iou": 0.70,
        "max_det": 50,
        "imgsz": 960,
        "device": "mps",
        "resize_mode": "ultralytics_letterbox",
        "input_color": "bgr_file_decode_to_rgb_model",
        "coordinate_space": "normalized_xyxy_original_image",
    }
    protocol_sha = hashlib.sha256(
        json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    checkpoint_sha = hashlib.sha256(candidate.encode()).hexdigest()
    ledger = {
        "schema": "yolo26n-v261-prediction-ledger-v1",
        "status": "V261_PREDICTIONS_READY",
        "candidate": candidate,
        "source_split": "val",
        "evaluation_role": "validation",
        "checkpoint_sha256": checkpoint_sha,
        "source_commit": "1" * 40,
        "lineage": {
            "dataset_sha256": "a" * 64,
            "gt_sha256": "pending",
            "source_sha256": hashlib.sha256(("1" * 40).encode()).hexdigest(),
            "evaluator_sha256": hashlib.sha256(
                Path(run_prediction_once.__code__.co_filename).read_bytes()
            ).hexdigest(),
            "inference_protocol_sha256": protocol_sha,
        },
        "protocol": protocol,
        "records": records,
    }
    canonical_gt = [
        {
            "sample_id": row["sample_id"],
            "camera_night": row["camera_night"],
            "episode_id": row["episode_id"],
            "gt_boxes": [tuple(box) for box in row["gt_boxes"]],
        }
        for row in records
    ]
    ledger["lineage"]["gt_sha256"] = hashlib.sha256(
        json.dumps(canonical_gt, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ledger


def _checkpoint_bindings() -> dict[str, str]:
    return {
        candidate: hashlib.sha256(candidate.encode()).hexdigest()
        for candidate in VALIDATION_CANDIDATES
    }


def _protection_evidence() -> dict[str, object]:
    return {
        "schema": "yolo26n-v261-protection-evidence-v1",
        "status": "V261_PROTECTED_INPUTS_VERIFIED",
        "future_holdout_manifest_sha256": "f" * 64,
        "future_holdout_access_count": 0,
        "old_validation_manifest_sha256": "e" * 64,
        "old_validation_inference_count": 0,
    }


def _bindings(
    dataset_sha: str,
    *,
    source_commit: str = "b" * 40,
    checkpoint_sha256: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "schema": "yolo26n-v261-evaluation-bindings-v1",
        "status": "V261_EVALUATION_PREFLIGHT_READY",
        "source_commit": source_commit,
        "dataset_sha256": dataset_sha,
        "evaluator_sha256": hashlib.sha256(
            Path(run_prediction_once.__code__.co_filename).read_bytes()
        ).hexdigest(),
        "checkpoint_sha256": checkpoint_sha256 or _checkpoint_bindings(),
    }


def _regression_binding(
    *, suite: str, selected: str, freeze: dict[str, object]
) -> dict[str, object]:
    split, count = {
        "v26-recent-val505": ("val", 505),
        "old-internal-test151": ("regression-test", 151),
    }[suite]
    return {
        "schema": "yolo26n-v261-regression-bindings-v1",
        "status": "V261_REGRESSION_PREFLIGHT_READY",
        "suite": suite,
        "source_split": split,
        "expected_sample_count": count,
        "actual_sample_count": count,
        "dataset_sha256": "a" * 64,
        "record_set_sha256": "c" * 64,
        "source_commit": "1" * 40,
        "evaluator_sha256": hashlib.sha256(
            Path(run_prediction_once.__code__.co_filename).read_bytes()
        ).hexdigest(),
        "checkpoint_sha256": {
            candidate: _checkpoint_bindings()[candidate]
            for candidate in ("baseline-v26", selected)
        },
        "freeze_sha256": hashlib.sha256(
            json.dumps(freeze, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def _regression_ledger(
    candidate: str,
    *,
    suite: str,
    binding: dict[str, object],
    false_positive: bool = False,
) -> dict[str, object]:
    ledger = _ledger(
        candidate,
        false_positive=false_positive,
        sample_count=int(binding["expected_sample_count"]),
    )
    ledger["evaluation_role"] = "regression"
    ledger["source_split"] = binding["source_split"]
    ledger["regression_suite"] = suite
    ledger["evaluation_binding_sha256"] = hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    ledger["lineage"]["dataset_sha256"] = binding["dataset_sha256"]
    return ledger


def test_score_ledger_calculates_frame_and_localization_metrics() -> None:
    ledger = _ledger("baseline-v26")
    rows = score_ledger(ledger, confidence_grid=(0.5,), nms_grid=(0.55,))

    assert len(rows) == 1
    row = rows[0]
    assert row["tp"] == 9
    assert row["fp"] == 0
    assert row["fn"] == 0
    assert row["precision"] == 1.0
    assert row["recall"] == 1.0
    assert row["specificity"] == 1.0
    assert row["matched_box_recall"] == 1.0
    assert row["median_matched_iou"] == 1.0
    assert row["median_center_offset"] == 0.0
    assert row["duplicate"] == 0
    assert row["camera_night_min_recall"] == 1.0


def test_score_ledger_counts_duplicate_predictions_after_nms() -> None:
    ledger = _ledger("baseline-v26")
    ledger["records"][0]["predictions"].append(
        {"box": [0.55, 0.1, 0.9, 0.5], "confidence": 0.8}
    )
    row = score_ledger(ledger, confidence_grid=(0.5,), nms_grid=(0.55,))[0]
    assert row["duplicate"] == 1


def test_score_ledger_counts_non_overlapping_prediction_as_fn_and_fp() -> None:
    ledger = _ledger("baseline-v26")
    ledger["records"][0]["predictions"] = [
        {"box": [0.6, 0.6, 0.9, 0.9], "confidence": 0.9}
    ]
    row = score_ledger(ledger, confidence_grid=(0.5,), nms_grid=(0.55,))[0]
    assert row["tp"] == 8
    assert row["fn"] == 1
    assert row["fp"] == 1


def test_select_candidate_requires_exact_seven_ledgers_and_chooses_warm_on_tie() -> (
    None
):
    ledgers = {candidate: _ledger(candidate) for candidate in VALIDATION_CANDIDATES}
    selected = select_candidate(ledgers, confidence_grid=(0.5,), nms_grid=(0.55,))

    assert selected["candidate"] == "warm-start-s26"
    assert selected["threshold"] == 0.5
    assert selected["nms_iou"] == 0.55

    ledgers.pop("clean-reference-s28")
    with pytest.raises(ValueError, match="exactly seven"):
        select_candidate(ledgers, confidence_grid=(0.5,), nms_grid=(0.55,))


def test_select_candidate_fails_closed_when_recall_gate_is_unreachable() -> None:
    ledgers = {
        candidate: _ledger(candidate, miss=True) for candidate in VALIDATION_CANDIDATES
    }
    with pytest.raises(ValidationShortage, match="V261_VALIDATION_SHORTAGE"):
        select_candidate(ledgers, confidence_grid=(0.5,), nms_grid=(0.55,))


def test_select_candidate_rejects_lineage_or_gt_drift() -> None:
    ledgers = {candidate: _ledger(candidate) for candidate in VALIDATION_CANDIDATES}
    ledgers["clean-reference-s28"]["lineage"]["gt_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="GT SHA mismatch"):
        select_candidate(ledgers, confidence_grid=(0.5,), nms_grid=(0.55,))


def test_build_freeze_binds_selected_candidate_and_temporal_contract() -> None:
    ledgers = {candidate: _ledger(candidate) for candidate in VALIDATION_CANDIDATES}
    freeze = build_detector_freeze(
        ledgers,
        checkpoint_sha256=_checkpoint_bindings(),
        protection_evidence=_protection_evidence(),
        confidence_grid=(0.5,),
        nms_grid=(0.55,),
    )
    assert freeze["status"] == "V261_DETECTOR_FROZEN"
    assert freeze["selected_candidate"] == "warm-start-s26"
    assert freeze["temporal_rule"] == {
        "analysis_fps": 10,
        "window_frames": 5,
        "required_positive_frames": 3,
    }
    assert freeze["clip_level_acceptance_pending"] is True
    assert freeze["inference_contract"]["resize_mode"] == "ultralytics_letterbox"
    assert freeze["checkpoint_sha256"] == _checkpoint_bindings()
    assert set(freeze["validation_ledger_sha256"]) == set(VALIDATION_CANDIDATES)


def test_build_freeze_rejects_checkpoint_or_protocol_not_bound_to_ledger() -> None:
    ledgers = {candidate: _ledger(candidate) for candidate in VALIDATION_CANDIDATES}
    bindings = _checkpoint_bindings()
    bindings["warm-start-s26"] = "0" * 64
    with pytest.raises(ValueError, match="checkpoint binding"):
        build_detector_freeze(
            ledgers,
            checkpoint_sha256=bindings,
            protection_evidence=_protection_evidence(),
            confidence_grid=(0.5,),
            nms_grid=(0.55,),
        )
    ledgers = {candidate: _ledger(candidate) for candidate in VALIDATION_CANDIDATES}
    ledgers["warm-start-s26"]["protocol"]["imgsz"] = 640
    with pytest.raises(ValueError, match="inference protocol"):
        build_detector_freeze(
            ledgers,
            checkpoint_sha256=_checkpoint_bindings(),
            protection_evidence=_protection_evidence(),
            confidence_grid=(0.5,),
            nms_grid=(0.55,),
        )


def test_regression_requires_freeze_and_baseline_selected_pair() -> None:
    selected = "warm-start-s26"
    freeze = {
        "schema": "yolo26n-v261-detector-freeze-v1",
        "status": "V261_DETECTOR_FROZEN",
        "selected_candidate": selected,
        "threshold": 0.5,
        "nms_iou": 0.55,
        "checkpoint_sha256": _checkpoint_bindings(),
    }
    suite_bindings = {
        suite: _regression_binding(suite=suite, selected=selected, freeze=freeze)
        for suite in ("v26-recent-val505", "old-internal-test151")
    }
    suites = {
        suite: {
            candidate: _regression_ledger(
                candidate, suite=suite, binding=suite_bindings[suite]
            )
            for candidate in ("baseline-v26", selected)
        }
        for suite in suite_bindings
    }
    report = build_regression_report(
        freeze=freeze, suites=suites, suite_bindings=suite_bindings
    )
    assert report["status"] == "V261_DEVELOPMENT_CANDIDATE_READY"
    assert report["future_holdout_pending"] is True

    broken = copy.deepcopy(freeze)
    broken["status"] = "other"
    with pytest.raises(PermissionError, match="freeze"):
        build_regression_report(
            freeze=broken, suites=suites, suite_bindings=suite_bindings
        )


def test_regression_fails_when_selected_precision_regresses_more_than_two_points() -> (
    None
):
    selected = "warm-start-s26"
    freeze = {
        "schema": "yolo26n-v261-detector-freeze-v1",
        "status": "V261_DETECTOR_FROZEN",
        "selected_candidate": selected,
        "threshold": 0.5,
        "nms_iou": 0.55,
        "checkpoint_sha256": _checkpoint_bindings(),
    }
    suite_bindings = {
        suite: _regression_binding(suite=suite, selected=selected, freeze=freeze)
        for suite in ("v26-recent-val505", "old-internal-test151")
    }
    suites = {
        suite: {
            "baseline-v26": _regression_ledger(
                "baseline-v26", suite=suite, binding=binding
            ),
            selected: _regression_ledger(
                selected, suite=suite, binding=binding, false_positive=True
            ),
        }
        for suite, binding in suite_bindings.items()
    }
    report = build_regression_report(
        freeze=freeze, suites=suites, suite_bindings=suite_bindings
    )
    assert report["status"] == "V261_REGRESSION_FAILED"


def test_regression_rejects_ledger_not_bound_to_fixed_suite() -> None:
    selected = "warm-start-s26"
    freeze = {
        "schema": "yolo26n-v261-detector-freeze-v1",
        "status": "V261_DETECTOR_FROZEN",
        "selected_candidate": selected,
        "threshold": 0.5,
        "nms_iou": 0.55,
        "checkpoint_sha256": _checkpoint_bindings(),
    }
    suite_bindings = {
        suite: _regression_binding(suite=suite, selected=selected, freeze=freeze)
        for suite in ("v26-recent-val505", "old-internal-test151")
    }
    suites = {
        suite: {
            candidate: _regression_ledger(
                candidate, suite=suite, binding=suite_bindings[suite]
            )
            for candidate in ("baseline-v26", selected)
        }
        for suite in suite_bindings
    }
    suites["v26-recent-val505"][selected]["evaluation_binding_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="fixed suite"):
        build_regression_report(
            freeze=freeze, suites=suites, suite_bindings=suite_bindings
        )


def test_claim_once_is_append_only(tmp_path: Path) -> None:
    claim = claim_once(tmp_path, "predict-baseline-v26-val")
    assert json.loads(claim.read_text())["operation"] == "predict-baseline-v26-val"
    with pytest.raises(FileExistsError):
        claim_once(tmp_path, "predict-baseline-v26-val")


def test_regression_prediction_requires_detector_freeze(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    manifest = dataset / "manifest.private.json"
    manifest.write_text(json.dumps({"records": [{"split": "regression-test"}]}))
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"weights")

    with pytest.raises(PermissionError, match="freeze"):
        run_prediction_once(
            dataset_root=dataset,
            manifest_path=manifest,
            split="regression-test",
            candidate="baseline-v26",
            checkpoint=checkpoint,
            source_commit="b" * 40,
            evaluation_root=tmp_path / "evaluation",
            bindings=_bindings(hashlib.sha256(manifest.read_bytes()).hexdigest()),
            regression_suite="old-internal-test151",
        )


def test_validation_prediction_writes_low_confidence_ledger_once(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset"
    (dataset / "images/val").mkdir(parents=True)
    (dataset / "labels/val").mkdir(parents=True)
    image = dataset / "images/val/N0000001.jpg"
    label = dataset / "labels/val/N0000001.txt"
    image.write_bytes(b"image")
    label.write_text("0 0.5 0.5 0.4 0.4\n")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = dataset / "manifest.private.json"
    manifest.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "split": "val",
                        "image_path": "images/val/N0000001.jpg",
                        "label_path": "labels/val/N0000001.txt",
                        "image_sha256": digest(image),
                        "label_sha256": digest(label),
                        "camera_night": "night-a",
                        "episode_id": "episode-a",
                    }
                ]
            }
        )
    )
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"weights")
    evaluation = tmp_path / "evaluation"
    ledger = run_prediction_once(
        dataset_root=dataset,
        manifest_path=manifest,
        split="val",
        candidate="baseline-v26",
        checkpoint=checkpoint,
        source_commit="b" * 40,
        evaluation_root=evaluation,
        bindings=_bindings(
            digest(manifest),
            checkpoint_sha256={
                **_checkpoint_bindings(),
                "baseline-v26": digest(checkpoint),
            },
        ),
        predictor=lambda _: [{"box": [0.3, 0.3, 0.7, 0.7], "confidence": 0.9}],
    )
    assert ledger["status"] == "V261_PREDICTIONS_READY"
    assert ledger["records"][0]["gt_boxes"] == [[0.3, 0.3, 0.7, 0.7]]
    assert (evaluation / "prediction-ledgers/baseline-v26-val.private.json").is_file()
    with pytest.raises(FileExistsError):
        run_prediction_once(
            dataset_root=dataset,
            manifest_path=manifest,
            split="val",
            candidate="baseline-v26",
            checkpoint=checkpoint,
            source_commit="b" * 40,
            evaluation_root=evaluation,
            bindings=_bindings(
                digest(manifest),
                checkpoint_sha256={
                    **_checkpoint_bindings(),
                    "baseline-v26": digest(checkpoint),
                },
            ),
            predictor=lambda _: [],
        )


def test_regression_prediction_can_use_recent_validation_source_split(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset"
    (dataset / "images/val").mkdir(parents=True)
    (dataset / "labels/val").mkdir(parents=True)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    records = []
    for index in range(505):
        image = dataset / f"images/val/{index:04d}.jpg"
        label = dataset / f"labels/val/{index:04d}.txt"
        image.write_bytes(f"image-{index}".encode())
        label.write_text("")
        records.append(
            {
                "split": "val",
                "image_path": f"images/val/{index:04d}.jpg",
                "label_path": f"labels/val/{index:04d}.txt",
                "image_sha256": digest(image),
                "label_sha256": digest(label),
                "camera_night": "night-a",
                "episode_id": f"episode-{index}",
            }
        )
    manifest = dataset / "manifest.private.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "yolo26n-owner-dataset-v26",
                "status": "V26_DATASET_READY",
                "records": records,
            }
        )
    )
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"weights")
    selected_checkpoint = tmp_path / "selected.pt"
    selected_checkpoint.write_bytes(b"selected-weights")
    checkpoint_sha = digest(checkpoint)
    bindings = _checkpoint_bindings()
    bindings["baseline-v26"] = checkpoint_sha
    bindings["warm-start-s26"] = digest(selected_checkpoint)
    freeze = {
        "schema": "yolo26n-v261-detector-freeze-v1",
        "status": "V261_DETECTOR_FROZEN",
        "selected_candidate": "warm-start-s26",
        "checkpoint_sha256": bindings,
    }
    regression_bindings = build_regression_preflight(
        freeze=freeze,
        suite="v26-recent-val505",
        dataset_manifest_path=manifest,
        checkpoints={
            "baseline-v26": checkpoint,
            "warm-start-s26": selected_checkpoint,
        },
        source_commit="1" * 40,
    )
    ledger = run_prediction_once(
        dataset_root=dataset,
        manifest_path=manifest,
        split="val",
        evaluation_role="regression",
        candidate="baseline-v26",
        checkpoint=checkpoint,
        source_commit="1" * 40,
        evaluation_root=tmp_path / "evaluation",
        freeze=freeze,
        bindings=regression_bindings,
        regression_suite="v26-recent-val505",
        predictor=lambda _: [],
    )
    assert ledger["source_split"] == "val"
    assert ledger["evaluation_role"] == "regression"
    assert (
        tmp_path / "evaluation/prediction-ledgers/baseline-v26-regression.private.json"
    ).is_file()

    manifest.write_text(
        json.dumps(
            {
                "schema": "yolo26n-owner-dataset-v26",
                "status": "V26_DATASET_READY",
                "records": records[:-1],
            }
        )
    )
    with pytest.raises(ValueError, match="sample count"):
        build_regression_preflight(
            freeze=freeze,
            suite="v26-recent-val505",
            dataset_manifest_path=manifest,
            checkpoints={
                "baseline-v26": checkpoint,
                "warm-start-s26": selected_checkpoint,
            },
            source_commit="1" * 40,
        )


def test_validate_evaluation_bindings_requires_six_completion_manifests(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps(
            {
                "schema": "yolo26n-owner-dataset-v261",
                "status": "V261_DATASET_READY",
            }
        )
    )
    checkpoints = {}
    completions = {}
    for candidate in VALIDATION_CANDIDATES:
        checkpoint = tmp_path / f"{candidate}.pt"
        checkpoint.write_bytes(candidate.encode())
        checkpoints[candidate] = checkpoint
        if candidate != "baseline-v26":
            manifest = tmp_path / f"{candidate}.json"
            family, seed = candidate.rsplit("-s", 1)
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "yolo26n-v261-training-run-v1",
                        "status": "V261_TRAINING_COMPLETE",
                        "candidate": family,
                        "seed": int(seed),
                        "source_commit": "1" * 40,
                        "dataset_sha256": hashlib.sha256(
                            dataset.read_bytes()
                        ).hexdigest(),
                        "best_pt_sha256": hashlib.sha256(
                            checkpoint.read_bytes()
                        ).hexdigest(),
                    }
                )
            )
            completions[candidate] = manifest
    bindings = validate_evaluation_bindings(
        dataset_manifest_path=dataset,
        checkpoints=checkpoints,
        completion_manifests=completions,
        source_commit="1" * 40,
        approved_baseline_sha256=hashlib.sha256(
            checkpoints["baseline-v26"].read_bytes()
        ).hexdigest(),
    )
    assert set(bindings) == set(VALIDATION_CANDIDATES)
    completions.pop("clean-reference-s28")
    with pytest.raises(ValueError, match="six completion"):
        validate_evaluation_bindings(
            dataset_manifest_path=dataset,
            checkpoints=checkpoints,
            completion_manifests=completions,
            source_commit="1" * 40,
            approved_baseline_sha256=hashlib.sha256(
                checkpoints["baseline-v26"].read_bytes()
            ).hexdigest(),
        )

    artifact = build_evaluation_preflight(
        dataset_manifest_path=dataset,
        checkpoints=checkpoints,
        completion_manifests={
            candidate: tmp_path / f"{candidate}.json"
            for candidate in VALIDATION_CANDIDATES[1:]
        },
        source_commit="1" * 40,
        approved_baseline_sha256=hashlib.sha256(
            checkpoints["baseline-v26"].read_bytes()
        ).hexdigest(),
    )
    assert artifact["status"] == "V261_EVALUATION_PREFLIGHT_READY"

    with pytest.raises(ValueError, match="approved v2.6 SHA"):
        validate_evaluation_bindings(
            dataset_manifest_path=dataset,
            checkpoints=checkpoints,
            completion_manifests={
                candidate: tmp_path / f"{candidate}.json"
                for candidate in VALIDATION_CANDIDATES[1:]
            },
            source_commit="1" * 40,
            approved_baseline_sha256="0" * 64,
        )


def test_prediction_rejects_checkpoint_not_in_preflight(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    (dataset / "images/val").mkdir(parents=True)
    (dataset / "labels/val").mkdir(parents=True)
    image = dataset / "images/val/a.jpg"
    label = dataset / "labels/val/a.txt"
    image.write_bytes(b"image")
    label.write_text("")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = dataset / "manifest.private.json"
    manifest.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "split": "val",
                        "image_path": "images/val/a.jpg",
                        "label_path": "labels/val/a.txt",
                        "image_sha256": digest(image),
                        "label_sha256": digest(label),
                        "camera_night": "night-a",
                        "episode_id": "episode-a",
                    }
                ]
            }
        )
    )
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"wrong")
    with pytest.raises(ValueError, match="preflight checkpoint"):
        run_prediction_once(
            dataset_root=dataset,
            manifest_path=manifest,
            split="val",
            candidate="baseline-v26",
            checkpoint=checkpoint,
            source_commit="1" * 40,
            evaluation_root=tmp_path / "evaluation",
            bindings=_bindings(digest(manifest), source_commit="1" * 40),
            predictor=lambda _: [],
        )


def test_protection_evidence_uses_queue_receipt_and_no_old_validation_ledger(
    tmp_path: Path,
) -> None:
    future = tmp_path / "future.private.json"
    old_validation = tmp_path / "old-validation.private.json"
    completion = tmp_path / "completion.private.json"
    future.write_bytes(b"sealed-source-manifest")
    old_validation.write_bytes(b"old-validation-manifest")
    completion.write_text(
        json.dumps(
            {
                "schema": "yolo26n-v261-blind-queue-completion-v1",
                "status": "BLIND_QUEUE_READY",
                "future_holdout_access_count": 0,
            }
        )
    )
    evidence = build_protection_evidence(
        future_holdout_manifest_path=future,
        queue_completion_path=completion,
        old_validation_manifest_path=old_validation,
        evaluation_root=tmp_path / "evaluation",
    )
    assert evidence["status"] == "V261_PROTECTED_INPUTS_VERIFIED"
    assert evidence["future_holdout_access_count"] == 0
    assert evidence["old_validation_inference_count"] == 0

    ledger = tmp_path / "evaluation/prediction-ledgers/old-validation153.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("{}")
    with pytest.raises(ValueError, match="old validation inference"):
        build_protection_evidence(
            future_holdout_manifest_path=future,
            queue_completion_path=completion,
            old_validation_manifest_path=old_validation,
            evaluation_root=tmp_path / "evaluation",
        )

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import scripts.evaluate_yolo26n_v26 as evaluator

from scripts.evaluate_yolo26n_v26 import (
    INFERENCE_CONTRACT,
    VALIDATION_CANDIDATES,
    V26Sample,
    build_detector_freeze,
    build_regression_report,
    load_v26_samples,
    paired_episode_bootstrap,
    run_prediction_once,
    score_v26_ledger,
    select_v26_candidate,
    verify_evaluator_source_commit,
    verify_prediction_checkpoint_binding,
    verify_v26_training_artifacts,
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _prediction(confidence: float, box: list[float]) -> dict[str, object]:
    return {"confidence": confidence, "xyxy": box}


def _ledger(candidate: str, predictions: list[list[dict[str, object]]]) -> dict[str, object]:
    gt_boxes = [[[10.0, 10.0, 50.0, 50.0]], []]
    return {
        "schema": "yolo26n-v26-prediction-ledger-v1",
        "status": "V26_PREDICTIONS_READY",
        "evaluation_tier": "development",
        "split": "val",
        "candidate": candidate,
        "source_commit": "a" * 40,
        "runner_sha256": _sha(Path(evaluator.__file__).read_bytes()),
        "dataset_manifest_sha256": "c" * 64,
        "recent_split_manifest_sha256": "d" * 64,
        "checkpoint_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
        "inference": INFERENCE_CONTRACT,
        "image_count": 2,
        "gt_box_count": 1,
        "prediction_count": sum(len(items) for items in predictions),
        "records": [
            {
                "sequence": f"S{index + 1:04d}",
                "image_sha256": str(index + 1) * 64,
                "camera_night": f"camera-night-{index + 1}",
                "episode_id": f"episode-{index + 1}",
                "clip_ref": f"clip-{index + 1}",
                "width": 100,
                "height": 100,
                "gt_boxes": gt_boxes[index],
                "predictions": items,
            }
            for index, items in enumerate(predictions)
        ],
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "deploy_count": 0,
    }


def test_load_v26_validation_binds_recent_split_metadata(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    (dataset / "images/val").mkdir(parents=True)
    (dataset / "labels/val").mkdir(parents=True)
    records: list[dict[str, object]] = []
    recent_records: list[dict[str, object]] = []
    for index in range(505):
        sequence = f"V{index:04d}"
        image_payload = f"image-{index}".encode()
        label_payload = b"0 0.5 0.5 0.4 0.4\n" if index % 2 == 0 else b""
        image = dataset / f"images/val/{sequence}.jpg"
        label = dataset / f"labels/val/{sequence}.txt"
        image.write_bytes(image_payload)
        label.write_bytes(label_payload)
        image_sha = _sha(image_payload)
        label_sha = _sha(label_payload)
        records.append({
            "sequence": sequence,
            "split": "val",
            "image_path": f"images/val/{sequence}.jpg",
            "label_path": f"labels/val/{sequence}.txt",
            "image_sha256": image_sha,
            "label_sha256": label_sha,
            "positive": bool(label_payload),
            "box_count": 1 if label_payload else 0,
            "camera_night": f"night-{index % 6}",
            "episode_id": f"episode-{index % 74}",
            "source_dataset": "recent-v26",
        })
        recent_records.append({
            "image_sha256": image_sha,
            "split": "val",
            "camera_night": f"night-{index % 6}",
            "episode_id": f"episode-{index % 74}",
            "clip_ref": f"clip-{index % 90}",
        })

    for split, count in (("train", 3662), ("regression-val", 153), ("regression-test", 151)):
        for index in range(count):
            records.append({
                "sequence": f"{split}-{index}",
                "split": split,
                "image_path": f"images/{split}/{index}.jpg",
                "label_path": f"labels/{split}/{index}.txt",
                "image_sha256": hashlib.sha256(f"{split}-image-{index}".encode()).hexdigest(),
                "label_sha256": hashlib.sha256(f"{split}-label-{index}".encode()).hexdigest(),
            })
    for index in range(2003):
        recent_records.append({
            "image_sha256": hashlib.sha256(f"train-recent-{index}".encode()).hexdigest(),
            "split": "train",
            "camera_night": f"night-{index % 6}",
            "episode_id": f"train-episode-{index % 240}",
            "clip_ref": f"train-clip-{index % 339}",
        })

    recent_split = tmp_path / "recent-split.private.json"
    recent_split.write_text(json.dumps({
        "schema": "yolo26n-v26-recent-split-plan-v1",
        "status": "V26_RECENT_SPLIT_READY",
        "recent_image_count": 2508,
        "recent_split_counts": {"train": 2003, "val": 505},
        "episode_count": 314,
        "recent_records": recent_records,
    }))
    manifest = dataset / "manifest.private.json"
    manifest.write_text(json.dumps({
        "schema": "yolo26n-owner-dataset-v26",
        "status": "V26_DATASET_READY",
        "evaluation_tier": "development",
        "image_count": 4471,
        "active_image_count": 4167,
        "active_split_counts": {"train": 3662, "val": 505},
        "regression_split_counts": {"regression-test": 151, "regression-val": 153},
        "source_commit": "a" * 40,
        "recent_split_sha256": _sha(recent_split.read_bytes()),
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "deploy_count": 0,
        "records": records,
    }))

    samples = load_v26_samples(
        dataset_root=dataset,
        manifest_path=manifest,
        recent_split_path=recent_split,
        split="val",
    )

    assert len(samples) == 505
    assert len({sample.camera_night for sample in samples}) == 6
    assert len({sample.episode_id for sample in samples}) == 74
    assert all(sample.clip_ref for sample in samples)

    recent_split.write_bytes(recent_split.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="recent split SHA"):
        load_v26_samples(
            dataset_root=dataset,
            manifest_path=manifest,
            recent_split_path=recent_split,
            split="val",
        )


def test_score_v26_ledger_calculates_specificity_camera_recall_and_offline_nms() -> None:
    ledger = _ledger(
        "warm-start-s28",
        [
            [
                _prediction(0.90, [10, 10, 50, 50]),
                _prediction(0.80, [11, 11, 49, 49]),
            ],
            [_prediction(0.70, [60, 60, 90, 90])],
        ],
    )

    rows = score_v26_ledger(ledger)
    row = next(item for item in rows if item["threshold"] == 0.50 and item["nms_iou"] == 0.40)

    assert row == {
        "threshold": 0.50,
        "nms_iou": 0.40,
        "tp": 1,
        "fp": 1,
        "fn": 0,
        "precision": 0.5,
        "recall": 1.0,
        "specificity": 0.0,
        "duplicate": 0,
        "camera_night_recall_min": 1.0,
    }


def test_select_v26_candidate_requires_all_gates_and_prefers_recall() -> None:
    failing = {
        "threshold": 0.20,
        "nms_iou": 0.70,
        "precision": 0.90,
        "recall": 0.89,
        "specificity": 0.95,
        "camera_night_recall_min": 0.90,
        "fp": 1,
        "duplicate": 0,
    }
    metrics = {candidate: [dict(failing)] for candidate in VALIDATION_CANDIDATES if candidate != "baseline-v25"}
    metrics["warm-start-s28"] = [{
        **failing,
        "threshold": 0.25,
        "recall": 0.92,
    }]
    metrics["clean-reference-s28"] = [{
        **failing,
        "threshold": 0.30,
        "recall": 0.91,
        "specificity": 0.97,
    }]

    selection = select_v26_candidate(metrics)

    assert selection["candidate"] == "warm-start-s28"
    assert selection["threshold"] == 0.25
    assert selection["nms_iou"] == 0.70


def test_select_v26_candidate_fails_closed_when_no_row_passes() -> None:
    row = {
        "threshold": 0.20,
        "nms_iou": 0.70,
        "precision": 0.79,
        "recall": 0.95,
        "specificity": 0.95,
        "camera_night_recall_min": 0.90,
        "fp": 1,
        "duplicate": 0,
    }
    with pytest.raises(ValueError, match="V26_VALIDATION_SHORTAGE"):
        select_v26_candidate({candidate: [row] for candidate in VALIDATION_CANDIDATES if candidate != "baseline-v25"})


def test_detector_freeze_requires_same_protocol_baseline_and_all_six_candidates() -> None:
    ledgers = {
        candidate: _ledger(candidate, [[_prediction(0.9, [10, 10, 50, 50])], []])
        for candidate in VALIDATION_CANDIDATES
    }
    hashes = {candidate: hashlib.sha256(candidate.encode()).hexdigest() for candidate in VALIDATION_CANDIDATES}

    freeze = build_detector_freeze(ledgers, ledger_sha256=hashes)

    assert freeze["status"] == "V26_DETECTOR_FROZEN_DEVELOPMENT_ONLY"
    assert freeze["baseline_remeasured_same_protocol"] is True
    assert freeze["temporal_contract"] == {
        "max_analysis_fps": 10.0,
        "window_frames": 5,
        "min_positive_frames": 3,
    }
    assert freeze["clip_level_acceptance_pending"] is True

    del ledgers["baseline-v25"]
    with pytest.raises(ValueError, match="all seven"):
        build_detector_freeze(ledgers, ledger_sha256={key: hashes[key] for key in ledgers})


def test_prediction_claims_before_inference_and_cannot_repeat(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    label = tmp_path / "frame.txt"
    image.write_bytes(b"frame")
    label.write_text("0 0.5 0.5 0.4 0.4\n")
    sample = V26Sample(
        sequence="S0001",
        image_path=image,
        label_path=label,
        image_sha256=_sha(image.read_bytes()),
        label_sha256=_sha(label.read_bytes()),
        normalized_gt_boxes=((0.3, 0.3, 0.7, 0.7),),
        camera_night="night-1",
        episode_id="episode-1",
        clip_ref="clip-1",
    )
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model")
    manifest = tmp_path / "manifest.private.json"
    recent_split = tmp_path / "recent-split.private.json"
    manifest.write_text("{}")
    recent_split.write_text("{}")
    evaluation = tmp_path / "evaluation"
    calls = 0

    def predictor(paths, **contract):
        nonlocal calls
        calls += 1
        assert (evaluation / ".locks/predict-baseline-v25-val.started.private.json").is_file()
        assert list(paths) == [image]
        assert contract == {
            "confidence": 0.001,
            "imgsz": 960,
            "nms_iou": 0.70,
            "max_det": 50,
            "device": "mps",
        }
        return [{"width": 100, "height": 100, "predictions": []}]

    kwargs = dict(
        dataset_root=tmp_path,
        manifest_path=manifest,
        recent_split_path=recent_split,
        split="val",
        candidate="baseline-v25",
        checkpoint_path=checkpoint,
        source_commit="a" * 40,
        evaluation_root=evaluation,
        predictor=predictor,
        sample_loader=lambda **_kwargs: (sample,),
        source_verifier=lambda **_kwargs: None,
    )
    ledger = run_prediction_once(**kwargs)

    assert ledger["image_count"] == 1
    assert (evaluation / "prediction-ledgers/baseline-v25-val.private.json").is_file()
    with pytest.raises(FileExistsError):
        run_prediction_once(**kwargs)
    assert calls == 1


def test_regression_report_compares_baseline_and_selected_at_frozen_row() -> None:
    validation_ledgers = {
        candidate: _ledger(candidate, [[_prediction(0.9, [10, 10, 50, 50])], []])
        for candidate in VALIDATION_CANDIDATES
    }
    hashes = {candidate: hashlib.sha256(candidate.encode()).hexdigest() for candidate in VALIDATION_CANDIDATES}
    freeze = build_detector_freeze(validation_ledgers, ledger_sha256=hashes)
    freeze_sha = hashlib.sha256(json.dumps(freeze, sort_keys=True).encode()).hexdigest()
    selected = str(freeze["candidate"])
    test_ledgers = {}
    for candidate in ("baseline-v25", selected):
        ledger = json.loads(json.dumps(validation_ledgers[candidate]))
        ledger["split"] = "regression-test"
        ledger["threshold_freeze_sha256"] = freeze_sha
        test_ledgers[candidate] = ledger

    report = build_regression_report(
        test_ledgers=test_ledgers,
        test_ledger_sha256={candidate: hashlib.sha256(f"test-{candidate}".encode()).hexdigest() for candidate in test_ledgers},
        freeze=freeze,
        freeze_sha256=freeze_sha,
    )

    assert report["status"] == "V26_OLD_REGRESSION_COMPLETED_DEVELOPMENT_ONLY"
    assert report["regression_pass"] is True
    assert set(report["metrics"]) == {"baseline-v25", selected}
    assert report["clip_level_acceptance_pending"] is True


def test_training_preflight_verifies_all_six_manifests_and_checkpoint_hashes(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset-v26-v1"
    dataset.mkdir()
    dataset_manifest = dataset / "manifest.private.json"
    dataset_manifest.write_bytes(b"dataset-manifest")
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    warm_initializer = inputs / "v25-warm-start-best.pt"
    clean_initializer = inputs / "yolo26n-clean-reference.pt"
    warm_initializer.write_bytes(b"warm-initializer")
    clean_initializer.write_bytes(b"clean-initializer")
    manifests = tmp_path / "run-manifests-v26-v2"
    runs = tmp_path / "runs-v26-comparison-v2"
    manifests.mkdir()
    for candidate in ("warm-start", "clean-reference"):
        for seed in (26, 27, 28):
            run_name = f"{candidate}-s{seed}"
            run = runs / run_name
            (run / "weights").mkdir(parents=True)
            results = run / "results.csv"
            best = run / "weights/best.pt"
            results.write_text("epoch,time\n1,1\n")
            best.write_bytes(f"best-{run_name}".encode())
            initializer = warm_initializer if candidate == "warm-start" else clean_initializer
            (manifests / f"{run_name}.private.json").write_text(json.dumps({
                "schema": "yolo26n-v26-training-run-v1",
                "status": "V26_TRAINING_COMPLETED",
                "run_name": run_name,
                "candidate": candidate,
                "seed": seed,
                "returncode": 0,
                "best_pt_sha256": _sha(best.read_bytes()),
                "results_csv_sha256": _sha(results.read_bytes()),
                "dataset_manifest_sha256": _sha(dataset_manifest.read_bytes()),
                "initializer_sha256": _sha(initializer.read_bytes()),
                "source_commit": "a" * 40,
                "db_write_count": 0,
                "r2_write_count": 0,
                "service_write_count": 0,
                "deploy_count": 0,
            }))

    verified = verify_v26_training_artifacts(
        attempt_root=tmp_path,
        training_source_commit="a" * 40,
    )

    assert set(verified) == set(VALIDATION_CANDIDATES)
    assert verified["baseline-v25"] == warm_initializer
    assert verified["warm-start-s28"].name == "best.pt"

    verified["clean-reference-s28"].write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="best.pt SHA"):
        verify_v26_training_artifacts(attempt_root=tmp_path, training_source_commit="a" * 40)


def test_prediction_checkpoint_must_match_verified_training_artifact(tmp_path: Path) -> None:
    expected = tmp_path / "expected.pt"
    unexpected = tmp_path / "unexpected.pt"
    expected.write_bytes(b"expected")
    unexpected.write_bytes(b"unexpected")

    verify_prediction_checkpoint_binding(
        candidate="warm-start-s28",
        checkpoint_path=expected,
        verified={"warm-start-s28": expected},
    )

    with pytest.raises(ValueError, match="verified training artifact"):
        verify_prediction_checkpoint_binding(
            candidate="warm-start-s28",
            checkpoint_path=unexpected,
            verified={"warm-start-s28": expected},
        )


def test_evaluator_source_commit_must_contain_exact_runner_bytes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    runner = repo / "scripts/evaluate.py"
    runner.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "Test"], check=True)
    runner.write_text("print('frozen')\n")
    subprocess.run(["git", "-C", repo, "add", "scripts/evaluate.py"], check=True)
    subprocess.run(["git", "-C", repo, "commit", "-qm", "freeze runner"], check=True)
    commit = subprocess.run(
        ["git", "-C", repo, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    verify_evaluator_source_commit(source_commit=commit, repo_root=repo, runner_path=runner)

    runner.write_text("print('changed')\n")
    with pytest.raises(ValueError, match="runner bytes"):
        verify_evaluator_source_commit(source_commit=commit, repo_root=repo, runner_path=runner)


def test_episode_bootstrap_is_deterministic_and_reports_recall_delta() -> None:
    baseline = _ledger("baseline-v25", [[], []])
    candidate = _ledger("warm-start-s28", [[_prediction(0.9, [10, 10, 50, 50])], []])

    first = paired_episode_bootstrap(
        baseline,
        candidate,
        threshold=0.50,
        nms_iou=0.70,
        seed=260831,
        repetitions=200,
    )
    second = paired_episode_bootstrap(
        baseline,
        candidate,
        threshold=0.50,
        nms_iou=0.70,
        seed=260831,
        repetitions=200,
    )

    assert first == second
    assert first["recall_delta"] == 1.0
    assert first["seed"] == 260831
    assert first["repetitions"] == 200

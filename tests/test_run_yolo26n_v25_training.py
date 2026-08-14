import hashlib
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from scripts.run_yolo26n_v25_training import (
    build_training_command,
    build_v25_training_spec,
    run_v25_training,
)


def test_exact_warm_and_clean_specs(tmp_path: Path) -> None:
    warm = build_v25_training_spec("warm-start", tmp_path / "v24.pt", tmp_path / "data.yaml", tmp_path / "runs")
    clean = build_v25_training_spec("clean-reference", tmp_path / "base.pt", tmp_path / "data.yaml", tmp_path / "runs")
    assert (warm.epochs, warm.patience, warm.lr0) == (60, 15, 0.001)
    assert (clean.epochs, clean.patience, clean.lr0) == (100, 20, 0.01)
    for spec in (warm, clean):
        command = build_training_command(spec, yolo_executable=Path("/venv/bin/yolo"))
        for expected in ("optimizer=AdamW", "imgsz=960", "batch=2", "device=mps", "workers=0", "seed=26", "exist_ok=False"):
            assert expected in command


def test_unknown_candidate_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_v25_training_spec("other", tmp_path / "x.pt", tmp_path / "data.yaml", tmp_path / "runs")


def test_training_rejects_data_yaml_outside_pinned_dataset(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    manifest = dataset / "manifest.private.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "yolo26n-owner-dataset-v25",
                "status": "V25_DATASET_READY",
                "evaluation_tier": "development",
            }
        )
    )
    initializer = tmp_path / "v24.pt"
    initializer.write_bytes(b"checkpoint")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    data_yaml = foreign / "data.yaml"
    data_yaml.write_text("path: foreign\n")
    spec = build_v25_training_spec("warm-start", initializer, data_yaml, tmp_path / "runs")

    with pytest.raises(ValueError, match="data.yaml"):
        run_v25_training(
            spec,
            yolo_executable=Path("/venv/bin/yolo"),
            dataset_manifest=manifest,
            output_manifest=tmp_path / "run.private.json",
            started_lock=tmp_path / "started.private.json",
            source_commit="a" * 40,
            expected_dataset_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
            expected_initializer_sha256=hashlib.sha256(initializer.read_bytes()).hexdigest(),
            expected_runner_sha256=hashlib.sha256(
                Path("scripts/run_yolo26n_v25_training.py").read_bytes()
            ).hexdigest(),
            executor=lambda *_args, **_kwargs: CompletedProcess([], 0),
        )

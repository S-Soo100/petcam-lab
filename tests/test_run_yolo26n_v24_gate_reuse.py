from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.run_yolo26n_v24_gate_reuse import (
    build_training_command,
    build_v24_training_spec,
    run_v24_training,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v24_training_matches_v23_warm_contract(tmp_path: Path) -> None:
    spec = build_v24_training_spec(
        tmp_path / "data.yaml", tmp_path / "v23-best.pt", tmp_path / "runs"
    )
    command = build_training_command(spec, yolo_executable=Path("/venv/bin/yolo"))

    assert command[:3] == ["/venv/bin/yolo", "detect", "train"]
    for expected in (
        "epochs=60",
        "patience=15",
        "optimizer=AdamW",
        "lr0=0.001",
        "imgsz=960",
        "batch=2",
        "device=mps",
        "workers=0",
        "seed=26",
        "name=warm-start",
        "exist_ok=False",
    ):
        assert expected in command


def test_v24_training_claims_one_shot_before_execution_and_records_outputs(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    data_yaml = dataset / "data.yaml"
    data_yaml.write_text("names:\n  0: gecko\n")
    manifest = dataset / "manifest.private.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "yolo26n-owner-dataset-v24",
                "evaluation_tier": "development",
                "future_holdout_required": True,
                "db_write_count": 0,
                "r2_write_count": 0,
                "service_write_count": 0,
            }
        )
    )
    checkpoint = tmp_path / "v23-best.pt"
    checkpoint.write_bytes(b"v23-checkpoint")
    yolo = tmp_path / "yolo"
    yolo.write_text("runner")
    runs = tmp_path / "runs"
    output_manifest = tmp_path / "run-manifest.private.json"
    lock = tmp_path / ".locks/warm-start.started.private.json"
    calls: list[list[str]] = []

    class Completed:
        returncode = 0

    def executor(command: list[str], check: bool):
        calls.append(command)
        run = runs / "warm-start"
        (run / "weights").mkdir(parents=True)
        (run / "weights/best.pt").write_bytes(b"trained")
        (run / "results.csv").write_text("epoch,metric\n1,0.5\n")
        return Completed()

    result = run_v24_training(
        build_v24_training_spec(data_yaml, checkpoint, runs),
        yolo_executable=yolo,
        dataset_manifest=manifest,
        output_manifest=output_manifest,
        started_lock=lock,
        source_commit="a" * 40,
        expected_dataset_sha256=_sha(manifest),
        expected_initializer_sha256=_sha(checkpoint),
        executor=executor,
    )

    assert result["status"] == "V24_TRAINING_COMPLETED"
    assert len(result["best_pt_sha256"]) == 64
    assert len(result["results_csv_sha256"]) == 64
    assert len(calls) == 1
    assert lock.stat().st_mode & 0o777 == 0o600
    assert output_manifest.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        run_v24_training(
            build_v24_training_spec(data_yaml, checkpoint, runs),
            yolo_executable=yolo,
            dataset_manifest=manifest,
            output_manifest=tmp_path / "second.private.json",
            started_lock=lock,
            source_commit="a" * 40,
            expected_dataset_sha256=_sha(manifest),
            expected_initializer_sha256=_sha(checkpoint),
            executor=executor,
        )
    assert len(calls) == 1


def test_v24_training_rejects_input_pin_mismatch_before_claim(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    data_yaml = dataset / "data.yaml"
    data_yaml.write_text("data")
    manifest = dataset / "manifest.private.json"
    manifest.write_text('{"schema":"yolo26n-owner-dataset-v24"}')
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    yolo = tmp_path / "yolo"
    yolo.write_text("runner")
    lock = tmp_path / ".locks/warm-start.started.private.json"

    with pytest.raises(ValueError, match="dataset manifest SHA"):
        run_v24_training(
            build_v24_training_spec(data_yaml, checkpoint, tmp_path / "runs"),
            yolo_executable=yolo,
            dataset_manifest=manifest,
            output_manifest=tmp_path / "output.private.json",
            started_lock=lock,
            source_commit="a" * 40,
            expected_dataset_sha256="0" * 64,
            expected_initializer_sha256=_sha(checkpoint),
            executor=lambda *_args, **_kwargs: None,
        )
    assert not lock.exists()

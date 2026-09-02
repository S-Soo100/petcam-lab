import json
from pathlib import Path

import pytest

from scripts.run_yolo26n_v22_training import (
    TrainingSpec,
    build_training_command,
    build_training_specs,
    run_training,
)


def test_training_specs_freeze_identical_data_and_different_initializers(
    tmp_path: Path,
):
    data_yaml = tmp_path / "dataset/data.yaml"
    warm = tmp_path / "v21-best.pt"
    clean = tmp_path / "yolo26n.pt"
    specs = build_training_specs(
        data_yaml=data_yaml,
        warm_initializer=warm,
        clean_initializer=clean,
        runs_dir=tmp_path / "runs",
        seed=26,
    )

    assert specs["warm-start"].epochs == 60
    assert specs["warm-start"].patience == 15
    assert specs["clean-reference"].epochs == 100
    assert specs["clean-reference"].patience == 20
    assert specs["warm-start"].lr0 == 0.001
    assert specs["clean-reference"].lr0 == 0.01
    assert {spec.data_yaml for spec in specs.values()} == {data_yaml}
    assert {spec.imgsz for spec in specs.values()} == {960}
    assert {spec.batch for spec in specs.values()} == {2}
    assert {spec.device for spec in specs.values()} == {"mps"}
    assert {spec.workers for spec in specs.values()} == {0}
    assert {spec.seed for spec in specs.values()} == {26}
    assert specs["warm-start"].initializer == warm
    assert specs["clean-reference"].initializer == clean


def test_training_command_is_fail_closed_and_uses_one_frozen_split(tmp_path: Path):
    spec = TrainingSpec(
        name="warm-start",
        initializer=tmp_path / "best.pt",
        data_yaml=tmp_path / "data.yaml",
        runs_dir=tmp_path / "runs",
        epochs=60,
        patience=15,
        lr0=0.001,
    )

    command = build_training_command(spec, yolo_executable=Path("/venv/bin/yolo"))

    assert command[:3] == ["/venv/bin/yolo", "detect", "train"]
    assert f"model={spec.initializer}" in command
    assert f"data={spec.data_yaml}" in command
    assert "epochs=60" in command
    assert "patience=15" in command
    assert "optimizer=AdamW" in command
    assert "lr0=0.001" in command
    assert "imgsz=960" in command
    assert "batch=2" in command
    assert "device=mps" in command
    assert "workers=0" in command
    assert "seed=26" in command
    assert "deterministic=True" in command
    assert "exist_ok=False" in command


class _Completed:
    returncode = 0


def test_run_training_records_provenance_after_success(tmp_path: Path):
    initializer = tmp_path / "best.pt"
    initializer.write_bytes(b"checkpoint")
    data_yaml = tmp_path / "dataset/data.yaml"
    data_yaml.parent.mkdir()
    data_yaml.write_text("names:\n  0: gecko\n", encoding="utf-8")
    dataset_manifest = tmp_path / "dataset/manifest.private.json"
    dataset_manifest.write_text('{"schema":"yolo26n-owner-dataset-v23"}\n')
    yolo = tmp_path / "venv/yolo"
    yolo.parent.mkdir()
    yolo.write_text("runner")
    output = tmp_path / "run.private.json"
    captured = []

    result = run_training(
        TrainingSpec(
            name="warm-start",
            initializer=initializer,
            data_yaml=data_yaml,
            runs_dir=tmp_path / "runs",
            epochs=60,
            patience=15,
            lr0=0.001,
        ),
        yolo_executable=yolo,
        dataset_manifest=dataset_manifest,
        output_manifest=output,
        executor=lambda command, check: captured.append((command, check)) or _Completed(),
        source_commit="a" * 40,
    )

    saved = json.loads(output.read_text())
    assert saved["schema"] == "yolo26n-v23-training-run-v1"
    assert saved["dataset_schema"] == "yolo26n-owner-dataset-v23"
    assert result == saved
    assert saved["status"] == "V23_TRAINING_COMPLETED"
    assert saved["returncode"] == 0
    assert saved["source_commit"] == "a" * 40
    assert len(saved["initializer_sha256"]) == 64
    assert len(saved["dataset_manifest_sha256"]) == 64
    assert saved["mps_determinism_warning"] is True
    assert captured[0][1] is False


def test_run_training_records_failure_without_publishing_success(tmp_path: Path):
    initializer = tmp_path / "best.pt"
    initializer.write_bytes(b"checkpoint")
    data_yaml = tmp_path / "data.yaml"
    data_yaml.write_text("data")
    dataset_manifest = tmp_path / "manifest.json"
    dataset_manifest.write_text('{"schema":"yolo26n-owner-dataset-v22"}')
    yolo = tmp_path / "yolo"
    yolo.write_text("runner")

    class Failed:
        returncode = 3

    output = tmp_path / "result.json"
    with pytest.raises(RuntimeError, match="exit 3"):
        run_training(
            TrainingSpec(
                name="warm-start",
                initializer=initializer,
                data_yaml=data_yaml,
                runs_dir=tmp_path / "runs",
                epochs=60,
                patience=15,
                lr0=0.001,
            ),
            yolo_executable=yolo,
            dataset_manifest=dataset_manifest,
            output_manifest=output,
            executor=lambda command, check: Failed(),
            source_commit="b" * 40,
        )

    saved = json.loads(output.read_text())
    assert saved["status"] == "V22_TRAINING_FAILED"
    assert saved["returncode"] == 3

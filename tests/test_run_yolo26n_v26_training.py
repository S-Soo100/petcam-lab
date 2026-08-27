from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from scripts.run_yolo26n_v26_training import (
    build_training_command,
    build_v26_training_spec,
    run_v26_training,
)


APPROVED_RUNTIME = {
    "python": "3.12.13",
    "ultralytics": "8.4.118",
    "torch": "2.13.0",
    "torchvision": "0.28.0",
    "numpy": "2.5.2",
    "opencv-python": "5.0.0.93",
    "pillow": "12.3.0",
    "mps_available": True,
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_dataset(tmp_path: Path) -> tuple[Path, Path, Path]:
    dataset = tmp_path / "dataset"
    records: list[dict[str, object]] = []
    for index, split in enumerate(("train", "val"), start=1):
        image = dataset / "images" / split / f"sample-{index}.jpg"
        label = dataset / "labels" / split / f"sample-{index}.txt"
        image.parent.mkdir(parents=True, exist_ok=True)
        label.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(f"image-{index}".encode())
        label.write_text("" if split == "val" else "0 0.5 0.5 0.5 0.5\n")
        records.append(
            {
                "sequence": f"S{index}",
                "split": split,
                "image_path": str(image.relative_to(dataset)),
                "label_path": str(label.relative_to(dataset)),
                "image_sha256": _sha(image),
                "label_sha256": _sha(label),
                "box_count": 0 if split == "val" else 1,
                "positive": split == "train",
                "source_dataset": "test",
            }
        )
    data_yaml = dataset / "data.yaml"
    data_yaml.write_text(
        f"path: {dataset.resolve()}\ntrain: images/train\nval: images/val\nnames:\n  0: gecko\n"
    )
    manifest = dataset / "manifest.private.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "yolo26n-owner-dataset-v26",
                "status": "V26_DATASET_READY",
                "evaluation_tier": "development",
                "source_commit": _head(),
                "builder_sha256": _sha(Path("scripts/build_yolo26n_v26_dataset.py")),
                "image_count": 2,
                "active_image_count": 2,
                "active_split_counts": {"train": 1, "val": 1},
                "regression_split_counts": {},
                "data_yaml_sha256": _sha(data_yaml),
                "records": records,
            },
            sort_keys=True,
        )
    )
    initializer = tmp_path / "v25.pt"
    initializer.write_bytes(b"checkpoint")
    return manifest, data_yaml, initializer


def _run(
    tmp_path: Path,
    *,
    manifest: Path,
    data_yaml: Path,
    initializer: Path,
    source_commit: str,
    executor,
    runtime: dict[str, object] | None = None,
    expected_yolo_sha256: str | None = None,
) -> dict[str, object]:
    yolo = tmp_path / "runtime/bin/yolo"
    yolo.parent.mkdir(parents=True, exist_ok=True)
    if not yolo.exists():
        yolo.write_text("#!/approved/runtime/bin/python\n")
    spec = build_v26_training_spec(
        "warm-start", 27, initializer, data_yaml, tmp_path / "runs"
    )
    return run_v26_training(
        spec,
        yolo_executable=yolo,
        dataset_manifest=manifest,
        output_manifest=tmp_path / "run.private.json",
        started_lock=tmp_path / "started.private.json",
        source_commit=source_commit,
        expected_dataset_sha256=_sha(manifest),
        expected_initializer_sha256=_sha(initializer),
        expected_runner_sha256=_sha(Path("scripts/run_yolo26n_v26_training.py")),
        expected_yolo_executable_sha256=expected_yolo_sha256 or _sha(yolo),
        runtime_probe=lambda _path: dict(runtime or APPROVED_RUNTIME),
        executor=executor,
    )


def test_exact_six_candidate_specs_share_one_recipe(tmp_path: Path) -> None:
    specs = [
        build_v26_training_spec(
            candidate,
            seed,
            tmp_path / f"{candidate}.pt",
            tmp_path / "data.yaml",
            tmp_path / "runs",
        )
        for candidate in ("warm-start", "clean-reference")
        for seed in (26, 27, 28)
    ]
    assert [spec.run_name for spec in specs] == [
        "warm-start-s26",
        "warm-start-s27",
        "warm-start-s28",
        "clean-reference-s26",
        "clean-reference-s27",
        "clean-reference-s28",
    ]
    for spec in specs:
        assert (spec.epochs, spec.patience, spec.lr0) == (100, 20, 0.001)
        command = build_training_command(
            spec, yolo_executable=Path("/venv/bin/yolo")
        )
        for item in (
            "epochs=100",
            "patience=20",
            "lr0=0.001",
            "optimizer=AdamW",
            "imgsz=960",
            "batch=2",
            "device=mps",
            "workers=0",
            f"seed={spec.seed}",
            "exist_ok=False",
        ):
            assert item in command


def test_invalid_candidate_or_seed_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_v26_training_spec(
            "other", 26, tmp_path / "x.pt", tmp_path / "data.yaml", tmp_path / "runs"
        )
    with pytest.raises(ValueError):
        build_v26_training_spec(
            "warm-start",
            29,
            tmp_path / "x.pt",
            tmp_path / "data.yaml",
            tmp_path / "runs",
        )


def test_training_writes_pinned_completion_manifest(tmp_path: Path) -> None:
    manifest, data_yaml, initializer = _write_dataset(tmp_path)
    runs = tmp_path / "runs"

    def executor(*_args: object, **_kwargs: object) -> CompletedProcess[bytes]:
        output = runs / "warm-start-s27"
        (output / "weights").mkdir(parents=True)
        (output / "weights" / "best.pt").write_bytes(b"best")
        (output / "results.csv").write_text("epoch,metric\n1,0.5\n")
        return CompletedProcess([], 0)

    result = _run(
        tmp_path,
        manifest=manifest,
        data_yaml=data_yaml,
        initializer=initializer,
        source_commit=_head(),
        executor=executor,
    )

    assert result["status"] == "V26_TRAINING_COMPLETED"
    assert result["run_name"] == "warm-start-s27"
    assert result["runtime_versions"] == APPROVED_RUNTIME
    assert result["yolo_executable_sha256"] == _sha(tmp_path / "runtime/bin/yolo")
    assert (tmp_path / "started.private.json").is_file()
    assert (tmp_path / "run.private.json").is_file()


@pytest.mark.parametrize("tampered", ["data-yaml", "image", "label"])
def test_training_rejects_tampered_dataset_before_executor(
    tmp_path: Path, tampered: str
) -> None:
    manifest, data_yaml, initializer = _write_dataset(tmp_path)
    dataset = manifest.parent
    payload = json.loads(manifest.read_text())
    if tampered == "data-yaml":
        data_yaml.write_text(data_yaml.read_text() + "# drift\n")
    elif tampered == "image":
        (dataset / payload["records"][0]["image_path"]).write_bytes(b"tampered-image")
    else:
        (dataset / payload["records"][0]["label_path"]).write_bytes(b"tampered-label")
    called = False

    def executor(*_args: object, **_kwargs: object) -> CompletedProcess[bytes]:
        nonlocal called
        called = True
        return CompletedProcess([], 0)

    with pytest.raises(ValueError, match="data.yaml SHA|image SHA|label SHA"):
        _run(
            tmp_path,
            manifest=manifest,
            data_yaml=data_yaml,
            initializer=initializer,
            source_commit=_head(),
            executor=executor,
        )
    assert not called
    assert not (tmp_path / "started.private.json").exists()


def test_training_rejects_wrong_source_commit_before_executor(tmp_path: Path) -> None:
    manifest, data_yaml, initializer = _write_dataset(tmp_path)
    called = False

    def executor(*_args: object, **_kwargs: object) -> CompletedProcess[bytes]:
        nonlocal called
        called = True
        return CompletedProcess([], 0)

    with pytest.raises(ValueError, match="source commit"):
        _run(
            tmp_path,
            manifest=manifest,
            data_yaml=data_yaml,
            initializer=initializer,
            source_commit="0" * 40,
            executor=executor,
        )
    assert not called
    assert not (tmp_path / "started.private.json").exists()


def test_training_rejects_dataset_built_by_other_source_before_executor(
    tmp_path: Path,
) -> None:
    manifest, data_yaml, initializer = _write_dataset(tmp_path)
    payload = json.loads(manifest.read_text())
    payload["builder_sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload, sort_keys=True))
    called = False

    def executor(*_args: object, **_kwargs: object) -> CompletedProcess[bytes]:
        nonlocal called
        called = True
        return CompletedProcess([], 0)

    with pytest.raises(ValueError, match="dataset source/builder"):
        _run(
            tmp_path,
            manifest=manifest,
            data_yaml=data_yaml,
            initializer=initializer,
            source_commit=_head(),
            executor=executor,
        )
    assert not called


@pytest.mark.parametrize(
    ("expected_yolo_sha256", "runtime", "message"),
    [
        ("f" * 64, APPROVED_RUNTIME, "yolo executable"),
        (None, {**APPROVED_RUNTIME, "mps_available": False}, "runtime"),
        (None, {**APPROVED_RUNTIME, "torch": "2.12.0"}, "runtime"),
    ],
)
def test_training_rejects_unpinned_yolo_or_runtime_before_executor(
    tmp_path: Path,
    expected_yolo_sha256: str | None,
    runtime: dict[str, object],
    message: str,
) -> None:
    manifest, data_yaml, initializer = _write_dataset(tmp_path)
    called = False

    def executor(*_args: object, **_kwargs: object) -> CompletedProcess[bytes]:
        nonlocal called
        called = True
        return CompletedProcess([], 0)

    with pytest.raises(ValueError, match=message):
        _run(
            tmp_path,
            manifest=manifest,
            data_yaml=data_yaml,
            initializer=initializer,
            source_commit=_head(),
            executor=executor,
            runtime=runtime,
            expected_yolo_sha256=expected_yolo_sha256,
        )
    assert not called
    assert not (tmp_path / "started.private.json").exists()

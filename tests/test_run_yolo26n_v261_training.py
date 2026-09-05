from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.run_yolo26n_v261_training import (
    build_training_command,
    build_v261_training_spec,
    run_v261_training,
    validate_training_dataset,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dataset(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "dataset"
    root.mkdir(parents=True)
    records = []
    for split, token in (("train", "a"), ("val", "c")):
        (root / "images" / split).mkdir(parents=True)
        (root / "labels" / split).mkdir(parents=True)
        image = root / "images" / split / f"{token}.jpg"
        label = root / "labels" / split / f"{token}.txt"
        image.write_bytes(f"image-{token}".encode())
        label.write_text("0 0.5 0.5 0.2 0.2\n")
        records.append(
            {
                "split": split,
                "image_path": str(image.relative_to(root)),
                "label_path": str(label.relative_to(root)),
                "image_sha256": _sha(image),
                "label_sha256": _sha(label),
                "box_count": 1,
            }
        )
    data = root / "data.yaml"
    data.write_text(
        f"path: {root.resolve()}\n"
        "train: images/train\nval: images/val\nnames:\n  0: gecko\n"
    )
    manifest = root / "manifest.private.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "yolo26n-owner-dataset-v261",
                "status": "V261_DATASET_READY",
                "source_commit": "b" * 40,
                "data_yaml_sha256": _sha(data),
                "records": records,
            }
        )
    )
    return manifest, data


def test_build_training_command_is_matched_except_initializer(tmp_path: Path) -> None:
    warm = build_v261_training_spec(
        candidate="warm-start",
        seed=26,
        initializer=tmp_path / "warm.pt",
        data_yaml=tmp_path / "data.yaml",
        runs_dir=tmp_path / "runs",
    )
    clean = build_v261_training_spec(
        candidate="clean-reference",
        seed=26,
        initializer=tmp_path / "clean.pt",
        data_yaml=tmp_path / "data.yaml",
        runs_dir=tmp_path / "runs",
    )
    warm_command = build_training_command(warm, yolo_executable=tmp_path / "yolo")
    clean_command = build_training_command(clean, yolo_executable=tmp_path / "yolo")

    assert warm_command[0] == str(tmp_path / "yolo")
    for expected in (
        "epochs=100",
        "patience=20",
        "optimizer=AdamW",
        "lr0=0.001",
        "imgsz=960",
        "batch=2",
        "workers=0",
        "device=mps",
        "seed=26",
        "deterministic=True",
        "exist_ok=False",
    ):
        assert expected in warm_command
    assert [
        item for item in warm_command if not item.startswith(("model=", "name="))
    ] == [item for item in clean_command if not item.startswith(("model=", "name="))]


@pytest.mark.parametrize("candidate", ["other", "baseline-v26"])
def test_training_spec_rejects_unapproved_candidate(
    tmp_path: Path, candidate: str
) -> None:
    with pytest.raises(ValueError, match="candidate"):
        build_v261_training_spec(
            candidate=candidate,
            seed=26,
            initializer=tmp_path / "x",
            data_yaml=tmp_path / "d",
            runs_dir=tmp_path / "r",
        )


def test_training_spec_rejects_unapproved_seed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="seed"):
        build_v261_training_spec(
            candidate="warm-start",
            seed=25,
            initializer=tmp_path / "x",
            data_yaml=tmp_path / "d",
            runs_dir=tmp_path / "r",
        )


def test_validate_training_dataset_rejects_manifest_or_yaml_drift(
    tmp_path: Path,
) -> None:
    manifest, data = _dataset(tmp_path)
    payload = validate_training_dataset(
        manifest, expected_manifest_sha256=_sha(manifest)
    )
    assert payload["status"] == "V261_DATASET_READY"
    data.write_text("changed")
    with pytest.raises(ValueError, match="data.yaml SHA mismatch"):
        validate_training_dataset(manifest, expected_manifest_sha256=_sha(manifest))


def test_run_training_writes_started_lock_and_completion_manifest(
    tmp_path: Path,
) -> None:
    manifest, data = _dataset(tmp_path)
    initializer = tmp_path / "warm.pt"
    yolo = tmp_path / "yolo"
    initializer.write_bytes(b"weights")
    yolo.write_bytes(b"binary")
    spec = build_v261_training_spec(
        candidate="warm-start",
        seed=26,
        initializer=initializer,
        data_yaml=data,
        runs_dir=tmp_path / "runs",
    )
    started = tmp_path / "locks" / "warm-start-s26.started.private.json"
    completion = tmp_path / "manifests" / "warm-start-s26.private.json"

    def executor(command: list[str]) -> SimpleNamespace:
        assert command == build_training_command(spec, yolo_executable=yolo)
        run = spec.runs_dir / spec.run_name
        (run / "weights").mkdir(parents=True)
        (run / "results.csv").write_text(
            "epoch,metrics/precision(B),metrics/recall(B)\n1,0.8,0.9\n"
        )
        (run / "weights" / "best.pt").write_bytes(b"best")
        return SimpleNamespace(returncode=0)

    result = run_v261_training(
        spec=spec,
        dataset_manifest_path=manifest,
        run_manifest_path=completion,
        started_lock_path=started,
        yolo_executable=yolo,
        source_commit="b" * 40,
        dataset_sha256=_sha(manifest),
        initializer_sha256=_sha(initializer),
        runner_sha256=_sha(Path(run_v261_training.__code__.co_filename)),
        yolo_executable_sha256=_sha(yolo),
        executor=executor,
        repository_head=lambda: "b" * 40,
        repository_status=lambda: "",
    )

    assert started.is_file()
    assert result["status"] == "V261_TRAINING_COMPLETE"
    assert result["candidate"] == "warm-start"
    assert result["seed"] == 26
    assert json.loads(completion.read_text()) == result


def test_run_training_refuses_existing_lock(tmp_path: Path) -> None:
    manifest, data = _dataset(tmp_path)
    initializer = tmp_path / "warm.pt"
    yolo = tmp_path / "yolo"
    initializer.write_bytes(b"weights")
    yolo.write_bytes(b"binary")
    spec = build_v261_training_spec(
        candidate="warm-start",
        seed=26,
        initializer=initializer,
        data_yaml=data,
        runs_dir=tmp_path / "runs",
    )
    started = tmp_path / "started.json"
    started.write_text("{}")
    with pytest.raises(FileExistsError):
        run_v261_training(
            spec=spec,
            dataset_manifest_path=manifest,
            run_manifest_path=tmp_path / "completion.json",
            started_lock_path=started,
            yolo_executable=yolo,
            source_commit="b" * 40,
            dataset_sha256=_sha(manifest),
            initializer_sha256=_sha(initializer),
            runner_sha256=_sha(Path(run_v261_training.__code__.co_filename)),
            yolo_executable_sha256=_sha(yolo),
            executor=lambda _: SimpleNamespace(returncode=0),
            repository_head=lambda: "b" * 40,
            repository_status=lambda: "",
        )


def test_run_training_rejects_dirty_repository(tmp_path: Path) -> None:
    manifest, data = _dataset(tmp_path)
    initializer = tmp_path / "warm.pt"
    yolo = tmp_path / "yolo"
    initializer.write_bytes(b"weights")
    yolo.write_bytes(b"binary")
    spec = build_v261_training_spec(
        candidate="warm-start",
        seed=26,
        initializer=initializer,
        data_yaml=data,
        runs_dir=tmp_path / "runs",
    )
    with pytest.raises(ValueError, match="worktree must be clean"):
        run_v261_training(
            spec=spec,
            dataset_manifest_path=manifest,
            run_manifest_path=tmp_path / "completion.json",
            started_lock_path=tmp_path / "started.json",
            yolo_executable=yolo,
            source_commit="b" * 40,
            dataset_sha256=_sha(manifest),
            initializer_sha256=_sha(initializer),
            runner_sha256=_sha(Path(run_v261_training.__code__.co_filename)),
            yolo_executable_sha256=_sha(yolo),
            executor=lambda _: SimpleNamespace(returncode=0),
            repository_head=lambda: "b" * 40,
            repository_status=lambda: " M changed.py",
        )


def test_run_training_failure_keeps_lock_without_completion(tmp_path: Path) -> None:
    manifest, data = _dataset(tmp_path)
    initializer = tmp_path / "warm.pt"
    yolo = tmp_path / "yolo"
    initializer.write_bytes(b"weights")
    yolo.write_bytes(b"binary")
    spec = build_v261_training_spec(
        candidate="warm-start",
        seed=26,
        initializer=initializer,
        data_yaml=data,
        runs_dir=tmp_path / "runs",
    )
    started = tmp_path / "started.json"
    completion = tmp_path / "completion.json"
    with pytest.raises(RuntimeError, match="return code 9"):
        run_v261_training(
            spec=spec,
            dataset_manifest_path=manifest,
            run_manifest_path=completion,
            started_lock_path=started,
            yolo_executable=yolo,
            source_commit="b" * 40,
            dataset_sha256=_sha(manifest),
            initializer_sha256=_sha(initializer),
            runner_sha256=_sha(Path(run_v261_training.__code__.co_filename)),
            yolo_executable_sha256=_sha(yolo),
            executor=lambda _: SimpleNamespace(returncode=9),
            repository_head=lambda: "b" * 40,
            repository_status=lambda: "",
        )
    assert started.is_file()
    assert not completion.exists()


def test_validate_training_dataset_rejects_image_label_or_file_set_drift(
    tmp_path: Path,
) -> None:
    manifest, _ = _dataset(tmp_path)
    payload = json.loads(manifest.read_text())
    image = manifest.parent / payload["records"][0]["image_path"]
    image.write_bytes(b"mutated")
    with pytest.raises(ValueError, match="dataset byte drift"):
        validate_training_dataset(manifest, expected_manifest_sha256=_sha(manifest))

    manifest, _ = _dataset(tmp_path / "second")
    (manifest.parent / "images" / "train" / "extra.jpg").write_bytes(b"extra")
    with pytest.raises(ValueError, match="dataset file set drift"):
        validate_training_dataset(manifest, expected_manifest_sha256=_sha(manifest))


def test_run_training_revalidates_dataset_after_executor(tmp_path: Path) -> None:
    manifest, data = _dataset(tmp_path)
    initializer = tmp_path / "warm.pt"
    yolo = tmp_path / "yolo"
    initializer.write_bytes(b"weights")
    yolo.write_bytes(b"binary")
    spec = build_v261_training_spec(
        candidate="warm-start",
        seed=26,
        initializer=initializer,
        data_yaml=data,
        runs_dir=tmp_path / "runs",
    )
    completion = tmp_path / "completion.json"

    def executor(_: list[str]) -> SimpleNamespace:
        payload = json.loads(manifest.read_text())
        (manifest.parent / payload["records"][0]["image_path"]).write_bytes(b"drift")
        run = spec.runs_dir / spec.run_name
        (run / "weights").mkdir(parents=True)
        (run / "results.csv").write_text("epoch\n1\n")
        (run / "weights" / "best.pt").write_bytes(b"best")
        return SimpleNamespace(returncode=0)

    with pytest.raises(ValueError, match="dataset byte drift"):
        run_v261_training(
            spec=spec,
            dataset_manifest_path=manifest,
            run_manifest_path=completion,
            started_lock_path=tmp_path / "started.json",
            yolo_executable=yolo,
            source_commit="b" * 40,
            dataset_sha256=_sha(manifest),
            initializer_sha256=_sha(initializer),
            runner_sha256=_sha(Path(run_v261_training.__code__.co_filename)),
            yolo_executable_sha256=_sha(yolo),
            executor=executor,
            repository_head=lambda: "b" * 40,
            repository_status=lambda: "",
        )
    assert not completion.exists()

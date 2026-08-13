"""Run the reviewed YOLO26n v2.4 warm-start training exactly once."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class TrainingSpec:
    initializer: Path
    data_yaml: Path
    runs_dir: Path
    name: str = "warm-start"
    epochs: int = 60
    patience: int = 15
    lr0: float = 0.001
    imgsz: int = 960
    batch: int = 2
    device: str = "mps"
    workers: int = 0
    seed: int = 26


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _write_private_new(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)


def build_v24_training_spec(
    data_yaml: Path, initializer: Path, runs_dir: Path
) -> TrainingSpec:
    return TrainingSpec(
        initializer=initializer, data_yaml=data_yaml, runs_dir=runs_dir
    )


def build_training_command(
    spec: TrainingSpec, *, yolo_executable: Path
) -> list[str]:
    return [
        str(yolo_executable),
        "detect",
        "train",
        f"model={spec.initializer}",
        f"data={spec.data_yaml}",
        f"epochs={spec.epochs}",
        f"patience={spec.patience}",
        "optimizer=AdamW",
        f"lr0={spec.lr0}",
        "lrf=0.01",
        f"imgsz={spec.imgsz}",
        f"batch={spec.batch}",
        f"device={spec.device}",
        f"workers={spec.workers}",
        f"seed={spec.seed}",
        "deterministic=True",
        f"project={spec.runs_dir}",
        f"name={spec.name}",
        "exist_ok=False",
        "pretrained=True",
        "val=True",
        "plots=True",
        "hsv_h=0.015",
        "hsv_s=0.7",
        "hsv_v=0.4",
        "degrees=0.0",
        "translate=0.1",
        "scale=0.5",
        "shear=0.0",
        "perspective=0.0",
        "flipud=0.0",
        "fliplr=0.5",
        "mosaic=1.0",
        "mixup=0.0",
        "close_mosaic=10",
    ]


def run_v24_training(
    spec: TrainingSpec,
    *,
    yolo_executable: Path,
    dataset_manifest: Path,
    output_manifest: Path,
    started_lock: Path,
    source_commit: str,
    expected_dataset_sha256: str,
    expected_initializer_sha256: str,
    executor: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, object]:
    if output_manifest.exists():
        raise FileExistsError(output_manifest)
    for path in (spec.initializer, spec.data_yaml, dataset_manifest, yolo_executable):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not _is_sha(source_commit, 40):
        raise ValueError("source commit malformed")
    if not _is_sha(expected_dataset_sha256, 64) or _sha256(dataset_manifest) != expected_dataset_sha256:
        raise ValueError("dataset manifest SHA mismatch")
    if not _is_sha(expected_initializer_sha256, 64) or _sha256(spec.initializer) != expected_initializer_sha256:
        raise ValueError("initializer SHA mismatch")
    dataset = json.loads(dataset_manifest.read_bytes())
    if (
        dataset.get("schema") != "yolo26n-owner-dataset-v24"
        or dataset.get("evaluation_tier") != "development"
        or dataset.get("future_holdout_required") is not True
        or any(dataset.get(key) != 0 for key in ("db_write_count", "r2_write_count", "service_write_count"))
    ):
        raise ValueError("v2.4 dataset contract mismatch")
    run_dir = spec.runs_dir / spec.name
    if run_dir.exists():
        raise FileExistsError(run_dir)

    command = build_training_command(spec, yolo_executable=yolo_executable)
    _write_private_new(
        started_lock,
        {
            "schema": "yolo26n-v24-training-started-lock-v1",
            "status": "V24_TRAINING_STARTED",
            "operation": "warm-start",
            "dataset_manifest_sha256": expected_dataset_sha256,
            "initializer_sha256": expected_initializer_sha256,
            "source_commit": source_commit,
        },
    )
    if _sha256(dataset_manifest) != expected_dataset_sha256 or _sha256(spec.initializer) != expected_initializer_sha256:
        raise ValueError("training input changed after one-shot claim")
    started_at = datetime.now(UTC).isoformat()
    completed = executor(command, check=False)
    finished_at = datetime.now(UTC).isoformat()
    returncode = int(completed.returncode)
    best_pt = run_dir / "weights/best.pt"
    results_csv = run_dir / "results.csv"
    if returncode == 0 and (not best_pt.is_file() or not results_csv.is_file()):
        raise ValueError("successful training outputs missing")
    if _sha256(dataset_manifest) != expected_dataset_sha256 or _sha256(spec.initializer) != expected_initializer_sha256:
        raise ValueError("training input changed during execution")
    result: dict[str, object] = {
        "schema": "yolo26n-v24-training-run-v1",
        "status": "V24_TRAINING_COMPLETED" if returncode == 0 else "V24_TRAINING_FAILED",
        "dataset_schema": "yolo26n-owner-dataset-v24",
        "name": spec.name,
        "source_commit": source_commit,
        "runner_sha256": _sha256(Path(__file__)),
        "yolo_executable_sha256": _sha256(yolo_executable),
        "initializer_sha256": expected_initializer_sha256,
        "dataset_manifest_sha256": expected_dataset_sha256,
        "data_yaml_sha256": _sha256(spec.data_yaml),
        "started_at": started_at,
        "finished_at": finished_at,
        "returncode": returncode,
        "mps_determinism_warning": True,
        "spec": {**asdict(spec), "initializer": str(spec.initializer), "data_yaml": str(spec.data_yaml), "runs_dir": str(spec.runs_dir)},
        "command": command,
        "best_pt_sha256": _sha256(best_pt) if best_pt.is_file() else None,
        "results_csv_sha256": _sha256(results_csv) if results_csv.is_file() else None,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }
    _write_private_new(output_manifest, result)
    if returncode != 0:
        raise RuntimeError(f"training exited with exit {returncode}")
    return result

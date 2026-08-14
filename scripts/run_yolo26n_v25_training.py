"""Run YOLO26n v2.5 warm-start and clean-reference one-shot candidates."""

from __future__ import annotations

import hashlib
import argparse
import importlib.metadata
import json
import os
import platform
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from collections.abc import Sequence
from typing import Callable


@dataclass(frozen=True)
class TrainingSpec:
    candidate: str
    initializer: Path
    data_yaml: Path
    runs_dir: Path
    epochs: int
    patience: int
    lr0: float
    imgsz: int = 960
    batch: int = 2
    device: str = "mps"
    workers: int = 0
    seed: int = 26


def build_v25_training_spec(candidate: str, initializer: Path, data_yaml: Path, runs_dir: Path) -> TrainingSpec:
    recipes = {"warm-start": (60, 15, 0.001), "clean-reference": (100, 20, 0.01)}
    if candidate not in recipes:
        raise ValueError("unknown v2.5 candidate")
    epochs, patience, lr0 = recipes[candidate]
    return TrainingSpec(candidate, initializer, data_yaml, runs_dir, epochs, patience, lr0)


def build_training_command(spec: TrainingSpec, *, yolo_executable: Path) -> list[str]:
    return [
        str(yolo_executable), "detect", "train", f"model={spec.initializer}", f"data={spec.data_yaml}",
        f"epochs={spec.epochs}", f"patience={spec.patience}", "optimizer=AdamW", f"lr0={spec.lr0}",
        "lrf=0.01", f"imgsz={spec.imgsz}", f"batch={spec.batch}", f"device={spec.device}",
        f"workers={spec.workers}", f"seed={spec.seed}", "deterministic=True", f"project={spec.runs_dir}",
        f"name={spec.candidate}", "exist_ok=False", "pretrained=True", "val=True", "plots=True",
        "hsv_h=0.015", "hsv_s=0.7", "hsv_v=0.4", "degrees=0.0", "translate=0.1", "scale=0.5",
        "shear=0.0", "perspective=0.0", "flipud=0.0", "fliplr=0.5", "mosaic=1.0", "mixup=0.0",
        "close_mosaic=10",
    ]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_private_new(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, (json.dumps(value, sort_keys=True) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)


def runtime_version_ledger() -> dict[str, str]:
    names = ("ultralytics", "torch", "torchvision", "numpy", "opencv-python", "pillow")
    result = {"python": platform.python_version()}
    for name in names:
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = "unavailable"
    return result


def run_v25_training(
    spec: TrainingSpec,
    *,
    yolo_executable: Path,
    dataset_manifest: Path,
    output_manifest: Path,
    started_lock: Path,
    source_commit: str,
    expected_dataset_sha256: str,
    expected_initializer_sha256: str,
    expected_runner_sha256: str,
    executor: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, object]:
    runner_sha = _sha(Path(__file__))
    if not all(len(value) == size and all(c in "0123456789abcdef" for c in value) for value, size in ((source_commit, 40), (expected_dataset_sha256, 64), (expected_initializer_sha256, 64), (expected_runner_sha256, 64))):
        raise ValueError("identity pin malformed")
    if _sha(dataset_manifest) != expected_dataset_sha256 or _sha(spec.initializer) != expected_initializer_sha256 or runner_sha != expected_runner_sha256:
        raise ValueError("hard-stop identity mismatch")
    dataset = json.loads(dataset_manifest.read_bytes())
    if dataset.get("schema") != "yolo26n-owner-dataset-v25" or dataset.get("status") != "V25_DATASET_READY" or dataset.get("evaluation_tier") != "development":
        raise ValueError("v2.5 dataset contract mismatch")
    if spec.data_yaml.resolve().parent != dataset_manifest.resolve().parent:
        raise ValueError("training data.yaml must belong to the pinned dataset")
    run_dir = spec.runs_dir / spec.candidate
    if output_manifest.exists() or run_dir.exists():
        raise FileExistsError("candidate output exists")
    _write_private_new(started_lock, {"schema": "yolo26n-v25-training-lock-v1", "status": "V25_TRAINING_STARTED", "candidate": spec.candidate, "dataset_sha256": expected_dataset_sha256, "initializer_sha256": expected_initializer_sha256, "runner_sha256": runner_sha})
    if _sha(dataset_manifest) != expected_dataset_sha256 or _sha(spec.initializer) != expected_initializer_sha256:
        raise ValueError("training input changed after claim")
    completed = executor(build_training_command(spec, yolo_executable=yolo_executable), check=False)
    best = run_dir / "weights/best.pt"
    results = run_dir / "results.csv"
    if completed.returncode == 0 and (not best.is_file() or not results.is_file()):
        raise ValueError("successful training output missing")
    result = {
        "schema": "yolo26n-v25-training-run-v1",
        "status": "V25_TRAINING_COMPLETED" if completed.returncode == 0 else "V25_TRAINING_FAILED",
        "candidate": spec.candidate,
        "source_commit": source_commit,
        "dataset_manifest_sha256": expected_dataset_sha256,
        "initializer_sha256": expected_initializer_sha256,
        "runner_sha256": runner_sha,
        "runtime_versions_warning_only": runtime_version_ledger(),
        "mps_one_shot_not_bitwise_deterministic": True,
        "spec": {**asdict(spec), "initializer": str(spec.initializer), "data_yaml": str(spec.data_yaml), "runs_dir": str(spec.runs_dir)},
        "returncode": int(completed.returncode),
        "best_pt_sha256": _sha(best) if best.is_file() else None,
        "results_csv_sha256": _sha(results) if results.is_file() else None,
        "db_write_count": 0, "r2_write_count": 0, "service_write_count": 0, "deploy_count": 0,
    }
    _write_private_new(output_manifest, result)
    if completed.returncode != 0:
        raise RuntimeError(f"training exited {completed.returncode}")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=("warm-start", "clean-reference"), required=True)
    parser.add_argument("--initializer", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--data-yaml", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--run-manifest", type=Path, required=True)
    parser.add_argument("--started-lock", type=Path, required=True)
    parser.add_argument("--yolo-executable", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--dataset-sha256", required=True)
    parser.add_argument("--initializer-sha256", required=True)
    parser.add_argument("--runner-sha256", required=True)
    args = parser.parse_args(argv)
    spec = build_v25_training_spec(
        args.candidate,
        args.initializer,
        args.data_yaml,
        args.runs_dir,
    )
    result = run_v25_training(
        spec,
        yolo_executable=args.yolo_executable,
        dataset_manifest=args.dataset_manifest,
        output_manifest=args.run_manifest,
        started_lock=args.started_lock,
        source_commit=args.source_commit,
        expected_dataset_sha256=args.dataset_sha256,
        expected_initializer_sha256=args.initializer_sha256,
        expected_runner_sha256=args.runner_sha256,
    )
    print(result["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

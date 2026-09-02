"""Run reproducible YOLO26n v2.2 development training candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Sequence


@dataclass(frozen=True)
class TrainingSpec:
    name: str
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha(value: str, *, length: int) -> bool:
    return (
        len(value) == length
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _write_private_new(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def build_training_specs(
    *,
    data_yaml: Path,
    warm_initializer: Path,
    clean_initializer: Path,
    runs_dir: Path,
    seed: int = 26,
) -> dict[str, TrainingSpec]:
    return {
        "warm-start": TrainingSpec(
            name="warm-start",
            initializer=warm_initializer,
            data_yaml=data_yaml,
            runs_dir=runs_dir,
            epochs=60,
            patience=15,
            lr0=0.001,
            seed=seed,
        ),
        "clean-reference": TrainingSpec(
            name="clean-reference",
            initializer=clean_initializer,
            data_yaml=data_yaml,
            runs_dir=runs_dir,
            epochs=100,
            patience=20,
            lr0=0.01,
            seed=seed,
        ),
    }


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


def run_training(
    spec: TrainingSpec,
    *,
    yolo_executable: Path,
    dataset_manifest: Path,
    output_manifest: Path,
    source_commit: str,
    executor: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, object]:
    if output_manifest.exists():
        raise FileExistsError(output_manifest)
    for path in (
        spec.initializer,
        spec.data_yaml,
        dataset_manifest,
        yolo_executable,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not _is_sha(source_commit, length=40):
        raise ValueError("source commit must be a lowercase 40-character SHA")
    dataset_payload = json.loads(dataset_manifest.read_bytes())
    dataset_schema = dataset_payload.get("schema")
    if dataset_schema not in {"yolo26n-owner-dataset-v22", "yolo26n-owner-dataset-v23"}:
        raise ValueError("unsupported dataset schema")
    run_dir = spec.runs_dir / spec.name
    if run_dir.exists():
        raise FileExistsError(run_dir)

    command = build_training_command(spec, yolo_executable=yolo_executable)
    started_at = datetime.now(UTC).isoformat()
    completed = executor(command, check=False)
    finished_at = datetime.now(UTC).isoformat()
    returncode = int(completed.returncode)
    version = "V23" if dataset_schema == "yolo26n-owner-dataset-v23" else "V22"
    result: dict[str, object] = {
        "schema": (
            "yolo26n-v23-training-run-v1"
            if dataset_schema == "yolo26n-owner-dataset-v23"
            else "yolo26n-v22-training-run-v1"
        ),
        "dataset_schema": dataset_schema,
        "status": (
            f"{version}_TRAINING_COMPLETED"
            if returncode == 0
            else f"{version}_TRAINING_FAILED"
        ),
        "name": spec.name,
        "source_commit": source_commit,
        "runner_sha256": _sha256(Path(__file__)),
        "yolo_executable_sha256": _sha256(yolo_executable),
        "initializer_sha256": _sha256(spec.initializer),
        "dataset_manifest_sha256": _sha256(dataset_manifest),
        "data_yaml_sha256": _sha256(spec.data_yaml),
        "started_at": started_at,
        "finished_at": finished_at,
        "returncode": returncode,
        "mps_determinism_warning": spec.device == "mps",
        "spec": {
            **asdict(spec),
            "initializer": str(spec.initializer),
            "data_yaml": str(spec.data_yaml),
            "runs_dir": str(spec.runs_dir),
        },
        "command": command,
    }
    _write_private_new(output_manifest, result)
    if returncode != 0:
        raise RuntimeError(f"training exited with exit {returncode}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", choices=("warm-start", "clean-reference"), required=True)
    parser.add_argument("--data-yaml", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--warm-initializer", type=Path, required=True)
    parser.add_argument("--clean-initializer", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--yolo-executable", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--seed", type=int, default=26)
    args = parser.parse_args()
    specs = build_training_specs(
        data_yaml=args.data_yaml,
        warm_initializer=args.warm_initializer,
        clean_initializer=args.clean_initializer,
        runs_dir=args.runs_dir,
        seed=args.seed,
    )
    result = run_training(
        specs[args.candidate],
        yolo_executable=args.yolo_executable,
        dataset_manifest=args.dataset_manifest,
        output_manifest=args.output_manifest,
        source_commit=args.source_commit,
    )
    print(
        json.dumps(
            {"status": result["status"], "name": result["name"]},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

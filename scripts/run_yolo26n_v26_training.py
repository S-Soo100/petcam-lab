"""Run one pinned YOLO26n v2.6 candidate/seed without overwriting outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


_APPROVED_RUNTIME: dict[str, object] = {
    "python": "3.12.13",
    "ultralytics": "8.4.118",
    "torch": "2.13.0",
    "torchvision": "0.28.0",
    "numpy": "2.5.2",
    "opencv-python": "5.0.0.93",
    "pillow": "12.3.0",
    "mps_available": True,
}


@dataclass(frozen=True)
class TrainingSpec:
    candidate: str
    seed: int
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

    @property
    def run_name(self) -> str:
        return f"{self.candidate}-s{self.seed}"


def build_v26_training_spec(
    candidate: str,
    seed: int,
    initializer: Path,
    data_yaml: Path,
    runs_dir: Path,
) -> TrainingSpec:
    if candidate not in {"warm-start", "clean-reference"}:
        raise ValueError("unknown v2.6 candidate")
    if seed not in {26, 27, 28}:
        raise ValueError("v2.6 seed is not approved")
    return TrainingSpec(
        candidate, seed, initializer, data_yaml, runs_dir, 100, 20, 0.001
    )


def build_training_command(spec: TrainingSpec, *, yolo_executable: Path) -> list[str]:
    return [
        str(yolo_executable), "detect", "train",
        f"model={spec.initializer}", f"data={spec.data_yaml}",
        f"epochs={spec.epochs}", f"patience={spec.patience}",
        "optimizer=AdamW", f"lr0={spec.lr0}", "lrf=0.01",
        f"imgsz={spec.imgsz}", f"batch={spec.batch}", f"device={spec.device}",
        f"workers={spec.workers}", f"seed={spec.seed}", "deterministic=True",
        f"project={spec.runs_dir}", f"name={spec.run_name}", "exist_ok=False",
        "pretrained=True", "val=True", "plots=True",
        "hsv_h=0.015", "hsv_s=0.7", "hsv_v=0.4", "degrees=0.0",
        "translate=0.1", "scale=0.5", "shear=0.0", "perspective=0.0",
        "flipud=0.0", "fliplr=0.5", "mosaic=1.0", "mixup=0.0",
        "close_mosaic=10",
    ]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sha(value: object, length: int = 64) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _repository_head() -> str:
    completed = subprocess.run(
        ["git", "-C", str(Path(__file__).resolve().parent.parent), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    head = completed.stdout.strip()
    if not _is_sha(head, 40):
        raise ValueError("repository HEAD malformed")
    return head


def _record_path(dataset_root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"dataset {label} path malformed")
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"dataset {label} path must be relative")
    resolved = (dataset_root / relative).resolve()
    if not resolved.is_relative_to(dataset_root.resolve()) or not resolved.is_file():
        raise ValueError(f"dataset {label} path escaped or missing")
    return resolved


def _validate_training_dataset(
    dataset: Mapping[str, object], *, dataset_root: Path, data_yaml: Path
) -> None:
    records = dataset.get("records")
    active_counts = dataset.get("active_split_counts")
    regression_counts = dataset.get("regression_split_counts")
    if (
        not isinstance(records, list)
        or type(dataset.get("image_count")) is not int
        or dataset.get("image_count") != len(records)
        or not isinstance(active_counts, Mapping)
        or not isinstance(regression_counts, Mapping)
    ):
        raise ValueError("v2.6 dataset record/count contract mismatch")
    if data_yaml.resolve().parent != dataset_root.resolve():
        raise ValueError("training data.yaml must belong to the pinned dataset")
    expected_data_yaml_sha = dataset.get("data_yaml_sha256")
    if not _is_sha(expected_data_yaml_sha) or _sha(data_yaml) != expected_data_yaml_sha:
        raise ValueError("data.yaml SHA mismatch")

    split_counts: Counter[str] = Counter()
    image_paths: set[Path] = set()
    label_paths: set[Path] = set()
    for raw in records:
        if not isinstance(raw, Mapping):
            raise ValueError("dataset record malformed")
        split = raw.get("split")
        if not isinstance(split, str) or not split:
            raise ValueError("dataset split malformed")
        image_path = _record_path(dataset_root, raw.get("image_path"), "image")
        label_path = _record_path(dataset_root, raw.get("label_path"), "label")
        if image_path in image_paths or label_path in label_paths:
            raise ValueError("dataset record path duplicated")
        image_paths.add(image_path)
        label_paths.add(label_path)
        if not _is_sha(raw.get("image_sha256")) or _sha(image_path) != raw.get("image_sha256"):
            raise ValueError("dataset image SHA mismatch")
        if not _is_sha(raw.get("label_sha256")) or _sha(label_path) != raw.get("label_sha256"):
            raise ValueError("dataset label SHA mismatch")
        box_count = raw.get("box_count")
        if type(box_count) is not int or box_count < 0:
            raise ValueError("dataset box count malformed")
        label_lines = [line for line in label_path.read_text().splitlines() if line.strip()]
        if len(label_lines) != box_count:
            raise ValueError("dataset label box count mismatch")
        split_counts[split] += 1

    normalized_active = {str(key): value for key, value in active_counts.items()}
    normalized_regression = {str(key): value for key, value in regression_counts.items()}
    if (
        set(normalized_active) & set(normalized_regression)
        or any(
            not key or type(value) is not int or value < 0
            for counts in (normalized_active, normalized_regression)
            for key, value in counts.items()
        )
    ):
        raise ValueError("v2.6 dataset split count contract malformed")
    expected_counts = Counter({**normalized_active, **normalized_regression})
    if split_counts != expected_counts:
        raise ValueError("v2.6 dataset split counts mismatch")
    if dataset.get("active_image_count") != sum(normalized_active.values()):
        raise ValueError("v2.6 active image count mismatch")
    actual_images = {path.resolve() for path in (dataset_root / "images").rglob("*") if path.is_file()}
    actual_labels = {path.resolve() for path in (dataset_root / "labels").rglob("*") if path.is_file()}
    if actual_images != image_paths or actual_labels != label_paths:
        raise ValueError("v2.6 dataset file count mismatch")


def _write_private_new(path: Path, value: MappingLike) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, (json.dumps(value, sort_keys=True) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)


MappingLike = dict[str, object]


def probe_yolo_runtime(yolo_executable: Path) -> dict[str, object]:
    """Read the YOLO shebang and probe versions inside that exact Python runtime."""
    try:
        first_line = yolo_executable.read_bytes().splitlines()[0].decode("utf-8")
    except (OSError, IndexError, UnicodeDecodeError) as error:
        raise ValueError("yolo executable shebang malformed") from error
    if not first_line.startswith("#!"):
        raise ValueError("yolo executable shebang malformed")
    runtime_python = Path(first_line[2:])
    if not runtime_python.is_absolute() or not runtime_python.is_file():
        raise ValueError("yolo runtime Python is missing")
    probe = (
        "import importlib.metadata as m,json,platform,torch;"
        "print(json.dumps({"
        "'python':platform.python_version(),"
        "'ultralytics':m.version('ultralytics'),"
        "'torch':m.version('torch'),"
        "'torchvision':m.version('torchvision'),"
        "'numpy':m.version('numpy'),"
        "'opencv-python':m.version('opencv-python'),"
        "'pillow':m.version('pillow'),"
        "'mps_available':torch.backends.mps.is_available()"
        "},sort_keys=True))"
    )
    completed = subprocess.run(
        [str(runtime_python), "-c", probe],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("yolo runtime probe output malformed") from error
    if not isinstance(value, dict):
        raise ValueError("yolo runtime probe output malformed")
    return value


def _validate_runtime(value: Mapping[str, object]) -> dict[str, object]:
    normalized = dict(value)
    if normalized != _APPROVED_RUNTIME:
        raise ValueError("yolo runtime does not match approved contract")
    return normalized


def _validate_dataset_builder_identity(
    dataset: Mapping[str, object], *, source_commit: str
) -> None:
    builder = Path(__file__).with_name("build_yolo26n_v26_dataset.py")
    if (
        dataset.get("source_commit") != source_commit
        or dataset.get("builder_sha256") != _sha(builder)
    ):
        raise ValueError("dataset source/builder identity mismatch")


def run_v26_training(
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
    expected_yolo_executable_sha256: str,
    runtime_probe: Callable[[Path], Mapping[str, object]] = probe_yolo_runtime,
    executor: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, object]:
    runner_sha = _sha(Path(__file__))
    pins = (
        (source_commit, 40),
        (expected_dataset_sha256, 64),
        (expected_initializer_sha256, 64),
        (expected_runner_sha256, 64),
        (expected_yolo_executable_sha256, 64),
    )
    if not all(_is_sha(value, size) for value, size in pins):
        raise ValueError("identity pin malformed")
    if (
        _sha(dataset_manifest) != expected_dataset_sha256
        or _sha(spec.initializer) != expected_initializer_sha256
        or runner_sha != expected_runner_sha256
    ):
        raise ValueError("hard-stop identity mismatch")
    if _sha(yolo_executable) != expected_yolo_executable_sha256:
        raise ValueError("yolo executable SHA mismatch")
    runtime_versions = _validate_runtime(runtime_probe(yolo_executable))
    dataset = json.loads(dataset_manifest.read_bytes())
    if (
        not isinstance(dataset, Mapping)
        or dataset.get("schema") != "yolo26n-owner-dataset-v26"
        or dataset.get("status") != "V26_DATASET_READY"
        or dataset.get("evaluation_tier") != "development"
    ):
        raise ValueError("v2.6 dataset contract mismatch")
    if _repository_head() != source_commit:
        raise ValueError("source commit does not match repository HEAD")
    _validate_dataset_builder_identity(dataset, source_commit=source_commit)
    _validate_training_dataset(
        dataset,
        dataset_root=dataset_manifest.resolve().parent,
        data_yaml=spec.data_yaml,
    )
    run_dir = spec.runs_dir / spec.run_name
    if output_manifest.exists() or started_lock.exists() or run_dir.exists():
        raise FileExistsError("candidate output exists")
    _write_private_new(
        started_lock,
        {
            "schema": "yolo26n-v26-training-lock-v1",
            "status": "V26_TRAINING_STARTED",
            "candidate": spec.candidate,
            "seed": spec.seed,
            "run_name": spec.run_name,
            "dataset_sha256": expected_dataset_sha256,
            "data_yaml_sha256": dataset["data_yaml_sha256"],
            "initializer_sha256": expected_initializer_sha256,
            "runner_sha256": runner_sha,
            "yolo_executable_sha256": expected_yolo_executable_sha256,
            "source_commit": source_commit,
            "runtime_versions": runtime_versions,
        },
    )
    if (
        _sha(dataset_manifest) != expected_dataset_sha256
        or _sha(spec.initializer) != expected_initializer_sha256
        or _sha(Path(__file__)) != expected_runner_sha256
        or _sha(yolo_executable) != expected_yolo_executable_sha256
        or _repository_head() != source_commit
    ):
        raise ValueError("training input changed after claim")
    dataset = json.loads(dataset_manifest.read_bytes())
    if not isinstance(dataset, Mapping):
        raise ValueError("v2.6 dataset manifest root malformed")
    _validate_dataset_builder_identity(dataset, source_commit=source_commit)
    _validate_training_dataset(
        dataset,
        dataset_root=dataset_manifest.resolve().parent,
        data_yaml=spec.data_yaml,
    )
    runtime_versions = _validate_runtime(runtime_probe(yolo_executable))
    completed = executor(build_training_command(spec, yolo_executable=yolo_executable), check=False)
    best = run_dir / "weights/best.pt"
    results = run_dir / "results.csv"
    if completed.returncode == 0 and (not best.is_file() or not results.is_file()):
        raise ValueError("successful training output missing")
    result: dict[str, object] = {
        "schema": "yolo26n-v26-training-run-v1",
        "status": "V26_TRAINING_COMPLETED" if completed.returncode == 0 else "V26_TRAINING_FAILED",
        "candidate": spec.candidate,
        "seed": spec.seed,
        "run_name": spec.run_name,
        "source_commit": source_commit,
        "dataset_manifest_sha256": expected_dataset_sha256,
        "data_yaml_sha256": dataset["data_yaml_sha256"],
        "initializer_sha256": expected_initializer_sha256,
        "runner_sha256": runner_sha,
        "yolo_executable_sha256": expected_yolo_executable_sha256,
        "runtime_versions": runtime_versions,
        "mps_one_shot_not_bitwise_deterministic": True,
        "spec": {
            **asdict(spec),
            "initializer": str(spec.initializer),
            "data_yaml": str(spec.data_yaml),
            "runs_dir": str(spec.runs_dir),
            "run_name": spec.run_name,
        },
        "returncode": int(completed.returncode),
        "best_pt_sha256": _sha(best) if best.is_file() else None,
        "results_csv_sha256": _sha(results) if results.is_file() else None,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "deploy_count": 0,
    }
    _write_private_new(output_manifest, result)
    if completed.returncode != 0:
        raise RuntimeError(f"training exited {completed.returncode}")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=("warm-start", "clean-reference"), required=True)
    parser.add_argument("--seed", type=int, choices=(26, 27, 28), required=True)
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
    parser.add_argument("--yolo-executable-sha256", required=True)
    args = parser.parse_args(argv)
    spec = build_v26_training_spec(
        args.candidate, args.seed, args.initializer, args.data_yaml, args.runs_dir
    )
    result = run_v26_training(
        spec,
        yolo_executable=args.yolo_executable,
        dataset_manifest=args.dataset_manifest,
        output_manifest=args.run_manifest,
        started_lock=args.started_lock,
        source_commit=args.source_commit,
        expected_dataset_sha256=args.dataset_sha256,
        expected_initializer_sha256=args.initializer_sha256,
        expected_runner_sha256=args.runner_sha256,
        expected_yolo_executable_sha256=args.yolo_executable_sha256,
    )
    print(result["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

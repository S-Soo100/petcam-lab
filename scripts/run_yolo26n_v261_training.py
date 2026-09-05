"""Run one immutable YOLO26n v2.6.1 candidate/seed training job."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DATASET_SCHEMA = "yolo26n-owner-dataset-v261"
DATASET_STATUS = "V261_DATASET_READY"
TRAINING_STATUS = "V261_TRAINING_COMPLETE"
APPROVED_CANDIDATES = {"warm-start", "clean-reference"}
APPROVED_SEEDS = {26, 27, 28}


@dataclass(frozen=True)
class TrainingSpec:
    candidate: str
    seed: int
    initializer: Path
    data_yaml: Path
    runs_dir: Path
    epochs: int = 100
    patience: int = 20
    lr0: float = 0.001
    optimizer: str = "AdamW"
    imgsz: int = 960
    batch: int = 2
    workers: int = 0
    device: str = "mps"

    @property
    def run_name(self) -> str:
        return f"{self.candidate}-s{self.seed}"


def build_v261_training_spec(
    *,
    candidate: str,
    seed: int,
    initializer: Path,
    data_yaml: Path,
    runs_dir: Path,
) -> TrainingSpec:
    if candidate not in APPROVED_CANDIDATES:
        raise ValueError("v2.6.1 candidate is not approved")
    if seed not in APPROVED_SEEDS:
        raise ValueError("v2.6.1 seed is not approved")
    return TrainingSpec(candidate, seed, initializer, data_yaml, runs_dir)


def build_training_command(spec: TrainingSpec, *, yolo_executable: Path) -> list[str]:
    return [
        str(yolo_executable),
        "detect",
        "train",
        f"model={spec.initializer}",
        f"data={spec.data_yaml}",
        f"project={spec.runs_dir}",
        f"name={spec.run_name}",
        f"epochs={spec.epochs}",
        f"patience={spec.patience}",
        f"optimizer={spec.optimizer}",
        f"lr0={spec.lr0}",
        f"imgsz={spec.imgsz}",
        f"batch={spec.batch}",
        f"workers={spec.workers}",
        f"device={spec.device}",
        f"seed={spec.seed}",
        "deterministic=True",
        "exist_ok=False",
    ]


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def _write_json_new(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    data = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
    os.chmod(path, 0o600)


def _secure_tree(root: Path) -> None:
    for path in root.rglob("*"):
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    os.chmod(root, 0o700)


def _resolve_dataset_file(root: Path, relative: object, *, label: str) -> Path:
    if not isinstance(relative, str):
        raise TypeError(f"dataset {label} path is missing")
    path = (root / relative).resolve()
    if root.resolve() not in path.parents:
        raise ValueError(f"dataset {label} path escapes root")
    return path


def _label_box_count(path: Path) -> int:
    count = 0
    for raw in path.read_text().splitlines():
        if not raw.strip():
            continue
        parts = raw.split()
        if len(parts) != 5 or parts[0] != "0":
            raise ValueError("invalid dataset YOLO label")
        try:
            x, y, width, height = (float(value) for value in parts[1:])
        except ValueError as exc:
            raise ValueError("invalid dataset YOLO label") from exc
        if not (
            width > 0
            and height > 0
            and x - width / 2 >= 0
            and x + width / 2 <= 1
            and y - height / 2 >= 0
            and y + height / 2 <= 1
        ):
            raise ValueError("invalid dataset YOLO label")
        count += 1
    return count


def validate_training_dataset(
    manifest_path: Path, *, expected_manifest_sha256: str
) -> dict[str, Any]:
    if (
        not _is_sha(expected_manifest_sha256, 64)
        or _sha(manifest_path) != expected_manifest_sha256
    ):
        raise ValueError("dataset manifest SHA mismatch")
    manifest = _load_object(manifest_path, label="dataset manifest")
    if (
        manifest.get("schema") != DATASET_SCHEMA
        or manifest.get("status") != DATASET_STATUS
    ):
        raise ValueError("v2.6.1 dataset is not ready")
    data_yaml = manifest_path.parent / "data.yaml"
    if not data_yaml.is_file() or _sha(data_yaml) != manifest.get("data_yaml_sha256"):
        raise ValueError("data.yaml SHA mismatch")
    expected_yaml = (
        f"path: {manifest_path.parent.resolve()}\n"
        "train: images/train\n"
        "val: images/val\n"
        "names:\n"
        "  0: gecko\n"
    )
    if data_yaml.read_text() != expected_yaml:
        raise ValueError("data.yaml training root contract mismatch")
    records = manifest.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("dataset records are empty")
    splits = {row.get("split") for row in records if isinstance(row, dict)}
    if splits != {"train", "val"}:
        raise ValueError("dataset must contain train and val only")
    root = manifest_path.parent.resolve()
    expected_files: set[Path] = set()
    seen_images: set[str] = set()
    for row in records:
        if not isinstance(row, dict):
            raise TypeError("invalid dataset manifest record")
        split = row.get("split")
        image = _resolve_dataset_file(root, row.get("image_path"), label="image")
        label = _resolve_dataset_file(root, row.get("label_path"), label="label")
        if image.parent != root / "images" / str(split):
            raise ValueError("dataset image path does not match split")
        if label.parent != root / "labels" / str(split):
            raise ValueError("dataset label path does not match split")
        if not image.is_file() or not label.is_file():
            raise ValueError("dataset file is missing")
        image_sha = _sha(image)
        if image_sha != row.get("image_sha256") or _sha(label) != row.get(
            "label_sha256"
        ):
            raise ValueError("dataset byte drift")
        if image_sha in seen_images:
            raise ValueError("duplicate dataset image SHA")
        seen_images.add(image_sha)
        if _label_box_count(label) != row.get("box_count"):
            raise ValueError("dataset label box count drift")
        expected_files.update({image, label})
    actual_files = {
        path.resolve()
        for directory in (root / "images", root / "labels")
        if directory.is_dir()
        for path in directory.rglob("*")
        if path.is_file()
    }
    if actual_files != expected_files:
        raise ValueError("dataset file set drift")
    if manifest.get("image_count", len(records)) != len(records):
        raise ValueError("dataset manifest image count drift")
    return manifest


def _default_repository_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _default_repository_status() -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain"], check=True, capture_output=True, text=True
    )
    return result.stdout


def _default_executor(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, text=True)


def _require_training_outputs_under_attempt(
    *,
    dataset_manifest_path: Path,
    runs_dir: Path,
    run_manifest_path: Path,
    started_lock_path: Path,
) -> None:
    attempt_root = dataset_manifest_path.resolve().parent.parent
    for path in (runs_dir, run_manifest_path, started_lock_path):
        resolved = path.resolve()
        if resolved != attempt_root and attempt_root not in resolved.parents:
            raise ValueError("training output path escapes private attempt")


def _results_summary(path: Path) -> dict[str, Any]:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("results.csv has no epochs")
    last = rows[-1]
    epoch_value = last.get("epoch")
    try:
        final_epoch = int(float(str(epoch_value)))
    except ValueError as exc:
        raise ValueError("results.csv has invalid epoch") from exc
    return {"completed_epoch_rows": len(rows), "final_epoch": final_epoch}


def run_v261_training(
    *,
    spec: TrainingSpec,
    dataset_manifest_path: Path,
    run_manifest_path: Path,
    started_lock_path: Path,
    yolo_executable: Path,
    source_commit: str,
    dataset_sha256: str,
    initializer_sha256: str,
    runner_sha256: str,
    yolo_executable_sha256: str,
    executor: Callable[[list[str]], Any] = _default_executor,
    repository_head: Callable[[], str] = _default_repository_head,
    repository_status: Callable[[], str] = _default_repository_status,
) -> dict[str, Any]:
    _require_training_outputs_under_attempt(
        dataset_manifest_path=dataset_manifest_path,
        runs_dir=spec.runs_dir,
        run_manifest_path=run_manifest_path,
        started_lock_path=started_lock_path,
    )
    for path in (started_lock_path, run_manifest_path, spec.runs_dir / spec.run_name):
        if path.exists():
            raise FileExistsError(path)
    if not _is_sha(source_commit, 40) or repository_head() != source_commit:
        raise ValueError("training source commit mismatch")
    if repository_status().strip():
        raise ValueError("training worktree must be clean")
    if not _is_sha(runner_sha256, 64) or _sha(Path(__file__)) != runner_sha256:
        raise ValueError("training runner SHA mismatch")
    if not spec.initializer.is_file() or _sha(spec.initializer) != initializer_sha256:
        raise ValueError("initializer SHA mismatch")
    if not yolo_executable.is_file() or _sha(yolo_executable) != yolo_executable_sha256:
        raise ValueError("YOLO executable SHA mismatch")
    dataset = validate_training_dataset(
        dataset_manifest_path, expected_manifest_sha256=dataset_sha256
    )
    if (
        spec.data_yaml.resolve()
        != (dataset_manifest_path.parent / "data.yaml").resolve()
    ):
        raise ValueError("training data.yaml is not bound to dataset manifest")
    if dataset.get("source_commit") != source_commit:
        raise ValueError("dataset builder source commit mismatch")

    command = build_training_command(spec, yolo_executable=yolo_executable)
    lock = {
        "schema": "yolo26n-v261-training-lock-v1",
        "status": "V261_TRAINING_STARTED",
        "candidate": spec.candidate,
        "seed": spec.seed,
        "source_commit": source_commit,
        "dataset_sha256": dataset_sha256,
        "initializer_sha256": initializer_sha256,
        "runner_sha256": runner_sha256,
        "yolo_executable_sha256": yolo_executable_sha256,
        "command": command,
    }
    _write_json_new(started_lock_path, lock)
    completed = executor(command)
    returncode = getattr(completed, "returncode", None)
    if returncode != 0:
        raise RuntimeError(f"YOLO training failed with return code {returncode}")
    validate_training_dataset(
        dataset_manifest_path, expected_manifest_sha256=dataset_sha256
    )

    run_root = spec.runs_dir / spec.run_name
    results = run_root / "results.csv"
    best = run_root / "weights" / "best.pt"
    if not results.is_file() or not best.is_file():
        raise RuntimeError("YOLO training completed without results.csv or best.pt")
    _secure_tree(run_root)
    summary = _results_summary(results)
    manifest = {
        "schema": "yolo26n-v261-training-run-v1",
        "status": TRAINING_STATUS,
        "candidate": spec.candidate,
        "seed": spec.seed,
        "source_commit": source_commit,
        "dataset_sha256": dataset_sha256,
        "initializer_sha256": initializer_sha256,
        "runner_sha256": runner_sha256,
        "yolo_executable_sha256": yolo_executable_sha256,
        "spec": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in asdict(spec).items()
        },
        "results_csv_sha256": _sha(results),
        "best_pt_sha256": _sha(best),
        **summary,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "deploy_count": 0,
    }
    _write_json_new(run_manifest_path, manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate", choices=sorted(APPROVED_CANDIDATES), required=True
    )
    parser.add_argument(
        "--seed", type=int, choices=sorted(APPROVED_SEEDS), required=True
    )
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
    spec = build_v261_training_spec(
        candidate=args.candidate,
        seed=args.seed,
        initializer=args.initializer,
        data_yaml=args.data_yaml,
        runs_dir=args.runs_dir,
    )
    run_v261_training(
        spec=spec,
        dataset_manifest_path=args.dataset_manifest,
        run_manifest_path=args.run_manifest,
        started_lock_path=args.started_lock,
        yolo_executable=args.yolo_executable,
        source_commit=args.source_commit,
        dataset_sha256=args.dataset_sha256,
        initializer_sha256=args.initializer_sha256,
        runner_sha256=args.runner_sha256,
        yolo_executable_sha256=args.yolo_executable_sha256,
    )
    print(TRAINING_STATUS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

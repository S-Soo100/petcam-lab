"""YOLO 라벨링 보조 모델을 검증된 read-only release로 만든다."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


SCHEMA = "petcam-yolo-release-v1"
V23_MODEL_VERSION = "yolo26n-owner-dataset-v2.3-warm-start+dbed3a2d8018"
V23_CHECKPOINT_SHA256 = "dbed3a2d8018a2eb6e4130de57d301414fcd6c9ba80aef8aafdaba55b19a6a34"
V23_CHECKPOINT_SIZE = 5_400_581
V23_THRESHOLD = 0.25
ALLOWED_USE = "labeling_bbox_assist_only"
REQUIRED_FORBIDDEN_USES = (
    "gt_auto_confirm",
    "absence_decision",
    "gme_routing",
    "r2_classification",
    "deletion",
    "vlm_skip",
)
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9.+_-]{1,128}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ReleaseError(RuntimeError):
    """Local path나 private payload를 포함하지 않는 release 오류."""


@dataclass(frozen=True, slots=True)
class FixedTestMetrics:
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float


@dataclass(frozen=True, slots=True)
class YoloReleaseManifest:
    schema: str
    model_version: str
    checkpoint_sha256: str
    checkpoint_size: int
    candidate: str
    threshold: float
    evaluation_tier: str
    future_holdout_required: bool
    allowed_use: str
    forbidden_uses: tuple[str, ...]
    fixed_test: FixedTestMetrics

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["forbidden_uses"] = list(self.forbidden_uses)
        return payload


def v23_release_manifest() -> YoloReleaseManifest:
    return YoloReleaseManifest(
        schema=SCHEMA,
        model_version=V23_MODEL_VERSION,
        checkpoint_sha256=V23_CHECKPOINT_SHA256,
        checkpoint_size=V23_CHECKPOINT_SIZE,
        candidate="warm-start",
        threshold=V23_THRESHOLD,
        evaluation_tier="development",
        future_holdout_required=True,
        allowed_use=ALLOWED_USE,
        forbidden_uses=REQUIRED_FORBIDDEN_USES,
        fixed_test=FixedTestMetrics(
            tp=53,
            fp=19,
            fn=37,
            precision=0.7361111111111112,
            recall=0.5888888888888889,
        ),
    )


def _checkpoint_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_checkpoint(path: Path, manifest: YoloReleaseManifest, *, code: str) -> None:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ReleaseError(code)
        if metadata.st_size != manifest.checkpoint_size:
            raise ReleaseError(code)
        if _checkpoint_sha256(path) != manifest.checkpoint_sha256:
            raise ReleaseError(code)
    except ReleaseError:
        raise
    except OSError as exc:
        raise ReleaseError(code) from exc


def _validate_manifest(manifest: YoloReleaseManifest) -> None:
    metrics = manifest.fixed_test
    valid = (
        manifest.schema == SCHEMA
        and bool(_SAFE_VERSION.fullmatch(manifest.model_version))
        and bool(_SHA256.fullmatch(manifest.checkpoint_sha256))
        and manifest.checkpoint_size > 0
        and manifest.candidate == "warm-start"
        and manifest.threshold == V23_THRESHOLD
        and manifest.evaluation_tier == "development"
        and manifest.future_holdout_required is True
        and manifest.allowed_use == ALLOWED_USE
        and manifest.forbidden_uses == REQUIRED_FORBIDDEN_USES
        and metrics.tp == 53
        and metrics.fp == 19
        and metrics.fn == 37
        and metrics.precision == 0.7361111111111112
        and metrics.recall == 0.5888888888888889
    )
    if not valid:
        raise ReleaseError("release_manifest_invalid")


def load_release_manifest(path: Path) -> YoloReleaseManifest:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ReleaseError("release_manifest_invalid")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or set(raw) != {
            "schema",
            "model_version",
            "checkpoint_sha256",
            "checkpoint_size",
            "candidate",
            "threshold",
            "evaluation_tier",
            "future_holdout_required",
            "allowed_use",
            "forbidden_uses",
            "fixed_test",
        }:
            raise ReleaseError("release_manifest_invalid")
        fixed = raw["fixed_test"]
        if not isinstance(fixed, dict) or set(fixed) != {
            "tp",
            "fp",
            "fn",
            "precision",
            "recall",
        }:
            raise ReleaseError("release_manifest_invalid")
        forbidden = raw["forbidden_uses"]
        if not isinstance(forbidden, list) or not all(isinstance(v, str) for v in forbidden):
            raise ReleaseError("release_manifest_invalid")
        manifest = YoloReleaseManifest(
            schema=raw["schema"],
            model_version=raw["model_version"],
            checkpoint_sha256=raw["checkpoint_sha256"],
            checkpoint_size=raw["checkpoint_size"],
            candidate=raw["candidate"],
            threshold=raw["threshold"],
            evaluation_tier=raw["evaluation_tier"],
            future_holdout_required=raw["future_holdout_required"],
            allowed_use=raw["allowed_use"],
            forbidden_uses=tuple(forbidden),
            fixed_test=FixedTestMetrics(**fixed),
        )
    except ReleaseError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise ReleaseError("release_manifest_invalid") from exc
    _validate_manifest(manifest)
    return manifest


def _verify_existing_release(
    target: Path,
    manifest: YoloReleaseManifest,
) -> tuple[Path, Path]:
    checkpoint = target / "best.pt"
    manifest_path = target / "manifest.json"
    try:
        if target.is_symlink() or not target.is_dir():
            raise ReleaseError("release_identity_invalid")
        if stat.S_IMODE(checkpoint.lstat().st_mode) != 0o444:
            raise ReleaseError("release_identity_invalid")
        if stat.S_IMODE(manifest_path.lstat().st_mode) != 0o444:
            raise ReleaseError("release_identity_invalid")
        _verify_checkpoint(checkpoint, manifest, code="release_identity_invalid")
        if load_release_manifest(manifest_path) != manifest:
            raise ReleaseError("release_identity_invalid")
    except ReleaseError:
        raise
    except OSError as exc:
        raise ReleaseError("release_identity_invalid") from exc
    return checkpoint, manifest_path


def _write_release_directory(
    *,
    source: Path,
    target: Path,
    manifest: YoloReleaseManifest,
) -> tuple[Path, Path]:
    temporary = Path(tempfile.mkdtemp(prefix=".petcam-yolo-release-", dir=target.parent))
    try:
        checkpoint = temporary / "best.pt"
        with source.open("rb") as source_handle, checkpoint.open("xb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        _verify_checkpoint(checkpoint, manifest, code="release_identity_invalid")
        checkpoint.chmod(0o444)

        manifest_path = temporary / "manifest.json"
        encoded = json.dumps(
            manifest.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        with manifest_path.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        manifest_path.chmod(0o444)
        load_release_manifest(manifest_path)

        try:
            temporary.rename(target)
        except FileExistsError:
            return _verify_existing_release(target, manifest)
        return target / "best.pt", target / "manifest.json"
    except ReleaseError:
        raise
    except OSError as exc:
        raise ReleaseError("release_write_failed") from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def create_immutable_release(
    *,
    source: Path,
    release_root: Path,
    manifest: YoloReleaseManifest,
) -> tuple[Path, Path]:
    _validate_manifest(manifest)
    _verify_checkpoint(source, manifest, code="source_identity_invalid")
    try:
        if release_root.exists():
            if release_root.is_symlink() or not release_root.is_dir():
                raise ReleaseError("release_root_invalid")
        else:
            release_root.mkdir(parents=True, mode=0o700)
    except ReleaseError:
        raise
    except OSError as exc:
        raise ReleaseError("release_root_invalid") from exc

    target = release_root / f"{manifest.model_version}-{manifest.checkpoint_sha256}"
    if target.exists() or target.is_symlink():
        return _verify_existing_release(target, manifest)
    return _write_release_directory(source=source, target=target, manifest=manifest)


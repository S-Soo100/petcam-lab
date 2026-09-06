"""R2/DB/pipeline 완료가 교차검증된 local bundle만 명시적으로 정리해."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from backend.rap_c500g_manifest import read_manifest, sha256_file
from backend.rap_c500g_pipeline_types import PipelineState


PRODUCTION_MOUNT = Path("/Volumes/RAP-C500G")
PRODUCTION_ROOT = PRODUCTION_MOUNT / "RAP-c500g-recordings"
ARTIFACT_NAMES = (
    "video.mp4", "thumbnail.jpg", "ffmpeg.sanitized.log", "manifest.json"
)


class PruneSafetyError(RuntimeError):
    pass


class MountInspector(Protocol):
    def is_mount(self, path: Path) -> bool: ...
    def volume_uuid(self, path: Path) -> str: ...


class HeadReader(Protocol):
    def head_object(self, key: str) -> Mapping[str, Any] | None: ...


class RecordingReader(Protocol):
    def get_recording(self, bundle_id: str) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class PruneRootGuard:
    mount_path: Path
    root_path: Path
    volume_uuid: str
    device_id: int
    root_inode: int


@dataclass(frozen=True, slots=True)
class PruneCandidate:
    bundle_dir: Path
    bytes_total: int
    identity_digest: str
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class PrunePlan:
    root_guard: PruneRootGuard
    candidates: tuple[PruneCandidate, ...]
    excluded: Mapping[str, int]
    plan_digest: str

    def to_public_dict(self) -> dict[str, object]:
        return {
            "candidate_count": len(self.candidates),
            "candidate_bytes": sum(item.bytes_total for item in self.candidates),
            "excluded": dict(sorted(self.excluded.items())),
            "plan_digest": self.plan_digest,
        }


@dataclass(frozen=True, slots=True)
class PruneReceipt:
    deleted_count: int
    deleted_bytes: int
    plan_digest: str


class _DefaultMountInspector:
    def is_mount(self, path: Path) -> bool:
        return path.is_mount()

    def volume_uuid(self, path: Path) -> str:
        value = os.stat(path).st_dev
        return f"device-{value}"


def _has_symlink(path: Path, *, stop: Path | None = None) -> bool:
    current = path
    while True:
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                return True
        except FileNotFoundError:
            return True
        if current == stop or current.parent == current:
            return False
        current = current.parent


def capture_prune_root_guard(
    root: Path,
    *,
    expected_root: Path = PRODUCTION_ROOT,
    inspector: MountInspector | None = None,
) -> PruneRootGuard:
    inspector = inspector or _DefaultMountInspector()
    if not root.is_absolute() or root != expected_root or root.name != "RAP-c500g-recordings":
        raise PruneSafetyError("prune root is not the exact allowed root")
    mount = root.parent
    if _has_symlink(root, stop=mount) or not root.is_dir() or not inspector.is_mount(mount):
        raise PruneSafetyError("prune root or mount identity is unsafe")
    if root.resolve(strict=True) != root or mount.resolve(strict=True) != mount:
        raise PruneSafetyError("prune root contains a symlink")
    root_stat = root.stat()
    mount_stat = mount.stat()
    if root_stat.st_dev != mount_stat.st_dev:
        raise PruneSafetyError("prune root crossed a device boundary")
    volume_uuid = inspector.volume_uuid(mount)
    if not volume_uuid:
        raise PruneSafetyError("volume UUID is unavailable")
    return PruneRootGuard(mount, root, volume_uuid, root_stat.st_dev, root_stat.st_ino)


def _head_sha(head: Mapping[str, Any]) -> str | None:
    direct = head.get("sha256")
    if isinstance(direct, str):
        return direct
    metadata = head.get("Metadata")
    if isinstance(metadata, Mapping) and isinstance(metadata.get("sha256"), str):
        return str(metadata["sha256"])
    return None


def _head_time(head: Mapping[str, Any]) -> float:
    value = head.get("LastModified")
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _stable_digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _safe_bundle(root: Path, manifest_path: Path) -> tuple[Path, dict[str, Any]]:
    if manifest_path.is_symlink() or _has_symlink(manifest_path.parent, stop=root):
        raise PruneSafetyError("bundle contains a symlink")
    bundle = manifest_path.parent
    try:
        bundle.relative_to(root)
        resolved = bundle.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise PruneSafetyError("bundle escapes prune root") from error
    if resolved != bundle:
        raise PruneSafetyError("bundle path is not canonical")
    names = {path.name for path in bundle.iterdir()}
    if names != set(ARTIFACT_NAMES):
        raise PruneSafetyError("bundle has partial or recovery artifacts")
    for name in ARTIFACT_NAMES:
        path = bundle / name
        if path.is_symlink() or not path.is_file() or path.stat().st_dev != root.stat().st_dev:
            raise PruneSafetyError("bundle artifact is unsafe")
    manifest = read_manifest(manifest_path)
    if manifest.get("relative_bundle_path") != bundle.relative_to(root).as_posix():
        raise PruneSafetyError("manifest path identity differs")
    return bundle, manifest


def build_prune_plan(
    root: Path,
    *,
    uploader: HeadReader,
    repository: RecordingReader,
    store: Any,
    now: datetime,
    guard: PruneRootGuard | None = None,
) -> PrunePlan:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    guard = guard or capture_prune_root_guard(root)
    if guard.root_path != root:
        raise PruneSafetyError("root guard does not match root")
    candidates: list[PruneCandidate] = []
    excluded: Counter[str] = Counter()
    pipeline = {
        (item.slot_start, item.camera_key): item
        for item in store.list_pipeline_items()
    }
    claims = store.read_capture_claim_statuses()
    protected_nights = {now.date().isoformat(), (now.date() - timedelta(days=1)).isoformat()}
    for manifest_path in sorted(root.rglob("manifest.json")):
        try:
            bundle, manifest = _safe_bundle(root, manifest_path)
        except (PruneSafetyError, ValueError, OSError):
            excluded["unsafe_bundle"] += 1
            continue
        if manifest.get("mode") != "production":
            excluded["non_production"] += 1
            continue
        if manifest.get("partial") is True:
            excluded["partial"] += 1
            continue
        if str(manifest.get("night_date")) in protected_nights:
            excluded["protected_night"] += 1
            continue
        slot = str(manifest.get("scheduled_start_utc", ""))
        try:
            slot = datetime.fromisoformat(slot).astimezone(now.tzinfo).isoformat()
        except ValueError:
            excluded["invalid_identity"] += 1
            continue
        camera = str(manifest.get("camera_key", ""))
        if claims.get((slot, camera)) in {"running", "finalizing"}:
            excluded["active"] += 1
            continue
        item = pipeline.get((slot, camera))
        if item is None or item.state is not PipelineState.VERIFIED_UPLOADED:
            excluded["pipeline_incomplete"] += 1
            continue
        row = repository.get_recording(str(manifest.get("bundle_id", "")))
        if not row or any((
            row.get("capture_status") != "captured",
            row.get("upload_status") != "uploaded",
            not row.get("manifest_r2_key"),
            not row.get("uploaded_at"),
            row.get("manifest_r2_key") != manifest.get("manifest_r2_key"),
        )):
            excluded["database_incomplete"] += 1
            continue
        if manifest.get("upload_status") != "uploaded" or manifest.get("r2_verified") is not True:
            excluded["manifest_incomplete"] += 1
            continue
        expected: list[tuple[str, Path, int, str]] = []
        for artifact in manifest.get("artifacts", []):
            if not isinstance(artifact, Mapping) or artifact.get("name") not in ARTIFACT_NAMES[:3]:
                continue
            path = bundle / str(artifact["name"])
            expected.append((str(artifact["r2_key"]), path, int(artifact["size_bytes"]), str(artifact["sha256"])))
        expected.append((str(manifest["manifest_r2_key"]), manifest_path, manifest_path.stat().st_size, sha256_file(manifest_path)))
        if len(expected) != 4:
            excluded["manifest_artifacts"] += 1
            continue
        heads: list[Mapping[str, Any]] = []
        mismatch = False
        for key, path, size, digest in expected:
            head = uploader.head_object(key)
            if (
                head is None
                or path.stat().st_size != size
                or sha256_file(path) != digest
                or int(head.get("ContentLength", -1)) != size
                or _head_sha(head) != digest
            ):
                mismatch = True
                break
            heads.append(head)
        if mismatch:
            excluded["r2_mismatch"] += 1
            continue
        if _head_time(heads[-1]) < max(_head_time(head) for head in heads[:-1]):
            excluded["manifest_not_last"] += 1
            continue
        identity_digest = hashlib.sha256(str(manifest["bundle_id"]).encode()).hexdigest()
        evidence_digest = _stable_digest({
            "identity": identity_digest,
            "artifact_sha": [digest for _key, _path, _size, digest in expected],
            "db": [row.get("capture_status"), row.get("upload_status"), bool(row.get("uploaded_at"))],
            "pipeline": item.state.value,
        })
        candidates.append(PruneCandidate(
            bundle, sum(path.stat().st_size for _key, path, _size, _digest in expected),
            identity_digest, evidence_digest,
        ))
    candidates.sort(key=lambda item: item.identity_digest)
    digest_payload = {
        "guard": [guard.volume_uuid, guard.device_id, guard.root_inode],
        "candidates": [[item.identity_digest, item.bytes_total, item.evidence_digest] for item in candidates],
        "excluded": dict(sorted(excluded.items())),
    }
    return PrunePlan(guard, tuple(candidates), dict(excluded), _stable_digest(digest_payload))


def _write_receipt(directory: Path, phase: str, payload: Mapping[str, object]) -> Path:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    path = directory / f"{datetime.now().astimezone().strftime('%Y%m%dT%H%M%S%f')}-{phase}-{uuid4().hex}.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
        json.dump(dict(payload), destination, sort_keys=True)
        destination.write("\n")
    return path


def execute_prune(
    plan: PrunePlan,
    *,
    supplied_digest: str,
    receipt_dir: Path,
    rebuild_plan: Callable[[], PrunePlan],
) -> PruneReceipt:
    if supplied_digest != plan.plan_digest:
        raise PruneSafetyError("supplied plan digest differs")
    try:
        receipt_dir.resolve().relative_to(plan.root_guard.root_path.resolve())
    except ValueError:
        pass
    else:
        raise PruneSafetyError("receipt directory must be outside recording root")
    if receipt_dir.exists() and (_has_symlink(receipt_dir) or not receipt_dir.is_dir()):
        raise PruneSafetyError("receipt directory is unsafe")
    parent = receipt_dir.parent
    if not parent.exists() or _has_symlink(parent):
        raise PruneSafetyError("receipt parent is unsafe")
    current = rebuild_plan()
    if current.plan_digest != plan.plan_digest or current.root_guard != plan.root_guard:
        raise PruneSafetyError("prune evidence changed after dry-run")
    _write_receipt(receipt_dir, "before", {
        "phase": "before", "plan_digest": plan.plan_digest,
        "candidate_count": len(plan.candidates),
        "candidate_bytes": sum(item.bytes_total for item in plan.candidates),
    })
    deleted_count = 0
    deleted_bytes = 0
    for candidate in plan.candidates:
        for name in ARTIFACT_NAMES:
            path = candidate.bundle_dir / name
            if path.is_symlink() or not path.is_file():
                raise PruneSafetyError("candidate changed during execution")
        for name in ARTIFACT_NAMES:
            (candidate.bundle_dir / name).unlink()
        candidate.bundle_dir.rmdir()
        deleted_count += 1
        deleted_bytes += candidate.bytes_total
    receipt = PruneReceipt(deleted_count, deleted_bytes, plan.plan_digest)
    _write_receipt(receipt_dir, "after", {
        "phase": "after", "plan_digest": plan.plan_digest,
        "deleted_count": deleted_count, "deleted_bytes": deleted_bytes,
    })
    return receipt

"""RAP C500G bundle manifest, 해시, 비밀값 제거."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC
from pathlib import Path, PurePosixPath
from typing import Any

from backend.rap_c500g_types import BundlePaths, SegmentIdentity


SCHEMA = "rap-c500g-bundle/v1"
_RTSP_CREDENTIALS = re.compile(r"(rtsp://)[^/@\s:]+:[^/@\s]+@", re.IGNORECASE)
_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:token|key|signature|credential)=)[^&\s]+"
)
_FORBIDDEN_KEY = re.compile(r"(?i)(password|secret|credential|rtsp_url|local_root)")


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_text(text: str, *, secrets: Sequence[str] = ()) -> str:
    safe = _RTSP_CREDENTIALS.sub(r"\1***:***@", text)
    safe = _QUERY_SECRET.sub(r"\1***", safe)
    for secret in sorted({value for value in secrets if value}, key=len, reverse=True):
        safe = safe.replace(secret, "***")
    return safe


def _walk_manifest(value: Any, *, path: str = "manifest") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _FORBIDDEN_KEY.search(str(key)):
                raise ValueError(f"manifest contains forbidden field: {path}.{key}")
            _walk_manifest(child, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _walk_manifest(child, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        if value.lower().startswith("rtsp://"):
            raise ValueError(f"manifest contains RTSP URL: {path}")
        if value.startswith(("/Users/", "/home/", "/var/", "/tmp/")):
            raise ValueError(f"manifest contains absolute local path: {path}")


def validate_manifest(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != SCHEMA:
        raise ValueError("manifest schema is invalid")
    _walk_manifest(payload)


def atomic_write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    validate_manifest(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f"{path.name}.part")
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )
    try:
        with part.open("x", encoding="utf-8") as destination:
            destination.write(encoded)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(part, path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def read_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manifest root must be an object")
    validate_manifest(payload)
    return payload


def _artifact(path: Path, relative_dir: Path, content_type: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path.name)
    return {
        "name": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "content_type": content_type,
        "r2_key": (PurePosixPath(relative_dir.as_posix()) / path.name).as_posix(),
    }


def build_local_manifest(
    identity: SegmentIdentity,
    paths: BundlePaths,
    *,
    media: Mapping[str, Any],
    capture: Mapping[str, Any],
) -> dict[str, Any]:
    relative = paths.relative_dir.as_posix()
    bundle_digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:32]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "bundle_id": f"rap-{bundle_digest}",
        "mode": identity.mode.value,
        "camera_key": identity.camera_key,
        "test_run_id": identity.test_run_id,
        "night_date": identity.night_date.isoformat() if identity.night_date else None,
        "scheduled_start_utc": identity.scheduled_start_kst.astimezone(UTC).isoformat(),
        "actual_start_utc": identity.actual_start_kst.astimezone(UTC).isoformat(),
        "partial": identity.partial,
        "relative_bundle_path": relative,
        "media": dict(media),
        "capture": dict(capture),
        "artifacts": [
            _artifact(paths.video, paths.relative_dir, "video/mp4"),
            _artifact(paths.thumbnail, paths.relative_dir, "image/jpeg"),
            _artifact(paths.log, paths.relative_dir, "text/plain; charset=utf-8"),
        ],
        "manifest_r2_key": (
            PurePosixPath(paths.relative_dir.as_posix()) / "manifest.json"
        ).as_posix(),
        "upload_status": "pending",
    }
    validate_manifest(payload)
    return payload

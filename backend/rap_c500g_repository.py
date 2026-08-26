"""RAP C500G manifest를 별도 Supabase 원장에 동기화한다."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any, Protocol

from backend.rap_c500g_manifest import validate_manifest


class Query(Protocol):
    def upsert(self, payload: dict[str, Any], *, on_conflict: str) -> "Query": ...

    def execute(self) -> object: ...


class SupabaseLike(Protocol):
    def table(self, name: str) -> Query: ...


def _artifact_by_name(manifest: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    for artifact in manifest.get("artifacts", []):
        if artifact.get("name") == name:
            return artifact
    raise ValueError(f"manifest artifact missing: {name}")


def manifest_to_row(manifest: Mapping[str, Any]) -> dict[str, Any]:
    validate_manifest(manifest)
    relative_path = str(manifest["relative_bundle_path"])
    pure_path = PurePosixPath(relative_path)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        raise ValueError("relative_bundle_path must be a safe relative path")

    upload_status = str(manifest.get("upload_status", "pending"))
    if upload_status == "uploaded" and manifest.get("r2_verified") is not True:
        raise ValueError("uploaded manifest must be R2 verified")

    video = _artifact_by_name(manifest, "video.mp4")
    thumbnail = _artifact_by_name(manifest, "thumbnail.jpg")
    log = _artifact_by_name(manifest, "ffmpeg.sanitized.log")
    media = manifest["media"]

    return {
        "bundle_id": manifest["bundle_id"],
        "mode": manifest["mode"],
        "camera_key": manifest["camera_key"],
        "test_run_id": manifest.get("test_run_id"),
        "night_date": manifest.get("night_date"),
        "scheduled_start_utc": manifest["scheduled_start_utc"],
        "actual_start_utc": manifest["actual_start_utc"],
        "ended_at_utc": manifest.get("ended_at_utc"),
        "partial": bool(manifest["partial"]),
        "duration_sec": media["duration_sec"],
        "codec": media["codec"],
        "width": media["width"],
        "height": media["height"],
        "fps": media["fps"],
        "video_size_bytes": video["size_bytes"],
        "video_sha256": video["sha256"],
        "video_r2_key": video["r2_key"],
        "thumbnail_r2_key": thumbnail["r2_key"],
        "log_r2_key": log["r2_key"],
        "manifest_r2_key": manifest["manifest_r2_key"],
        "relative_bundle_path": relative_path,
        "capture_status": "captured",
        "upload_status": upload_status,
        "upload_attempts": int(manifest.get("upload_attempts", 0)),
        "last_error_code": manifest.get("last_error_code"),
        "uploaded_at": manifest.get("uploaded_at"),
    }


class RapRecordingRepository:
    def __init__(self, client: SupabaseLike) -> None:
        self._client = client

    def upsert_manifest(self, manifest: Mapping[str, Any]) -> None:
        row = manifest_to_row(manifest)
        self._client.table("rap_c500g_recordings").upsert(
            row,
            on_conflict="bundle_id",
        ).execute()

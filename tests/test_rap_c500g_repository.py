from __future__ import annotations

from typing import Any

import pytest

from backend.rap_c500g_repository import RapRecordingRepository, manifest_to_row


def manifest() -> dict[str, Any]:
    return {
        "schema": "rap-c500g-bundle/v1",
        "bundle_id": "rap-abc",
        "mode": "production",
        "camera_key": "cam02",
        "test_run_id": None,
        "night_date": "2026-08-26",
        "scheduled_start_utc": "2026-08-26T15:00:00+00:00",
        "actual_start_utc": "2026-08-26T15:15:00+00:00",
        "partial": True,
        "relative_bundle_path": "recordings/cam02/night=2026-08-26/x",
        "media": {
            "duration_sec": 900.0,
            "codec": "hevc",
            "width": 2880,
            "height": 1620,
            "fps": 20.0,
        },
        "artifacts": [
            {"name": "video.mp4", "r2_key": "recordings/x/video.mp4", "size_bytes": 10, "sha256": "a" * 64},
            {"name": "thumbnail.jpg", "r2_key": "recordings/x/thumbnail.jpg", "size_bytes": 2, "sha256": "b" * 64},
            {"name": "ffmpeg.sanitized.log", "r2_key": "recordings/x/ffmpeg.sanitized.log", "size_bytes": 3, "sha256": "c" * 64},
        ],
        "manifest_r2_key": "recordings/x/manifest.json",
        "upload_status": "uploaded",
        "r2_verified": True,
        "uploaded_at": "2026-08-26T05:00:00+00:00",
    }


class Query:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None
        self.on_conflict: str | None = None

    def upsert(self, payload: dict[str, Any], *, on_conflict: str) -> "Query":
        self.payload = payload
        self.on_conflict = on_conflict
        return self

    def execute(self) -> object:
        return object()


class Client:
    def __init__(self) -> None:
        self.query = Query()
        self.table_name: str | None = None

    def table(self, name: str) -> Query:
        self.table_name = name
        return self.query


def test_manifest_to_row_maps_only_safe_relative_and_media_fields() -> None:
    row = manifest_to_row(manifest())
    assert row["bundle_id"] == "rap-abc"
    assert row["capture_status"] == "captured"
    assert row["upload_status"] == "uploaded"
    assert row["video_r2_key"] == "recordings/x/video.mp4"
    assert row["video_sha256"] == "a" * 64
    assert "artifacts" not in row
    assert "capture" not in row


def test_repository_upserts_only_separate_rap_table_by_bundle_id() -> None:
    client = Client()
    repository = RapRecordingRepository(client)

    repository.upsert_manifest(manifest())

    assert client.table_name == "rap_c500g_recordings"
    assert client.query.on_conflict == "bundle_id"
    assert client.query.payload is not None
    assert client.query.payload["bundle_id"] == "rap-abc"


def test_manifest_to_row_rejects_absolute_local_path_and_uploaded_without_verification() -> None:
    absolute = manifest()
    absolute["relative_bundle_path"] = "/Users/name/video"
    with pytest.raises(ValueError, match="relative"):
        manifest_to_row(absolute)

    unverified = manifest()
    unverified["r2_verified"] = False
    with pytest.raises(ValueError, match="verified"):
        manifest_to_row(unverified)

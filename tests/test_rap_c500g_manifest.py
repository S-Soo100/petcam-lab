import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend.rap_c500g_manifest import (
    atomic_write_manifest,
    build_local_manifest,
    read_manifest,
    sanitize_text,
    sha256_file,
    validate_manifest,
)
from backend.rap_c500g_naming import build_bundle_paths
from backend.rap_c500g_types import SegmentIdentity


KST = ZoneInfo("Asia/Seoul")


def identity() -> SegmentIdentity:
    return SegmentIdentity.test(
        camera_key="cam01",
        scheduled_start_kst=datetime(2026, 8, 26, 13, 42, 27, tzinfo=KST),
        test_run_id="test-20260826T134227-KST-a1b2c3d4",
    )


def test_sanitize_text_removes_rtsp_credentials_query_tokens_and_known_secrets() -> None:
    raw = (
        "open rtsp://viewer:s3cret@192.168.50.23:554/onvif1 "
        "retry https://example.test/a?token=abc123&mode=x user=viewer s3cret"
    )

    safe = sanitize_text(raw, secrets=("viewer", "s3cret"))

    assert "viewer" not in safe
    assert "s3cret" not in safe
    assert "abc123" not in safe
    assert "192.168.50.23" in safe
    assert "token=***" in safe


def test_atomic_manifest_round_trip_leaves_no_part_file(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    payload = {"schema": "rap-c500g-bundle/v1", "bundle_id": "bundle-1"}

    atomic_write_manifest(path, payload)

    assert read_manifest(path) == payload
    assert not path.with_name("manifest.json.part").exists()
    assert path.read_bytes().endswith(b"\n")


def test_sha256_file_uses_file_content(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4"
    path.write_bytes(b"abc")
    assert sha256_file(path) == (
        "ba7816bf8f01cfea414140de5dae2223"
        "b00361a396177a9cb410ff61f20015ad"
    )


def test_build_local_manifest_contains_relative_artifacts_without_local_root(
    tmp_path: Path,
) -> None:
    paths = build_bundle_paths(tmp_path, identity())
    paths.bundle_dir.mkdir(parents=True)
    paths.video.write_bytes(b"video")
    paths.thumbnail.write_bytes(b"jpeg")
    paths.log.write_text("safe log\n", encoding="utf-8")

    manifest = build_local_manifest(
        identity(),
        paths,
        media={
            "duration_sec": 60.0,
            "codec": "hevc",
            "width": 2880,
            "height": 1620,
            "fps": 20.0,
        },
        capture={"ffmpeg_exit_code": 0, "verified": True},
    )

    encoded = json.dumps(manifest, sort_keys=True)
    assert str(tmp_path) not in encoded
    assert manifest["schema"] == "rap-c500g-bundle/v1"
    assert manifest["camera_key"] == "cam01"
    assert manifest["scheduled_start_utc"] == "2026-08-26T04:42:27+00:00"
    assert [item["name"] for item in manifest["artifacts"]] == [
        "video.mp4",
        "thumbnail.jpg",
        "ffmpeg.sanitized.log",
    ]
    assert all(item["r2_key"].startswith("test/") for item in manifest["artifacts"])


@pytest.mark.parametrize(
    "payload",
    [
        {"schema": "rap-c500g-bundle/v1", "password": "x"},
        {"schema": "rap-c500g-bundle/v1", "source": "rtsp://u:p@host/onvif1"},
        {"schema": "rap-c500g-bundle/v1", "path": "/Users/name/private/video.mp4"},
    ],
)
def test_validate_manifest_rejects_secret_or_absolute_path(payload: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="manifest"):
        validate_manifest(payload)

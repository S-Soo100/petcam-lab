from __future__ import annotations

import json
import subprocess
from collections import namedtuple
from datetime import datetime
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

import pytest

from backend.rap_c500g_capture import (
    CaptureFailed,
    capture_segment,
    load_camera_configs,
)
from backend.rap_c500g_manifest import read_manifest
from backend.rap_c500g_naming import build_bundle_paths
from backend.rap_c500g_types import SegmentIdentity


KST = ZoneInfo("Asia/Seoul")


def make_identity() -> SegmentIdentity:
    return SegmentIdentity.test(
        camera_key="cam01",
        scheduled_start_kst=datetime(2026, 8, 26, 13, 42, 27, tzinfo=KST),
        test_run_id="test-20260826T134227-KST-a1b2c3d4",
    )


class FakeRunner:
    def __init__(self, *, capture_exit: int = 0, probe_payload: dict | None = None) -> None:
        self.capture_exit = capture_exit
        self.calls: list[list[str]] = []
        self.probe_payload = probe_payload or {
            "streams": [
                {
                    "codec_name": "hevc",
                    "width": 2880,
                    "height": 1620,
                    "avg_frame_rate": "20/1",
                }
            ],
            "format": {"duration": "60.032"},
        }

    def __call__(self, args: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
        argv = list(args)
        self.calls.append(argv)
        if argv[0] == "ffprobe":
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.probe_payload), "")
        if "-frames:v" in argv:
            Path(argv[-1]).write_bytes(b"jpeg")
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "-f" in argv and "null" in argv:
            return subprocess.CompletedProcess(argv, 0, "", "")
        Path(argv[-1]).write_bytes(b"video")
        return subprocess.CompletedProcess(
            argv,
            self.capture_exit,
            "",
            "Input #0 rtsp://viewer:s3cret@192.168.50.23:554/onvif1\n",
        )


def test_load_camera_configs_supports_existing_three_camera_env_names() -> None:
    env = {
        "RAP_CAM_C500G_RTSP_USER": "u1",
        "RAP_CAM_C500G_RTSP_PASSWORD": "p1",
        "RAP_CAM_C500G_RTSP_USER_02": "u2",
        "RAP_CAM_C500G_RTSP_PASSWORD_02": "p2",
        "RAP_CAM_C500G_RTSP_USER_03": "u3",
        "RAP_CAM_C500G_RTSP_PASSWORD_03": "p3",
    }

    configs = load_camera_configs(env)

    assert [(c.camera_key, c.ip, c.rtsp_path) for c in configs] == [
        ("cam01", "192.168.50.23", "/onvif1"),
        ("cam02", "192.168.50.24", "/onvif1"),
        ("cam03", "192.168.50.25", "/onvif1"),
    ]


def test_load_camera_configs_fails_closed_without_printing_values() -> None:
    with pytest.raises(ValueError, match="cam02") as error:
        load_camera_configs(
            {
                "RAP_CAM_C500G_RTSP_USER": "u1",
                "RAP_CAM_C500G_RTSP_PASSWORD": "p1",
                "RAP_CAM_C500G_RTSP_USER_02": "sensitive-user",
            }
        )
    assert "sensitive-user" not in str(error.value)


def test_capture_segment_creates_atomic_verified_bundle_without_secret(tmp_path: Path) -> None:
    config = load_camera_configs(
        {
            "RAP_CAM_C500G_RTSP_USER": "viewer",
            "RAP_CAM_C500G_RTSP_PASSWORD": "s3cret",
            "RAP_CAM_C500G_RTSP_USER_02": "u2",
            "RAP_CAM_C500G_RTSP_PASSWORD_02": "p2",
            "RAP_CAM_C500G_RTSP_USER_03": "u3",
            "RAP_CAM_C500G_RTSP_PASSWORD_03": "p3",
        }
    )[0]
    identity = make_identity()
    paths = build_bundle_paths(tmp_path, identity)
    runner = FakeRunner()

    result = capture_segment(config, identity, paths, duration_sec=60, runner=runner)

    assert result.paths.video.read_bytes() == b"video"
    assert result.paths.thumbnail.read_bytes() == b"jpeg"
    assert not result.paths.video_part.exists()
    assert not result.paths.log_part.exists()
    safe_log = result.paths.log.read_text(encoding="utf-8")
    assert "viewer" not in safe_log
    assert "s3cret" not in safe_log
    assert "192.168.50.23" in safe_log
    manifest = read_manifest(result.paths.manifest)
    assert manifest["media"] == {
        "codec": "hevc",
        "duration_sec": 60.032,
        "fps": 20.0,
        "height": 1620,
        "width": 2880,
    }
    assert "rtsp://" not in json.dumps(manifest)


def test_capture_failure_keeps_sanitized_log_but_no_completed_video_or_manifest(
    tmp_path: Path,
) -> None:
    env = {
        "RAP_CAM_C500G_RTSP_USER": "viewer",
        "RAP_CAM_C500G_RTSP_PASSWORD": "s3cret",
        "RAP_CAM_C500G_RTSP_USER_02": "u2",
        "RAP_CAM_C500G_RTSP_PASSWORD_02": "p2",
        "RAP_CAM_C500G_RTSP_USER_03": "u3",
        "RAP_CAM_C500G_RTSP_PASSWORD_03": "p3",
    }
    config = load_camera_configs(env)[0]
    paths = build_bundle_paths(tmp_path, make_identity())

    with pytest.raises(CaptureFailed, match="cam01"):
        capture_segment(config, make_identity(), paths, duration_sec=60, runner=FakeRunner(capture_exit=1))

    assert paths.log.is_file()
    assert "s3cret" not in paths.log.read_text(encoding="utf-8")
    assert not paths.video.exists()
    assert not paths.manifest.exists()


def test_capture_rejects_invalid_probe_metadata_before_atomic_rename(tmp_path: Path) -> None:
    env = {
        "RAP_CAM_C500G_RTSP_USER": "u1",
        "RAP_CAM_C500G_RTSP_PASSWORD": "p1",
        "RAP_CAM_C500G_RTSP_USER_02": "u2",
        "RAP_CAM_C500G_RTSP_PASSWORD_02": "p2",
        "RAP_CAM_C500G_RTSP_USER_03": "u3",
        "RAP_CAM_C500G_RTSP_PASSWORD_03": "p3",
    }
    paths = build_bundle_paths(tmp_path, make_identity())

    with pytest.raises(CaptureFailed, match="media verification"):
        capture_segment(
            load_camera_configs(env)[0],
            make_identity(),
            paths,
            duration_sec=60,
            runner=FakeRunner(probe_payload={"streams": [], "format": {}}),
        )

    assert not paths.video.exists()
    assert not paths.manifest.exists()


def test_capture_fails_closed_when_local_disk_is_below_safety_floor(tmp_path: Path, monkeypatch) -> None:
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr("backend.rap_c500g_capture.shutil.disk_usage", lambda _: usage(100, 99, 1))
    env = {
        "RAP_CAM_C500G_RTSP_USER": "u1", "RAP_CAM_C500G_RTSP_PASSWORD": "p1",
        "RAP_CAM_C500G_RTSP_USER_02": "u2", "RAP_CAM_C500G_RTSP_PASSWORD_02": "p2",
        "RAP_CAM_C500G_RTSP_USER_03": "u3", "RAP_CAM_C500G_RTSP_PASSWORD_03": "p3",
    }
    paths = build_bundle_paths(tmp_path, make_identity())

    with pytest.raises(CaptureFailed, match="disk space.*cam01"):
        capture_segment(load_camera_configs(env)[0], make_identity(), paths, duration_sec=60, runner=FakeRunner())

    assert not paths.video_part.exists()

from __future__ import annotations

from pathlib import Path

from backend.rap_c500g_capture import (
    finalize_raw_capture,
    load_camera_configs,
    record_raw_segment,
)
from backend.rap_c500g_naming import build_bundle_paths
from tests.test_rap_c500g_capture import FakeRunner, make_identity


ENV = {
    "RAP_CAM_C500G_RTSP_USER": "u1", "RAP_CAM_C500G_RTSP_PASSWORD": "p1",
    "RAP_CAM_C500G_RTSP_USER_02": "u2", "RAP_CAM_C500G_RTSP_PASSWORD_02": "p2",
    "RAP_CAM_C500G_RTSP_USER_03": "u3", "RAP_CAM_C500G_RTSP_PASSWORD_03": "p3",
}


def test_raw_recording_releases_camera_before_decode_and_thumbnail(tmp_path: Path) -> None:
    runner = FakeRunner()
    config = load_camera_configs(ENV)[0]
    identity = make_identity()
    paths = build_bundle_paths(tmp_path, identity)

    raw = record_raw_segment(
        config, identity, paths, duration_sec=57, runner=runner
    )

    assert paths.video_part.is_file()
    assert paths.log_part.is_file()
    assert not paths.video.is_file()
    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "ffmpeg"
    assert "-t" in runner.calls[0]
    assert runner.timeouts[0] == 59.0

    result = finalize_raw_capture(raw, runner=runner)

    assert result.paths.video.is_file()
    assert result.paths.thumbnail.is_file()
    assert result.paths.manifest.is_file()
    assert not result.paths.video_part.exists()
    assert [call[0] for call in runner.calls[1:]] == ["ffprobe", "ffmpeg", "ffmpeg"]

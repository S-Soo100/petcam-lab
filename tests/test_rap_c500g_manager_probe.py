from __future__ import annotations

import json
import subprocess
from collections import namedtuple
from dataclasses import asdict
from pathlib import Path

from backend.rap_c500g_capture import CameraConfig, MIN_FREE_BYTES
from backend.rap_c500g_manager_probe import (
    list_external_volumes,
    probe_camera,
    validate_selected_volume,
)


DiskUsage = namedtuple("DiskUsage", "total used free")


def test_selected_volume_fails_closed_when_mount_disappears(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "RAP-C500G").mkdir()
    monkeypatch.setattr(Path, "is_mount", lambda _: False)

    status = validate_selected_volume("RAP-C500G", volumes_root=tmp_path)

    assert status.ready is False
    assert status.reason == "volume_missing"
    assert status.mount_point is None


def test_selected_volume_requires_rw_and_safety_free_space(
    tmp_path: Path,
    monkeypatch,
) -> None:
    volume = tmp_path / "RAP-C500G"
    volume.mkdir()
    monkeypatch.setattr(Path, "is_mount", lambda _: True)
    monkeypatch.setattr("backend.rap_c500g_manager_probe.os.access", lambda *_: True)
    monkeypatch.setattr(
        "backend.rap_c500g_manager_probe.shutil.disk_usage",
        lambda _: DiskUsage(100 * 1024**3, 95 * 1024**3, MIN_FREE_BYTES - 1),
    )

    status = validate_selected_volume("RAP-C500G", volumes_root=tmp_path)

    assert status.ready is False
    assert status.reason == "low_space"
    assert status.free_bytes == MIN_FREE_BYTES - 1


def test_external_volume_listing_excludes_system_and_unmounted_entries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for name in ("RAP-C500G", "Macintosh HD", "loose-folder"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(
        Path,
        "is_mount",
        lambda path: path.name in {"RAP-C500G", "Macintosh HD"},
    )
    monkeypatch.setattr("backend.rap_c500g_manager_probe.os.access", lambda *_: True)
    monkeypatch.setattr(
        "backend.rap_c500g_manager_probe.shutil.disk_usage",
        lambda _: DiskUsage(100 * 1024**3, 20 * 1024**3, 80 * 1024**3),
    )

    statuses = list_external_volumes(volumes_root=tmp_path)

    assert [status.name for status in statuses] == ["RAP-C500G"]
    assert statuses[0].ready is True


def test_camera_probe_reports_tcp_failure_without_attempting_rtsp() -> None:
    config = CameraConfig("cam01", "192.168.50.23", "secret-user", "secret-pass")
    runner_called = False

    def fail_connect(address: tuple[str, int], timeout: float):
        assert address == ("192.168.50.23", 554)
        assert timeout == 2.0
        raise OSError("offline")

    def runner(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        nonlocal runner_called
        runner_called = True
        return subprocess.CompletedProcess(args, 0, "", "")

    status = probe_camera(config, connector=fail_connect, runner=runner)

    assert status.tcp_554 is False
    assert status.rtsp is False
    assert status.error_code == "tcp_554_unreachable"
    assert runner_called is False


def test_camera_probe_reports_rtsp_success_without_secret_fields() -> None:
    config = CameraConfig("cam03", "192.168.50.25", "secret-user", "secret-pass")

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def connect(address: tuple[str, int], timeout: float) -> Connection:
        return Connection()

    def runner(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        assert args[0] == "ffprobe"
        assert timeout == 8.0
        return subprocess.CompletedProcess(args, 0, "codec_name=hevc\n", "")

    status = probe_camera(config, connector=connect, runner=runner)
    public = json.dumps(asdict(status))

    assert status.tcp_554 is True
    assert status.rtsp is True
    assert status.error_code is None
    assert "secret-user" not in public
    assert "secret-pass" not in public
    assert "rtsp://" not in public

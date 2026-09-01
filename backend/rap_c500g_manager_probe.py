"""RAP manager용 외장 저장소와 카메라의 bounded read-only probe."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.rap_c500g_capture import CameraConfig, MIN_FREE_BYTES


SYSTEM_VOLUME_NAMES = frozenset(
    {"Macintosh HD", "Macintosh HD - Data", "System", "Data", "Recovery"}
)


@dataclass(frozen=True, slots=True)
class VolumeStatus:
    name: str
    ready: bool
    reason: str | None
    writable: bool
    total_bytes: int
    free_bytes: int
    mount_point: str | None

    def to_public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("mount_point", None)
        return payload


@dataclass(frozen=True, slots=True)
class CameraProbeStatus:
    camera_key: str
    ip: str
    tcp_554: bool
    rtsp: bool
    checked_at: str
    error_code: str | None


def _safe_volume_name(name: str) -> bool:
    return bool(name) and Path(name).name == name and name not in {".", ".."}


def validate_selected_volume(
    volume_name: str,
    *,
    volumes_root: Path = Path("/Volumes"),
) -> VolumeStatus:
    if not _safe_volume_name(volume_name) or volume_name in SYSTEM_VOLUME_NAMES:
        return VolumeStatus(volume_name, False, "volume_not_allowed", False, 0, 0, None)
    volume = volumes_root / volume_name
    if not volume.is_dir() or not volume.is_mount():
        return VolumeStatus(volume_name, False, "volume_missing", False, 0, 0, None)
    writable = os.access(volume, os.W_OK)
    usage = shutil.disk_usage(volume)
    if not writable:
        reason = "volume_read_only"
    elif usage.free < MIN_FREE_BYTES:
        reason = "low_space"
    else:
        reason = None
    return VolumeStatus(
        name=volume_name,
        ready=reason is None,
        reason=reason,
        writable=writable,
        total_bytes=usage.total,
        free_bytes=usage.free,
        mount_point=str(volume.resolve()),
    )


def list_external_volumes(
    *,
    volumes_root: Path = Path("/Volumes"),
) -> list[VolumeStatus]:
    if not volumes_root.is_dir():
        return []
    statuses = []
    for candidate in sorted(volumes_root.iterdir(), key=lambda path: path.name.lower()):
        if candidate.name.startswith(".") or candidate.name in SYSTEM_VOLUME_NAMES:
            continue
        if not candidate.is_dir() or not candidate.is_mount():
            continue
        statuses.append(
            validate_selected_volume(candidate.name, volumes_root=volumes_root)
        )
    return statuses


Connector = Callable[[tuple[str, int], float], Any]
ProbeRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]


def _run_probe(
    args: Sequence[str], timeout: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def probe_camera(
    config: CameraConfig,
    *,
    connector: Connector = socket.create_connection,
    runner: ProbeRunner = _run_probe,
) -> CameraProbeStatus:
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        connection = connector((config.ip, 554), 2.0)
        close = getattr(connection, "close", None)
        if callable(close):
            close()
    except (OSError, TimeoutError):
        return CameraProbeStatus(
            config.camera_key,
            config.ip,
            False,
            False,
            checked_at,
            "tcp_554_unreachable",
        )

    try:
        result = runner(
            [
                "ffprobe",
                "-v",
                "error",
                "-rtsp_transport",
                "tcp",
                "-read_intervals",
                "%+1",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=noprint_wrappers=1",
                config.rtsp_url,
            ],
            8.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return CameraProbeStatus(
            config.camera_key,
            config.ip,
            True,
            False,
            checked_at,
            "rtsp_probe_error",
        )
    if result.returncode != 0 or "codec_name=" not in result.stdout:
        return CameraProbeStatus(
            config.camera_key,
            config.ip,
            True,
            False,
            checked_at,
            "rtsp_unavailable",
        )
    return CameraProbeStatus(
        config.camera_key,
        config.ip,
        True,
        True,
        checked_at,
        None,
    )

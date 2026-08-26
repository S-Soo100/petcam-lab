"""C500G RTSP 한 구간을 검증된 local bundle로 만든다."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from backend.rap_c500g_manifest import (
    atomic_write_manifest,
    build_local_manifest,
    sanitize_text,
)
from backend.rap_c500g_types import BundlePaths, SegmentIdentity


MIN_FREE_BYTES = 8 * 1024 * 1024 * 1024


class CaptureFailed(RuntimeError):
    """완료 bundle로 승격할 수 없는 녹화/검증 실패."""


@dataclass(frozen=True, slots=True)
class CameraConfig:
    camera_key: str
    ip: str
    username: str
    password: str
    rtsp_path: str = "/onvif1"

    @property
    def rtsp_url(self) -> str:
        user = quote(self.username, safe="")
        password = quote(self.password, safe="")
        return f"rtsp://{user}:{password}@{self.ip}:554{self.rtsp_path}"


@dataclass(frozen=True, slots=True)
class CaptureResult:
    paths: BundlePaths
    manifest: dict[str, object]


class Runner(Protocol):
    def __call__(
        self, args: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[str]: ...


def _default_runner(
    args: Sequence[str], timeout: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def load_camera_configs(environ: Mapping[str, str]) -> tuple[CameraConfig, ...]:
    specs = (
        ("cam01", None, "192.168.50.23"),
        ("cam02", "02", "192.168.50.24"),
        ("cam03", "03", "192.168.50.25"),
    )
    configs: list[CameraConfig] = []
    for camera_key, number, default_ip in specs:
        if number is None:
            user_names = ("RAP_CAM_C500G_RTSP_USER",)
            password_names = ("RAP_CAM_C500G_RTSP_PASSWORD",)
            ip_names = ("RAP_CAM_C500G_IP",)
        else:
            # Mac mini의 기존 변수명을 우선하고, 초기 문서의 suffix 형식도 호환해.
            user_names = (
                f"RAP_CAM_C500G_{number}_RTSP_USER",
                f"RAP_CAM_C500G_RTSP_USER_{number}",
            )
            password_names = (
                f"RAP_CAM_C500G_{number}_RTSP_PASSWORD",
                f"RAP_CAM_C500G_RTSP_PASSWORD_{number}",
            )
            ip_names = (
                f"RAP_CAM_C500G_{number}_IP",
                f"RAP_CAM_C500G_IP_{number}",
            )
        username = next((environ[name] for name in user_names if environ.get(name)), None)
        password = next((environ[name] for name in password_names if environ.get(name)), None)
        ip = next((environ[name] for name in ip_names if environ.get(name)), default_ip)
        if not username or not password:
            raise ValueError(f"missing RTSP environment for {camera_key}")
        configs.append(
            CameraConfig(
                camera_key=camera_key,
                ip=ip,
                username=username,
                password=password,
            )
        )
    return tuple(configs)


def _parse_fps(raw: str) -> float:
    try:
        numerator, denominator = raw.split("/", 1)
        value = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError) as error:
        raise CaptureFailed("media verification failed: invalid fps") from error
    if value <= 0:
        raise CaptureFailed("media verification failed: invalid fps")
    return value


def _parse_probe(stdout: str) -> dict[str, object]:
    try:
        payload = json.loads(stdout)
        stream = payload["streams"][0]
        duration = float(payload["format"]["duration"])
        codec = str(stream["codec_name"])
        width = int(stream["width"])
        height = int(stream["height"])
        fps = _parse_fps(str(stream["avg_frame_rate"]))
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise CaptureFailed("media verification failed: invalid ffprobe output") from error
    if codec not in {"hevc", "h264"} or duration <= 0 or width <= 0 or height <= 0:
        raise CaptureFailed("media verification failed: invalid video stream")
    return {
        "codec": codec,
        "duration_sec": duration,
        "fps": fps,
        "height": height,
        "width": width,
    }


def capture_segment(
    config: CameraConfig,
    identity: SegmentIdentity,
    paths: BundlePaths,
    *,
    duration_sec: int | float,
    runner: Runner = _default_runner,
) -> CaptureResult:
    if config.camera_key != identity.camera_key:
        raise ValueError("camera config and segment identity differ")
    if duration_sec <= 0:
        raise ValueError("duration_sec must be positive")
    if paths.video.exists() or paths.manifest.exists():
        raise FileExistsError(f"completed bundle already exists for {config.camera_key}")

    paths.root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(paths.root).free < MIN_FREE_BYTES:
        raise CaptureFailed(f"disk space safety floor reached for {config.camera_key}")
    paths.bundle_dir.mkdir(parents=True, exist_ok=True)
    thumbnail_part = paths.thumbnail.with_name("thumbnail.part.jpg")
    for stale in (paths.video_part, paths.log_part, thumbnail_part):
        if stale.exists():
            raise FileExistsError(f"stale partial bundle exists for {config.camera_key}")

    secrets = (config.username, config.password, quote(config.username, safe=""), quote(config.password, safe=""))
    logs: list[str] = []

    def add_log(result: subprocess.CompletedProcess[str]) -> None:
        if result.stderr:
            logs.append(sanitize_text(result.stderr, secrets=secrets))

    def finish_log() -> None:
        safe = "".join(logs)
        paths.log_part.write_text(safe, encoding="utf-8")
        os.replace(paths.log_part, paths.log)

    capture_args = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "info",
        "-rtsp_transport",
        "tcp",
        "-i",
        config.rtsp_url,
        "-t",
        f"{float(duration_sec):.3f}",
        "-map",
        "0:v:0",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(paths.video_part),
    ]
    try:
        captured = runner(capture_args, float(duration_sec) + 90.0)
    except subprocess.TimeoutExpired as error:
        logs.append(sanitize_text(str(error), secrets=secrets))
        finish_log()
        raise CaptureFailed(f"capture timeout for {config.camera_key}") from error
    add_log(captured)
    if captured.returncode != 0 or not paths.video_part.is_file():
        finish_log()
        raise CaptureFailed(f"capture failed for {config.camera_key}")

    try:
        probed = runner(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(paths.video_part),
            ],
            60.0,
        )
        add_log(probed)
        if probed.returncode != 0:
            raise CaptureFailed("media verification failed: ffprobe error")
        media = _parse_probe(probed.stdout)

        decoded = runner(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(paths.video_part),
                "-f",
                "null",
                "-",
            ],
            max(120.0, float(duration_sec) * 2.0),
        )
        add_log(decoded)
        if decoded.returncode != 0:
            raise CaptureFailed("media verification failed: decode error")

        thumbnail = runner(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(min(5.0, max(0.0, float(media["duration_sec"]) / 2))),
                "-i",
                str(paths.video_part),
                "-frames:v",
                "1",
                str(thumbnail_part),
            ],
            60.0,
        )
        add_log(thumbnail)
        if thumbnail.returncode != 0 or not thumbnail_part.is_file():
            raise CaptureFailed("media verification failed: thumbnail error")
    except BaseException:
        finish_log()
        raise

    finish_log()
    os.replace(thumbnail_part, paths.thumbnail)
    os.replace(paths.video_part, paths.video)
    manifest = build_local_manifest(
        identity,
        paths,
        media=media,
        capture={"ffmpeg_exit_code": captured.returncode, "verified": True},
    )
    atomic_write_manifest(paths.manifest, manifest)
    return CaptureResult(paths=paths, manifest=manifest)

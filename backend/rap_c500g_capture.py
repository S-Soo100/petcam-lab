"""C500G RTSP 한 구간을 검증된 local bundle로 만든다."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from contextlib import contextmanager
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol
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


@dataclass(frozen=True, slots=True)
class RawCaptureResult:
    config: CameraConfig
    identity: SegmentIdentity
    paths: BundlePaths


class Runner(Protocol):
    def __call__(
        self, args: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[str]: ...


def _default_runner(
    args: Sequence[str], timeout: float
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    with _MEDIA_PROCESS_LOCK:
        _MEDIA_PROCESSES.add(process)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(args, timeout, stdout, stderr)
    finally:
        with _MEDIA_PROCESS_LOCK:
            _MEDIA_PROCESSES.discard(process)
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


_MEDIA_PROCESS_LOCK = threading.Lock()
_MEDIA_PROCESSES: set[subprocess.Popen[str]] = set()


def terminate_media_processes() -> None:
    """현재 manager가 직접 만든 ffmpeg/ffprobe child만 종료해."""
    with _MEDIA_PROCESS_LOCK:
        processes = list(_MEDIA_PROCESSES)
    for process in processes:
        if process.poll() is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
    for process in processes:
        if process.poll() is not None:
            continue
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@contextmanager
def _storage_root_lease(root: Path) -> Iterator[int]:
    """mount dirfd를 잡아 경로가 내부 SSD mountpoint로 바뀌는 race를 막아."""
    parent = root.parent
    is_external_volume = parent.parent == Path("/Volumes")
    if is_external_volume and not os.path.ismount(parent):
        raise CaptureFailed("selected external volume is not mounted")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        parent_fd = os.open(parent, flags)
    except FileNotFoundError as error:
        raise CaptureFailed("storage parent is unavailable") from error
    root_fd: int | None = None
    try:
        anchored = os.fstat(parent_fd)
        visible = os.stat(parent, follow_symlinks=False)
        if (anchored.st_dev, anchored.st_ino) != (visible.st_dev, visible.st_ino):
            raise CaptureFailed("storage mount changed during validation")
        try:
            os.mkdir(root.name, dir_fd=parent_fd)
        except FileExistsError:
            pass
        root_fd = os.open(root.name, flags, dir_fd=parent_fd)
        if os.fstat(root_fd).st_dev != anchored.st_dev:
            raise CaptureFailed("storage root device differs from selected mount")
        if is_external_volume and not os.path.ismount(parent):
            raise CaptureFailed("selected external volume was unmounted")
        yield root_fd
    finally:
        if root_fd is not None:
            os.close(root_fd)
        os.close(parent_fd)


def _mkdir_bundle_at(root_fd: int, relative_dir: Path) -> None:
    current_fd = os.dup(root_fd)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for part in relative_dir.parts:
            if part in {"", ".", ".."}:
                raise CaptureFailed("unsafe bundle path")
            try:
                os.mkdir(part, dir_fd=current_fd)
            except FileExistsError:
                pass
            next_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
    finally:
        os.close(current_fd)


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
        codec_tag = str(stream["codec_tag_string"])
        width = int(stream["width"])
        height = int(stream["height"])
        fps = _parse_fps(str(stream["avg_frame_rate"]))
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise CaptureFailed("media verification failed: invalid ffprobe output") from error
    if codec not in {"hevc", "h264"} or duration <= 0 or width <= 0 or height <= 0:
        raise CaptureFailed("media verification failed: invalid video stream")
    if codec == "hevc" and codec_tag != "hvc1":
        raise CaptureFailed(
            "media verification failed: HEVC requires QuickTime-compatible hvc1 tag"
        )
    return {
        "codec": codec,
        "codec_tag": codec_tag,
        "duration_sec": duration,
        "fps": fps,
        "height": height,
        "width": width,
    }


def _record_raw_segment_unleased(
    config: CameraConfig,
    identity: SegmentIdentity,
    paths: BundlePaths,
    *,
    duration_sec: int | float,
    runner: Runner = _default_runner,
) -> RawCaptureResult:
    """RTSP FFmpeg 소유 시간만 담당하고 검증은 별도 worker에 넘겨."""
    if config.camera_key != identity.camera_key:
        raise ValueError("camera config and segment identity differ")
    if duration_sec <= 0:
        raise ValueError("duration_sec must be positive")
    if paths.video.exists() or paths.manifest.exists():
        raise FileExistsError(f"completed bundle already exists for {config.camera_key}")
    if shutil.disk_usage(paths.root).free < MIN_FREE_BYTES:
        raise CaptureFailed(f"disk space safety floor reached for {config.camera_key}")
    thumbnail_part = paths.thumbnail.with_name("thumbnail.part.jpg")
    for stale in (paths.video_part, paths.log_part, thumbnail_part):
        if stale.exists():
            raise FileExistsError(f"stale partial bundle exists for {config.camera_key}")

    secrets = (
        config.username,
        config.password,
        quote(config.username, safe=""),
        quote(config.password, safe=""),
    )
    args = [
        "ffmpeg", "-hide_banner", "-loglevel", "info",
        "-rtsp_transport", "tcp", "-i", config.rtsp_url,
        "-t", f"{float(duration_sec):.3f}", "-map", "0:v:0",
        "-c", "copy", "-tag:v", "hvc1", "-movflags", "+faststart",
        str(paths.video_part),
    ]
    try:
        # manager가 넘기는 slot boundary 여유 안에서 child가 반드시 끝나야 해.
        captured = runner(args, float(duration_sec) + 2.0)
    except subprocess.TimeoutExpired as error:
        paths.log.write_text(
            sanitize_text(str(error), secrets=secrets), encoding="utf-8"
        )
        raise CaptureFailed(f"capture timeout for {config.camera_key}") from error
    safe_log = sanitize_text(captured.stderr or "", secrets=secrets)
    if captured.returncode != 0 or not paths.video_part.is_file():
        paths.log.write_text(safe_log, encoding="utf-8")
        raise CaptureFailed(f"capture failed for {config.camera_key}")
    paths.log_part.write_text(safe_log, encoding="utf-8")
    return RawCaptureResult(config=config, identity=identity, paths=paths)


def _finalize_raw_capture_unleased(
    raw: RawCaptureResult,
    *,
    runner: Runner = _default_runner,
) -> CaptureResult:
    """완료된 raw MP4를 decode/thumbnail/manifest로 원자 승격해."""
    config, identity, paths = raw.config, raw.identity, raw.paths
    if not paths.video_part.is_file() or not paths.log_part.is_file():
        raise CaptureFailed(f"raw bundle is incomplete for {config.camera_key}")
    secrets = (
        config.username,
        config.password,
        quote(config.username, safe=""),
        quote(config.password, safe=""),
    )
    logs = [paths.log_part.read_text(encoding="utf-8")]
    thumbnail_part = paths.thumbnail.with_name("thumbnail.part.jpg")

    def add_log(result: subprocess.CompletedProcess[str]) -> None:
        if result.stderr:
            logs.append(sanitize_text(result.stderr, secrets=secrets))

    def finish_log() -> None:
        paths.log_part.write_text("".join(logs), encoding="utf-8")
        os.replace(paths.log_part, paths.log)

    try:
        probed = runner(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(paths.video_part)],
            60.0,
        )
        add_log(probed)
        if probed.returncode != 0:
            raise CaptureFailed("media verification failed: ffprobe error")
        media = _parse_probe(probed.stdout)
        decoded = runner(
            ["ffmpeg", "-v", "error", "-i", str(paths.video_part), "-f", "null", "-"],
            max(120.0, float(media["duration_sec"]) * 2.0),
        )
        add_log(decoded)
        if decoded.returncode != 0:
            raise CaptureFailed("media verification failed: decode error")
        thumbnail = runner(
            [
                "ffmpeg", "-v", "error", "-ss",
                str(min(5.0, max(0.0, float(media["duration_sec"]) / 2))),
                "-i", str(paths.video_part), "-frames:v", "1", str(thumbnail_part),
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
        capture={"ffmpeg_exit_code": 0, "verified": True},
    )
    atomic_write_manifest(paths.manifest, manifest)
    return CaptureResult(paths=paths, manifest=manifest)


def _capture_segment_unleased(
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

    # `/Volumes/<label>`가 사라진 상태에서 parents=True를 쓰면 내부 SSD에 같은
    # 경로를 재생성할 수 있어. 저장 root의 부모가 실제로 남아 있을 때만 leaf를 만들어.
    if shutil.disk_usage(paths.root).free < MIN_FREE_BYTES:
        raise CaptureFailed(f"disk space safety floor reached for {config.camera_key}")
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
        # C500G WQHD 스트림은 HEVC다. hvc1 sample entry가 있어야 macOS QuickTime이
        # 같은 비트스트림을 재인코딩 없이 정상 MP4로 인식한다.
        "-tag:v",
        "hvc1",
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


def record_raw_segment(
    config: CameraConfig,
    identity: SegmentIdentity,
    paths: BundlePaths,
    *,
    duration_sec: int | float,
    runner: Runner = _default_runner,
) -> RawCaptureResult:
    with _storage_root_lease(paths.root) as root_fd:
        _mkdir_bundle_at(root_fd, paths.relative_dir)
        return _record_raw_segment_unleased(
            config, identity, paths, duration_sec=duration_sec, runner=runner
        )


def finalize_raw_capture(
    raw: RawCaptureResult,
    *,
    runner: Runner = _default_runner,
) -> CaptureResult:
    with _storage_root_lease(raw.paths.root):
        return _finalize_raw_capture_unleased(raw, runner=runner)


def capture_segment(
    config: CameraConfig,
    identity: SegmentIdentity,
    paths: BundlePaths,
    *,
    duration_sec: int | float,
    runner: Runner = _default_runner,
) -> CaptureResult:
    with _storage_root_lease(paths.root) as root_fd:
        _mkdir_bundle_at(root_fd, paths.relative_dir)
        return _capture_segment_unleased(
            config, identity, paths, duration_sec=duration_sec, runner=runner
        )

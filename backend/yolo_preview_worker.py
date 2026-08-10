"""보호된 Preview 전용 YOLO worker.

production provider와 분리된 Mac mini localhost runtime만 이 모듈을 실행한다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from threading import Lock
from typing import Any, Callable
from uuid import UUID

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from PIL import Image, UnidentifiedImageError


CHECKPOINT_SHA256 = "9ba825697693a0e84078a32120f64ea4e9da6a20bb50b9636403c9409200036e"
CHECKPOINT_SIZE = 5_408_389
MODEL_VERSION = "yolo26n-owner-v2.1+9ba825697693"
EXPECTED_HOST = "baeg-endeuui-Macmini.local"


class WorkerStartupError(RuntimeError):
    """비밀값이나 로컬 경로를 포함하지 않는 startup error."""


def checkpoint_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checkpoint(path: Path, *, expected_size: int, expected_sha256: str) -> None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size != expected_size:
            raise WorkerStartupError("checkpoint_identity_invalid")
        if checkpoint_sha256(path) != expected_sha256:
            raise WorkerStartupError("checkpoint_identity_invalid")
    except WorkerStartupError:
        raise
    except OSError as exc:
        raise WorkerStartupError("checkpoint_identity_invalid") from exc


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    checkpoint_path: Path
    token: str
    expected_host: str
    temp_root: Path
    request_limit: int = 30

    @classmethod
    def from_env(
        cls,
        *,
        hostname: Callable[[], str] = socket.gethostname,
    ) -> "WorkerConfig":
        expected_host = os.environ.get("YOLO_EXPECTED_HOST", EXPECTED_HOST)
        if hostname() != expected_host:
            raise WorkerStartupError("runtime_host_mismatch")
        token = os.environ.get("YOLO_WORKER_TOKEN", "")
        if len(token.encode("utf-8")) < 32:
            raise WorkerStartupError("worker_token_invalid")
        checkpoint = Path(os.environ.get("YOLO_CHECKPOINT_PATH", ""))
        verify_checkpoint(
            checkpoint,
            expected_size=CHECKPOINT_SIZE,
            expected_sha256=CHECKPOINT_SHA256,
        )
        temp_root = Path(os.environ.get("YOLO_TEMP_ROOT", tempfile.gettempdir()))
        return cls(
            checkpoint_path=checkpoint,
            token=token,
            expected_host=expected_host,
            temp_root=temp_root,
        )


class YoloModelRunner:
    def __init__(self, *, model: Any) -> None:
        self._model = model

    @classmethod
    def load(
        cls,
        checkpoint_path: Path,
        *,
        yolo_factory: Callable[[Path], Any] | None = None,
        mps_available: Callable[[], bool] | None = None,
    ) -> "YoloModelRunner":
        if mps_available is None:
            import torch

            mps_available = torch.backends.mps.is_available
        if not mps_available():
            raise WorkerStartupError("mps_unavailable")
        if yolo_factory is None:
            from ultralytics import YOLO

            yolo_factory = YOLO
        try:
            model = yolo_factory(checkpoint_path)
        except Exception as exc:
            raise WorkerStartupError("model_load_failed") from exc
        if "gecko" not in set(model.names.values()):
            raise WorkerStartupError("model_class_invalid")
        return cls(model=model)

    def predict_image(self, frame: np.ndarray) -> list[dict[str, object]]:
        height, width = frame.shape[:2]
        results = self._model.predict(
            source=frame,
            imgsz=960,
            conf=0.25,
            iou=0.7,
            max_det=20,
            device="mps",
            verbose=False,
        )
        detections: list[dict[str, object]] = []
        if not results:
            return detections
        boxes = results[0].boxes
        for xyxy, confidence, class_id in zip(
            boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist(), strict=True
        ):
            if self._model.names.get(int(class_id)) != "gecko":
                continue
            values = [float(value) for value in xyxy]
            score = float(confidence)
            if not all(math.isfinite(value) for value in [*values, score]):
                continue
            x1, y1, x2, y2 = values
            x1 = min(max(x1, 0.0), float(width))
            y1 = min(max(y1, 0.0), float(height))
            x2 = min(max(x2, 0.0), float(width))
            y2 = min(max(y2, 0.0), float(height))
            if x2 <= x1 or y2 <= y1:
                continue
            detections.append(
                {
                    "label": "gecko",
                    "confidence": score,
                    "bbox": {
                        "x": x1 / width,
                        "y": y1 / height,
                        "width": (x2 - x1) / width,
                        "height": (y2 - y1) / height,
                    },
                }
            )
        return detections


def video_sample_stride(source_fps: float) -> int:
    if not math.isfinite(source_fps) or source_fps <= 0:
        raise ValueError("video_metadata_invalid")
    return max(1, math.ceil(source_fps / 5.0))


def sample_frame_indices(*, total_frames: int, source_fps: float) -> list[int]:
    if total_frames <= 0:
        raise ValueError("video_metadata_invalid")
    return list(range(0, total_frames, video_sample_stride(source_fps)))[:300]


class _SlidingWindowLimiter:
    def __init__(self, *, limit: int, window_sec: float = 60.0) -> None:
        self._limit = limit
        self._window_sec = window_sec
        self._timestamps: deque[float] = deque()
        self._lock = Lock()

    def consume(self, now: float) -> bool:
        with self._lock:
            cutoff = now - self._window_sec
            while self._timestamps and self._timestamps[0] <= cutoff:
                self._timestamps.popleft()
            if len(self._timestamps) >= self._limit:
                return False
            self._timestamps.append(now)
            return True


def _authorized(request: Request, token: str) -> bool:
    values = request.headers.getlist("authorization")
    if len(values) != 1:
        return False
    value = values[0]
    prefix = "Bearer "
    return value.startswith(prefix) and secrets.compare_digest(value[len(prefix) :], token)


def _image_signature_allowed(data: bytes, content_type: str) -> bool:
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def _decode_image(path: Path, *, content_type: str) -> np.ndarray:
    data = path.read_bytes()
    if not _image_signature_allowed(data, content_type):
        raise ValueError("media_invalid")
    try:
        with Image.open(path) as image:
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("media_invalid")
            image.verify()
        with Image.open(path) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError("media_invalid")
            rgb = np.asarray(image.convert("RGB"))
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("media_invalid") from exc


def _video_signature_allowed(data: bytes, content_type: str) -> bool:
    if content_type == "video/mp4":
        return len(data) >= 12 and data[4:8] == b"ftyp"
    if content_type == "video/webm":
        return data.startswith(b"\x1a\x45\xdf\xa3")
    return False


@dataclass(frozen=True, slots=True)
class _VideoMetadata:
    width: int
    height: int
    fps: float
    duration_sec: float
    total_frames: int


def _probe_video(path: Path) -> _VideoMetadata:
    try:
        completed = subprocess.run(
            [
                "/opt/homebrew/bin/ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,r_frame_rate,nb_frames:format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        payload = json.loads(completed.stdout)
        stream = payload["streams"][0]
        fps = float(Fraction(stream["r_frame_rate"]))
        duration = float(payload["format"]["duration"])
        total_frames = int(stream.get("nb_frames") or round(duration * fps))
        metadata = _VideoMetadata(
            width=int(stream["width"]),
            height=int(stream["height"]),
            fps=fps,
            duration_sec=duration,
            total_frames=total_frames,
        )
    except (KeyError, IndexError, ValueError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ValueError("media_invalid") from exc
    if (
        metadata.width <= 0
        or metadata.height <= 0
        or metadata.width > 1920
        or metadata.height > 1080
        or not math.isfinite(metadata.fps)
        or metadata.fps <= 0
        or metadata.fps > 30
        or not math.isfinite(metadata.duration_sec)
        or metadata.duration_sec <= 0
        or metadata.duration_sec > 60
        or metadata.total_frames <= 0
    ):
        raise ValueError("media_invalid")
    return metadata


def _infer_video(
    path: Path, *, content_type: str, runner: Any
) -> list[dict[str, object]]:
    header = path.read_bytes()[:12]
    if not _video_signature_allowed(header, content_type):
        raise ValueError("media_invalid")
    metadata = _probe_video(path)
    stride = video_sample_stride(metadata.fps)
    max_actual_frames = max(1, math.floor(60 * metadata.fps))
    frames: list[dict[str, object]] = []
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError("media_invalid")
        frame_index = 0
        last_timestamp_ms = -1.0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            timestamp_ms = float(capture.get(cv2.CAP_PROP_POS_MSEC))
            if (
                not math.isfinite(timestamp_ms)
                or timestamp_ms < 0
                or timestamp_ms > 60_000.5
                or timestamp_ms < last_timestamp_ms
            ):
                raise ValueError("media_invalid")
            # ffprobe metadata가 tail을 축소 보고해도 실제 decode frame 수로 60초를 다시 제한한다.
            if frame_index >= max_actual_frames:
                raise ValueError("media_invalid")
            if frame_index % stride == 0:
                if len(frames) >= 300:
                    raise ValueError("media_invalid")
                if frame.shape[:2] != (metadata.height, metadata.width):
                    raise ValueError("media_invalid")
                frames.append(
                    {
                        "frame_index": frame_index,
                        "timestamp_ms": round(timestamp_ms),
                        "detections": runner.predict_image(frame),
                    }
                )
            last_timestamp_ms = timestamp_ms
            frame_index += 1
    finally:
        capture.release()
    if not frames or (frame_index > 1 and last_timestamp_ms <= 0):
        raise ValueError("media_invalid")
    return frames


def _cleanup_stale_temp(temp_root: Path, *, now: float) -> None:
    temp_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp_root.chmod(0o700)
    for candidate in temp_root.glob("petcam-yolo-preview-*"):
        try:
            if candidate.is_dir() and now - candidate.stat().st_mtime > 900:
                shutil.rmtree(candidate)
        except OSError:
            continue


def create_app(*, config: WorkerConfig, runner: Any) -> FastAPI:
    limiter = _SlidingWindowLimiter(limit=config.request_limit)
    inference_lock = Lock()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _cleanup_stale_temp(config.temp_root, now=time.time())
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/v1/health")
    def health(request: Request) -> dict[str, str]:
        if not _authorized(request, config.token):
            raise HTTPException(status_code=401, detail="unauthorized")
        return {
            "status": "ok",
            "model_version": MODEL_VERSION,
            "device": "mps",
            "checkpoint_sha256": CHECKPOINT_SHA256,
        }

    @app.post("/v1/infer")
    async def infer(request: Request) -> dict[str, object]:
        if not _authorized(request, config.token):
            raise HTTPException(status_code=401, detail="unauthorized")
        if not limiter.consume(time.monotonic()):
            raise HTTPException(status_code=429, detail="rate_limited")
        if not inference_lock.acquire(blocking=False):
            raise HTTPException(status_code=503, detail="worker_busy")
        try:
            required_headers = {
                name: request.headers.getlist(name)
                for name in (
                    "x-request-id",
                    "x-media-kind",
                    "content-type",
                    "x-training-consent",
                )
            }
            if any(len(values) != 1 for values in required_headers.values()):
                raise HTTPException(status_code=400, detail="request_invalid")
            request_id = required_headers["x-request-id"][0]
            media_kind = required_headers["x-media-kind"][0]
            content_type = required_headers["content-type"][0]
            consent = required_headers["x-training-consent"][0]
            try:
                UUID(request_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="request_invalid") from exc
            if media_kind not in {"image", "video"} or consent not in {"true", "false"}:
                raise HTTPException(status_code=400, detail="request_invalid")
            allowed_types = {
                "image": {"image/jpeg", "image/png", "image/webp"},
                "video": {"video/mp4", "video/webm"},
            }
            if content_type not in allowed_types[media_kind]:
                raise HTTPException(status_code=415, detail="media_invalid")

            request_dir = Path(
                tempfile.mkdtemp(prefix="petcam-yolo-preview-", dir=config.temp_root)
            )
            request_dir.chmod(0o700)
            media_path = request_dir / "media.bin"
            limit = 10 * 1024 * 1024 if media_kind == "image" else 50 * 1024 * 1024
            try:
                size = 0
                with media_path.open("wb") as handle:
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > limit:
                            raise HTTPException(status_code=413, detail="media_too_large")
                        handle.write(chunk)
                if size == 0:
                    raise HTTPException(status_code=422, detail="media_invalid")
                try:
                    if media_kind == "image":
                        frame = await asyncio.to_thread(
                            _decode_image, media_path, content_type=content_type
                        )
                        frames = [
                            {
                                "frame_index": 0,
                                "timestamp_ms": 0,
                                "detections": await asyncio.to_thread(
                                    runner.predict_image, frame
                                ),
                            }
                        ]
                    else:
                        frames = await asyncio.to_thread(
                            _infer_video,
                            media_path,
                            content_type=content_type,
                            runner=runner,
                        )
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail="media_invalid") from exc
                except Exception as exc:
                    raise HTTPException(
                        status_code=502, detail="inference_unavailable"
                    ) from exc
                return {
                    "request_id": request_id,
                    "media_kind": media_kind,
                    "model_version": MODEL_VERSION,
                    "provider_mode": "worker",
                    "processed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "warning": "연구용 결과이며 오류 가능",
                    "frames": frames,
                    "contribution_status": (
                        "candidate_only" if consent == "true" else "not_requested"
                    ),
                }
            finally:
                shutil.rmtree(request_dir, ignore_errors=True)
        finally:
            inference_lock.release()

    return app


def create_runtime_app(
    *,
    config_loader: Callable[[], WorkerConfig] = WorkerConfig.from_env,
    runner_loader: Callable[[Path], YoloModelRunner] = YoloModelRunner.load,
) -> FastAPI:
    config = config_loader()
    runner = runner_loader(config.checkpoint_path)
    return create_app(config=config, runner=runner)

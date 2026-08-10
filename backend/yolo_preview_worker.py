"""보호된 Preview 전용 YOLO worker.

production provider와 분리된 Mac mini localhost runtime만 이 모듈을 실행한다.
"""

from __future__ import annotations

import hashlib
import math
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np


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
        return cls(checkpoint_path=checkpoint, token=token, expected_host=expected_host)


class YoloModelRunner:
    def __init__(self, *, model: Any) -> None:
        self._model = model

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

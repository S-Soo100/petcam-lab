from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.yolo_preview_worker import (
    CHECKPOINT_SHA256,
    CHECKPOINT_SIZE,
    MODEL_VERSION,
    WorkerConfig,
    WorkerStartupError,
    YoloModelRunner,
    checkpoint_sha256,
    verify_checkpoint,
)


def test_checkpoint_sha256_reads_the_file_bytes(tmp_path: Path) -> None:
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"pinned-checkpoint")

    assert checkpoint_sha256(checkpoint) == hashlib.sha256(b"pinned-checkpoint").hexdigest()


def test_verify_checkpoint_rejects_size_or_digest_mismatch(tmp_path: Path) -> None:
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")

    with pytest.raises(WorkerStartupError, match="checkpoint_identity_invalid"):
        verify_checkpoint(checkpoint, expected_size=9, expected_sha256="0" * 64)


def test_config_rejects_wrong_host_before_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    monkeypatch.setenv("YOLO_CHECKPOINT_PATH", str(checkpoint))
    monkeypatch.setenv("YOLO_WORKER_TOKEN", "x" * 43)
    monkeypatch.setenv("YOLO_EXPECTED_HOST", "baeg-endeuui-Macmini.local")

    with pytest.raises(WorkerStartupError, match="runtime_host_mismatch"):
        WorkerConfig.from_env(hostname=lambda: "BaekBook-Pro-14-M5.local")


def test_config_rejects_short_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    monkeypatch.setenv("YOLO_CHECKPOINT_PATH", str(checkpoint))
    monkeypatch.setenv("YOLO_WORKER_TOKEN", "too-short")
    monkeypatch.setenv("YOLO_EXPECTED_HOST", "baeg-endeuui-Macmini.local")

    with pytest.raises(WorkerStartupError, match="worker_token_invalid"):
        WorkerConfig.from_env(hostname=lambda: "baeg-endeuui-Macmini.local")


def test_checkpoint_identity_constants_are_the_owner_v21_artifact() -> None:
    assert CHECKPOINT_SIZE == 5_408_389
    assert CHECKPOINT_SHA256 == "9ba825697693a0e84078a32120f64ea4e9da6a20bb50b9636403c9409200036e"
    assert MODEL_VERSION == "yolo26n-owner-v2.1+9ba825697693"


class _FakeModel:
    names = {0: "gecko", 1: "other"}

    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None

    def predict(self, source: np.ndarray, **kwargs: object) -> list[SimpleNamespace]:
        self.kwargs = kwargs
        boxes = SimpleNamespace(
            xyxy=np.array([[-10.0, 5.0, 110.0, 55.0], [1.0, 1.0, 2.0, 2.0]]),
            conf=np.array([0.8, 0.9]),
            cls=np.array([0.0, 1.0]),
        )
        return [SimpleNamespace(boxes=boxes)]


def test_model_runner_pins_inference_args_and_normalizes_gecko_boxes() -> None:
    model = _FakeModel()
    runner = YoloModelRunner(model=model)
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    detections = runner.predict_image(frame)

    assert detections == [
        {
            "label": "gecko",
            "confidence": 0.8,
            "bbox": {"x": 0.0, "y": 0.05, "width": 1.0, "height": 0.5},
        }
    ]
    assert model.kwargs == {
        "imgsz": 960,
        "conf": 0.25,
        "iou": 0.7,
        "max_det": 20,
        "device": "mps",
        "verbose": False,
    }


def test_model_runner_rejects_non_finite_or_degenerate_boxes() -> None:
    model = _FakeModel()
    model.predict = lambda source, **_kwargs: [
        SimpleNamespace(
            boxes=SimpleNamespace(
                xyxy=np.array([[np.nan, 0.0, 5.0, 5.0], [5.0, 5.0, 5.0, 8.0]]),
                conf=np.array([0.9, 0.7]),
                cls=np.array([0.0, 0.0]),
            )
        )
    ]

    assert YoloModelRunner(model=model).predict_image(np.zeros((10, 10, 3), dtype=np.uint8)) == []

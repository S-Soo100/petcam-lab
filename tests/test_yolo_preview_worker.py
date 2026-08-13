from __future__ import annotations

import hashlib
import os
import threading
import time
import traceback
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import cv2
from fastapi.testclient import TestClient
from PIL import Image

import backend.yolo_preview_worker as worker
from backend.yolo_release import (
    FixedTestMetrics,
    ReleaseError,
    YoloReleaseManifest,
    create_immutable_release,
    v23_release_manifest,
)
from backend.yolo_preview_worker import (
    EXPECTED_HOST,
    WorkerConfig,
    WorkerStartupError,
    YoloModelRunner,
    checkpoint_sha256,
    create_app,
    create_runtime_app,
    sample_frame_indices,
    video_sample_stride,
    verify_checkpoint,
)


MODEL_VERSION = "yolo26n-owner-dataset-v2.3-warm-start+dbed3a2d8018"
CHECKPOINT_SHA256 = "dbed3a2d8018a2eb6e4130de57d301414fcd6c9ba80aef8aafdaba55b19a6a34"


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
    runner = YoloModelRunner(model=model, manifest=v23_release_manifest())
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

    assert YoloModelRunner(model=model, manifest=v23_release_manifest()).predict_image(
        np.zeros((10, 10, 3), dtype=np.uint8)
    ) == []


def test_model_load_requires_mps_before_opening_checkpoint(tmp_path: Path) -> None:
    factory_calls: list[Path] = []

    with pytest.raises(WorkerStartupError, match="mps_unavailable"):
        YoloModelRunner.load(
            tmp_path / "best.pt",
            manifest=v23_release_manifest(),
            yolo_factory=lambda path: factory_calls.append(path),
            mps_available=lambda: False,
        )

    assert factory_calls == []


def test_model_load_rejects_checkpoint_without_gecko_class(tmp_path: Path) -> None:
    with pytest.raises(WorkerStartupError, match="model_class_invalid"):
        YoloModelRunner.load(
            tmp_path / "best.pt",
            manifest=v23_release_manifest(),
            yolo_factory=lambda _path: SimpleNamespace(names={0: "lizard"}),
            mps_available=lambda: True,
        )


class _StubRunner:
    def __init__(self, *, expected_shape: tuple[int, int, int] = (8, 10, 3)) -> None:
        self.calls = 0
        self.frames: list[np.ndarray] = []
        self.expected_shape = expected_shape

    def predict_image(self, frame: np.ndarray) -> list[dict[str, object]]:
        self.calls += 1
        assert frame.shape == self.expected_shape
        self.frames.append(frame.copy())
        return [
            {
                "label": "gecko",
                "confidence": 0.75,
                "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
            }
        ]


def _worker_config(tmp_path: Path, **overrides: object) -> WorkerConfig:
    values: dict[str, object] = {
        "checkpoint_path": tmp_path / "best.pt",
        "manifest": v23_release_manifest(),
        "token": "t" * 43,
        "expected_host": EXPECTED_HOST,
        "temp_root": tmp_path / "temp",
        "request_limit": 30,
    }
    values.update(overrides)
    return WorkerConfig(**values)  # type: ignore[arg-type]


def _small_release_manifest(payload: bytes) -> YoloReleaseManifest:
    digest = hashlib.sha256(payload).hexdigest()
    return YoloReleaseManifest(
        schema="petcam-yolo-release-v1",
        model_version=MODEL_VERSION,
        checkpoint_sha256=digest,
        checkpoint_size=len(payload),
        candidate="warm-start",
        threshold=0.25,
        image_size=960,
        iou=0.7,
        max_detections=20,
        evaluation_tier="development",
        future_holdout_required=True,
        allowed_use="labeling_bbox_assist_only",
        forbidden_uses=(
            "gt_auto_confirm",
            "absence_decision",
            "gme_routing",
            "r2_classification",
            "deletion",
            "vlm_skip",
            "behavior_name",
            "event_grouping",
        ),
        fixed_test=FixedTestMetrics(
            tp=53,
            fp=19,
            fn=37,
            precision=0.7361111111111112,
            recall=0.5888888888888889,
        ),
    )


def test_config_loads_release_manifest_and_rejects_checkpoint_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pt"
    source.write_bytes(b"checkpoint")
    checkpoint, manifest_path = create_immutable_release(
        source=source,
        release_root=tmp_path / "releases",
        manifest=_small_release_manifest(b"checkpoint"),
    )
    monkeypatch.setenv("YOLO_RELEASE_MANIFEST", str(manifest_path))
    monkeypatch.setenv("YOLO_WORKER_TOKEN", "x" * 43)
    monkeypatch.setenv("YOLO_EXPECTED_HOST", EXPECTED_HOST)
    monkeypatch.setattr(worker, "v23_release_manifest", lambda: _small_release_manifest(b"checkpoint"))

    config = WorkerConfig.from_env(hostname=lambda: EXPECTED_HOST)

    assert config.checkpoint_path == checkpoint
    assert config.manifest == _small_release_manifest(b"checkpoint")

    checkpoint.chmod(0o644)
    checkpoint.write_bytes(b"checkpoinu")
    with pytest.raises(WorkerStartupError, match="checkpoint_identity_invalid"):
        WorkerConfig.from_env(hostname=lambda: EXPECTED_HOST)


def test_config_rejects_release_that_is_not_exact_v23(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pt"
    source.write_bytes(b"checkpoint")
    _checkpoint, manifest_path = create_immutable_release(
        source=source,
        release_root=tmp_path / "releases",
        manifest=_small_release_manifest(b"checkpoint"),
    )
    monkeypatch.setenv("YOLO_RELEASE_MANIFEST", str(manifest_path))
    monkeypatch.setenv("YOLO_WORKER_TOKEN", "x" * 43)
    monkeypatch.setenv("YOLO_EXPECTED_HOST", EXPECTED_HOST)

    with pytest.raises(WorkerStartupError, match="release_identity_invalid"):
        WorkerConfig.from_env(hostname=lambda: EXPECTED_HOST)


def test_config_rejects_writable_release_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pt"
    source.write_bytes(b"checkpoint")
    _checkpoint, manifest_path = create_immutable_release(
        source=source,
        release_root=tmp_path / "releases",
        manifest=_small_release_manifest(b"checkpoint"),
    )
    manifest_path.chmod(0o644)
    monkeypatch.setenv("YOLO_RELEASE_MANIFEST", str(manifest_path))
    monkeypatch.setenv("YOLO_WORKER_TOKEN", "x" * 43)
    monkeypatch.setenv("YOLO_EXPECTED_HOST", EXPECTED_HOST)

    with pytest.raises(WorkerStartupError, match="release_identity_invalid"):
        WorkerConfig.from_env(hostname=lambda: EXPECTED_HOST)


def test_startup_traceback_redacts_release_loader_private_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "private-model" / "manifest.json"
    manifest_path.parent.mkdir()
    manifest_path.write_text("{}")
    manifest_path.chmod(0o444)
    monkeypatch.setenv("YOLO_RELEASE_MANIFEST", str(manifest_path))
    monkeypatch.setenv("YOLO_WORKER_TOKEN", "x" * 43)
    monkeypatch.setenv("YOLO_EXPECTED_HOST", EXPECTED_HOST)

    def fail_load(_path: Path) -> YoloReleaseManifest:
        try:
            raise OSError(f"cannot open {manifest_path}")
        except OSError as exc:
            raise ReleaseError("release_manifest_invalid") from exc

    monkeypatch.setattr(worker, "load_release_manifest", fail_load)
    try:
        WorkerConfig.from_env(hostname=lambda: EXPECTED_HOST)
    except WorkerStartupError:
        rendered = traceback.format_exc()
    else:
        pytest.fail("startup must fail")

    assert str(manifest_path) not in rendered


def test_startup_traceback_redacts_manifest_stat_private_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "private-model" / "manifest.json"
    manifest_path.parent.mkdir()
    manifest_path.write_text("{}")
    monkeypatch.setenv("YOLO_RELEASE_MANIFEST", str(manifest_path))
    monkeypatch.setenv("YOLO_WORKER_TOKEN", "x" * 43)
    monkeypatch.setenv("YOLO_EXPECTED_HOST", EXPECTED_HOST)
    original_stat = Path.stat

    def fail_manifest_stat(path: Path, *args: object, **kwargs: object) -> os.stat_result:
        if path == manifest_path:
            raise OSError(f"cannot stat {manifest_path}")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_manifest_stat)
    try:
        WorkerConfig.from_env(hostname=lambda: EXPECTED_HOST)
    except WorkerStartupError:
        rendered = traceback.format_exc()
    else:
        pytest.fail("startup must fail")

    assert str(manifest_path) not in rendered


def test_model_load_traceback_redacts_factory_private_path(tmp_path: Path) -> None:
    private_path = tmp_path / "private-model" / "best.pt"

    def fail_factory(_path: Path) -> object:
        raise RuntimeError(f"ultralytics failed at {private_path}")

    try:
        YoloModelRunner.load(
            private_path,
            manifest=v23_release_manifest(),
            yolo_factory=fail_factory,
            mps_available=lambda: True,
        )
    except WorkerStartupError:
        rendered = traceback.format_exc()
    else:
        pytest.fail("model load must fail")

    assert str(private_path) not in rendered


def _jpeg_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (10, 8), color=(30, 40, 50)).save(output, format="JPEG")
    return output.getvalue()


def _animated_webp_bytes() -> bytes:
    output = BytesIO()
    frames = [
        Image.new("RGB", (10, 8), color=(30, 40, 50)),
        Image.new("RGB", (10, 8), color=(50, 40, 30)),
    ]
    frames[0].save(output, format="WEBP", save_all=True, append_images=frames[1:])
    return output.getvalue()


def _mpo_bytes() -> bytes:
    output = BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    frames = [
        Image.new("RGB", (10, 8), color=(30, 40, 50)),
        Image.new("RGB", (10, 8), color=(200, 10, 20)),
    ]
    frames[0].save(
        output,
        format="MPO",
        save_all=True,
        append_images=frames[1:],
        exif=exif,
    )
    return output.getvalue()


def _oversized_pixel_png_bytes() -> bytes:
    output = BytesIO()
    Image.new("1", (5000, 4001)).save(output, format="PNG")
    return output.getvalue()


def _headers(token: str = "t" * 43, **overrides: str) -> dict[str, str]:
    headers = {
        "authorization": f"Bearer {token}",
        "content-type": "image/jpeg",
        "x-request-id": "00000000-0000-4000-8000-000000000001",
        "x-media-kind": "image",
        "x-training-consent": "false",
    }
    headers.update(overrides)
    return headers


def test_health_requires_bearer_and_never_exposes_checkpoint_path(tmp_path: Path) -> None:
    config = _worker_config(tmp_path)
    with TestClient(create_app(config=config, runner=_StubRunner())) as client:
        assert client.get("/v1/health").status_code == 401
        response = client.get("/v1/health", headers={"authorization": f"Bearer {config.token}"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "model_version": MODEL_VERSION,
        "device": "mps",
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "threshold": 0.25,
        "development_only": True,
        "usage_scope": "labeling_bbox_assist_only",
    }
    assert str(config.checkpoint_path) not in response.text


def test_infer_requires_bearer_before_reading_the_body(tmp_path: Path) -> None:
    config = _worker_config(tmp_path)
    with TestClient(create_app(config=config, runner=_StubRunner())) as client:
        response = client.post("/v1/infer", content=b"not-media")

    assert response.status_code == 401


def test_runtime_factory_loads_config_and_model_once(tmp_path: Path) -> None:
    config = _worker_config(tmp_path)
    runner = _StubRunner()
    config_calls = 0
    runner_inputs: list[tuple[Path, float]] = []

    def load_config() -> WorkerConfig:
        nonlocal config_calls
        config_calls += 1
        return config

    def load_runner(path: Path, manifest: YoloReleaseManifest) -> _StubRunner:
        runner_inputs.append((path, manifest.threshold))
        return runner

    app = create_runtime_app(config_loader=load_config, runner_loader=load_runner)
    with TestClient(app) as client:
        response = client.get(
            "/v1/health", headers={"authorization": f"Bearer {config.token}"}
        )

    assert response.status_code == 200
    assert config_calls == 1
    assert runner_inputs == [(config.checkpoint_path, 0.25)]


def test_image_infer_returns_versioned_schema_and_cleans_temp(tmp_path: Path) -> None:
    config = _worker_config(tmp_path)
    with TestClient(create_app(config=config, runner=_StubRunner())) as client:
        response = client.post("/v1/infer", headers=_headers(), content=_jpeg_bytes())

    assert response.status_code == 200
    assert response.json() == {
        "request_id": "00000000-0000-4000-8000-000000000001",
        "media_kind": "image",
        "model_version": MODEL_VERSION,
        "provider_mode": "worker",
        "processed_at": response.json()["processed_at"],
        "warning": "라벨링 보조 후보야. 박스가 없어도 게코 없음 판정이 아니야.",
        "threshold": 0.25,
        "development_only": True,
        "usage_scope": "labeling_bbox_assist_only",
        "frames": [
            {
                "frame_index": 0,
                "timestamp_ms": 0,
                "detections": [
                    {
                        "label": "gecko",
                        "confidence": 0.75,
                        "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                    }
                ],
            }
        ],
        "contribution_status": "not_requested",
    }
    assert list(config.temp_root.iterdir()) == []


def test_zero_detection_is_success_and_warns_against_absence_decision(
    tmp_path: Path,
) -> None:
    config = _worker_config(tmp_path)
    runner = _StubRunner()
    runner.predict_image = lambda _frame: []  # type: ignore[method-assign]

    with TestClient(create_app(config=config, runner=runner)) as client:
        response = client.post("/v1/infer", headers=_headers(), content=_jpeg_bytes())

    assert response.status_code == 200
    assert response.json()["frames"][0]["detections"] == []
    assert response.json()["warning"] == (
        "라벨링 보조 후보야. 박스가 없어도 게코 없음 판정이 아니야."
    )


def test_invalid_image_is_redacted_and_temp_is_cleaned(tmp_path: Path) -> None:
    config = _worker_config(tmp_path)
    with TestClient(create_app(config=config, runner=_StubRunner())) as client:
        response = client.post("/v1/infer", headers=_headers(), content=b"not-jpeg")

    assert response.status_code == 422
    assert response.json() == {"detail": "media_invalid"}
    assert list(config.temp_root.iterdir()) == []
    assert "checkpoint" not in response.text.lower()


def test_duplicate_required_metadata_is_rejected(tmp_path: Path) -> None:
    config = _worker_config(tmp_path)
    headers = list(_headers().items())
    headers.append(("x-media-kind", "video"))

    with TestClient(create_app(config=config, runner=_StubRunner())) as client:
        response = client.post("/v1/infer", headers=headers, content=_jpeg_bytes())

    assert response.status_code == 400
    assert response.json() == {"detail": "request_invalid"}


def test_image_body_cap_returns_413_and_cleans_partial_file(tmp_path: Path) -> None:
    config = _worker_config(tmp_path)
    oversized = b"\xff\xd8\xff" + (b"x" * (10 * 1024 * 1024))

    with TestClient(create_app(config=config, runner=_StubRunner())) as client:
        response = client.post("/v1/infer", headers=_headers(), content=oversized)

    assert response.status_code == 413
    assert list(config.temp_root.iterdir()) == []


def test_animated_image_is_rejected(tmp_path: Path) -> None:
    config = _worker_config(tmp_path)
    headers = _headers(**{"content-type": "image/webp"})

    with TestClient(create_app(config=config, runner=_StubRunner())) as client:
        response = client.post(
            "/v1/infer", headers=headers, content=_animated_webp_bytes()
        )

    assert response.status_code == 422


def test_mpo_jpeg_uses_primary_frame(tmp_path: Path) -> None:
    config = _worker_config(tmp_path)
    runner = _StubRunner(expected_shape=(10, 8, 3))

    with TestClient(create_app(config=config, runner=runner)) as client:
        response = client.post("/v1/infer", headers=_headers(), content=_mpo_bytes())

    assert response.status_code == 200
    assert runner.calls == 1
    np.testing.assert_allclose(runner.frames[0][0, 0], [50, 40, 30], atol=2)
    assert list(config.temp_root.iterdir()) == []


def test_image_over_twenty_megapixels_is_rejected(tmp_path: Path) -> None:
    config = _worker_config(tmp_path)
    headers = _headers(**{"content-type": "image/png"})

    with TestClient(create_app(config=config, runner=_StubRunner())) as client:
        response = client.post(
            "/v1/infer", headers=headers, content=_oversized_pixel_png_bytes()
        )

    assert response.status_code == 422


def test_model_exception_is_redacted_and_temp_is_cleaned(tmp_path: Path) -> None:
    config = _worker_config(tmp_path)

    class ExplodingRunner:
        def predict_image(self, _frame: np.ndarray) -> list[dict[str, object]]:
            raise RuntimeError(f"secret checkpoint: {config.checkpoint_path}")

    with TestClient(create_app(config=config, runner=ExplodingRunner())) as client:
        response = client.post("/v1/infer", headers=_headers(), content=_jpeg_bytes())

    assert response.status_code == 502
    assert response.json() == {"detail": "inference_unavailable"}
    assert str(config.checkpoint_path) not in response.text
    assert list(config.temp_root.iterdir()) == []


def test_startup_removes_only_stale_prefixed_temp_directories(tmp_path: Path) -> None:
    config = _worker_config(tmp_path)
    config.temp_root.mkdir()
    stale = config.temp_root / "petcam-yolo-preview-stale"
    recent = config.temp_root / "petcam-yolo-preview-recent"
    unrelated = config.temp_root / "keep-me"
    for directory in (stale, recent, unrelated):
        directory.mkdir()
    old = time.time() - 901
    os.utime(stale, (old, old))

    with TestClient(create_app(config=config, runner=_StubRunner())):
        pass

    assert not stale.exists()
    assert recent.is_dir()
    assert unrelated.is_dir()


def test_worker_rejects_concurrent_inference_without_queueing(tmp_path: Path) -> None:
    config = _worker_config(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    class BlockingRunner:
        def predict_image(self, _frame: np.ndarray) -> list[dict[str, object]]:
            entered.set()
            assert release.wait(timeout=3)
            return []

    app = create_app(config=config, runner=BlockingRunner())
    first_result: list[int] = []

    def make_first_request() -> None:
        with TestClient(app) as first_client:
            first_result.append(
                first_client.post(
                    "/v1/infer", headers=_headers(), content=_jpeg_bytes()
                ).status_code
            )

    thread = threading.Thread(target=make_first_request)
    thread.start()
    assert entered.wait(timeout=3)
    with TestClient(app) as second_client:
        second = second_client.post(
            "/v1/infer",
            headers=_headers(**{"x-request-id": "00000000-0000-4000-8000-000000000002"}),
            content=_jpeg_bytes(),
        )
    release.set()
    thread.join(timeout=3)

    assert second.status_code == 503
    assert second.json() == {"detail": "worker_busy"}
    assert first_result == [200]


def test_worker_rate_limit_is_process_global(tmp_path: Path) -> None:
    config = _worker_config(tmp_path, request_limit=1)
    with TestClient(create_app(config=config, runner=_StubRunner())) as client:
        first = client.post("/v1/infer", headers=_headers(), content=_jpeg_bytes())
        second = client.post("/v1/infer", headers=_headers(), content=_jpeg_bytes())

    assert first.status_code == 200
    assert second.status_code == 429


@pytest.mark.parametrize(
    ("source_fps", "expected"),
    [(30.0, 6), (7.0, 2), (5.0, 1), (1.0, 1)],
)
def test_video_sampling_never_exceeds_five_fps(source_fps: float, expected: int) -> None:
    assert video_sample_stride(source_fps) == expected


def test_video_sampling_caps_a_sixty_second_clip_at_three_hundred_frames() -> None:
    indices = sample_frame_indices(total_frames=1800, source_fps=30.0)

    assert len(indices) == 300
    assert indices[:3] == [0, 6, 12]
    assert indices[-1] == 1794


@pytest.mark.parametrize(
    ("width", "height", "fps", "duration", "frames"),
    [
        (1921, 1080, "30/1", "1", "30"),
        (1920, 1081, "30/1", "1", "30"),
        (1920, 1080, "31/1", "1", "31"),
        (1920, 1080, "30/1", "60.1", "1803"),
    ],
)
def test_video_probe_rejects_metadata_over_contract_caps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    width: int,
    height: int,
    fps: str,
    duration: str,
    frames: str,
) -> None:
    payload = {
        "streams": [
            {
                "width": width,
                "height": height,
                "r_frame_rate": fps,
                "nb_frames": frames,
            }
        ],
        "format": {"duration": duration},
    }
    monkeypatch.setattr(
        worker.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=worker.json.dumps(payload)),
    )

    with pytest.raises(ValueError, match="media_invalid"):
        worker._probe_video(tmp_path / "media.bin")


def test_video_decode_rejects_actual_tail_beyond_sixty_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media_path = tmp_path / "media.mp4"
    media_path.write_bytes(b"\x00\x00\x00\x18ftypisom")
    released = False

    class UnderreportedCapture:
        def __init__(self) -> None:
            self.index = 0

        def isOpened(self) -> bool:
            return True

        def read(self) -> tuple[bool, np.ndarray | None]:
            if self.index >= 61:
                return False, None
            self.index += 1
            return True, np.zeros((1, 1, 3), dtype=np.uint8)

        def get(self, _property: int) -> float:
            return float((self.index - 1) * 1000)

        def release(self) -> None:
            nonlocal released
            released = True

    monkeypatch.setattr(
        worker,
        "_probe_video",
        lambda _path: worker._VideoMetadata(
            width=1, height=1, fps=1.0, duration_sec=1.0, total_frames=1
        ),
    )
    monkeypatch.setattr(worker.cv2, "VideoCapture", lambda _path: UnderreportedCapture())

    with pytest.raises(ValueError, match="media_invalid"):
        worker._infer_video(
            media_path,
            content_type="video/mp4",
            runner=SimpleNamespace(predict_image=lambda _frame: []),
        )

    assert released is True


def test_video_decode_rejects_sparse_tail_timestamp_beyond_sixty_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media_path = tmp_path / "media.mp4"
    media_path.write_bytes(b"\x00\x00\x00\x18ftypisom")

    class SparseTailCapture:
        def __init__(self) -> None:
            self.index = 0

        def isOpened(self) -> bool:
            return True

        def read(self) -> tuple[bool, np.ndarray | None]:
            if self.index >= 2:
                return False, None
            self.index += 1
            return True, np.zeros((1, 1, 3), dtype=np.uint8)

        def get(self, _property: int) -> float:
            return [0.0, 61_000.0][self.index - 1]

        def release(self) -> None:
            pass

    monkeypatch.setattr(
        worker,
        "_probe_video",
        lambda _path: worker._VideoMetadata(
            width=1, height=1, fps=30.0, duration_sec=1.0, total_frames=2
        ),
    )
    monkeypatch.setattr(worker.cv2, "VideoCapture", lambda _path: SparseTailCapture())

    with pytest.raises(ValueError, match="media_invalid"):
        worker._infer_video(
            media_path,
            content_type="video/mp4",
            runner=SimpleNamespace(predict_image=lambda _frame: []),
        )


def _mp4_bytes(tmp_path: Path) -> bytes:
    video_path = tmp_path / "sample.mp4"
    writer = cv2.VideoWriter(
        str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (10, 8)
    )
    assert writer.isOpened()
    try:
        for value in range(10):
            writer.write(np.full((8, 10, 3), value * 10, dtype=np.uint8))
    finally:
        writer.release()
    return video_path.read_bytes()


def test_video_infer_returns_actual_sampled_frame_indices_and_timestamps(tmp_path: Path) -> None:
    config = _worker_config(tmp_path)
    runner = _StubRunner()
    headers = _headers(
        **{
            "content-type": "video/mp4",
            "x-media-kind": "video",
            "x-training-consent": "true",
        }
    )

    with TestClient(create_app(config=config, runner=runner)) as client:
        response = client.post("/v1/infer", headers=headers, content=_mp4_bytes(tmp_path))

    assert response.status_code == 200
    payload = response.json()
    assert payload["media_kind"] == "video"
    assert payload["contribution_status"] == "candidate_only"
    assert [frame["frame_index"] for frame in payload["frames"]] == [0, 2, 4, 6, 8]
    assert [frame["timestamp_ms"] for frame in payload["frames"]] == [0, 200, 400, 600, 800]
    assert runner.calls == 5
    assert list(config.temp_root.iterdir()) == []

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

import scripts.build_yolo26n_v25_owner_hardcase_queue as builder


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_uniform_indices_cover_interior_deterministically() -> None:
    assert builder.uniform_indices(1) == (0,)
    assert builder.uniform_indices(2) == (0, 1)
    assert builder.uniform_indices(10, limit=3) == (2, 4, 7)
    assert builder.uniform_indices(100, limit=8) == (11, 22, 33, 44, 55, 66, 77, 88)


@pytest.mark.parametrize("total", [0, -1, True])
def test_uniform_indices_reject_invalid_frame_count(total: object) -> None:
    with pytest.raises(ValueError, match="frame count"):
        builder.uniform_indices(total)  # type: ignore[arg-type]


def test_scene_anchors_use_score_spacing_and_uniform_exclusion() -> None:
    scans = [
        {"frame_index": 30, "timestamp_sec": 1.0, "score": 9.0},
        {"frame_index": 60, "timestamp_sec": 2.0, "score": 8.0},
        {"frame_index": 90, "timestamp_sec": 3.0, "score": 7.0},
        {"frame_index": 150, "timestamp_sec": 5.0, "score": 6.0},
        {"frame_index": 240, "timestamp_sec": 8.0, "score": 6.0},
    ]

    selected = builder.select_scene_anchors(
        scans,
        uniform_timestamps=(0.0,),
        limit=4,
    )

    # 1.0 is excluded by the uniform ±1s boundary; 3.0 is too close to the
    # higher-score 2.0 anchor; equal score at 5/8 is frame-rank stable.
    assert selected == (60, 150, 240)


def test_scene_anchor_tie_break_uses_frame_index_not_input_order() -> None:
    left = {"frame_index": 60, "timestamp_sec": 2.0, "score": 5.0}
    right = {"frame_index": 120, "timestamp_sec": 4.0, "score": 5.0}
    assert builder.select_scene_anchors([right, left], uniform_timestamps=()) == (60,)


def test_historical_dhash_is_existing_box_right_gt_left_policy() -> None:
    image = Image.new("L", (9, 8))
    for y in range(8):
        for x in range(9):
            image.putpixel((x, y), x)
    payload = builder.encode_jpeg(image.convert("RGB"))
    assert builder.historical_dhash64(payload) == "ffffffffffffffff"


def _candidate(index: int, *, dhash: str, image_sha: str | None = None) -> dict[str, object]:
    return {
        "source_video_sha256": _sha(f"video-{index // 2}"),
        "frame_index": index,
        "timestamp_sec": float(index),
        "image_sha256": image_sha or _sha(f"frame-{index}"),
        "dhash64": dhash,
        "width": 100,
        "height": 80,
        "jpeg_bytes": f"jpeg-{index}".encode(),
        "selection_reasons": ["uniform"],
    }


def test_global_dedup_rejects_historical_exact_and_dhash_two_keeps_three() -> None:
    historical = [
        {"image_sha256": _sha("protected"), "dhash64": "0000000000000000"}
    ]
    records = [
        _candidate(0, dhash="ffffffffffffffff", image_sha=_sha("protected")),
        _candidate(1, dhash="0000000000000003"),  # two bits
        _candidate(2, dhash="0000000000000007"),  # three bits
    ]

    result = builder.deduplicate_frames(records, historical)

    assert result["counts"] == {
        "input": 3,
        "historical_exact": 1,
        "historical_perceptual": 1,
        "pool_exact": 0,
        "pool_perceptual": 0,
        "accepted": 1,
    }
    assert [row["frame_index"] for row in result["records"]] == [2]


def test_pool_dedup_keeper_is_independent_of_discovery_order() -> None:
    first = _candidate(4, dhash="0000000000000000")
    second = _candidate(2, dhash="0000000000000001")
    expected = builder.deduplicate_frames([first, second], [])
    reversed_result = builder.deduplicate_frames([second, first], [])
    assert expected["records"] == reversed_result["records"]
    assert expected["counts"]["pool_perceptual"] == 1


def test_inventory_only_accepts_direct_regular_mov_and_preserves_originals(
    tmp_path: Path,
) -> None:
    first = tmp_path / "one.MOV"
    second = tmp_path / "two.mov"
    ignored = tmp_path / "still.jpg"
    first.write_bytes(b"one-video")
    second.write_bytes(b"two-video")
    ignored.write_bytes(b"still")
    symlink = tmp_path / "rival.MOV"
    symlink.symlink_to(first)
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "hidden.MOV").write_bytes(b"nested")
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (first, second)}

    result = builder.inventory_owner_sources(tmp_path, expected_count=35)

    assert result["status"] == "V25_OWNER_SOURCES_AUDITED"
    assert result["counts"] == {
        "expected": 35,
        "actual_regular_mov": 2,
        "missing": 33,
        "symlink_excluded": 1,
        "other_excluded": 2,
    }
    assert len(result["records"]) == 2
    assert all("source_video_sha256" in row for row in result["records"])
    assert all("source_path" in row for row in result["records"])
    assert before == {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (first, second)
    }


def test_inventory_fails_if_source_changes_during_hash(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "one.MOV"
    source.write_bytes(b"original")
    original_read = os.read
    changed = False

    def mutate_after_read(descriptor: int, size: int) -> bytes:
        nonlocal changed
        payload = original_read(descriptor, size)
        if payload and not changed:
            changed = True
            source.write_bytes(b"rival-data")
        return payload

    monkeypatch.setattr(os, "read", mutate_after_read)
    with pytest.raises(ValueError, match="source changed during inventory"):
        builder.inventory_owner_sources(tmp_path, expected_count=1)


def _write_video(path: Path, *, frames: int = 20, fps: float = 5.0) -> None:
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 48)
    )
    assert writer.isOpened()
    try:
        for index in range(frames):
            value = 20 if index < frames // 2 else 220
            frame = np.full((48, 64, 3), value, dtype=np.uint8)
            frame[:, index % 64] = (0, 0, 255)
            writer.write(frame)
    finally:
        writer.release()


def test_mine_owner_video_decodes_twice_and_emits_deterministic_frames(
    tmp_path: Path,
) -> None:
    video = tmp_path / "source.MOV"
    _write_video(video)
    inventory = builder.inventory_owner_sources(tmp_path, expected_count=1)
    source = inventory["records"][0]

    first = builder.mine_owner_video(source, uniform_limit=3, scene_limit=2)
    second = builder.mine_owner_video(source, uniform_limit=3, scene_limit=2)

    assert first == second
    assert first["status"] == "V25_OWNER_VIDEO_MINED"
    assert first["decoded_frame_count"] == 20
    assert 1 <= len(first["records"]) <= 5
    assert all(row["source_video_sha256"] == source["source_video_sha256"] for row in first["records"])
    assert all(row["image_sha256"] == hashlib.sha256(row["jpeg_bytes"]).hexdigest() for row in first["records"])
    assert all(builder.historical_dhash64(row["jpeg_bytes"]) == row["dhash64"] for row in first["records"])


@pytest.mark.parametrize("replacement_kind", ["regular", "fifo"])
def test_mine_owner_video_decodes_verified_inode_during_pathname_aba(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement_kind: str
) -> None:
    video = tmp_path / "source.MOV"
    _write_video(video, frames=10)
    inventory = builder.inventory_owner_sources(tmp_path, expected_count=1)
    source = inventory["records"][0]
    saved = tmp_path / "approved.MOV"
    rival = tmp_path / "rival.MOV"
    _write_video(rival, frames=10)
    real_capture = cv2.VideoCapture
    captured_paths: list[str] = []
    attacked = False

    def swap_path_before_decode(path: str):
        nonlocal attacked
        captured_paths.append(path)
        if attacked:
            return real_capture(path)
        attacked = True
        os.rename(video, saved)
        if replacement_kind == "regular":
            os.rename(rival, video)
        else:
            os.mkfifo(video, 0o600)
        try:
            if path == str(video):
                raise AssertionError("mutable source pathname reached decoder")
            return real_capture(path)
        finally:
            if replacement_kind == "regular":
                os.rename(video, rival)
            else:
                video.unlink()
            os.rename(saved, video)

    monkeypatch.setattr(builder.cv2, "VideoCapture", swap_path_before_decode)
    result = builder.mine_owner_video(source, uniform_limit=2, scene_limit=1)

    assert result["status"] == "V25_OWNER_VIDEO_MINED"
    assert attacked is True
    assert captured_paths and all(path.startswith("/dev/fd/") for path in captured_paths)


def test_mine_owner_video_releases_capture_on_invalid_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeCapture:
        released = False

        def isOpened(self) -> bool:
            return True

        def get(self, _key: int) -> float:
            return 0.0

        def release(self) -> None:
            self.released = True

    fake = FakeCapture()
    monkeypatch.setattr(builder.cv2, "VideoCapture", lambda _path: fake)
    source_path = tmp_path / "source.MOV"
    source_path.write_bytes(b"not-a-video")
    source = builder._snapshot_source(source_path)
    with pytest.raises(ValueError, match="video metadata"):
        builder.mine_owner_video(source)
    assert fake.released is True


def _prediction_frame(
    index: int,
    *,
    timestamp: float,
    predictions: list[dict[str, object]],
    source: str = "a" * 64,
) -> dict[str, object]:
    return {
        "source_video_sha256": source,
        "frame_index": index,
        "timestamp_sec": timestamp,
        "image_sha256": _sha(f"prediction-frame-{source}-{index}"),
        "width": 100,
        "height": 100,
        "predictions": predictions,
    }


def _box(confidence: float, xyxy: list[float]) -> dict[str, object]:
    return {"class_id": 0, "confidence": confidence, "box_xyxy": xyxy}


def test_zero_prediction_is_suspected_miss_but_never_gt() -> None:
    result = builder.classify_hardcase_signals(
        [_prediction_frame(0, timestamp=0.0, predictions=[])]
    )
    assert result[0]["signals"] == ["suspected_miss", "source_diversity"]
    assert "presence" not in result[0]
    assert "gt_boxes" not in result[0]


@pytest.mark.parametrize(
    ("confidence", "support_time", "expect_false_positive"),
    [
        (0.49, None, True),
        (0.50, None, False),
        (0.49, 2.0, False),
        (0.49, 2.01, True),
    ],
)
def test_suspected_false_positive_exact_confidence_and_two_second_boundaries(
    confidence: float,
    support_time: float | None,
    expect_false_positive: bool,
) -> None:
    frames = [
        _prediction_frame(
            0,
            timestamp=0.0,
            predictions=[_box(confidence, [20.0, 20.0, 40.0, 40.0])],
        )
    ]
    if support_time is not None:
        frames.append(
            _prediction_frame(
                1,
                timestamp=support_time,
                predictions=[_box(0.9, [20.0, 20.0, 40.0, 40.0])],
            )
        )
    result = builder.classify_hardcase_signals(frames)
    assert ("suspected_false_positive" in result[0]["signals"]) is expect_false_positive


@pytest.mark.parametrize(("right", "expected"), [(65.2, False), (66.0, True)])
def test_duplicate_iou_point_seven_boundary(right: float, expected: bool) -> None:
    result = builder.classify_hardcase_signals(
        [
            _prediction_frame(
                0,
                timestamp=0.0,
                predictions=[
                    _box(0.9, [10.0, 10.0, 90.0, 90.0]),
                    _box(0.8, [10.0, 10.0, right, 90.0]),
                ],
            )
        ]
    )
    assert ("duplicate_box_signal" in result[0]["signals"]) is expected


@pytest.mark.parametrize(
    ("box", "expected"),
    [
        ([2.0, 20.0, 30.0, 40.0], True),
        ([3.0, 20.0, 30.0, 40.0], False),
        ([70.0, 20.0, 98.0, 40.0], True),
        ([70.0, 20.0, 97.0, 40.0], False),
    ],
)
def test_partial_occlusion_spatial_two_percent_boundary(
    box: list[float], expected: bool
) -> None:
    result = builder.classify_hardcase_signals(
        [
            _prediction_frame(
                0, timestamp=0.0, predictions=[_box(0.9, box)]
            )
        ]
    )
    assert ("partial_occlusion_signal" in result[0]["signals"]) is expected
    assert "species" not in result[0]


class _Tensor:
    def __init__(self, value):
        self.value = value

    def cpu(self):
        return self

    def tolist(self):
        return self.value


class _Boxes:
    def __init__(self, xyxy, confidence):
        self.xyxy = _Tensor(xyxy)
        self.conf = _Tensor(confidence)


class _Result:
    def __init__(self, *, path: str, shape: tuple[int, int], xyxy, confidence):
        self.path = path
        self.orig_shape = shape
        self.boxes = _Boxes(xyxy, confidence)


def _private_file(path: Path, payload: bytes) -> Path:
    path.write_bytes(payload)
    path.chmod(0o600)
    return path


def _freeze_file(tmp_path: Path, checkpoint_sha: str) -> Path:
    payload = {
        "schema": "yolo26n-v24b-postprocess-freeze-v1",
        "status": "V24B_POSTPROCESS_FROZEN_DEVELOPMENT_ONLY",
        "checkpoint_sha256": checkpoint_sha,
        "selected": {"confidence": 0.25, "nms_iou": 0.40, "duplicate": 4},
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "git_write_count": 0,
    }
    return _private_file(
        tmp_path / "freeze.private.json",
        (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )


def _runtime_fingerprint() -> dict[str, str]:
    return {
        "python_binary_sha256": "1" * 64,
        "uv_lock_sha256": "2" * 64,
        "distributions_sha256": "3" * 64,
        "site_packages_tree_sha256": "c" * 64,
        "ultralytics_version": "8.4.104",
        "ultralytics_tree_sha256": "4" * 64,
        "torch_version": "2.12.0",
        "torch_tree_sha256": "8" * 64,
        "torchvision_version": "0.27.0",
        "torchvision_tree_sha256": "9" * 64,
        "numpy_version": "2.4.4",
        "numpy_tree_sha256": "a" * 64,
        "opencv_version": "5.0.0",
        "opencv_tree_sha256": "7" * 64,
        "pillow_version": "12.2.0",
        "pillow_tree_sha256": "b" * 64,
    }


def _runtime_preflight(checkpoint_sha: str) -> dict[str, object]:
    return {
        "schema": "yolo26n-v24b-runtime-preflight-v1",
        "status": "PREFLIGHT_OK",
        "implementation_commit": "a" * 40,
        "code_bundle_sha256": "5" * 64,
        "checkpoint_sha256": checkpoint_sha,
        "dataset_manifest_sha256": "6" * 64,
        "runtime": _runtime_fingerprint(),
        "prohibited_inputs": ["internal-test151", "owner-external60"],
        "writes": ["private-local-artifacts-only"],
    }


def _shadow_frame() -> dict[str, object]:
    payload = builder.encode_jpeg(Image.new("RGB", (100, 80), "black"))
    return {
        "role": "owner-development-video",
        "source_video_sha256": "a" * 64,
        "frame_index": 0,
        "timestamp_sec": 0.0,
        "image_sha256": hashlib.sha256(payload).hexdigest(),
        "dhash64": builder.historical_dhash64(payload),
        "width": 100,
        "height": 80,
        "jpeg_bytes": payload,
        "selection_reasons": ["uniform"],
    }


def test_shadow_inference_uses_verified_checkpoint_bytes_and_frozen_parameters(
    tmp_path: Path,
) -> None:
    checkpoint = _private_file(tmp_path / "model.pt", b"approved-checkpoint")
    checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    freeze = _freeze_file(tmp_path, checkpoint_sha)
    calls: dict[str, object] = {}

    class Model:
        def predict(self, **kwargs):
            calls.update(kwargs)
            return [
                _Result(
                    path="image0.jpg",
                    shape=(80, 100),
                    xyxy=[[10.0, 20.0, 30.0, 40.0]],
                    confidence=[0.49],
                )
            ]

    def factory(capability):
        assert capability.payload == b"approved-checkpoint"
        assert capability.sha256 == checkpoint_sha
        return Model()

    result = builder.run_shadow_inference(
        [_shadow_frame()],
        checkpoint=checkpoint,
        expected_checkpoint_sha256=checkpoint_sha,
        freeze=freeze,
        expected_freeze_sha256=hashlib.sha256(freeze.read_bytes()).hexdigest(),
        expected_runtime_fingerprint=_runtime_fingerprint(),
        runtime_probe=_runtime_fingerprint,
        model_factory=factory,
    )

    assert calls["conf"] == 0.25
    assert calls["iou"] == 0.40
    assert calls["imgsz"] == 960
    assert calls["max_det"] == 50
    assert result[0]["predictions"] == [
        {"class_id": 0, "confidence": 0.49, "box_xyxy": [10.0, 20.0, 30.0, 40.0]}
    ]


def test_shadow_inference_accepts_actual_duplicate_four_freeze_contract(
    tmp_path: Path,
) -> None:
    checkpoint = _private_file(tmp_path / "model.pt", b"approved-checkpoint")
    checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    freeze = _freeze_file(tmp_path, checkpoint_sha)
    payload = json.loads(freeze.read_bytes())
    payload["selected"]["duplicate"] = 4
    freeze.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    freeze.chmod(0o600)

    class Model:
        def predict(self, **_kwargs):
            return [_Result(path="image0.jpg", shape=(80, 100), xyxy=[], confidence=[])]

    result = builder.run_shadow_inference(
        [_shadow_frame()],
        checkpoint=checkpoint,
        expected_checkpoint_sha256=checkpoint_sha,
        freeze=freeze,
        expected_freeze_sha256=hashlib.sha256(freeze.read_bytes()).hexdigest(),
        expected_runtime_fingerprint=_runtime_fingerprint(),
        runtime_probe=_runtime_fingerprint,
        model_factory=lambda _capability: Model(),
    )
    assert result[0]["predictions"] == []


def test_runtime_preflight_rejects_model_pin_and_runtime_drift() -> None:
    checkpoint_sha = "a" * 64
    payload = _runtime_preflight(checkpoint_sha)
    expected = _runtime_fingerprint()

    assert builder.validate_runtime_preflight(
        payload,
        expected_checkpoint_sha256=checkpoint_sha,
        expected_code_sha256="5" * 64,
        expected_dataset_manifest_sha256="6" * 64,
        runtime_probe=lambda: dict(expected),
    ) == expected

    drifted = {**expected, "ultralytics_tree_sha256": "b" * 64}
    with pytest.raises(ValueError, match="runtime fingerprint"):
        builder.validate_runtime_preflight(
            payload,
            expected_checkpoint_sha256=checkpoint_sha,
            expected_code_sha256="5" * 64,
            expected_dataset_manifest_sha256="6" * 64,
            runtime_probe=lambda: drifted,
        )
    with pytest.raises(ValueError, match="runtime fingerprint"):
        builder.validate_runtime_preflight(
            payload,
            expected_checkpoint_sha256="c" * 64,
            expected_code_sha256="5" * 64,
            expected_dataset_manifest_sha256="6" * 64,
            runtime_probe=lambda: dict(expected),
        )
    for field, value in (
        ("expected_code_sha256", "7" * 64),
        ("expected_dataset_manifest_sha256", "8" * 64),
    ):
        kwargs = {
            "expected_checkpoint_sha256": checkpoint_sha,
            "expected_code_sha256": "5" * 64,
            "expected_dataset_manifest_sha256": "6" * 64,
            "runtime_probe": lambda: dict(expected),
        }
        kwargs[field] = value
        with pytest.raises(ValueError, match="runtime fingerprint"):
            builder.validate_runtime_preflight(payload, **kwargs)


def test_runtime_tree_reader_consumes_opened_regular_inode_during_pathname_aba(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = tmp_path / "approved.py"
    approved.write_bytes(b"approved-runtime")
    rival = tmp_path / "rival.py"
    rival.write_bytes(b"rival-runtime")
    saved = tmp_path / "saved.py"
    real_open = os.open

    def open_then_swap(path: str | os.PathLike[str], flags: int) -> int:
        descriptor = real_open(path, flags)
        os.rename(approved, saved)
        os.rename(rival, approved)
        return descriptor

    monkeypatch.setattr(builder.os, "open", open_then_swap)
    try:
        assert builder._read_regular_file_bytes(approved) == b"approved-runtime"
    finally:
        if saved.exists():
            os.rename(approved, rival)
            os.rename(saved, approved)


def test_shadow_inference_rechecks_runtime_after_model_execution(
    tmp_path: Path,
) -> None:
    checkpoint = _private_file(tmp_path / "model.pt", b"approved-checkpoint")
    checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    freeze = _freeze_file(tmp_path, checkpoint_sha)
    freeze_payload = json.loads(freeze.read_bytes())
    freeze_payload["selected"]["duplicate"] = 4
    freeze.write_text(
        json.dumps(freeze_payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    freeze.chmod(0o600)
    expected = _runtime_fingerprint()
    calls = 0

    def probe() -> dict[str, str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return dict(expected)
        return {**expected, "distributions_sha256": "f" * 64}

    class Model:
        def predict(self, **_kwargs):
            return [_Result(path="image0.jpg", shape=(80, 100), xyxy=[], confidence=[])]

    with pytest.raises(ValueError, match="runtime changed during inference"):
        builder.run_shadow_inference(
            [_shadow_frame()],
            checkpoint=checkpoint,
            expected_checkpoint_sha256=checkpoint_sha,
            freeze=freeze,
            expected_freeze_sha256=hashlib.sha256(freeze.read_bytes()).hexdigest(),
            expected_runtime_fingerprint=expected,
            runtime_probe=probe,
            model_factory=lambda _capability: Model(),
        )
    assert calls == 2


def test_shadow_inference_detects_checkpoint_path_replacement_after_factory(
    tmp_path: Path,
) -> None:
    checkpoint = _private_file(tmp_path / "model.pt", b"approved-checkpoint")
    checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    freeze = _freeze_file(tmp_path, checkpoint_sha)

    class Model:
        def predict(self, **_kwargs):
            return [_Result(path="image0.jpg", shape=(80, 100), xyxy=[], confidence=[])]

    def factory(capability):
        assert capability.payload == b"approved-checkpoint"
        rival = _private_file(tmp_path / "rival.pt", b"rival-checkpoint")
        os.replace(rival, checkpoint)
        return Model()

    with pytest.raises(ValueError, match="checkpoint changed after validation"):
        builder.run_shadow_inference(
            [_shadow_frame()],
            checkpoint=checkpoint,
            expected_checkpoint_sha256=checkpoint_sha,
            freeze=freeze,
            expected_freeze_sha256=hashlib.sha256(freeze.read_bytes()).hexdigest(),
            expected_runtime_fingerprint=_runtime_fingerprint(),
            runtime_probe=_runtime_fingerprint,
            model_factory=factory,
        )


@pytest.mark.parametrize("role", ["validation153", "internal-test151", "owner-external60"])
def test_shadow_inference_rejects_protected_roles_before_model_load(
    tmp_path: Path, role: str
) -> None:
    checkpoint = _private_file(tmp_path / "model.pt", b"approved-checkpoint")
    checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    freeze = _freeze_file(tmp_path, checkpoint_sha)
    frame = _shadow_frame()
    frame["role"] = role
    called = False

    def factory(_capability):
        nonlocal called
        called = True
        raise AssertionError("must not load model")

    with pytest.raises(ValueError, match="protected role"):
        builder.run_shadow_inference(
            [frame],
            checkpoint=checkpoint,
            expected_checkpoint_sha256=checkpoint_sha,
            freeze=freeze,
            expected_freeze_sha256=hashlib.sha256(freeze.read_bytes()).hexdigest(),
            expected_runtime_fingerprint=_runtime_fingerprint(),
            runtime_probe=_runtime_fingerprint,
            model_factory=factory,
        )
    assert called is False


def _queue_record(index: int, source_index: int, signal: str) -> dict[str, object]:
    payload = builder.encode_jpeg(Image.new("RGB", (40, 30), (index, 0, 0)))
    return {
        "role": "owner-development-video",
        "source_video_sha256": _sha(f"queue-source-{source_index}"),
        "frame_index": index,
        "timestamp_sec": float(index),
        "image_sha256": hashlib.sha256(payload).hexdigest(),
        "dhash64": builder.historical_dhash64(payload),
        "width": 40,
        "height": 30,
        "jpeg_bytes": payload,
        "selection_reasons": ["uniform"],
        "predictions": [],
        "signals": [signal, "source_diversity"] if signal != "source_diversity" else [signal],
    }


def test_select_blind_queue_round_robins_sources_and_applies_caps() -> None:
    records = [
        _queue_record(index, 0, "suspected_miss") for index in range(10)
    ] + [
        _queue_record(100 + index, 1, "duplicate_box_signal") for index in range(3)
    ]
    selected = builder.select_blind_queue(records, per_source_cap=2, total_cap=3)
    assert len(selected) == 3
    assert len({row["source_video_sha256"] for row in selected[:2]}) == 2
    assert sum(row["source_video_sha256"] == _sha("queue-source-0") for row in selected) <= 2


def test_build_blind_queue_publishes_anonymous_atomic_bundle(tmp_path: Path) -> None:
    output = tmp_path / "queue-result"
    records = [
        _queue_record(0, 0, "suspected_miss"),
        _queue_record(1, 1, "duplicate_box_signal"),
    ]

    result = builder.build_blind_queue(records, output_dir=output)

    assert result["status"] == "V25_BLIND_QUEUE_READY"
    assert result["queue_count"] == 2
    assert stat.S_IMODE(output.lstat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(path.lstat().st_mode) == (0o700 if path.is_dir() else 0o600)
        for path in output.rglob("*")
    )
    public_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (output / "cvat").iterdir()
        if path.suffix in {".json", ".md"}
    )
    assert "predictions" not in public_text
    assert "source_video_sha256" not in public_text
    assert _sha("queue-source-0") not in public_text
    with pytest.raises(FileExistsError):
        builder.build_blind_queue(records, output_dir=output)


def test_build_blind_queue_empty_is_shortage_without_output(tmp_path: Path) -> None:
    output = tmp_path / "queue-result"
    result = builder.build_blind_queue([], output_dir=output)
    assert result["status"] == "V25_HARDCASE_QUEUE_SHORTAGE"
    assert not output.exists()


def test_build_blind_queue_rejects_staging_directory_aba(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "queue-result"
    owned_backup = tmp_path / "owned-backup"
    original_exchange = builder._atomic_exchange_paths
    attacked = False

    def swap_then_exchange(left: Path, right: Path) -> None:
        nonlocal attacked
        if not attacked and left.name.startswith(".queue-result") and right == output:
            attacked = True
            os.rename(left, owned_backup)
            shutil.copytree(owned_backup, left, copy_function=shutil.copy2)
        original_exchange(left, right)

    monkeypatch.setattr(builder, "_atomic_exchange_paths", swap_then_exchange)
    with pytest.raises(ValueError, match="publication identity"):
        builder.build_blind_queue([_queue_record(0, 0, "suspected_miss")], output_dir=output)
    assert owned_backup.is_dir()
    assert not output.exists()


def test_build_blind_queue_quarantines_owned_final_on_late_failure(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "queue-result"
    original = builder.directory_contract_sha256
    calls = 0

    def fail_after_publish(root: Path) -> str:
        nonlocal calls
        calls += 1
        value = original(root)
        if root == output:
            return "0" * 64
        return value

    monkeypatch.setattr(builder, "directory_contract_sha256", fail_after_publish)
    with pytest.raises(ValueError, match="publication identity"):
        builder.build_blind_queue(
            [_queue_record(0, 0, "suspected_miss")], output_dir=output
        )
    assert calls > 0
    assert not output.exists()


def test_directory_publication_restores_rival_destination_after_reservation_aba(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "queue-result"
    saved_reservation = tmp_path / "saved-reservation"
    original_exchange = builder._atomic_exchange_paths
    rival_inode: int | None = None
    attacked = False

    def replace_destination_then_exchange(left: Path, right: Path) -> None:
        nonlocal attacked, rival_inode
        if not attacked and right == output and left.name.startswith(".queue-result"):
            attacked = True
            os.rename(right, saved_reservation)
            right.mkdir(mode=0o700)
            rival_inode = right.lstat().st_ino
        original_exchange(left, right)

    monkeypatch.setattr(builder, "_atomic_exchange_paths", replace_destination_then_exchange)
    with pytest.raises(ValueError, match="publication identity"):
        builder.build_blind_queue(
            [_queue_record(0, 0, "suspected_miss")], output_dir=output
        )
    assert output.is_dir()
    assert output.lstat().st_ino == rival_inode
    assert not (output / "cvat").exists()


def test_directory_contract_rejects_fifo_without_opening_it(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    root.mkdir(mode=0o700)
    fifo = root / "blocked.private"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(ValueError, match="regular"):
        builder.directory_contract_sha256(root)


def test_prediction_ledger_is_private_one_shot_and_pins_full_provenance(
    tmp_path: Path,
) -> None:
    record = _queue_record(0, 0, "suspected_miss")
    output = tmp_path / "prediction.private.json"
    pins = {
        "input_audit_sha256": "1" * 64,
        "historical_fingerprint_sha256": "2" * 64,
        "checkpoint_sha256": "3" * 64,
        "freeze_sha256": "4" * 64,
        "code_sha256": "5" * 64,
        "runtime_sha256": "6" * 64,
    }

    digest = builder.publish_prediction_ledger(
        records=[record], output=output, **pins
    )

    payload = json.loads(output.read_bytes())
    assert payload["status"] == "V25_SHADOW_PREDICTIONS_READY"
    assert payload["provenance"] == pins
    assert payload["postprocess_selected"] == {
        "confidence": 0.25,
        "nms_iou": 0.40,
        "duplicate": 4,
    }
    assert "jpeg_bytes" not in payload["records"][0]
    assert stat.S_IMODE(output.lstat().st_mode) == 0o600
    assert digest == hashlib.sha256(output.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        builder.publish_prediction_ledger(records=[record], output=output, **pins)


def test_prediction_ledger_rejects_protected_role_and_bad_pin(tmp_path: Path) -> None:
    record = _queue_record(0, 0, "suspected_miss")
    record["role"] = "validation153"
    pins = {
        "input_audit_sha256": "1" * 64,
        "historical_fingerprint_sha256": "2" * 64,
        "checkpoint_sha256": "3" * 64,
        "freeze_sha256": "4" * 64,
        "code_sha256": "5" * 64,
        "runtime_sha256": "bad",
    }
    with pytest.raises(ValueError, match="prediction ledger provenance"):
        builder.publish_prediction_ledger(
            records=[record], output=tmp_path / "must-not-exist.json", **pins
        )


def test_stage_lock_is_0600_one_shot_and_records_zero_writes(tmp_path: Path) -> None:
    lock = tmp_path / "inventory.started.private.json"
    final_output = tmp_path / "inventory.private.json"
    provenance = {"input_audit_sha256": "1" * 64}
    digest = builder.publish_stage_lock(
        stage="inventory",
        output=lock,
        final_output=final_output,
        provenance=provenance,
    )
    payload = json.loads(lock.read_bytes())
    assert payload["status"] == "STARTED"
    assert payload["stage"] == "inventory"
    assert payload["final_output"] == str(final_output)
    assert payload["provenance"] == provenance
    assert payload["db_write_count"] == payload["r2_write_count"] == 0
    assert digest == hashlib.sha256(lock.read_bytes()).hexdigest()
    assert stat.S_IMODE(lock.lstat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        builder.publish_stage_lock(
            stage="inventory",
            output=lock,
            final_output=final_output,
            provenance=provenance,
        )


def test_build_queue_from_prediction_ledger_rejects_arbitrary_predictions(
    tmp_path: Path,
) -> None:
    record = _queue_record(0, 0, "suspected_miss")
    ledger_path = tmp_path / "prediction.private.json"
    pins = {
        "input_audit_sha256": "1" * 64,
        "historical_fingerprint_sha256": "2" * 64,
        "checkpoint_sha256": "3" * 64,
        "freeze_sha256": "4" * 64,
        "code_sha256": "5" * 64,
        "runtime_sha256": "6" * 64,
    }
    ledger_sha = builder.publish_prediction_ledger(
        records=[record], output=ledger_path, **pins
    )
    rival = dict(record)
    rival["signals"] = ["source_diversity"]
    with pytest.raises(ValueError, match="prediction ledger frame mismatch"):
        builder.build_blind_queue_from_prediction_ledger(
            records=[rival],
            prediction_ledger=ledger_path,
            expected_prediction_ledger_sha256=ledger_sha,
            expected_provenance=pins,
            output_dir=tmp_path / "must-not-exist",
        )


def test_queue_consumer_rejects_forged_or_missing_prediction_provenance(
    tmp_path: Path,
) -> None:
    record = _queue_record(0, 0, "suspected_miss")
    ledger = {
        "schema": "yolo26n-v25-shadow-prediction-ledger-v1",
        "status": "V25_SHADOW_PREDICTIONS_READY",
        "role": "owner-development-video",
        "record_count": 1,
        "records": [{key: value for key, value in record.items() if key != "jpeg_bytes"}],
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "production_model_write_count": 0,
    }
    path = _private_file(tmp_path / "forged.private.json", (json.dumps(ledger) + "\n").encode())
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="prediction ledger frame mismatch"):
        builder.build_blind_queue_from_prediction_ledger(
            records=[record],
            prediction_ledger=path,
            expected_prediction_ledger_sha256=sha,
            expected_provenance={
                "input_audit_sha256": "1" * 64,
                "historical_fingerprint_sha256": "2" * 64,
                "checkpoint_sha256": "3" * 64,
                "freeze_sha256": "4" * 64,
                "code_sha256": "5" * 64,
                "runtime_sha256": "6" * 64,
            },
            output_dir=tmp_path / "must-not-exist",
        )


def test_dedup_frame_bundle_round_trip_is_private_and_cross_pinned(tmp_path: Path) -> None:
    records = [_shadow_frame()]
    provenance = {
        "input_audit_sha256": "1" * 64,
        "historical_fingerprint_sha256": "2" * 64,
        "code_sha256": "3" * 64,
        "dedup_ledger_sha256": "4" * 64,
    }
    output = tmp_path / "dedup-frame-bundle"

    digest = builder.materialize_dedup_frame_bundle(
        records=records, output_dir=output, provenance=provenance
    )
    loaded = builder.load_dedup_frame_bundle(
        bundle_dir=output,
        expected_bundle_sha256=digest,
        expected_provenance=provenance,
    )

    assert loaded == records
    assert stat.S_IMODE(output.lstat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(path.lstat().st_mode) == (0o700 if path.is_dir() else 0o600)
        for path in output.rglob("*")
    )


def test_dedup_frame_bundle_rejects_changed_image_or_provenance(tmp_path: Path) -> None:
    record = _shadow_frame()
    provenance = {
        "input_audit_sha256": "1" * 64,
        "historical_fingerprint_sha256": "2" * 64,
        "code_sha256": "3" * 64,
        "dedup_ledger_sha256": "4" * 64,
    }
    output = tmp_path / "dedup-frame-bundle"
    digest = builder.materialize_dedup_frame_bundle(
        records=[record], output_dir=output, provenance=provenance
    )
    image = next((output / "images").iterdir())
    image.write_bytes(b"changed")
    image.chmod(0o600)
    with pytest.raises(ValueError, match="dedup frame bundle"):
        builder.load_dedup_frame_bundle(
            bundle_dir=output,
            expected_bundle_sha256=digest,
            expected_provenance=provenance,
        )


def test_builder_cli_exposes_cross_runtime_prepare_and_consume() -> None:
    parser = builder.build_parser()
    assert parser.parse_args(["prepare-owner-bundle", "--help-contract"]).command == "prepare-owner-bundle"
    assert parser.parse_args(["infer-build-queue", "--help-contract"]).command == "infer-build-queue"


def test_cross_runtime_cli_prints_all_downstream_sha_pins(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        builder,
        "prepare_owner_bundle",
        lambda **_kwargs: {
            "status": "V25_DEDUP_FRAME_BUNDLE_READY",
            "source_count": 35,
            "mined_count": 10,
            "dedup_count": 8,
            "dedup_ledger_sha256": "1" * 64,
            "bundle_sha256": "2" * 64,
        },
    )
    assert builder.main(
        [
            "prepare-owner-bundle",
            "--source-root", "/private/source",
            "--attempt-root", "/private/attempt",
            "--input-audit", "/private/audit.json",
            "--historical-fingerprints", "/private/historical.json",
            "--expected-input-audit-sha256", "3" * 64,
            "--expected-historical-fingerprint-sha256", "4" * 64,
            "--expected-freeze-sha256", "5" * 64,
            "--expected-code-sha256", "6" * 64,
        ]
    ) == 0
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["dedup_ledger_sha256"] == "1" * 64
    assert prepared["bundle_sha256"] == "2" * 64

    monkeypatch.setattr(
        builder,
        "infer_build_queue_from_bundle",
        lambda **_kwargs: {
            "status": "V25_BLIND_QUEUE_READY",
            "queue_count": 8,
            "prediction_ledger_sha256": "7" * 64,
            "queue_sha256": "8" * 64,
        },
    )
    read_descriptor, write_descriptor = os.pipe()
    os.write(
        write_descriptor,
        (
            json.dumps(
                {
                    "schema": "yolo26n-v25-launch-capability-v1",
                    "status": "LAUNCH_VERIFIED",
                    "runtime_build_sha256": "d" * 64,
                    "runtime_preflight_sha256": "a" * 64,
                    "inference_code_sha256": "6" * 64,
                    "inference_code_bundle_sha256": "e" * 64,
                    "nonce": "f" * 64,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode(),
    )
    os.close(write_descriptor)
    monkeypatch.setenv("V25_LAUNCH_CAPABILITY_FD", str(read_descriptor))
    assert builder.main(
        [
            "infer-build-queue",
            "--bundle-dir", "/private/bundle",
            "--attempt-root", "/private/runtime-attempt",
            "--input-audit", "/private/audit.json",
            "--historical-fingerprints", "/private/historical.json",
            "--checkpoint", "/private/model.pt",
            "--freeze", "/private/freeze.json",
            "--runtime-preflight", "/private/runtime.json",
            "--expected-bundle-sha256", "2" * 64,
            "--expected-dedup-ledger-sha256", "1" * 64,
            "--expected-input-audit-sha256", "3" * 64,
            "--expected-historical-fingerprint-sha256", "4" * 64,
            "--expected-checkpoint-sha256", "9" * 64,
            "--expected-freeze-sha256", "5" * 64,
            "--expected-runtime-sha256", "a" * 64,
            "--expected-code-sha256", "6" * 64,
            "--expected-runtime-build-sha256", "d" * 64,
            "--expected-inference-code-bundle-sha256", "e" * 64,
        ]
    ) == 0
    consumed = json.loads(capsys.readouterr().out)
    assert consumed["prediction_ledger_sha256"] == "7" * 64
    assert consumed["queue_sha256"] == "8" * 64


def test_builder_cli_exposes_ordered_private_pipeline() -> None:
    parser = builder.build_parser()
    args = parser.parse_args(["run-owner-pipeline", "--help-contract"])
    assert args.command == "run-owner-pipeline"
    assert args.help_contract is True


def test_legacy_all_in_one_cli_is_superseded_by_verified_launcher() -> None:
    with pytest.raises(ValueError, match="superseded.*verified launcher"):
        builder.main(["run-owner-pipeline"])


def test_owner_pipeline_historical_gate_rejects_empty_or_wrong_policy() -> None:
    with pytest.raises(ValueError, match="historical fingerprint contract"):
        builder.validate_historical_fingerprints(
            {
                "schema": "yolo26n-v24b-historical-fingerprint-exclusions-v1",
                "status": "V24B_HISTORICAL_FINGERPRINTS_FROZEN",
                "records": [],
            },
            expected_freeze_sha256="4" * 64,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(db_write_count=1),
        lambda payload: payload.update(source_clip_ref="must-not-be-present"),
        lambda payload: payload.update(gate_policy="include-reviewed"),
        lambda payload: payload.update(gate_candidate_count=1),
        lambda payload: payload.update(gate_inputs_consumed=True),
    ],
)
def test_owner_only_audit_consumer_rejects_writes_or_gate_identity(mutation) -> None:
    historical_sha = "1" * 64
    payload = {
        "schema": "yolo26n-v25-owner-only-input-audit-v1",
        "status": "V25_OWNER_ONLY_INPUT_AUDIT_READY",
        "gate_policy": "quarantine_all",
        "gate_candidate_count": 0,
        "gate_inputs_consumed": False,
        "protected_role_counts": {
            "validation153": 153,
            "internal-test151": 151,
            "owner-external60": 60,
        },
        "historical_unique_image_count": 1822,
        "input_sha256": {
            "v24_dataset": "2" * 64,
            "historical_fingerprints": historical_sha,
        },
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "production_model_write_count": 0,
        "gme_write_count": 0,
        "labeling_web_write_count": 0,
    }
    mutation(payload)
    with pytest.raises(ValueError, match="owner pipeline private input contract"):
        builder._validate_owner_only_audit(
            payload,
            expected_historical_fingerprint_sha256=historical_sha,
        )


def test_owner_pipeline_publishes_ordered_one_shot_ledgers_and_queue(
    tmp_path: Path,
) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    _write_video(sources / "one.MOV", frames=10, fps=5.0)
    checkpoint = _private_file(tmp_path / "model.pt", b"approved-checkpoint")
    checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    freeze = _freeze_file(tmp_path, checkpoint_sha)
    input_audit = _private_file(
        tmp_path / "audit.private.json",
        (
            json.dumps(
                {
                    "schema": "yolo26n-v25-owner-only-input-audit-v1",
                    "status": "V25_OWNER_ONLY_INPUT_AUDIT_READY",
                    "gate_policy": "quarantine_all",
                    "gate_candidate_count": 0,
                    "gate_inputs_consumed": False,
                    "protected_role_counts": {
                        "validation153": 153,
                        "internal-test151": 0,
                        "owner-external60": 0,
                    },
                    "historical_unique_image_count": 0,
                    "input_sha256": {
                        "v24_dataset": "1" * 64,
                        "historical_fingerprints": "HISTORICAL_SHA_PLACEHOLDER"
                    },
                    "db_write_count": 0,
                    "r2_write_count": 0,
                    "service_write_count": 0,
                    "production_model_write_count": 0,
                    "gme_write_count": 0,
                    "labeling_web_write_count": 0,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode(),
    )
    historical = _private_file(
        tmp_path / "historical.private.json",
        (
            json.dumps(
                {
                    "schema": "yolo26n-v24b-historical-fingerprint-exclusions-v1",
                    "status": "V24B_HISTORICAL_FINGERPRINTS_FROZEN",
                    "freeze_sha256": hashlib.sha256(freeze.read_bytes()).hexdigest(),
                    "artifact_sha256": {
                        "dataset": "1" * 64,
                        "internal-test151": "2" * 64,
                        "owner-external60": "3" * 64,
                        "owner-external-snapshot": "4" * 64,
                    },
                    "role_counts": {
                        "dataset": 0,
                        "internal-test151": 0,
                        "owner-external60": 0,
                    },
                    "unique_image_count": 0,
                    "fingerprint_policy": {
                        "algorithm": "dhash64",
                        "version": "pillow-rgb-luma-9x8-box-right-gt-left-v1",
                        "pillow_version": "12.2.0",
                        "scope": "global-historical",
                        "hamming_reject_max_distance": 2,
                    },
                    "records": [],
                    "db_write_count": 0,
                    "r2_write_count": 0,
                    "service_write_count": 0,
                    "git_write_count": 0,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode(),
    )
    audit_payload = json.loads(input_audit.read_bytes())
    audit_payload["input_sha256"]["historical_fingerprints"] = hashlib.sha256(
        historical.read_bytes()
    ).hexdigest()
    input_audit.write_text(
        json.dumps(audit_payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    input_audit.chmod(0o600)
    runtime_payload = _runtime_preflight(checkpoint_sha)
    runtime_payload["code_bundle_sha256"] = hashlib.sha256(
        Path(builder.__file__).read_bytes()
    ).hexdigest()
    runtime_payload["dataset_manifest_sha256"] = "1" * 64
    runtime = _private_file(
        tmp_path / "runtime.private.json",
        (
            json.dumps(
                runtime_payload,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode(),
    )

    class Model:
        def predict(self, **kwargs):
            return [
                _Result(path=f"image{index}.jpg", shape=(48, 64), xyxy=[], confidence=[])
                for index, _ in enumerate(kwargs["source"])
            ]

    result = builder.run_owner_pipeline(
        source_root=sources,
        attempt_root=tmp_path / "attempt",
        input_audit=input_audit,
        expected_input_audit_sha256=hashlib.sha256(input_audit.read_bytes()).hexdigest(),
        historical_fingerprints=historical,
        expected_historical_fingerprint_sha256=hashlib.sha256(historical.read_bytes()).hexdigest(),
        checkpoint=checkpoint,
        expected_checkpoint_sha256=checkpoint_sha,
        freeze=freeze,
        expected_freeze_sha256=hashlib.sha256(freeze.read_bytes()).hexdigest(),
        runtime_preflight=runtime,
        expected_runtime_sha256=hashlib.sha256(runtime.read_bytes()).hexdigest(),
        expected_code_sha256=hashlib.sha256(Path(builder.__file__).read_bytes()).hexdigest(),
        expected_historical_unique_count=0,
        expected_historical_role_counts={
            "dataset": 0,
            "internal-test151": 0,
            "owner-external60": 0,
        },
        runtime_probe=_runtime_fingerprint,
        model_factory=lambda _capability: Model(),
    )

    attempt = tmp_path / "attempt"
    assert result["status"] == "V25_BLIND_QUEUE_READY"
    assert result["queue_sha256"] == builder.directory_contract_sha256(
        attempt / "blind-queue"
    )
    assert all((attempt / f"{stage}.started.private.json").is_file() for stage in ("inventory", "mining", "dedup", "prediction", "queue"))
    assert all(stat.S_IMODE(path.lstat().st_mode) == 0o600 for path in attempt.glob("*.json"))
    assert (attempt / "blind-queue" / "cvat-upload.zip").is_file()
    downstream = b"".join(
        path.read_bytes()
        for path in attempt.rglob("*")
        if path.is_file() and path.suffix != ".zip"
    )
    assert b"source_relpath" not in downstream
    assert b"boxes_xywh" not in downstream
    assert b"gate_quarantine" not in downstream
    assert b"operational_labeled_count" not in downstream
    assert b"lineage_covered_count" not in downstream
    assert b"1951" not in downstream
    assert b"1373" not in downstream
    with pytest.raises(ValueError, match="owner pipeline preflight"):
        builder.run_owner_pipeline(
            source_root=sources,
            attempt_root=attempt,
            input_audit=input_audit,
            expected_input_audit_sha256=hashlib.sha256(input_audit.read_bytes()).hexdigest(),
            historical_fingerprints=historical,
            expected_historical_fingerprint_sha256=hashlib.sha256(historical.read_bytes()).hexdigest(),
            checkpoint=checkpoint,
            expected_checkpoint_sha256=checkpoint_sha,
            freeze=freeze,
            expected_freeze_sha256=hashlib.sha256(freeze.read_bytes()).hexdigest(),
            runtime_preflight=runtime,
            expected_runtime_sha256=hashlib.sha256(runtime.read_bytes()).hexdigest(),
            expected_code_sha256=hashlib.sha256(Path(builder.__file__).read_bytes()).hexdigest(),
            expected_historical_unique_count=0,
            expected_historical_role_counts={
                "dataset": 0,
                "internal-test151": 0,
                "owner-external60": 0,
            },
            runtime_probe=_runtime_fingerprint,
            model_factory=lambda _capability: Model(),
        )

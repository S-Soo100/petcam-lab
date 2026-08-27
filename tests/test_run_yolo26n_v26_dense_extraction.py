from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np
import pytest

import scripts.run_yolo26n_v26_dense_extraction as dense_extraction
from scripts.run_yolo26n_v26_dense_extraction import (
    extract_video_to_directory,
    validate_completed_clip,
)


def _write_video(path: Path, *, frames: int = 20, fps: float = 10.0) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 48))
    assert writer.isOpened()
    try:
        for index in range(frames):
            image = np.zeros((48, 64, 3), dtype=np.uint8)
            image[:, :, 1] = index * 10
            writer.write(image)
    finally:
        writer.release()


class _FakeCapture:
    def __init__(self, *, decoded_frames: int, reported_frames: int) -> None:
        self._frames = [np.zeros((48, 64, 3), dtype=np.uint8) for _ in range(decoded_frames)]
        self._reported_frames = reported_frames
        self._index = 0

    def isOpened(self) -> bool:
        return True

    def get(self, property_id: int) -> float:
        return {
            cv2.CAP_PROP_FPS: 10.0,
            cv2.CAP_PROP_FRAME_COUNT: float(self._reported_frames),
            cv2.CAP_PROP_FRAME_WIDTH: 64.0,
            cv2.CAP_PROP_FRAME_HEIGHT: 48.0,
        }[property_id]

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._index == len(self._frames):
            return False, None
        frame = self._frames[self._index]
        self._index += 1
        return True, frame

    def release(self) -> None:
        pass


def test_extractor_decodes_full_video_and_records_exact_two_fps_samples(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    destination = tmp_path / "complete"
    _write_video(video)

    completion = extract_video_to_directory(
        video,
        destination,
        clip_ref="clip-a",
        camera_night="camera-a:2026-08-24",
        expected_size_bytes=video.stat().st_size,
        sample_fps=2.0,
    )

    rows = [json.loads(line) for line in (destination / "ledger.jsonl").read_text().splitlines()]
    assert completion["decoded_frame_count"] == 20
    assert completion["sampled_frame_count"] == 4
    assert [row["timestamp_ms"] for row in rows] == [0, 500, 1000, 1500]
    assert all(len(row["image_sha256"]) == 64 for row in rows)
    assert rows[0]["motion_score"] == 0.0
    assert rows[1]["motion_score"] > 0.0


def test_extractor_writes_source_and_ledger_lineage_that_revalidates(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    destination = tmp_path / "complete"
    _write_video(video, frames=10, fps=5.0)

    completion = extract_video_to_directory(
        video,
        destination,
        clip_ref="clip-a",
        camera_night="camera-a:2026-08-24",
        expected_size_bytes=video.stat().st_size,
    )

    assert completion["source_sha256"] == hashlib.sha256(video.read_bytes()).hexdigest()
    assert validate_completed_clip(
        destination,
        expected_clip_ref="clip-a",
        expected_camera_night="camera-a:2026-08-24",
        expected_size_bytes=video.stat().st_size,
        expected_sample_fps=2.0,
        expected_source_sha256=completion["source_sha256"],
    ) == completion


@pytest.mark.parametrize(
    ("decoded_frames", "reported_frames", "error"),
    [
        (5, 100, "before expected EOF"),
        (120, 100, "exceeds reported frame count"),
    ],
)
def test_extractor_rejects_decoded_count_outside_metadata_tolerance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    decoded_frames: int,
    reported_frames: int,
    error: str,
) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"fake-video")
    monkeypatch.setattr(
        dense_extraction.cv2,
        "VideoCapture",
        lambda _path: _FakeCapture(
            decoded_frames=decoded_frames,
            reported_frames=reported_frames,
        ),
    )

    with pytest.raises(ValueError, match=error):
        extract_video_to_directory(
            video,
            tmp_path / "complete",
            clip_ref="clip-a",
            camera_night="camera-a:2026-08-24",
            expected_size_bytes=video.stat().st_size,
        )


def test_extractor_accepts_one_frame_of_opencv_metadata_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"fake-video")
    monkeypatch.setattr(
        dense_extraction.cv2,
        "VideoCapture",
        lambda _path: _FakeCapture(decoded_frames=99, reported_frames=100),
    )

    completion = extract_video_to_directory(
        video,
        tmp_path / "complete",
        clip_ref="clip-a",
        camera_night="camera-a:2026-08-24",
        expected_size_bytes=video.stat().st_size,
    )

    assert completion["decoded_frame_count"] == 99
    assert completion["frame_count_drift"] == -1
    assert completion["frame_count_tolerance"] == 1


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"expected_camera_night": "camera-b:2026-08-25"}, "camera-night"),
        ({"expected_sample_fps": 1.0}, "sample fps"),
        ({"expected_source_sha256": "f" * 64}, "source SHA"),
    ],
)
def test_validator_rejects_reused_artifact_outside_current_contract(
    tmp_path: Path,
    overrides: dict[str, object],
    error: str,
) -> None:
    video = tmp_path / "source.mp4"
    destination = tmp_path / "complete"
    _write_video(video)
    completion = extract_video_to_directory(
        video,
        destination,
        clip_ref="clip-a",
        camera_night="camera-a:2026-08-24",
        expected_size_bytes=video.stat().st_size,
    )
    expected = {
        "expected_clip_ref": "clip-a",
        "expected_camera_night": "camera-a:2026-08-24",
        "expected_size_bytes": video.stat().st_size,
        "expected_sample_fps": 2.0,
        "expected_source_sha256": completion["source_sha256"],
    }
    expected.update(overrides)

    with pytest.raises(ValueError, match=error):
        validate_completed_clip(destination, **expected)


def test_extractor_never_overwrites_completed_clip(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    destination = tmp_path / "complete"
    _write_video(video)
    destination.mkdir()

    with pytest.raises(FileExistsError):
        extract_video_to_directory(
            video,
            destination,
            clip_ref="clip-a",
            camera_night="camera-a:2026-08-24",
            expected_size_bytes=video.stat().st_size,
        )


def test_validator_rejects_tampered_completed_ledger(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    destination = tmp_path / "complete"
    _write_video(video)
    extract_video_to_directory(
        video,
        destination,
        clip_ref="clip-a",
        camera_night="camera-a:2026-08-24",
        expected_size_bytes=video.stat().st_size,
    )
    with (destination / "ledger.jsonl").open("a") as handle:
        handle.write("{}\n")

    with pytest.raises(ValueError, match="ledger SHA"):
        validate_completed_clip(
            destination,
            expected_clip_ref="clip-a",
            expected_camera_night="camera-a:2026-08-24",
            expected_size_bytes=video.stat().st_size,
            expected_sample_fps=2.0,
        )


def _write_reuse_manifest(
    path: Path,
    *,
    video: Path,
    camera_id: str = "camera-a",
    source_sha256: str | None = None,
) -> None:
    source: dict[str, object] = {
        "clip_id": "clip-a",
        "camera_id": camera_id,
        "started_at": "2026-08-24T00:00:00+09:00",
        "r2_key": "private/clip-a.mp4",
        "size_bytes": video.stat().st_size,
        "object_status": "available",
    }
    if source_sha256 is not None:
        source["source_sha256"] = source_sha256
    path.write_text(
        json.dumps(
            {
                "lineage_sha256": "b" * 64,
                "aggregate": {"accessible_clip_count": 1},
                "sources": [source],
            },
            sort_keys=True,
        )
        + "\n"
    )


def _prepare_reused_clip(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    video = tmp_path / "source.mp4"
    output_root = tmp_path / "dense"
    _write_video(video)
    private_ref = hashlib.sha256(b"clip-a").hexdigest()[:24]
    completion = extract_video_to_directory(
        video,
        output_root / "clips" / private_ref,
        clip_ref="clip-a",
        camera_night="camera-a:2026-08-24",
        expected_size_bytes=video.stat().st_size,
        sample_fps=2.0,
    )
    return video, output_root, completion


class _PayloadR2:
    def __init__(self, payload: bytes, *, failure: Exception | None = None) -> None:
        self.payload = payload
        self.failure = failure
        self.calls: list[tuple[str, str]] = []

    def download_file(self, bucket: str, key: str, destination: str) -> None:
        self.calls.append((bucket, key))
        if self.failure is not None:
            raise self.failure
        Path(destination).write_bytes(self.payload)


def _set_reuse_main_argv(
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_manifest: Path,
    output_root: Path,
    sample_fps: float = 2.0,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dense-extraction",
            "--source-manifest",
            str(source_manifest),
            "--env-file",
            str(source_manifest.parent / ".env"),
            "--output-root",
            str(output_root),
            "--sample-fps",
            str(sample_fps),
        ],
    )


def test_main_reuse_without_manifest_sha_redownloads_and_verifies_source_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video, output_root, _completion = _prepare_reused_clip(tmp_path)
    source_manifest = tmp_path / "source.private.json"
    _write_reuse_manifest(source_manifest, video=video)
    clip_root = output_root / "clips" / hashlib.sha256(b"clip-a").hexdigest()[:24]
    original_completion = (clip_root / "completion.private.json").read_bytes()
    original_ledger = (clip_root / "ledger.jsonl").read_bytes()
    r2 = _PayloadR2(video.read_bytes())
    monkeypatch.setattr(dense_extraction, "_load_r2", lambda _path: (r2, "bucket"))
    monkeypatch.setattr(
        dense_extraction,
        "extract_video_to_directory",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("reused source must not be decoded again")
        ),
    )
    _set_reuse_main_argv(
        monkeypatch,
        source_manifest=source_manifest,
        output_root=output_root,
    )

    assert dense_extraction.main() == 0

    assert r2.calls == [("bucket", "private/clip-a.mp4")]
    assert (clip_root / "completion.private.json").read_bytes() == original_completion
    assert (clip_root / "ledger.jsonl").read_bytes() == original_ledger


@pytest.mark.parametrize(
    ("payload_factory", "error"),
    [
        (lambda payload: bytes([payload[0] ^ 1]) + payload[1:], "source SHA"),
        (lambda payload: payload + b"size-drift", "source size"),
    ],
)
def test_main_reuse_without_manifest_sha_rejects_downloaded_source_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload_factory: object,
    error: str,
) -> None:
    video, output_root, _completion = _prepare_reused_clip(tmp_path)
    source_manifest = tmp_path / "source.private.json"
    _write_reuse_manifest(source_manifest, video=video)
    original = video.read_bytes()
    assert callable(payload_factory)
    r2 = _PayloadR2(payload_factory(original))
    monkeypatch.setattr(dense_extraction, "_load_r2", lambda _path: (r2, "bucket"))
    monkeypatch.setattr(
        dense_extraction,
        "extract_video_to_directory",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("failed reuse validation must not re-decode")
        ),
    )
    _set_reuse_main_argv(
        monkeypatch,
        source_manifest=source_manifest,
        output_root=output_root,
    )

    with pytest.raises(ValueError, match=error):
        dense_extraction.main()


def test_main_reuse_without_manifest_sha_propagates_download_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video, output_root, _completion = _prepare_reused_clip(tmp_path)
    source_manifest = tmp_path / "source.private.json"
    _write_reuse_manifest(source_manifest, video=video)
    r2 = _PayloadR2(b"", failure=OSError("R2 unavailable"))
    monkeypatch.setattr(dense_extraction, "_load_r2", lambda _path: (r2, "bucket"))
    _set_reuse_main_argv(
        monkeypatch,
        source_manifest=source_manifest,
        output_root=output_root,
    )

    with pytest.raises(OSError, match="R2 unavailable"):
        dense_extraction.main()


@pytest.mark.parametrize(
    ("camera_id", "sample_fps", "source_sha256", "error"),
    [
        ("camera-b", 2.0, None, "camera-night"),
        ("camera-a", 1.0, None, "sample fps"),
        ("camera-a", 2.0, "f" * 64, "source SHA"),
    ],
)
def test_main_reuse_path_revalidates_current_source_window_and_sampling_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    camera_id: str,
    sample_fps: float,
    source_sha256: str | None,
    error: str,
) -> None:
    video, output_root, _completion = _prepare_reused_clip(tmp_path)
    source_manifest = tmp_path / "source.private.json"
    _write_reuse_manifest(
        source_manifest,
        video=video,
        camera_id=camera_id,
        source_sha256=source_sha256,
    )
    r2 = _PayloadR2(video.read_bytes())
    monkeypatch.setattr(dense_extraction, "_load_r2", lambda _path: (r2, "bucket"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dense-extraction",
            "--source-manifest",
            str(source_manifest),
            "--env-file",
            str(tmp_path / ".env"),
            "--output-root",
            str(output_root),
            "--sample-fps",
            str(sample_fps),
        ],
    )

    with pytest.raises(ValueError, match=error):
        dense_extraction.main()


def test_main_final_provenance_is_copied_from_revalidated_clip_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video, output_root, completion = _prepare_reused_clip(tmp_path)
    source_manifest = tmp_path / "source.private.json"
    _write_reuse_manifest(
        source_manifest,
        video=video,
        source_sha256=str(completion["source_sha256"]),
    )
    monkeypatch.setattr(dense_extraction, "_load_r2", lambda _path: (object(), "bucket"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dense-extraction",
            "--source-manifest",
            str(source_manifest),
            "--env-file",
            str(tmp_path / ".env"),
            "--output-root",
            str(output_root),
            "--sample-fps",
            "2.0",
        ],
    )

    assert dense_extraction.main() == 0

    final = json.loads((output_root / "completion.private.json").read_text())
    assert final["sample_fps"] == completion["sample_fps"]
    assert final["sampled_frame_count"] == completion["sampled_frame_count"]
    assert final["clips"] == [
        {
            "private_ref": hashlib.sha256(b"clip-a").hexdigest()[:24],
            "clip_ref": "clip-a",
            "camera_night": completion["camera_night"],
            "source_size_bytes": completion["source_size_bytes"],
            "source_sha256": completion["source_sha256"],
            "ledger_sha256": completion["ledger_sha256"],
            "sample_fps": completion["sample_fps"],
            "sampled_frame_count": completion["sampled_frame_count"],
        }
    ]

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from scripts.build_yolo26n_v26_blind_bundle import (
    extract_selected_jpegs,
    historical_dhash_int,
)
from scripts.run_yolo26n_v26_dense_extraction import extract_video_to_directory


def _write_video(path: Path, *, frames: int = 20, fps: float = 10.0) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 48))
    assert writer.isOpened()
    try:
        for index in range(frames):
            image = np.zeros((48, 64, 3), dtype=np.uint8)
            image[:, :, 0] = index * 10
            image[10:20, index : index + 10, 1] = 255
            writer.write(image)
    finally:
        writer.release()


def _dense_rows(video: Path, tmp_path: Path) -> list[dict[str, object]]:
    dense = tmp_path / "dense"
    extract_video_to_directory(
        video,
        dense,
        clip_ref="clip-a",
        camera_night="camera-a:2026-08-24",
        expected_size_bytes=video.stat().st_size,
    )
    return [json.loads(line) for line in (dense / "ledger.jsonl").read_text().splitlines()]


def test_bundle_extractor_reproduces_selected_image_sha_and_uses_anonymous_names(
    tmp_path: Path,
) -> None:
    video = tmp_path / "source.mp4"
    _write_video(video)
    rows = _dense_rows(video, tmp_path)
    selected = [rows[1], rows[3]]
    destination = tmp_path / "bundle"

    completion = extract_selected_jpegs(
        video,
        destination,
        selections=selected,
        selection_sha256="a" * 64,
        expected_size_bytes=video.stat().st_size,
        protected_dhash64=set(),
    )

    images = sorted((destination / "images").glob("*.jpg"))
    assert completion["image_count"] == 2
    assert len(images) == 2
    assert all("clip" not in image.name for image in images)
    assert {hashlib.sha256(image.read_bytes()).hexdigest() for image in images} == {
        str(row["image_sha256"]) for row in selected
    }
    assert all(len(record["historical_dhash64"]) == 16 for record in completion["records"])


def test_bundle_extractor_fails_closed_on_exact_historical_near_duplicate(
    tmp_path: Path,
) -> None:
    video = tmp_path / "source.mp4"
    _write_video(video)
    row = _dense_rows(video, tmp_path)[1]
    capture = cv2.VideoCapture(str(video))
    capture.set(cv2.CAP_PROP_POS_FRAMES, int(row["frame_index"]))
    ok, frame = capture.read()
    capture.release()
    assert ok
    encoded_ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    assert encoded_ok
    protected = historical_dhash_int(encoded.tobytes())
    destination = tmp_path / "bundle"

    with pytest.raises(ValueError, match="protected historical near-duplicate"):
        extract_selected_jpegs(
            video,
            destination,
            selections=[row],
            selection_sha256="a" * 64,
            expected_size_bytes=video.stat().st_size,
            protected_dhash64={protected},
        )

    assert not destination.exists()


def test_bundle_extractor_never_overwrites_completed_clip(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    _write_video(video)
    row = _dense_rows(video, tmp_path)[0]
    destination = tmp_path / "bundle"
    destination.mkdir()

    with pytest.raises(FileExistsError):
        extract_selected_jpegs(
            video,
            destination,
            selections=[row],
            selection_sha256="a" * 64,
            expected_size_bytes=video.stat().st_size,
            protected_dhash64=set(),
        )


def test_bundle_extractor_replaces_unstable_selected_frame_with_stable_reserve(
    tmp_path: Path,
) -> None:
    video = tmp_path / "source.mp4"
    _write_video(video)
    rows = _dense_rows(video, tmp_path)
    unstable = dict(rows[1])
    unstable["image_sha256"] = "0" * 64
    unstable["stratum"] = "coverage"
    stable = dict(rows[2])
    destination = tmp_path / "bundle"

    completion = extract_selected_jpegs(
        video,
        destination,
        selections=[unstable],
        fallback_selections=[stable],
        selection_sha256="a" * 64,
        expected_size_bytes=video.stat().st_size,
        protected_dhash64=set(),
    )

    assert completion["image_count"] == 1
    assert completion["replacement_count"] == 1
    assert completion["records"][0]["materialization_reason"] == "decode-replacement"
    assert completion["records"][0]["stratum"] == "coverage"
    assert completion["records"][0]["image_sha256"] == stable["image_sha256"]

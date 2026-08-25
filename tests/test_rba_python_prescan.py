from __future__ import annotations

import gzip
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from scripts.rba_python_prescan import PrescanError, scan_video


def _write_video(path: Path, *, fps: float, frames: list[np.ndarray]) -> None:
    height, width = frames[0].shape[:2]
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    assert writer.isOpened()
    try:
        for frame in frames:
            writer.write(frame)
    finally:
        writer.release()


def test_scan_video_reads_every_native_frame_without_fps_duplication(tmp_path: Path) -> None:
    video = tmp_path / "native-6fps.mp4"
    frames = [
        np.full((48, 64, 3), 20 if index < 6 else 220, dtype=np.uint8)
        for index in range(12)
    ]
    _write_video(video, fps=6.0, frames=frames)
    summary_path = tmp_path / "summary.json"
    sidecar_path = tmp_path / "frames.jsonl.gz"

    summary = scan_video(
        video,
        summary_output=summary_path,
        sidecar_output=sidecar_path,
        max_analysis_fps=30.0,
    )

    assert summary["schema_version"] == "python-prescan-v1"
    assert summary["decode"]["decoded_frames"] == 12
    assert summary["decode"]["analyzed_frames"] == 12
    assert summary["decode"]["source_fps"] == pytest.approx(6.0, rel=0.05)
    assert summary["decode"]["duration_sec"] == pytest.approx(2.0, rel=0.1)
    assert summary["vlm_support"]["full_coverage_preserved"] is True
    assert summary["vlm_support"]["dense_intervals"]
    assert summary["lighting"]["ir_transition_intervals"]
    assert len(summary_path.read_bytes()) <= 16 * 1024
    assert summary_path.stat().st_mode & 0o777 == 0o600
    assert sidecar_path.stat().st_mode & 0o777 == 0o600
    with gzip.open(sidecar_path, "rt") as handle:
        rows = [json.loads(line) for line in handle]
    assert len(rows) == 12
    assert [row["frame_index"] for row in rows] == list(range(12))


def test_scan_video_decodes_all_but_caps_analysis_above_30fps(tmp_path: Path) -> None:
    video = tmp_path / "native-60fps.mp4"
    frames = [np.full((32, 48, 3), index, dtype=np.uint8) for index in range(60)]
    _write_video(video, fps=60.0, frames=frames)

    summary = scan_video(video, max_analysis_fps=30.0)

    assert summary["decode"]["decoded_frames"] == 60
    assert 29 <= summary["decode"]["analyzed_frames"] <= 31


def test_scan_video_releases_capture_when_open_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    released = False

    class ClosedCapture:
        def isOpened(self) -> bool:
            return False

        def release(self) -> None:
            nonlocal released
            released = True

    monkeypatch.setattr(cv2, "VideoCapture", lambda _: ClosedCapture())

    with pytest.raises(PrescanError, match="video_open"):
        scan_video(tmp_path / "missing.mp4")

    assert released is True

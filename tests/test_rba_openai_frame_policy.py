from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from scripts.rba_gme_activity import parse_gme_activity
from scripts.rba_openai_frame_policy import materialize_frame_manifest


RUN_ID = "123e4567-e89b-42d3-a456-426614174000"


def _video(path: Path, *, seconds: int, fps: int) -> None:
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (80, 48)
    )
    assert writer.isOpened()
    try:
        for index in range(seconds * fps):
            frame = np.full((48, 80, 3), index % 255, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()


def test_materialize_preserves_base_coverage_and_adds_dense_frames(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    _video(video, seconds=4, fps=10)
    output = tmp_path / "frames"

    manifest = materialize_frame_manifest(
        video,
        output_dir=output,
        base_fps=2.0,
        dense_fps=5.0,
        dense_intervals=[{"start_sec": 1.0, "end_sec": 2.0}],
        window_sec=6.0,
        overlap_sec=1.0,
    )

    assert manifest["schema_version"] == "rba-openai-frame-manifest-v1"
    assert manifest["planned_frame_count"] == manifest["actual_frame_count"]
    assert manifest["base_coverage_preserved"] is True
    assert manifest["actual_frame_count"] > 8
    assert len(manifest["windows"]) == 1
    assert any("dense20fps" in row["source_policies"] for row in manifest["frames"])
    assert all(Path(row["path"]).is_file() for row in manifest["frames"])
    assert all(Path(row["path"]).stat().st_mode & 0o777 == 0o600 for row in manifest["frames"])
    assert not list(output.glob("*sheet*"))
    stored = json.loads((output / "frame-manifest.json").read_text())
    assert stored == manifest


def test_materialize_uses_six_second_windows_with_one_second_overlap(
    tmp_path: Path,
) -> None:
    video = tmp_path / "clip-12s.mp4"
    _video(video, seconds=12, fps=10)

    manifest = materialize_frame_manifest(
        video,
        output_dir=tmp_path / "frames-12s",
        base_fps=4.0,
        dense_fps=20.0,
        dense_intervals=[],
        window_sec=6.0,
        overlap_sec=1.0,
    )

    assert [window["start_sec"] for window in manifest["windows"]] == [0.0, 5.0, 10.0]
    assert [window["end_sec"] for window in manifest["windows"]] == [6.0, 11.0, 12.0]
    assert manifest["actual_frame_count"] == 48
    covered = {
        frame_ref
        for window in manifest["windows"]
        for frame_ref in window["frame_refs"]
    }
    assert covered == {row["frame_ref"] for row in manifest["frames"]}


def test_materialize_uses_gme_moving_intervals_without_losing_base_coverage(
    tmp_path: Path,
) -> None:
    video = tmp_path / "gme-clip.mp4"
    _video(video, seconds=4, fps=10)
    context = parse_gme_activity(
        {
            "id": RUN_ID,
            "status": "ok",
            "candidate_moving_sec_any_gecko": 1.0,
            "visible_sec": 2.0,
            "max_simultaneous_geckos": 1,
            "state_intervals": [
                {
                    "start_sec": 0.0,
                    "end_sec": 1.0,
                    "state": "static",
                    "track_ids": ["g1"],
                },
                {
                    "start_sec": 1.0,
                    "end_sec": 2.0,
                    "state": "moving",
                    "track_ids": ["g1"],
                },
                {
                    "start_sec": 2.0,
                    "end_sec": 4.0,
                    "state": "not_visible",
                    "track_ids": [],
                },
            ],
        },
        duration_sec=4.0,
    )

    manifest = materialize_frame_manifest(
        video,
        output_dir=tmp_path / "gme-frames",
        base_fps=2.0,
        dense_fps=5.0,
        dense_intervals=(),
        gme_context=context,
        window_sec=6.0,
        overlap_sec=1.0,
    )

    assert manifest["gme_activity"] == {
        "run_id": RUN_ID,
        "detected": True,
        "activity_sec": 1.0,
        "visible_sec": 2.0,
    }
    assert manifest["dense_intervals"] == [
        {"start_sec": 0.5, "end_sec": 2.5}
    ]
    assert any(
        "gme-moving-dense" in row["source_policies"]
        for row in manifest["frames"]
    )
    assert manifest["base_coverage_preserved"] is True

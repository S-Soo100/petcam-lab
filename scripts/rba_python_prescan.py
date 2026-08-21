"""모든 native frame을 순차 디코딩하는 RBA Python prescan v1이야."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import fmean
from typing import Iterable

import cv2
import numpy as np


class PrescanError(ValueError):
    """입력 영상 또는 prescan 산출물 계약이 깨졌어."""


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_new(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise PrescanError("output_exists")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def _analysis_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise PrescanError("frame_shape")
    height, width = frame.shape[:2]
    scale = min(1.0, 320 / max(1, width))
    if scale < 1.0:
        frame = cv2.resize(
            frame,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def _intervals(
    timestamps: Iterable[float], *, radius_sec: float, merge_gap_sec: float
) -> list[dict[str, float]]:
    ordered = sorted(timestamps)
    if not ordered:
        return []
    intervals: list[list[float]] = []
    for timestamp in ordered:
        start = max(0.0, timestamp - radius_sec)
        end = timestamp + radius_sec
        if intervals and start <= intervals[-1][1] + merge_gap_sec:
            intervals[-1][1] = max(intervals[-1][1], end)
        else:
            intervals.append([start, end])
    return [
        {"start_sec": round(start, 3), "end_sec": round(end, 3)}
        for start, end in intervals
    ]


def scan_video(
    video_path: Path,
    *,
    summary_output: Path | None = None,
    sidecar_output: Path | None = None,
    max_analysis_fps: float = 30.0,
) -> dict[str, object]:
    """영상은 전부 decode하고 원본 30fps 이하 frame은 하나도 복제·생략하지 않아."""
    if max_analysis_fps <= 0 or not math.isfinite(max_analysis_fps):
        raise PrescanError("max_analysis_fps")
    path = video_path.resolve()
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise PrescanError("video_open")
        source_fps = float(capture.get(cv2.CAP_PROP_FPS))
        expected_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not math.isfinite(source_fps) or source_fps <= 0:
            raise PrescanError("video_fps")

        decoded_frames = 0
        analyzed_frames = 0
        next_analysis_sec = 0.0
        previous_gray: np.ndarray | None = None
        previous_brightness: float | None = None
        brightness_values: list[float] = []
        motion_values: list[float] = []
        dense_timestamps: list[float] = []
        ir_timestamps: list[float] = []
        shake_timestamps: list[float] = []
        duplicate_frames = 0
        per_second: dict[int, list[float]] = defaultdict(list)
        sidecar_rows: list[dict[str, object]] = []

        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frame_index = decoded_frames
            decoded_frames += 1
            timestamp_sec = frame_index / source_fps
            if source_fps > max_analysis_fps and timestamp_sec + 1e-9 < next_analysis_sec:
                continue
            next_analysis_sec = timestamp_sec + (1.0 / max_analysis_fps)
            gray = _analysis_gray(frame)
            brightness = float(gray.mean() / 255.0)
            motion_score = 0.0
            if previous_gray is not None:
                motion_score = float(
                    cv2.absdiff(gray, previous_gray).mean() / 255.0
                )
                if motion_score < 0.001:
                    duplicate_frames += 1
                if motion_score >= 0.05:
                    dense_timestamps.append(timestamp_sec)
                if motion_score >= 0.30:
                    shake_timestamps.append(timestamp_sec)
            if (
                previous_brightness is not None
                and abs(brightness - previous_brightness) >= 0.25
            ):
                ir_timestamps.append(timestamp_sec)
            previous_gray = gray
            previous_brightness = brightness
            analyzed_frames += 1
            brightness_values.append(brightness)
            motion_values.append(motion_score)
            per_second[int(timestamp_sec)].append(motion_score)
            sidecar_rows.append(
                {
                    "frame_index": frame_index,
                    "timestamp_sec": round(timestamp_sec, 6),
                    "brightness": round(brightness, 6),
                    "motion_score": round(motion_score, 6),
                }
            )
    finally:
        capture.release()

    if decoded_frames == 0 or analyzed_frames == 0:
        raise PrescanError("video_decode")
    duration_sec = decoded_frames / source_fps
    invalid_reasons: list[str] = []
    if expected_frames > 0 and decoded_frames != expected_frames:
        invalid_reasons.append("frame_count_mismatch")
    active_frames = sum(value >= 0.05 for value in motion_values)
    sidecar_sha: str | None = None
    if sidecar_output is not None:
        if sidecar_output.exists() or sidecar_output.is_symlink():
            raise PrescanError("output_exists")
        sidecar_output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(sidecar_output.parent, 0o700)
        with gzip.open(sidecar_output, "wt", encoding="utf-8") as handle:
            for row in sidecar_rows:
                handle.write(_canonical_bytes(row).decode())
        sidecar_output.chmod(0o600)
        sidecar_sha = _sha256_file(sidecar_output)

    summary: dict[str, object] = {
        "schema_version": "python-prescan-v1",
        "extractor_version": "native-frame-v1",
        "config": {"max_analysis_fps": max_analysis_fps},
        "media_sha256": _sha256_file(path),
        "decode": {
            "expected_frames": expected_frames,
            "decoded_frames": decoded_frames,
            "analyzed_frames": analyzed_frames,
            "source_fps": round(source_fps, 6),
            "duration_sec": round(duration_sec, 6),
            "width": width,
            "height": height,
            "duplicate_frames": duplicate_frames,
            "invalid_reasons": invalid_reasons,
        },
        "lighting": {
            "brightness_summary": {
                "min": round(min(brightness_values), 6),
                "mean": round(fmean(brightness_values), 6),
                "max": round(max(brightness_values), 6),
            },
            "ir_transition_intervals": _intervals(
                ir_timestamps, radius_sec=0.5, merge_gap_sec=0.25
            ),
        },
        "camera_motion": {
            "motion_mean": round(fmean(motion_values), 6),
            "motion_max": round(max(motion_values), 6),
            "shake_intervals": _intervals(
                shake_timestamps, radius_sec=0.25, merge_gap_sec=0.25
            ),
        },
        "activity": {
            "active_ratio": round(active_frames / analyzed_frames, 6),
            "per_second_envelope": [
                {
                    "second": second,
                    "mean": round(fmean(values), 6),
                    "max": round(max(values), 6),
                }
                for second, values in sorted(per_second.items())
            ],
        },
        "vlm_support": {
            "dense_intervals": _intervals(
                dense_timestamps, radius_sec=0.25, merge_gap_sec=0.25
            ),
            "full_coverage_preserved": True,
        },
        "sidecar": {
            "row_count": len(sidecar_rows),
            "sha256": sidecar_sha,
        },
        "producer": "petcam-lab",
        "processed_at": datetime.now(UTC).isoformat(),
    }
    payload = _canonical_bytes(summary)
    if len(payload) > 16 * 1024:
        raise PrescanError("summary_too_large")
    if summary_output is not None:
        _write_new(summary_output, payload)
    return summary


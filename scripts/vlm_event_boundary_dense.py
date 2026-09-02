"""사건 경계 바로 앞뒤만 촘촘히 보여주는 공통 입력 계약이야."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import cv2
import numpy as np


A_BOUNDARY_OFFSETS_SEC = (6.0, 4.0, 2.0, 1.0, 0.5, 0.1)
B_BOUNDARY_OFFSETS_SEC = (0.1, 0.5, 1.0, 2.0, 4.0, 6.0)
DENSE_REPRESENTATION = "boundary_dense_two_images_6x2"
DENSE_PROMPT_VERSION = "vlm-event-boundary-dense-v2"
DENSE_PROMPT = """You are checking whether two consecutive gecko camera clips show one continuous physical activity event.
Image A contains the last six frames of video A, sampled increasingly densely toward its end, in chronological order.
Image B contains the first six frames of the following video B, sampled increasingly densely from its start, in chronological order.
Each image is a 3-column by 2-row sheet read left-to-right, top-to-bottom. The header states the unrecorded time gap between A and B.
Judge the boundary between A and B, not the overall similarity of the full videos. Use visible changes in gecko position, posture, direction, and motion across A's end and B's start.
same_event means the same physical activity or posture transition plausibly continues across the recording gap. different_event means the activity clearly stopped, reset, or a new activity or scene begins. If these boundary frames cannot establish either conclusion, choose uncertain.
Return one JSON object only with keys decision, confidence, reason_code.
decision: same_event|different_event|uncertain
confidence: number from 0 to 1
reason_code: continuous_motion|continuous_posture|clear_stop|new_activity|scene_discontinuity|insufficient_visual"""


def boundary_frame_indices(
    *,
    frame_count: int,
    fps: float,
    offsets_sec: tuple[float, ...],
    anchor: str,
) -> tuple[int, ...]:
    """초 단위 규칙을 실제 프레임 번호로 바꿔 영상 길이 변화에 흔들리지 않게 해."""
    if frame_count < 2 or not np.isfinite(fps) or fps <= 0:
        raise ValueError("video_metadata")
    if anchor not in {"start", "end"} or len(offsets_sec) != 6 or any(
        not np.isfinite(value) or value <= 0 for value in offsets_sec
    ):
        raise ValueError("sampling_contract")

    last = frame_count - 1
    if anchor == "start":
        indices = tuple(min(last, max(0, round(value * fps))) for value in offsets_sec)
    else:
        indices = tuple(min(last, max(0, last - round(value * fps))) for value in offsets_sec)
    if tuple(sorted(indices)) != indices or len(set(indices)) != len(indices):
        raise ValueError("sampling_collision")
    return indices


def extract_boundary_frames(
    path: Path,
    *,
    offsets_sec: tuple[float, ...],
    anchor: str,
) -> tuple[np.ndarray, ...]:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError("video_open")
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        indices = boundary_frame_indices(
            frame_count=frame_count,
            fps=fps,
            offsets_sec=offsets_sec,
            anchor=anchor,
        )
        frames: list[np.ndarray] = []
        for index in indices:
            if not capture.set(cv2.CAP_PROP_POS_FRAMES, index):
                raise ValueError("video_seek")
            ok, frame = capture.read()
            if not ok or frame is None:
                raise ValueError("video_decode")
            frames.append(frame)
        return tuple(frames)
    finally:
        capture.release()


def _fit_cell(frame: np.ndarray, *, max_width: int = 480, max_height: int = 270) -> np.ndarray:
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("frame_shape")
    height, width = frame.shape[:2]
    scale = min(1.0, max_width / width, max_height / height)
    if scale == 1.0:
        return frame
    return cv2.resize(
        frame,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def _sheet(
    frames: Iterable[np.ndarray],
    *,
    video_label: str,
    offsets_sec: tuple[float, ...],
    gap_sec: float,
) -> np.ndarray:
    prepared = [_fit_cell(frame) for frame in frames]
    if len(prepared) != 6 or not np.isfinite(gap_sec) or gap_sec < 0:
        raise ValueError("sheet_contract")
    cell_height = max(frame.shape[0] for frame in prepared)
    cell_width = max(frame.shape[1] for frame in prepared)
    cells: list[np.ndarray] = []
    for frame, offset in zip(prepared, offsets_sec, strict=True):
        # 시간 표시는 영상 위가 아니라 별도 header에 둬 원본 좌하단 timestamp를 보존해.
        header = np.full((28, cell_width, 3), 30, dtype=np.uint8)
        relation = "before end" if video_label == "A" else "after start"
        cv2.putText(
            header,
            f"{video_label} {offset:g}s {relation}",
            (8, 19),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        canvas = np.zeros((cell_height, cell_width, 3), dtype=np.uint8)
        y = (cell_height - frame.shape[0]) // 2
        x = (cell_width - frame.shape[1]) // 2
        canvas[y:y + frame.shape[0], x:x + frame.shape[1]] = frame
        cells.append(np.vstack((header, canvas)))
    grid = np.vstack((np.hstack(cells[:3]), np.hstack(cells[3:])))
    title = np.full((32, grid.shape[1], 3), 18, dtype=np.uint8)
    cv2.putText(
        title,
        f"VIDEO {video_label} boundary frames | A-to-B unrecorded gap: {gap_sec:.1f}s",
        (10, 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return np.vstack((title, grid))


def build_boundary_sheets(
    frames_a: Iterable[np.ndarray],
    frames_b: Iterable[np.ndarray],
    *,
    gap_sec: float,
) -> tuple[np.ndarray, np.ndarray]:
    return (
        _sheet(
            frames_a,
            video_label="A",
            offsets_sec=A_BOUNDARY_OFFSETS_SEC,
            gap_sec=gap_sec,
        ),
        _sheet(
            frames_b,
            video_label="B",
            offsets_sec=B_BOUNDARY_OFFSETS_SEC,
            gap_sec=gap_sec,
        ),
    )

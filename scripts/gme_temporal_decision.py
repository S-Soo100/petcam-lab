"""Pure 10fps temporal presence contract for GME detector evaluation.

This module does not write runtime state or deploy a detector.  It provides the
same sampling and clip aggregation rules that training evaluation and a later
shadow worker must share.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class TemporalDecisionContract:
    max_analysis_fps: float = 10.0
    window_frames: int = 5
    min_positive_frames: int = 3

    def validate(self) -> "TemporalDecisionContract":
        if (
            isinstance(self.max_analysis_fps, bool)
            or not isinstance(self.max_analysis_fps, (int, float))
            or not math.isfinite(float(self.max_analysis_fps))
            or float(self.max_analysis_fps) <= 0
        ):
            raise ValueError("max_analysis_fps must be finite and positive")
        if type(self.window_frames) is not int or self.window_frames < 1:
            raise ValueError("window_frames must be a positive integer")
        if (
            type(self.min_positive_frames) is not int
            or self.min_positive_frames < 1
            or self.min_positive_frames > self.window_frames
        ):
            raise ValueError("min_positive_frames must be in 1..window_frames")
        return self


def analysis_frame_indices(
    *,
    frame_count: int,
    source_fps: float,
    contract: TemporalDecisionContract = TemporalDecisionContract(),
) -> tuple[int, ...]:
    """Return native frame indices sampled at no more than the 10fps contract."""

    contract.validate()
    if type(frame_count) is not int or frame_count < 1:
        raise ValueError("frame_count must be a positive integer")
    if (
        isinstance(source_fps, bool)
        or not isinstance(source_fps, (int, float))
        or not math.isfinite(float(source_fps))
        or float(source_fps) <= 0
    ):
        raise ValueError("source_fps must be finite and positive")

    source_rate = float(source_fps)
    analysis_rate = float(contract.max_analysis_fps)
    if source_rate <= analysis_rate:
        return tuple(range(frame_count))

    next_deadline_number = 0
    selected: list[int] = []
    for frame_index in range(frame_count):
        timestamp_sec = frame_index / source_rate
        deadline_sec = next_deadline_number / analysis_rate
        if timestamp_sec + 1e-12 < deadline_sec:
            continue
        selected.append(frame_index)
        next_deadline_number += 1
    return tuple(selected)


def classify_clip_presence(
    frame_detections: Sequence[bool],
    *,
    contract: TemporalDecisionContract = TemporalDecisionContract(),
) -> str:
    """Aggregate frame detections into present/unknown/absent at clip level."""

    contract.validate()
    if not frame_detections or any(type(value) is not bool for value in frame_detections):
        raise ValueError("frame_detections must be a non-empty bool sequence")

    detections = tuple(frame_detections)
    window_size = min(len(detections), contract.window_frames)
    for start in range(0, len(detections) - window_size + 1):
        if sum(detections[start : start + window_size]) >= contract.min_positive_frames:
            return "present"
    return "unknown" if any(detections) else "absent"

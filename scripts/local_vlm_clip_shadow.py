"""Production local VLM clip shadow의 순수 입력·출력 계약이야."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import json
import math
import re
from typing import Iterable, Literal, Mapping, Sequence

import cv2
import numpy as np


Visibility = Literal["visible", "partial", "not_visible", "uncertain"]
ActivityState = Literal["active", "stationary", "uncertain"]
NotableChange = Literal[
    "movement", "posture", "location", "interaction", "none", "uncertain"
]

FRAME_FRACTIONS = (0.05, 0.20, 0.40, 0.60, 0.80, 0.95)
VISIBILITY = ("visible", "partial", "not_visible", "uncertain")
ACTIVITY_STATES = ("active", "stationary", "uncertain")
NOTABLE_CHANGES = (
    "movement", "posture", "location", "interaction", "none", "uncertain"
)
PROMPT_VERSION = "production-local-vlm-clip-shadow-canary-v1"
PROMPT = """You are observing six chronological frames from one gecko camera clip.
Use only facts visible in the frames. Do not diagnose health, infer unseen eating or defecation, or tell the user what to do.
Return one JSON object matching the supplied schema. summary_ko must be one Korean sentence of at most 120 characters. If evidence is unclear, use uncertain and needs_human_review=true."""

RESULT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "gecko_visibility": {"type": "string", "enum": list(VISIBILITY)},
        "activity_state": {"type": "string", "enum": list(ACTIVITY_STATES)},
        "notable_change": {"type": "string", "enum": list(NOTABLE_CHANGES)},
        "summary_ko": {"type": "string", "minLength": 1, "maxLength": 120},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "needs_human_review": {"type": "boolean"},
    },
    "required": [
        "gecko_visibility",
        "activity_state",
        "notable_change",
        "summary_ko",
        "confidence",
        "needs_human_review",
    ],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class ClipObservation:
    gecko_visibility: Visibility
    activity_state: ActivityState
    notable_change: NotableChange
    summary_ko: str
    confidence: float
    needs_human_review: bool


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def parse_observation(raw: str) -> ClipObservation:
    try:
        payload = json.loads(raw, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("invalid_json") from exc
    required = set(RESULT_SCHEMA["required"])
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("invalid_keys")
    visibility = payload["gecko_visibility"]
    activity = payload["activity_state"]
    change = payload["notable_change"]
    summary = payload["summary_ko"]
    confidence = payload["confidence"]
    review = payload["needs_human_review"]
    if visibility not in VISIBILITY:
        raise ValueError("invalid_visibility")
    if activity not in ACTIVITY_STATES:
        raise ValueError("invalid_activity")
    if change not in NOTABLE_CHANGES:
        raise ValueError("invalid_change")
    if (
        not isinstance(summary, str)
        or not 1 <= len(summary) <= 120
        or re.search(r"[가-힣]", summary) is None
    ):
        raise ValueError("invalid_summary")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(float(confidence))
        or not 0 <= float(confidence) <= 1
    ):
        raise ValueError("invalid_confidence")
    if not isinstance(review, bool):
        raise ValueError("invalid_review")
    return ClipObservation(
        gecko_visibility=visibility,
        activity_state=activity,
        notable_change=change,
        summary_ko=summary,
        confidence=float(confidence),
        needs_human_review=review,
    )


def _fit_frame(frame: np.ndarray, maximum: int = 256) -> np.ndarray:
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("frame_shape")
    height, width = frame.shape[:2]
    scale = min(1.0, maximum / max(height, width))
    if scale == 1.0:
        return frame
    return cv2.resize(
        frame,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def build_contact_sheet(frames: Sequence[np.ndarray]) -> np.ndarray:
    if len(frames) != 6:
        raise ValueError("frame_count")
    fitted = [_fit_frame(frame) for frame in frames]
    cell_height = max(frame.shape[0] for frame in fitted)
    cell_width = max(frame.shape[1] for frame in fitted)
    cells: list[np.ndarray] = []
    for frame in fitted:
        canvas = np.zeros((cell_height, cell_width, 3), dtype=np.uint8)
        y = (cell_height - frame.shape[0]) // 2
        x = (cell_width - frame.shape[1]) // 2
        canvas[y:y + frame.shape[0], x:x + frame.shape[1]] = frame
        cells.append(canvas)
    grid = np.vstack((np.hstack(cells[:3]), np.hstack(cells[3:])))
    header = np.full((24, grid.shape[1], 3), 32, dtype=np.uint8)
    cv2.putText(
        header,
        "chronological frames 1-6",
        (8, 17),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return np.vstack((header, grid))


def stop_reason(
    now: datetime,
    end_at: datetime,
    valid_count: int,
    max_requests: int,
    attempted_count: int,
) -> str | None:
    if valid_count >= max_requests:
        return "LIVE_COMPLETE"
    if attempted_count >= max_requests:
        return "REJECT_RELIABILITY"
    if now >= end_at:
        return "INCOMPLETE_LIVE_VOLUME"
    return None


def aggregate_public(records: Iterable[Mapping[str, object]]) -> dict[str, object]:
    rows = list(records)
    counts = Counter(str(row.get("status", row.get("type", "unknown"))) for row in rows)
    elapsed = sorted(
        float(row["elapsed_sec"])
        for row in rows
        if isinstance(row.get("elapsed_sec"), (int, float))
    )
    return {
        "records": len(rows),
        "schema_valid": counts["schema_valid"],
        "media_error": counts["media_error"],
        "invalid": counts["invalid"],
        "timeout": counts["timeout"],
        "latency_min_sec": elapsed[0] if elapsed else None,
        "latency_max_sec": elapsed[-1] if elapsed else None,
    }

"""현재 GME run을 OpenAI 입력 준비용 private activity context로 정규화해."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Mapping


UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
GME_STATES = frozenset(
    {"moving", "static", "not_visible", "unknown", "camera_motion"}
)
STATE_INTERVAL_FIELDS = frozenset(
    {"start_sec", "end_sec", "state", "track_ids"}
)
MOVING_DURATION_TOLERANCE_SEC = 0.001
INTERVAL_DURATION_TOLERANCE_SEC = 0.000001


class GmeActivityError(ValueError):
    """GME summary와 raw interval이 모순이면 입력 생성을 중단해."""


@dataclass(frozen=True, slots=True)
class GmeDenseInterval:
    start_sec: float
    end_sec: float


@dataclass(frozen=True, slots=True)
class GmeActivityContext:
    run_id: str
    detected: bool
    activity_sec: float
    visible_sec: float
    dense_intervals: tuple[GmeDenseInterval, ...]


def _strict_finite_number(value: object, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GmeActivityError(code)
    number = float(value)
    if not math.isfinite(number):
        raise GmeActivityError(code)
    return number


def _merge_touching_intervals(
    intervals: list[GmeDenseInterval],
) -> tuple[GmeDenseInterval, ...]:
    merged: list[GmeDenseInterval] = []
    for interval in intervals:
        if merged and interval.start_sec <= merged[-1].end_sec:
            merged[-1] = GmeDenseInterval(
                start_sec=merged[-1].start_sec,
                end_sec=max(merged[-1].end_sec, interval.end_sec),
            )
        else:
            merged.append(interval)
    return tuple(merged)


def _validate_track_ids(value: object) -> None:
    if (
        not isinstance(value, list)
        or not all(isinstance(track_id, str) for track_id in value)
        or value != sorted(set(value))
    ):
        raise GmeActivityError("state_interval")


def parse_gme_activity(
    run: Mapping[str, object], *, duration_sec: float
) -> GmeActivityContext:
    duration = _strict_finite_number(duration_sec, "duration_sec")
    if duration <= 0 or not isinstance(run, Mapping):
        raise GmeActivityError("run_contract")

    activity = _strict_finite_number(
        run.get("candidate_moving_sec_any_gecko"), "activity_sec"
    )
    visible = _strict_finite_number(run.get("visible_sec"), "visible_sec")
    count = run.get("max_simultaneous_geckos")
    run_id = run.get("id")
    intervals = run.get("state_intervals")
    if (
        activity < 0
        or visible < 0
        or activity > visible
        or visible > duration + MOVING_DURATION_TOLERANCE_SEC
        or type(count) is not int
        or count < 0
        or not isinstance(run_id, str)
        or not UUID.fullmatch(run_id)
        or run.get("status") != "ok"
        or not isinstance(intervals, list)
    ):
        raise GmeActivityError("run_contract")

    moving: list[GmeDenseInterval] = []
    raw_moving_sec = 0.0
    previous_end = 0.0
    for raw in intervals:
        if (
            not isinstance(raw, Mapping)
            or frozenset(raw) != STATE_INTERVAL_FIELDS
            or raw.get("state") not in GME_STATES
        ):
            raise GmeActivityError("state_interval")
        _validate_track_ids(raw.get("track_ids"))
        start = _strict_finite_number(raw.get("start_sec"), "state_interval")
        end = _strict_finite_number(raw.get("end_sec"), "state_interval")
        if (
            start < 0
            or start < previous_end
            or end <= start
            or end > duration + INTERVAL_DURATION_TOLERANCE_SEC
        ):
            raise GmeActivityError("state_interval")
        previous_end = end
        if raw["state"] == "moving":
            raw_moving_sec += end - start
            moving.append(
                GmeDenseInterval(
                    start_sec=max(0.0, start - 0.5),
                    end_sec=min(duration, end + 0.5),
                )
            )

    if not math.isclose(
        activity,
        raw_moving_sec,
        rel_tol=0.0,
        abs_tol=MOVING_DURATION_TOLERANCE_SEC,
    ):
        raise GmeActivityError("moving_duration_mismatch")

    return GmeActivityContext(
        run_id=run_id,
        detected=visible > 0 and count > 0,
        activity_sec=activity,
        visible_sec=visible,
        dense_intervals=_merge_touching_intervals(moving),
    )

from __future__ import annotations

import fcntl
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class QuietWindow:
    name: str
    hours: tuple[int, ...] | str
    minute: int
    before_minutes: int
    after_minutes: int


@dataclass(frozen=True, slots=True)
class GuardConfig:
    timezone: str
    segment_max_seconds: int
    minimum_buffer_seconds: int
    locks: tuple[tuple[str, Path], ...]
    windows: tuple[QuietWindow, ...]


@dataclass(frozen=True, slots=True)
class GuardDecision:
    allowed: bool
    reason: str


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid_guard_config")
    return value


def load_guard_config(path: Path) -> GuardConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid_guard_config") from error
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("invalid_guard_config")
    try:
        ZoneInfo(raw["timezone"])
        locks = tuple(
            (str(item["name"]), Path(item["path"])) for item in raw["locks"]
        )
        windows: list[QuietWindow] = []
        for item in raw["windows"]:
            hours = item["hours"]
            if hours != "every":
                if not isinstance(hours, list) or not hours:
                    raise ValueError
                hours = tuple(_positive_int(hour) for hour in hours)
                if any(hour > 23 for hour in hours):
                    raise ValueError
            minute = _positive_int(item["minute"])
            if minute > 59:
                raise ValueError
            windows.append(
                QuietWindow(
                    name=str(item["name"]),
                    hours=hours,
                    minute=minute,
                    before_minutes=_positive_int(item["before_minutes"]),
                    after_minutes=_positive_int(item["after_minutes"]),
                )
            )
        segment_max = _positive_int(raw["segment_max_seconds"])
        minimum_buffer = _positive_int(raw["minimum_buffer_seconds"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid_guard_config") from error
    return GuardConfig(
        timezone=raw["timezone"],
        segment_max_seconds=segment_max,
        minimum_buffer_seconds=minimum_buffer,
        locks=locks,
        windows=tuple(windows),
    )


def probe_lock(path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(handle, fcntl.LOCK_UN)
    return True


def _reserved_intervals(
    now: datetime,
    config: GuardConfig,
) -> tuple[tuple[datetime, datetime], ...]:
    timezone = ZoneInfo(config.timezone)
    local_now = now.astimezone(timezone)
    intervals: list[tuple[datetime, datetime]] = []
    for day_offset in (-1, 0, 1):
        day = (local_now + timedelta(days=day_offset)).date()
        for window in config.windows:
            hours = range(24) if window.hours == "every" else window.hours
            for hour in hours:
                start = datetime(
                    day.year,
                    day.month,
                    day.day,
                    hour,
                    window.minute,
                    tzinfo=timezone,
                )
                intervals.append(
                    (
                        start - timedelta(minutes=window.before_minutes),
                        start + timedelta(minutes=window.after_minutes),
                    )
                )
    return tuple(sorted(intervals))


def evaluate_guard(
    *,
    now: datetime,
    config: GuardConfig,
    segment_seconds: int,
) -> GuardDecision:
    if now.tzinfo is None or now.utcoffset() is None:
        return GuardDecision(False, "invalid_time")
    if segment_seconds < 1 or segment_seconds > config.segment_max_seconds:
        return GuardDecision(False, "segment_budget_invalid")
    for name, path in config.locks:
        if not probe_lock(path):
            return GuardDecision(False, f"{name}_lock_busy")
    local_now = now.astimezone(ZoneInfo(config.timezone))
    protected_end = local_now + timedelta(
        seconds=segment_seconds + config.minimum_buffer_seconds
    )
    for start, end in _reserved_intervals(local_now, config):
        if start <= local_now < end or local_now < start < protected_end:
            return GuardDecision(False, "quiet_window_insufficient")
    return GuardDecision(True, "allowed")

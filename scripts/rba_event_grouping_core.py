"""Pure metadata-only accounting and event grouping for the Phase 1 shadow."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

ALGORITHM_VERSION = "event-gap-metadata-v1"
KST = ZoneInfo("Asia/Seoul")
ACTIVE_EXCLUSION_STATES = frozenset(
    {"candidate", "quarantined", "media_deleted", "deletion_blocked"}
)

AccountingKind = Literal[
    "activity_candidate",
    "diagnostic_integrity",
    "blocked_research",
]


class EventGroupingContractError(ValueError):
    """The frozen Phase 1 contract was violated."""


@dataclass(frozen=True, slots=True)
class SourceClip:
    clip_id: str
    camera_id: str
    started_at: datetime
    duration_sec: float | None


@dataclass(frozen=True, slots=True)
class ExclusionState:
    clip_id: str
    state: str
    reason_code: str
    rule_version: str


@dataclass(frozen=True, slots=True)
class AccountedClip:
    clip_id: str
    camera_id: str
    started_at: datetime
    activity_day_kst: date
    duration_sec: float | None
    kind: AccountingKind
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class EventGroup:
    event_id: str
    algorithm_version: str
    camera_id: str
    activity_day_kst: date
    clip_ids: tuple[str, ...]
    started_at: datetime
    ended_at: datetime


def parse_aware_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise EventGroupingContractError("invalid_datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EventGroupingContractError("timestamp_must_be_timezone_aware")
    return parsed.astimezone(UTC)


def activity_day_kst(started_at: datetime) -> date:
    aware = parse_aware_datetime(started_at)
    return (aware.astimezone(KST) - timedelta(hours=7)).date()


def _valid_duration(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def _validate_source(clips: tuple[SourceClip, ...]) -> None:
    ids: set[str] = set()
    order_keys: set[tuple[str, date, datetime]] = set()
    for row in clips:
        if not row.clip_id:
            raise EventGroupingContractError("empty_source_clip_id")
        if row.clip_id in ids:
            raise EventGroupingContractError(f"duplicate_source_clip_id:{row.clip_id}")
        ids.add(row.clip_id)
        if not row.camera_id:
            raise EventGroupingContractError(f"empty_camera_id:{row.clip_id}")
        started_at = parse_aware_datetime(row.started_at)
        order_key = (row.camera_id, activity_day_kst(started_at), started_at)
        if order_key in order_keys:
            raise EventGroupingContractError("source_ordering_ambiguity")
        order_keys.add(order_key)


def account_source_clips(
    clips: Iterable[SourceClip],
    exclusions: Mapping[str, ExclusionState],
    blocked_clip_ids: frozenset[str],
) -> tuple[AccountedClip, ...]:
    source = tuple(clips)
    _validate_source(source)
    source_ids = {row.clip_id for row in source}
    unknown = set(exclusions) - source_ids
    if unknown:
        raise EventGroupingContractError(
            f"unknown_exclusion_clip:{sorted(unknown)[0]}"
        )

    accounted: list[AccountedClip] = []
    for clip in source:
        started_at = parse_aware_datetime(clip.started_at)
        state = exclusions.get(clip.clip_id)
        if state is not None and state.clip_id != clip.clip_id:
            raise EventGroupingContractError("exclusion_key_identity_mismatch")

        kind: AccountingKind
        reason: str | None
        if clip.clip_id in blocked_clip_ids:
            kind, reason = "blocked_research", "formal_or_frozen_manifest"
        elif state is not None and state.state in ACTIVE_EXCLUSION_STATES:
            reason_code = state.reason_code or "unknown"
            kind, reason = (
                "diagnostic_integrity",
                f"{reason_code}:{state.state}",
            )
        elif not _valid_duration(clip.duration_sec):
            kind, reason = "diagnostic_integrity", "invalid_duration"
        else:
            kind, reason = "activity_candidate", None

        accounted.append(
            AccountedClip(
                clip_id=clip.clip_id,
                camera_id=clip.camera_id,
                started_at=started_at,
                activity_day_kst=activity_day_kst(started_at),
                duration_sec=clip.duration_sec,
                kind=kind,
                reason_code=reason,
            )
        )

    return tuple(
        sorted(
            accounted,
            key=lambda row: (
                row.camera_id,
                row.activity_day_kst,
                row.started_at,
                row.clip_id,
            ),
        )
    )


def _event_id(
    algorithm_version: str,
    camera_id: str,
    activity_day: date,
    clip_ids: tuple[str, ...],
) -> str:
    payload = "\0".join(
        (algorithm_version, camera_id, activity_day.isoformat(), *clip_ids)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_event(
    rows: list[AccountedClip],
    algorithm_version: str,
) -> EventGroup:
    clip_ids = tuple(row.clip_id for row in rows)
    ended_at = max(
        row.started_at + timedelta(seconds=float(row.duration_sec or 0))
        for row in rows
    )
    return EventGroup(
        event_id=_event_id(
            algorithm_version,
            rows[0].camera_id,
            rows[0].activity_day_kst,
            clip_ids,
        ),
        algorithm_version=algorithm_version,
        camera_id=rows[0].camera_id,
        activity_day_kst=rows[0].activity_day_kst,
        clip_ids=clip_ids,
        started_at=rows[0].started_at,
        ended_at=ended_at,
    )


def group_activity_events(
    accounted: Iterable[AccountedClip],
    threshold_sec: float,
    algorithm_version: str = ALGORITHM_VERSION,
) -> tuple[EventGroup, ...]:
    if not math.isfinite(threshold_sec) or threshold_sec < 0:
        raise EventGroupingContractError("invalid_threshold")
    if not algorithm_version:
        raise EventGroupingContractError("empty_algorithm_version")

    rows = tuple(
        sorted(
            accounted,
            key=lambda row: (
                row.camera_id,
                row.activity_day_kst,
                row.started_at,
                row.clip_id,
            ),
        )
    )
    events: list[EventGroup] = []
    current: list[AccountedClip] = []

    def flush() -> None:
        nonlocal current
        if current:
            events.append(_build_event(current, algorithm_version))
            current = []

    for row in rows:
        if row.kind != "activity_candidate":
            flush()
            continue
        if not _valid_duration(row.duration_sec):
            raise EventGroupingContractError("activity_candidate_invalid_duration")
        if not current:
            current = [row]
            continue
        previous = current[-1]
        same_scope = (
            previous.camera_id == row.camera_id
            and previous.activity_day_kst == row.activity_day_kst
        )
        gap_sec = (
            row.started_at
            - (
                previous.started_at
                + timedelta(seconds=float(previous.duration_sec or 0))
            )
        ).total_seconds()
        if same_scope and gap_sec <= threshold_sec:
            current.append(row)
        else:
            flush()
            current = [row]
    flush()
    return tuple(events)


def verify_accounting(
    source: Iterable[SourceClip],
    accounted: Iterable[AccountedClip],
    events: Iterable[EventGroup],
) -> None:
    source_rows = tuple(source)
    accounted_rows = tuple(accounted)
    event_rows = tuple(events)

    source_ids = [row.clip_id for row in source_rows]
    accounted_ids = [row.clip_id for row in accounted_rows]
    if len(source_ids) != len(set(source_ids)):
        raise EventGroupingContractError("duplicate_source_clip_id")
    if len(accounted_ids) != len(set(accounted_ids)):
        raise EventGroupingContractError("duplicate_accounted_clip_id")
    if set(source_ids) != set(accounted_ids):
        raise EventGroupingContractError("source_accounting_mismatch")

    by_id = {row.clip_id: row for row in accounted_rows}
    assigned: list[str] = []
    for event in event_rows:
        if not event.clip_ids:
            raise EventGroupingContractError("empty_event")
        for clip_id in event.clip_ids:
            row = by_id.get(clip_id)
            if row is None:
                raise EventGroupingContractError("unknown_event_clip")
            if row.kind != "activity_candidate":
                raise EventGroupingContractError("protected_clip_in_event")
            if (
                row.camera_id != event.camera_id
                or row.activity_day_kst != event.activity_day_kst
            ):
                raise EventGroupingContractError("event_crosses_camera_or_day")
            assigned.append(clip_id)

    if len(assigned) != len(set(assigned)):
        raise EventGroupingContractError("duplicate_event_assignment")
    candidate_ids = {
        row.clip_id
        for row in accounted_rows
        if row.kind == "activity_candidate"
    }
    if set(assigned) != candidate_ids:
        raise EventGroupingContractError("activity_event_coverage_mismatch")

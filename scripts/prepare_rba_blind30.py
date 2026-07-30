"""Formal Blind30 metadata-only deterministic selector and private manifest writer."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

SEED = "rba-data-engine-blind30-v1"
SELECTION_VERSION = "formal-blind30-selection-v1"
MANIFEST_SCHEMA = "rba-blind30-manifest-v1"
_KST = ZoneInfo("Asia/Seoul")
_REVIEWER_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{12,64}$")


class Blind30PreparationError(ValueError):
    """Frozen selection contract cannot be satisfied without relaxing it."""


@dataclass(frozen=True)
class Candidate:
    clip_id: str
    camera_id: str
    started_at: datetime
    duration_sec: float
    r2_ready: bool
    labelable: bool
    excluded: bool
    tutorial: bool
    canary_history: bool
    submission_count: int
    live_terminal_consensus: bool
    legacy_gt_count: int

    @property
    def activity_day_kst(self) -> date:
        _require_aware(self.started_at, name="started_at")
        return (self.started_at.astimezone(_KST) - timedelta(hours=7)).date()


def _require_aware(value: datetime, *, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise Blind30PreparationError(f"{name}_MUST_BE_TIMEZONE_AWARE")


def stable_hash(*parts: object) -> str:
    canonical = "|".join(str(part) for part in parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _activity_day_closed(candidate: Candidate, *, t0: datetime) -> bool:
    close_at = datetime.combine(
        candidate.activity_day_kst + timedelta(days=1),
        time(hour=7),
        tzinfo=_KST,
    )
    return close_at <= t0.astimezone(_KST)


def _eligible(candidate: Candidate, *, t0: datetime) -> bool:
    return (
        candidate.started_at < t0
        and _activity_day_closed(candidate, t0=t0)
        and candidate.r2_ready
        and candidate.labelable
        and not candidate.excluded
        and not candidate.tutorial
        and not candidate.canary_history
        and candidate.submission_count == 0
        and not candidate.live_terminal_consensus
        and candidate.legacy_gt_count == 0
    )


def select_formal30(
    candidates: Sequence[Candidate],
    *,
    t0: datetime,
) -> list[Candidate]:
    """Select exact 30 without reading answers, predictions, consensus outcomes, or GT."""

    _require_aware(t0, name="t0")

    # Near-duplicate guard: one stable winner per camera/activity-day/5-minute bucket.
    bucket_winners: dict[tuple[str, date, int], Candidate] = {}
    for candidate in candidates:
        _require_aware(candidate.started_at, name="started_at")
        if not _eligible(candidate, t0=t0):
            continue
        key = (
            candidate.camera_id,
            candidate.activity_day_kst,
            int(candidate.started_at.timestamp()) // 300,
        )
        current = bucket_winners.get(key)
        if current is None or stable_hash(SEED, candidate.clip_id) < stable_hash(
            SEED, current.clip_id
        ):
            bucket_winners[key] = candidate

    strata: dict[tuple[str, date], list[Candidate]] = {}
    for candidate in bucket_winners.values():
        key = (candidate.camera_id, candidate.activity_day_kst)
        strata.setdefault(key, []).append(candidate)

    ordered_strata = sorted(
        strata,
        key=lambda key: stable_hash(SEED, key[0], key[1].isoformat()),
    )
    for key in ordered_strata:
        strata[key].sort(key=lambda row: stable_hash(SEED, row.clip_id))

    selected: list[Candidate] = []
    for offset in range(5):
        for key in ordered_strata:
            rows = strata[key]
            if offset < len(rows):
                selected.append(rows[offset])
                if len(selected) == 30:
                    break
        if len(selected) == 30:
            break

    selected_strata = {
        (candidate.camera_id, candidate.activity_day_kst) for candidate in selected
    }
    selected_cameras = {candidate.camera_id for candidate in selected}
    if (
        len(selected) != 30
        or len(selected_strata) < 6
        or len(selected_cameras) < 2
    ):
        raise Blind30PreparationError("INSUFFICIENT_ELIGIBLE_POOL")
    return selected


def build_manifest(
    selected: Sequence[Candidate],
    *,
    t0: datetime,
    reviewer_fingerprints: Sequence[str],
) -> dict[str, object]:
    _require_aware(t0, name="t0")
    if len(selected) != 30 or len({row.clip_id for row in selected}) != 30:
        raise Blind30PreparationError("MANIFEST_REQUIRES_EXACT_30")
    if (
        len(reviewer_fingerprints) != 2
        or len(set(reviewer_fingerprints)) != 2
        or any(
            _REVIEWER_FINGERPRINT_RE.fullmatch(value) is None
            for value in reviewer_fingerprints
        )
    ):
        raise Blind30PreparationError("MANIFEST_REQUIRES_TWO_REVIEWER_FINGERPRINTS")

    ordered_ids = [candidate.clip_id for candidate in selected]
    clips = [
        {
            "clip_id": candidate.clip_id,
            "camera_id": candidate.camera_id,
            "activity_day_kst": candidate.activity_day_kst.isoformat(),
            "started_at": candidate.started_at.isoformat(),
            "duration_sec": candidate.duration_sec,
            "eligibility": {
                "r2_ready": candidate.r2_ready,
                "labelable": candidate.labelable,
                "excluded": candidate.excluded,
                "tutorial": candidate.tutorial,
                "canary_history": candidate.canary_history,
                "submission_count": candidate.submission_count,
                "live_terminal_consensus": candidate.live_terminal_consensus,
                "legacy_gt_count": candidate.legacy_gt_count,
            },
        }
        for candidate in selected
    ]
    return {
        "schema": MANIFEST_SCHEMA,
        "version": SELECTION_VERSION,
        "seed": SEED,
        "selection_t0": t0.isoformat(),
        "selection_rule": {
            "near_duplicate_bucket_seconds": 300,
            "max_per_camera_night": 5,
            "minimum_camera_nights": 6,
            "minimum_cameras": 2,
            "sample_size": 30,
        },
        "reviewer_fingerprints": list(reviewer_fingerprints),
        "ordered_list_sha256": stable_hash(*ordered_ids),
        "clips": clips,
    }


def write_manifest(path: Path, manifest: Mapping[str, object]) -> str:
    """Write canonical UTF-8 JSON privately and return the full file digest."""

    payload = (
        json.dumps(
            manifest,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(path.read_bytes()).hexdigest()

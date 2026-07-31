"""Deterministic boundary-pair selection for the event-grouping shadow."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date
from itertools import permutations
from pathlib import Path
from typing import Literal

from scripts.rba_event_grouping_core import AccountedClip

EXPERIMENT_ID = "rba-event-grouping-shadow-v2"
SELECTION_SEED = "rba-event-grouping-shadow-v2"
SOURCE_CUTOFF = "2026-07-31T03:44:27.183403+09:00"
BLOCKED_INSUFFICIENT_BOUNDARY_PAIRS = "BLOCKED_INSUFFICIENT_BOUNDARY_PAIRS"
BLOCKED_SELECTOR_SEARCH_EXHAUSTED = "BLOCKED_SELECTOR_SEARCH_EXHAUSTED"
SEARCH_MAX_ATTEMPTS = 2000
GAP_BINS = ("le30", "30to60", "60to300")

GapBin = Literal["le30", "30to60", "60to300"]
CameraNight = tuple[str, date]


class BoundarySelectionBlocked(RuntimeError):
    """The frozen inventory cannot satisfy the exact selection contract."""


@dataclass(frozen=True, slots=True)
class BoundaryPair:
    pair_id: str
    left_clip_id: str
    right_clip_id: str
    camera_id: str
    activity_day_kst: date
    gap_sec: float
    gap_bin: GapBin


@dataclass(frozen=True, slots=True)
class FrozenSplit:
    all_pairs: tuple[BoundaryPair, ...]
    development_nights: tuple[CameraNight, ...]
    holdout_nights: tuple[CameraNight, ...]
    selection_order: tuple[GapBin, GapBin, GapBin] = GAP_BINS
    search_attempt: int = 0
    search_max_attempts: int = SEARCH_MAX_ATTEMPTS


def _stable_hash(seed: str, *parts: object) -> str:
    payload = "\0".join((seed, *(str(part) for part in parts)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _gap_bin(gap_sec: float) -> GapBin:
    if gap_sec <= 30:
        return "le30"
    if gap_sec <= 60:
        return "30to60"
    return "60to300"


def build_adjacent_pairs(
    accounted: Iterable[AccountedClip],
    seed: str = SELECTION_SEED,
) -> tuple[BoundaryPair, ...]:
    rows = sorted(
        accounted,
        key=lambda row: (
            row.camera_id,
            row.activity_day_kst,
            row.started_at,
            row.clip_id,
        ),
    )
    pairs: list[BoundaryPair] = []
    previous: AccountedClip | None = None
    for row in rows:
        if row.kind != "activity_candidate":
            previous = None
            continue
        if previous is not None:
            same_night = (
                previous.camera_id == row.camera_id
                and previous.activity_day_kst == row.activity_day_kst
            )
            gap_sec = (
                row.started_at
                - previous.started_at
            ).total_seconds() - float(previous.duration_sec or 0)
            if same_night and gap_sec <= 300:
                pairs.append(
                    BoundaryPair(
                        pair_id=_stable_hash(
                            seed,
                            row.camera_id,
                            row.activity_day_kst.isoformat(),
                            previous.clip_id,
                            row.clip_id,
                        ),
                        left_clip_id=previous.clip_id,
                        right_clip_id=row.clip_id,
                        camera_id=row.camera_id,
                        activity_day_kst=row.activity_day_kst,
                        gap_sec=gap_sec,
                        gap_bin=_gap_bin(gap_sec),
                    )
                )
        previous = row
    return tuple(pairs)


def _night_bins(
    pairs: tuple[BoundaryPair, ...],
) -> dict[CameraNight, set[str]]:
    bins_by_night: dict[CameraNight, set[str]] = defaultdict(set)
    for item in pairs:
        bins_by_night[(item.camera_id, item.activity_day_kst)].add(item.gap_bin)
    return bins_by_night


def _partition_for_attempt(
    pair_rows: tuple[BoundaryPair, ...],
    *,
    seed: str,
    attempt: int,
    max_attempts: int,
) -> FrozenSplit | None:
    bins_by_night = _night_bins(pair_rows)
    ordered = sorted(
        bins_by_night,
        key=lambda night: _stable_hash(
            seed,
            "partition",
            attempt,
            night[0],
            night[1].isoformat(),
        ),
    )
    development = tuple(sorted(ordered[:6]))
    holdout = tuple(sorted(ordered[6:12]))
    if len(development) != 6 or len(holdout) != 6:
        return None
    if (
        len({camera for camera, _ in development}) < 2
        or len({camera for camera, _ in holdout}) < 2
    ):
        return None
    for nights in (development, holdout):
        observed = set().union(*(bins_by_night[night] for night in nights))
        if observed != set(GAP_BINS):
            return None
    return FrozenSplit(
        all_pairs=pair_rows,
        development_nights=development,
        holdout_nights=holdout,
        search_attempt=attempt,
        search_max_attempts=max_attempts,
    )


def split_camera_nights(
    pairs: Iterable[BoundaryPair],
    seed: str,
) -> FrozenSplit:
    pair_rows = tuple(
        sorted(
            pairs,
            key=lambda item: (
                item.camera_id,
                item.activity_day_kst,
                item.pair_id,
            ),
        )
    )
    bins_by_night = _night_bins(pair_rows)
    if (
        len(bins_by_night) < 12
        or len({night[0] for night in bins_by_night}) < 2
        or {item.gap_bin for item in pair_rows} != set(GAP_BINS)
    ):
        raise BoundarySelectionBlocked(BLOCKED_INSUFFICIENT_BOUNDARY_PAIRS)
    for attempt in range(SEARCH_MAX_ATTEMPTS):
        split = _partition_for_attempt(
            pair_rows,
            seed=seed,
            attempt=attempt,
            max_attempts=SEARCH_MAX_ATTEMPTS,
        )
        if split is not None:
            return split
    raise BoundarySelectionBlocked(BLOCKED_SELECTOR_SEARCH_EXHAUSTED)


def _select_split(
    pairs: tuple[BoundaryPair, ...],
    nights: tuple[CameraNight, ...],
    seed: str,
    gap_order: tuple[GapBin, GapBin, GapBin] = GAP_BINS,
) -> list[BoundaryPair]:
    selected: list[BoundaryPair] = []
    used_clips: set[str] = set()
    camera_totals: Counter[str] = Counter()
    night_set = set(nights)
    for gap_bin in gap_order:
        bin_selected: list[BoundaryPair] = []
        bin_camera_totals: Counter[str] = Counter()
        candidates = sorted(
            (
                item
                for item in pairs
                if item.gap_bin == gap_bin
                and (item.camera_id, item.activity_day_kst) in night_set
            ),
            key=lambda item: _stable_hash(seed, item.pair_id),
        )
        for item in candidates:
            if len(bin_selected) == 20:
                break
            if (
                item.left_clip_id in used_clips
                or item.right_clip_id in used_clips
                or bin_camera_totals[item.camera_id] >= 14
                or camera_totals[item.camera_id] >= 36
            ):
                continue
            bin_selected.append(item)
            used_clips.update((item.left_clip_id, item.right_clip_id))
            bin_camera_totals[item.camera_id] += 1
            camera_totals[item.camera_id] += 1
        if len(bin_selected) != 20:
            raise BoundarySelectionBlocked(BLOCKED_INSUFFICIENT_BOUNDARY_PAIRS)
        selected.extend(bin_selected)
    return selected


def select_boundary_pairs(
    split: FrozenSplit,
    seed: str,
) -> tuple[BoundaryPair, ...]:
    development = _select_split(
        split.all_pairs,
        split.development_nights,
        seed,
        split.selection_order,
    )
    holdout = _select_split(
        split.all_pairs,
        split.holdout_nights,
        seed,
        split.selection_order,
    )
    selected = tuple(development + holdout)
    clip_ids = [
        clip_id
        for item in selected
        for clip_id in (item.left_clip_id, item.right_clip_id)
    ]
    if len(selected) != 120 or len(clip_ids) != len(set(clip_ids)):
        raise BoundarySelectionBlocked(BLOCKED_INSUFFICIENT_BOUNDARY_PAIRS)
    return selected


def _selection_digest(
    split: FrozenSplit,
    selected: tuple[BoundaryPair, ...],
) -> str:
    payload = {
        "development_nights": [
            [camera, day.isoformat()]
            for camera, day in split.development_nights
        ],
        "holdout_nights": [
            [camera, day.isoformat()]
            for camera, day in split.holdout_nights
        ],
        "selection_order": list(split.selection_order),
        "pair_ids": sorted(item.pair_id for item in selected),
    }
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def search_boundary_selection(
    pairs: Iterable[BoundaryPair],
    seed: str = SELECTION_SEED,
    *,
    max_attempts: int = SEARCH_MAX_ATTEMPTS,
) -> tuple[FrozenSplit, tuple[BoundaryPair, ...]]:
    pair_rows = tuple(
        sorted(
            pairs,
            key=lambda item: (
                item.camera_id,
                item.activity_day_kst,
                item.pair_id,
            ),
        )
    )
    bins_by_night = _night_bins(pair_rows)
    if (
        len(bins_by_night) < 12
        or len({night[0] for night in bins_by_night}) < 2
        or {item.gap_bin for item in pair_rows} != set(GAP_BINS)
    ):
        raise BoundarySelectionBlocked(BLOCKED_INSUFFICIENT_BOUNDARY_PAIRS)
    witnesses: list[
        tuple[str, FrozenSplit, tuple[BoundaryPair, ...]]
    ] = []
    for attempt in range(max_attempts):
        base = _partition_for_attempt(
            pair_rows,
            seed=seed,
            attempt=attempt,
            max_attempts=max_attempts,
        )
        if base is None:
            continue
        for raw_order in permutations(GAP_BINS):
            order = (
                raw_order[0],
                raw_order[1],
                raw_order[2],
            )
            split = FrozenSplit(
                all_pairs=pair_rows,
                development_nights=base.development_nights,
                holdout_nights=base.holdout_nights,
                selection_order=order,
                search_attempt=attempt,
                search_max_attempts=max_attempts,
            )
            try:
                selected = select_boundary_pairs(split, seed)
            except BoundarySelectionBlocked:
                continue
            witnesses.append(
                (_selection_digest(split, selected), split, selected)
            )
    if not witnesses:
        raise BoundarySelectionBlocked(BLOCKED_SELECTOR_SEARCH_EXHAUSTED)
    _, split, selected = min(witnesses, key=lambda item: item[0])
    return split, selected


def _pair_row(item: BoundaryPair) -> dict[str, object]:
    return {
        "pair_id": item.pair_id,
        "left_clip_id": item.left_clip_id,
        "right_clip_id": item.right_clip_id,
        "camera_id": item.camera_id,
        "activity_day_kst": item.activity_day_kst.isoformat(),
        "gap_sec": item.gap_sec,
        "gap_bin": item.gap_bin,
    }


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def build_private_manifest(
    *,
    source_snapshot_sha256: str,
    blocked_set_sha256: str,
    split: FrozenSplit,
    selected_pairs: Iterable[BoundaryPair],
    accounting_rows: Iterable[AccountedClip],
) -> dict[str, object]:
    selected = tuple(
        sorted(selected_pairs, key=lambda item: item.pair_id)
    )
    development_nights = set(split.development_nights)
    payload: dict[str, object] = {
        "schema_version": "rba-event-boundary-manifest-v2",
        "experiment_id": EXPERIMENT_ID,
        "selection_seed": SELECTION_SEED,
        "source_cutoff": SOURCE_CUTOFF,
        "source_snapshot_sha256": source_snapshot_sha256,
        "blocked_set_sha256": blocked_set_sha256,
        "search": {
            "attempt": split.search_attempt,
            "max_attempts": split.search_max_attempts,
            "selection_order": list(split.selection_order),
        },
        "camera_nights": {
            "development": [
                [camera, day.isoformat()]
                for camera, day in split.development_nights
            ],
            "holdout": [
                [camera, day.isoformat()]
                for camera, day in split.holdout_nights
            ],
        },
        "splits": {
            "development": [
                _pair_row(item)
                for item in selected
                if (item.camera_id, item.activity_day_kst)
                in development_nights
            ],
            "holdout": [
                _pair_row(item)
                for item in selected
                if (item.camera_id, item.activity_day_kst)
                not in development_nights
            ],
        },
        "accounting": [
            {
                **asdict(row),
                "started_at": row.started_at.isoformat(),
                "activity_day_kst": row.activity_day_kst.isoformat(),
            }
            for row in sorted(accounting_rows, key=lambda row: row.clip_id)
        ],
    }
    payload["manifest_sha256"] = hashlib.sha256(
        _canonical_bytes(payload)
    ).hexdigest()
    return payload


def build_blank_worksheet(
    selected_pairs: Iterable[BoundaryPair],
) -> dict[str, object]:
    return {
        "schema_version": "rba-event-boundary-worksheet-v2",
        "rows": [
            {"pair_id": item.pair_id, "decision": None, "reason": None}
            for item in sorted(selected_pairs, key=lambda item: item.pair_id)
        ],
    }


def build_public_summary(
    selected_pairs: Iterable[BoundaryPair],
    split: FrozenSplit,
    *,
    salt: str,
) -> dict[str, object]:
    selected = tuple(selected_pairs)
    cameras = sorted({item.camera_id for item in selected})
    fingerprints = [
        hashlib.sha256(f"{salt}\0{camera}".encode()).hexdigest()[:16]
        for camera in cameras
    ]
    return {
        "experiment_id": EXPERIMENT_ID,
        "selected_count": len(selected),
        "development_night_count": len(split.development_nights),
        "holdout_night_count": len(split.holdout_nights),
        "gap_bin_counts": dict(
            sorted(Counter(item.gap_bin for item in selected).items())
        ),
        "camera_fingerprints": fingerprints,
    }


def write_private_new(path: Path, payload: Mapping[str, object]) -> str:
    data = _canonical_bytes(payload)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    os.chmod(path, 0o600)
    return hashlib.sha256(data).hexdigest()

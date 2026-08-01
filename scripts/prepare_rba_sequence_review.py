"""연속 clip run을 보존하는 사건 이어짐 v2 표본 선택기."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

from scripts.prepare_rba_event_grouping_shadow import BoundaryPair, build_adjacent_pairs
from scripts.rba_event_grouping_core import AccountedClip


SELECTION_SEED = "rba-event-sequence-review-v2"
EXPERIMENT_ID = "rba-event-sequence-review-v2"
BLOCKED_INSUFFICIENT_SEQUENCE_RUNS = "BLOCKED_INSUFFICIENT_SEQUENCE_RUNS"

CameraNight = tuple[str, date]


class SequenceSelectionBlocked(RuntimeError):
    """동결 source가 연속 run 표본 계약을 만족하지 못했어."""


@dataclass(frozen=True, slots=True)
class SelectedSequenceRun:
    camera_id: str
    activity_day_kst: date
    pairs: tuple[BoundaryPair, ...]
    left_censored: bool
    right_censored: bool


def _stable_hash(seed: str, *parts: object) -> str:
    payload = "\0".join((seed, *(str(part) for part in parts)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _complete_runs(
    accounted: Iterable[AccountedClip],
) -> dict[CameraNight, list[tuple[BoundaryPair, ...]]]:
    pairs = build_adjacent_pairs(accounted, seed=SELECTION_SEED)
    by_night: dict[CameraNight, list[tuple[BoundaryPair, ...]]] = {}
    current: list[BoundaryPair] = []
    previous: BoundaryPair | None = None
    # build_adjacent_pairs가 실제 촬영 시각 순으로 반환해. clip UUID 정렬은
    # 시간 순서와 무관하므로 다시 정렬하면 A-B/B-C chain이 깨져.
    for pair in pairs:
        same_run = (
            previous is not None
            and previous.camera_id == pair.camera_id
            and previous.activity_day_kst == pair.activity_day_kst
            and previous.right_clip_id == pair.left_clip_id
        )
        if current and not same_run:
            key = (current[0].camera_id, current[0].activity_day_kst)
            by_night.setdefault(key, []).append(tuple(current))
            current = []
        current.append(pair)
        previous = pair
    if current:
        key = (current[0].camera_id, current[0].activity_day_kst)
        by_night.setdefault(key, []).append(tuple(current))
    return by_night


def select_sequence_runs(
    accounted: Iterable[AccountedClip],
    *,
    development_nights: tuple[CameraNight, ...],
    target_edges: int = 120,
    seed: str = SELECTION_SEED,
) -> tuple[SelectedSequenceRun, ...]:
    nights = tuple(sorted(set(development_nights)))
    if (
        len(nights) != 6
        or len({camera_id for camera_id, _ in nights}) < 2
        or target_edges < len(nights)
    ):
        raise SequenceSelectionBlocked(BLOCKED_INSUFFICIENT_SEQUENCE_RUNS)

    runs_by_night = _complete_runs(accounted)
    chosen: list[tuple[CameraNight, tuple[BoundaryPair, ...]]] = []
    for night in nights:
        candidates = runs_by_night.get(night, [])
        if not candidates:
            raise SequenceSelectionBlocked(BLOCKED_INSUFFICIENT_SEQUENCE_RUNS)
        best = min(
            candidates,
            key=lambda run: (
                -len(run),
                _stable_hash(seed, night[0], night[1].isoformat(), run[0].pair_id),
            ),
        )
        chosen.append((night, best))
    if sum(len(run) for _, run in chosen) < target_edges:
        raise SequenceSelectionBlocked(BLOCKED_INSUFFICIENT_SEQUENCE_RUNS)

    quotas = [1] * len(chosen)
    remaining = target_edges - len(chosen)
    order = sorted(
        range(len(chosen)),
        key=lambda index: _stable_hash(
            seed,
            "quota",
            chosen[index][0][0],
            chosen[index][0][1].isoformat(),
        ),
    )
    while remaining:
        progressed = False
        for index in order:
            if quotas[index] < len(chosen[index][1]):
                quotas[index] += 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
        if not progressed:
            raise SequenceSelectionBlocked(BLOCKED_INSUFFICIENT_SEQUENCE_RUNS)

    selected: list[SelectedSequenceRun] = []
    for (night, run), quota in zip(chosen, quotas, strict=True):
        window_count = len(run) - quota + 1
        start = int(
            _stable_hash(seed, "window", night[0], night[1].isoformat()),
            16,
        ) % window_count
        selected.append(SelectedSequenceRun(
            camera_id=night[0],
            activity_day_kst=night[1],
            pairs=run[start:start + quota],
            left_censored=start > 0,
            right_censored=start + quota < len(run),
        ))
    return tuple(selected)


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


def build_sequence_manifest(
    *,
    accounted: Iterable[AccountedClip],
    development_nights: tuple[CameraNight, ...],
    source_snapshot_sha256: str,
    blocked_set_sha256: str,
    seed: str = SELECTION_SEED,
) -> dict[str, object]:
    if (
        len(source_snapshot_sha256) != 64
        or len(blocked_set_sha256) != 64
    ):
        raise SequenceSelectionBlocked(BLOCKED_INSUFFICIENT_SEQUENCE_RUNS)
    selected = select_sequence_runs(
        accounted,
        development_nights=development_nights,
        target_edges=120,
        seed=seed,
    )
    run_rows: list[dict[str, object]] = []
    pair_rows: list[dict[str, object]] = []
    clip_ids: set[str] = set()
    ordinal = 0
    for run_ordinal, run in enumerate(selected, 1):
        run_rows.append({
            "run_ordinal": run_ordinal,
            "camera_id": run.camera_id,
            "activity_day_kst": run.activity_day_kst.isoformat(),
            "pair_count": len(run.pairs),
            "left_censored": run.left_censored,
            "right_censored": run.right_censored,
        })
        for pair in run.pairs:
            ordinal += 1
            clip_ids.update((pair.left_clip_id, pair.right_clip_id))
            pair_rows.append({
                "split": "development",
                "ordinal": ordinal,
                "run_ordinal": run_ordinal,
                "left_clip_id": pair.left_clip_id,
                "right_clip_id": pair.right_clip_id,
                "camera_id": pair.camera_id,
                "activity_day_kst": pair.activity_day_kst.isoformat(),
                "gap_sec": pair.gap_sec,
                "gap_bin": pair.gap_bin,
                "pair_digest": pair.pair_id,
            })
    manifest: dict[str, object] = {
        "schema_version": "rba-event-sequence-review-manifest-v2",
        "experiment_id": EXPERIMENT_ID,
        "selection_seed": seed,
        "source_snapshot_sha256": source_snapshot_sha256,
        "blocked_set_sha256": blocked_set_sha256,
        "camera_nights": [
            [camera_id, activity_day.isoformat()]
            for camera_id, activity_day in sorted(development_nights)
        ],
        "runs": run_rows,
        "pairs": pair_rows,
        "unique_clip_count": len(clip_ids),
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        _canonical_bytes(manifest)
    ).hexdigest()
    return manifest


def manifest_from_base_artifact(
    base: dict[str, Any],
    *,
    seed: str = SELECTION_SEED,
) -> dict[str, object]:
    if base.get("schema_version") != "rba-event-boundary-manifest-v2":
        raise SequenceSelectionBlocked(BLOCKED_INSUFFICIENT_SEQUENCE_RUNS)
    raw_nights = base.get("camera_nights")
    raw_accounting = base.get("accounting")
    if not isinstance(raw_nights, dict) or not isinstance(raw_accounting, list):
        raise SequenceSelectionBlocked(BLOCKED_INSUFFICIENT_SEQUENCE_RUNS)
    development = raw_nights.get("development")
    if not isinstance(development, list):
        raise SequenceSelectionBlocked(BLOCKED_INSUFFICIENT_SEQUENCE_RUNS)
    try:
        nights = tuple(
            (str(camera_id), date.fromisoformat(str(activity_day)))
            for camera_id, activity_day in development
        )
        accounted = tuple(AccountedClip(
            clip_id=str(row["clip_id"]),
            camera_id=str(row["camera_id"]),
            started_at=datetime.fromisoformat(str(row["started_at"])),
            activity_day_kst=date.fromisoformat(str(row["activity_day_kst"])),
            duration_sec=(
                float(row["duration_sec"])
                if row.get("duration_sec") is not None
                else None
            ),
            kind=row["kind"],
            reason_code=(
                str(row["reason_code"])
                if row.get("reason_code") is not None
                else None
            ),
        ) for row in raw_accounting)
    except (KeyError, TypeError, ValueError) as exc:
        raise SequenceSelectionBlocked(
            BLOCKED_INSUFFICIENT_SEQUENCE_RUNS
        ) from exc
    return build_sequence_manifest(
        accounted=accounted,
        development_nights=nights,
        source_snapshot_sha256=str(base.get("source_snapshot_sha256", "")),
        blocked_set_sha256=str(base.get("blocked_set_sha256", "")),
        seed=seed,
    )

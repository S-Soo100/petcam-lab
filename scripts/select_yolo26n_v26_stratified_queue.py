"""Deterministic multi-stratum selector for the YOLO26n v2.6 blind queue."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
import hashlib
import math
import re

from scripts.build_yolo26n_v26_recent_dense_queue import DenseFrame


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REASON_ORDER = {
    "feedback-band": 0,
    "detection-transition": 1,
    "low-confidence-detection": 2,
    "motion-without-detection": 3,
    "scene-change": 4,
}


@dataclass(frozen=True, slots=True)
class StratifiedQueueContract:
    coverage_per_clip: int = 2
    uncertainty_count: int = 900
    hard_negative_count: int = 700
    iid_random_count: int = 400
    gold_count: int = 200
    seed: str = "yolo26n-v26-recent-dense-v1"
    protected_dhash_distance: int = 2
    temporal_dhash_distance: int = 2
    low_confidence_ceiling: float = 0.5
    motion_threshold: float = 5.0
    scene_threshold: float = 5.0
    hard_negative_confidence_floor: float = 0.5
    hard_negative_motion_ceiling: float = 1.5
    uncertainty_near_duplicate_per_clip: int = 2
    hard_negative_near_duplicate_per_clip: int = 1
    iid_near_duplicate_per_clip: int = 1

    def validate(self) -> "StratifiedQueueContract":
        if type(self.coverage_per_clip) is not int or self.coverage_per_clip < 1:
            raise ValueError("coverage_per_clip must be positive")
        for name, value in (
            ("uncertainty_count", self.uncertainty_count),
            ("hard_negative_count", self.hard_negative_count),
            ("iid_random_count", self.iid_random_count),
            ("gold_count", self.gold_count),
            ("uncertainty_near_duplicate_per_clip", self.uncertainty_near_duplicate_per_clip),
            ("hard_negative_near_duplicate_per_clip", self.hard_negative_near_duplicate_per_clip),
            ("iid_near_duplicate_per_clip", self.iid_near_duplicate_per_clip),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.seed, str) or not self.seed:
            raise ValueError("seed is missing")
        for name, value in (
            ("protected_dhash_distance", self.protected_dhash_distance),
            ("temporal_dhash_distance", self.temporal_dhash_distance),
        ):
            if type(value) is not int or not 0 <= value <= 64:
                raise ValueError(f"{name} must be in 0..64")
        for name, value in (
            ("low_confidence_ceiling", self.low_confidence_ceiling),
            ("motion_threshold", self.motion_threshold),
            ("scene_threshold", self.scene_threshold),
            ("hard_negative_confidence_floor", self.hard_negative_confidence_floor),
            ("hard_negative_motion_ceiling", self.hard_negative_motion_ceiling),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                raise ValueError(f"{name} must be finite and non-negative")
        if not 0 <= self.low_confidence_ceiling <= 1:
            raise ValueError("low_confidence_ceiling must be in 0..1")
        if not 0 <= self.hard_negative_confidence_floor <= 1:
            raise ValueError("hard_negative_confidence_floor must be in 0..1")
        return self


@dataclass(frozen=True, slots=True)
class StratifiedSelectedFrame:
    frame: DenseFrame
    stratum: str
    reasons: tuple[str, ...]
    double_review: bool


@dataclass(frozen=True, slots=True)
class StratifiedSelection:
    items: tuple[StratifiedSelectedFrame, ...]
    strata_counts: dict[str, int]
    excluded_protected: int
    review_task_count: int


def _hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _canonical(frame: DenseFrame) -> tuple[str, int, str]:
    return frame.clip_ref, frame.timestamp_ms, frame.image_sha256


def _hash_rank(seed: str, namespace: str, frame: DenseFrame) -> str:
    return hashlib.sha256(
        f"{seed}:{namespace}:{frame.image_sha256}".encode()
    ).hexdigest()


def _uncertainty_reasons(
    frame: DenseFrame,
    *,
    prior: DenseFrame | None,
    contract: StratifiedQueueContract,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if frame.feedback_band:
        reasons.append("feedback-band")
    if prior is not None and (prior.detection_count > 0) != (frame.detection_count > 0):
        reasons.append("detection-transition")
    if 0 < frame.max_confidence < contract.low_confidence_ceiling:
        reasons.append("low-confidence-detection")
    if frame.detection_count == 0 and frame.motion_score >= contract.motion_threshold:
        reasons.append("motion-without-detection")
    if frame.scene_score >= contract.scene_threshold:
        reasons.append("scene-change")
    return tuple(sorted(set(reasons), key=_REASON_ORDER.__getitem__))


def _coverage_frames(frames: Sequence[DenseFrame], count: int) -> tuple[DenseFrame, ...]:
    if len(frames) < count:
        raise ValueError("coverage shortage")
    indices = [round((index + 1) * (len(frames) - 1) / (count + 1)) for index in range(count)]
    return tuple(frames[index] for index in indices)


def select_stratified_queue(
    frames: Sequence[DenseFrame],
    *,
    contract: StratifiedQueueContract = StratifiedQueueContract(),
    protected_sha256: set[str] | None = None,
    protected_dhash64: set[int] | None = None,
) -> StratifiedSelection:
    contract.validate()
    protected_sha256 = protected_sha256 or set()
    protected_dhash64 = protected_dhash64 or set()
    if any(_SHA256.fullmatch(value) is None for value in protected_sha256):
        raise ValueError("protected SHA is invalid")
    if any(type(value) is not int or not 0 <= value < 2**64 for value in protected_dhash64):
        raise ValueError("protected dHash is invalid")

    validated = sorted((frame.validate() for frame in frames), key=_canonical)
    if not validated:
        raise ValueError("dense frame input is empty")

    reasons_by_sha: dict[str, tuple[str, ...]] = {}
    by_clip_before_filter: dict[str, list[DenseFrame]] = defaultdict(list)
    for frame in validated:
        by_clip_before_filter[frame.clip_ref].append(frame)
    for clip in sorted(by_clip_before_filter):
        prior: DenseFrame | None = None
        for frame in by_clip_before_filter[clip]:
            reasons_by_sha[frame.image_sha256] = _uncertainty_reasons(
                frame, prior=prior, contract=contract
            )
            prior = frame

    eligible: list[DenseFrame] = []
    excluded_protected = 0
    seen_sha: set[str] = set()
    protected_values = tuple(sorted(protected_dhash64))
    for frame in validated:
        if frame.image_sha256 in seen_sha:
            continue
        seen_sha.add(frame.image_sha256)
        is_protected = frame.image_sha256 in protected_sha256 or any(
            _hamming(frame.dhash64, protected) <= contract.protected_dhash_distance
            for protected in protected_values
        )
        if is_protected:
            excluded_protected += 1
        else:
            eligible.append(frame)

    by_clip: dict[str, list[DenseFrame]] = defaultdict(list)
    for frame in eligible:
        by_clip[frame.clip_ref].append(frame)
    if set(by_clip) != set(by_clip_before_filter):
        raise ValueError("protected filter removed an entire clip")

    chosen: dict[str, tuple[DenseFrame, str]] = {}
    near_exception_counts: dict[tuple[str, str], int] = defaultdict(int)

    def add(
        frame: DenseFrame,
        stratum: str,
        *,
        allow_near: bool,
        near_duplicate_budget_per_clip: int = 0,
    ) -> bool:
        if frame.image_sha256 in chosen:
            return False
        is_near = any(
            existing.clip_ref == frame.clip_ref
            and _hamming(existing.dhash64, frame.dhash64)
            <= contract.temporal_dhash_distance
            for existing, _ in chosen.values()
        )
        if not allow_near and is_near:
            budget_key = (stratum, frame.clip_ref)
            if near_exception_counts[budget_key] >= near_duplicate_budget_per_clip:
                return False
            near_exception_counts[budget_key] += 1
        chosen[frame.image_sha256] = (frame, stratum)
        return True

    for clip in sorted(by_clip):
        for frame in _coverage_frames(by_clip[clip], contract.coverage_per_clip):
            if not add(frame, "coverage", allow_near=True):
                raise ValueError("coverage frame identity collision")

    def take_round_robin(
        *,
        stratum: str,
        pool: Sequence[DenseFrame],
        count: int,
        key: Callable[[DenseFrame], object],
        near_duplicate_budget_per_clip: int = 0,
    ) -> None:
        if count == 0:
            return
        grouped: dict[str, list[DenseFrame]] = defaultdict(list)
        for frame in pool:
            if frame.image_sha256 not in chosen:
                grouped[frame.clip_ref].append(frame)
        for values in grouped.values():
            values.sort(key=key)
        added = 0
        while added < count:
            progressed = False
            for clip in sorted(grouped):
                values = grouped[clip]
                while values:
                    candidate = values.pop(0)
                    if add(
                        candidate,
                        stratum,
                        allow_near=False,
                        near_duplicate_budget_per_clip=near_duplicate_budget_per_clip,
                    ):
                        added += 1
                        progressed = True
                        break
                if added == count:
                    break
            if not progressed:
                raise ValueError(f"{stratum} shortage")

    uncertainty_pool = [
        frame for frame in eligible if reasons_by_sha.get(frame.image_sha256)
    ]
    take_round_robin(
        stratum="uncertainty",
        pool=uncertainty_pool,
        count=contract.uncertainty_count,
        key=lambda frame: (
            min(_REASON_ORDER[reason] for reason in reasons_by_sha[frame.image_sha256]),
            _hash_rank(contract.seed, "uncertainty", frame),
        ),
        near_duplicate_budget_per_clip=contract.uncertainty_near_duplicate_per_clip,
    )

    hard_negative_pool = [
        frame
        for frame in eligible
        if frame.detection_count > 0
        and frame.max_confidence >= contract.hard_negative_confidence_floor
        and frame.motion_score <= contract.hard_negative_motion_ceiling
    ]
    take_round_robin(
        stratum="hard-negative-candidate",
        pool=hard_negative_pool,
        count=contract.hard_negative_count,
        key=lambda frame: (
            -frame.max_confidence,
            frame.motion_score,
            _hash_rank(contract.seed, "hard-negative", frame),
        ),
        near_duplicate_budget_per_clip=contract.hard_negative_near_duplicate_per_clip,
    )

    take_round_robin(
        stratum="iid-random",
        pool=eligible,
        count=contract.iid_random_count,
        key=lambda frame: _hash_rank(contract.seed, "iid", frame),
        near_duplicate_budget_per_clip=contract.iid_near_duplicate_per_clip,
    )

    if contract.gold_count > len(chosen):
        raise ValueError("gold double-review shortage")
    gold_sha = {
        frame.image_sha256
        for frame, _ in sorted(
            chosen.values(),
            key=lambda item: _hash_rank(contract.seed, "gold", item[0]),
        )[: contract.gold_count]
    }
    strata_counts = {
        name: sum(stratum == name for _, stratum in chosen.values())
        for name in ("coverage", "uncertainty", "hard-negative-candidate", "iid-random")
    }
    items = tuple(
        StratifiedSelectedFrame(
            frame=frame,
            stratum=stratum,
            reasons=reasons_by_sha.get(frame.image_sha256, ()),
            double_review=frame.image_sha256 in gold_sha,
        )
        for frame, stratum in sorted(chosen.values(), key=lambda item: _canonical(item[0]))
    )
    return StratifiedSelection(
        items=items,
        strata_counts=strata_counts,
        excluded_protected=excluded_protected,
        review_task_count=len(items) + len(gold_sha),
    )

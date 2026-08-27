"""Pure contracts for the YOLO26n v2.6 recent dense review queue.

The operational extractor writes only private artifacts.  This module keeps the
selection and human-export gates deterministic so they can be reviewed before
any Mac mini source media is read.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
import re


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERDICTS = frozenset({"gecko_present", "gecko_absent", "uncertain", "media_error"})
_HARD_REASON_PRIORITY = {
    "feedback-band": 0,
    "detection-transition": 1,
    "motion-without-detection": 2,
    "persistent-detection": 3,
    "scene-change": 4,
}


@dataclass(frozen=True, slots=True)
class SamplingContract:
    sample_fps: float = 2.0
    coverage_per_clip: int = 4
    queue_min: int = 2500
    queue_max: int = 4000
    protected_dhash_distance: int = 2
    temporal_dhash_distance: int = 2
    motion_threshold: float = 10.0
    scene_threshold: float = 10.0
    persistent_confidence: float = 0.5

    def validate(self) -> "SamplingContract":
        if (
            isinstance(self.sample_fps, bool)
            or not isinstance(self.sample_fps, (int, float))
            or not math.isfinite(float(self.sample_fps))
            or float(self.sample_fps) <= 0
        ):
            raise ValueError("sample_fps must be finite and positive")
        for name, value in (
            ("coverage_per_clip", self.coverage_per_clip),
            ("queue_min", self.queue_min),
            ("queue_max", self.queue_max),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.queue_min > self.queue_max or self.coverage_per_clip > self.queue_max:
            raise ValueError("queue bounds are inconsistent")
        for name, value in (
            ("protected_dhash_distance", self.protected_dhash_distance),
            ("temporal_dhash_distance", self.temporal_dhash_distance),
        ):
            if type(value) is not int or not 0 <= value <= 64:
                raise ValueError(f"{name} must be in 0..64")
        for name, value in (
            ("motion_threshold", self.motion_threshold),
            ("scene_threshold", self.scene_threshold),
            ("persistent_confidence", self.persistent_confidence),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                raise ValueError(f"{name} must be finite and non-negative")
        if float(self.persistent_confidence) > 1:
            raise ValueError("persistent_confidence must be in 0..1")
        return self


@dataclass(frozen=True, slots=True)
class DenseFrame:
    clip_ref: str
    camera_night: str
    timestamp_ms: int
    image_sha256: str
    dhash64: int
    detection_count: int
    max_confidence: float
    motion_score: float
    scene_score: float
    feedback_band: bool

    def validate(self) -> "DenseFrame":
        if not isinstance(self.clip_ref, str) or not self.clip_ref:
            raise ValueError("clip_ref is missing")
        if not isinstance(self.camera_night, str) or not self.camera_night:
            raise ValueError("camera_night is missing")
        if type(self.timestamp_ms) is not int or self.timestamp_ms < 0:
            raise ValueError("timestamp_ms is invalid")
        if not isinstance(self.image_sha256, str) or _SHA256.fullmatch(self.image_sha256) is None:
            raise ValueError("image_sha256 is invalid")
        if type(self.dhash64) is not int or not 0 <= self.dhash64 < 2**64:
            raise ValueError("dhash64 is invalid")
        if type(self.detection_count) is not int or self.detection_count < 0:
            raise ValueError("detection_count is invalid")
        for name, value in (
            ("max_confidence", self.max_confidence),
            ("motion_score", self.motion_score),
            ("scene_score", self.scene_score),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                raise ValueError(f"{name} is invalid")
        if float(self.max_confidence) > 1:
            raise ValueError("max_confidence is invalid")
        if self.detection_count == 0 and float(self.max_confidence) != 0:
            raise ValueError("zero detections cannot have confidence")
        if type(self.feedback_band) is not bool:
            raise ValueError("feedback_band must be bool")
        return self


@dataclass(frozen=True, slots=True)
class SelectedFrame:
    frame: DenseFrame
    reasons: tuple[str, ...]


def dense_timestamps_ms(duration_sec: float, *, sample_fps: float = 2.0) -> tuple[int, ...]:
    """Return exact integer-millisecond sample times without seeking past EOF."""

    if (
        isinstance(duration_sec, bool)
        or not isinstance(duration_sec, (int, float))
        or not math.isfinite(float(duration_sec))
        or float(duration_sec) <= 0
        or isinstance(sample_fps, bool)
        or not isinstance(sample_fps, (int, float))
        or not math.isfinite(float(sample_fps))
        or float(sample_fps) <= 0
    ):
        raise ValueError("duration and sample_fps must be finite and positive")
    interval_ms_float = 1000.0 / float(sample_fps)
    interval_ms = round(interval_ms_float)
    if interval_ms < 1 or not math.isclose(interval_ms_float, interval_ms, abs_tol=1e-9):
        raise ValueError("sample_fps must map to an exact millisecond interval")
    duration_ms = float(duration_sec) * 1000.0
    return tuple(range(0, math.ceil(duration_ms), interval_ms))


def _hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _canonical_frame_key(frame: DenseFrame) -> tuple[str, int, str]:
    return frame.clip_ref, frame.timestamp_ms, frame.image_sha256


def _uniform_frames(frames: Sequence[DenseFrame], count: int) -> tuple[DenseFrame, ...]:
    if len(frames) < count:
        raise ValueError("coverage shortage")
    if count == 1:
        return (frames[len(frames) // 2],)
    indices = [round(index * (len(frames) - 1) / (count - 1)) for index in range(count)]
    return tuple(frames[index] for index in indices)


def _frame_reasons(
    frame: DenseFrame,
    *,
    prior: DenseFrame | None,
    contract: SamplingContract,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if frame.feedback_band:
        reasons.append("feedback-band")
    if prior is not None and prior.detection_count != frame.detection_count:
        reasons.append("detection-transition")
    if frame.detection_count == 0 and frame.motion_score >= contract.motion_threshold:
        reasons.append("motion-without-detection")
    if (
        frame.detection_count > 0
        and frame.max_confidence >= contract.persistent_confidence
    ):
        reasons.append("persistent-detection")
    if frame.scene_score >= contract.scene_threshold:
        reasons.append("scene-change")
    return tuple(sorted(set(reasons), key=_HARD_REASON_PRIORITY.__getitem__))


def select_review_queue(
    frames: Sequence[DenseFrame],
    *,
    contract: SamplingContract = SamplingContract(),
    protected_sha256: set[str] | None = None,
    protected_dhash64: set[int] | None = None,
) -> tuple[SelectedFrame, ...]:
    """Select one deterministic queue while preserving every valid clip."""

    contract.validate()
    protected_sha256 = protected_sha256 or set()
    protected_dhash64 = protected_dhash64 or set()
    if any(_SHA256.fullmatch(value) is None for value in protected_sha256):
        raise ValueError("protected SHA is invalid")
    if any(type(value) is not int or not 0 <= value < 2**64 for value in protected_dhash64):
        raise ValueError("protected dHash is invalid")

    validated = sorted((frame.validate() for frame in frames), key=_canonical_frame_key)
    if not validated:
        raise ValueError("dense frame input is empty")
    if any(frame.image_sha256 in protected_sha256 for frame in validated):
        raise ValueError("protected exact overlap")
    if any(
        _hamming(frame.dhash64, protected) <= contract.protected_dhash_distance
        for frame in validated
        for protected in protected_dhash64
    ):
        raise ValueError("protected near overlap")

    unique: list[DenseFrame] = []
    seen_sha: set[str] = set()
    for frame in validated:
        if frame.image_sha256 in seen_sha:
            continue
        seen_sha.add(frame.image_sha256)
        unique.append(frame)

    by_clip: dict[str, list[DenseFrame]] = defaultdict(list)
    for frame in unique:
        by_clip[frame.clip_ref].append(frame)
    if contract.coverage_per_clip * len(by_clip) > contract.queue_max:
        raise ValueError("queue_max cannot preserve every clip coverage")

    reasons_by_sha: dict[str, set[str]] = defaultdict(set)
    hard_rows: list[DenseFrame] = []
    for clip in sorted(by_clip):
        prior: DenseFrame | None = None
        for frame in by_clip[clip]:
            reasons = _frame_reasons(frame, prior=prior, contract=contract)
            if reasons:
                hard_rows.append(frame)
                reasons_by_sha[frame.image_sha256].update(reasons)
            prior = frame

    chosen: dict[str, DenseFrame] = {}

    def add(frame: DenseFrame, reason: str, *, allow_near: bool) -> bool:
        if frame.image_sha256 in chosen:
            reasons_by_sha[frame.image_sha256].add(reason)
            return True
        if len(chosen) >= contract.queue_max:
            return False
        same_clip = [row for row in chosen.values() if row.clip_ref == frame.clip_ref]
        if not allow_near and any(
            _hamming(row.dhash64, frame.dhash64) <= contract.temporal_dhash_distance
            for row in same_clip
        ):
            return False
        chosen[frame.image_sha256] = frame
        reasons_by_sha[frame.image_sha256].add(reason)
        return True

    hard_rows.sort(
        key=lambda frame: (
            min(_HARD_REASON_PRIORITY[reason] for reason in reasons_by_sha[frame.image_sha256]),
            *_canonical_frame_key(frame),
        )
    )
    hard_by_clip: dict[str, list[DenseFrame]] = defaultdict(list)
    for frame in hard_rows:
        hard_by_clip[frame.clip_ref].append(frame)
    for clip in sorted(by_clip):
        current = 0
        # Hard cases count toward coverage, so reserve every clip's quota before
        # any one noisy clip can consume the global queue budget.
        for frame in hard_by_clip.get(clip, []):
            if current >= contract.coverage_per_clip:
                break
            before = len(chosen)
            add(frame, "hard-case", allow_near=True)
            if len(chosen) > before:
                current += 1
        for frame in _uniform_frames(by_clip[clip], contract.coverage_per_clip):
            if current >= contract.coverage_per_clip:
                break
            before = len(chosen)
            add(frame, "coverage", allow_near=True)
            if len(chosen) > before:
                current += 1
        if current < contract.coverage_per_clip:
            for frame in by_clip[clip]:
                if current >= contract.coverage_per_clip:
                    break
                before = len(chosen)
                add(frame, "coverage", allow_near=True)
                if len(chosen) > before:
                    current += 1
        if current < contract.coverage_per_clip:
            raise ValueError("coverage shortage")

    for frame in hard_rows:
        if len(chosen) == contract.queue_max:
            break
        add(frame, "hard-case", allow_near=True)

    for frame in unique:
        if len(chosen) >= contract.queue_min:
            break
        add(frame, "deterministic-fill", allow_near=False)
    if len(chosen) < contract.queue_min:
        raise ValueError("queue minimum shortage after temporal dedup")

    return tuple(
        SelectedFrame(
            frame=frame,
            reasons=tuple(
                sorted(
                    reasons_by_sha[frame.image_sha256],
                    key=lambda reason: (_HARD_REASON_PRIORITY.get(reason, 100), reason),
                )
            ),
        )
        for frame in sorted(chosen.values(), key=_canonical_frame_key)
    )


def assert_human_export_ready(
    rows: Sequence[Mapping[str, object]],
    selected: Sequence[SelectedFrame],
) -> dict[str, int]:
    """Require one immutable human verdict for every selected image before training."""

    expected = {row.frame.image_sha256 for row in selected}
    if len(expected) != len(selected):
        raise ValueError("selected frame identities are not unique")
    actual: dict[str, Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {"image_sha256", "verdict", "box_count"}:
            raise ValueError("human export row contract mismatch")
        image_sha = row["image_sha256"]
        verdict = row["verdict"]
        box_count = row["box_count"]
        if not isinstance(image_sha, str) or _SHA256.fullmatch(image_sha) is None:
            raise ValueError("human export image SHA is invalid")
        if image_sha in actual:
            raise ValueError("human export contains duplicate image rows")
        if verdict not in _VERDICTS:
            raise ValueError("human export verdict is invalid")
        if type(box_count) is not int or box_count < 0:
            raise ValueError("human export box_count is invalid")
        if verdict == "gecko_present" and box_count < 1:
            raise ValueError("present frame must have at least one box")
        if verdict == "gecko_absent" and box_count != 0:
            raise ValueError("absent frame must have zero boxes")
        if verdict in {"uncertain", "media_error"} and box_count != 0:
            raise ValueError("excluded frame must have zero boxes")
        actual[image_sha] = row
    if set(actual) != expected:
        raise ValueError("human export must cover the exact selected frame set")

    present = sum(row["verdict"] == "gecko_present" for row in actual.values())
    absent = sum(row["verdict"] == "gecko_absent" for row in actual.values())
    excluded = len(actual) - present - absent
    return {
        "present": present,
        "absent": absent,
        "excluded": excluded,
        "box_count": sum(int(row["box_count"]) for row in actual.values()),
    }

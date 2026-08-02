"""Local VLM 사건 경계 baseline의 순수 계약과 scorer야."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Iterable, Literal, Mapping


Decision = Literal["same_event", "different_event", "uncertain"]
ReasonCode = Literal[
    "continuous_motion",
    "continuous_posture",
    "clear_stop",
    "new_activity",
    "scene_discontinuity",
    "insufficient_visual",
]

A_FRAME_FRACTIONS = (0.15, 0.55, 0.85, 0.98)
B_FRAME_FRACTIONS = (0.02, 0.15, 0.55, 0.85)
DECISIONS = ("same_event", "different_event", "uncertain")
REASON_CODES = (
    "continuous_motion",
    "continuous_posture",
    "clear_stop",
    "new_activity",
    "scene_discontinuity",
    "insufficient_visual",
)

RESULT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": list(DECISIONS)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason_code": {"type": "string", "enum": list(REASON_CODES)},
    },
    "required": ["decision", "confidence", "reason_code"],
    "additionalProperties": False,
}

PROMPT_VERSION = "local-vlm-event-boundary-v1"
PROMPT = """You are checking whether two consecutive gecko camera clips show one continuous physical activity event.
Image A contains four frames from video A in time order. Image B contains four frames from the following video B in time order.
If one combined image is provided, its top half is video A and its bottom half is video B.
Use only visible continuity. same_event means the same physical activity/posture transition continues across A to B. different_event means the activity clearly stopped, reset, or a new activity/scene begins. If the images cannot establish this, choose uncertain.
Return one JSON object only with keys decision, confidence, reason_code.
decision: same_event|different_event|uncertain
confidence: number from 0 to 1
reason_code: continuous_motion|continuous_posture|clear_stop|new_activity|scene_discontinuity|insufficient_visual"""


@dataclass(frozen=True, slots=True)
class BoundaryPrediction:
    decision: Decision
    confidence: float
    reason_code: ReasonCode


@dataclass(frozen=True, slots=True)
class BoundaryScore:
    expected: int
    completed: int
    schema_valid: int
    same_total: int
    different_total: int
    same_correct: int
    different_correct: int
    overmerge: int
    oversplit: int
    uncertain: int
    confusion: dict[str, dict[str, int]]
    same_recall: float
    same_recall_wilson95: tuple[float, float]
    verdict: str


def expected_sheet_count(representation: str, *, pair_count: int) -> int:
    if pair_count < 0:
        raise ValueError("pair_count")
    if representation == "two_images":
        return pair_count * 2
    if representation == "combined_4x2":
        return pair_count
    raise ValueError("representation")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def parse_prediction(raw: str) -> BoundaryPrediction:
    try:
        payload = json.loads(raw, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(payload, dict) or set(payload) != set(RESULT_SCHEMA["required"]):
        raise ValueError("invalid_keys")
    decision = payload["decision"]
    confidence = payload["confidence"]
    reason_code = payload["reason_code"]
    if decision not in DECISIONS:
        raise ValueError("invalid_decision")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("invalid_confidence")
    if not math.isfinite(float(confidence)) or not 0 <= float(confidence) <= 1:
        raise ValueError("invalid_confidence")
    if reason_code not in REASON_CODES:
        raise ValueError("invalid_reason_code")
    return BoundaryPrediction(
        decision=decision,
        confidence=float(confidence),
        reason_code=reason_code,
    )


def wilson_interval(successes: int, total: int, *, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0 or successes < 0 or successes > total:
        raise ValueError("wilson_counts")
    probability = successes / total
    denominator = 1 + z * z / total
    center = (probability + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            probability * (1 - probability) / total
            + z * z / (4 * total * total)
        )
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def score_predictions(
    human: Mapping[str, Decision],
    predictions: Mapping[str, BoundaryPrediction | None],
    *,
    expected_count: int,
) -> BoundaryScore:
    if len(human) != expected_count or set(predictions) != set(human):
        raise ValueError("identity_or_count_mismatch")
    if any(value == "uncertain" for value in human.values()):
        raise ValueError("human_uncertain_forbidden")

    matrix = {actual: {predicted: 0 for predicted in DECISIONS} for actual in DECISIONS[:2]}
    valid = 0
    overmerge = 0
    oversplit = 0
    uncertain = 0
    for identity, actual in human.items():
        prediction = predictions[identity]
        if prediction is None:
            continue
        valid += 1
        matrix[actual][prediction.decision] += 1
        if actual == "different_event" and prediction.decision == "same_event":
            overmerge += 1
        if actual == "same_event" and prediction.decision == "different_event":
            oversplit += 1
        if prediction.decision == "uncertain":
            uncertain += 1

    human_counts = Counter(human.values())
    same_total = human_counts["same_event"]
    different_total = human_counts["different_event"]
    same_correct = matrix["same_event"]["same_event"]
    different_correct = matrix["different_event"]["different_event"]
    same_recall = same_correct / same_total if same_total else 0.0
    interval = wilson_interval(same_correct, same_total) if same_total else (0.0, 0.0)

    completed = len(predictions)
    if completed != expected_count or valid != expected_count:
        verdict = "REJECT_RELIABILITY"
    elif overmerge:
        verdict = "REJECT_SAFETY"
    elif same_correct < math.ceil(same_total / 2):
        verdict = "REJECT_UTILITY"
    else:
        verdict = "DEVELOPMENT_CANDIDATE"
    return BoundaryScore(
        expected=expected_count,
        completed=completed,
        schema_valid=valid,
        same_total=same_total,
        different_total=different_total,
        same_correct=same_correct,
        different_correct=different_correct,
        overmerge=overmerge,
        oversplit=oversplit,
        uncertain=uncertain,
        confusion=matrix,
        same_recall=same_recall,
        same_recall_wilson95=interval,
        verdict=verdict,
    )


def stable_pair_order(keys: Iterable[str], *, seed: str) -> tuple[str, ...]:
    unique = set(keys)
    return tuple(sorted(
        unique,
        key=lambda key: hashlib.sha256(f"{seed}\0{key}".encode()).digest(),
    ))

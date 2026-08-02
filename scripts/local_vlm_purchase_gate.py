"""Mac Studio 구매 판단 실험의 순수 synthetic/scoring 계약이야."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Literal, Mapping

import cv2
import numpy as np


MODELS = (
    "gemma3:4b-it-q8_0",
    "gemma4:12b-it-qat",
    "qwen3-vl:8b-instruct-q4_K_M",
    "qwen3-vl:30b-a3b-instruct-q4_K_M",
)
MODEL_STATUSES = {
    "PASS",
    "QUALITY_FAIL",
    "SYNTHETIC_GATE_FAIL",
    "RESOURCE_FAIL",
    "TAG_UNAVAILABLE",
}


@dataclass(frozen=True, slots=True)
class SyntheticPrediction:
    background: Literal["dark", "lit"]
    position_change: Literal["yes", "no", "uncertain"]


@dataclass(frozen=True, slots=True)
class ClipSyntheticCase:
    name: str
    frames: tuple[np.ndarray, ...]
    expected: SyntheticPrediction


@dataclass(frozen=True, slots=True)
class BoundarySyntheticCase:
    name: str
    frames: tuple[np.ndarray, ...]
    expected: Literal["same_event", "different_event"]


def _base(*, dark: bool = False) -> np.ndarray:
    value = 4 if dark else 72
    frame = np.full((360, 640, 3), value, dtype=np.uint8)
    if not dark:
        cv2.line(frame, (20, 285), (620, 285), (115, 115, 115), 8)
    return frame


def _oval(frame: np.ndarray, center: tuple[int, int]) -> np.ndarray:
    result = frame.copy()
    cv2.ellipse(result, center, (42, 18), 10, 0, 360, (210, 210, 210), -1)
    cv2.circle(result, (center[0] + 31, center[1] - 2), 5, (250, 250, 250), -1)
    return result


def _clip_frames(*, moving: bool, shadow: bool = False, brightness: bool = False) -> tuple[np.ndarray, ...]:
    frames = []
    for index in range(12):
        background = _base()
        if brightness:
            background = np.clip(background.astype(np.int16) + (index - 5) * 5, 0, 255).astype(np.uint8)
        if shadow:
            left = 30 + index * 42
            cv2.rectangle(background, (left, 30), (min(639, left + 120), 330), (20, 20, 20), -1)
        center = (160 + index * 24, 250) if moving else (310, 250)
        frames.append(_oval(background, center))
    return tuple(frames)


def clip_synthetic_cases() -> tuple[ClipSyntheticCase, ...]:
    dark = tuple(_base(dark=True) for _ in range(12))
    return (
        ClipSyntheticCase("dark", dark, SyntheticPrediction("dark", "no")),
        ClipSyntheticCase("clean_static", _clip_frames(moving=False), SyntheticPrediction("lit", "no")),
        ClipSyntheticCase("clean_moving", _clip_frames(moving=True), SyntheticPrediction("lit", "yes")),
        ClipSyntheticCase("shadow_static", _clip_frames(moving=False, shadow=True), SyntheticPrediction("lit", "no")),
        ClipSyntheticCase("shadow_moving", _clip_frames(moving=True, shadow=True), SyntheticPrediction("lit", "yes")),
        ClipSyntheticCase("brightness_static", _clip_frames(moving=False, brightness=True), SyntheticPrediction("lit", "no")),
        ClipSyntheticCase("brightness_moving", _clip_frames(moving=True, brightness=True), SyntheticPrediction("lit", "yes")),
    )


def boundary_synthetic_cases() -> tuple[BoundarySyntheticCase, ...]:
    continuous = _clip_frames(moving=True)
    same_frames = (continuous[1], continuous[3], continuous[5], continuous[7], continuous[8], continuous[9], continuous[10], continuous[11])
    first = _clip_frames(moving=False)
    second = tuple(_oval(_base(), (500, 100)) for _ in range(4))
    return (
        BoundarySyntheticCase("continuous_move", same_frames, "same_event"),
        BoundarySyntheticCase("position_jump", (first[0], first[3], first[6], first[9], *second), "different_event"),
    )


def parse_synthetic_prediction(raw: str) -> SyntheticPrediction:
    payload = json.loads(raw)
    if not isinstance(payload, dict) or set(payload) != {"background", "position_change"}:
        raise ValueError("synthetic_keys")
    if payload["background"] not in {"dark", "lit"}:
        raise ValueError("synthetic_background")
    if payload["position_change"] not in {"yes", "no", "uncertain"}:
        raise ValueError("synthetic_position")
    return SyntheticPrediction(payload["background"], payload["position_change"])


def purchase_verdict(statuses: Mapping[str, str]) -> str:
    if set(statuses) != set(MODELS) or any(value not in MODEL_STATUSES for value in statuses.values()):
        raise ValueError("model_statuses")
    small = MODELS[:3]
    if any(statuses[model] == "PASS" for model in small):
        return "MAC_STUDIO_NOT_REQUIRED_FOR_QUALITY"
    if any(statuses[model] in {"RESOURCE_FAIL", "TAG_UNAVAILABLE"} for model in MODELS):
        return "INCONCLUSIVE_NEEDS_COMPATIBLE_HARDWARE"
    if statuses[MODELS[-1]] == "PASS" and all(
        statuses[model] in {"QUALITY_FAIL", "SYNTHETIC_GATE_FAIL"} for model in small
    ):
        return "MAC_STUDIO_64GB_PURCHASE_EVIDENCE_PENDING_HOLDOUT"
    return "NO_MAC_STUDIO_PURCHASE_EVIDENCE"

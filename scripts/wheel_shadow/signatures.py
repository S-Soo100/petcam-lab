"""결정론 프레임 시그니처 — VLM 없이 OpenCV/numpy 로만 계산.

부동소수 요약은 round(...,6) 로 양자화해 결정론 SHA 를 안정화한다.
dHash 는 이산(bit) 표현 → 같은 프레임이면 hash 동일.
"""
from __future__ import annotations

import dataclasses

import cv2
import numpy as np


@dataclasses.dataclass(frozen=True, slots=True)
class RoiBox:
    """normalized [0,1] 좌표. 해상도 독립 → 프로파일 재사용 가능."""

    x: float
    y: float
    w: float
    h: float

    def pixel_box(self, width: int, height: int) -> tuple[int, int, int, int]:
        px = max(0, min(width - 1, int(round(self.x * width))))
        py = max(0, min(height - 1, int(round(self.y * height))))
        pw = max(1, int(round(self.w * width)))
        ph = max(1, int(round(self.h * height)))
        return px, py, min(pw, width - px), min(ph, height - py)


def crop_roi(frame: np.ndarray, roi: RoiBox) -> np.ndarray:
    h, w = frame.shape[:2]
    px, py, pw, ph = roi.pixel_box(w, h)
    return frame[py:py + ph, px:px + pw]


def ir_mode(frames: list[np.ndarray], sat_threshold: float = 20.0) -> str:
    """IR 야간 프레임은 거의 무채색 → HSV saturation 평균으로 판정."""
    sats = []
    for f in frames:
        hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
        sats.append(float(hsv[:, :, 1].mean()))
    return "ir" if (sum(sats) / len(sats)) < sat_threshold else "day"


def roi_motion_series(roi_frames: list[np.ndarray]) -> tuple[float, ...]:
    """연속 ROI grayscale absdiff 평균 (0~1 정규화)."""
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in roi_frames]
    series: list[float] = []
    for a, b in zip(grays, grays[1:]):
        if a.shape != b.shape:
            b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
        d = np.abs(a.astype(np.int16) - b.astype(np.int16)).mean() / 255.0
        series.append(round(float(d), 6))
    return tuple(series)


def motion_summary(series: tuple[float, ...]) -> tuple[float, float, float]:
    """(mean, peak, periodicity). periodicity = 최대 lag autocorr (0~1)."""
    if not series:
        return (0.0, 0.0, 0.0)
    arr = np.asarray(series, dtype=np.float64)
    mean = round(float(arr.mean()), 6)
    peak = round(float(arr.max()), 6)
    return (mean, peak, _peak_autocorr(arr))


def _peak_autocorr(arr: np.ndarray) -> float:
    if len(arr) < 4:
        return 0.0
    a = arr - arr.mean()
    denom = float((a * a).sum())
    if denom == 0.0:
        return 0.0
    best = 0.0
    for lag in range(1, len(a) // 2 + 1):
        c = float((a[:-lag] * a[lag:]).sum()) / denom
        best = max(best, c)
    return round(best, 6)


def dhash(gray_roi: np.ndarray, hash_size: int = 8) -> int:
    """difference hash — resize 후 인접 픽셀 대소 비교로 64bit."""
    small = cv2.resize(gray_roi, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]
    bits = 0
    for v in diff.flatten():
        bits = (bits << 1) | int(bool(v))
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


@dataclasses.dataclass(frozen=True, slots=True)
class ClipSignature:
    clip_id: str
    started_at: str
    duration_sec: float
    mode: str                 # 'ir' | 'day'
    roi_motion_mean: float
    roi_motion_peak: float
    roi_periodicity: float
    perceptual_hash: int
    evidence_quality: str     # 'ok' | 'degraded' | 'missing'
    evidence_score: float     # 대표 랭킹용 (높을수록 좋음)
    novelty: bool
    frames_used: int

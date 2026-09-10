"""F8 head_micro — "몸은 멈췄는데 머리 끝만 움직인다" 를 bbox 만으로 근사하는 채널 (TEST-SHEET §4 F8).

아이디어: 게코는 머리부터 이동하므로 직전 이동 벡터의 앞쪽 끝이 머리다. 그 끝 30% 영역의 프레임 간
절대차에서 몸통 영역의 절대차를 빼고, 배경 노이즈(절대차)로 나눈다. keypoint 모델 없이 되는 값싼 탐침.

프레임 선택은 gate `AnalysisClock` 과 같은 절대시간 10fps grid 를 재현한다 (track_points 의 timestamp 와
정확히 같은 프레임을 봐야 bbox 를 붙일 수 있기 때문). gate 패키지를 import 하지 않는 이유: 이 모듈은
petcam-lab venv(cv2·numpy)에서 돌고, gate venv 는 러너에만 필요하다.
"""
from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

HEAD_FRACTION = 0.3
MIN_DIRECTION_BODY_FRACTION = 0.1
BACKGROUND_MARGIN = 0.2
EPS_GRAY = 1.0
ANALYSIS_FPS = 10.0

Direction = tuple[float, float] | None
BoxPx = tuple[int, int, int, int]


def analysis_grid_indices(source_fps: float, n_frames: int, max_fps: float = ANALYSIS_FPS) -> list[int]:
    """gate AnalysisClock.accept 와 동일: 절대시간 deadline grid 에서 처음 도달한 프레임만 채택."""
    if not math.isfinite(source_fps) or source_fps <= 0:
        raise ValueError("source_fps must be finite and positive")
    accepted: list[int] = []
    next_deadline_number = 0
    for frame_index in range(n_frames):
        timestamp = frame_index / source_fps
        deadline = next_deadline_number / max_fps
        if timestamp + 1e-12 < deadline:
            continue
        next_deadline_number += 1
        accepted.append(frame_index)
    return accepted


def _center(b: Sequence[float]) -> tuple[float, float]:
    x, y, w, h = b
    return x + w / 2.0, y + h / 2.0


def head_end_direction(points: list[dict], interval_start: float, lookback_sec: float = 5.0) -> Direction:
    """interval_start 직전 lookback 창 안의 순변위 단위벡터. 변위가 체장의 10% 미만이면 None(방향 불명)."""
    window = sorted(
        (p for p in points if interval_start - lookback_sec - 1e-9 <= p["timestamp_sec"] <= interval_start + 1e-9),
        key=lambda p: p["timestamp_sec"],
    )
    if len(window) < 2:
        return None
    first, last = window[0], window[-1]
    (x0, y0), (x1, y1) = _center(first["bbox_norm"]), _center(last["bbox_norm"])
    dx, dy = x1 - x0, y1 - y0
    norm = math.hypot(dx, dy)
    body = (math.hypot(*first["bbox_norm"][2:]) + math.hypot(*last["bbox_norm"][2:])) / 2.0
    if body <= 0 or norm < MIN_DIRECTION_BODY_FRACTION * body:
        return None
    return dx / norm, dy / norm


def split_head_body(box: BoxPx, direction: tuple[float, float]) -> tuple[BoxPx, BoxPx]:
    """direction 의 지배 축 앞쪽 30% = 머리, 나머지 70% = 몸통 (px xywh)."""
    x, y, w, h = box
    dx, dy = direction
    if abs(dx) >= abs(dy):
        hw = int(round(w * HEAD_FRACTION))
        if dx >= 0:
            return (x + w - hw, y, hw, h), (x, y, w - hw, h)
        return (x, y, hw, h), (x + hw, y, w - hw, h)
    hh = int(round(h * HEAD_FRACTION))
    if dy >= 0:
        return (x, y + h - hh, w, hh), (x, y, w, h - hh)
    return (x, y, w, hh), (x, y + hh, w, h - hh)


def _mean_in(diff: np.ndarray, box: BoxPx) -> float:
    x, y, w, h = box
    if w <= 0 or h <= 0:
        return math.nan
    region = diff[max(0, y):y + h, max(0, x):x + w]
    return float(region.mean()) if region.size else math.nan


def _background_mean(diff: np.ndarray, box: BoxPx) -> float:
    x, y, w, h = box
    mx, my = int(round(w * BACKGROUND_MARGIN)), int(round(h * BACKGROUND_MARGIN))
    mask = np.ones(diff.shape, dtype=bool)
    mask[max(0, y - my):y + h + my, max(0, x - mx):x + w + mx] = False
    return float(diff[mask].mean()) if mask.any() else math.nan


def _candidates(box: BoxPx, direction: Direction) -> list[tuple[float, float]]:
    if direction is not None:
        return [direction]
    _, _, w, h = box
    return [(1.0, 0.0), (-1.0, 0.0)] if w >= h else [(0.0, 1.0), (0.0, -1.0)]


def head_micro_ratio(frames: Sequence[np.ndarray], boxes: Sequence[BoxPx], direction: Direction) -> float:
    """연속 프레임 쌍마다 (머리 절대차 − 몸통 절대차) / max(배경 절대차, 1) 을 구해 중앙값. 방향 불명이면 양끝 max."""
    if len(frames) < 2 or len(frames) != len(boxes):
        return math.nan
    best = -math.inf
    for cand in _candidates(boxes[0], direction):
        ratios: list[float] = []
        for i in range(1, len(frames)):
            prev = frames[i - 1].astype(np.float32)
            cur = frames[i].astype(np.float32)
            if prev.ndim == 3:
                prev = prev.mean(axis=2)
            if cur.ndim == 3:
                cur = cur.mean(axis=2)
            diff = np.abs(cur - prev)
            head, body = split_head_body(boxes[i], cand)
            hd, bd, bg = _mean_in(diff, head), _mean_in(diff, body), _background_mean(diff, boxes[i])
            if math.isnan(hd) or math.isnan(bd) or math.isnan(bg):
                continue
            ratios.append((hd - bd) / max(bg, EPS_GRAY))
        if ratios:
            best = max(best, float(np.median(ratios)))
    return best if best > -math.inf else math.nan


def compute_head_micro_for_clip(
    video_path: str | Path,
    track_points: list[dict],
    interval: tuple[float, float],
    *,
    frame_reader=None,
) -> float:
    """가장 긴 정지 구간(interval)에서 F8 을 계산. frame_reader 는 테스트 주입용 (기본 cv2)."""
    start, end = interval
    if not (math.isfinite(start) and math.isfinite(end)) or end - start < 3.0:
        return math.nan
    in_interval = [p for p in track_points if start - 1e-9 <= p["timestamp_sec"] <= end + 1e-9]
    if not in_interval:
        return math.nan
    track_id = Counter(p["track_id"] for p in in_interval).most_common(1)[0][0]
    track_all = [p for p in track_points if p["track_id"] == track_id]
    by_ts = {round(p["timestamp_sec"], 6): p["bbox_norm"] for p in track_all if start - 1e-9 <= p["timestamp_sec"] <= end + 1e-9}
    direction = head_end_direction(track_all, interval_start=start)

    reader = frame_reader or _cv2_frames
    frames: list[np.ndarray] = []
    boxes: list[BoxPx] = []
    for timestamp, gray in reader(video_path):
        if timestamp + 1e-9 < start:
            continue
        if timestamp - 1e-9 > end:
            break
        b = by_ts.get(round(timestamp, 6))
        if b is None:
            continue
        fh, fw = gray.shape[:2]
        x, y, w, h = b
        boxes.append((int(round(x * fw)), int(round(y * fh)), max(1, int(round(w * fw))), max(1, int(round(h * fh)))))
        frames.append(gray)
    return head_micro_ratio(frames, boxes, direction)


def _cv2_frames(video_path: str | Path) -> Iterable[tuple[float, np.ndarray]]:
    """10fps 절대 grid 의 프레임만 (timestamp, gray) 로 yield. cap 은 finally 로 반드시 release (donts/python #7)."""
    import cv2  # 지연 import: 테스트는 주입 reader 를 써서 cv2 가 없어도 된다

    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            return
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        if not math.isfinite(fps) or fps <= 0:
            return
        next_deadline_number = 0
        frame_index = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            timestamp = frame_index / fps
            frame_index += 1
            if timestamp + 1e-12 < next_deadline_number / ANALYSIS_FPS:
                continue
            next_deadline_number += 1
            yield timestamp, cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    finally:
        cap.release()

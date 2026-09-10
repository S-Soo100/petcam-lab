"""F8 head_micro — 몸은 멈췄는데 머리 끝만 움직이는지 (TEST-SHEET §4 F8).

합성 프레임(numpy)만 사용. 실제 영상·detector 없음.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from scripts.nonvlm_behavior_v0.head_micro import (
    analysis_grid_indices,
    head_end_direction,
    head_micro_ratio,
    split_head_body,
)


def test_analysis_grid_matches_gate_absolute_10fps_deadline_grid():
    # gate tests/test_gme_temporal.py 와 동일 기대값 (25fps 원본 → 10fps 절대 grid)
    assert analysis_grid_indices(25.0, 26) == [0, 3, 5, 8, 10, 13, 15, 18, 20, 23, 25]


def test_analysis_grid_keeps_every_frame_when_source_is_slower_than_10fps():
    assert analysis_grid_indices(7.0, 5) == [0, 1, 2, 3, 4]


def _pt(t, x, y, w=0.2, h=0.1, track="a"):
    return {"track_id": track, "timestamp_sec": t, "bbox_norm": [x, y, w, h], "confidence": 0.9, "provenance": "observed"}


# ── 방향 ──────────────────────────────────────────────────────────────

def test_direction_is_unit_vector_of_net_displacement_before_interval():
    pts = [_pt(0.0, 0.10, 0.5), _pt(1.0, 0.20, 0.5), _pt(2.0, 0.40, 0.5)]  # 오른쪽으로 이동
    d = head_end_direction(pts, interval_start=2.0, lookback_sec=5.0)
    assert d == pytest.approx((1.0, 0.0))


def test_direction_is_none_when_displacement_below_body_length_fraction():
    pts = [_pt(0.0, 0.100, 0.5), _pt(1.0, 0.101, 0.5), _pt(2.0, 0.102, 0.5)]  # 0.002 이동 ≪ 체장 0.22
    assert head_end_direction(pts, interval_start=2.0, lookback_sec=5.0) is None


def test_direction_ignores_points_after_interval_start_and_outside_lookback():
    pts = [_pt(0.0, 0.90, 0.5), _pt(10.0, 0.10, 0.5), _pt(12.0, 0.30, 0.5), _pt(13.0, 0.05, 0.5)]
    # lookback 5s 안의 포인트는 t=10,12 뿐(→ 오른쪽). t=13 은 interval 이후라 무시.
    d = head_end_direction(pts, interval_start=12.0, lookback_sec=5.0)
    assert d == pytest.approx((1.0, 0.0))


# ── 머리/몸통 분할 ───────────────────────────────────────────────────

def test_split_uses_leading_30_percent_along_dominant_axis():
    head, body = split_head_body((100, 50, 200, 40), direction=(1.0, 0.0))  # px xywh, 오른쪽이 머리
    assert head == (240, 50, 60, 40)
    assert body == (100, 50, 140, 40)
    head, body = split_head_body((100, 50, 200, 40), direction=(-1.0, 0.0))
    assert head == (100, 50, 60, 40)
    assert body == (160, 50, 140, 40)


def test_split_vertical_direction_uses_top_or_bottom():
    head, body = split_head_body((10, 100, 40, 200), direction=(0.0, -1.0))  # 위로 이동 → 위쪽이 머리
    assert head == (10, 100, 40, 60)
    assert body == (10, 160, 40, 140)


# ── 비율 ──────────────────────────────────────────────────────────────

def _frames_with_moving_head(n=6, size=(120, 200), bbox=(40, 40, 100, 40), head_side="right", noise=0.0, seed=0):
    """몸통은 고정 텍스처, 머리 끝 30% 만 프레임마다 밝기가 뒤집힘. 배경은 상수(+noise)."""
    rng = np.random.default_rng(seed)
    frames = []
    x, y, w, h = bbox
    for i in range(n):
        f = np.full(size, 100, dtype=np.uint8)
        if noise:
            f = np.clip(f + rng.normal(0, noise, size), 0, 255).astype(np.uint8)
        f[y:y + h, x:x + w] = 60  # 몸통
        hw = int(round(w * 0.3))
        hx = x + w - hw if head_side == "right" else x
        f[y:y + h, hx:hx + hw] = 200 if i % 2 == 0 else 20  # 머리 끝 깜빡임
        frames.append(f)
    return frames


def test_ratio_is_high_when_only_head_end_changes():
    frames = _frames_with_moving_head()
    boxes = [(40, 40, 100, 40)] * len(frames)
    r = head_micro_ratio(frames, boxes, direction=(1.0, 0.0))
    assert r > 2.0


def test_ratio_is_near_zero_when_whole_body_static():
    frames = [np.full((120, 200), 100, dtype=np.uint8) for _ in range(6)]
    for f in frames:
        f[40:80, 40:140] = 60
    boxes = [(40, 40, 100, 40)] * len(frames)
    r = head_micro_ratio(frames, boxes, direction=(1.0, 0.0))
    assert r == pytest.approx(0.0, abs=1e-6)


def test_ratio_without_direction_takes_max_over_both_ends():
    frames = _frames_with_moving_head(head_side="left")
    boxes = [(40, 40, 100, 40)] * len(frames)
    r_none = head_micro_ratio(frames, boxes, direction=None)
    r_wrong = head_micro_ratio(frames, boxes, direction=(1.0, 0.0))
    assert r_none > 2.0
    assert r_none > r_wrong


def test_ratio_is_nan_with_fewer_than_two_frames():
    frames = _frames_with_moving_head(n=1)
    assert math.isnan(head_micro_ratio(frames, [(40, 40, 100, 40)], direction=(1.0, 0.0)))


def test_clip_level_uses_majority_track_in_interval_and_joins_frames_by_grid_timestamp():
    from scripts.nonvlm_behavior_v0.head_micro import compute_head_micro_for_clip

    # track "a" 가 [10, 20] 정지 구간의 다수 track, 머리는 왼쪽(직전 이동이 왼쪽으로). 프레임 10fps grid.
    frames = _frames_with_moving_head(n=101, head_side="left")
    fw, fh = 200, 120
    box_px = (40, 40, 100, 40)
    bbox_norm = [box_px[0] / fw, box_px[1] / fh, box_px[2] / fw, box_px[3] / fh]
    pts = [{"track_id": "a", "timestamp_sec": round(10 + i / 10, 6), "bbox_norm": bbox_norm, "confidence": 0.9, "provenance": "observed"} for i in range(101)]
    pts += [{"track_id": "a", "timestamp_sec": 6.0, "bbox_norm": [0.6, 0.33, 0.5, 0.33], "confidence": 0.9, "provenance": "observed"}]  # 직전 이동 (오른쪽→왼쪽)
    pts += [{"track_id": "b", "timestamp_sec": 12.0, "bbox_norm": [0.1, 0.1, 0.1, 0.1], "confidence": 0.5, "provenance": "tracked"}]

    def reader(_path):
        for i, f in enumerate(frames):
            yield round(10 + i / 10, 6), f

    r = compute_head_micro_for_clip("unused.mp4", pts, (10.0, 20.0), frame_reader=reader)
    assert r > 2.0


def test_clip_level_returns_nan_for_short_interval_or_no_points():
    from scripts.nonvlm_behavior_v0.head_micro import compute_head_micro_for_clip

    assert math.isnan(compute_head_micro_for_clip("x", [], (10.0, 12.9), frame_reader=lambda p: iter(())))
    assert math.isnan(compute_head_micro_for_clip("x", [], (10.0, 20.0), frame_reader=lambda p: iter(())))


def test_ratio_is_normalized_by_background_noise():
    quiet = head_micro_ratio(_frames_with_moving_head(noise=0.0), [(40, 40, 100, 40)] * 6, direction=(1.0, 0.0))
    noisy = head_micro_ratio(_frames_with_moving_head(noise=20.0), [(40, 40, 100, 40)] * 6, direction=(1.0, 0.0))
    assert noisy < quiet

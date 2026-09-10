"""nonvlm-behavior-v0 특징 추출 (TEST-SHEET §4 F1~F7, F9~F11) — 합성 artifact로 검증.

artifact = 연구 러너가 쓰는 확장 JSON:
  {"gme": {intervals, track_points, duration_sec, ...}, "summary": {...}}
GT는 절대 읽지 않는다.
"""
from __future__ import annotations

import math

import pytest

from scripts.nonvlm_behavior_v0.features import compute_features


def _pt(track, t, x, y, w, h, conf=0.9, prov="observed"):
    return {"track_id": track, "timestamp_sec": t, "bbox_norm": [x, y, w, h], "confidence": conf, "provenance": prov}


def _iv(s, e, state, tracks=()):
    return {"start_sec": s, "end_sec": e, "state": state, "track_ids": list(tracks)}


def _artifact(intervals, points, *, duration=60.0, moving=0.0, visible=0.0, unknown=0.0, cam=0.0, geckos=1):
    return {
        "gme": {"duration_sec": duration, "intervals": intervals, "track_points": points},
        "summary": {
            "status": "ok", "duration_sec": duration, "candidate_moving_sec_any_gecko": moving,
            "visible_sec": visible, "unknown_sec": unknown, "camera_motion_sec": cam,
            "max_simultaneous_geckos": geckos,
        },
    }


def test_moving_ratio_is_moving_over_visible():
    a = _artifact([_iv(0, 10, "moving", ("t1",)), _iv(10, 40, "static", ("t1",))], [], moving=10, visible=40)
    f = compute_features(a)
    assert f["moving_ratio"] == pytest.approx(0.25)


def test_moving_ratio_is_nan_when_nothing_visible():
    a = _artifact([_iv(0, 60, "not_visible")], [], moving=0, visible=0)
    assert math.isnan(compute_features(a)["moving_ratio"])


def test_longest_static_merges_adjacent_static_intervals():
    ivs = [_iv(0, 5, "static", ("t1",)), _iv(5, 12, "static", ("t1",)), _iv(12, 20, "moving", ("t1",)), _iv(20, 23, "static", ("t1",))]
    f = compute_features(_artifact(ivs, [], visible=23, moving=8))
    assert f["longest_static_sec"] == pytest.approx(12.0)
    assert f["longest_moving_sec"] == pytest.approx(8.0)


def test_moving_bouts_count_merged_runs():
    ivs = [_iv(0, 2, "moving"), _iv(2, 3, "moving"), _iv(3, 10, "static"), _iv(10, 11, "moving"), _iv(11, 30, "static")]
    assert compute_features(_artifact(ivs, [], visible=30, moving=3))["n_moving_bouts"] == 2


def test_displacement_is_body_length_normalized_per_track():
    # 체장(대각) 0.1 짜리 bbox 가 0.05 이동 → 0.5 체장. 다른 track 은 이동 0.
    pts = [
        _pt("a", 0.0, 0.10, 0.10, 0.06, 0.08), _pt("a", 0.1, 0.15, 0.10, 0.06, 0.08),
        _pt("b", 0.0, 0.50, 0.50, 0.06, 0.08), _pt("b", 0.1, 0.50, 0.50, 0.06, 0.08),
    ]
    f = compute_features(_artifact([_iv(0, 1, "moving", ("a", "b"))], pts, visible=1, moving=1, geckos=2))
    assert f["disp_max"] == pytest.approx(0.5)
    assert f["disp_mean"] == pytest.approx(0.25)
    assert f["max_geckos"] == 2


def test_aspect_oscillation_uses_only_points_inside_static_intervals():
    pts = [
        _pt("a", 0.0, 0.1, 0.1, 0.10, 0.10),   # static 구간: w/h = 1.0
        _pt("a", 0.1, 0.1, 0.1, 0.20, 0.10),   # static 구간: w/h = 2.0
        _pt("a", 5.0, 0.1, 0.1, 0.90, 0.10),   # moving 구간: 무시돼야 함
    ]
    ivs = [_iv(0, 1, "static", ("a",)), _iv(4, 6, "moving", ("a",))]
    f = compute_features(_artifact(ivs, pts, visible=3, moving=2))
    assert f["aspect_osc"] == pytest.approx(0.5)  # std([1.0, 2.0]) population


def test_global_change_frames_and_first_time():
    ivs = [_iv(0, 3, "static", ("a",)), _iv(3, 3.5, "camera_motion"), _iv(3.5, 10, "static", ("a",))]
    f = compute_features(_artifact(ivs, [], visible=9.5, cam=0.5))
    assert f["global_change_frames"] == 5
    assert f["first_global_change_sec"] == pytest.approx(3.0)


def test_no_global_change_gives_zero_frames_and_nan_time():
    f = compute_features(_artifact([_iv(0, 10, "static", ("a",))], [], visible=10))
    assert f["global_change_frames"] == 0
    assert math.isnan(f["first_global_change_sec"])


def test_visibility_ratios():
    ivs = [_iv(0, 30, "not_visible"), _iv(30, 45, "unknown"), _iv(45, 60, "static", ("a",))]
    f = compute_features(_artifact(ivs, [], duration=60, visible=15, unknown=15))
    assert f["not_visible_ratio"] == pytest.approx(0.5)
    assert f["unknown_ratio"] == pytest.approx(0.25)


def test_bbox_area_jump_is_max_ratio_between_consecutive_points_of_same_track():
    pts = [_pt("a", 0.0, 0.1, 0.1, 0.10, 0.10), _pt("a", 0.1, 0.1, 0.1, 0.20, 0.15), _pt("a", 0.2, 0.1, 0.1, 0.10, 0.10)]
    f = compute_features(_artifact([_iv(0, 1, "static", ("a",))], pts, visible=1))
    assert f["bbox_area_jump"] == pytest.approx(3.0)


def test_feature_keys_are_complete_and_head_micro_left_for_frame_stage():
    f = compute_features(_artifact([_iv(0, 10, "static", ("a",))], [], visible=10))
    expected = {
        "moving_ratio", "longest_static_sec", "longest_moving_sec", "n_moving_bouts", "disp_mean", "disp_max",
        "aspect_osc", "global_change_frames", "first_global_change_sec", "unknown_ratio", "not_visible_ratio",
        "max_geckos", "bbox_area_jump", "longest_static_start_sec", "longest_static_end_sec",
    }
    assert expected <= set(f)
    assert "head_micro" not in f

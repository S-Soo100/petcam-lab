"""nonvlm-behavior-v0 룰 v0 (TEST-SHEET §5-1) — 임계값은 시험지에서 사전 고정, 여기서 그대로 검증."""
from __future__ import annotations

import math

from scripts.nonvlm_behavior_v0.rules import RULE_VERSION, rule_v0


def _f(**over):
    base = {
        "moving_ratio": 0.9, "longest_static_sec": 1.0, "longest_moving_sec": 5.0, "n_moving_bouts": 1,
        "disp_mean": 0.3, "disp_max": 1.0, "aspect_osc": 0.05, "global_change_frames": 0,
        "first_global_change_sec": math.nan, "unknown_ratio": 0.0, "not_visible_ratio": 0.0,
        "max_geckos": 1, "bbox_area_jump": 1.2, "head_micro": math.nan,
    }
    base.update(over)
    return base


def test_rule_version_is_pinned():
    assert RULE_VERSION == "nonvlm-rule-v0"


def test_default_is_moving():
    assert rule_v0(_f()) == "moving"


def test_r1_hand_feeding_needs_global_change_and_area_jump():
    assert rule_v0(_f(global_change_frames=5, bbox_area_jump=2.0)) == "hand_feeding"
    assert rule_v0(_f(global_change_frames=4, bbox_area_jump=2.0)) == "moving"
    assert rule_v0(_f(global_change_frames=5, bbox_area_jump=1.9)) == "moving"


def test_r2_feeding_needs_long_static_and_head_micro():
    assert rule_v0(_f(longest_static_sec=8.0, head_micro=2.0)) == "feeding"
    assert rule_v0(_f(longest_static_sec=7.9, head_micro=2.0)) == "moving"
    assert rule_v0(_f(longest_static_sec=8.0, head_micro=1.9)) == "moving"


def test_r2_treats_missing_head_micro_as_no_evidence():
    assert rule_v0(_f(longest_static_sec=20.0, head_micro=math.nan)) == "moving"


def test_r3_shedding_needs_aspect_osc_bouts_and_low_moving_ratio():
    assert rule_v0(_f(aspect_osc=0.25, n_moving_bouts=4, moving_ratio=0.5)) == "shedding"
    assert rule_v0(_f(aspect_osc=0.24, n_moving_bouts=4, moving_ratio=0.5)) == "moving"
    assert rule_v0(_f(aspect_osc=0.25, n_moving_bouts=3, moving_ratio=0.5)) == "moving"
    assert rule_v0(_f(aspect_osc=0.25, n_moving_bouts=4, moving_ratio=0.51)) == "moving"


def test_r4_unseen_when_mostly_unknown_or_not_visible():
    # v1 엔진은 미검출을 unknown 으로 내므로(not_visible 미사용) 두 비율의 합으로 판정한다.
    assert rule_v0(_f(not_visible_ratio=0.9)) == "unseen"
    assert rule_v0(_f(unknown_ratio=0.9)) == "unseen"
    assert rule_v0(_f(unknown_ratio=0.5, not_visible_ratio=0.4)) == "unseen"
    assert rule_v0(_f(unknown_ratio=0.5, not_visible_ratio=0.39)) == "moving"


def test_rule_order_first_match_wins():
    # R1 이 R2 보다 먼저: 둘 다 만족하면 hand_feeding
    f = _f(global_change_frames=9, bbox_area_jump=3.0, longest_static_sec=10.0, head_micro=3.0)
    assert rule_v0(f) == "hand_feeding"
    # R2 가 R3 보다 먼저
    f = _f(longest_static_sec=10.0, head_micro=3.0, aspect_osc=0.3, n_moving_bouts=5, moving_ratio=0.2)
    assert rule_v0(f) == "feeding"

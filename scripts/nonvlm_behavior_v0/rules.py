"""룰 v0 — 시험지 §5-1. 임계값은 pre-reg 로 고정됐고 결과 확인 후 변경 금지 (변경은 v1 시험지).

순서대로 첫 매치. NaN 특징은 그 룰의 증거 없음으로 취급한다 (float 비교가 NaN 에 항상 False 인 성질을 그대로 씀).
"""
from __future__ import annotations

RULE_VERSION = "nonvlm-rule-v0"

# 시험지 §5-1 임계값 (사후 변경 금지)
R1_GLOBAL_CHANGE_FRAMES = 5
R1_AREA_JUMP = 2.0
R2_STATIC_SEC = 8.0
R2_HEAD_MICRO = 2.0
R3_ASPECT_OSC = 0.25
R3_MOVING_BOUTS = 4
R3_MOVING_RATIO_MAX = 0.5
R4_UNSEEN_RATIO = 0.9  # unknown + not_visible 합산 (v1 엔진은 미검출을 unknown 으로 냄 — 실행 전 정정)


def rule_v0(f: dict) -> str:
    if f["global_change_frames"] >= R1_GLOBAL_CHANGE_FRAMES and f["bbox_area_jump"] >= R1_AREA_JUMP:
        return "hand_feeding"
    if f["longest_static_sec"] >= R2_STATIC_SEC and f["head_micro"] >= R2_HEAD_MICRO:
        return "feeding"
    if (
        f["aspect_osc"] >= R3_ASPECT_OSC
        and f["n_moving_bouts"] >= R3_MOVING_BOUTS
        and f["moving_ratio"] <= R3_MOVING_RATIO_MAX
    ):
        return "shedding"
    if (f["unknown_ratio"] + f["not_visible_ratio"]) >= R4_UNSEEN_RATIO:
        return "unseen"
    return "moving"

"""채점기 — TEST-SHEET §6 지표 · §7 게이트 · §5-3 결합 룰. 합성 예측/GT 로 검증."""
from __future__ import annotations

import math

import pytest

from scripts.nonvlm_behavior_v0.scorer import (
    FEEDING,
    class_recall,
    complementarity,
    evaluate,
    feeding_false_positives,
    feeding_recall,
    fuse_c,
    merge_feeding,
    paired_boundary,
)


def test_merge_feeding_maps_drinking_and_paste_only():
    assert merge_feeding("drinking") == "feeding"
    assert merge_feeding("eating_paste") == "feeding"
    assert merge_feeding("moving") == "moving"
    assert FEEDING == {"drinking", "eating_paste"}


def test_class_recall_counts_hits_over_gt_of_that_class():
    gt = {"a": "moving", "b": "moving", "c": "drinking"}
    pred = {"a": "moving", "b": "hand_feeding", "c": "moving"}
    hit, total = class_recall(pred, gt, "moving")
    assert (hit, total) == (1, 2)


def test_feeding_recall_treats_feeding_bundle_as_hit():
    gt = {"a": "drinking", "b": "eating_paste", "c": "drinking", "d": "moving"}
    pred_b = {"a": "feeding", "b": "feeding", "c": "moving", "d": "moving"}   # B 는 묶음 라벨
    pred_a = {"a": "eating_paste", "b": "moving", "c": "drinking", "d": "moving"}  # A 는 7-class
    assert feeding_recall(pred_b, gt) == (2, 3)
    assert feeding_recall(pred_a, gt) == (2, 3)


def test_feeding_false_positives_count_non_feeding_gt_predicted_feeding():
    gt = {"a": "moving", "b": "shedding", "c": "drinking"}
    pred = {"a": "feeding", "b": "drinking", "c": "feeding"}
    assert feeding_false_positives(pred, gt) == (2, 2)


def test_complementarity_four_cells_on_boundary_correctness():
    gt = {"a": "drinking", "b": "moving", "c": "moving", "d": "shedding"}
    a = {"a": "eating_paste", "b": "moving", "c": "drinking", "d": "moving"}   # a✓ b✓ c✗ d✗
    b = {"a": "moving", "b": "moving", "c": "moving", "d": "moving"}          # a✗ b✓ c✓ d✗
    cells = complementarity(a, b, gt)
    assert cells == {"both": 1, "a_only": 1, "b_only": 1, "neither": 1}


def _feat(**over):
    base = {"longest_static_sec": 1.0, "head_micro": math.nan, "global_change_frames": 0, "bbox_area_jump": 1.0}
    base.update(over)
    return base


def test_fuse_c1_demotes_feeding_without_stationarity():
    assert fuse_c("drinking", _feat(longest_static_sec=2.9)) == "moving"
    assert fuse_c("drinking", _feat(longest_static_sec=3.0)) == "drinking"


def test_fuse_c2_promotes_moving_to_feeding_when_r2_matches():
    assert fuse_c("moving", _feat(longest_static_sec=8.0, head_micro=2.0)) == "feeding"
    assert fuse_c("moving", _feat(longest_static_sec=8.0, head_micro=1.9)) == "moving"


def test_fuse_c3_sets_hand_feeding_when_r1_matches():
    assert fuse_c("moving", _feat(global_change_frames=5, bbox_area_jump=2.0)) == "hand_feeding"
    assert fuse_c("shedding", _feat(global_change_frames=5, bbox_area_jump=2.0)) == "hand_feeding"


def test_fuse_keeps_a_otherwise():
    assert fuse_c("shedding", _feat()) == "shedding"
    assert fuse_c("eating_prey", _feat(longest_static_sec=10.0)) == "eating_prey"


def test_paired_boundary_recovered_broken_harmless():
    gt = {"a": "drinking", "b": "moving", "c": "drinking", "d": "eating_paste"}
    a = {"a": "moving", "b": "moving", "c": "drinking", "d": "drinking"}
    c = {"a": "feeding", "b": "drinking", "c": "drinking", "d": "eating_paste"}
    rec, brk, harmless = paired_boundary(a, c, gt)
    assert [x[0] for x in rec] == ["a"]       # A 오답 → C 정답
    assert [x[0] for x in brk] == ["b"]       # A 정답 → C 오답 (moving→drinking 과탐)
    assert [x[0] for x in harmless] == ["d"]  # 급여 내부 이동


def test_evaluate_applies_gates_from_test_sheet():
    gt = {f"m{i}": "moving" for i in range(10)}
    gt.update({f"h{i}": "hand_feeding" for i in range(5)})
    gt.update({"f1": "drinking", "f2": "eating_paste", "f3": "drinking"})
    a = {k: v for k, v in gt.items()}          # A 는 전부 정답
    b = {k: ("feeding" if v in FEEDING else v) for k, v in gt.items()}  # B 도 전부 정답(묶음)
    # 급여 클립은 정지 구간이 있어 C1 강등이 걸리지 않게 (결합 룰 검증은 별도 테스트)
    feats = {k: _feat(longest_static_sec=10.0 if v in FEEDING else 1.0) for k, v in gt.items()}
    res = evaluate(gt, a, b, feats)
    assert res["gates"]["G_B1_moving_recall"] is True
    assert res["gates"]["G_B2_hand_feeding_recall"] is True
    assert res["gates"]["G_B3_feeding_recall_vs_A"] is True
    assert res["gates"]["G_B4_feeding_fp"] is True
    assert res["gates"]["G_C"] is True
    assert res["decision_B"] == "adopt"


def test_evaluate_lists_boundary_disagreements_for_discordant_review():
    gt = {"a": "drinking", "b": "moving", "c": "moving", "d": "shedding"}
    a = {"a": "eating_paste", "b": "moving", "c": "drinking", "d": "moving"}
    b = {"a": "moving", "b": "moving", "c": "moving", "d": "moving"}
    res = evaluate(gt, a, b, {k: _feat(longest_static_sec=10.0) for k in gt})
    dis = res["disagreements"]
    # 급여경계 기준으로 A·B 정오가 갈리는 클립만: a(A✓B✗), c(A✗B✓). b 는 둘 다 정답, d 는 둘 다 오답(같은 라벨)
    assert [x["key"] for x in dis] == ["a", "c"]
    assert dis[0] == {"key": "a", "gt": "drinking", "A": "eating_paste", "B": "moving", "A_ok": True, "B_ok": False}


def test_evaluate_holds_when_feeding_recall_falls_more_than_10pp_below_A():
    gt = {f"m{i}": "moving" for i in range(10)}
    gt.update({f"h{i}": "hand_feeding" for i in range(5)})
    gt.update({f"f{i}": "drinking" for i in range(10)})
    a = dict(gt)
    b = {k: v for k, v in gt.items() if v != "drinking"}
    b.update({f"f{i}": ("feeding" if i < 8 else "moving") for i in range(10)})  # B 급여 80% vs A 100%
    res = evaluate(gt, a, b, {k: _feat() for k in gt})
    assert res["gates"]["G_B3_feeding_recall_vs_A"] is False
    assert res["decision_B"] == "hold"


def test_evaluate_rejects_when_moving_recall_below_gate():
    gt = {f"m{i}": "moving" for i in range(10)}
    gt.update({f"h{i}": "hand_feeding" for i in range(5)})
    a = dict(gt)
    b = dict(gt)
    for i in range(2):
        b[f"m{i}"] = "shedding"  # moving recall 0.8 < 0.9
    res = evaluate(gt, a, b, {k: _feat() for k in gt})
    assert res["gates"]["G_B1_moving_recall"] is False
    assert res["decision_B"] == "reject"

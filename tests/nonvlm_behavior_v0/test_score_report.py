"""채점 리포트 CLI 의 순수 조립부 — GT/예측/특징 로드 + 결과 markdown."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from scripts.nonvlm_behavior_v0.score_report import (
    build_markdown,
    load_features,
    load_gt,
    load_rule_predictions,
    run_scoring,
)


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def test_load_gt_reads_manifest_filename_to_gt(tmp_path: Path):
    m = tmp_path / "manifest.csv"
    _write_csv(m, [{"filename": "a.mp4", "gt": "drinking", "source": "uploaded"}, {"filename": "b.mp4", "gt": "moving", "source": "eval-0617"}])
    gt, sources = load_gt(m)
    assert gt == {"a.mp4": "drinking", "b.mp4": "moving"}
    assert sources == {"a.mp4": "uploaded", "b.mp4": "eval-0617"}


def test_load_features_parses_numbers_and_empty_as_nan(tmp_path: Path):
    f = tmp_path / "features.csv"
    _write_csv(f, [{"filename": "a.mp4", "clip_id": "x", "source": "uploaded", "longest_static_sec": "8.5", "head_micro": "", "max_geckos": "1"}])
    feats = load_features(f)
    assert feats["a.mp4"]["longest_static_sec"] == 8.5
    assert math.isnan(feats["a.mp4"]["head_micro"])
    assert feats["a.mp4"]["max_geckos"] == 1.0
    assert feats["a.mp4"]["source"] == "uploaded"


def test_load_rule_predictions(tmp_path: Path):
    p = tmp_path / "pred.csv"
    _write_csv(p, [{"filename": "a.mp4", "label": "feeding", "rule_version": "nonvlm-rule-v0"}])
    assert load_rule_predictions(p) == {"a.mp4": "feeding"}


def test_run_scoring_restricts_paired_to_regression_set_and_measures_all(tmp_path: Path):
    gt = {"a.mp4": "moving", "b.mp4": "hand_feeding", "c.mp4": "drinking", "d.mp4": "moving"}
    sources = {"a.mp4": "uploaded", "b.mp4": "cam-motion", "c.mp4": "eval-0608", "d.mp4": "eval-0617"}
    v40 = {"a.mp4": "moving", "b.mp4": "hand_feeding", "c.mp4": "drinking"}      # d 는 v4.0 없음(paired 제외)
    rule = {"a.mp4": "moving", "b.mp4": "hand_feeding", "c.mp4": "feeding", "d.mp4": "moving"}
    feats = {k: {"longest_static_sec": 10.0, "head_micro": math.nan, "global_change_frames": 0, "bbox_area_jump": 1.0, "source": sources[k]} for k in gt}
    res = run_scoring(gt, sources, v40, rule, feats)
    assert res["paired"]["n"] == 3
    assert res["all197"]["n"] == 4
    assert res["paired"]["decision_B"] == "adopt"
    assert "classifier_cv" in res["paired"]
    assert set(res["paired"]["classifier_cv"]["predictions"]) == {"a.mp4", "b.mp4", "c.mp4"}


def test_build_markdown_mentions_gates_and_decision():
    res = {
        "paired": {
            "n": 3, "decision_B": "hold",
            "gates": {"G_B1_moving_recall": True, "G_B2_hand_feeding_recall": True, "G_B3_feeding_recall_vs_A": False, "G_B4_feeding_fp": True, "G_C": False},
            "moving_recall_B": (1, 1), "hand_feeding_recall_B": (1, 1), "feeding_recall_A": (1, 1), "feeding_recall_B": (0, 1), "feeding_fp_B": (0, 2),
            "boundary_acc": {"A": 1.0, "B": 0.67, "C": 1.0}, "raw6_acc_B": 0.67,
            "complementarity": {"both": 2, "a_only": 1, "b_only": 0, "neither": 0},
            "paired_A_to_C": {"recovered": [], "broken": [], "harmless": []},
            "per_class_A": {}, "per_class_B": {},
            "classifier_cv": {"accuracy_raw6": 0.67, "per_class_recall": {}},
        },
        "all197": {"n": 4, "raw6_acc_B": 0.75, "per_class_B": {}},
    }
    md = build_markdown(res)
    assert "G_B3_feeding_recall_vs_A" in md and "hold" in md
    assert "complementarity" in md.lower() or "상보" in md

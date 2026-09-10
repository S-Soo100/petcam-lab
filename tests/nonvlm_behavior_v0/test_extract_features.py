"""특징 추출 CLI 의 순수 부분 — v4.0 저장 예측 조인(G0 게이트), CSV 직렬화."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from scripts.nonvlm_behavior_v0.extract_features import (
    REGRESSION_EXCLUDED_SOURCES,
    feature_rows_to_csv,
    join_gate,
    load_v40_predictions,
)


def _v40_dir(tmp_path: Path) -> Path:
    d = tmp_path / "v40"
    for n, src in [("01", "a.mp4"), ("02", "b.mov")]:
        m = d / "frames" / f"sample-{n}"
        m.mkdir(parents=True)
        (m / "meta.json").write_text(json.dumps({"gt": "moving", "src": src, "nframes": 6}))
    (d / "raw").mkdir()
    (d / "raw" / "v4.0_g1.json").write_text(json.dumps({"results": [{"sample": "sample-01", "action": "drinking", "confidence": 0.9}]}))
    (d / "raw" / "v4.0_g2.json").write_text(json.dumps({"results": [{"sample": "sample-02", "action": "moving", "confidence": 0.6}]}))
    (d / "raw" / "v3.6.1_g1.json").write_text(json.dumps({"results": [{"sample": "sample-01", "action": "moving"}]}))  # 다른 버전은 무시
    return d


def test_load_v40_predictions_joins_meta_src_to_action(tmp_path: Path):
    preds = load_v40_predictions(_v40_dir(tmp_path))
    assert preds == {"a.mp4": "drinking", "b.mov": "moving"}


def test_join_gate_excludes_eval06_sources_and_reports_missing():
    rows = [
        {"filename": "a.mp4", "source": "cam-motion"},
        {"filename": "b.mov", "source": "uploaded"},
        {"filename": "c.mp4", "source": "eval-0615"},
        {"filename": "d.mp4", "source": "eval-0608"},
    ]
    paired, missing = join_gate(rows, {"a.mp4": "drinking", "b.mov": "moving"})
    assert REGRESSION_EXCLUDED_SOURCES == {"eval-0615", "eval-0617"}
    assert paired == ["a.mp4", "b.mov", "d.mp4"]
    assert missing == ["d.mp4"]


def test_feature_rows_to_csv_writes_nan_as_empty_and_fixed_columns(tmp_path: Path):
    rows = [
        {"filename": "a.mp4", "moving_ratio": 0.5, "head_micro": math.nan, "max_geckos": 1},
        {"filename": "b.mov", "moving_ratio": math.nan, "head_micro": 2.5, "max_geckos": 2},
    ]
    out = tmp_path / "features.csv"
    feature_rows_to_csv(rows, out)
    with out.open(newline="") as fh:
        got = list(csv.DictReader(fh))
    assert [r["filename"] for r in got] == ["a.mp4", "b.mov"]
    assert got[0]["head_micro"] == "" and got[1]["moving_ratio"] == ""
    assert got[1]["head_micro"] == "2.5" and got[0]["max_geckos"] == "1"
    assert list(got[0].keys())[0] == "filename"

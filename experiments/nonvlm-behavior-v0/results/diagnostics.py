"""사후 진단 (사전등록 아님 · 게이트 판정에 미반영) — 왜 룰 v0 가 이렇게 나왔는지 클래스별 특징 분포로 설명.

실행: uv run python -m experiments.nonvlm-behavior-v0.results.diagnostics  (또는 PYTHONPATH=. python 이 파일)
출력: 같은 폴더 diagnostics.txt
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MANIFEST = Path("/Users/baek/petcam-lab/storage/dataset-203/manifest.csv")
FEATS = ["head_micro", "longest_static_sec", "global_change_frames", "bbox_area_jump", "aspect_osc", "n_moving_bouts", "moving_ratio", "unknown_ratio"]


def q(vals, p):
    vals = sorted(v for v in vals if not math.isnan(v))
    if not vals:
        return math.nan
    return vals[min(len(vals) - 1, int(round(p * (len(vals) - 1))))]


def main() -> None:
    with MANIFEST.open(newline="") as fh:
        man = {r["filename"]: r for r in csv.DictReader(fh)}
    with (HERE / "features.csv").open(newline="") as fh:
        feats = {r["filename"]: r for r in csv.DictReader(fh)}
    paired = [f for f in feats if man[f]["source"] not in ("eval-0615", "eval-0617")]
    out = []

    def gt6(f):
        g = man[f]["gt"]
        return "feeding" if g in ("drinking", "eating_paste") else g

    out.append("## 클래스 × source (paired 185) — 그룹 LOO CV 가 왜 20% 인가")
    ct = defaultdict(Counter)
    for f in paired:
        ct[gt6(f)][man[f]["source"]] += 1
    srcs = sorted({man[f]["source"] for f in paired})
    out.append("| 클래스 | " + " | ".join(srcs) + " |")
    out.append("|---|" + "---|" * len(srcs))
    for g in sorted(ct, key=lambda k: -sum(ct[k].values())):
        out.append(f"| {g} | " + " | ".join(str(ct[g][s]) for s in srcs) + " |")

    out.append("\n## 특징 분위수 by GT(6-class, paired 185) — 중앙값 [p25, p75] (non-NaN n)")
    for name in FEATS:
        out.append(f"\n### {name}")
        out.append("| 클래스 | n | 중앙값 | p25 | p75 | max |")
        out.append("|---|---|---|---|---|---|")
        for g in ("moving", "feeding", "hand_feeding", "shedding", "eating_prey", "unseen"):
            vals = [float(feats[f][name]) if feats[f][name] != "" else math.nan for f in paired if gt6(f) == g]
            nn = [v for v in vals if not math.isnan(v)]
            out.append(f"| {g} | {len(nn)}/{len(vals)} | {q(vals, .5):.3g} | {q(vals, .25):.3g} | {q(vals, .75):.3g} | {(max(nn) if nn else math.nan):.3g} |")

    out.append("\n## 룰별 발화 조건 충족 수 by GT (paired 185)")
    conds = {
        "R1 global_change≥5": lambda r: float(r["global_change_frames"]) >= 5,
        "R1 area_jump≥2": lambda r: float(r["bbox_area_jump"]) >= 2,
        "R2 static≥8s": lambda r: float(r["longest_static_sec"]) >= 8,
        "R2 head_micro≥2": lambda r: r["head_micro"] != "" and float(r["head_micro"]) >= 2,
        "R2 head_micro≥0.2 (참고)": lambda r: r["head_micro"] != "" and float(r["head_micro"]) >= 0.2,
        "R3 aspect_osc≥0.25": lambda r: r["aspect_osc"] != "" and float(r["aspect_osc"]) >= 0.25,
        "R3 bouts≥4": lambda r: float(r["n_moving_bouts"]) >= 4,
        "R4 unknown≥0.9": lambda r: float(r["unknown_ratio"]) >= 0.9,
    }
    classes = ("moving", "feeding", "hand_feeding", "shedding", "eating_prey", "unseen")
    out.append("| 조건 | " + " | ".join(classes) + " |")
    out.append("|---|" + "---|" * len(classes))
    for cname, fn in conds.items():
        row = []
        for g in classes:
            ks = [f for f in paired if gt6(f) == g]
            row.append(f"{sum(1 for f in ks if fn(feats[f]))}/{len(ks)}")
        out.append(f"| {cname} | " + " | ".join(row) + " |")

    # 참고: 그룹 혼입 없는 층화 5-fold (사전등록 아님, 상한 진단 전용)
    from scripts.nonvlm_behavior_v0.classifier_cv import group_loo_predict
    from scripts.nonvlm_behavior_v0.extract_features import FEATURE_KEYS

    keys = sorted(paired)
    X = [[float(feats[k][n]) if feats[k][n] != "" else math.nan for n in FEATURE_KEYS] for k in keys]
    y = [gt6(k) for k in keys]
    # 층화 5-fold: 클래스별로 순번을 5 로 나눠 fold 배정 (결정론)
    idx_by_cls = defaultdict(list)
    for i, lab in enumerate(y):
        idx_by_cls[lab].append(i)
    folds = [""] * len(y)
    for lab, idxs in idx_by_cls.items():
        for j, i in enumerate(idxs):
            folds[i] = f"fold{j % 5}"
    pred = group_loo_predict(X, y, folds)
    acc = sum(p == t for p, t in zip(pred, y)) / len(y)
    per = Counter()
    tot = Counter(y)
    for p, t in zip(pred, y):
        if p == t:
            per[t] += 1
    out.append(f"\n## 참고(사전등록 아님): 층화 5-fold 로지스틱 — raw6 정확도 {acc:.1%}")
    out.append("| 클래스 | recall |"); out.append("|---|---|")
    for g in classes:
        out.append(f"| {g} | {per[g]}/{tot[g]} |")

    text = "\n".join(out) + "\n"
    (HERE / "diagnostics.txt").write_text(text)
    print(text)


if __name__ == "__main__":
    main()

"""채점 리포트 CLI — GT(manifest) + v4.0 저장 예측(A) + 룰 v0 예측(B) + 특징 → §6 지표·§7 게이트·분류기 arm.

실행 (`-m` 으로 — 레포 루트가 sys.path 에 있어야 `scripts.` 패키지가 잡힌다):
  uv run python -m scripts.nonvlm_behavior_v0.score_report \
      --manifest /Users/baek/petcam-lab/storage/dataset-203/manifest.csv \
      --v40-dir experiments/v40-regression \
      --results-dir experiments/nonvlm-behavior-v0/results

산출: results.json · results.md. GT 는 여기서 처음 읽힌다 (③ deterministic scorer).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path

from scripts.nonvlm_behavior_v0.classifier_cv import group_loo_predict
from scripts.nonvlm_behavior_v0.extract_features import FEATURE_KEYS, REGRESSION_EXCLUDED_SOURCES, load_v40_predictions
from scripts.nonvlm_behavior_v0.scorer import evaluate, merge_feeding, per_class


def load_gt(manifest_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    with Path(manifest_path).open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {r["filename"]: r["gt"] for r in rows}, {r["filename"]: r["source"] for r in rows}


def load_features(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with Path(path).open(newline="") as fh:
        for r in csv.DictReader(fh):
            row: dict = {}
            for k, v in r.items():
                if k == "filename":
                    continue
                if k in ("clip_id", "source"):
                    row[k] = v
                else:
                    row[k] = float(v) if v not in ("", None) else math.nan
            out[r["filename"]] = row
    return out


def load_rule_predictions(path: Path) -> dict[str, str]:
    with Path(path).open(newline="") as fh:
        return {r["filename"]: r["label"] for r in csv.DictReader(fh)}


def _classifier_arm(keys: list[str], gt: dict[str, str], feats: dict[str, dict]) -> dict:
    X = [[feats[k].get(name, math.nan) for name in FEATURE_KEYS] for k in keys]
    y = [merge_feeding(gt[k]) for k in keys]
    groups = [feats[k].get("source", "?") for k in keys]
    pred = group_loo_predict(X, y, groups)
    hits = Counter()
    totals = Counter(y)
    for p, t in zip(pred, y):
        if p == t:
            hits[t] += 1
    return {
        "note": "상한 확인용 (§5-2). adopt 대상 아님. 그룹 = manifest source.",
        "groups": sorted(set(groups)),
        "accuracy_raw6": sum(hits.values()) / len(y) if y else 0.0,
        "per_class_recall": {c: (hits[c], totals[c]) for c in sorted(totals)},
        "predictions": dict(zip(keys, pred)),
    }


def run_scoring(gt, sources, v40, rule, feats) -> dict:
    paired_keys = [k for k in gt if sources.get(k) not in REGRESSION_EXCLUDED_SOURCES and k in v40 and k in rule and k in feats]
    gt_p = {k: gt[k] for k in paired_keys}
    res_p = evaluate(gt_p, {k: v40[k] for k in paired_keys}, {k: rule[k] for k in paired_keys}, {k: feats[k] for k in paired_keys})
    res_p["classifier_cv"] = _classifier_arm(paired_keys, gt_p, feats)

    all_keys = [k for k in gt if k in rule and k in feats]
    gt_a = {k: gt[k] for k in all_keys}
    rule_a = {k: rule[k] for k in all_keys}
    res_all = {
        "n": len(all_keys),
        "raw6_acc_B": sum(1 for k in all_keys if rule_a[k] == merge_feeding(gt_a[k])) / len(all_keys) if all_keys else 0.0,
        "per_class_B": per_class(rule_a, gt_a, merge=True),
    }
    return {"paired": res_p, "all197": res_all}


def _pct(hit_total) -> str:
    hit, total = hit_total
    return f"{hit}/{total} = {hit / total:.1%}" if total else f"{hit}/0"


def build_markdown(res: dict) -> str:
    p, a = res["paired"], res["all197"]
    lines = [
        "# nonvlm-behavior-v0 채점 결과 (자동 생성)", "",
        f"- paired(185 동결 기준) n = {p['n']} · 전체 측정 n = {a['n']}",
        f"- **decision_B = `{p['decision_B']}`** (§9 룰)", "",
        "## 게이트 (§7)", "", "| 게이트 | 판정 | 값 |", "|---|---|---|",
        f"| G_B1_moving_recall ≥0.90 | {'✅' if p['gates']['G_B1_moving_recall'] else '❌'} | {_pct(p['moving_recall_B'])} |",
        f"| G_B2_hand_feeding_recall ≥0.80 | {'✅' if p['gates']['G_B2_hand_feeding_recall'] else '❌'} | {_pct(p['hand_feeding_recall_B'])} |",
        f"| G_B3_feeding_recall_vs_A (−10%p) | {'✅' if p['gates']['G_B3_feeding_recall_vs_A'] else '❌'} | B {_pct(p['feeding_recall_B'])} vs A {_pct(p['feeding_recall_A'])} |",
        f"| G_B4_feeding_fp ≤10% | {'✅' if p['gates']['G_B4_feeding_fp'] else '❌'} | {_pct(p['feeding_fp_B'])} |",
        f"| G_C (C 급여경계 ≥ A AND recovered ≥ broken) | {'✅' if p['gates']['G_C'] else '❌'} | acc A {p['boundary_acc']['A']:.1%} / C {p['boundary_acc']['C']:.1%} · recovered {len(p['paired_A_to_C']['recovered'])} / broken {len(p['paired_A_to_C']['broken'])} |",
        "", "## 정확도", "",
        f"- 급여경계: A {p['boundary_acc']['A']:.1%} · B {p['boundary_acc']['B']:.1%} · C {p['boundary_acc']['C']:.1%}",
        f"- B raw(6-class, 급여 묶음): paired {p['raw6_acc_B']:.1%} · 전체 {a['raw6_acc_B']:.1%}",
        f"- 분류기 arm(그룹 LOO CV, 상한): {p['classifier_cv']['accuracy_raw6']:.1%}",
        "", "## A↔B 상보성 (complementarity, 급여경계 기준)", "",
        "| both | A만 정답 | B만 정답 | 둘 다 오답 |", "|---|---|---|---|",
        "| {both} | {a_only} | {b_only} | {neither} |".format(**p["complementarity"]),
        "", "## 클래스별 (B, 급여 묶음)", "", "| 클래스 | recall | precision | 혼동 |", "|---|---|---|---|",
    ]
    for cls, row in sorted(p["per_class_B"].items(), key=lambda kv: -kv[1]["gt_total"]):
        rec = f"{row['tp']}/{row['gt_total']}" if row["gt_total"] else "—"
        prec = f"{row['precision']:.0%}" if row["precision"] is not None else "—"
        lines.append(f"| {cls} | {rec} | {prec} | {row['confusion']} |")
    lines += ["", "## 클래스별 (A = v4.0 Sonnet, 7-class)", "", "| 클래스 | recall | precision |", "|---|---|---|"]
    for cls, row in sorted(p["per_class_A"].items(), key=lambda kv: -kv[1]["gt_total"]):
        rec = f"{row['tp']}/{row['gt_total']}" if row["gt_total"] else "—"
        prec = f"{row['precision']:.0%}" if row["precision"] is not None else "—"
        lines.append(f"| {cls} | {rec} | {prec} |")
    lines += ["", "## C paired (A→C)", ""]
    for tag in ("recovered", "broken", "harmless"):
        for k, g, pa, pc in p["paired_A_to_C"][tag]:
            lines.append(f"- [{tag}] `{k}` GT={g}: {pa} → {pc}")
    dis = p.get("disagreements", [])
    lines += ["", f"## Discordant review 후보 — A↔B 급여경계 정오 불일치 {len(dis)}건 (owner 육안, 최대 20건 권장)", "",
              "| 파일 | GT | A(v4.0) | B(룰 v0) | 정답 쪽 |", "|---|---|---|---|---|"]
    for d in dis:
        lines.append(f"| `{d['key']}` | {d['gt']} | {d['A']} | {d['B']} | {'A' if d['A_ok'] else 'B'} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--v40-dir", required=True)
    parser.add_argument("--results-dir", required=True)
    args = parser.parse_args(argv)
    results = Path(args.results_dir)
    gt, sources = load_gt(Path(args.manifest))
    v40 = load_v40_predictions(Path(args.v40_dir))
    rule = load_rule_predictions(results / "predictions_rule_v0.csv")
    feats = load_features(results / "features.csv")
    res = run_scoring(gt, sources, v40, rule, feats)
    (results / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True, default=str))
    md = build_markdown(res)
    (results / "results.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

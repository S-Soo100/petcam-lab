"""artifact → 특징 CSV + 룰 v0 예측 (petcam-lab venv). GT 는 읽지 않는다 (무결성 ②).

실행 (`-m` 으로 — 레포 루트가 sys.path 에 있어야 `scripts.` 패키지가 잡힌다):
  uv run python -m scripts.nonvlm_behavior_v0.extract_features \
      --manifest /Users/baek/petcam-lab/storage/dataset-203/manifest.csv \
      --clips-dir /Users/baek/petcam-lab/storage/dataset-203 \
      --artifacts-dir /Users/baek/petcam-lab/storage/nonvlm-behavior-v0/gme \
      --v40-dir experiments/v40-regression \
      --out-dir experiments/nonvlm-behavior-v0/results

산출: features.csv · predictions_rule_v0.csv · join_gate.json (G0: v4.0 조인 185/185, artifact ok 수)
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from pathlib import Path

from scripts.nonvlm_behavior_v0.features import compute_features
from scripts.nonvlm_behavior_v0.head_micro import compute_head_micro_for_clip
from scripts.nonvlm_behavior_v0.rules import RULE_VERSION, rule_v0

REGRESSION_EXCLUDED_SOURCES = {"eval-0615", "eval-0617"}
FEATURE_KEYS = [
    "moving_ratio", "longest_static_sec", "longest_static_start_sec", "longest_static_end_sec", "longest_moving_sec",
    "n_moving_bouts", "disp_mean", "disp_max", "aspect_osc", "global_change_frames", "first_global_change_sec",
    "unknown_ratio", "not_visible_ratio", "max_geckos", "bbox_area_jump", "head_micro",
]


def load_v40_predictions(v40_dir: Path) -> dict[str, str]:
    """frames/sample-NN/meta.json 의 src(파일명) ↔ raw/v4.0_g*.json 의 sample→action 을 파일명 키로 조인."""
    sample_to_src = {}
    for meta in sorted(Path(v40_dir, "frames").glob("sample-*/meta.json")):
        sample_to_src[meta.parent.name] = json.loads(meta.read_text())["src"]
    preds: dict[str, str] = {}
    for raw in sorted(Path(v40_dir, "raw").glob("v4.0_g*.json")):
        for r in json.loads(raw.read_text()).get("results", []):
            src = sample_to_src.get(r.get("sample"))
            if src and "action" in r:
                preds[src] = r["action"]
    return preds


def join_gate(rows: list[dict], v40_preds: dict[str, str]) -> tuple[list[str], list[str]]:
    paired = [r["filename"] for r in rows if r["source"] not in REGRESSION_EXCLUDED_SOURCES]
    missing = [f for f in paired if f not in v40_preds]
    return paired, missing


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    return str(v)


def feature_rows_to_csv(rows: list[dict], path: Path) -> None:
    keys = ["filename"] + [k for k in rows[0] if k != "filename"] if rows else ["filename"]
    with Path(path).open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: _cell(r.get(k)) for k in keys})


def write_sample_list(manifest_path: Path, out_path: Path, taken: str) -> int:
    with Path(manifest_path).open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    keep = [{k: r[k] for k in ("filename", "clip_id", "gt", "source")} for r in rows]
    Path(out_path).write_text(json.dumps({
        "snapshot_of": "storage/dataset-203/manifest.csv", "taken": taken, "n": len(keep),
        "regression_excluded_sources": sorted(REGRESSION_EXCLUDED_SOURCES), "rows": keep,
    }, ensure_ascii=False, indent=1))
    return len(keep)


def _load_artifact(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(gzip.decompress(path.read_bytes()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--clips-dir", required=True)
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--v40-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--sample-list", default="", help="주어지면 manifest 스냅샷을 이 경로에 쓴다")
    parser.add_argument("--taken", default="")
    args = parser.parse_args(argv)

    if args.sample_list:
        n = write_sample_list(Path(args.manifest), Path(args.sample_list), args.taken)
        print(f"sample_list {n} rows → {args.sample_list}")

    with open(args.manifest, newline="") as fh:
        rows = sorted(csv.DictReader(fh), key=lambda r: r["filename"])
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    feature_rows, pred_rows, statuses = [], [], {}
    for r in rows:
        filename = r["filename"]
        art = _load_artifact(Path(args.artifacts_dir) / f"{filename}.json.gz")
        if art is None:
            statuses[filename] = "missing_artifact"
            continue
        status = art["summary"]["status"]
        statuses[filename] = status
        if status != "ok":
            continue
        feats = compute_features(art)
        feats["head_micro"] = compute_head_micro_for_clip(
            Path(args.clips_dir) / filename, art["gme"]["track_points"],
            (feats["longest_static_start_sec"], feats["longest_static_end_sec"]),
        )
        label = rule_v0(feats)
        feature_rows.append({"filename": filename, "clip_id": r["clip_id"], "source": r["source"], **{k: feats[k] for k in FEATURE_KEYS}})
        pred_rows.append({"filename": filename, "label": label, "rule_version": RULE_VERSION})
        print(f"{filename} {label} static={feats['longest_static_sec']:.1f}s head_micro={_cell(feats['head_micro'])}", flush=True)

    feature_rows_to_csv(feature_rows, out_dir / "features.csv")
    feature_rows_to_csv(pred_rows, out_dir / "predictions_rule_v0.csv")

    v40 = load_v40_predictions(Path(args.v40_dir))
    paired, missing = join_gate(rows, v40)
    ok = sum(1 for s in statuses.values() if s == "ok")
    gate = {
        "artifact_ok": ok, "artifact_total": len(rows), "artifact_ok_ratio": ok / len(rows) if rows else 0.0,
        "statuses": statuses, "v40_predictions": len(v40), "paired_expected": len(paired), "paired_missing": missing,
        "G0_artifact_ok_ge_95pct": (ok / len(rows) if rows else 0.0) >= 0.95,
        "G0_join_complete": not missing,
    }
    (out_dir / "join_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=1, sort_keys=True))
    print(json.dumps({k: gate[k] for k in ("artifact_ok", "artifact_total", "paired_expected", "G0_artifact_ok_ge_95pct", "G0_join_complete")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

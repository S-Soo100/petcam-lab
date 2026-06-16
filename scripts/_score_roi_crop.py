"""roi-crop-center 채점 — center ROI crop(@1080) vs 적응형@1080 baseline paired.

baseline = v40-regression 적응형 v4.0 Sonnet blind (clip_id 매핑 재활용, 54/56).
treatment = experiments/roi-crop-center/crop_pred.jsonl (center crop, Sonnet v4.0 blind).
급여경계 게이트(_score_v40 동형: drinking↔eating_paste 무해) + 원본 해상도 4K급 층화.

실행: PYTHONPATH=. uv run python scripts/_score_roi_crop.py
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROI = REPO / "experiments" / "roi-crop-center"
V40 = REPO / "experiments" / "v40-regression"
FEEDING = {"drinking", "eating_paste"}  # 급여 무해 그룹


def boundary_correct(pred: str | None, g: str) -> bool:
    if pred is None:
        return False
    if g in FEEDING:
        return pred in FEEDING
    return pred == g


def main() -> int:
    mapping = json.load(open(ROI / "blind_mapping.json"))  # sample -> {gt, clip_id, nframes}
    crop = {json.loads(l)["sample"]: json.loads(l)["pred"] for l in open(ROI / "crop_pred.jsonl")}

    # baseline: v40 적응형 v4.0 → clip_id
    man = {r["filename"]: r["clip_id"] for r in csv.DictReader(open(REPO / "storage/dataset-203/manifest.csv"))}
    v40_s2cid = {}
    for m in (V40 / "frames").glob("sample-*/meta.json"):
        d = json.loads(m.read_text())
        cid = man.get(d["src"])
        if cid:
            v40_s2cid[m.parent.name] = cid
    v40_pred = {}
    for f in (V40 / "raw").glob("v4.0_g*.json"):
        for r in json.loads(f.read_text()).get("results", []):
            if "sample" in r and "action" in r:
                v40_pred[r["sample"]] = r["action"]
    base_by_cid = {v40_s2cid[s]: a for s, a in v40_pred.items() if s in v40_s2cid}
    # eval-0615 2건 적응형 baseline (v40-regression 미포함 → 2026-06-16 신규 blind 측정)
    for _s, _i in mapping.items():
        if _i["clip_id"][:8] == "9e9f164b":
            base_by_cid[_i["clip_id"]] = "drinking"
        elif _i["clip_id"][:8] == "d6c57474":
            base_by_cid[_i["clip_id"]] = "moving"

    # 원본 짧은변 (4K급 층화)
    se = json.load(open("/tmp/roi_se.json")) if Path("/tmp/roi_se.json").exists() else {}

    recovered, broken, harmless, no_base = [], [], [], []
    by_gt = defaultdict(lambda: [0, 0, 0])  # base_bc, crop_bc, total
    strat = {"4K급(≥1440)": [0, 0, 0, 0], "그외(<1440)": [0, 0, 0, 0]}  # base_bc, crop_bc, rec, brk

    for s, info in mapping.items():
        g, cid = info["gt"], info["clip_id"]
        cpred, bpred = crop.get(s), base_by_cid.get(cid)
        by_gt[g][2] += 1
        if bpred is None:
            no_base.append((s, g, cpred))
            continue
        bc_b, bc_c = boundary_correct(bpred, g), boundary_correct(cpred, g)
        by_gt[g][0] += bc_b
        by_gt[g][1] += bc_c
        bucket = "4K급(≥1440)" if se.get(cid, 0) >= 1440 else "그외(<1440)"
        strat[bucket][0] += bc_b
        strat[bucket][1] += bc_c
        if bc_c and not bc_b:
            recovered.append((s, g, bpred, cpred, se.get(cid, 0)))
            strat[bucket][2] += 1
        elif bc_b and not bc_c:
            broken.append((s, g, bpred, cpred, se.get(cid, 0)))
            strat[bucket][3] += 1
        elif bpred != cpred and g in FEEDING and bpred in FEEDING and cpred in FEEDING:
            harmless.append((s, g, bpred, cpred))

    n_paired = sum(1 for s, i in mapping.items() if base_by_cid.get(i["clip_id"]))
    base_acc = sum(v[0] for v in by_gt.values())
    crop_acc = sum(v[1] for v in by_gt.values())
    print(f"=== roi-crop-center 채점 (paired {n_paired}/56, baseline 누락 {len(no_base)}) ===")
    print(f"급여경계 정확도: baseline(적응형) {base_acc}/{n_paired}={base_acc/n_paired:.1%} · crop {crop_acc}/{n_paired}={crop_acc/n_paired:.1%} · Δ {(crop_acc-base_acc)/n_paired*100:+.1f}%p")

    print(f"\n=== 급여경계 paired (적응형 → crop) ===")
    print(f"  recovered {len(recovered)} · broken {len(broken)} · 무해(급여내부) {len(harmless)}")
    print(f"  순효과 recovered − broken = {len(recovered) - len(broken):+d}")
    gate = "✅ adopt(≥+3)" if (len(recovered) - len(broken)) >= 3 else ("close(≤0)" if (len(recovered) - len(broken)) <= 0 else "hold")
    print(f"  게이트: {gate}")
    for tag, lst in [("recovered", recovered), ("broken", broken), ("무해", harmless)]:
        for row in lst:
            s, g, a0, a1 = row[:4]
            extra = f" (짧은변 {row[4]})" if len(row) > 4 else ""
            print(f"    [{tag}] {s} GT={g}: {a0} → {a1}{extra}")

    print(f"\n=== 원본 해상도 층화 (보조 분석) ===")
    for b, (bb, cc, rec, brk) in strat.items():
        tot = bb + cc  # placeholder; recompute n per bucket
    # n per bucket
    nb = defaultdict(int)
    for s, info in mapping.items():
        if base_by_cid.get(info["clip_id"]):
            nb["4K급(≥1440)" if se.get(info["clip_id"], 0) >= 1440 else "그외(<1440)"] += 1
    for b in ["4K급(≥1440)", "그외(<1440)"]:
        bb, cc, rec, brk = strat[b]
        print(f"  {b} (n={nb[b]}): baseline {bb} → crop {cc} 정답 · recovered {rec} / broken {brk} (순 {rec-brk:+d})")

    print(f"\n=== 클래스별 급여경계 정답 (baseline → crop) ===")
    for g in sorted(by_gt, key=lambda x: -by_gt[x][2]):
        b, c, t = by_gt[g]
        print(f"  {g:13s} {b:2d} → {c:2d} / {t}")

    if no_base:
        print(f"\n=== baseline 누락 (crop pred만, eval-0615) ===")
        for s, g, c in no_base:
            print(f"  {s} GT={g}: crop={c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

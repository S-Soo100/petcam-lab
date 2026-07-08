"""v4.1 shedding IR-guard 회귀 채점 — 시험지 게이트 그대로 구현.

입력:
  _preds_raw.json  — Workflow 출력 [{i, results:[{sid,action,confidence,reasoning}]}]
  _batches.json    — 사설 맵 [{job, samples:[{sid,real_id,gt}]}] (batch i 정렬 일치)
  ../v40-regression/raw/v4.0_g*.json   — Set-REG v4.0 캐시 (paired 기준선)
  ../v40-regression/frames/*/meta.json — Set-REG GT

Part A (Set-FP 32, GT=moving): shedding 억제율 · paired recovered/broken/new-error.
Part B (Set-REG 185): v4.0 캐시 vs v4.1 — raw · 진짜탈피 recall(broken_shed) · 급여경계 paired.

실행: PYTHONPATH=. uv run python experiments/v41-shedding-ir-guard/_score.py
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
EXP = Path(__file__).resolve().parent
V40REG = REPO / "experiments" / "v40-regression"

FEEDING = {"drinking", "eating_paste"}
NON_MOVING_ERR = {"drinking", "eating_paste", "eating_prey", "hand_feeding", "unseen"}


def boundary_correct(pred: str | None, g: str) -> bool:
    if pred is None:
        return False
    if g in FEEDING:
        return pred in FEEDING
    return pred == g


def load_reg_gt() -> dict[str, str]:
    return {
        m.parent.name: json.loads(m.read_text())["gt"]
        for m in sorted((V40REG / "frames").glob("sample-*/meta.json"))
    }


def load_reg_v40_cache() -> dict[str, str]:
    preds: dict[str, str] = {}
    for f in sorted((V40REG / "raw").glob("v4.0_g*.json")):
        for r in json.loads(f.read_text()).get("results", []):
            if "sample" in r and "action" in r:
                preds[r["sample"]] = r["action"]
    return preds


def main() -> int:
    preds_raw = json.loads((EXP / "_preds_raw.json").read_text())
    batches = json.loads((EXP / "_batches.json").read_text())

    sid_info = {s["sid"]: (s["real_id"], s["gt"]) for b in batches for s in b["samples"]}
    by_i = {p["i"]: p for p in preds_raw}

    job_preds: dict[str, dict[str, str]] = defaultdict(dict)
    conf_rows = []
    missing = []
    for i, b in enumerate(batches):
        p = by_i.get(i)
        if not p or not p.get("results"):
            missing.append((i, b["job"]))
            continue
        for r in p["results"]:
            sid = r.get("sid")
            if sid in sid_info:
                real_id, gt = sid_info[sid]
                job_preds[b["job"]][real_id] = r["action"]
                conf_rows.append({"job": b["job"], "real_id": real_id, "gt": gt,
                                  "action": r["action"], "confidence": r.get("confidence"),
                                  "reasoning": r.get("reasoning", "")})

    if missing:
        print(f"⚠️ 결과 누락 배치 {len(missing)}: {missing}\n")

    # jsonl 박제
    with (EXP / "_preds.jsonl").open("w", encoding="utf-8") as fh:
        for row in conf_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ══════════════ Part A — Set-FP (오탐 억제) ══════════════
    v40 = job_preds["fp_v40"]
    v41 = job_preds["fp_v41"]
    fp_clips = sorted({s["real_id"] for b in batches if b["job"] == "fp_v40" for s in b["samples"]})
    print(f"══ Part A · Set-FP (N={len(fp_clips)}, GT=moving 전부) ══")
    print(f"  적재: v4.0 {len(v40)}건 · v4.1 {len(v41)}건")

    dist0 = Counter(v40.get(c, "∅") for c in fp_clips)
    dist1 = Counter(v41.get(c, "∅") for c in fp_clips)
    print(f"  v4.0 분포: {dict(dist0)}")
    print(f"  v4.1 분포: {dict(dist1)}")

    S0 = sum(v40.get(c) == "shedding" for c in fp_clips)
    S1 = sum(v41.get(c) == "shedding" for c in fp_clips)
    suppression = (S0 - S1) / S0 if S0 else float("nan")
    recovered = [c for c in fp_clips if v40.get(c) == "shedding" and v41.get(c) == "moving"]
    broken = [c for c in fp_clips if v40.get(c) == "moving" and v41.get(c) == "shedding"]
    new_err = [c for c in fp_clips if v41.get(c) in NON_MOVING_ERR]
    v41_moving = sum(v41.get(c) == "moving" for c in fp_clips)

    print(f"\n  shedding 오탐: v4.0 S0={S0} → v4.1 S1={S1} · 억제율 {suppression:.0%}")
    print(f"  recovered(shed→moving) {len(recovered)} · broken(moving→shed) {len(broken)} · new-error(→비moving) {len(new_err)} {new_err}")
    print(f"  v4.1 정확도(→moving): {v41_moving}/{len(fp_clips)} = {v41_moving/len(fp_clips):.1%}")
    gA = (not (S0 == 0)) and suppression >= 0.60 and len(broken) == 0 and len(new_err) <= 2
    print(f"  ▶ Part A 게이트 (억제율≥60% + broken=0 + new-error≤2): {'✅ PASS' if gA else '❌'}")

    # ══════════════ Part B — Set-REG (회귀) ══════════════
    gt = load_reg_gt()
    c40 = load_reg_v40_cache()
    r41 = job_preds["reg_v41"]
    n = len(gt)
    print(f"\n══ Part B · Set-REG (N={n}) ══")
    miss41 = sorted(set(gt) - set(r41))
    print(f"  적재: v4.0캐시 {len(c40)} · v4.1 {len(r41)}" + (f" · ⚠️v4.1 누락 {len(miss41)}: {miss41[:6]}" if miss41 else " · 누락 0"))

    def acc(p):
        raw = sum(p.get(s) == g for s, g in gt.items())
        bnd = sum(boundary_correct(p.get(s), g) for s, g in gt.items())
        return raw, bnd

    r0, b0 = acc(c40)
    r1, b1 = acc(r41)
    d_raw = (r1 - r0) / n * 100
    print(f"  raw: v4.0 {r0}/{n}={r0/n:.1%} → v4.1 {r1}/{n}={r1/n:.1%} (Δ{d_raw:+.1f}%p)")
    print(f"  급여경계: v4.0 {b0/n:.1%} → v4.1 {b1/n:.1%}")

    # 진짜 탈피 recall
    shed = [s for s, g in gt.items() if g == "shedding"]
    sh0 = sum(c40.get(s) == "shedding" for s in shed)
    sh1 = sum(r41.get(s) == "shedding" for s in shed)
    broken_shed = [(s, c40.get(s), r41.get(s)) for s in shed if c40.get(s) == "shedding" and r41.get(s) != "shedding"]
    recovered_shed = [(s, c40.get(s), r41.get(s)) for s in shed if c40.get(s) != "shedding" and r41.get(s) == "shedding"]
    print(f"\n  진짜 탈피 recall(N={len(shed)}): v4.0 {sh0} → v4.1 {sh1}")
    print(f"  broken_shed(v4.0맞음→v4.1틀림) {len(broken_shed)}: {broken_shed}")
    if recovered_shed:
        print(f"  recovered_shed {len(recovered_shed)}: {recovered_shed}")

    # 급여경계 paired
    rec, brk, harm = [], [], []
    for s, g in gt.items():
        a0, a1 = c40.get(s), r41.get(s)
        if a0 is None or a1 is None:
            continue
        bc0, bc1 = boundary_correct(a0, g), boundary_correct(a1, g)
        if bc0 and not bc1:
            brk.append((s, g, a0, a1))
        elif bc1 and not bc0:
            rec.append((s, g, a0, a1))
        elif a0 != a1 and g in FEEDING and a0 in FEEDING and a1 in FEEDING:
            harm.append((s, g, a0, a1))
    print(f"\n  급여경계 paired: recovered {len(rec)} · broken {len(brk)} · 무해 {len(harm)}")
    for tag, lst in [("recovered", rec), ("broken", brk)]:
        for s, g, a0, a1 in lst:
            print(f"    [{tag}] {s} GT={g}: {a0}→{a1}")

    # shedding 관련 클래스 변동 (오탐 억제가 다른 클래스로 샜나)
    print(f"\n  클래스별 raw (v4.0→v4.1):")
    by_gt = defaultdict(lambda: [0, 0, 0])
    for s, g in gt.items():
        by_gt[g][2] += 1
        by_gt[g][0] += c40.get(s) == g
        by_gt[g][1] += r41.get(s) == g
    for g in sorted(by_gt, key=lambda x: -by_gt[x][2]):
        a, bb, t = by_gt[g]
        flag = " ⚠️" if bb < a - 1 else ""
        print(f"    {g:13s} {a:2d}/{t:2d} → {bb:2d}/{t:2d}{flag}")

    gB = len(broken_shed) <= 2 and len(rec) >= len(brk) and d_raw >= -3.0
    print(f"\n  ▶ Part B 게이트 (broken_shed≤2 + 급여 rec≥brk + raw≥−3%p): {'✅ PASS' if gB else '❌'}")

    # ══════════════ Decision ══════════════
    print(f"\n══ Decision (시험지 §7) ══")
    if gA and gB:
        dec = "adopt"
    elif suppression < 0.30 or len(broken) > 0 or len(broken_shed) >= 5 or d_raw < -3.0:
        dec = "reject"
    else:
        dec = "hold"
    print(f"  Part A {'PASS' if gA else 'FAIL'} · Part B {'PASS' if gB else 'FAIL'} → **{dec.upper()}**")
    print(f"  (억제율 {suppression:.0%} · broken {len(broken)} · new-err {len(new_err)} · broken_shed {len(broken_shed)} · raw Δ{d_raw:+.1f}%p)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

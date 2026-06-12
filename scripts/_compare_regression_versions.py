"""4버전(v3.5/v3.6/v3.6.1/v3.6.2-draft) Gemini 회귀 결과 통합 비교. 임시 (2026-06-12).

eval_vlm_v36_handfeeding.py 가 버전별로 떨군 /tmp/vlm-regression-{v35,v36,v361,v362-draft}.jsonl
를 읽어 공식 채점(merge_label + FEEDING_MERGE/HIDING_MERGE)으로 한 표에 정렬.

목적:
- P0 floor(85.5%) 를 어느 버전이 넘는지 한눈에.
- OOD hand_feeding recall (v3.5 구조적 0 vs v3.6+ 이득).
- v3.6.1 → v3.6.2-draft 의 shedding/moving 변화 = IR 가드가 production(Gemini)에서
  no-op 인지 / 진짜 shed 를 깎는지 직접 확인 (P3 가설은 Sonnet 기준이었음).

실행: PYTHONPATH=. uv run python scripts/_compare_regression_versions.py
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from scripts.eval_vlm_worker_regression import (
    FEEDING_MERGE,
    HIDING_MERGE,
    PRICE_INPUT_PER_1M,
    PRICE_OUTPUT_PER_1M,
    merge_label,
)

FLOOR = 0.855
VERSIONS = [
    ("v3.5", "/tmp/vlm-regression-v35.jsonl"),
    ("v3.6", "/tmp/vlm-regression-v36.jsonl"),
    ("v3.6.1", "/tmp/vlm-regression-v361.jsonl"),
    ("v3.6.2-draft", "/tmp/vlm-regression-v362-draft.jsonl"),
]


def load(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("ok"):
            rows.append(r)
    return rows


def score(rows: list[dict]) -> dict:
    p0_total = p0_correct = ood_total = ood_rec = 0
    tok_in = tok_out = 0
    # 클래스별 recall (raw GT 기준) + shedding 과탐 추적
    per_gt = defaultdict(lambda: [0, 0])  # gt → [correct(merged), total]
    pred_shedding = 0  # 전체에서 shedding 으로 찍은 수 (과탐 프록시)
    confusion = []
    for r in rows:
        gt, pred = r["gt_action"], r["action"]
        tok_in += r.get("tokens_input") or 0
        tok_out += r.get("tokens_output") or 0
        if pred == "shedding":
            pred_shedding += 1
        if gt == "hand_feeding":
            ood_total += 1
            ood_rec += pred == "hand_feeding"
            continue
        gt_m = merge_label(gt, HIDING_MERGE, FEEDING_MERGE)
        pred_m = merge_label(pred, FEEDING_MERGE)
        p0_total += 1
        ok = gt_m == pred_m
        p0_correct += ok
        per_gt[gt_m][1] += 1
        per_gt[gt_m][0] += ok
        if not ok:
            confusion.append((r["clip_id"][:8], gt_m, pred_m))
    return {
        "n": len(rows),
        "p0_acc": p0_correct / p0_total if p0_total else 0.0,
        "p0": (p0_correct, p0_total),
        "ood": (ood_rec, ood_total),
        "cost": tok_in * PRICE_INPUT_PER_1M / 1e6 + tok_out * PRICE_OUTPUT_PER_1M / 1e6,
        "per_gt": dict(per_gt),
        "pred_shedding": pred_shedding,
        "confusion": confusion,
    }


def main() -> int:
    results = {v: score(load(path)) for v, path in VERSIONS}

    print("\n" + "=" * 78)
    print("Gemini 2.5 Flash 회귀 — 4버전 통합 (202건, P0 floor 85.5%)")
    print("=" * 78)
    print(f"{'version':14s} {'N':>4s} {'P0 feeding-merged':>20s} {'OOD recall':>14s} "
          f"{'shed찍음':>9s} {'$':>7s}")
    for v, _ in VERSIONS:
        s = results[v]
        if not s["n"]:
            print(f"{v:14s}  (결과 파일 없음/비어있음)")
            continue
        floor_mark = "✅" if s["p0_acc"] >= FLOOR else "⚠️"
        oc, ot = s["ood"]
        pc, pt = s["p0"]
        print(f"{v:14s} {s['n']:>4d} {pc:>4d}/{pt:<3d}={s['p0_acc']:>6.1%}{floor_mark} "
              f"{oc:>3d}/{ot:<3d}={oc/ot if ot else 0:>5.0%} {s['pred_shedding']:>9d} "
              f"${s['cost']:>5.3f}")

    # 클래스별 recall 매트릭스
    all_classes = sorted({c for s in results.values() for c in s.get("per_gt", {})})
    print("\n" + "-" * 78)
    print("클래스별 정확도 (feeding-merged GT 기준, recall)")
    print("-" * 78)
    print(f"{'class':14s} " + " ".join(f"{v.replace('-draft',''):>12s}" for v, _ in VERSIONS))
    for cls in all_classes:
        cells = []
        for v, _ in VERSIONS:
            pg = results[v].get("per_gt", {})
            if cls in pg:
                c, t = pg[cls]
                cells.append(f"{c:>2d}/{t:<2d}={c/t:>3.0%}")
            else:
                cells.append(f"{'-':>12s}")
        print(f"{cls:14s} " + " ".join(f"{x:>12s}" for x in cells))

    # v3.6.1 → v3.6.2 직접 diff (IR 가드 효과)
    s1, s2 = results.get("v3.6.1"), results.get("v3.6.2-draft")
    if s1 and s2 and s1["n"] and s2["n"]:
        print("\n" + "-" * 78)
        print("v3.6.1 → v3.6.2-draft 변화 (IR shedding 가드의 production 효과)")
        print("-" * 78)
        print(f"  P0 정확도   : {s1['p0_acc']:.1%} → {s2['p0_acc']:.1%} "
              f"({(s2['p0_acc']-s1['p0_acc'])*100:+.1f}%p)")
        print(f"  shedding 찍은 수: {s1['pred_shedding']} → {s2['pred_shedding']} "
              f"({s2['pred_shedding']-s1['pred_shedding']:+d})")
        sh1 = s1["per_gt"].get("shedding", (0, 0))
        sh2 = s2["per_gt"].get("shedding", (0, 0))
        print(f"  shedding recall: {sh1[0]}/{sh1[1]} → {sh2[0]}/{sh2[1]}  "
              f"(가드가 진짜 shed 를 깎으면 여기 떨어짐)")
        c1 = {x[0] for x in s1["confusion"]}
        c2 = {x[0] for x in s2["confusion"]}
        print(f"  v3.6.1 오답인데 v3.6.2 정답 (recovered): {len(c1 - c2)}건")
        print(f"  v3.6.1 정답인데 v3.6.2 오답 (broken)   : {len(c2 - c1)}건")

    print("\n" + "=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""eval-0608 Claude v3.6 blind 판정 분석 — GT(meta.json) 대조.

claude_v36_blind.jsonl(서브에이전트 blind 판정) vs 각 sample 의 meta.json GT.
정성 트랙 (contact sheet + Claude 구독) — Gemini 영상 네이티브 정량 baseline 아님.

실행: PYTHONPATH=. uv run python scripts/analyze_eval0608_claude.py
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "experiments" / "eval-0608-claude"
FEEDING_MERGE = {"drinking": "feeding", "eating_paste": "feeding"}


def merge(a: str) -> str:
    return FEEDING_MERGE.get(a, a)


def main() -> None:
    preds = {}
    for line in (BASE / "claude_v36_blind.jsonl").read_text().splitlines():
        r = json.loads(line)
        preds[r["sample"]] = r

    rows = []
    for d in sorted(BASE.glob("sample-*")):
        meta = json.loads((d / "meta.json").read_text())
        p = preds[d.name]
        rows.append({"sample": d.name, "gt": meta["gt"], "pred": p["pred"], "conf": p["conf"]})

    n = len(rows)
    raw = sum(1 for r in rows if r["gt"] == r["pred"])
    merged = sum(1 for r in rows if merge(r["gt"]) == merge(r["pred"]))

    by_gt: dict[str, dict[str, int]] = defaultdict(lambda: {"c": 0, "t": 0})
    for r in rows:
        by_gt[r["gt"]]["t"] += 1
        if r["gt"] == r["pred"]:
            by_gt[r["gt"]]["c"] += 1

    ood = [r for r in rows if r["gt"] == "hand_feeding"]
    ood_rec = sum(1 for r in ood if r["pred"] == "hand_feeding")

    confusion: Counter = Counter()
    errors = []
    for r in rows:
        if r["gt"] != r["pred"]:
            confusion[f"{r['gt']:13s} → {r['pred']}"] += 1
            errors.append(r)

    print("=" * 62)
    print(f"eval-0608 — Claude v3.6 blind 판정 (contact sheet, N={n})")
    print("  ⚠️ 정성 트랙: contact sheet 입력 + Claude 구독. Gemini 영상")
    print("     네이티브 정량 baseline 아님 (모델·입력 둘 다 다름).")
    print("=" * 62)
    print(f"raw 정확도       : {raw}/{n} = {raw / n:.1%}")
    print(f"feeding-merged   : {merged}/{n} = {merged / n:.1%}")
    print()
    print("클래스별 정확도(raw):")
    for k in sorted(by_gt, key=lambda x: -by_gt[x]["t"]):
        b = by_gt[k]
        print(f"  {k:13s} {b['c']:2d}/{b['t']:2d} = {b['c'] / b['t']:.0%}")
    print()
    print(f"★ hand_feeding OOD recall: {ood_rec}/{len(ood)} = {ood_rec / len(ood):.1%}")
    print("   (v3.5 는 클래스 자체가 없어 구조적 0 → v3.6 순수 이득)")
    print()
    # hard negative false-positive 게이트
    hn = next((r for r in rows if "not-drinking" in r["sample"]), None)
    if hn:
        fp = "✅ moving (false-positive 안 냄)" if hn["pred"] == "moving" else f"❌ {hn['pred']} (오탐!)"
        print(f"★ hard negative (not-drinking→GT moving): pred={hn['pred']} → {fp}")
    print()
    print("혼동 패턴:")
    for k, v in confusion.most_common():
        print(f"  {v}x  {k}")
    print()
    print(f"오답 {len(errors)}건 상세 (conf 순):")
    for r in sorted(errors, key=lambda x: -x["conf"]):
        print(f"  {r['sample'][7:]:38s} GT={r['gt']:12s} → {r['pred']:12s} conf={r['conf']}")


if __name__ == "__main__":
    main()

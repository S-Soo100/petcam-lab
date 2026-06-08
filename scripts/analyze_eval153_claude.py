"""153건 Claude blind 통합 분석 + GT 검수 — 적합 5클래스 (44 eval-0608 + 109 eval-159).

미세/순간 행동(shedding/defecating/hiding/unseen 50건)은 파일럿서 contact sheet 불가
확정 → 제외. 적합 클래스(moving/hand_feeding/eating_prey/drinking/eating_paste)만.

GT 검수 분류:
- 라벨오류 후보: pred≠GT AND conf≥0.7 (2961형 — confident 반박). 사람 재확인 대상.
- contact sheet 한계: pred=moving AND conf<0.6 (저conf 과소). 입력 한계로 분류.

실행: PYTHONPATH=. uv run python scripts/analyze_eval153_claude.py
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCES = [
    ("eval-0608-claude", "claude_v36_blind.jsonl"),   # 44건 (sample 이름 = sample-{filename})
    ("eval-159-claude", "eval159_blind.jsonl"),         # 109건 (sample 이름 = sample-{clip_short})
]
FEEDING_MERGE = {"drinking": "feeding", "eating_paste": "feeding"}


def merge(a: str) -> str:
    return FEEDING_MERGE.get(a, a)


def main() -> None:
    rows = []
    for folder, jsonl in SOURCES:
        base = REPO / "experiments" / folder
        jpath = base / jsonl
        if not jpath.exists():
            print(f"⚠️ {jsonl} 없음 — {folder} 건너뜀 (blind 평가 아직?)")
            continue
        preds = {}
        for line in jpath.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            preds[r["sample"]] = r
        for d in sorted(base.glob("sample-*")):
            meta = json.loads((d / "meta.json").read_text())
            if d.name not in preds:
                continue
            p = preds[d.name]
            rows.append({
                "sample": d.name, "gt": meta["gt"], "pred": p["pred"],
                "conf": p.get("conf", 0.0), "reasoning": p.get("reasoning", ""),
                "src": folder,
            })

    n = len(rows)
    if not n:
        print("집계할 행 없음 (blind jsonl 둘 다 없음)")
        return

    raw = sum(1 for r in rows if r["gt"] == r["pred"])
    merged = sum(1 for r in rows if merge(r["gt"]) == merge(r["pred"]))
    by_gt: dict[str, dict[str, int]] = defaultdict(lambda: {"c": 0, "t": 0})
    for r in rows:
        by_gt[r["gt"]]["t"] += 1
        if r["gt"] == r["pred"]:
            by_gt[r["gt"]]["c"] += 1
    ood = [r for r in rows if r["gt"] == "hand_feeding"]
    ood_rec = sum(1 for r in ood if r["pred"] == "hand_feeding")

    errors = [r for r in rows if r["gt"] != r["pred"]]
    label_suspects = [r for r in errors if r["conf"] >= 0.7]      # confident 반박 = 라벨오류 후보
    sheet_limit = [r for r in errors if r["pred"] == "moving" and r["conf"] < 0.6]
    other_err = [r for r in errors if r not in label_suspects and r not in sheet_limit]

    print("=" * 64)
    print(f"153건 Claude blind 통합 — 적합 5클래스 (N={n})")
    print("  미세행동(shedding/defecating/hiding/unseen) 제외 = contact sheet 불가")
    print("=" * 64)
    print(f"raw 정확도      : {raw}/{n} = {raw / n:.1%}")
    print(f"feeding-merged  : {merged}/{n} = {merged / n:.1%}")
    print()
    print("클래스별(raw):")
    for k in sorted(by_gt, key=lambda x: -by_gt[x]["t"]):
        b = by_gt[k]
        print(f"  {k:13s} {b['c']:3d}/{b['t']:3d} = {b['c'] / b['t']:.0%}")
    if ood:
        print(f"\n★ hand_feeding OOD recall: {ood_rec}/{len(ood)} = {ood_rec / len(ood):.1%}")
    print("\n혼동 패턴:")
    conf_cnt: Counter = Counter(f"{r['gt']:13s} → {r['pred']}" for r in errors)
    for k, v in conf_cnt.most_common():
        print(f"  {v}x  {k}")

    print("\n" + "=" * 64)
    print(f"★ GT 검수 — 라벨오류 후보 {len(label_suspects)}건 (conf≥0.7 confident 반박, 2961형)")
    print("=" * 64)
    for r in sorted(label_suspects, key=lambda x: -x["conf"]):
        print(f"  {r['sample']:28s} GT={r['gt']:12s} → {r['pred']:12s} conf={r['conf']}")
        print(f"      \"{r['reasoning'][:110]}\"")
    print(f"\ncontact sheet 한계(저conf →moving): {len(sheet_limit)}건")
    print(f"기타 오답: {len(other_err)}건")


if __name__ == "__main__":
    main()

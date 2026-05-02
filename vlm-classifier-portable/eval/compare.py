"""두 jsonl 비교 — 5-카테고리 분석 (held-correct/recovered/broken/still-wrong-same/still-wrong-changed).

사용:
  uv run python eval/compare.py \
    --baseline data/eval-159.jsonl \
    --new my-new-results.jsonl \
    --gt data/gt-159.jsonl \
    --classes data/classes.json

채택 기준 (CHALLENGE.md §5):
  - Δ > +3.0%p (feeding-merged eval 기준) AND
  - recovered > broken

자기충족: stdlib만.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# analyze.py 에서 매퍼/로더 재사용
from analyze import (
    make_mappers,
    load_eval,
    load_gt,
    accuracy,
)


def categorize(
    baseline: dict[str, dict],
    new: dict[str, dict],
    gt: dict[str, str],
    mapper: callable,
) -> dict[str, list[dict]]:
    """5-카테고리 분류.

    held-correct:        둘 다 정답
    recovered:           baseline 오답 → new 정답
    broken:              baseline 정답 → new 오답
    still-wrong-same:    둘 다 오답, 같은 라벨
    still-wrong-changed: 둘 다 오답, 다른 라벨
    missing:             new 결과 없는 클립 (분석에서 제외)
    """
    cats: dict[str, list[dict]] = {
        "held-correct": [],
        "recovered": [],
        "broken": [],
        "still-wrong-same": [],
        "still-wrong-changed": [],
        "missing": [],
    }

    for cid, gt_action in gt.items():
        if cid not in baseline:
            continue  # baseline 자체에 없는 건 비교 불가
        gt_mapped = mapper(gt_action)
        b_action = baseline[cid].get("action")
        b_mapped = mapper(b_action)

        if cid not in new:
            cats["missing"].append({
                "clip_id": cid,
                "gt": gt_action,
                "baseline": b_action,
            })
            continue

        n_action = new[cid].get("action")
        n_mapped = mapper(n_action)

        b_correct = (b_mapped == gt_mapped)
        n_correct = (n_mapped == gt_mapped)

        entry = {
            "clip_id": cid,
            "gt": gt_action,
            "gt_mapped": gt_mapped,
            "baseline": b_action,
            "baseline_mapped": b_mapped,
            "new": n_action,
            "new_mapped": n_mapped,
        }

        if b_correct and n_correct:
            cats["held-correct"].append(entry)
        elif not b_correct and n_correct:
            cats["recovered"].append(entry)
        elif b_correct and not n_correct:
            cats["broken"].append(entry)
        elif b_mapped == n_mapped:
            cats["still-wrong-same"].append(entry)
        else:
            cats["still-wrong-changed"].append(entry)

    return cats


def print_summary(cats: dict[str, list[dict]], delta_pp: float) -> None:
    """5-카테고리 요약 출력."""
    print(f"\n## 5-카테고리 분석")
    total = sum(len(v) for k, v in cats.items() if k != "missing")
    for name in ["held-correct", "recovered", "broken", "still-wrong-same", "still-wrong-changed"]:
        n = len(cats[name])
        pct = n / total * 100 if total else 0
        print(f"  {name:24s} {n:>4d} ({pct:5.1f}%)")
    if cats["missing"]:
        print(f"  {'(missing in new)':24s} {len(cats['missing']):>4d}")
    print(f"  {'TOTAL':24s} {total:>4d}")

    print(f"\n## 채택 권장 판정")
    recovered = len(cats["recovered"])
    broken = len(cats["broken"])
    print(f"  Δ vs baseline: {delta_pp:+.2f}%p")
    print(f"  recovered={recovered} / broken={broken} (recovered-broken={recovered-broken:+d})")

    delta_pass = delta_pp > 3.0
    rb_pass = recovered > broken
    print(f"  Δ > +3.0%p:        {'PASS' if delta_pass else 'FAIL'}")
    print(f"  recovered > broken: {'PASS' if rb_pass else 'FAIL'}")
    print(f"\n  → 채택 권장: {'YES' if (delta_pass and rb_pass) else 'NO'}")


def print_details(cats: dict[str, list[dict]], top_n: int = 10) -> None:
    """카테고리별 상세 출력 (recovered/broken 위주)."""
    for name in ["recovered", "broken", "still-wrong-changed"]:
        items = cats[name]
        if not items:
            continue
        print(f"\n## {name} 상세 (max {top_n})")
        for e in items[:top_n]:
            print(f"  {e['clip_id'][:8]} GT={e['gt']:14s} "
                  f"base={e['baseline']:14s} → new={e['new']}")


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description="두 jsonl 비교 — 5-카테고리 분석")
    p.add_argument("--baseline", type=Path, required=True, help="baseline jsonl (보통 v3.5)")
    p.add_argument("--new", type=Path, required=True, help="새 시도 jsonl")
    p.add_argument("--gt", type=Path, default=here / "data" / "gt-159.jsonl")
    p.add_argument("--classes", type=Path, default=here / "data" / "classes.json")
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--export", type=Path, default=None,
                   help="카테고리별 jsonl 저장")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    _, to_eval = make_mappers(args.classes)

    baseline = load_eval(args.baseline)
    new = load_eval(args.new)
    gt = load_gt(args.gt)

    print(f"baseline: {len(baseline)}건 ({args.baseline.name})")
    print(f"new:      {len(new)}건 ({args.new.name})")
    print(f"GT:       {len(gt)}건")

    # 정확도 (eval-merged 기준)
    b_correct, b_total = accuracy(baseline, gt, to_eval)
    n_correct, n_total = accuracy(new, gt, to_eval)
    b_acc = b_correct / b_total * 100 if b_total else 0
    n_acc = n_correct / n_total * 100 if n_total else 0
    delta = n_acc - b_acc

    print(f"\n## 정확도 (eval-merged: feeding + hiding→moving)")
    print(f"  baseline: {b_correct}/{b_total} = {b_acc:.2f}%")
    print(f"  new:      {n_correct}/{n_total} = {n_acc:.2f}%")
    print(f"  Δ:        {delta:+.2f}%p")

    cats = categorize(baseline, new, gt, to_eval)
    print_summary(cats, delta)
    print_details(cats, args.top_n)

    if args.export:
        args.export.parent.mkdir(parents=True, exist_ok=True)
        for name, items in cats.items():
            out = args.export.parent / f"{args.export.stem}-{name}.jsonl"
            with out.open("w", encoding="utf-8") as f:
                for e in items:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            print(f"  saved: {out} ({len(items)}건)")


if __name__ == "__main__":
    main()

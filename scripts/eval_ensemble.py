"""여러 모델의 jsonl 결과를 ensemble voting으로 합쳐서 정확도 측정.

Strategy: 같은 P0 평가셋에 대한 여러 모델 결과 jsonl을 majority vote 또는
confidence-weighted vote로 합치고, 최종 정확도가 single best model보다 높은지 확인.

실행:
    uv run python scripts/eval_ensemble.py \\
        storage/track-a-eval/multi-strategy/A-minicpm-v-97p0.jsonl \\
        storage/track-a-eval/multi-strategy/A-gemma3-4b-97p0.jsonl \\
        storage/track-a-eval/multi-strategy/D-minicpm-v-97p0.jsonl \\
        --method weighted
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_results(jsonl_path: Path) -> dict[str, dict]:
    """clip_id → {predicted_label, confidence, gt_action}."""
    rows: dict[str, dict] = {}
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not rec.get("ok"):
            continue
        rows[rec["clip_id"]] = {
            "predicted_label": rec["predicted_label"],
            "confidence": float(rec.get("confidence", 0.0)),
            "gt_action": rec["gt_action"],
        }
    return rows


def majority_vote(predictions: list[dict]) -> tuple[str, float]:
    """단순 다수결. 동률 시 가장 confidence 높은 거."""
    if not predictions:
        return "moving", 0.0
    counter = Counter(p["predicted_label"] for p in predictions)
    most_common = counter.most_common()
    top_count = most_common[0][1]
    candidates = [lbl for lbl, c in most_common if c == top_count]
    if len(candidates) == 1:
        winner = candidates[0]
    else:
        # 동률 → 후보들 중 confidence 합 max
        scores = {
            lbl: sum(p["confidence"] for p in predictions if p["predicted_label"] == lbl)
            for lbl in candidates
        }
        winner = max(scores, key=scores.get)
    avg_conf = sum(p["confidence"] for p in predictions if p["predicted_label"] == winner) / counter[winner]
    return winner, avg_conf


def weighted_vote(predictions: list[dict]) -> tuple[str, float]:
    """confidence 가중 vote — 라벨별 confidence 합 max."""
    if not predictions:
        return "moving", 0.0
    scores: dict[str, float] = defaultdict(float)
    for p in predictions:
        scores[p["predicted_label"]] += p["confidence"]
    winner = max(scores, key=scores.get)
    total = sum(scores.values())
    norm_conf = scores[winner] / total if total > 0 else 0.0
    return winner, norm_conf


def p0_priority_vote(predictions: list[dict]) -> tuple[str, float]:
    """P0 라벨이 하나라도 있으면 P0 우선. 여러 P0면 confidence 가중.
    이유: false negative (P0 → moving)를 줄이는 게 false positive보다 중요.
    """
    P0 = {"drinking", "eating_paste", "eating_prey", "defecating", "shedding"}
    p0_preds = [p for p in predictions if p["predicted_label"] in P0]
    if not p0_preds:
        return weighted_vote(predictions)
    return weighted_vote(p0_preds)


METHODS = {
    "majority": majority_vote,
    "weighted": weighted_vote,
    "p0_priority": p0_priority_vote,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("jsonls", nargs="+", type=Path, help="결과 jsonl 파일들")
    parser.add_argument("--method", choices=list(METHODS), default="weighted")
    args = parser.parse_args()

    all_results: dict[str, list[dict]] = defaultdict(list)
    gt_map: dict[str, str] = {}
    for jp in args.jsonls:
        if not jp.exists():
            print(f"WARN: {jp} 없음, skip")
            continue
        results = load_results(jp)
        print(f"{jp.name}: {len(results)} clip")
        for clip_id, r in results.items():
            all_results[clip_id].append(r)
            gt_map[clip_id] = r["gt_action"]

    method_func = METHODS[args.method]
    correct = 0
    total = 0
    by_gt: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
    pred_dist: dict[str, int] = defaultdict(int)
    confusion: list[tuple[str, str, str]] = []

    for clip_id, preds in all_results.items():
        if len(preds) < 2:
            continue  # ensemble은 2개 이상 모델 필요
        gt = gt_map[clip_id]
        winner, conf = method_func(preds)
        total += 1
        by_gt[gt]["total"] += 1
        pred_dist[winner] += 1
        if winner == gt:
            correct += 1
            by_gt[gt]["correct"] += 1
        else:
            confusion.append((clip_id, gt, winner))

    if not total:
        print("ensemble 가능한 clip 없음 (각 jsonl이 같은 clip을 평가해야 함)")
        return 1

    print()
    print("=" * 72)
    print(f"Ensemble ({args.method}) 결과 — N={total}, 모델 {len(args.jsonls)}개")
    print("=" * 72)
    acc = correct / total
    print(f"정확도: {correct}/{total} = {acc:.1%}  목표 90%: {'✅' if acc >= 0.90 else '❌'}")
    print()
    print("per-class:")
    for gt in sorted(by_gt):
        b = by_gt[gt]
        print(f"  {gt:14s} {b['correct']:3d}/{b['total']:3d} = {b['correct']/b['total']:.0%}")
    print()
    print("예측 분포:")
    for p in sorted(pred_dist):
        print(f"  {p:14s} {pred_dist[p]:3d}")
    print()
    if confusion:
        print(f"오답 {len(confusion)}건:")
        for clip_id, gt, pred in confusion[:30]:
            print(f"  {clip_id[:8]} GT={gt:13s} → {pred}")
        if len(confusion) > 30:
            print(f"  ... +{len(confusion)-30}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

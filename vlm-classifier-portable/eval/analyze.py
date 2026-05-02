"""평가 jsonl 분석 — 정확도 + confusion matrix + mismatch 리스트.

사용:
  uv run python eval/analyze.py \
    --eval data/eval-159.jsonl \
    --gt data/gt-159.jsonl \
    --classes data/classes.json

출력:
  - 3가지 정확도 (raw / feeding-merged UI / feeding+hiding-merge eval)
  - 클래스 별 confusion matrix
  - mismatch 리스트 (clip_id, GT, pred, reasoning)

자기충족: stdlib 만 사용 (numpy 불필요).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


# -----------------------------------------------------------------------------
# 매핑 함수 (classes.json mappings.* 적용)
# -----------------------------------------------------------------------------
def make_mappers(classes_path: Path) -> tuple[callable, callable]:
    """classes.json 읽어서 to_ui / to_eval 매퍼 반환.

    to_ui: raw → feeding-merged (drinking/eating_paste → feeding)
    to_eval: to_ui + eval-only-extra (hiding → moving)
    """
    data = json.loads(classes_path.read_text(encoding="utf-8"))
    raw_to_ui = data["mappings"]["raw_to_ui"]["rules"]
    eval_extra = data["mappings"]["eval_only_extra"]["rules"]

    def to_ui(action: str | None) -> str | None:
        if action is None:
            return None
        return raw_to_ui.get(action, action)

    def to_eval(action: str | None) -> str | None:
        if action is None:
            return None
        ui = to_ui(action)
        return eval_extra.get(ui, ui)

    return to_ui, to_eval


# -----------------------------------------------------------------------------
# 데이터 로딩
# -----------------------------------------------------------------------------
def load_eval(path: Path) -> dict[str, dict]:
    """eval-N.jsonl → {clip_id: record}. ok=True 만."""
    out: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("ok") and r.get("action"):
            out[r["clip_id"]] = r
    return out


def load_gt(path: Path) -> dict[str, str]:
    """gt-N.jsonl → {clip_id: gt_action}."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            out[r["clip_id"]] = r["gt_action"]
        except (json.JSONDecodeError, KeyError):
            continue
    return out


# -----------------------------------------------------------------------------
# 정확도 측정
# -----------------------------------------------------------------------------
def accuracy(eval_records: dict[str, dict], gt: dict[str, str], mapper: callable) -> tuple[int, int]:
    """매퍼 적용 후 일치 건수 / 전체 건수."""
    correct = total = 0
    for cid, rec in eval_records.items():
        if cid not in gt:
            continue
        total += 1
        if mapper(rec["action"]) == mapper(gt[cid]):
            correct += 1
    return correct, total


# -----------------------------------------------------------------------------
# Confusion matrix
# -----------------------------------------------------------------------------
def confusion_matrix(eval_records: dict[str, dict], gt: dict[str, str], mapper: callable) -> dict:
    """{(gt_class, pred_class): count}."""
    cm: dict[tuple[str, str], int] = defaultdict(int)
    for cid, rec in eval_records.items():
        if cid not in gt:
            continue
        cm[(mapper(gt[cid]), mapper(rec["action"]))] += 1
    return dict(cm)


def print_confusion(cm: dict[tuple[str, str], int], title: str) -> None:
    """confusion matrix 텍스트 출력 (행=GT, 열=pred)."""
    classes = sorted({c for pair in cm.keys() for c in pair})
    print(f"\n## Confusion Matrix — {title}")
    print(f"{'GT \\ pred':>14s} | " + " ".join(f"{c[:10]:>10s}" for c in classes))
    print("-" * (16 + 11 * len(classes)))
    for gt_cls in classes:
        row = [cm.get((gt_cls, p), 0) for p in classes]
        print(f"{gt_cls[:14]:>14s} | " + " ".join(f"{v:>10d}" for v in row))


# -----------------------------------------------------------------------------
# Mismatch 리스트
# -----------------------------------------------------------------------------
def list_mismatches(
    eval_records: dict[str, dict],
    gt: dict[str, str],
    mapper: callable,
    top_n: int | None = None,
) -> list[dict]:
    """mismatch 클립 — (gt, pred, confidence, reasoning)."""
    out: list[dict] = []
    for cid, rec in eval_records.items():
        if cid not in gt:
            continue
        gt_mapped = mapper(gt[cid])
        pred_mapped = mapper(rec["action"])
        if gt_mapped != pred_mapped:
            out.append({
                "clip_id": cid,
                "gt": gt[cid],
                "gt_mapped": gt_mapped,
                "pred": rec["action"],
                "pred_mapped": pred_mapped,
                "confidence": rec.get("confidence", 0),
                "reasoning": rec.get("reasoning", ""),
            })
    out.sort(key=lambda r: r["confidence"] or 0, reverse=True)
    return out if top_n is None else out[:top_n]


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description="평가 jsonl 분석 — 정확도 + confusion + mismatch")
    p.add_argument("--eval", type=Path, default=here / "data" / "eval-159.jsonl")
    p.add_argument("--gt", type=Path, default=here / "data" / "gt-159.jsonl")
    p.add_argument("--classes", type=Path, default=here / "data" / "classes.json")
    p.add_argument("--mismatches", type=int, default=20, help="mismatch top-N 출력")
    p.add_argument("--confusion", action="store_true", help="confusion matrix 출력")
    p.add_argument("--export-mismatches", type=Path, default=None,
                   help="mismatch jsonl 저장 (분석용)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    to_ui, to_eval = make_mappers(args.classes)

    eval_recs = load_eval(args.eval)
    gt = load_gt(args.gt)

    print(f"평가 레코드: {len(eval_recs)}")
    print(f"GT 레코드:   {len(gt)}")
    overlap = set(eval_recs) & set(gt)
    print(f"교집합:      {len(overlap)}")

    if not overlap:
        print("ERROR: clip_id 교집합 없음. eval/gt 파일 확인.")
        raise SystemExit(1)

    # 3가지 정확도
    print(f"\n## 정확도")
    raw_correct, raw_total = accuracy(eval_recs, gt, lambda x: x)
    ui_correct, ui_total = accuracy(eval_recs, gt, to_ui)
    eval_correct, eval_total = accuracy(eval_recs, gt, to_eval)
    print(f"  raw 9-class:           {raw_correct}/{raw_total} = {raw_correct/raw_total*100:.1f}%")
    print(f"  feeding-merged (UI):   {ui_correct}/{ui_total} = {ui_correct/ui_total*100:.1f}%")
    print(f"  + hiding→moving (eval): {eval_correct}/{eval_total} = {eval_correct/eval_total*100:.1f}%")
    print(f"  → v3.5 production baseline: 85.5% (136/159) — 비교 기준")

    # GT 클래스 분포
    print(f"\n## GT 클래스 분포")
    for cls, n in Counter(gt[c] for c in overlap).most_common():
        print(f"  {cls:14s} {n:>3d}")

    if args.confusion:
        cm_eval = confusion_matrix(eval_recs, gt, to_eval)
        print_confusion(cm_eval, "feeding+hiding-merge (eval baseline)")

    # mismatches
    print(f"\n## Mismatch top-{args.mismatches} (eval-merged 기준, confidence 내림차순)")
    mismatches = list_mismatches(eval_recs, gt, to_eval, top_n=args.mismatches)
    print(f"총 mismatch: {len(list_mismatches(eval_recs, gt, to_eval))}")
    for m in mismatches:
        reason = m["reasoning"][:80].replace("\n", " ")
        print(f"  {m['clip_id'][:8]} GT={m['gt']:14s} → pred={m['pred']:14s} "
              f"(conf={m['confidence']:.2f}) {reason}")

    if args.export_mismatches:
        all_mismatches = list_mismatches(eval_recs, gt, to_eval)
        args.export_mismatches.parent.mkdir(parents=True, exist_ok=True)
        with args.export_mismatches.open("w", encoding="utf-8") as f:
            for m in all_mismatches:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
        print(f"\nmismatch jsonl: {args.export_mismatches} ({len(all_mismatches)}건)")


if __name__ == "__main__":
    main()

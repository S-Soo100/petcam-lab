"""채점 — TEST-SHEET §6 지표 · §7 게이트 · §5-3 결합 룰 · §9 decision.

급여경계 논리는 v4.0 회귀(`scripts/_score_v40.py`)와 같은 정의를 쓴다. 다른 점 하나: arm B 는 drinking 과
eating_paste 를 못 가르므로 `feeding` 묶음 라벨을 내고, 급여경계 채점은 그 묶음을 급여로 인정한다.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from scripts._score_v40 import FEEDING
from scripts.nonvlm_behavior_v0.rules import (
    R1_AREA_JUMP,
    R1_GLOBAL_CHANGE_FRAMES,
    R2_HEAD_MICRO,
    R2_STATIC_SEC,
)

FEEDING_BUNDLE = "feeding"

# 시험지 §7 게이트 숫자 (사후 변경 금지)
GATE_MOVING_RECALL = 0.90
GATE_HAND_FEEDING_RECALL = 0.80
GATE_FEEDING_RECALL_MARGIN = 0.10
GATE_FEEDING_FP_RATE = 0.10
C1_MIN_STATIC_SEC = 3.0


def is_feeding(label: str | None) -> bool:
    return label is not None and (label in FEEDING or label == FEEDING_BUNDLE)


def merge_feeding(label: str) -> str:
    return FEEDING_BUNDLE if label in FEEDING else label


def boundary_correct(pred: str | None, gt: str) -> bool:
    """GT 가 급여면 예측이 급여(묶음 포함)이기만 하면 정답, 비급여는 정확 일치."""
    if pred is None:
        return False
    if gt in FEEDING:
        return is_feeding(pred)
    return pred == gt


def class_recall(pred: dict[str, str], gt: dict[str, str], cls: str) -> tuple[int, int]:
    keys = [k for k, g in gt.items() if g == cls]
    return sum(1 for k in keys if pred.get(k) == cls), len(keys)


def feeding_recall(pred: dict[str, str], gt: dict[str, str]) -> tuple[int, int]:
    keys = [k for k, g in gt.items() if g in FEEDING]
    return sum(1 for k in keys if is_feeding(pred.get(k))), len(keys)


def feeding_false_positives(pred: dict[str, str], gt: dict[str, str]) -> tuple[int, int]:
    keys = [k for k, g in gt.items() if g not in FEEDING]
    return sum(1 for k in keys if is_feeding(pred.get(k))), len(keys)


def complementarity(a: dict[str, str], b: dict[str, str], gt: dict[str, str]) -> dict[str, int]:
    cells = Counter()
    for k, g in gt.items():
        ca, cb = boundary_correct(a.get(k), g), boundary_correct(b.get(k), g)
        cells["both" if ca and cb else "a_only" if ca else "b_only" if cb else "neither"] += 1
    return {name: cells.get(name, 0) for name in ("both", "a_only", "b_only", "neither")}


def _r1(f: dict) -> bool:
    return f["global_change_frames"] >= R1_GLOBAL_CHANGE_FRAMES and f["bbox_area_jump"] >= R1_AREA_JUMP


def _r2(f: dict) -> bool:
    return f["longest_static_sec"] >= R2_STATIC_SEC and f["head_micro"] >= R2_HEAD_MICRO


def fuse_c(a: str, f: dict) -> str:
    """§5-3 결합 룰: C1 정지 없는 급여 강등 → C2 R2 승격 → C3 R1 손급여 → 그 외 A 유지."""
    if a in FEEDING and f["longest_static_sec"] < C1_MIN_STATIC_SEC:
        return "moving"
    if a == "moving" and _r2(f):
        return FEEDING_BUNDLE
    if a != "hand_feeding" and _r1(f):
        return "hand_feeding"
    return a


def paired_boundary(a: dict[str, str], c: dict[str, str], gt: dict[str, str]):
    recovered, broken, harmless = [], [], []
    for k, g in gt.items():
        pa, pc = a.get(k), c.get(k)
        if pa is None or pc is None:
            continue
        ca, cc = boundary_correct(pa, g), boundary_correct(pc, g)
        if cc and not ca:
            recovered.append((k, g, pa, pc))
        elif ca and not cc:
            broken.append((k, g, pa, pc))
        elif pa != pc and g in FEEDING and is_feeding(pa) and is_feeding(pc):
            harmless.append((k, g, pa, pc))
    return recovered, broken, harmless


def per_class(pred: dict[str, str], gt: dict[str, str], *, merge: bool) -> dict[str, dict]:
    """클래스별 recall/precision + 혼동행렬. merge=True 면 GT·예측 모두 급여 묶음으로 본다."""
    g_map = {k: (merge_feeding(v) if merge else v) for k, v in gt.items()}
    p_map = {k: (merge_feeding(pred[k]) if merge and pred.get(k) else pred.get(k)) for k in gt}
    confusion: dict[str, Counter] = defaultdict(Counter)
    for k, g in g_map.items():
        confusion[g][p_map.get(k) or "(none)"] += 1
    out = {}
    for cls in sorted(set(g_map.values()) | {v for v in p_map.values() if v}):
        tp = sum(1 for k, g in g_map.items() if g == cls and p_map.get(k) == cls)
        total = sum(1 for g in g_map.values() if g == cls)
        predicted = sum(1 for v in p_map.values() if v == cls)
        out[cls] = {
            "recall": (tp / total) if total else None, "precision": (tp / predicted) if predicted else None,
            "tp": tp, "gt_total": total, "predicted": predicted, "confusion": dict(confusion.get(cls, {})),
        }
    return out


def evaluate(gt: dict[str, str], a: dict[str, str], b: dict[str, str], feats: dict[str, dict]) -> dict:
    n = len(gt)
    mov_hit, mov_tot = class_recall(b, gt, "moving")
    hf_hit, hf_tot = class_recall(b, gt, "hand_feeding")
    fa_hit, f_tot = feeding_recall(a, gt)
    fb_hit, _ = feeding_recall(b, gt)
    fp_hit, fp_tot = feeding_false_positives(b, gt)
    recall_a = fa_hit / f_tot if f_tot else 0.0
    recall_b = fb_hit / f_tot if f_tot else 0.0
    fp_rate = fp_hit / fp_tot if fp_tot else 0.0

    c = {k: fuse_c(a[k], feats[k]) for k in gt if k in a and k in feats}
    acc_a = sum(1 for k, g in gt.items() if boundary_correct(a.get(k), g)) / n
    acc_b = sum(1 for k, g in gt.items() if boundary_correct(b.get(k), g)) / n
    acc_c = sum(1 for k, g in gt.items() if boundary_correct(c.get(k), g)) / n
    raw6_b = sum(1 for k, g in gt.items() if b.get(k) == merge_feeding(g)) / n
    recovered, broken, harmless = paired_boundary(a, c, gt)

    gates = {
        "G_B1_moving_recall": (mov_hit / mov_tot if mov_tot else 0.0) >= GATE_MOVING_RECALL,
        "G_B2_hand_feeding_recall": (hf_hit / hf_tot if hf_tot else 0.0) >= GATE_HAND_FEEDING_RECALL,
        "G_B3_feeding_recall_vs_A": recall_b >= recall_a - GATE_FEEDING_RECALL_MARGIN - 1e-12,
        "G_B4_feeding_fp": fp_rate <= GATE_FEEDING_FP_RATE + 1e-12,
        "G_C": acc_c >= acc_a - 1e-12 and len(recovered) >= len(broken),
    }
    if not (gates["G_B1_moving_recall"] and gates["G_B2_hand_feeding_recall"]):
        decision_b = "reject"
    elif gates["G_B3_feeding_recall_vs_A"] and gates["G_B4_feeding_fp"]:
        decision_b = "adopt"
    else:
        decision_b = "hold"

    disagreements = []
    for k, g in gt.items():
        a_ok, b_ok = boundary_correct(a.get(k), g), boundary_correct(b.get(k), g)
        if a_ok != b_ok:
            disagreements.append({"key": k, "gt": g, "A": a.get(k), "B": b.get(k), "A_ok": a_ok, "B_ok": b_ok})

    return {
        "n": n,
        "disagreements": disagreements,
        "moving_recall_B": (mov_hit, mov_tot),
        "hand_feeding_recall_B": (hf_hit, hf_tot),
        "feeding_recall_A": (fa_hit, f_tot),
        "feeding_recall_B": (fb_hit, f_tot),
        "feeding_fp_B": (fp_hit, fp_tot),
        "boundary_acc": {"A": acc_a, "B": acc_b, "C": acc_c},
        "raw6_acc_B": raw6_b,
        "complementarity": complementarity(a, b, gt),
        "paired_A_to_C": {"recovered": recovered, "broken": broken, "harmless": harmless},
        "per_class_A": per_class(a, gt, merge=False),
        "per_class_B": per_class(b, gt, merge=True),
        "gates": gates,
        "decision_B": decision_b,
        "c_predictions": c,
    }

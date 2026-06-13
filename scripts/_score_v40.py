"""v4.0 회귀 채점 — raw/ 예측 + meta GT 대조 + 급여경계 paired 분석.

시험지(experiments/v40-regression/TEST-SHEET.md §5) 게이트를 그대로 구현:
- raw 정확도(7-class 엄격) = 정직 보고
- 급여경계 정확도 = GT가 급여(drinking/eating_paste)면 예측이 급여이기만 하면 정답
  (drinking↔eating_paste 내부 혼동은 무해 — 사용자 결정 2026-06-13)
- 급여경계 paired recovered/broken (주 게이트: recovered ≥ broken)
- drinking 비급여 누출 / moving→drinking 과탐

실행: PYTHONPATH=. uv run python scripts/_score_v40.py
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIR = REPO / "experiments" / "v40-regression"
FRAMES = DIR / "frames"
RAW = DIR / "raw"

FEEDING = {"drinking", "eating_paste"}  # 급여 무해 그룹 (둘 사이 혼동 = 무해)


def load_gt() -> dict[str, str]:
    return {
        m.parent.name: json.loads(m.read_text())["gt"]
        for m in sorted(FRAMES.glob("sample-*/meta.json"))
    }


def load_preds(version: str) -> dict[str, str]:
    """raw/{version}_g*.json 모음 → {sample: action}. 방어적 파싱."""
    preds: dict[str, str] = {}
    for f in sorted(RAW.glob(f"{version}_g*.json")):
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError as e:
            print(f"  ⚠️ 파싱 실패 {f.name}: {e}")
            continue
        for r in data.get("results", []):
            if "sample" in r and "action" in r:
                preds[r["sample"]] = r["action"]
    return preds


def boundary_correct(pred: str | None, g: str) -> bool:
    """급여경계 정답: GT가 급여면 예측이 급여이기만 하면 OK, 비급여는 정확히 일치."""
    if pred is None:
        return False
    if g in FEEDING:
        return pred in FEEDING
    return pred == g


def main() -> int:
    gt = load_gt()
    v361 = load_preds("v3.6.1")
    v40 = load_preds("v4.0")
    n = len(gt)

    print(f"=== 로드 (GT {n}건) ===")
    for name, p in [("v3.6.1", v361), ("v4.0", v40)]:
        miss = sorted(set(gt) - set(p))
        print(f"  {name}: 예측 {len(p)}건" + (f" · ⚠️ 누락 {len(miss)}: {miss[:8]}" if miss else " · 누락 0"))

    # ── 정확도 (raw 엄격 + 급여경계) ──
    def acc(p: dict[str, str]) -> tuple[int, int]:
        raw = sum(1 for s, g in gt.items() if p.get(s) == g)
        bnd = sum(1 for s, g in gt.items() if boundary_correct(p.get(s), g))
        return raw, bnd

    r0, b0 = acc(v361)
    r1, b1 = acc(v40)
    print(f"\n=== 정확도 (N={n}) ===")
    print(f"  v3.6.1 : raw {r0}/{n}={r0/n:.1%} · 급여경계 {b0}/{n}={b0/n:.1%}")
    print(f"  v4.0   : raw {r1}/{n}={r1/n:.1%} · 급여경계 {b1}/{n}={b1/n:.1%}")
    print(f"  Δ      : raw {(r1-r0)/n*100:+.1f}%p · 급여경계 {(b1-b0)/n*100:+.1f}%p")
    print(f"  폭락가드(raw −5%p): {'⚠️ 폭락' if (r1-r0)/n < -0.05 else 'OK'}")

    # ── 급여경계 paired ──
    recovered, broken, harmless = [], [], []
    for s, g in gt.items():
        a0, a1 = v361.get(s), v40.get(s)
        if a0 is None or a1 is None:
            continue
        bc0, bc1 = boundary_correct(a0, g), boundary_correct(a1, g)
        if bc0 and not bc1:
            broken.append((s, g, a0, a1))
        elif bc1 and not bc0:
            recovered.append((s, g, a0, a1))
        elif a0 != a1 and g in FEEDING and a0 in FEEDING and a1 in FEEDING:
            harmless.append((s, g, a0, a1))

    print(f"\n=== 급여경계 paired (v3.6.1→v4.0) ===")
    print(f"  recovered {len(recovered)} · broken {len(broken)} · 무해(급여내부) {len(harmless)}")
    gate = "✅ PASS" if len(recovered) >= len(broken) else "❌ FAIL"
    print(f"  주 게이트 (recovered ≥ broken): {gate}")
    for tag, lst in [("recovered", recovered), ("broken", broken), ("무해", harmless)]:
        for s, g, a0, a1 in lst:
            print(f"    [{tag}] {s} GT={g}: {a0} → {a1}")

    # ── drinking 비급여 누출 ──
    def leak(p):
        return sorted(s for s, g in gt.items() if g == "drinking" and p.get(s) and p[s] not in FEEDING)

    l0, l1 = leak(v361), leak(v40)
    print(f"\n=== drinking 비급여 누출 (GT=drinking → moving 등) ===")
    print(f"  v3.6.1: {len(l0)}건 {l0}")
    print(f"  v4.0  : {len(l1)}건 {l1}")
    print(f"  목표(비증가): {'✅' if len(l1) <= len(l0) else '⚠️ 증가'}")

    # ── moving→drinking 과탐 ──
    def overcatch(p):
        return sorted(s for s, g in gt.items() if g == "moving" and p.get(s) == "drinking")

    o0, o1 = overcatch(v361), overcatch(v40)
    print(f"\n=== moving→drinking 과탐 (비급여→급여) ===")
    print(f"  v3.6.1: {len(o0)}건 · v4.0: {len(o1)}건 {o1}")

    # ── 클래스별 raw 정확도 ──
    print(f"\n=== 클래스별 raw 정확도 (v3.6.1 → v4.0) ===")
    by_gt = defaultdict(lambda: [0, 0, 0])
    for s, g in gt.items():
        by_gt[g][2] += 1
        if v361.get(s) == g:
            by_gt[g][0] += 1
        if v40.get(s) == g:
            by_gt[g][1] += 1
    for g in sorted(by_gt, key=lambda x: -by_gt[x][2]):
        c0, c1, t = by_gt[g]
        print(f"  {g:13s} {c0:2d}/{t:2d} → {c1:2d}/{t:2d}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

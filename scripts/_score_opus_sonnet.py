"""opus-sonnet-186 채점 — Opus(186 신규) vs Sonnet(v40 재활용 185 + eval-0615 1).

시험지(experiments/opus-sonnet-186/TEST-SHEET.md) 지표 구현:
- raw 7-class 정확도 (모델별 × 186/185회귀셋/eval-0615 분리)
- 급여경계 정확도 (drinking↔eating_paste 무해 묶음)
- 클래스별 정확도 + care-priority 3클래스
- Opus↔Sonnet discordant

입력:
- GT: experiments/opus-sonnet-186/sample_list.json
- Opus: experiments/opus-sonnet-186/raw/opus.json (Workflow 결과 저장본)
- Sonnet: experiments/v40-regression/raw/v4.0_g*.json (185) + .../raw/sonnet0615.json (1)

실행: PYTHONPATH=. uv run python scripts/_score_opus_sonnet.py
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXP = REPO / "experiments" / "opus-sonnet-186"
V40RAW = REPO / "experiments" / "v40-regression" / "raw"
FEEDING = {"drinking", "eating_paste"}
CLASSES = ["moving", "shedding", "hand_feeding", "eating_prey", "eating_paste", "drinking", "unseen"]


def boundary(pred: str | None, g: str) -> bool:
    if pred is None:
        return False
    if g in FEEDING:
        return pred in FEEDING
    return pred == g


def main() -> int:
    samples = json.loads((EXP / "sample_list.json").read_text())
    gt = {s["id"]: s["gt"] for s in samples}
    is0615 = {s["id"]: (s.get("src") == "eval-0615") for s in samples}

    # Opus
    opus = {r["sample"]: r["action"] for r in json.loads((EXP / "raw" / "opus.json").read_text())}
    # Sonnet: v40 v4.0 (185) + eval-0615 (1)
    sonnet: dict[str, str] = {}
    for f in sorted(V40RAW.glob("v4.0_g*.json")):
        for r in json.loads(f.read_text()).get("results", []):
            sonnet[r["sample"]] = r["action"]
    s0615 = EXP / "raw" / "sonnet0615.json"
    if s0615.exists():
        for r in json.loads(s0615.read_text()):
            sonnet[r["sample"]] = r["action"]

    all_ids = list(gt)
    set185 = [s for s in all_ids if not is0615[s]]
    set0615 = [s for s in all_ids if is0615[s]]

    def score(preds, subset):
        ids = [s for s in subset if s in gt]
        raw = sum(1 for s in ids if preds.get(s) == gt[s])
        bnd = sum(1 for s in ids if boundary(preds.get(s), gt[s]))
        return raw, bnd, len(ids)

    print(f"=== 로드 — GT {len(gt)}건 ===")
    for name, p in [("Opus", opus), ("Sonnet", sonnet)]:
        miss = sorted(s for s in all_ids if s not in p)
        dup = "" if len(p) >= len(set185) else f" ⚠️예측 {len(p)}"
        print(f"  {name}: 예측 {len(p)}" + (f" · ⚠️누락 {len(miss)}: {miss[:6]}" if miss else " · 누락 0") + dup)

    print(f"\n=== 정확도 (raw 7-class / 급여경계) ===")
    for name, p in [("Opus 4.8", opus), ("Sonnet 4.6", sonnet)]:
        for label, subset in [("186 전체", all_ids), ("185 회귀셋", set185), ("eval-0615", set0615)]:
            r, b, n = score(p, subset)
            if n:
                print(f"  {name:11} {label:10}: raw {r:3}/{n} = {r/n:.1%}  ·  급여경계 {b:3}/{n} = {b/n:.1%}")
        print()

    # 모델 차 (186 raw)
    ro, _, n = score(opus, all_ids)
    rs, _, _ = score(sonnet, all_ids)
    diff = (ro - rs) / n * 100
    print(f"=== 모델 차 (186 raw): Opus {ro/n:.1%} − Sonnet {rs/n:.1%} = {diff:+.1f}%p ===")
    gate = "Opus 우위(>+2%p)" if diff > 2 else ("Sonnet 우위(<−2%p)" if diff < -2 else "동등(±2%p) → Sonnet 충분")
    print(f"  decision 후보: {gate}")

    print(f"\n=== 클래스별 raw (Opus / Sonnet) — 186 ===")
    for c in CLASSES:
        cids = [s for s in all_ids if gt[s] == c]
        o = sum(1 for s in cids if opus.get(s) == c)
        sn = sum(1 for s in cids if sonnet.get(s) == c)
        flag = " ←갈림" if abs(o - sn) >= 3 else ""
        print(f"  {c:14} ({len(cids):2}): Opus {o:2}/{len(cids):2}  ·  Sonnet {sn:2}/{len(cids):2}{flag}")

    care = [s for s in all_ids if gt[s] in {"moving", "shedding", "drinking"}]
    print(f"\n=== care-priority 3클래스 (moving+shedding+drinking, {len(care)}건) ===")
    for name, p in [("Opus", opus), ("Sonnet", sonnet)]:
        r = sum(1 for s in care if p.get(s) == gt[s])
        print(f"  {name}: {r}/{len(care)} = {r/len(care):.1%}")

    disc = [s for s in all_ids if opus.get(s) != sonnet.get(s)]
    print(f"\n=== Opus↔Sonnet discordant: {len(disc)}건 ===")
    for s in sorted(disc):
        mark = "○" if opus.get(s) == gt[s] else ("●" if sonnet.get(s) == gt[s] else "✗")
        print(f"  [{mark}] {s} GT={gt[s]:13}: Opus={opus.get(s):13} / Sonnet={sonnet.get(s)}")
    print("  (○=Opus만 정답 · ●=Sonnet만 정답 · ✗=둘다 오답)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

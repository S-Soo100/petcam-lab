"""conf 캐스케이드 심화 진단 — calibration curve + threshold robustness + 비용 모델.

C REPORT(cascade-opus-sim) 'conf<0.7 = ceiling 100% 회수' 발견의 견고성을 인퍼런스 0 으로 진단.
production conf 캐스케이드 spec 전 단계 — "conf 가 진짜 신뢰할 신호인가".

분석:
  1. Sonnet/Opus calibration curve (conf bin 별 실제 정확도) — conf 가 정확도와 monotonic 연동?
  2. threshold robustness sweep (0.50~0.95) — ceiling 달성 구간 폭
  3. 비용 모델 (Opus/Sonnet 가격비 r 시나리오) — 캐스케이드 vs Opus 단독 절감률

⚠️ 입력은 opus-sonnet-186 (temperature 비제어, Workflow blind). conf 안정성 자체는
   temperature 0 API 재측정으로만 확정 — 본 진단은 "이론적 상한" 확인용.

실행: PYTHONPATH=. uv run python scripts/_cascade_conf_deep.py
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXP = REPO / "experiments" / "opus-sonnet-186"
V40RAW = REPO / "experiments" / "v40-regression" / "raw"
FEEDING = {"drinking", "eating_paste"}

# ── 로드 (채점 SOT 동일: id 문자열 join, conf 포함) ──
samples = json.loads((EXP / "sample_list.json").read_text())
gt = {s["id"]: s["gt"] for s in samples}
opus = {r["sample"]: (r["action"], r.get("confidence", 0.0))
        for r in json.loads((EXP / "raw" / "opus.json").read_text())}
sonnet: dict[str, tuple[str, float]] = {}
for f in sorted(V40RAW.glob("v4.0_g*.json")):
    for r in json.loads(f.read_text()).get("results", []):
        sonnet[r["sample"]] = (r["action"], r.get("confidence", 0.0))
for r in json.loads((EXP / "raw" / "sonnet0615.json").read_text()):
    sonnet[r["sample"]] = (r["action"], r.get("confidence", 0.0))
keys = [i for i in gt if i in opus and i in sonnet]
N = len(keys)


def hit(model, k):
    return model[k][0] == gt[k]


# ── 1. calibration curve ──
print("=" * 78)
print("★ 1. Calibration curve — conf bin 별 실제 정확도 (conf 신호 신뢰성)")
print("=" * 78)
bins = [(0.0, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 0.951), (0.951, 1.01)]
for name, model in [("Sonnet 4.6", sonnet), ("Opus 4.8", opus)]:
    print(f"\n{name}:")
    print(f"  {'conf bin':12} {'건수':>5} {'정확도':>8}   {'(이상적: conf≈정확도)'}")
    for lo, hi in bins:
        ids = [k for k in keys if lo <= model[k][1] < hi]
        if not ids:
            print(f"  [{lo:.2f},{hi:.2f})    {0:>5}      —")
            continue
        acc = sum(hit(model, k) for k in ids) / len(ids)
        bar = "█" * round(acc * 20)
        print(f"  [{lo:.2f},{hi:.2f})  {len(ids):>5}  {acc:>7.0%}  {bar}")

# ── 2. threshold robustness ──
print("\n" + "=" * 78)
print("★ 2. Threshold robustness — Sonnet conf<t 면 Opus 에스컬 (정밀 sweep)")
print("=" * 78)
base_acc = sum(hit(sonnet, k) for k in keys) / N
ceil_acc = sum(hit(opus, k) for k in keys) / N
gap_n = round((ceil_acc - base_acc) * N)
print(f"base(Sonnet) {base_acc:.1%} / ceiling(Opus) {ceil_acc:.1%} / 격차 {gap_n}건")
print(f"\n  {'t':>5} {'esc율':>6} {'esc건':>6} {'raw':>7} {'급여경계':>8} {'격차회수':>8}")
for t in [round(0.50 + 0.05 * i, 2) for i in range(10)]:
    esc = {k for k in keys if sonnet[k][1] < t}
    pred = {k: (opus[k][0] if k in esc else sonnet[k][0]) for k in keys}
    raw = sum(pred[k] == gt[k] for k in keys) / N
    bnd = sum((pred[k] in FEEDING if gt[k] in FEEDING else pred[k] == gt[k]) for k in keys) / N
    recov = round((raw - base_acc) * N)
    star = "  ← ceiling" if recov >= gap_n else ""
    print(f"  {t:>5} {len(esc)/N:>5.0%} {len(esc):>6} {raw:>6.1%} {bnd:>7.1%} {recov:>+5d}/{gap_n}{star}")

# ── 3. 비용 모델 ──
print("\n" + "=" * 78)
print("★ 3. 비용 모델 — 캐스케이드(Sonnet 전건 + Opus esc) vs Opus 단독")
print("=" * 78)
print("  r = Opus/Sonnet 단가비. 실측(claude-api 2026-06-04): Sonnet $3/$15 · Opus $5/$25 → r=1.67 (input·output 동일)")
print("  캐스케이드 비용 = N + esc·r (Sonnet=1 기준) · Opus 단독 = N·r · 절감률 = 1 − (N + esc·r)/(N·r)\n")
for t in [0.6, 0.7, 0.8]:
    esc = len({k for k in keys if sonnet[k][1] < t})
    pred = {k: (opus[k][0] if sonnet[k][1] < t else sonnet[k][0]) for k in keys}
    raw = sum(pred[k] == gt[k] for k in keys) / N
    print(f"  conf<{t} (esc {esc}/{N}={esc/N:.0%}, raw {raw:.1%}):")
    for r in [1.67, 3.0]:  # 1.67=실제 Claude · 3.0=참고(가격차 큰 모델쌍)
        casc = N + esc * r
        solo = N * r
        save = 1 - casc / solo
        print(f"    r={r}: 캐스케이드 {casc:.0f} vs Opus단독 {solo:.0f}  →  비용 {save:.0%} 절감")

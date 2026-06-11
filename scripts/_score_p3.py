"""P3 채점 — v3.6.2-draft(IR shedding 가드) vs v3.6.1, Sonnet shedding 예측 46건.

recovered = v3.6.1 오답(shedding) → v3.6.2 정답.
broken    = v3.6.1 정답(shedding TP) → v3.6.2 오답.
FP-removed = 오탐이 shedding 은 벗어났으나 여전히 ≠GT (부분개선).
"""
from __future__ import annotations
import csv, json
from pathlib import Path

REPO = Path("/Users/baek/petcam-lab"); EXP = REPO / "experiments"; DS = REPO / "storage/dataset-203"
nn = {d.name: json.loads((d / "meta.json").read_text())["src"].split("__")[-1].split(".")[0]
      for d in (EXP / "eval-frames-claude").glob("sample-*") if d.is_dir()}
to_c8 = lambda s: nn.get(s, s.replace("sample-", ""))

# v3.6.2 재판정 (6배치 전사)
V362 = {
    # B0
    "sample-0146200f": "shedding", "sample-2d583811": "shedding", "sample-6142554e": "shedding",
    "sample-9c871834": "shedding", "sample-d83eacae": "shedding", "sample-48b5582e": "moving",
    "sample-78d6736e": "moving", "sample-da02bc43": "moving",
    # B1
    "sample-0525472f": "shedding", "sample-3252ac4a": "shedding", "sample-640ce9bb": "shedding",
    "sample-9dd677be": "shedding", "sample-efa2afcc": "shedding", "sample-556a7bfe": "moving",
    "sample-82333b9d": "moving", "sample-e0589541": "moving",
    # B2
    "sample-0e7bccb0": "shedding", "sample-3b0d9995": "shedding", "sample-67c40fdf": "shedding",
    "sample-abd987a3": "shedding", "sample-f4d9b62f": "shedding", "sample-50": "shedding",
    "sample-8a629097": "moving", "sample-e2eef892": "moving",
    # B3
    "sample-251ffaaa": "shedding", "sample-3b169faa": "shedding", "sample-6901da64": "shedding",
    "sample-ba39511a": "shedding", "sample-04ec15e3": "moving", "sample-5a34267c": "shedding",
    "sample-26": "moving", "sample-fc7f8f63": "moving",
    # B4
    "sample-25fa7876": "shedding", "sample-3f976b25": "shedding", "sample-6c9b50ad": "shedding",
    "sample-c2cd0200": "shedding", "sample-135a2e58": "moving", "sample-55": "moving",
    "sample-a09edeab": "moving",
    # B5
    "sample-2cad1b51": "shedding", "sample-53a2525b": "shedding", "sample-8d3d74b5": "shedding",
    "sample-c72a8256": "shedding", "sample-3e51c7ed": "moving", "sample-6eaea082": "moving",
    "sample-ce9bab20": "shedding",
}
v362 = {to_c8(k): v for k, v in V362.items()}

# v3.6.1 (기존 Sonnet)
son = {}
for ln in (EXP / "eval-frames-full/sonnet46_blind.jsonl").read_text().splitlines():
    if ln.strip():
        r = json.loads(ln); son[to_c8(r["sample"])] = r["action"]
gt = {r["clip_id"][:8]: r["gt"] for r in csv.DictReader(open(DS / "manifest.csv"))}

assert len(v362) == 46, f"v362 count {len(v362)}"
fp = [c for c in v362 if son[c] == "shedding" and gt[c] != "shedding"]
tp = [c for c in v362 if son[c] == "shedding" and gt[c] == "shedding"]

print("=" * 64)
print("★ P3 — v3.6.2-draft(IR 가드) vs v3.6.1, Sonnet shedding 예측 46건")
print("=" * 64)
print(f"\n[오탐셋 {len(fp)}건] v3.6.1=shedding 오탐 → v3.6.2:")
rec = fpr = 0
for c in sorted(fp, key=lambda x: gt[x]):
    p = v362[c]; ok = p == gt[c]
    if ok: rec += 1; tag = "✅ recovered"
    elif p != "shedding": fpr += 1; tag = "△ shedding이탈(여전오답)"
    else: tag = "✗ 여전 shedding"
    print(f"  {c}  gt={gt[c]:11s} v362={p:9s} {tag}")
print(f"\n[정탐셋 {len(tp)}건] v3.6.1=shedding 정답 → v3.6.2 (broken 측정):")
brk = 0
for c in sorted(tp):
    p = v362[c]; ok = p == "shedding"
    if not ok: brk += 1
    print(f"  {c}  v362={p:9s} {'✅ 유지' if ok else '✗ BROKEN'}")

print("\n" + "=" * 64)
print(f"recovered {rec}/{len(fp)}  ·  shedding이탈(부분) {fpr}  ·  broken {brk}/{len(tp)}")
net = rec - brk
print(f"순 정확도 효과(46건): {net:+d}건  →  전체 202 환산 {net/202*100:+.1f}%p")
# 전체 202 재계산: 기존 Sonnet 158 정답 + recovered - broken
new_total = 158 + rec - brk
print(f"Sonnet 전체: 158/202(78.2%) → {new_total}/202({new_total/202:.1%})  [오탐셋 밖 불변 가정]")
print("=" * 64)

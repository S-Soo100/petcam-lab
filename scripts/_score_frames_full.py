"""전체 202건 frames 단일 정확도 채점 (임시).

pred 출처 = full_blind.jsonl(136) + frames63_blind.jsonl(63, 재사용) + hiding 3(moving).
GT = manifest.csv(2026-06-09 정정본). clip8 기준 매칭.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

REPO = Path("/Users/baek/petcam-lab")
DS = REPO / "storage" / "dataset-203"

pred: dict[str, str] = {}
# full 136
for line in (REPO / "experiments/eval-frames-full/full_blind.jsonl").read_text().splitlines():
    if line.strip():
        r = json.loads(line)
        pred[r["sample"].replace("sample-", "")] = r["action"]
# frames63 (재사용, f=frames pred)
for line in (REPO / "experiments/eval-frames-claude/frames63_blind.jsonl").read_text().splitlines():
    if line.strip():
        r = json.loads(line)
        pred[r["src"].split("__")[-1].split(".")[0]] = r["f"]
# hiding 3 (검증서 moving)
for c8 in ["556a7bfe", "8899146c", "e07f9b00"]:
    pred[c8] = "moving"

rows = list(csv.DictReader(open(DS / "manifest.csv")))
gt = {r["clip_id"][:8]: r["gt"] for r in rows}

FM = {"drinking": "feeding", "eating_paste": "feeding"}
def fm(a: str) -> str:
    return FM.get(a, a)

n = raw = merged = 0
by: dict = defaultdict(lambda: {"c": 0, "t": 0})
conf: dict = defaultdict(int)
miss = []
for c8, g in gt.items():
    if c8 not in pred:
        miss.append((c8, g))
        continue
    p = pred[c8]
    n += 1
    by[g]["t"] += 1
    if p == g:
        raw += 1
        by[g]["c"] += 1
    else:
        conf[f"{g:13s}→ {p}"] += 1
    if fm(p) == fm(g):
        merged += 1

print("=" * 64)
print(f"★ 전체 {n}건 frames(개별 풀해상도 10장) 단일 정확도 — Claude subagent blind")
print("=" * 64)
print(f"raw 정확도          : {raw}/{n} = {raw/n:.1%}")
print(f"feeding-merged 정확도: {merged}/{n} = {merged/n:.1%}")
if miss:
    print(f"⚠️ pred 누락 {len(miss)}건: {miss[:5]}")
print("\n클래스별 (raw):")
for k in sorted(by, key=lambda x: -by[x]["t"]):
    b = by[k]
    print(f"  {k:14s} {b['c']:3d}/{b['t']:3d} = {b['c']/b['t']:.0%}")
print("\n주요 혼동 (상위 12):")
for k, v in sorted(conf.items(), key=lambda x: -x[1])[:12]:
    print(f"  {v:2d}x  {k}")

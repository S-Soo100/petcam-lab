"""frames 202 blind — 4모델 비교 (Fable 5 / Opus 4.8 / Sonnet 4.6 + 이전 run).

P1/P1b 채점기. 같은 추출프레임·v3.6.1 프롬프트·blind 프로토콜, 모델만 교체.
각 모델 pred = experiments/eval-frames-full/{model}_blind.jsonl (sample 키, 202 단일 파일).
이전 run = full_blind.jsonl(136) + frames63(63) + hiding 3 재구성 (모델 미기록).
GT = manifest.csv (2026-06-09 2차 정정본). frames63 sample-NN → meta.json src c8.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path

REPO = Path("/Users/baek/petcam-lab")
EXP = REPO / "experiments"
DS = REPO / "storage" / "dataset-203"

nn_to_c8: dict[str, str] = {}
for d in (EXP / "eval-frames-claude").glob("sample-*"):
    if d.is_dir():
        nn_to_c8[d.name] = json.loads((d / "meta.json").read_text())["src"].split("__")[-1].split(".")[0]


def to_c8(sample: str) -> str:
    return nn_to_c8.get(sample, sample.replace("sample-", ""))


def load_single(fname: str) -> dict[str, str]:
    pred = {}
    for line in (EXP / "eval-frames-full" / fname).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            pred[to_c8(r["sample"])] = r["action"]
    return pred


def load_prev() -> dict[str, str]:
    pred = {}
    for line in (EXP / "eval-frames-full/full_blind.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            pred[r["sample"].replace("sample-", "")] = r["action"]
    for line in (EXP / "eval-frames-claude/frames63_blind.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            pred[r["src"].split("__")[-1].split(".")[0]] = r["f"]
    for c8 in ["556a7bfe", "8899146c", "e07f9b00"]:
        pred[c8] = "moving"
    return pred


gt = {r["clip_id"][:8]: r["gt"] for r in csv.DictReader(open(DS / "manifest.csv"))}
FM = {"drinking": "feeding", "eating_paste": "feeding"}
fm = lambda a: FM.get(a, a)

MODELS = {
    "이전 run (모델 미기록)": load_prev(),
    "Sonnet 4.6": load_single("sonnet46_blind.jsonl"),
    "Opus 4.8": load_single("opus48_blind.jsonl"),
    "Fable 5": load_single("fable5_blind.jsonl"),
}

CLASS_ORDER = ["moving", "shedding", "hand_feeding", "eating_prey",
               "eating_paste", "defecating", "drinking", "unseen"]


def score(pred):
    n = raw = 0
    by = defaultdict(lambda: {"c": 0, "t": 0})
    for c8, g in gt.items():
        if c8 not in pred:
            continue
        n += 1
        by[g]["t"] += 1
        if pred[c8] == g:
            raw += 1
            by[g]["c"] += 1
    return n, raw, by


print("=" * 70)
print("★ frames 202 blind — 4모델 비교 (같은 입력·v3.6.1·blind, 모델만 교체)")
print("=" * 70)
results = {name: score(p) for name, p in MODELS.items()}
hdr = f"{'클래스(GT수)':16s}"
for name in MODELS:
    hdr += f"{name.split('(')[0].strip()[:11]:>13s}"
print(hdr)
print("-" * 70)
for k in CLASS_ORDER:
    t = next(b[k]["t"] for _, _, b in [results["Fable 5"]] for b in [results["Fable 5"][2]]) if False else results["Fable 5"][2][k]["t"]
    row = f"{k:13s}({t:2d})  "
    for name in MODELS:
        b = results[name][2][k]
        row += f"{b['c']:3d}/{b['t']:2d}={b['c']/b['t']*100:3.0f}% " if b["t"] else f"   - " + " " * 7
    print(row)
print("-" * 70)
tot = f"{'raw 전체':16s}"
for name in MODELS:
    n, raw, _ = results[name]
    tot += f"{raw:3d}/{n}={raw/n*100:4.1f}%".rjust(13)
print(tot)

# paired McNemar (Fable/Opus/Sonnet 3자, 이전 run 제외 — 모델 미기록)
print("\n" + "=" * 70)
print("★ paired 비교 — discordant (b/c) + McNemar χ² (현행 3모델 간)")
print("=" * 70)
cur = {k: v for k, v in MODELS.items() if k != "이전 run (모델 미기록)"}
keys = [c8 for c8 in gt if all(c8 in p for p in cur.values())]
for a, b in combinations(cur, 2):
    pa, pb = cur[a], cur[b]
    a_only = [c8 for c8 in keys if pa[c8] == gt[c8] and pb[c8] != gt[c8]]
    b_only = [c8 for c8 in keys if pb[c8] == gt[c8] and pa[c8] != gt[c8]]
    nb, nc = len(a_only), len(b_only)
    chi = (abs(nb - nc) - 1) ** 2 / (nb + nc) if (nb + nc) else 0.0
    sig = "유의(p<0.05)" if chi > 3.84 else "유의 X"
    print(f"  {a:11s} vs {b:11s}: {a}만맞 {nb:2d} / {b}만맞 {nc:2d}  χ²={chi:.2f} {sig}")

# 이전→Fable (모델교체 효과, 참고)
print("\n  [참고] 이전 run → Fable 5 (모델 미기록이라 비교 약함):")
prev, fab = MODELS["이전 run (모델 미기록)"], MODELS["Fable 5"]
pk = [c8 for c8 in gt if c8 in prev and c8 in fab]
rec = [c8 for c8 in pk if prev[c8] != gt[c8] and fab[c8] == gt[c8]]
brk = [c8 for c8 in pk if prev[c8] == gt[c8] and fab[c8] != gt[c8]]
chi = (abs(len(rec) - len(brk)) - 1) ** 2 / (len(rec) + len(brk))
print(f"    recovered {len(rec)} / broken {len(brk)}  χ²={chi:.2f} ({'유의' if chi > 3.84 else '유의 X'})")

# 합의 분석 (레버 D 사전데이터): 3모델 만장일치 vs 불일치 정확도
print("\n" + "=" * 70)
print("★ 레버 D 사전 데이터 — 3모델(현행) 합의 시 정확도")
print("=" * 70)
unanimous = [c8 for c8 in keys if len({cur[m][c8] for m in cur}) == 1]
split = [c8 for c8 in keys if c8 not in unanimous]
ua = sum(1 for c8 in unanimous if cur["Fable 5"][c8] == gt[c8])
print(f"만장일치 {len(unanimous)}/{len(keys)}건 → 정확도 {ua}/{len(unanimous)} = {ua/len(unanimous):.1%}")
# majority vote
maj_correct = 0
for c8 in keys:
    votes = defaultdict(int)
    for m in cur:
        votes[cur[m][c8]] += 1
    win = max(votes, key=votes.get)
    if win == gt[c8]:
        maj_correct += 1
print(f"3모델 majority-vote 정확도: {maj_correct}/{len(keys)} = {maj_correct/len(keys):.1%}")
print(f"불일치 {len(split)}건 (레버 D/캐스케이드 타깃)")

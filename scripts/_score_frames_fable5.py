"""전체 202건 frames blind — Fable 5 채점 + 이전 run(2026-06-09) paired 비교.

Fable 5 pred = experiments/eval-frames-full/fable5_blind.jsonl (202건 단일 파일).
이전 pred    = full_blind.jsonl(136) + frames63_blind.jsonl(63, "f") + hiding 3(moving)
               — _score_frames_full.py 와 동일 재구성. 정정 GT 로 재채점하므로
               미완 태스크 "frames 79.7% 재계산"(GT 4건 정정 반영)을 겸한다.
GT = manifest.csv (2026-06-09 2차 정정본: drinking 16 / moving 72). clip8 매칭.
frames63 의 sample-NN 은 meta.json src 에서 c8 추출 (채점기만 GT 접근 — blind 유지).
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

REPO = Path("/Users/baek/petcam-lab")
EXP = REPO / "experiments"
DS = REPO / "storage" / "dataset-203"

# frames63 sample-NN → c8 매핑 (meta.json src 파일명 마지막 토큰)
nn_to_c8: dict[str, str] = {}
for d in (EXP / "eval-frames-claude").glob("sample-*"):
    if d.is_dir():
        meta = json.loads((d / "meta.json").read_text())
        nn_to_c8[d.name] = meta["src"].split("__")[-1].split(".")[0]


def to_c8(sample: str) -> str:
    return nn_to_c8.get(sample, sample.replace("sample-", ""))


# Fable 5 preds
new: dict[str, str] = {}
for line in (EXP / "eval-frames-full/fable5_blind.jsonl").read_text().splitlines():
    if line.strip():
        r = json.loads(line)
        new[to_c8(r["sample"])] = r["action"]

# 이전 run preds (2026-06-09)
old: dict[str, str] = {}
for line in (EXP / "eval-frames-full/full_blind.jsonl").read_text().splitlines():
    if line.strip():
        r = json.loads(line)
        old[r["sample"].replace("sample-", "")] = r["action"]
for line in (EXP / "eval-frames-claude/frames63_blind.jsonl").read_text().splitlines():
    if line.strip():
        r = json.loads(line)
        old[r["src"].split("__")[-1].split(".")[0]] = r["f"]
for c8 in ["556a7bfe", "8899146c", "e07f9b00"]:
    old[c8] = "moving"

gt = {r["clip_id"][:8]: r["gt"] for r in csv.DictReader(open(DS / "manifest.csv"))}

FM = {"drinking": "feeding", "eating_paste": "feeding"}


def fm(a: str) -> str:
    return FM.get(a, a)


def score(pred: dict[str, str], label: str) -> None:
    n = raw = merged = 0
    by: dict = defaultdict(lambda: {"c": 0, "t": 0})
    conf: dict = defaultdict(int)
    for c8, g in gt.items():
        if c8 not in pred:
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
    print(f"\n{'=' * 64}\n★ {label}\n{'=' * 64}")
    print(f"raw 정확도          : {raw}/{n} = {raw / n:.1%}")
    print(f"feeding-merged 정확도: {merged}/{n} = {merged / n:.1%}")
    print("클래스별 (raw):")
    for k in sorted(by, key=lambda x: -by[x]["t"]):
        b = by[k]
        print(f"  {k:14s} {b['c']:3d}/{b['t']:3d} = {b['c'] / b['t']:.0%}")
    print("주요 혼동 (상위 8):")
    for k, v in sorted(conf.items(), key=lambda x: -x[1])[:8]:
        print(f"  {v:2d}x  {k}")


score(old, "이전 run (2026-06-09) — 정정 GT 재채점 (79.7% 재계산)")
score(new, "Fable 5 (2026-06-10) — 같은 프레임·같은 v3.6.1 프롬프트")

# paired 비교 (clip 단위)
recovered, broken, both_wrong_changed = [], [], []
for c8, g in gt.items():
    if c8 not in old or c8 not in new:
        continue
    o_ok, n_ok = old[c8] == g, new[c8] == g
    if not o_ok and n_ok:
        recovered.append((c8, g, old[c8]))
    elif o_ok and not n_ok:
        broken.append((c8, g, new[c8]))
    elif not o_ok and not n_ok and old[c8] != new[c8]:
        both_wrong_changed.append((c8, g, old[c8], new[c8]))

print(f"\n{'=' * 64}\n★ paired 비교 (모델만 교체: 이전 → Fable 5)\n{'=' * 64}")
print(f"recovered (이전 오답 → 정답): {len(recovered)}건")
for c8, g, op in sorted(recovered, key=lambda x: x[1]):
    print(f"  {c8}  gt={g:13s} 이전pred={op}")
print(f"\nbroken (이전 정답 → 오답): {len(broken)}건")
for c8, g, np_ in sorted(broken, key=lambda x: x[1]):
    print(f"  {c8}  gt={g:13s} Fable5pred={np_}")
print(f"\n둘 다 오답인데 pred 변경: {len(both_wrong_changed)}건")
for c8, g, op, np_ in sorted(both_wrong_changed, key=lambda x: x[1]):
    print(f"  {c8}  gt={g:13s} {op} → {np_}")

# GT 오류 후보: GT≠hand_feeding 인데 Fable 5 가 hand_feeding (사람 영상 확인 후 정정 원칙)
hf_dev = [(c8, g) for c8, g in gt.items() if c8 in new and new[c8] == "hand_feeding" and g != "hand_feeding"]
if hf_dev:
    print(f"\n⚠️ hand_feeding 이탈 (GT 오류 후보, 사람 영상 확인 필요): {len(hf_dev)}건")
    for c8, g in hf_dev:
        print(f"  {c8}  gt={g}")

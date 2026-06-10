"""P2 채점 — 모션 키프레임(N=20) vs 기존 균등 N=10. recovered/broken.

오답셋: N=10 에서 Fable 가 →moving 오답낸 11건(eating_prey/paste/shedding).
대조군: N=10 에서 정답이던 9건(같은 클래스).
P2 pred = 아래 전사(모션키프레임 Fable 재판정). meta.json GT 대조.
"""
from __future__ import annotations
import json
from pathlib import Path

REPO = Path("/Users/baek/petcam-lab")
P2 = REPO / "experiments/eval-frames-p2"

# 모션키프레임 Fable 재판정 (3배치 전사)
P2_PRED = {
    # B0
    "0dbc54a8": "moving", "7b9d6d42": "drinking", "cc9463c9": "moving",
    "76b9a076": "moving", "2c5c4fc6": "eating_paste", "caf661e0": "eating_prey",
    "0e7bccb0": "shedding",
    # B1
    "3abc83bc": "moving", "26c75091": "moving", "dfcf1099": "moving",
    "abd987a3": "shedding", "8329c627": "eating_paste", "d70cebe1": "eating_prey",
    "2d583811": "shedding",
    # B2
    "8f186154": "moving", "b9181603": "moving", "31da5684": "moving",
    "bae3a9e3": "eating_paste", "b9656d30": "eating_prey", "c2cd0200": "shedding",
}

meta = {d.name.replace("sample-", ""): json.loads((d / "meta.json").read_text())
        for d in P2.glob("sample-*") if (d / "meta.json").exists()}

err = [c8 for c8, m in meta.items() if m["role"] == "ERR"]
ctrl = [c8 for c8, m in meta.items() if m["role"] == "CTRL"]

print("=" * 60)
print("★ P2 — 모션 키프레임(N=20) vs 균등(N=10) 재판정")
print("=" * 60)
print("\n[오답셋] N=10 에서 →moving 오답 → N=20 모션키프레임:")
rec = 0
for c8 in sorted(err, key=lambda c: meta[c]["gt"]):
    g, p = meta[c8]["gt"], P2_PRED[c8]
    ok = p == g
    rec += ok
    print(f"  {c8}  gt={g:13s} N20={p:13s} {'✅ recovered' if ok else '✗ 여전오답'}")
print(f"\n  recovered {rec}/{len(err)}")

print("\n[대조군] N=10 정답 → N=20 (broken 측정):")
brk = 0
for c8 in sorted(ctrl, key=lambda c: meta[c]["gt"]):
    g, p = meta[c8]["gt"], P2_PRED[c8]
    ok = p == g
    brk += not ok
    print(f"  {c8}  gt={g:13s} N20={p:13s} {'✅ 유지' if ok else '✗ BROKEN'}")
print(f"\n  broken {brk}/{len(ctrl)}")

print("\n" + "=" * 60)
print(f"판정: recovered {rec} / broken {brk}  →  순효과 {rec - brk:+d}건")
print(f"전체 202 환산: {(rec - brk) / 202 * 100:+.1f}%p (채택 기준 +1%p)")
print("=" * 60)
# 클래스별 recovered
from collections import defaultdict
by = defaultdict(lambda: [0, 0])
for c8 in err:
    by[meta[c8]["gt"]][1] += 1
    if P2_PRED[c8] == meta[c8]["gt"]:
        by[meta[c8]["gt"]][0] += 1
print("오답셋 클래스별 recovered:")
for k, (c, t) in sorted(by.items()):
    print(f"  {k:13s} {c}/{t}")

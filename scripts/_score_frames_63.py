"""frames 정량 채점 — 미세접촉 전체 63건. frames(개별 풀해상도) vs montage(몽타주).

클래스별(drinking/eating_prey/eating_paste) 정확도 = 핵심. blind=라벨QA 단서도 추출.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

OUT = Path("/Users/baek/petcam-lab/experiments/eval-frames-claude")

# 서브에이전트 blind 판정 취합 (20건 편향표본 + 43건 신규 = 63건 전체)
PRED = {
    "sample-01": ("eating_paste", 0.95), "sample-02": ("hand_feeding", 0.88),
    "sample-03": ("moving", 0.85), "sample-04": ("drinking", 0.92),
    "sample-05": ("eating_prey", 0.72), "sample-06": ("eating_prey", 0.82),
    "sample-07": ("eating_paste", 0.85), "sample-08": ("eating_paste", 0.95),
    "sample-09": ("drinking", 0.92), "sample-10": ("eating_prey", 0.93),
    "sample-11": ("moving", 0.50), "sample-12": ("moving", 0.90),
    "sample-13": ("drinking", 0.72), "sample-14": ("eating_prey", 0.97),
    "sample-15": ("moving", 0.70), "sample-16": ("eating_paste", 0.97),
    "sample-17": ("moving", 0.85), "sample-18": ("eating_paste", 0.70),
    "sample-19": ("drinking", 0.82), "sample-20": ("moving", 0.88),
    "sample-21": ("eating_prey", 0.85), "sample-22": ("drinking", 0.40),
    "sample-23": ("hand_feeding", 0.92), "sample-24": ("eating_prey", 0.85),
    "sample-25": ("moving", 0.85), "sample-26": ("moving", 0.82),
    "sample-27": ("drinking", 0.88), "sample-28": ("moving", 0.55),
    "sample-29": ("hand_feeding", 0.95), "sample-30": ("eating_prey", 0.80),
    "sample-31": ("drinking", 0.85), "sample-32": ("eating_prey", 0.85),
    "sample-33": ("moving", 0.78), "sample-34": ("eating_paste", 0.95),
    "sample-35": ("eating_prey", 0.88), "sample-36": ("eating_paste", 0.95),
    "sample-37": ("eating_paste", 0.95), "sample-38": ("moving", 0.70),
    "sample-39": ("eating_paste", 0.92), "sample-40": ("drinking", 0.70),
    "sample-41": ("eating_prey", 0.55), "sample-42": ("eating_paste", 0.95),
    "sample-43": ("drinking", 0.62), "sample-44": ("eating_prey", 0.70),
    "sample-45": ("drinking", 0.85), "sample-46": ("moving", 0.88),
    "sample-47": ("eating_paste", 0.80), "sample-48": ("moving", 0.70),
    "sample-49": ("eating_paste", 0.82), "sample-50": ("eating_prey", 0.82),
    "sample-51": ("eating_paste", 0.82), "sample-52": ("eating_prey", 0.95),
    "sample-53": ("eating_prey", 0.70), "sample-54": ("eating_prey", 0.90),
    "sample-55": ("moving", 0.45), "sample-56": ("eating_prey", 0.92),
    "sample-57": ("moving", 0.85), "sample-58": ("moving", 0.70),
    "sample-59": ("eating_paste", 0.80), "sample-60": ("eating_prey", 0.80),
    "sample-61": ("moving", 0.85), "sample-62": ("eating_paste", 0.92),
    "sample-63": ("drinking", 0.90),
}
FEEDING_MERGE = {"drinking": "feeding", "eating_paste": "feeding"}


def fm(a: str) -> str:
    return FEEDING_MERGE.get(a, a)


rows = []
jsonl = OUT / "frames63_blind.jsonl"
with jsonl.open("w") as jf:
    for d in sorted(OUT.glob("sample-*")):
        if d.name not in PRED:
            continue
        meta = json.loads((d / "meta.json").read_text())
        pred, conf = PRED[d.name]
        r = {"sample": d.name, "gt": meta["gt"], "f": pred, "conf": conf,
             "m": meta["pred_montage"], "src": meta["src"]}
        rows.append(r)
        jf.write(json.dumps(r, ensure_ascii=False) + "\n")

n = len(rows)
f_raw = sum(1 for r in rows if r["f"] == r["gt"])
m_raw = sum(1 for r in rows if r["m"] == r["gt"])
f_mg = sum(1 for r in rows if fm(r["f"]) == fm(r["gt"]))
m_mg = sum(1 for r in rows if fm(r["m"]) == fm(r["gt"]))

print("=" * 70)
print(f"미세접촉 전체 {n}건 정량 — montage(몽타주) vs frames(개별 풀해상도 10장)")
print("=" * 70)
print(f"raw 정확도      : montage {m_raw}/{n}={m_raw/n:.0%}   →   frames {f_raw}/{n}={f_raw/n:.0%}")
print(f"feeding-merged  : montage {m_mg}/{n}={m_mg/n:.0%}   →   frames {f_mg}/{n}={f_mg/n:.0%}")
print()


def cls(key: str) -> dict:
    by: dict = defaultdict(lambda: {"c": 0, "t": 0})
    for r in rows:
        by[r["gt"]]["t"] += 1
        if r[key] == r["gt"]:
            by[r["gt"]]["c"] += 1
    return by


fby, mby = cls("f"), cls("m")
print(f"{'클래스(raw)':16s}{'montage':>14s}{'frames':>14s}")
for k in ("drinking", "eating_prey", "eating_paste"):
    mb, fb = mby[k], fby[k]
    ms = f"{mb['c']}/{mb['t']}={mb['c'] / mb['t']:.0%}"
    fs = f"{fb['c']}/{fb['t']}={fb['c'] / fb['t']:.0%}"
    print(f"  {k:14s}{ms:>14s}{fs:>14s}")
print()

recovered = [r for r in rows if r["m"] != r["gt"] and r["f"] == r["gt"]]
broken = [r for r in rows if r["m"] == r["gt"] and r["f"] != r["gt"]]
print(f"몽타주 오답 → frames 회복(recovered): {len(recovered)}건 / 몽타주 정답 → frames 파손(broken): {len(broken)}건")
for r in broken:
    print(f"    [파손] {r['sample']} GT={r['gt']} → frames={r['f']} (conf {r['conf']})")
print()

# frames 가 hand_feeding 으로 본 것 = OOD 라벨 QA 후보 (GT 가 다른 클래스면 오라벨 의심)
hf = [r for r in rows if r["f"] == "hand_feeding"]
print(f"★ hand_feeding 판정 {len(hf)}건 (GT≠hand_feeding 이면 OOD 오라벨 후보 — 사람 영상 확인):")
for r in hf:
    flag = "⚠️오라벨후보" if r["gt"] != "hand_feeding" else "일치"
    print(f"    {r['sample']} GT={r['gt']:12s} → hand_feeding (conf {r['conf']}) [{flag}]  {r['src']}")
print()

qa = [r for r in rows if r["f"] != r["gt"] and r["conf"] >= 0.85]
print(f"GT 검수 후보 (frames confident≥0.85 인데 GT 불일치) {len(qa)}건:")
for r in qa:
    print(f"    {r['sample']} GT={r['gt']:12s} → frames={r['f']:12s} conf={r['conf']}  {r['src']}")
print(f"\n→ jsonl: {jsonl}")

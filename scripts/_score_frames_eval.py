"""frames blind 평가 채점 (임시). meta.json GT vs 서브에이전트 blind 판정 대조.

핵심 측정: contact-sheet 몽타주(프레임당 ~72px)가 틀린 미세접촉 케이스를 개별 풀해상도
프레임이 회복(recovered)했는가 / 맞던 걸 깼는가(broken).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path("/Users/baek/petcam-lab/experiments/eval-frames-claude")

# 서브에이전트 5배치 blind 판정 취합 (sample → (frames_pred, conf))
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
}
FEEDING_MERGE = {"drinking": "feeding", "eating_paste": "feeding"}


def fm(a: str) -> str:
    return FEEDING_MERGE.get(a, a)


rows = []
jsonl = OUT / "frames_blind.jsonl"
with jsonl.open("w") as jf:
    for d in sorted(OUT.glob("sample-*")):
        meta = json.loads((d / "meta.json").read_text())
        pred, conf = PRED[d.name]
        r = {"sample": d.name, "gt": meta["gt"], "frames": pred, "conf": conf,
             "montage": meta["pred_montage"], "src": meta["src"]}
        rows.append(r)
        jf.write(json.dumps(r, ensure_ascii=False) + "\n")

n = len(rows)
f_raw = sum(1 for r in rows if r["frames"] == r["gt"])
m_raw = sum(1 for r in rows if r["montage"] == r["gt"])
f_merged = sum(1 for r in rows if fm(r["frames"]) == fm(r["gt"]))
m_merged = sum(1 for r in rows if fm(r["montage"]) == fm(r["gt"]))

print("=" * 66)
print(f"frames(개별 풀해상도) vs montage(몽타주) — 같은 {n}건 직접 비교")
print("=" * 66)
print(f"raw 정확도      : montage {m_raw}/{n}={m_raw/n:.0%}  →  frames {f_raw}/{n}={f_raw/n:.0%}")
print(f"feeding-merged  : montage {m_merged}/{n}={m_merged/n:.0%}  →  frames {f_merged}/{n}={f_merged/n:.0%}")
print()

# 결정적: 몽타주 오답(N) 중 frames 회복 / 몽타주 정답(Y) 중 frames 파손
recovered = [r for r in rows if r["montage"] != r["gt"] and r["frames"] == r["gt"]]
broken = [r for r in rows if r["montage"] == r["gt"] and r["frames"] != r["gt"]]
still_wrong = [r for r in rows if r["montage"] != r["gt"] and r["frames"] != r["gt"]]
n_montage_wrong = sum(1 for r in rows if r["montage"] != r["gt"])

print(f"★ 몽타주 오답 {n_montage_wrong}건 중 개별프레임 회복(recovered): {len(recovered)}건")
for r in recovered:
    print(f"    [회복] {r['sample']} GT={r['gt']:12s} montage={r['montage']:12s} → frames={r['frames']} (conf {r['conf']})")
print(f"★ 몽타주 정답 중 개별프레임이 깬(broken): {len(broken)}건")
for r in broken:
    print(f"    [파손] {r['sample']} GT={r['gt']:12s} → frames={r['frames']} (conf {r['conf']})")
print(f"  둘 다 오답(still-wrong): {len(still_wrong)}건")
for r in still_wrong:
    print(f"    [잔존] {r['sample']} GT={r['gt']:12s} montage={r['montage']:12s} frames={r['frames']:12s} (conf {r['conf']})")
print()

print("클래스별 (frames raw):")
by = defaultdict(lambda: {"c": 0, "t": 0})
for r in rows:
    by[r["gt"]]["t"] += 1
    if r["frames"] == r["gt"]:
        by[r["gt"]]["c"] += 1
for k in sorted(by, key=lambda x: -by[x]["t"]):
    b = by[k]
    print(f"  {k:14s} {b['c']}/{b['t']} = {b['c']/b['t']:.0%}")
print()

# 라벨 QA 단서: frames 가 confident(>=0.7) 하게 GT 와 다른 케이스
qa = [r for r in rows if r["frames"] != r["gt"] and r["conf"] >= 0.7]
print(f"GT 검수 후보 (frames confident≥0.7 인데 GT 불일치) {len(qa)}건 — 사람 영상 확인 대상:")
for r in qa:
    print(f"    {r['sample']} GT={r['gt']:12s} → frames={r['frames']:12s} conf={r['conf']}  src={r['src']}")
print(f"\n→ jsonl: {jsonl}")

"""20프레임 회복 채점 (임시). 10f 오답 21건이 20f(시간 샘플링 2배)에서 회복됐는지.

분류: recovered(p20==gt) / moving-유지(시각·시간축 진짜 한계) / hand_feeding-유지(GT 오류 후보).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

OUT = Path("/Users/baek/petcam-lab/experiments/eval-frames20")

P20 = {
    "sample-01": "hand_feeding", "sample-02": "eating_prey", "sample-03": "moving",
    "sample-04": "eating_prey", "sample-05": "eating_paste", "sample-06": "moving",
    "sample-07": "moving", "sample-08": "moving", "sample-09": "moving",
    "sample-10": "moving", "sample-11": "moving", "sample-12": "eating_prey",
    "sample-13": "hand_feeding", "sample-14": "moving", "sample-15": "moving",
    "sample-16": "hand_feeding", "sample-17": "moving", "sample-18": "moving",
    "sample-19": "moving", "sample-20": "moving", "sample-21": "moving",
}

rows = []
for d in sorted(OUT.glob("sample-*")):
    m = json.loads((d / "meta.json").read_text())
    rows.append({"s": d.name, "gt": m["gt"], "p10": m["pred10"], "p20": P20[d.name], "src": m["src"]})

n = len(rows)
recovered = [r for r in rows if r["p20"] == r["gt"]]
hf = [r for r in rows if r["p20"] == "hand_feeding" and r["gt"] != "hand_feeding"]
moving_stuck = [r for r in rows if r["p20"] == "moving" and r["gt"] != "moving"]
other = [r for r in rows if r not in recovered and r not in hf and r not in moving_stuck]

print("=" * 64)
print(f"10프레임 오답 {n}건 → 20프레임 재평가 (시간 샘플링 2배)")
print("=" * 64)
print(f"★ 회복(recovered, p20==GT): {len(recovered)}/{n} = {len(recovered)/n:.0%}")
for r in recovered:
    print(f"    [회복] {r['s']} GT={r['gt']:12s} p10={r['p10']:12s} → p20={r['p20']}")
print(f"\n여전히 →moving (시각/시간축 진짜 한계): {len(moving_stuck)}건")
for r in moving_stuck:
    print(f"    {r['s']} GT={r['gt']:12s} (10f·20f 둘 다 moving)" if r["p10"] == "moving"
          else f"    {r['s']} GT={r['gt']:12s} p10={r['p10']}→moving")
print(f"\nhand_feeding 유지 (GT 오류 후보, 10f·20f 일관): {len(hf)}건")
for r in hf:
    print(f"    {r['s']} GT={r['gt']:12s} → hand_feeding   src={r['src']}")
if other:
    print(f"\n기타 변화: {len(other)}건")
    for r in other:
        print(f"    {r['s']} GT={r['gt']:12s} p10={r['p10']}→p20={r['p20']}")

# 클래스별 회복
print("\n회복 GT 클래스:", dict(Counter(r["gt"] for r in recovered)))
print(f"\n→ 종합: 21건 잔존오답 중 {len(recovered)} 회복 / {len(moving_stuck)} 시각한계 / {len(hf)} GT오류후보")

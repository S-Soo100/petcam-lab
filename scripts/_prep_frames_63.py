"""frames 정량 — 미세접촉 전체 63건(drinking20+prey25+paste18) 중 미평가 43건 추가 준비.

기존 eval-frames-claude/sample-01~20 (편향 표본, 이미 평가) 은 그대로 두고, 겹치지 않는
43건을 sample-21~ 로 추출. 합쳐서 63건 = 미세접촉 전체 정량 (편향 없음).
"""
from __future__ import annotations

import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

REPO = Path("/Users/baek/petcam-lab")
DS = REPO / "storage" / "dataset-203"
OUT = REPO / "experiments" / "eval-frames-claude"
N_FRAMES = 10
MICRO = ("drinking", "eating_prey", "eating_paste")

sys.path.insert(0, str(DS))
import analyze  # noqa: E402

rows = list(csv.DictReader(open(DS / "manifest.csv")))
targets = [r for r in rows if r["gt"] in MICRO]  # 63

done_src = {json.loads((d / "meta.json").read_text())["src"]
            for d in sorted(OUT.glob("sample-*"))}  # 기존 20
new = [r for r in targets if r["filename"] not in done_src]
random.seed(43)
random.shuffle(new)  # blind

start = len(done_src) + 1
for i, r in enumerate(new, start):
    d = OUT / f"sample-{i:02d}"
    d.mkdir(exist_ok=True)
    frames = analyze.extract_frames(DS / r["filename"], str(d), N_FRAMES)
    (d / "meta.json").write_text(
        json.dumps(
            {"gt": r["gt"], "src": r["filename"], "pred_montage": r["pred_v361"],
             "match_montage": r["match"], "nframes": len(frames)},
            ensure_ascii=False, indent=2,
        )
    )

names = [f"sample-{i:02d}" for i in range(start, start + len(new))]
print(f"기존 {len(done_src)} + 신규 {len(new)} = {len(targets)}건 (미세접촉 전체)")
print(f"신규: {names[0]} ~ {names[-1]}")
print("신규 GT 분포:", dict(Counter(r["gt"] for r in new)))
print("전체 63 GT 분포:", dict(Counter(r["gt"] for r in targets)))
# 배치 분할(7배치, 클래스 섞임 — 이미 셔플됨)
B = 6
for bi in range(0, len(names), B):
    print(f"  BATCH {bi//B + 1}: {' '.join(names[bi:bi+B])}")

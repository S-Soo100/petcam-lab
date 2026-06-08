"""frames 10장에서 틀린 오답을 20장으로 재추출 — 시간 샘플링 밀도 2배 회복 측정 (임시).

가설: frames 10장이 →moving 등으로 틀린 잔존 오답 일부는 결정적 순간(혀-접촉 등)이
10프레임 사이에 안 걸린 것. 20프레임이면 회복될 수 있다. (IR 야간·진짜 모호는 안 됨)
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

REPO = Path("/Users/baek/petcam-lab")
DS = REPO / "storage" / "dataset-203"
SRC_JSONL = REPO / "experiments" / "eval-frames-claude" / "frames63_blind.jsonl"
OUT = REPO / "experiments" / "eval-frames20"
N_FRAMES = 20

sys.path.insert(0, str(DS))
import analyze  # noqa: E402

OUT.mkdir(parents=True, exist_ok=True)
rows = [json.loads(l) for l in SRC_JSONL.read_text().splitlines() if l.strip()]
wrong = [r for r in rows if r["f"] != r["gt"]]  # 10장 오답 전체
random.seed(44)
random.shuffle(wrong)  # blind

for i, r in enumerate(wrong, 1):
    d = OUT / f"sample-{i:02d}"
    d.mkdir(exist_ok=True)
    frames = analyze.extract_frames(DS / r["src"], str(d), N_FRAMES)
    (d / "meta.json").write_text(
        json.dumps(
            {"gt": r["gt"], "src": r["src"], "pred10": r["f"], "conf10": r["conf"],
             "nframes": len(frames)},
            ensure_ascii=False, indent=2,
        )
    )

names = [f"sample-{i:02d}" for i in range(1, len(wrong) + 1)]
print(f"10장 오답 {len(wrong)}건 → 20프레임 재추출 (eval-frames20/{names[0]}~{names[-1]})")
print("오답 GT 분포:", dict(Counter(r["gt"] for r in wrong)))
print("오답 10f-pred 분포:", dict(Counter(r["f"] for r in wrong)))
B = 3
for bi in range(0, len(names), B):
    print(f"  BATCH {bi//B + 1}: {' '.join(names[bi:bi+B])}")

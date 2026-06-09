"""전체 202건 frames 단일 정확도용 — 미평가 136건 추출 (임시).

이미 frames 평가한 66건(미세접촉 63 = frames63_blind + hiding 3) 제외한 나머지를
개별 풀해상도 프레임 10장으로 추출. moving/hand_feeding/shedding/defecating/unseen.
(shedding/defecating 은 정지프레임이라 ~0 예상 — contact-sheet 파일럿서 입증됨.)
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
OUT = REPO / "experiments" / "eval-frames-full"
N_FRAMES = 10

sys.path.insert(0, str(DS))
import analyze  # noqa: E402

OUT.mkdir(parents=True, exist_ok=True)

# 이미 frames 평가한 clip8 (미세접촉 63 + hiding 3) = 재사용, 제외
done: set[str] = {"556a7bfe", "8899146c", "e07f9b00"}
for line in (REPO / "experiments/eval-frames-claude/frames63_blind.jsonl").read_text().splitlines():
    if line.strip():
        done.add(json.loads(line)["src"].split("__")[-1].split(".")[0])

rows = list(csv.DictReader(open(DS / "manifest.csv")))
new = [r for r in rows if r["clip_id"][:8] not in done]
random.seed(45)
random.shuffle(new)

for r in new:
    c8 = r["clip_id"][:8]
    src = [m for m in DS.glob(f"*{c8}*") if m.suffix.lower() in (".mp4", ".mov")][0]
    d = OUT / f"sample-{c8}"
    d.mkdir(exist_ok=True)
    analyze.extract_frames(src, str(d), N_FRAMES)
    (d / "meta.json").write_text(
        json.dumps({"gt": r["gt"], "src": r["filename"], "c8": c8}, ensure_ascii=False)
    )

names = [f"sample-{r['clip_id'][:8]}" for r in new]
print(f"추가 {len(new)}건 추출 → {OUT}  (이미 평가 {len(done)}건 제외)")
print("GT 분포:", dict(Counter(r["gt"] for r in new)))
# 배치 8건씩
B = 8
for bi in range(0, len(names), B):
    print(f"BATCH{bi//B + 1}: {' '.join(names[bi:bi+B])}")

"""frames 방식 blind 평가용 표본 준비 (임시 스크립트).

dataset-203 에서 미세접촉 클래스(drinking/eating_prey/eating_paste)의 몽타주 오답(N)
위주 + 정답(Y) 대조를 골라, 각 클립에서 개별 풀해상도 프레임 N장 추출 → 중립 폴더명
(sample-NN, GT 안 박힘) + meta.json(GT 숨김). blind 유지 위해 셔플(seed 고정).

목적: contact-sheet 몽타주(프레임당 ~72px, 153건 72.5%)가 →moving 으로 틀린 미세접촉
케이스를, 개별 풀해상도 프레임이 회복하는지 측정.
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

sys.path.insert(0, str(DS))
import analyze  # noqa: E402  — dataset-203/analyze.py (extract_frames 재사용)

OUT.mkdir(parents=True, exist_ok=True)
rows = list(csv.DictReader(open(DS / "manifest.csv")))


def pick(gt: str, match: str, k: int) -> list[dict]:
    """gt + match(Y/N) 조건 앞에서 k건 (정렬 순서 = 재현성)."""
    return [r for r in rows if r["gt"] == gt and r["match"] == match][:k]


# 오답(N) 위주 + 정답(Y) 대조. 몽타주가 틀린 미세접촉을 개별프레임이 회복하나가 핵심.
sample = (
    pick("drinking", "N", 5) + pick("drinking", "Y", 2)
    + pick("eating_prey", "N", 5) + pick("eating_prey", "Y", 2)
    + pick("eating_paste", "N", 4) + pick("eating_paste", "Y", 2)
)
random.seed(42)
random.shuffle(sample)  # blind: 폴더 순서로 클래스/정오답 패턴 안 보이게

for i, r in enumerate(sample, 1):
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
    print(f"  sample-{i:02d}: {len(frames)}프레임")

# v3.6.1 프롬프트 (analyze.build_prompt = production 동치) → 서브에이전트용
Path("/tmp/v361_frames_prompt.txt").write_text(analyze.build_prompt())

print(f"\n총 {len(sample)}건 → {OUT}  (각 {N_FRAMES}프레임, 프롬프트 → /tmp/v361_frames_prompt.txt)")
print("검증용(에이전트엔 숨김) GT 분포:", dict(Counter(r["gt"] for r in sample)))
print("검증용 match(몽타주) 분포:", dict(Counter(r["match"] for r in sample)))

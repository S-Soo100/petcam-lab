"""M0 pre-registration — stratified 20건 선정 + blind 번호 고정 (임시, 인퍼런스 0).

experiment-claude-montage-v2.md §4-2 구성 정책 구현:
- micro55에서 12건: drinking/eating_prey/eating_paste 4/4/4, 각 클래스 Sonnet frames 정답2+오답2
- 일반 8건: moving 4(그중 chemoreception 경계 2 = 0609 GT정정 cam-motion 클립) + shedding 3(정2오1)
  + hand_feeding 1. hand_feeding 과대표집 금지(≤1~2).
- 결정론: 각 버킷 후보를 c8 정렬 후 앞에서 k건 (재현성). blind 번호는 seed 42 셔플로 고정.
- 산출: experiments/m0-montage/sample_list.json — **GT 포함이므로 inference 입력 디렉토리에
  절대 복사 금지** (blind 유지: 입력 dir에는 jpg만, meta 없음).

실행: PYTHONPATH=. uv run python scripts/_m0_prereg.py
"""
from __future__ import annotations

import csv
import json
import random
from pathlib import Path

REPO = Path("/Users/baek/petcam-lab")
DS = REPO / "storage" / "dataset-203"
EXP = REPO / "experiments"
OUT = EXP / "m0-montage"

# ── GT (manifest = 로컬 SOT, 0609 2차 정정 반영) ─────────────────────────────
rows = list(csv.DictReader(open(DS / "manifest.csv")))
gt = {r["clip_id"][:8]: r["gt"] for r in rows}
fname = {r["clip_id"][:8]: r["filename"] for r in rows}
full_id = {r["clip_id"][:8]: r["clip_id"] for r in rows}

# ── Sonnet frames 정오답 맵 (P1 jsonl, raw 컨벤션 = _score_frames_models.py) ──
nn_to_c8 = {
    d.name: json.loads((d / "meta.json").read_text())["src"].split("__")[-1].split(".")[0]
    for d in (EXP / "eval-frames-claude").glob("sample-*") if d.is_dir()
}
to_c8 = lambda s: nn_to_c8.get(s, s.replace("sample-", ""))
sonnet: dict[str, str] = {}
for line in (EXP / "eval-frames-full" / "sonnet46_blind.jsonl").read_text().splitlines():
    if line.strip():
        r = json.loads(line)
        sonnet[to_c8(r["sample"])] = r["action"]
ok = {c8: (sonnet.get(c8) == g) for c8, g in gt.items()}

micro = [c8 for c8, g in gt.items() if g in ("drinking", "eating_prey", "eating_paste")]
assert len(micro) == 55, f"micro55 != {len(micro)}"

# chemoreception/moving 경계 = 0609 GT정정 cam-motion drinking→moving 4건
BOUNDARY = sorted(["ff1ecb03", "05da625c", "2420abd8", "987c7b5d"])
assert all(gt[b] == "moving" for b in BOUNDARY), "경계 클립 GT가 moving이 아님 — manifest 확인"


def pick(cls: str, correct: bool, k: int, exclude: set[str]) -> list[str]:
    """클래스+정오답 조건 후보를 c8 정렬 후 앞에서 k건 (결정론)."""
    cand = sorted(c8 for c8, g in gt.items()
                  if g == cls and ok[c8] == correct and c8 not in exclude)
    return cand[:k]


chosen: list[tuple[str, str]] = []  # (c8, bucket)
used: set[str] = set()


def take(c8s: list[str], bucket: str) -> None:
    for c8 in c8s:
        chosen.append((c8, bucket))
        used.add(c8)


# micro 12건 — 클래스별 정2+오2 (부족 시 반대쪽에서 보충, 로그)
for cls in ("drinking", "eating_prey", "eating_paste"):
    got_c = pick(cls, True, 2, used)
    got_w = pick(cls, False, 2, used)
    short = 4 - len(got_c) - len(got_w)
    if short > 0:  # 한쪽 부족 → 다른 쪽에서 보충
        pool = pick(cls, True, 4, used | set(got_c) | set(got_w)) + \
               pick(cls, False, 4, used | set(got_c) | set(got_w))
        got_w += pool[:short]
        print(f"⚠️ {cls}: 정오 2/2 불충족 → {short}건 보충")
    take(got_c, f"micro/{cls}/frames-Y")
    take(got_w, f"micro/{cls}/frames-N")

# 일반 8건
take(BOUNDARY[:2], "general/moving-boundary(chemoreception)")
take(pick("moving", True, 1, used), "general/moving/frames-Y")
take(pick("moving", False, 1, used), "general/moving/frames-N")
take(pick("shedding", True, 2, used), "general/shedding/frames-Y")
take(pick("shedding", False, 1, used), "general/shedding/frames-N")
take(pick("hand_feeding", True, 1, used), "general/hand_feeding")

assert len(chosen) == 20, f"선정 {len(chosen)}건 != 20"

# blind 번호 고정 (seed 42 — 폴더 순서로 클래스 패턴 안 보이게)
random.seed(42)
order = list(range(20))
random.shuffle(order)
samples = []
for blind_idx, (c8, bucket) in zip(order, chosen):
    samples.append({
        "sample": f"sample-{blind_idx + 1:02d}",
        "clip8": c8,
        "clip_id": full_id[c8],
        "filename": fname[c8],          # 파일 탐색은 manifest 기준 (.mov 포함)
        "gt": gt[c8],
        "bucket": bucket,
        "sonnet_frames_pred": sonnet.get(c8),
        "sonnet_frames_correct": ok[c8],
    })
samples.sort(key=lambda s: s["sample"])

OUT.mkdir(parents=True, exist_ok=True)
out_path = OUT / "sample_list.json"
out_path.write_text(json.dumps(
    {"phase": "M0", "created": "2026-06-12", "seed": 42, "n": 20,
     "policy": "experiment-claude-montage-v2.md §4-2 stratified — 고정 후 불변",
     "samples": samples}, ensure_ascii=False, indent=2))

print(f"✅ {out_path} ({len(samples)}건)\n")
print(f"{'sample':10s} {'clip8':9s} {'GT':13s} {'SonnetF':9s} bucket")
for s in samples:
    print(f"{s['sample']:10s} {s['clip8']:9s} {s['gt']:13s} "
          f"{'Y' if s['sonnet_frames_correct'] else 'N':9s} {s['bucket']}")
mc = sum(1 for s in samples if s["bucket"].startswith("micro"))
yc = sum(1 for s in samples if s["sonnet_frames_correct"])
print(f"\nmicro {mc} / general {20 - mc} · Sonnet frames 정답 {yc} / 오답 {20 - yc}")

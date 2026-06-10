"""P2 레버 A — 모션 키프레임 추출 (입력표현 ablation).

가설: Fable 의 남은 →moving 오답 = 결정적순간(혀접촉/먹이타격)이 균등 N=10 샘플
  사이로 샜다. 모션 피크 주변을 집중 샘플하면 그 순간이 잡힌다.

대상: fable5_blind 오답 중 gt∈{eating_prey,eating_paste,shedding} (전부 →moving) + 대조군.
방법: motion_series(프레임차분) → N=20 = 균등앵커 10 + 모션피크 10 (시간 커버리지 +
  결정적순간 둘 다 확보). 풀해상도 1024px 개별 jpg.
출력: experiments/eval-frames-p2/sample-{c8}/f_001..020.jpg + meta.json(gt 숨김).
"""
from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

import cv2

REPO = Path("/Users/baek/petcam-lab")
DS = REPO / "storage" / "dataset-203"
EXP = REPO / "experiments"
OUT = EXP / "eval-frames-p2"
N = 20
ANCHORS = 10  # 균등 앵커 수 (나머지 N-ANCHORS = 모션피크)
LONG_EDGE = 1024
PROBE_EDGE = 256
TARGET_FPS = 10.0

# Fable preds
nn = {d.name: json.loads((d / "meta.json").read_text())["src"].split("__")[-1].split(".")[0]
      for d in (EXP / "eval-frames-claude").glob("sample-*") if d.is_dir()}
to_c8 = lambda s: nn.get(s, s.replace("sample-", ""))
fable = {}
for ln in (EXP / "eval-frames-full/fable5_blind.jsonl").read_text().splitlines():
    if ln.strip():
        r = json.loads(ln)
        fable[to_c8(r["sample"])] = r["action"]

rows = list(csv.DictReader(open(DS / "manifest.csv")))
gt = {r["clip_id"][:8]: r["gt"] for r in rows}
fname = {r["clip_id"][:8]: r["filename"] for r in rows}

TARGET_CLASSES = {"eating_prey", "eating_paste", "shedding"}
errors = [c8 for c8, g in gt.items() if g in TARGET_CLASSES and fable.get(c8) and fable[c8] != g]
# 대조군: 같은 클래스 정답 (클래스별 균형, 결정론적 — clip8 역순정렬 상위)
correct = [c8 for c8, g in gt.items() if g in TARGET_CLASSES and fable.get(c8) == g]
by_cls = {}
for c8 in sorted(correct, key=lambda c: c[::-1]):
    by_cls.setdefault(gt[c8], []).append(c8)
control = []
for cls in sorted(by_cls):  # 클래스당 최대 3
    control += by_cls[cls][:3]

print(f"오답셋 {len(errors)}건: {[(c, gt[c], '→'+fable[c]) for c in errors]}")
print(f"대조군 {len(control)}건(정답): {[(c, gt[c]) for c in control]}")


def motion_peaks_timestamps(path: Path, dur: float) -> list[float]:
    """프레임차분 시계열 → 상위 모션 구간의 타임스탬프 (N-ANCHORS개)."""
    cap = cv2.VideoCapture(str(path))
    series: list[tuple[float, float]] = []  # (t_s, motion)
    try:
        if not cap.isOpened():
            return []
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        step = max(1, round(fps / TARGET_FPS))
        prev = None
        idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if idx % step == 0:
                h, w = frame.shape[:2]
                sc = PROBE_EDGE / max(h, w)
                small = cv2.resize(frame, (max(1, int(w * sc)), max(1, int(h * sc))))
                g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                if prev is not None:
                    t = (idx / fps)
                    series.append((t, float(cv2.absdiff(g, prev).mean())))
                prev = g
            idx += 1
    finally:
        cap.release()
    if not series:
        return []
    # 상위 모션 프레임을 시간 간격 최소 0.8s 로 NMS (한 버스트에 몰리지 않게)
    ranked = sorted(series, key=lambda x: -x[1])
    picked: list[float] = []
    for t, _m in ranked:
        if all(abs(t - p) >= 0.8 for p in picked):
            picked.append(t)
        if len(picked) >= N - ANCHORS:
            break
    return sorted(picked)


def probe_dur(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 60.0


def extract_at(path: Path, ts: list[float], outdir: Path) -> int:
    """주어진 타임스탬프들에서 풀해상도 프레임 추출 → f_001.. 순번(시간순)."""
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("f_*.jpg"):
        old.unlink()
    for i, t in enumerate(sorted(ts), 1):
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
             "-vf", f"scale={LONG_EDGE}:{LONG_EDGE}:force_original_aspect_ratio=decrease",
             "-q:v", "3", str(outdir / f"f_{i:03d}.jpg")],
            capture_output=True)
    return len(list(outdir.glob("f_*.jpg")))


def build(c8: str, role: str) -> None:
    fn = fname.get(c8)
    src = DS / fn if fn else None
    if not src or not src.exists():
        print(f"  ⚠️ {c8} 소스 없음 ({fn})")
        return
    dur = probe_dur(src)
    anchors = [dur * (i + 0.5) / ANCHORS for i in range(ANCHORS)]  # 균등 앵커
    peaks = motion_peaks_timestamps(src, dur)
    ts = sorted(set(round(t, 2) for t in anchors + peaks))
    outdir = OUT / f"sample-{c8}"
    got = extract_at(src, ts, outdir)
    (outdir / "meta.json").write_text(json.dumps(
        {"gt": gt[c8], "c8": c8, "src": fn, "n": got, "anchors": ANCHORS,
         "peaks": len(peaks), "role": role}))
    print(f"  {role:5s} {c8} gt={gt[c8]:13s} dur={dur:4.0f}s peaks={len(peaks):2d} → {got}장")


OUT.mkdir(parents=True, exist_ok=True)
print("\n=== 추출 (모션 키프레임 N=20 = 균등10 + 모션피크10) ===")
for c8 in errors:
    build(c8, "ERR")
for c8 in control:
    build(c8, "CTRL")
print(f"\n완료 → {OUT}")

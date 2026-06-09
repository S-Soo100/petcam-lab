"""drinking 가설2 PoC v0 — 프레임차분 motion energy 로 시간축 신호 탐색.

목적: detector 없이, "한 지점 정착 + 미세진동(혀 낼름)" 패턴이
  drinking 을 chemoreception / grooming / moving 과 시간축에서 가르는지 본다.
  (Gemini key 불필요, OpenCV 프레임차분만 사용)

그룹 (manifest.csv 의 gt / pred_v361 / source 로 자동 분류):
  A_drink_hit        gt=drinking pred=drinking                  맞힌 것 (주로 폰 고화질)
  B_drink_miss_cam   gt=drinking pred=moving  source=cam-motion ★ 운영환경서 놓친 drinking
  C_drink_miss_other gt=drinking pred=moving  (그 외 source)
  D_drink_to_paste   gt=drinking pred=eating_paste
  E_false_pos        gt=moving   pred=drinking                  chemoreception 을 drinking 오탐
  F_hardneg_face     'licking own face' 표식                    혀 쓰지만 drinking 아님 (대조군)
  G_moving_ctrl_cam  gt=moving   pred=moving  source=cam-motion 정상 이동 대조 (최대 3개)

지표 (클립별):
  dur_s     영상 길이(초)
  mean_raw  평균 프레임차분(절대값) — 클수록 전체 움직임 많음 (이동=큼, 정지=0)
  settle_s  정규화 motion<0.3 연속 최장 구간(초) — "한 곳 체류" 길이
  micro     그 정착 구간의 정규화 motion 평균 — 0=완전정지, 클수록 미세 떨림(혀?)
  spark     정규화 motion 스파크라인 (시간축 모양 눈으로 보기)

해석 가이드: drinking 후보면 settle_s 가 5~6초+ 이고 micro 가 0보다 또렷(정착했지만 떨림).
  완전정지(자는중)면 micro≈0 / 이동(moving)이면 settle_s 짧음 / mean_raw 큼.
  ⚠️ v0 는 판정기가 아니라 "시계열 모양이 그룹별로 다른가"를 보는 탐침. 과해석 금지.

실행: PYTHONPATH=. uv run python experiments/drinking-motion-poc/motion_energy.py
"""

from __future__ import annotations

import csv
from pathlib import Path

import cv2

REPO = Path(__file__).resolve().parents[2]
DATASET = REPO / "storage" / "dataset-203"
MANIFEST = DATASET / "manifest.csv"
OUT = REPO / "experiments" / "drinking-motion-poc"
TS_DIR = OUT / "timeseries"

TARGET_FPS = 10.0   # 모든 클립을 ~10fps 로 균일 샘플 → fps 차이 정규화
LONG_EDGE = 256     # 다운샘플 긴 변 (4K 도 256 으로 줄여 차분; 노이즈/속도 균형)
LOW_THR = 0.3       # 정규화 motion 이 이 아래면 '저모션(정착 후보)'
SPARK = "▁▂▃▄▅▆▇█"
MAX_CTRL = 3        # G_moving_ctrl_cam 표본 상한


def group_of(row: dict) -> str | None:
    gt, pred, src = row["gt"], row["pred_v361"], row["source"]
    key = (row.get("r2_key", "") + " " + row.get("filename", "")).lower()
    if "licking-own-face" in key or "not-drinking" in key:
        return "F_hardneg_face"
    if gt == "drinking" and pred == "drinking":
        return "A_drink_hit"
    if gt == "drinking" and pred == "moving" and src == "cam-motion":
        return "B_drink_miss_cam"
    if gt == "drinking" and pred == "moving":
        return "C_drink_miss_other"
    if gt == "drinking" and pred == "eating_paste":
        return "D_drink_to_paste"
    if gt == "moving" and pred == "drinking":
        return "E_false_pos"
    if gt == "moving" and pred == "moving" and src == "cam-motion":
        return "G_moving_ctrl_cam"
    return None


def motion_series(path: Path) -> list[float]:
    """프레임차분 시계열 (인접 샘플 프레임 간 mean abs diff), ~TARGET_FPS."""
    cap = cv2.VideoCapture(str(path))
    series: list[float] = []
    try:
        if not cap.isOpened():
            return series
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
                sc = LONG_EDGE / max(h, w)
                small = cv2.resize(frame, (max(1, int(w * sc)), max(1, int(h * sc))))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                if prev is not None:
                    series.append(float(cv2.absdiff(gray, prev).mean()))
                prev = gray
            idx += 1
    finally:
        cap.release()
    return series


def spark(norm: list[float]) -> str:
    if not norm:
        return ""
    if len(norm) > 60:  # 너무 길면 60칸으로 버킷 max
        b = len(norm) / 60
        norm = [max(norm[int(i * b):int((i + 1) * b)] or [0.0]) for i in range(60)]
    return "".join(SPARK[min(7, int(v * 8))] for v in norm)


def analyze(series: list[float]) -> dict:
    if not series:
        return {"dur_s": 0.0, "mean_raw": 0.0, "settle_s": 0.0, "micro": 0.0, "spark": ""}
    mx = max(series) or 1.0
    norm = [v / mx for v in series]
    best = cur = 0
    best_vals: list[float] = []
    cur_vals: list[float] = []
    for v in norm:
        if v < LOW_THR:
            cur += 1
            cur_vals.append(v)
            if cur > best:
                best, best_vals = cur, list(cur_vals)
        else:
            cur, cur_vals = 0, []
    micro = (sum(best_vals) / len(best_vals)) if best_vals else 0.0
    return {
        "dur_s": len(series) / TARGET_FPS,
        "mean_raw": sum(series) / len(series),
        "settle_s": best / TARGET_FPS,
        "micro": micro,
        "spark": spark(norm),
    }


def main() -> int:
    TS_DIR.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(MANIFEST.open()))

    targets: list[tuple[str, dict]] = []
    ctrl = 0
    for r in rows:
        g = group_of(r)
        if g is None:
            continue
        if g == "G_moving_ctrl_cam":
            ctrl += 1
            if ctrl > MAX_CTRL:
                continue
        targets.append((g, r))
    targets.sort(key=lambda t: (t[0], t[1]["clip_id"]))

    print(f"\n타겟 {len(targets)}건 분석 (TARGET_FPS={TARGET_FPS}, LONG_EDGE={LONG_EDGE}, LOW_THR={LOW_THR})\n")
    hdr = f"{'group':18s} {'clip':9s} {'dur':>5s} {'meanRaw':>7s} {'settle':>6s} {'micro':>5s}  spark"
    print(hdr)
    print("-" * len(hdr) + "-" * 40)

    summary: dict[str, list[dict]] = {}
    for g, r in targets:
        path = DATASET / r["filename"]
        if not path.exists():
            print(f"{g:18s} {r['clip_id'][:8]:9s}  MISSING {r['filename']}")
            continue
        ser = motion_series(path)
        m = analyze(ser)
        # 시계열 csv 저장 (사용자와 같이 들여다볼 수 있게)
        (TS_DIR / f"{g}__{r['clip_id'][:8]}.csv").write_text(
            "t_s,motion_raw\n" + "\n".join(f"{i / TARGET_FPS:.2f},{v:.4f}" for i, v in enumerate(ser))
        )
        print(f"{g:18s} {r['clip_id'][:8]:9s} {m['dur_s']:5.1f} {m['mean_raw']:7.2f} "
              f"{m['settle_s']:6.1f} {m['micro']:5.2f}  {m['spark']}")
        summary.setdefault(g, []).append(m)

    print("\n=== 그룹 평균 ===")
    print(f"{'group':18s} {'n':>3s} {'meanRaw':>7s} {'settle_s':>8s} {'micro':>6s}")
    for g in sorted(summary):
        ms = summary[g]
        n = len(ms)
        print(f"{g:18s} {n:3d} {sum(x['mean_raw'] for x in ms) / n:7.2f} "
              f"{sum(x['settle_s'] for x in ms) / n:8.1f} {sum(x['micro'] for x in ms) / n:6.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Step 1.5 — Tracker 품질 게이트 평가.

trajectories/*.json 21건 정량 메트릭 + 시각 모자이크.

GT bbox 가 없으므로 절대 IoU 는 못 구함. proxy 메트릭으로:
- ok_rate: CSRT 자체 confidence (낮은 신뢰도 — drift 해도 1.0 나오는 경우 있음)
- center_drift_norm: (last center - init center) / frame 대각선. 도마뱀이 정지면 0 근처.
  도마뱀이 움직였는데 bbox 가 따라가지 못하면 작음 (drift). 따라갔으면 큼.
- area_change_ratio: last bbox area / init bbox area. 1.0 근처면 stable, 크면 inflate.
- motion_var_norm: center 표준편차 합 / frame 대각선. 박스가 진동했는지 vs stuck.

정성 검증은 mosaic.jpg 로 사용자가 직접. init vs last 좌우 비교.

출력:
- experiments/tracking-poc/tracker-quality.csv
- experiments/tracking-poc/tracker-mosaic.jpg

참고: specs/experiment-tracking-vlm-input.md  Step 1.5
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TRAJ_DIR = ROOT / "experiments/tracking-poc/trajectories"
OUT_DIR = ROOT / "experiments/tracking-poc"


def compute_metrics(traj_data: dict) -> dict:
    tr = traj_data["trajectory"]
    w, h = traj_data["video"]["size"]
    diag = math.sqrt(w * w + h * h)

    ok_frames = [t for t in tr if t["ok"] and t["bbox_xywh"]]
    ok_rate = sum(1 for t in tr if t["ok"]) / len(tr)

    if len(ok_frames) < 2:
        return {"ok_rate": ok_rate, "frames": len(tr)}

    centers = []
    areas = []
    for t in ok_frames:
        x, y, bw, bh = t["bbox_xywh"]
        centers.append((x + bw / 2, y + bh / 2))
        areas.append(bw * bh)

    cx0, cy0 = centers[0]
    cxN, cyN = centers[-1]
    center_drift_px = math.sqrt((cxN - cx0) ** 2 + (cyN - cy0) ** 2)
    center_drift_norm = center_drift_px / diag

    area_change_ratio = areas[-1] / areas[0] if areas[0] > 0 else None

    xs = np.array([c[0] for c in centers])
    ys = np.array([c[1] for c in centers])
    motion_var_norm = (xs.std() + ys.std()) / diag

    return {
        "ok_rate": ok_rate,
        "center_drift_norm": center_drift_norm,
        "area_change_ratio": area_change_ratio,
        "motion_var_norm": motion_var_norm,
        "frames": len(tr),
    }


def build_mosaic(rows_data: list[dict], cols: int = 3) -> np.ndarray:
    """각 clip 의 init.jpg + last.jpg 좌우 합친 cell → grid.

    cell 상단에 clip_id 8자리 + 메트릭 (drift, motion_var, ok_rate).
    """
    cells = []
    cell_h, cell_w = 200, 360
    for r in rows_data:
        cid = r["clip_id"]
        init = cv2.imread(str(TRAJ_DIR / f"{cid}_init.jpg"))
        last = cv2.imread(str(TRAJ_DIR / f"{cid}_last.jpg"))
        if init is None or last is None:
            continue
        init_s = cv2.resize(init, (cell_w, cell_h))
        last_s = cv2.resize(last, (cell_w, cell_h))
        cell = np.concatenate([init_s, last_s], axis=1)

        text = (
            f"{cid[:8]} drift={r.get('center_drift_norm', 0):.2f} "
            f"motion={r.get('motion_var_norm', 0):.2f} "
            f"ok={r.get('ok_rate', 0):.2f}"
        )
        cv2.rectangle(cell, (0, 0), (cell.shape[1], 22), (0, 0, 0), -1)
        cv2.putText(
            cell, text, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1
        )
        cells.append(cell)

    if not cells:
        return np.zeros((cell_h, cell_w * 2, 3), dtype=np.uint8)
    rows = math.ceil(len(cells) / cols)
    full_h = cells[0].shape[0]
    full_w = cells[0].shape[1]
    canvas = np.zeros((rows * full_h, cols * full_w, 3), dtype=np.uint8)
    for i, c in enumerate(cells):
        r, col = i // cols, i % cols
        canvas[r * full_h : (r + 1) * full_h, col * full_w : (col + 1) * full_w] = c
    return canvas


def main():
    json_paths = sorted(TRAJ_DIR.glob("*.json"))
    rows = []
    for p in json_paths:
        try:
            d = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        if "trajectory" not in d:
            continue
        m = compute_metrics(d)
        m["clip_id"] = d["clip_id"]
        m["init_score"] = d["init"]["score"]
        m["init_area_ratio"] = d["init"]["area_ratio"]
        rows.append(m)

    cols = [
        "clip_id",
        "ok_rate",
        "center_drift_norm",
        "area_change_ratio",
        "motion_var_norm",
        "frames",
        "init_score",
        "init_area_ratio",
    ]
    out_csv = OUT_DIR / "tracker-quality.csv"
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"[csv] {out_csv} ({len(rows)} rows)")

    # 시각: motion_var 가 큰 (도마뱀이 많이 움직인) 클립 먼저 보이게 정렬
    rows_sorted = sorted(rows, key=lambda r: -r.get("motion_var_norm", 0))
    mosaic = build_mosaic(rows_sorted, cols=3)
    out_mosaic = OUT_DIR / "tracker-mosaic.jpg"
    cv2.imwrite(str(out_mosaic), mosaic, [cv2.IMWRITE_JPEG_QUALITY, 80])
    print(f"[mosaic] {out_mosaic} ({mosaic.shape[1]}x{mosaic.shape[0]})")

    # 요약 출력
    print("\n--- Top 10 motion_var_norm (도마뱀이 화면에서 많이 움직인 케이스) ---")
    for r in rows_sorted[:10]:
        print(
            f"  {r['clip_id'][:8]}  "
            f"motion={r.get('motion_var_norm', 0):.3f}  "
            f"drift={r.get('center_drift_norm', 0):.3f}  "
            f"area_x={r.get('area_change_ratio') or 0:.2f}  "
            f"ok={r.get('ok_rate', 0):.2f}"
        )
    print("\n--- Bottom 5 motion_var_norm (도마뱀 정지 추정) ---")
    for r in rows_sorted[-5:]:
        print(
            f"  {r['clip_id'][:8]}  "
            f"motion={r.get('motion_var_norm', 0):.3f}  "
            f"drift={r.get('center_drift_norm', 0):.3f}  "
            f"area_x={r.get('area_change_ratio') or 0:.2f}"
        )


if __name__ == "__main__":
    main()

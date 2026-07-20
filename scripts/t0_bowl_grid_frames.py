"""T0: 카메라별 대표 프레임에 4×4 그리드를 그려 owner의 그릇 셀 지정을 돕는다.

좌표계 = spatial_dwell 생성자와 동일: cells[row][col], row=y(위→아래), col=x(왼→오).
production DB 는 SELECT 만. (하드 계약 §1)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path[:0] = [str(_REPO_ROOT)]

GRID = 4
OUT_DIR = _REPO_ROOT / "storage" / "t0-probe" / "frames"


def draw_grid_overlay(frame: np.ndarray) -> np.ndarray:
    """4×4 그리드 선 + r{row}c{col} 라벨을 복사본에 그린다."""
    out = frame.copy()  # 원본 보존 (rationale: 호출자 프레임 재사용 안전)
    h, w = out.shape[:2]
    for i in range(1, GRID):
        cv2.line(out, (w * i // GRID, 0), (w * i // GRID, h), (0, 255, 255), 2)
        cv2.line(out, (0, h * i // GRID), (w, h * i // GRID), (0, 255, 255), 2)
    for r in range(GRID):
        for c in range(GRID):
            x = c * w // GRID + 10
            y = r * h // GRID + 40
            cv2.putText(out, f"r{r}c{c}", (x, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3)
    return out


def main() -> int:
    from backend.r2_uploader import get_r2_bucket, get_r2_client
    from backend.supabase_client import get_supabase_client

    client = get_supabase_client()
    cams = client.table("cameras").select("id,name").execute().data
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    r2 = get_r2_client()
    bucket = get_r2_bucket()

    for cam in cams:
        # 카메라별 최신 클립 1개 (고정캠이라 배치 대표 가능)
        rows = (client.table("motion_clips")
                .select("id,r2_key")
                .eq("camera_id", cam["id"])
                .order("started_at", desc=True)
                .limit(1).execute().data)
        if not rows:
            print(f"[skip] {cam['name']}: 클립 없음")
            continue
        with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
            r2.download_file(bucket, rows[0]["r2_key"], tmp.name)
            cap = cv2.VideoCapture(tmp.name)
            try:
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                # sparse-keyframe H.264 는 indexed seek 실패 이력 → 순차 read 로 중간 도달
                mid = max(0, total // 2)
                frame = None
                for _ in range(mid + 1):
                    ok, f = cap.read()
                    if not ok:
                        break
                    frame = f
            finally:
                cap.release()
        if frame is None:
            print(f"[skip] {cam['name']}: 디코드 실패")
            continue
        safe = cam["name"].replace(" ", "_").replace("(", "").replace(")", "")
        out_path = OUT_DIR / f"{safe}.jpg"
        cv2.imwrite(str(out_path), draw_grid_overlay(frame))
        print(f"[ok] {cam['name']} -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

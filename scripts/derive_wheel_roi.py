"""wheel ROI profile v1 도출 (1회성 데이터 준비 — 시험지 면제).

known wheel GT clip(07-22) 프레임에서 육안 + 모션에너지 히트맵으로 wheel 영역을 국소화한다.
SELECT-only + R2 read-only. 모든 media 는 experiments/.../_tmp (gitignored) 에 두고 finalize 시 정리.

사용:
  # 1) dump — 대표 프레임 + 모션에너지 히트맵을 _tmp 에 저장 (육안 확인용)
  PYTHONPATH=. uv run python scripts/derive_wheel_roi.py --dump --clips 4
  # 2) finalize — normalized ROI 확정 → ROI-PREVIEW.png + wheel-roi-profile-v1.json, _tmp 정리
  PYTHONPATH=. uv run python scripts/derive_wheel_roi.py --finalize --x 0.30 --y 0.30 --w 0.30 --h 0.35
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from backend.r2_uploader import get_r2_bucket, get_r2_client
from backend.supabase_client import get_supabase_client
from scripts.wheel_shadow.io_utils import download_clip, extract_adaptive_frames

REPO = Path(__file__).resolve().parent.parent
EXP = REPO / "experiments" / "wheel-episode-dedup-shadow"
TMP = EXP / "_tmp"
CAMERA_NAME = "P4 Cam (dev)"


def resolve_camera(sb) -> str:
    rows = sb.table("cameras").select("id,name").eq("name", CAMERA_NAME).execute().data
    if len(rows) != 1:
        raise SystemExit(f"HOLD: camera name {CAMERA_NAME!r} not unique ({len(rows)})")
    return rows[0]["id"]


def known_wheel_gt_clips(sb, cam_id: str) -> list[dict]:
    ids: set[str] = set()
    for col in ("current_gt", "initial_gt"):
        rows = (
            sb.table("motion_clip_labeling_sessions")
            .select(f"clip_id,{col}")
            .filter(f"{col}->>enrichment_object", "eq", "wheel")
            .execute()
            .data
        )
        ids.update(r["clip_id"] for r in rows)
    if not ids:
        return []
    clips = (
        sb.table("motion_clips")
        .select("id,started_at,r2_key,camera_id")
        .in_("id", list(ids))
        .eq("camera_id", cam_id)
        .order("started_at")
        .execute()
        .data
    )
    return [c for c in clips if c.get("r2_key")]


def _motion_heatmap(frames: list[np.ndarray]) -> np.ndarray:
    """연속 프레임 absdiff 누적 → 정규화 히트맵(0~255 uint8, 단일 채널)."""
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) for f in frames]
    h, w = grays[0].shape
    acc = np.zeros((h, w), dtype=np.float32)
    for a, b in zip(grays, grays[1:]):
        if b.shape != (h, w):
            b = cv2.resize(b, (w, h))
        acc += np.abs(a - b)
    if acc.max() > 0:
        acc = acc / acc.max() * 255.0
    return acc.astype(np.uint8)


def dump(n_clips: int) -> None:
    sb = get_supabase_client()
    r2 = get_r2_client()
    bucket = get_r2_bucket()
    cam_id = resolve_camera(sb)
    clips = known_wheel_gt_clips(sb, cam_id)
    print(f"known wheel GT clips = {len(clips)} (dump {min(n_clips, len(clips))})")
    if not clips:
        raise SystemExit("HOLD: no known wheel GT clips")
    TMP.mkdir(parents=True, exist_ok=True)
    # 여러 clip 프레임을 모아 aggregate 히트맵 + 대표 프레임 저장
    agg_frames: list[np.ndarray] = []
    base_frame = None
    picked = clips[:: max(1, len(clips) // n_clips)][:n_clips]
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        for i, c in enumerate(picked):
            mp4 = tdp / f"clip_{i}.mp4"
            if not download_clip(r2, bucket, c["r2_key"], mp4):
                print(f"  clip {i} download fail (skip)")
                continue
            frames_dir = tdp / f"frames_{i}"
            fps = extract_adaptive_frames(mp4, frames_dir)
            imgs = [cv2.imread(str(p)) for p in fps]
            imgs = [im for im in imgs if im is not None]
            if not imgs:
                continue
            agg_frames.extend(imgs)
            if base_frame is None:
                base_frame = imgs[len(imgs) // 2]
            # clip 별 대표 프레임 저장 (육안)
            cv2.imwrite(str(TMP / f"sample_clip{i}_{c['started_at'][11:19].replace(':','')}.jpg"),
                        imgs[len(imgs) // 2])
            print(f"  clip {i} {c['started_at']} frames={len(imgs)}")
        # aggregate 모션 히트맵 오버레이
        if base_frame is not None and len(agg_frames) > 1:
            heat = _motion_heatmap(agg_frames)
            heat = cv2.resize(heat, (base_frame.shape[1], base_frame.shape[0]))
            heat_color = cv2.applyColorMap(heat, cv2.COLORMAP_JET)
            overlay = cv2.addWeighted(base_frame, 0.55, heat_color, 0.45, 0)
            cv2.imwrite(str(TMP / "motion_heatmap.jpg"), overlay)
            cv2.imwrite(str(TMP / "base_frame.jpg"), base_frame)
            print(f"base frame size = {base_frame.shape[1]}x{base_frame.shape[0]}")
    print(f"dumped → {TMP}")


def finalize(x: float, y: float, w: float, h: float) -> None:
    base = TMP / "base_frame.jpg"
    if not base.is_file():
        raise SystemExit("HOLD: run --dump first (base_frame.jpg 없음)")
    img = cv2.imread(str(base))
    H, W = img.shape[:2]
    px, py, pw, ph = int(x * W), int(y * H), int(w * W), int(h * H)
    preview = img.copy()
    cv2.rectangle(preview, (px, py), (px + pw, py + ph), (0, 0, 255), 3)
    cv2.putText(preview, "wheel_roi_v1", (px, max(20, py - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    cv2.imwrite(str(EXP / "ROI-PREVIEW.png"), preview)

    profile = {
        "profile_id": "wheel_roi_profile_v1",
        "camera_name": CAMERA_NAME,
        "roi_normalized": {"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)},
        "frame_size": {"width": W, "height": H},
        "grouping_params": {
            "max_gap_sec": 600.0,
            "wheel_motion_floor": 0.06,
            "hamming_threshold": 10,
            "motion_tolerance": 0.06,
            "novelty_min_hamming": 8,
        },
        "provenance": {
            "derived_from": "known wheel GT clips (enrichment_object=wheel, 2026-07-22, P4 Cam (dev))",
            "method": "visual localization + aggregate motion-energy heatmap on wheel GT frames",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "provisional_shadow",
            "note": "owner 확인 전 production 계약 아님. shadow 전용 provisional ROI.",
        },
    }
    (EXP / "wheel-roi-profile-v1.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # temp media 정리
    if TMP.exists():
        shutil.rmtree(TMP)
    print(f"ROI-PREVIEW.png + wheel-roi-profile-v1.json 작성, _tmp 정리 완료. ROI=({x},{y},{w},{h})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--clips", type=int, default=4)
    ap.add_argument("--finalize", action="store_true")
    ap.add_argument("--x", type=float)
    ap.add_argument("--y", type=float)
    ap.add_argument("--w", type=float)
    ap.add_argument("--h", type=float)
    a = ap.parse_args()
    if a.dump:
        dump(a.clips)
    elif a.finalize:
        for v in (a.x, a.y, a.w, a.h):
            if v is None:
                raise SystemExit("finalize 는 --x --y --w --h 필요")
        finalize(a.x, a.y, a.w, a.h)
    else:
        ap.error("--dump 또는 --finalize 필요")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

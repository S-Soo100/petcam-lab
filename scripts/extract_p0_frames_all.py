"""97 P0 clip 모두 8 frame 추출 → pilot-frames/{clip_id}/ 에 저장.

이미 추출된 clip은 skip (resume 지원).
Strategy C (multi-frame input) 평가용.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import cv2  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from PIL import Image  # noqa: E402

from backend.local_track_a import (  # noqa: E402
    LocalTrackAError,
    download_r2_clip_to_temp,
)

EVAL_JSONL = REPO_ROOT / "storage" / "local-track-a" / "eval" / "local-track-a-eval.jsonl"
PILOT_DIR = REPO_ROOT / "storage" / "track-a-eval" / "pilot-frames"
FRAMES_PER_CLIP = 8


def extract_uniform_frames(video_path: Path, n: int) -> list[Image.Image]:
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise LocalTrackAError(f"video open 실패: {video_path}")
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total <= 0:
            raise LocalTrackAError(f"frame_count=0: {video_path}")
        indices = (
            [int(i * total / n) for i in range(n)] if total >= n else list(range(total))
        )
        frames: list[Image.Image] = []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(Image.fromarray(rgb))
        if not frames:
            raise LocalTrackAError(f"frame 추출 실패: {video_path}")
        return frames
    finally:
        cap.release()


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    PILOT_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    for line in EVAL_JSONL.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            if rec.get("ok") and rec["gt_action"] != "moving":
                rows.append(rec)
        except json.JSONDecodeError:
            continue
    print(f"P0 clips: {len(rows)}")

    n_ok = n_skip = n_fail = 0
    for i, rec in enumerate(rows, 1):
        clip_id = rec["clip_id"]
        gt = rec["gt_action"]
        clip_dir = PILOT_DIR / clip_id
        existing = list(clip_dir.glob("frame_*.jpg")) if clip_dir.exists() else []
        if len(existing) >= FRAMES_PER_CLIP:
            n_skip += 1
            continue
        clip_dir.mkdir(parents=True, exist_ok=True)
        print(f"[{i}/{len(rows)}] {clip_id[:8]} gt={gt:13s} 추출 중...")
        mp4_path = None
        try:
            mp4_path = download_r2_clip_to_temp(rec["r2_key"])
            frames = extract_uniform_frames(mp4_path, FRAMES_PER_CLIP)
            for idx, frame in enumerate(frames):
                fp = clip_dir / f"frame_{idx:02d}.jpg"
                frame.save(fp, format="JPEG", quality=88, optimize=True)
            n_ok += 1
            print(f"  OK {len(frames)} frames")
        except Exception as exc:  # noqa: BLE001
            n_fail += 1
            print(f"  FAIL: {type(exc).__name__}: {exc}")
        finally:
            if mp4_path is not None:
                try:
                    mp4_path.unlink(missing_ok=True)
                except OSError:
                    pass

    print(f"\n완료 — ok={n_ok} skip={n_skip} fail={n_fail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Track A Claude pilot — 10건 stratified small-N 평가용 frame 추출.

scope:
- 159건 평가셋 중 P0 라벨 (drinking, eating_paste, shedding, defecating, eating_prey)
- 라벨당 2건 stratified sample (seed=42, 재현 가능)
- 각 clip에서 60초 영상을 8 frame으로 균등 추출 → jpg 저장
- 매핑 jsonl 생성 → Claude Code 인터랙티브 평가용 입력

production Gemini와 달리 Claude는 video input 미지원이라 frame 8장 multi-image로 우회.
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
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


def extract_uniform_frames(video_path: Path, n: int) -> list[Image.Image]:
    """clip 길이와 무관하게 균등 간격으로 정확히 n장(또는 frame_count<n이면 전부) 추출."""
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
            raise LocalTrackAError(f"프레임 추출 실패: {video_path}")
        return frames
    finally:
        cap.release()

EVAL_JSONL = REPO_ROOT / "storage" / "local-track-a" / "eval" / "local-track-a-eval.jsonl"
PILOT_DIR = REPO_ROOT / "storage" / "track-a-eval" / "pilot-frames"
PILOT_MAPPING = REPO_ROOT / "storage" / "track-a-eval" / "pilot-mapping.jsonl"

P0_LABELS = ["drinking", "eating_paste", "shedding", "defecating", "eating_prey"]
SAMPLES_PER_LABEL = 2
FRAMES_PER_CLIP = 8
SEED = 42


def load_159_jsonl() -> list[dict]:
    rows: list[dict] = []
    for line in EVAL_JSONL.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("ok"):
            rows.append(rec)
    return rows


def stratified_sample(rows: list[dict]) -> list[dict]:
    rng = random.Random(SEED)
    by_gt: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_gt[r["gt_action"]].append(r)
    sample: list[dict] = []
    for label in P0_LABELS:
        cands = by_gt.get(label, [])
        if len(cands) < SAMPLES_PER_LABEL:
            print(f"WARN: {label} 후보 {len(cands)}건 < 요청 {SAMPLES_PER_LABEL}")
        rng.shuffle(cands)
        sample.extend(cands[:SAMPLES_PER_LABEL])
    return sample


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")

    if not EVAL_JSONL.exists():
        print(f"ERR: eval jsonl 없음: {EVAL_JSONL}")
        return 1

    rows = load_159_jsonl()
    print(f"159건 eval jsonl 로드: {len(rows)}건")
    sample = stratified_sample(rows)
    print(f"stratified pilot 샘플: {len(sample)}건 (P0 라벨당 {SAMPLES_PER_LABEL}건)")
    print(f"  분포: {dict((l, sum(1 for s in sample if s['gt_action'] == l)) for l in P0_LABELS)}")

    PILOT_DIR.mkdir(parents=True, exist_ok=True)
    PILOT_MAPPING.parent.mkdir(parents=True, exist_ok=True)

    n_ok = 0
    n_fail = 0
    with PILOT_MAPPING.open("w", encoding="utf-8") as f:
        for i, rec in enumerate(sample, 1):
            clip_id = rec["clip_id"]
            gt = rec["gt_action"]
            r2_key = rec["r2_key"]
            species_id = rec.get("species_id")
            clip_frame_dir = PILOT_DIR / clip_id
            clip_frame_dir.mkdir(parents=True, exist_ok=True)
            print(f"[{i}/{len(sample)}] {clip_id[:8]} gt={gt:13s} 처리 중...")

            mp4_path = None
            try:
                mp4_path = download_r2_clip_to_temp(r2_key)
                frames = extract_uniform_frames(mp4_path, FRAMES_PER_CLIP)
                frame_paths: list[str] = []
                for idx, frame in enumerate(frames):
                    fp = clip_frame_dir / f"frame_{idx:02d}.jpg"
                    frame.save(fp, format="JPEG", quality=88, optimize=True)
                    frame_paths.append(str(fp))
            except (LocalTrackAError, Exception) as exc:  # noqa: BLE001 — pilot은 계속 진행
                n_fail += 1
                print(f"  FAIL: {type(exc).__name__}: {exc}")
                continue
            finally:
                if mp4_path is not None:
                    try:
                        mp4_path.unlink(missing_ok=True)
                    except OSError:
                        pass

            entry = {
                "clip_id": clip_id,
                "gt_action": gt,
                "species_id": species_id,
                "r2_key": r2_key,
                "frame_paths": frame_paths,
                "n_frames": len(frame_paths),
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            n_ok += 1
            print(f"  OK — {len(frame_paths)} frames → {clip_frame_dir}")

    print()
    print(f"pilot 추출 완료: ok={n_ok} fail={n_fail}")
    print(f"매핑 jsonl: {PILOT_MAPPING}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

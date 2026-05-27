"""Mac mini local Track A smoke script.

DB에는 쓰지 않는다. 로컬 mp4 또는 R2 object 1건을 contact sheet로 바꾸고,
Ollama local VLM 결과를 `storage/local-track-a/*.json`에 저장한다.

실행:
    uv run python scripts/local_track_a_smoke.py --file storage/clips/sample.mp4
    uv run python scripts/local_track_a_smoke.py --r2-key clips/.../sample.mp4 --clip-id sample
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.local_track_a import (  # noqa: E402
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_URL,
    DEFAULT_OUTPUT_DIR,
    analyze_clip_file,
    download_r2_clip_to_temp,
)


def _parse_args() -> argparse.Namespace:
    load_dotenv(REPO_ROOT / ".env")
    output_dir = Path(os.getenv("LOCAL_TRACK_A_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))
    sample_fps = float(os.getenv("LOCAL_TRACK_A_SAMPLE_FPS", "1.0"))
    max_frames = int(os.getenv("LOCAL_TRACK_A_MAX_FRAMES", "60"))

    parser = argparse.ArgumentParser(description="local Track A smoke test")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="로컬 mp4 경로")
    source.add_argument("--r2-key", help="R2 object key")
    parser.add_argument("--clip-id", help="artifact clip_id. 기본값은 파일명 stem")
    parser.add_argument("--model", default=os.getenv("LOCAL_TRACK_A_MODEL", DEFAULT_MODEL))
    parser.add_argument(
        "--ollama-url",
        default=os.getenv("LOCAL_TRACK_A_OLLAMA_URL", DEFAULT_OLLAMA_URL),
    )
    parser.add_argument("--output-dir", type=Path, default=output_dir)
    parser.add_argument("--sample-fps", type=float, default=sample_fps)
    parser.add_argument("--max-frames", type=int, default=max_frames)
    parser.add_argument(
        "--thumb-width",
        type=int,
        default=int(os.getenv("LOCAL_TRACK_A_THUMB_WIDTH", "320")),
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=int(os.getenv("LOCAL_TRACK_A_TIMEOUT_SEC", "180")),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    video_path = args.file
    if args.r2_key:
        print(f"[1/4] R2 download: {args.r2_key}")
        video_path = download_r2_clip_to_temp(args.r2_key)
    if video_path is None or not video_path.is_file():
        raise SystemExit(f"mp4 파일 없음: {video_path}")

    print(f"[2/4] contact sheet + Ollama: {video_path}")
    result = analyze_clip_file(
        video_path,
        clip_id=args.clip_id,
        output_dir=args.output_dir,
        model=args.model,
        ollama_url=args.ollama_url,
        sample_fps=args.sample_fps,
        max_frames=args.max_frames,
        thumb_width=args.thumb_width,
        timeout_sec=args.timeout_sec,
    )
    artifact = args.output_dir / f"{result.clip_id}.local-track-a.json"
    print(f"[3/4] artifact: {artifact}")
    print("[4/4] normalized result")
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

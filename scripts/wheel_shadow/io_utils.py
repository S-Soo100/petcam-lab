"""R2 read-only 다운로드 + ffmpeg 적응형 프레임 추출 (shadow 전용, self-contained).

storage/dataset-203 의존 없이 ffmpeg 를 직접 호출한다(_extract_frames_clip.extract_adaptive
와 같은 규약: 간격 3.5s, clamp 6~20, 구간중앙 t=(i+0.5)*dur/N).

⚠️ R2 는 head_object/get_object(download) 만 쓴다. put/delete 계열은 이 모듈에 존재하지 않는다.
모든 media 는 호출 측의 tempfile.TemporaryDirectory 안에서만 생성/삭제.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from botocore.exceptions import ClientError

FRAME_INTERVAL = 3.5
FRAME_MIN = 6
FRAME_MAX = 20


def r2_object_exists(r2, bucket: str, key: str) -> bool:
    """HEAD 로 존재 확인. write 아님."""
    try:
        r2.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False


def download_clip(r2, bucket: str, key: str, dst: Path) -> bool:
    """R2 object 를 temp 로 GET. 존재하지 않으면 False (novelty 처리)."""
    if not r2_object_exists(r2, bucket, key):
        return False
    try:
        r2.download_file(bucket, key, str(dst))
        return dst.is_file() and dst.stat().st_size > 0
    except ClientError:
        return False


def probe_duration(mp4: Path) -> float:
    """ffprobe 로 duration(초). 실패 시 0.0."""
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(mp4),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return 0.0
    try:
        return float(json.loads(proc.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return 0.0


def adaptive_frame_count(dur: float, interval: float = FRAME_INTERVAL,
                         lo: int = FRAME_MIN, hi: int = FRAME_MAX) -> int:
    if dur <= 0:
        return lo
    return max(lo, min(hi, round(dur / interval)))


def extract_adaptive_frames(mp4: Path, out_dir: Path,
                            interval: float = FRAME_INTERVAL,
                            lo: int = FRAME_MIN, hi: int = FRAME_MAX) -> list[Path]:
    """구간중앙 t=(i+0.5)*dur/N 타임스탬프를 ffmpeg -ss 로 정확 추출.

    고정N(ffmpeg fps 필터)의 뒷부분 손실·t=0 결함을 피한다. 결정론:
    같은 mp4·같은 timestamp seek → 같은 프레임 → 같은 dHash.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    dur = probe_duration(mp4)
    n = adaptive_frame_count(dur, interval, lo, hi)
    frames: list[Path] = []
    for i in range(n):
        t = (i + 0.5) * dur / n if dur > 0 else 0.0
        p = out_dir / f"f_{i + 1:03d}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(mp4),
             "-frames:v", "1", "-q:v", "3", str(p)],
            capture_output=True,
        )
        if p.exists() and p.stat().st_size > 0:
            frames.append(p)
    return frames

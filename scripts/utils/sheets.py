"""Contact sheet 생성 공통 유틸 — eval round 다중 재사용.

`make_*_sheets.py` 들이 매 라운드 복붙하던 ffprobe duration + ffmpeg tile 로직을
한 곳으로. tile 문자열("5x6"/"6x6")에서 프레임 수 자동 계산.

사용:
    from scripts.utils.sheets import make_contact_sheet, make_contact_sheet_from_bytes
    make_contact_sheet(local_mp4, out_jpg, tile="5x6", scale=360)         # 로컬 파일
    make_contact_sheet_from_bytes(r2_bytes, out_jpg, tile="6x6", scale=480)  # R2 다운로드 bytes
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def probe_duration(path: str | Path) -> float:
    """ffprobe 로 영상 길이(초). 실패 시 30.0 fallback (짧은 클립 가정)."""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)]
        ).decode().strip()
        return float(out) if out and out != "N/A" else 30.0
    except Exception:
        return 30.0


def _run_tile(src: str | Path, output: Path, tile: str, scale: int) -> bool:
    """tile(=cols x rows) 프레임을 영상에서 균등 추출 → ffmpeg tile contact sheet."""
    dur = probe_duration(src)
    cols, rows = (int(x) for x in tile.lower().split("x"))
    fps = max(cols * rows / dur, 0.2)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-vf",
         f"fps={fps:.4f},scale={scale}:-2,tile={tile}", "-frames:v", "1", str(output)],
        capture_output=True,
    )
    return output.exists()


def make_contact_sheet(
    input_path: str | Path, output: Path, *, tile: str = "5x6", scale: int = 360
) -> bool:
    """로컬 영상 파일 → contact sheet. output 이미 있으면 skip(True)."""
    if output.exists():
        return True
    return _run_tile(input_path, output, tile, scale)


def make_contact_sheet_from_bytes(
    video_bytes: bytes, output: Path, *, tile: str = "5x6", scale: int = 360
) -> bool:
    """R2/원격 영상 bytes → temp mp4 → contact sheet. temp 자동 정리."""
    if output.exists():
        return True
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(video_bytes)
        tmp = Path(f.name)
    try:
        return _run_tile(tmp, output, tile, scale)
    finally:
        tmp.unlink(missing_ok=True)

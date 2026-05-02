"""
backend.encoding 단위 테스트.

## 검증 목표
- 정상 인코딩 → dst 존재 + size > 0 + duration 보존 + audio 없음 + 코덱 H.264
- 입력에 오디오 있어도 출력에 없음 (-an 검증)
- 미존재 / 디렉토리 / src==dst → 명확한 예외
- ffmpeg 부재 → FFmpegNotFound (PATH 비워서 검증)
- 깨진 입력 → False 반환 + dst cleanup

## ffprobe 로 출력 검증
ffmpeg 패키지에 동봉. JSON 출력 파싱으로 duration / streams / codec 확인.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.encoding import (
    ENCODE_TIMEOUT_SEC,
    FFmpegNotFound,
    encode_lightweight,
)

# ffmpeg/ffprobe 가 환경에 없으면 전체 모듈 skip — CI 에서 ffmpeg 미설치 환경 대비.
pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)


def _make_test_video(
    dst: Path,
    duration_sec: float = 1.0,
    with_audio: bool = False,
    width: int = 320,
    height: int = 240,
    fps: int = 12,
) -> None:
    """ffmpeg lavfi 로 결정론적 테스트 mp4 생성.
    testsrc 는 컬러바 + 카운터, 매번 동일 → 압축 결과 결정론적.
    """
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi",
        "-i", f"testsrc=duration={duration_sec}:size={width}x{height}:rate={fps}",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_sec}"]
    # 입력 인코더는 디폴트로 두고 빠르게.
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += [str(dst)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=15)


def _ffprobe(path: Path) -> dict:
    """ffprobe JSON 출력. format.duration + streams[*].codec_type/codec_name."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-show_entries", "stream=codec_type,codec_name",
            "-of", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return json.loads(result.stdout)


# ─── 정상 path ───────────────────────────────────────────────────────────────


def test_encode_lightweight_success(tmp_path: Path) -> None:
    """정상 인코딩 — 출력 존재 + duration 보존 + 코덱 H.264."""
    src = tmp_path / "in.mp4"
    dst = tmp_path / "out.mp4"
    _make_test_video(src, duration_sec=1.0)

    assert encode_lightweight(src, dst) is True
    assert dst.is_file()
    assert dst.stat().st_size > 0

    info = _ffprobe(dst)
    duration = float(info["format"]["duration"])
    assert 0.8 <= duration <= 1.3, f"duration drift: {duration}s"

    streams = info["streams"]
    assert len(streams) == 1, f"expected 1 stream (video only), got {streams}"
    assert streams[0]["codec_type"] == "video"
    assert streams[0]["codec_name"] == "h264"


def test_encode_lightweight_strips_audio(tmp_path: Path) -> None:
    """입력에 audio 있어도 출력은 video stream 1개만 (-an 검증)."""
    src = tmp_path / "in_with_audio.mp4"
    dst = tmp_path / "out_no_audio.mp4"
    _make_test_video(src, duration_sec=1.0, with_audio=True)

    src_streams = _ffprobe(src)["streams"]
    assert any(s["codec_type"] == "audio" for s in src_streams), "test fixture broken"

    assert encode_lightweight(src, dst) is True

    dst_streams = _ffprobe(dst)["streams"]
    assert all(s["codec_type"] != "audio" for s in dst_streams)


def test_encode_lightweight_smaller_than_source(tmp_path: Path) -> None:
    """testsrc 같은 단순 패턴은 인코딩 후 더 작아져야 함 (CRF 26 + faststart).
    실 클립은 patternless 라 차이 더 큼. 여기선 sanity check.
    """
    src = tmp_path / "in.mp4"
    dst = tmp_path / "out.mp4"
    _make_test_video(src, duration_sec=2.0, width=640, height=480)

    assert encode_lightweight(src, dst) is True
    # 어느 한쪽이 0이면 비교 무의미 — 둘 다 양수 + dst ≤ src
    assert src.stat().st_size > 0
    assert dst.stat().st_size > 0
    assert dst.stat().st_size <= src.stat().st_size


def test_encode_lightweight_custom_crf(tmp_path: Path) -> None:
    """CRF 23 (높은 품질) 이 CRF 28 (낮은 품질) 보다 큰 파일."""
    src = tmp_path / "in.mp4"
    dst_high = tmp_path / "out_crf23.mp4"
    dst_low = tmp_path / "out_crf28.mp4"
    _make_test_video(src, duration_sec=2.0, width=640, height=480)

    assert encode_lightweight(src, dst_high, crf=23) is True
    assert encode_lightweight(src, dst_low, crf=28) is True
    assert dst_high.stat().st_size >= dst_low.stat().st_size


# ─── 입력 검증 ────────────────────────────────────────────────────────────────


def test_encode_missing_src_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="encode source missing"):
        encode_lightweight(tmp_path / "nonexistent.mp4", tmp_path / "out.mp4")


def test_encode_directory_src_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="encode source missing"):
        encode_lightweight(tmp_path, tmp_path / "out.mp4")


def test_encode_src_eq_dst_raises(tmp_path: Path) -> None:
    """src == dst 면 ValueError. -y 로 원본 덮어쓰기 사고 방지."""
    src = tmp_path / "same.mp4"
    _make_test_video(src)
    with pytest.raises(ValueError, match="src == dst"):
        encode_lightweight(src, src)


# ─── ffmpeg 부재 ──────────────────────────────────────────────────────────────


def test_encode_ffmpeg_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PATH 비우면 FFmpegNotFound."""
    src = tmp_path / "in.mp4"
    _make_test_video(src)  # 이건 monkeypatch 전에 만들어야 함

    monkeypatch.setenv("PATH", "")
    with pytest.raises(FFmpegNotFound, match="ffmpeg"):
        encode_lightweight(src, tmp_path / "out.mp4")


# ─── ffmpeg 실패 ──────────────────────────────────────────────────────────────


def test_encode_invalid_input_returns_false(tmp_path: Path) -> None:
    """깨진 mp4 (실은 텍스트) 면 False + dst cleanup."""
    src = tmp_path / "fake.mp4"
    src.write_bytes(b"this is not an mp4 file at all")
    dst = tmp_path / "out.mp4"

    assert encode_lightweight(src, dst) is False
    assert not dst.exists(), "failed encode should leave no partial output"


def test_encode_dst_parent_missing_returns_false(tmp_path: Path) -> None:
    """dst 부모 디렉토리 없으면 ffmpeg 가 fail → False."""
    src = tmp_path / "in.mp4"
    _make_test_video(src)
    dst = tmp_path / "no_such_dir" / "out.mp4"

    assert encode_lightweight(src, dst) is False
    assert not dst.exists()


def test_default_crf_constant_is_26() -> None:
    """spec §3-2 결정 사항 회귀 — CRF 변경은 spec 동기화 동반해야."""
    from backend.encoding import DEFAULT_CRF
    assert DEFAULT_CRF == 26


def test_encode_timeout_constant() -> None:
    """타임아웃 30초 — 1분 segment veryfast 기준 충분 + 너무 짧지 않음."""
    assert ENCODE_TIMEOUT_SEC == 30

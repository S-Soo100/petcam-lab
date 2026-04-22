"""
backend.capture 의 Stage D4 썸네일 로직 단위 테스트.

## 전략 (donts/python.md 13번)
- 실 RTSP / VideoCapture 미사용
- `_save_thumbnail` 은 numpy 프레임으로 직접 호출해 파일 생성·경로 매핑 검증
- `_record_clip` 은 가짜 clip_recorder 콜백을 주입해 payload 내용 검증
  → insert 경로는 capture → recorder 콜백 의존성만 있으면 됨

## 왜 `_capture_loop` 전체 통합 테스트를 안 하나?
VideoCapture·VideoWriter·Motion·시간 진행 전부 얽힌 루프라 mock 체인이 커짐.
학습 가치 > 비용 시점에 추가 예정 (현재는 핵심 유닛만).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from backend.capture import CaptureWorker


# ────────────────────────────────────────────────────────────────────────────
# 공통 헬퍼
# ────────────────────────────────────────────────────────────────────────────


def _make_worker(tmp_path: Path) -> CaptureWorker:
    """실 RTSP 연결 안 하는 워커. 내부 헬퍼 직접 호출 테스트용."""
    return CaptureWorker(
        camera_id="test-cam",
        rtsp_url="rtsp://unused-for-this-test",
        storage_dir=tmp_path,
        segment_seconds=60,
    )


def _blue_frame(width: int = 320, height: int = 240) -> np.ndarray:
    """BGR 파란색 단색 프레임 — imwrite 가 어떤 내용이든 받아들이는지 확인용."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :, 0] = 255  # Blue 채널
    return frame


# ────────────────────────────────────────────────────────────────────────────
# _save_thumbnail — 파일 저장 경로
# ────────────────────────────────────────────────────────────────────────────


def test_save_thumbnail_writes_jpg_next_to_mp4(tmp_path: Path) -> None:
    """mp4 basename 과 동일 + .jpg 확장자로 생성된다."""
    worker = _make_worker(tmp_path)
    mp4_path = tmp_path / "20260422_154300_motion.mp4"
    mp4_path.touch()  # 실제 mp4 가 있어야 하는 건 아니지만 의도 명확화
    frame = _blue_frame()

    thumb_path = worker._save_thumbnail(mp4_path, frame)

    assert thumb_path is not None
    assert thumb_path == tmp_path / "20260422_154300_motion.jpg"
    assert thumb_path.exists()
    assert thumb_path.stat().st_size > 0


def test_save_thumbnail_produces_valid_jpeg_header(tmp_path: Path) -> None:
    """
    파일 첫 바이트가 JPEG SOI 마커 (0xFF 0xD8) 로 시작해야 한다.
    cv2.imwrite 가 jpg 확장자 보고 올바른 인코더 쓰는지 확인.
    """
    worker = _make_worker(tmp_path)
    mp4_path = tmp_path / "clip.mp4"
    frame = _blue_frame()

    thumb_path = worker._save_thumbnail(mp4_path, frame)

    assert thumb_path is not None
    head = thumb_path.read_bytes()[:2]
    assert head == b"\xff\xd8", f"JPEG SOI 마커 없음: {head!r}"


def test_save_thumbnail_returns_none_on_bad_path(tmp_path: Path) -> None:
    """
    쓸 수 없는 경로 (존재하지 않는 부모 디렉토리) → None + state.last_error 기록.
    imwrite 는 실패 시 False 를 리턴하므로 예외가 아니라 None 으로 전환되어야.
    """
    worker = _make_worker(tmp_path)
    bad_mp4 = tmp_path / "nonexistent-dir" / "clip.mp4"
    frame = _blue_frame()

    thumb_path = worker._save_thumbnail(bad_mp4, frame)

    assert thumb_path is None
    assert worker._state.last_error is not None
    assert "thumbnail" in worker._state.last_error.lower()


# ────────────────────────────────────────────────────────────────────────────
# _record_clip — INSERT payload 에 thumbnail_path 가 포함되는지
# ────────────────────────────────────────────────────────────────────────────


class _SpyRecorder:
    """마지막 호출 payload 를 기억하는 스텁."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, payload: dict[str, Any]) -> None:
        self.calls.append(payload)


def _worker_with_spy(tmp_path: Path) -> tuple[CaptureWorker, _SpyRecorder]:
    spy = _SpyRecorder()
    worker = CaptureWorker(
        camera_id="test-cam",
        rtsp_url="rtsp://unused",
        storage_dir=tmp_path,
        segment_seconds=60,
        clip_recorder=spy,
    )
    # _record_clip 내부에서 self._state.frame_size / fps 를 참조함
    worker._state.frame_size = (320, 240)
    worker._state.fps = 15.0
    worker._fourcc_used = "avc1"
    return worker, spy


def test_record_clip_includes_thumbnail_path_when_provided(tmp_path: Path) -> None:
    """thumbnail_path 파라미터가 Path 면 payload 에 str 로 직렬화."""
    worker, spy = _worker_with_spy(tmp_path)
    mp4_path = tmp_path / "20260422_154300_motion.mp4"
    mp4_path.write_bytes(b"dummy mp4 content for file_size calc")
    thumb_path = tmp_path / "20260422_154300_motion.jpg"

    worker._record_clip(
        path=mp4_path,
        started_at=1713780000.0,
        duration_sec=60.0,
        is_motion=True,
        motion_frames_count=180,
        thumbnail_path=thumb_path,
    )

    assert len(spy.calls) == 1
    payload = spy.calls[0]
    assert payload["thumbnail_path"] == str(thumb_path)
    # 기존 필드도 살아있는지 회귀 방지
    assert payload["file_path"] == str(mp4_path)
    assert payload["has_motion"] is True
    assert payload["codec"] == "avc1"


def test_record_clip_payload_thumbnail_none_when_omitted(tmp_path: Path) -> None:
    """
    thumbnail_path 기본값 None → payload 에도 None (DB NULL).
    기존 (D4 미도입 환경) 테스트가 기본값 호출 시 깨지면 안 되는 것도 같이 확인.
    """
    worker, spy = _worker_with_spy(tmp_path)
    mp4_path = tmp_path / "clip_idle.mp4"
    mp4_path.write_bytes(b"x")

    worker._record_clip(
        path=mp4_path,
        started_at=1713780000.0,
        duration_sec=30.0,
        is_motion=False,
        motion_frames_count=0,
        # thumbnail_path 생략 (기본값 None)
    )

    assert len(spy.calls) == 1
    payload = spy.calls[0]
    assert payload["thumbnail_path"] is None


def test_record_clip_payload_thumbnail_none_when_explicit_none(tmp_path: Path) -> None:
    """명시 None 도 동일 동작 — imwrite 실패 분기 대비."""
    worker, spy = _worker_with_spy(tmp_path)
    mp4_path = tmp_path / "clip.mp4"
    mp4_path.write_bytes(b"x")

    worker._record_clip(
        path=mp4_path,
        started_at=1713780000.0,
        duration_sec=60.0,
        is_motion=True,
        motion_frames_count=90,
        thumbnail_path=None,
    )

    payload = spy.calls[0]
    assert payload["thumbnail_path"] is None


def test_record_clip_no_recorder_is_noop(tmp_path: Path) -> None:
    """clip_recorder 미주입 워커는 호출해도 조용히 종료 — 회귀 방지."""
    worker = _make_worker(tmp_path)  # clip_recorder 없음
    mp4_path = tmp_path / "clip.mp4"
    mp4_path.write_bytes(b"x")

    # 예외 없이 끝나야 함
    worker._record_clip(
        path=mp4_path,
        started_at=1713780000.0,
        duration_sec=60.0,
        is_motion=False,
        motion_frames_count=0,
        thumbnail_path=tmp_path / "clip.jpg",
    )

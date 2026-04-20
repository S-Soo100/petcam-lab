"""
backend.capture 단위 테스트.

## 원칙 (donts/python.md 13번)
실제 RTSP 소스에 의존하지 않는다. fake numpy 프레임을 써서
파일 생성 + VideoWriter 쓰기 경로만 검증. 네트워크·카메라 불필요.

## 테스트 대상
- `CaptureState` — dataclass 기본값이 예상대로인지
- `CaptureWorker._open_new_segment` — mp4 파일을 실제로 생성하고 쓸 수 있는지
- `compute_padding_count`, `should_drop_frame` — CFR 보정 pure function

`_open_new_segment`는 private 메서드지만 Python 관례상 테스트에서는 접근 허용.
이게 세그먼트 생성 경로의 핵심이라 직접 검증하는 편이 나음.
"""

from __future__ import annotations

import numpy as np

from backend.capture import (
    CaptureState,
    CaptureWorker,
    compute_padding_count,
    should_drop_frame,
)


def test_capture_state_defaults() -> None:
    """dataclass 기본값 검증 — 새로 만든 상태는 모두 초기값이어야 함."""
    state = CaptureState(camera_id="cam-x")

    assert state.camera_id == "cam-x"
    assert state.is_running is False
    assert state.is_connected is False
    assert state.frames_read == 0
    assert state.segments_written == 0
    assert state.last_frame_ts is None
    assert state.current_segment is None
    assert state.last_error is None
    assert state.frame_size is None
    assert state.fps is None


def test_open_new_segment_creates_playable_mp4(tmp_path) -> None:
    """
    `_open_new_segment` 가 실제로 .mp4 파일을 만들고 VideoWriter 가 쓸 수 있는지.

    fake numpy 프레임 30개(~2초 분량)를 써서 파일 크기 > 0 확인.
    """
    worker = CaptureWorker(
        camera_id="test-cam",
        rtsp_url="rtsp://unused-for-this-test",   # 실제 연결 없음
        storage_dir=tmp_path,
        segment_seconds=60,
    )

    width, height, fps = 320, 240, 15.0
    writer, path = worker._open_new_segment(width, height, fps)

    try:
        # 검은 프레임 30장 작성
        for _ in range(30):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            writer.write(frame)
    finally:
        # 파일 finalize는 반드시 release 호출 후에 발생
        writer.release()

    assert path.exists(), "mp4 파일이 생성되어야 한다"
    assert path.stat().st_size > 0, "mp4 파일 크기가 0보다 커야 한다"
    assert path.suffix == ".mp4"

    # 경로 구조: {tmp_path}/{YYYY-MM-DD}/{camera_id}/{HHMMSS}.mp4
    assert path.parent.name == "test-cam"
    assert path.parent.parent.parent == tmp_path

    # 워커 상태에 현재 세그먼트 파일명이 반영돼야 함
    assert worker._state.current_segment == path.name


# ── CFR 보정 Pure Function 테스트 ──────────────────────────────────────
# 시간/IO 의존 없으므로 평범한 수학 검증.

def test_padding_count_fills_gap_before_current_frame() -> None:
    """
    expected=10, 이미 5개 썼음 → 현재 들어온 프레임 자리(1개) 빼고 4개 패딩.

    즉 'expected - 1 - written' 공식의 의미를 직접 검증.
    """
    assert compute_padding_count(frames_written=5, expected_frames=10) == 4


def test_padding_count_zero_when_no_gap() -> None:
    """expected=10, 이미 9개 썼음 → 현재 프레임이 10번째 자리 채움. 패딩 불필요."""
    assert compute_padding_count(frames_written=9, expected_frames=10) == 0


def test_padding_count_clamped_to_zero_when_ahead() -> None:
    """이미 expected 를 초과해서 썼으면 (수신 fps가 빨랐던 경우) 패딩 0."""
    assert compute_padding_count(frames_written=15, expected_frames=10) == 0


def test_should_drop_frame_when_at_or_over_expected() -> None:
    """frames_written >= expected → 드롭. 경계 포함."""
    assert should_drop_frame(frames_written=10, expected_frames=10) is True
    assert should_drop_frame(frames_written=11, expected_frames=10) is True


def test_should_not_drop_when_behind_expected() -> None:
    """아직 쓸 자리가 있으면 드롭 X."""
    assert should_drop_frame(frames_written=9, expected_frames=10) is False
    assert should_drop_frame(frames_written=0, expected_frames=10) is False

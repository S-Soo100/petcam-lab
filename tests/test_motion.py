"""
MotionDetector 단위 테스트.

## 원칙 (donts/python.md 13번)
실제 카메라/RTSP 없이 fake numpy 프레임으로 알고리즘 결정성만 검증.

## 테스트 전략
- TN (True Negative): 동일한 프레임 N장 → motion 절대 감지 X
- TP (True Positive): 배경 프레임 + 중앙에 밝은 사각형 그린 프레임 → motion 감지 O
- 초기화 동작: 첫 프레임은 비교 대상 없어서 무조건 False
- 입력 검증: 잘못된 파라미터는 ValueError
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.motion import MotionDetector


HEIGHT, WIDTH = 240, 320   # fake 프레임 크기


def _blank_frame(value: int = 128) -> np.ndarray:
    """회색 단색 프레임 (BGR 3채널)."""
    return np.full((HEIGHT, WIDTH, 3), value, dtype=np.uint8)


def _frame_with_bright_box(
    value: int = 128, box_value: int = 255, box_size: int = 80
) -> np.ndarray:
    """중앙에 밝은 사각형 있는 프레임. box_size px 정사각형.

    box_size=80 → 80*80 / (320*240) = 8.33% 변화 → 1% 임계에서 확실히 motion.
    """
    frame = _blank_frame(value)
    cy, cx = HEIGHT // 2, WIDTH // 2
    half = box_size // 2
    frame[cy - half : cy + half, cx - half : cx + half] = box_value
    return frame


def test_first_frame_returns_false() -> None:
    """첫 프레임은 비교 대상이 없으므로 무조건 False."""
    detector = MotionDetector(pixel_threshold=25, pixel_ratio_pct=1.0)
    assert detector.update(_blank_frame()) is False


def test_static_scene_no_motion() -> None:
    """
    TN: 동일한 프레임을 여러 번 줘도 motion 감지 안 됨.
    (센서 노이즈도 없는 이상적 상황 — 완전 동일 numpy 배열이라 변화량 0)
    """
    detector = MotionDetector(pixel_threshold=25, pixel_ratio_pct=1.0)
    frame = _blank_frame()
    detector.update(frame)   # 초기화
    for _ in range(10):
        assert detector.update(frame) is False
    assert detector.last_changed_ratio == 0.0


def test_bright_box_appears_triggers_motion() -> None:
    """
    TP: 회색 배경 → 밝은 박스 프레임 전환 시 motion 감지.
    박스 크기 80×80 = 전체의 ~8.33% → 임계 1.0% 를 여유 있게 넘음.
    """
    detector = MotionDetector(pixel_threshold=25, pixel_ratio_pct=1.0)
    detector.update(_blank_frame())               # 초기 상태
    detected = detector.update(_frame_with_bright_box())
    assert detected is True
    assert detector.last_changed_ratio > 1.0


def test_tiny_change_below_ratio_threshold() -> None:
    """
    TN: 아주 작은 박스(8×8 = 0.08%)는 임계(1%) 미만이므로 motion 아님.
    → pixel_ratio 임계값이 실제로 작동하는지 확인.
    """
    detector = MotionDetector(pixel_threshold=25, pixel_ratio_pct=1.0)
    detector.update(_blank_frame())
    tiny = _frame_with_bright_box(box_size=8)   # 8*8/(320*240) ≈ 0.083%
    assert detector.update(tiny) is False


def test_reset_clears_previous_frame() -> None:
    """reset() 후 첫 호출은 다시 False (내부 prev_gray 초기화)."""
    detector = MotionDetector(pixel_threshold=25, pixel_ratio_pct=1.0)
    detector.update(_blank_frame())
    detector.reset()
    # reset 직후엔 기준 프레임 없음 → 움직이는 박스 줘도 False
    assert detector.update(_frame_with_bright_box()) is False


def test_invalid_params_rejected() -> None:
    """생성자 파라미터 범위 검증."""
    with pytest.raises(ValueError):
        MotionDetector(pixel_threshold=-1, pixel_ratio_pct=1.0)
    with pytest.raises(ValueError):
        MotionDetector(pixel_threshold=300, pixel_ratio_pct=1.0)
    with pytest.raises(ValueError):
        MotionDetector(pixel_threshold=25, pixel_ratio_pct=-0.1)

"""
움직임 감지 모듈.

## 역할
프레임을 한 장씩 받아서 "이 프레임에서 장면이 변했는가" 를 Bool 로 리턴한다.
캡처 루프(`backend/capture.py`)가 매 프레임마다 이 `update()` 를 호출하고,
리턴값을 세그먼트 단위로 집계해서 파일명에 `_motion` / `_idle` 접미사를 붙인다.

## 알고리즘 — cv2.absdiff 기반 프레임 차분
1. BGR 프레임을 그레이스케일로 변환 (3채널 → 1채널, 연산량 3배 절감)
2. Gaussian 블러로 센서 노이즈 제거 (카메라 잡음 / 픽셀 깜빡임 억제)
3. 이전 프레임과 현재 프레임의 픽셀별 절대차이 (`cv2.absdiff`)
4. 차이값이 `pixel_threshold` 이상인 픽셀만 남김 (threshold binarization)
5. 변한 픽셀 비율이 `pixel_ratio_pct` 이상이면 `True` (motion frame)

## 왜 이 접근법?
- **MOG2/KNN 배경 차분** 보다 가볍고 구현 단순.
- 사육장은 조명이 거의 고정 → 배경 모델링 필요성 낮음.
- 조명 변화(UVB on/off, 주간↔야간 IR 전환) 는 일시적 false positive 로 나옴.
  Stage C 이후 "급격한 전체 밝기 변화 필터" 로 보완 예정.

## 노이즈 필터링은 여기에 없다
`MOTION_MIN_DURATION_FRAMES` (N프레임 연속) 필터는 capture.py 의 run-length 집계
로직에서 처리. MotionDetector 는 "이 프레임 자체가 motion 인가" 만 판정하는
**stateless-ish** 역할. (stateless-ish = 이전 프레임만 기억, 그외 상태 없음)
"""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np


# 블러 커널 — OpenCV motion detection 튜토리얼 표준값.
# (21, 21) 이 "센서 노이즈 지우고 실제 움직임 살림" 에 경험적으로 잘 맞음.
# 홀수여야 함 (커널 중심이 존재해야 해서).
GAUSSIAN_KERNEL = (21, 21)


class MotionDetector:
    """
    프레임 시퀀스에 대해 per-frame motion 판정.

    사용 예:
        detector = MotionDetector(pixel_threshold=25, pixel_ratio_pct=1.0)
        for frame in stream:
            if detector.update(frame):
                print("motion!")
    """

    def __init__(
        self,
        pixel_threshold: int = 25,
        pixel_ratio_pct: float = 1.0,
    ) -> None:
        """
        Args:
            pixel_threshold: absdiff 후 "변한 픽셀" 로 볼 밝기 차이 임계 (0~255).
                낮을수록 민감 (노이즈도 잡음). 보통 20~30.
            pixel_ratio_pct: 전체 픽셀 중 변한 비율(%) 임계.
                넘으면 motion frame. 도마뱀 케이스 추천 0.7 ~ 1.5.
        """
        if not (0 <= pixel_threshold <= 255):
            raise ValueError(f"pixel_threshold must be 0..255, got {pixel_threshold}")
        if pixel_ratio_pct < 0:
            raise ValueError(f"pixel_ratio_pct must be >= 0, got {pixel_ratio_pct}")

        self._pixel_threshold = pixel_threshold
        self._pixel_ratio_pct = pixel_ratio_pct
        self._prev_gray: Optional[np.ndarray] = None
        self._last_changed_ratio: float = 0.0   # 디버깅/튜닝용 외부 조회

    def update(self, frame_bgr: np.ndarray) -> bool:
        """
        프레임 1장을 받아 motion 여부 리턴.

        첫 호출은 비교 대상이 없어 **무조건 False**.
        이후부터 직전 프레임과 비교.

        Args:
            frame_bgr: OpenCV가 리턴한 BGR 3채널 uint8 프레임 (H, W, 3).

        Returns:
            True if 이 프레임에서 변화량이 임계를 넘음 (motion frame).
            False otherwise.
        """
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, GAUSSIAN_KERNEL, 0)

        if self._prev_gray is None:
            self._prev_gray = gray
            self._last_changed_ratio = 0.0
            return False

        # 픽셀별 |current - prev|
        delta = cv2.absdiff(self._prev_gray, gray)
        # threshold 넘는 픽셀은 255, 아니면 0 으로 이진화
        _, thresh_mask = cv2.threshold(
            delta, self._pixel_threshold, 255, cv2.THRESH_BINARY
        )

        # 변한 픽셀 비율
        changed_pixels = int(np.count_nonzero(thresh_mask))
        total_pixels = thresh_mask.size  # H * W
        changed_ratio = (changed_pixels / total_pixels) * 100.0

        self._prev_gray = gray
        self._last_changed_ratio = changed_ratio

        return changed_ratio >= self._pixel_ratio_pct

    @property
    def last_changed_ratio(self) -> float:
        """가장 최근 프레임의 변화 비율(%). 튜닝/로그용."""
        return self._last_changed_ratio

    def reset(self) -> None:
        """내부 상태(이전 프레임 기억)를 초기화. 재연결 직후 권장."""
        self._prev_gray = None
        self._last_changed_ratio = 0.0

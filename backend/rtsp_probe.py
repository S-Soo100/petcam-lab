"""
RTSP 테스트 연결 — `/cameras/test-connection` 과 `POST /cameras` 등록 시 사용.

## 왜 별도 모듈?
- cv2.VideoCapture 블로킹 호출을 라우터에 섞으면 테스트 mock 복잡.
- 순수 함수 (input: 필드, output: dataclass) 로 분리 → cv2 mock 만으로 단위 테스트.

## 블로킹 vs async
- cv2 는 C 레벨 블로킹 (최대 3초) → FastAPI 라우터는 **동기 def** 로 선언
  (donts/python#4). async 로 쓰면 `asyncio.to_thread` 필요.

## 비번 로깅 금지
- 로그에 원본 URL 찍지 말 것. `mask_rtsp_url` 로 치환 후 기록.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import cv2

logger = logging.getLogger(__name__)

# UX 상 6초 이내 피드백 목표. OpenCV 4.5+ 에서 동작.
_OPEN_TIMEOUT_MS = 3000
_READ_TIMEOUT_MS = 3000

# rtsp://user:pw@host 의 pw 를 마스킹
_MASK_RE = re.compile(r"(rtsp://[^:/@]+:)[^@]+(@)")


@dataclass(frozen=True)
class ProbeResult:
    success: bool
    detail: str
    frame_captured: bool
    elapsed_ms: int
    frame_size: Optional[tuple[int, int]] = None


def build_rtsp_url(
    host: str, port: int, path: str, username: str, password: str
) -> str:
    """
    RTSP URL 표준 조립. user/pw 의 특수문자 (@, :, /) 는 quote 로 이스케이프.
    """
    user_q = quote(username, safe="")
    pw_q = quote(password, safe="")
    path = path.lstrip("/")
    return f"rtsp://{user_q}:{pw_q}@{host}:{port}/{path}"


def mask_rtsp_url(url: str) -> str:
    """rtsp://user:pw@host → rtsp://user:***@host — 로깅용."""
    return _MASK_RE.sub(r"\1***\2", url)


def probe_rtsp(
    host: str, port: int, path: str, username: str, password: str
) -> ProbeResult:
    """
    실 RTSP 에 3초 타임아웃으로 연결 시도 → 첫 프레임 수신.

    예외는 안 던짐 — 실패도 ProbeResult(success=False) 로 반환.
    사용자 입력 오류 (비번 오타 등) 는 200 응답 + success=False 의도.
    """
    url = build_rtsp_url(host, port, path, username, password)
    logger.info("probing %s", mask_rtsp_url(url))

    start = time.monotonic()
    cap = cv2.VideoCapture(url)
    try:
        # OpenCV 4.5+ 기준. 속성 자체가 없는 옛 버전은 AttributeError 무시.
        try:
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, _OPEN_TIMEOUT_MS)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, _READ_TIMEOUT_MS)
        except AttributeError:
            pass

        if not cap.isOpened():
            elapsed = int((time.monotonic() - start) * 1000)
            return ProbeResult(
                success=False,
                detail="RTSP 연결 실패 (인증·IP·포트·방화벽 확인)",
                frame_captured=False,
                elapsed_ms=elapsed,
            )

        ok, frame = cap.read()
        elapsed = int((time.monotonic() - start) * 1000)

        if not ok or frame is None:
            return ProbeResult(
                success=False,
                detail="연결은 됐지만 프레임 읽기 실패",
                frame_captured=False,
                elapsed_ms=elapsed,
            )

        h, w = frame.shape[:2]
        return ProbeResult(
            success=True,
            detail="첫 프레임 수신 성공",
            frame_captured=True,
            elapsed_ms=elapsed,
            frame_size=(w, h),
        )
    finally:
        cap.release()

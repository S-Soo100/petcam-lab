"""
backend.rtsp_probe 단위 테스트 — cv2 는 전부 mock.

## 왜 cv2 mock?
실 RTSP 의존 테스트 금지 (donts/python#13). `cv2.VideoCapture` 를 MagicMock 으로
치환해 isOpened/read/release 의 반환값만 제어.

## frame 은 numpy array
`frame.shape` 을 호출하는 로직이 있으므로 numpy ndarray mock. 단순 MagicMock 으로는
shape 속성이 없어서 AttributeError.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from backend.rtsp_probe import (
    ProbeResult,
    build_rtsp_url,
    mask_rtsp_url,
    probe_rtsp,
)

# ─────────────────────────────────────────────────────────────────────────
# build_rtsp_url
# ─────────────────────────────────────────────────────────────────────────


def test_build_rtsp_url_basic() -> None:
    url = build_rtsp_url("192.168.0.10", 554, "stream1", "admin", "pw")
    assert url == "rtsp://admin:pw@192.168.0.10:554/stream1"


def test_build_rtsp_url_escapes_special_chars() -> None:
    """비번에 @:/ 특수문자 → URL-safe quote."""
    url = build_rtsp_url("host", 554, "stream1", "user@domain", "p@ss:1/2")
    # @ → %40, : → %3A, / → %2F
    assert "user%40domain" in url
    assert "p%40ss%3A1%2F2" in url
    assert "@host:554/" in url  # 실 구분자는 보존


def test_build_rtsp_url_strips_leading_slash_in_path() -> None:
    """path 앞 / 중복 방지."""
    url = build_rtsp_url("host", 554, "/stream1", "u", "p")
    assert url.endswith("/stream1")
    assert "//stream1" not in url


# ─────────────────────────────────────────────────────────────────────────
# mask_rtsp_url
# ─────────────────────────────────────────────────────────────────────────


def test_mask_rtsp_url_hides_password() -> None:
    masked = mask_rtsp_url("rtsp://admin:secret@host:554/stream1")
    assert masked == "rtsp://admin:***@host:554/stream1"


def test_mask_rtsp_url_handles_urlencoded_password() -> None:
    masked = mask_rtsp_url("rtsp://admin:p%40ss@host/stream")
    assert "p%40ss" not in masked
    assert "***" in masked


def test_mask_rtsp_url_no_password_returns_as_is() -> None:
    """user:pw 패턴 없으면 그대로."""
    plain = "rtsp://host:554/stream"
    assert mask_rtsp_url(plain) == plain


# ─────────────────────────────────────────────────────────────────────────
# probe_rtsp — cv2 mock
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_cv2_success(monkeypatch: pytest.MonkeyPatch):
    """연결 성공 + 1280x720 프레임 1개 수신."""
    fake_cap = MagicMock()
    fake_cap.isOpened.return_value = True
    # 프레임: shape=(720, 1280, 3) — OpenCV (H, W, C)
    fake_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    fake_cap.read.return_value = (True, fake_frame)
    monkeypatch.setattr("cv2.VideoCapture", lambda *a, **kw: fake_cap)
    return fake_cap


@pytest.fixture
def mock_cv2_cannot_open(monkeypatch: pytest.MonkeyPatch):
    """isOpened=False — 연결 자체 실패 (인증 거부·IP 오타·방화벽)."""
    fake_cap = MagicMock()
    fake_cap.isOpened.return_value = False
    monkeypatch.setattr("cv2.VideoCapture", lambda *a, **kw: fake_cap)
    return fake_cap


@pytest.fixture
def mock_cv2_read_fails(monkeypatch: pytest.MonkeyPatch):
    """연결은 됐는데 read 실패 — 네트워크 중단·카메라 busy."""
    fake_cap = MagicMock()
    fake_cap.isOpened.return_value = True
    fake_cap.read.return_value = (False, None)
    monkeypatch.setattr("cv2.VideoCapture", lambda *a, **kw: fake_cap)
    return fake_cap


def test_probe_success_returns_frame_size(mock_cv2_success) -> None:
    r = probe_rtsp("host", 554, "stream1", "admin", "pw")
    assert r.success is True
    assert r.frame_captured is True
    assert r.frame_size == (1280, 720)
    assert r.elapsed_ms >= 0
    assert "성공" in r.detail


def test_probe_cannot_open_returns_failure(mock_cv2_cannot_open) -> None:
    r = probe_rtsp("host", 554, "stream1", "admin", "wrong-pw")
    assert r.success is False
    assert r.frame_captured is False
    assert r.frame_size is None
    assert "연결 실패" in r.detail


def test_probe_read_fails_returns_failure(mock_cv2_read_fails) -> None:
    r = probe_rtsp("host", 554, "stream1", "admin", "pw")
    assert r.success is False
    assert r.frame_captured is False
    assert "프레임 읽기 실패" in r.detail


def test_probe_always_releases_cap(mock_cv2_success) -> None:
    """try/finally 로 release 보장 (donts/python#7)."""
    probe_rtsp("host", 554, "stream1", "admin", "pw")
    mock_cv2_success.release.assert_called_once()


def test_probe_releases_cap_on_open_failure(mock_cv2_cannot_open) -> None:
    probe_rtsp("host", 554, "stream1", "admin", "pw")
    mock_cv2_cannot_open.release.assert_called_once()


def test_probe_returns_dataclass() -> None:
    """반환 타입이 ProbeResult."""
    result = ProbeResult(
        success=True, detail="x", frame_captured=True, elapsed_ms=1, frame_size=(10, 20)
    )
    assert result.success is True
    # frozen=True 라 수정 불가
    with pytest.raises(Exception):
        result.success = False  # type: ignore

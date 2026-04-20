"""
RTSP 캡처 워커.

백그라운드 스레드에서 RTSP 프레임을 계속 읽어 1분 단위 mp4 세그먼트로 저장한다.

## 왜 threading인가?
- OpenCV `cv2.VideoCapture.read()`는 C 레벨 블로킹 I/O.
  asyncio 이벤트 루프에 직접 넣으면 루프 전체가 멈춤.
- `asyncio.to_thread`로 매 프레임을 wrap하는 방법도 있지만,
  캡처는 "계속 도는 루프"라 전용 스레드가 훨씬 직관적.
- JS로 치면: Node `worker_threads`에 블로킹 루프 돌리는 것과 비슷.

## 왜 클래스인가?
- 상태(연결 여부, 마지막 프레임 타임스탬프, 세그먼트 카운트)를
  스레드와 엔드포인트가 공유해야 함.
- 생명주기(start/stop)가 명확한 객체가 필요.
- Node로 치면: `EventEmitter` 상속 대신 명시적 state + 메서드.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2

# 재시도 상수 — test_rtsp.py와 동일 설계. 길게 끊기면 워커를 죽이지 않고 재연결 시도.
CONNECT_MAX_RETRIES = 3
CONNECT_RETRY_INTERVAL = 2.0   # 초. 캡처 워커는 스모크 테스트보다 여유 있게.
FRAME_READ_MAX_FAILS = 30      # 연속 프레임 실패 이 횟수 넘으면 재연결 시도
FRAME_SLEEP_ON_FAIL = 0.1

# VideoWriter 에 고정으로 쓸 fps.
#
# Tapo C200 은 CAP_PROP_FPS 로 "15" 라고 보고하지만 실제 송출은 약 12fps.
# scripts/measure_fps.py 실측 결과(2026-04-20): effective 12.28 fps.
# 메타값을 그대로 쓰면 60초 녹화가 48초로 재생되는 빨리감기 현상 발생.
# → 메타 대신 실측 기반 상수 고정. Stage B 에서 동적 측정으로 개선 예정.
CAPTURE_FPS = 12.0

# 왜 mp4v?
# - macOS OpenCV 기본 빌드에 포함 (FFmpeg 별도 설치 불필요)
# - VLC·QuickTime·브라우저 모두 재생 가능
# - H.264(avc1)은 용량 작지만 FFmpeg 빌드 의존 → Stage A는 호환성 우선
VIDEO_FOURCC = "mp4v"


@dataclass
class CaptureState:
    """워커 상태 스냅샷. /streams/{camera_id}/status 응답 바디의 원본."""
    camera_id: str
    is_running: bool = False
    is_connected: bool = False
    last_frame_ts: Optional[float] = None   # epoch 초
    frames_read: int = 0
    segments_written: int = 0
    current_segment: Optional[str] = None   # 파일명만 (전체 경로 아님)
    last_error: Optional[str] = None
    started_at: Optional[float] = None
    frame_size: Optional[tuple[int, int]] = None   # (width, height)
    fps: Optional[float] = None


class CaptureWorker:
    """
    RTSP 한 개를 받아서 세그먼트 파일로 떨구는 스레드 워커.

    사용 예:
        worker = CaptureWorker("cam-1", rtsp_url, Path("storage/clips"), 60)
        worker.start()
        ...
        worker.stop()
    """

    def __init__(
        self,
        camera_id: str,
        rtsp_url: str,
        storage_dir: Path,
        segment_seconds: int = 60,
    ) -> None:
        self.camera_id = camera_id
        self._rtsp_url = rtsp_url
        self._storage_dir = storage_dir
        self._segment_seconds = segment_seconds

        # 스레드 제어
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 상태 보호용 lock.
        # 왜 필요? Python GIL은 단일 바이트코드 수준 atomic만 보장.
        # 여러 필드를 "스냅샷으로 일관되게" 읽으려면 명시적 lock 필요.
        # (예: frames_read 증가 + last_frame_ts 갱신이 중간에 읽히면 어긋남)
        self._lock = threading.Lock()
        self._state = CaptureState(camera_id=camera_id)

    # ── 외부 API ────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        # daemon=True → 메인 프로세스 종료 시 같이 죽음. uvicorn Ctrl+C 대응.
        self._thread = threading.Thread(
            target=self._run, name=f"capture-{self.camera_id}", daemon=True
        )
        with self._lock:
            self._state.started_at = time.time()
            self._state.is_running = True
            self._state.last_error = None
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        with self._lock:
            self._state.is_running = False
            self._state.is_connected = False

    def snapshot(self) -> CaptureState:
        """현재 상태의 복사본. 엔드포인트에서 이걸 dict화해서 반환."""
        with self._lock:
            # dataclass는 얕은 복사도 충분 (내부가 전부 immutable).
            return CaptureState(**self._state.__dict__)

    # ── 내부 루프 ───────────────────────────────────────────────────────
    def _run(self) -> None:
        """스레드 본체. 연결 실패해도 stop_event 올 때까지 재연결 계속 시도."""
        while not self._stop_event.is_set():
            cap = self._open_with_retry()
            if cap is None:
                # 재연결 시도 실패 → 짧게 쉬고 다시.
                # stop()이 호출되면 event 체크로 빠져나감.
                if self._stop_event.wait(CONNECT_RETRY_INTERVAL):
                    break
                continue

            try:
                self._capture_loop(cap)
            except Exception as exc:
                # VideoWriter 오픈 실패 등 예기치 못한 예외.
                # 워커 스레드 자체가 죽으면 엔드포인트가 영원히 "running이지만 동작 X"로 보임.
                # 상태에 기록하고 재연결 루프로 복귀.
                with self._lock:
                    self._state.last_error = f"capture loop crashed: {exc}"
            finally:
                cap.release()
                with self._lock:
                    self._state.is_connected = False

    def _open_with_retry(self) -> Optional[cv2.VideoCapture]:
        for attempt in range(1, CONNECT_MAX_RETRIES + 1):
            if self._stop_event.is_set():
                return None
            cap = cv2.VideoCapture(self._rtsp_url)
            if cap.isOpened():
                with self._lock:
                    self._state.is_connected = True
                    self._state.last_error = None
                return cap
            cap.release()
            msg = f"RTSP open failed (attempt {attempt}/{CONNECT_MAX_RETRIES})"
            with self._lock:
                self._state.last_error = msg
            if attempt < CONNECT_MAX_RETRIES:
                if self._stop_event.wait(CONNECT_RETRY_INTERVAL):
                    return None
        return None

    def _capture_loop(self, cap: cv2.VideoCapture) -> None:
        """실제 프레임 수신 + 세그먼트 저장 루프."""
        # FPS 는 카메라 메타값 대신 실측 기반 상수 사용. (CAPTURE_FPS 주석 참조)
        # 해상도는 첫 프레임 받고 확정.
        fps = CAPTURE_FPS

        writer: Optional[cv2.VideoWriter] = None
        segment_path: Optional[Path] = None
        segment_started: float = 0.0
        consecutive_fail = 0
        width: int = 0
        height: int = 0

        try:
            while not self._stop_event.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    consecutive_fail += 1
                    if consecutive_fail >= FRAME_READ_MAX_FAILS:
                        # 끊긴 걸로 판단 → 루프 벗어나서 재연결.
                        with self._lock:
                            self._state.last_error = (
                                f"frame read fail x{consecutive_fail} → reconnect"
                            )
                        break
                    time.sleep(FRAME_SLEEP_ON_FAIL)
                    continue

                consecutive_fail = 0
                now = time.time()

                # 첫 유효 프레임에서 해상도 확정 & 세그먼트 writer 오픈
                if writer is None:
                    height, width = frame.shape[:2]
                    with self._lock:
                        self._state.frame_size = (width, height)
                        self._state.fps = fps
                    writer, segment_path = self._open_new_segment(width, height, fps)
                    segment_started = now

                writer.write(frame)
                with self._lock:
                    self._state.frames_read += 1
                    self._state.last_frame_ts = now

                # 세그먼트 roll-over
                if now - segment_started >= self._segment_seconds:
                    writer.release()
                    with self._lock:
                        self._state.segments_written += 1
                    writer, segment_path = self._open_new_segment(width, height, fps)
                    segment_started = now
        finally:
            if writer is not None:
                writer.release()
                # 중도 종료된 세그먼트도 하나 센다 — 파일은 정상이니까.
                with self._lock:
                    self._state.segments_written += 1
                    self._state.current_segment = None

    def _open_new_segment(
        self, width: int, height: int, fps: float
    ) -> tuple[cv2.VideoWriter, Path]:
        """날짜 폴더 만들고 새 VideoWriter 열기."""
        now = datetime.now()
        day_dir = self._storage_dir / now.strftime("%Y-%m-%d") / self.camera_id
        day_dir.mkdir(parents=True, exist_ok=True)

        filename = now.strftime("%H%M%S") + ".mp4"
        path = day_dir / filename

        fourcc = cv2.VideoWriter_fourcc(*VIDEO_FOURCC)
        writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
        if not writer.isOpened():
            # VideoWriter 오픈 실패는 코덱/권한 문제. 상위로 전파.
            with self._lock:
                self._state.last_error = f"VideoWriter open failed: {path}"
            raise RuntimeError(f"cannot open VideoWriter for {path}")

        with self._lock:
            self._state.current_segment = filename
        return writer, path

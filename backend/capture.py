"""
RTSP 캡처 워커 + 움직임 감지 태그 + CFR(Constant Frame Rate) 보정.

백그라운드 스레드에서 RTSP 프레임을 계속 읽어 1분 단위 mp4 세그먼트로 저장한다.
각 세그먼트는 종료 시점에 `_motion` / `_idle` 접미사로 rename 된다.

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

## Stage B 기능
- FPS 자동 측정 (워커 시작 시 10초 warmup)
- 프레임마다 MotionDetector.update() 호출
- run-length 방식 motion 집계:
  "min_duration_frames 이상 연속된 run" 만 유효 motion 으로 카운트
- 세그먼트 종료 시 누적 motion 초 ≥ threshold_sec 이면 _motion.mp4 로 rename

## CFR 보정 (2026-04-20 추가)
**문제**: RTSP 수신 FPS가 네트워크 상태로 요동쳐서 (3~15fps) 영상 재생 시간이
실제 녹화 시간과 어긋남. 예) 60초간 녹화했는데 재생은 21초.

**원인**: VideoWriter 는 CFR(고정 프레임률) 모드. fps 한 번 선언하면 끝.
선언 fps × 저장된 프레임 수 = 재생 시간 → 수신 fps 변동 시 어긋남.

**해결**: 매 프레임 "지금까지 써야 할 이상적 프레임 수" 계산 →
- 부족분은 직전 프레임 복제로 패딩
- 초과분은 드롭 (단, motion.update() 는 항상 호출해서 감지 정확도 유지)
- 세그먼트 roll-over 시 target(=segment_seconds × fps)까지 패딩 완료

## 코덱 교체 (2026-04-20 추가)
mp4v(MPEG-4 Part 2) → H.264 계열 폴백 체인.
H.264는 mp4v 대비 30~50% 파일 크기 감소. 품질은 동등 이상.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from backend.motion import MotionDetector

# 재시도 상수
CONNECT_MAX_RETRIES = 3
CONNECT_RETRY_INTERVAL = 2.0
FRAME_READ_MAX_FAILS = 30
FRAME_SLEEP_ON_FAIL = 0.1

# FPS 자동 측정 관련
FPS_MEASURE_SEC = 10.0            # 워커 시작 직후 이만큼 측정
FPS_FALLBACK = 12.0               # 측정 실패/이상값일 때 사용
FPS_MIN_VALID = 5.0               # 이 미만이면 이상값 (fallback 사용)
FPS_MAX_VALID = 60.0              # 이 이상이면 이상값
FIRST_FRAME_MAX_ATTEMPTS = 30     # 첫 유효 프레임 받기 최대 시도
FIRST_FRAME_SLEEP = 0.1

# 코덱 폴백 — 위부터 시도, 처음 성공한 것 세션 동안 재사용.
# avc1/H264/X264 모두 H.264 를 가리키지만 OpenCV 빌드에 따라 이름이 다름.
# mp4v 는 최후 폴백 (크기는 크지만 어떤 OpenCV 빌드든 대부분 뜬다).
VIDEO_FOURCC_CANDIDATES = ("avc1", "H264", "X264", "mp4v")

# 세그먼트 유효성 판정 — 둘 중 하나라도 걸리면 삭제.
# 시간 기반이 더 견고(코덱/장면 복잡도 무관), 바이트는 0바이트/거의 빈 파일 안전장치.
MIN_SEGMENT_SEC = 5.0        # motion threshold(3s) + 안전 마진. 5초 미만은 분석 가치 낮음
MIN_SEGMENT_BYTES = 50_000   # 거의 비어있는 파일 대비 하한


# ── CFR 보정 Pure Function ─────────────────────────────────────────────
# 테스트 가능하도록 클래스 바깥에 둔다. 시간/IO 의존 없음.

def compute_padding_count(frames_written: int, expected_frames: int) -> int:
    """
    '지금까지 이미 썼어야 할 이상적 프레임 수(expected)' 대비 부족분.

    expected 에서 1 을 빼는 이유:
    현재 들어온 진짜 프레임이 바로 다음 자리를 채울 예정이므로, 그 자리는
    미리 패딩하면 중복된다. 그래서 '현재 프레임 이전까지' 를 기준으로 패딩.
    """
    return max(0, expected_frames - 1 - frames_written)


def should_drop_frame(frames_written: int, expected_frames: int) -> bool:
    """
    현재 들어온 프레임을 writer 에 쓰지 말아야 하는가?

    이미 expected 만큼 썼다면 (=수신이 선언 fps 보다 빠름) 현재 프레임은 드롭.
    이때도 motion 판정은 호출 → 실제 장면 기반 감지 정확도 보존.
    """
    return frames_written >= expected_frames


@dataclass
class CaptureState:
    """워커 상태 스냅샷. /streams/{camera_id}/status 응답 바디의 원본."""
    camera_id: str
    is_running: bool = False
    is_connected: bool = False
    last_frame_ts: Optional[float] = None
    frames_read: int = 0
    segments_written: int = 0
    current_segment: Optional[str] = None
    last_error: Optional[str] = None
    started_at: Optional[float] = None
    frame_size: Optional[tuple[int, int]] = None
    fps: Optional[float] = None
    # Stage B
    last_motion_ts: Optional[float] = None       # 가장 최근 motion 감지 시각
    motion_segments_today: int = 0               # 오늘 저장된 _motion.mp4 개수
    measured_fps: Optional[float] = None         # 시작 시 실측한 effective fps
    # CFR + 코덱
    codec: Optional[str] = None                  # 실제로 열린 VideoWriter fourcc
    # 디버깅/튜닝 (motion 판정 실시간 관찰용)
    last_changed_ratio: float = 0.0              # 최근 프레임 픽셀 변화 비율 (%)
    segment_motion_frames: int = 0               # 현재 세그먼트 누적 '유효 run' 프레임 수


class CaptureWorker:
    """
    RTSP 한 개를 받아 motion-tagged + CFR-보정된 세그먼트로 떨구는 스레드 워커.

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
        *,
        motion_detector: Optional[MotionDetector] = None,
        motion_min_duration_frames: int = 12,
        motion_segment_threshold_sec: float = 3.0,
        clip_recorder: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        self.camera_id = camera_id
        self._rtsp_url = rtsp_url
        self._storage_dir = storage_dir
        self._segment_seconds = segment_seconds

        # Stage B 파라미터
        self._motion = motion_detector or MotionDetector()
        self._motion_min_duration = motion_min_duration_frames
        self._motion_segment_threshold_sec = motion_segment_threshold_sec

        # Stage C — 세그먼트 완료 시 camera_clips 에 INSERT 를 요청하는 콜백.
        # None 이면 DB 기록 없이 동작 (Supabase 미설정 환경에서도 캡처는 돌도록).
        self._clip_recorder = clip_recorder

        # 첫 세그먼트에서 성공한 fourcc 를 기억해서 이후 재사용
        self._fourcc_used: Optional[str] = None

        # 스레드 제어
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 상태 보호용 lock
        self._lock = threading.Lock()
        self._state = CaptureState(camera_id=camera_id)

    # ── 외부 API ────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
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
            return CaptureState(**self._state.__dict__)

    # ── 내부 루프 ───────────────────────────────────────────────────────
    def _run(self) -> None:
        """스레드 본체. 연결 실패해도 stop_event 올 때까지 재연결 계속 시도."""
        while not self._stop_event.is_set():
            cap = self._open_with_retry()
            if cap is None:
                if self._stop_event.wait(CONNECT_RETRY_INTERVAL):
                    break
                continue

            try:
                self._capture_loop(cap)
            except Exception as exc:
                with self._lock:
                    self._state.last_error = f"capture loop crashed: {exc}"
            finally:
                cap.release()
                with self._lock:
                    self._state.is_connected = False
                # 재연결 시 motion detector 상태 초기화 (장면 단절 대응)
                self._motion.reset()

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

    def _wait_first_frame(self, cap: cv2.VideoCapture) -> Optional[np.ndarray]:
        """연결 직후 첫 유효 프레임이 올 때까지 대기. 해상도 확정용."""
        for _ in range(FIRST_FRAME_MAX_ATTEMPTS):
            if self._stop_event.is_set():
                return None
            ok, frame = cap.read()
            if ok and frame is not None:
                return frame
            time.sleep(FIRST_FRAME_SLEEP)
        return None

    def _measure_fps(self, cap: cv2.VideoCapture) -> float:
        """
        워커 시작 직후 FPS_MEASURE_SEC 동안 프레임 수신률 측정.

        이 구간의 프레임은 VideoWriter 에 쓰이지 않음 (첫 세그먼트가 10초 짧아지는 대신,
        이후 모든 세그먼트의 재생시간이 정확해짐).
        """
        frame_count = 0
        start = time.perf_counter()
        while True:
            if self._stop_event.is_set():
                break
            elapsed = time.perf_counter() - start
            if elapsed >= FPS_MEASURE_SEC:
                break
            ok, _ = cap.read()
            if ok:
                frame_count += 1

        elapsed = time.perf_counter() - start
        if elapsed <= 0 or frame_count < 2:
            return FPS_FALLBACK

        measured = frame_count / elapsed
        if not (FPS_MIN_VALID <= measured <= FPS_MAX_VALID):
            return FPS_FALLBACK
        return round(measured, 2)

    def _capture_loop(self, cap: cv2.VideoCapture) -> None:
        """실제 프레임 수신 + 세그먼트 저장 + motion 태그 + CFR 보정 루프."""
        # 1) 해상도 확정 (첫 유효 프레임)
        first_frame = self._wait_first_frame(cap)
        if first_frame is None:
            with self._lock:
                self._state.last_error = "no valid frame within warmup window"
            return
        height, width = first_frame.shape[:2]

        # 2) FPS 측정 (10초) — 이 구간 프레임은 기록 안 함
        fps = self._measure_fps(cap)
        if self._stop_event.is_set():
            return

        with self._lock:
            self._state.frame_size = (width, height)
            self._state.fps = fps
            self._state.measured_fps = fps

        # 3) 본격 루프 상태
        writer: Optional[cv2.VideoWriter] = None
        segment_path: Optional[Path] = None
        segment_started = 0.0
        segment_motion_frames = 0       # 세그먼트 내 "유효 run" 누적 프레임 (수신 기준)
        consecutive_motion = 0          # 현재 진행 중인 motion run 길이
        consecutive_fail = 0

        # CFR 보정 상태
        segment_frames_written = 0      # 현재 세그먼트에 실제로 write 된 프레임 수
        last_written_frame: Optional[np.ndarray] = None  # 패딩용 복제 대상

        # 날짜 카운터 리셋 기준
        current_date = datetime.now().strftime("%Y-%m-%d")

        try:
            while not self._stop_event.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    consecutive_fail += 1
                    if consecutive_fail >= FRAME_READ_MAX_FAILS:
                        with self._lock:
                            self._state.last_error = (
                                f"frame read fail x{consecutive_fail} → reconnect"
                            )
                        break
                    time.sleep(FRAME_SLEEP_ON_FAIL)
                    continue

                consecutive_fail = 0
                now = time.time()

                # 첫 유효 프레임이면 VideoWriter 개설 + CFR 상태 초기화
                if writer is None:
                    writer, segment_path = self._open_new_segment(width, height, fps)
                    segment_started = now
                    segment_frames_written = 0
                    last_written_frame = None

                # CFR: 지금까지 써야 할 이상적 프레임 수
                segment_elapsed = now - segment_started
                expected = int(segment_elapsed * fps)

                # (1) 패딩: 부족분만큼 직전 프레임 복제
                padding_count = compute_padding_count(
                    segment_frames_written, expected
                )
                if padding_count > 0 and last_written_frame is not None:
                    for _ in range(padding_count):
                        writer.write(last_written_frame)
                        segment_frames_written += 1

                # (2) 현재 프레임 write or 드롭
                if not should_drop_frame(segment_frames_written, expected):
                    writer.write(frame)
                    segment_frames_written += 1
                    last_written_frame = frame
                # else: 드롭 — writer 에 안 씀. motion 은 아래에서 판정.

                # Motion 판정 (드롭 여부와 무관, 항상 실행)
                is_motion_frame = self._motion.update(frame)
                if is_motion_frame:
                    consecutive_motion += 1
                    with self._lock:
                        self._state.last_motion_ts = now
                else:
                    # run 종료 — 길이 충분하면 세그먼트 카운트에 누적
                    if consecutive_motion >= self._motion_min_duration:
                        segment_motion_frames += consecutive_motion
                    consecutive_motion = 0

                with self._lock:
                    self._state.frames_read += 1
                    self._state.last_frame_ts = now
                    # 튜닝 관찰용: 실시간 픽셀 변화 % + 세그먼트 내 누적 motion
                    self._state.last_changed_ratio = self._motion.last_changed_ratio
                    self._state.segment_motion_frames = segment_motion_frames

                # 세그먼트 roll-over
                segment_elapsed_final = now - segment_started
                if segment_elapsed_final >= self._segment_seconds:
                    # 진행 중이던 run 도 처리 (경계에서 잘린 경우)
                    if consecutive_motion >= self._motion_min_duration:
                        segment_motion_frames += consecutive_motion
                    consecutive_motion = 0

                    # 마지막 패딩: target 프레임 수까지 마저 채움 → 재생 60초 보장
                    target = int(self._segment_seconds * fps)
                    if last_written_frame is not None:
                        while segment_frames_written < target:
                            writer.write(last_written_frame)
                            segment_frames_written += 1

                    # motion 판정
                    motion_sec = segment_motion_frames / fps if fps > 0 else 0.0
                    is_motion_seg = motion_sec >= self._motion_segment_threshold_sec

                    renamed = self._close_and_tag_segment(
                        writer, segment_path, is_motion_seg, segment_elapsed_final
                    )
                    if renamed is not None:
                        current_date = self._bump_segment_counters(
                            current_date, is_motion_seg
                        )
                        self._record_clip(
                            path=renamed,
                            started_at=segment_started,
                            duration_sec=segment_elapsed_final,
                            is_motion=is_motion_seg,
                            motion_frames_count=segment_motion_frames,
                        )

                    # 다음 세그먼트 (+ CFR 상태 리셋)
                    writer, segment_path = self._open_new_segment(width, height, fps)
                    segment_started = now
                    segment_motion_frames = 0
                    segment_frames_written = 0
                    last_written_frame = None
        finally:
            if writer is not None and segment_path is not None:
                # 종료 시 진행 중이던 run 처리
                if consecutive_motion >= self._motion_min_duration:
                    segment_motion_frames += consecutive_motion

                # 실제 경과 시간 (네트워크 끊김·stop 시 60초 고정은 거짓말)
                elapsed_final = (
                    time.time() - segment_started if segment_started > 0 else 0.0
                )

                # 실제 경과 시간까지만 패딩
                if last_written_frame is not None and segment_started > 0:
                    final_target = int(elapsed_final * fps)
                    while segment_frames_written < final_target:
                        writer.write(last_written_frame)
                        segment_frames_written += 1

                motion_sec = segment_motion_frames / fps if fps > 0 else 0.0
                is_motion_seg = motion_sec >= self._motion_segment_threshold_sec

                renamed = self._close_and_tag_segment(
                    writer, segment_path, is_motion_seg, elapsed_final
                )
                if renamed is not None:
                    self._bump_segment_counters(current_date, is_motion_seg)
                    self._record_clip(
                        path=renamed,
                        started_at=segment_started,
                        duration_sec=elapsed_final,
                        is_motion=is_motion_seg,
                        motion_frames_count=segment_motion_frames,
                    )
                with self._lock:
                    self._state.current_segment = None

    # ── 세그먼트 I/O 헬퍼 ────────────────────────────────────────────────
    def _open_new_segment(
        self, width: int, height: int, fps: float
    ) -> tuple[cv2.VideoWriter, Path]:
        """
        날짜 폴더 만들고 새 VideoWriter 열기. 파일명은 HHMMSS.mp4 (태그 없음, 종료 시 rename).

        코덱 폴백:
        - 첫 호출에서 VIDEO_FOURCC_CANDIDATES 순서대로 시도, 성공한 것을 self._fourcc_used 에 저장
        - 이후 호출은 self._fourcc_used 만 시도 (세션 내 코덱 재협상 불필요)
        """
        now = datetime.now()
        day_dir = self._storage_dir / now.strftime("%Y-%m-%d") / self.camera_id
        day_dir.mkdir(parents=True, exist_ok=True)

        filename = now.strftime("%H%M%S") + ".mp4"
        path = day_dir / filename

        if self._fourcc_used is not None:
            candidates: tuple[str, ...] = (self._fourcc_used,)
        else:
            candidates = VIDEO_FOURCC_CANDIDATES

        writer: Optional[cv2.VideoWriter] = None
        used: Optional[str] = None
        tried: list[str] = []
        for fourcc_name in candidates:
            tried.append(fourcc_name)
            fourcc = cv2.VideoWriter_fourcc(*fourcc_name)
            candidate = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
            if candidate.isOpened():
                writer = candidate
                used = fourcc_name
                break
            candidate.release()
            # 실패한 코덱이 남긴 빈 파일 정리
            try:
                path.unlink()
            except FileNotFoundError:
                pass

        if writer is None or used is None:
            with self._lock:
                self._state.last_error = (
                    f"VideoWriter open failed (tried: {tried}): {path}"
                )
            raise RuntimeError(f"cannot open VideoWriter for {path}")

        self._fourcc_used = used
        with self._lock:
            self._state.current_segment = filename
            self._state.codec = used
        return writer, path

    def _close_and_tag_segment(
        self,
        writer: cv2.VideoWriter,
        path: Path,
        is_motion: bool,
        elapsed_sec: float,
    ) -> Optional[Path]:
        """
        VideoWriter 닫고, 유효 세그먼트면 _motion/_idle 접미사로 rename.

        아래 중 하나라도 해당하면 삭제 (카운터 증가 금지):
        - 경과 시간 < MIN_SEGMENT_SEC: motion 판정 임계(3초)조차 못 채우는 짧은 조각
        - 파일 크기 < MIN_SEGMENT_BYTES: 거의 비어있는 깨진 파일 (0바이트 방지)

        Returns:
            rename 된 최종 Path: 정상 저장됨 (Stage C 에서 INSERT 대상)
            None: 파일이 삭제됨. 카운터 증가 / INSERT 모두 건너뜀.

        rename 자체가 실패해도 파일은 원래 이름(suffix 없이)으로 남아있으므로
        원본 path 를 대신 리턴 — INSERT 는 진행되게 함.
        """
        writer.release()

        try:
            size = path.stat().st_size if path.exists() else 0
        except OSError:
            size = 0

        too_short = elapsed_sec < MIN_SEGMENT_SEC
        too_small = size < MIN_SEGMENT_BYTES

        if too_short or too_small:
            try:
                path.unlink()
            except (OSError, FileNotFoundError):
                pass
            reason = (
                f"too short ({elapsed_sec:.1f}s)"
                if too_short
                else f"tiny ({size}B)"
            )
            with self._lock:
                self._state.last_error = (
                    f"dropped segment [{reason}]: {path.name}"
                )
            return None

        suffix = "_motion" if is_motion else "_idle"
        new_path = path.with_name(path.stem + suffix + path.suffix)
        try:
            path.rename(new_path)
            return new_path
        except OSError as exc:
            with self._lock:
                self._state.last_error = f"rename failed: {exc}"
            return path

    def _bump_segment_counters(self, current_date: str, is_motion: bool) -> str:
        """
        세그먼트 완료 카운터 갱신. 날짜 바뀌었으면 오늘자 motion 카운터 리셋.
        새 current_date 리턴 (호출부에서 보관).
        """
        today = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            self._state.segments_written += 1
            if today != current_date:
                self._state.motion_segments_today = 0
            if is_motion:
                self._state.motion_segments_today += 1
        return today

    def _record_clip(
        self,
        path: Path,
        started_at: float,
        duration_sec: float,
        is_motion: bool,
        motion_frames_count: int,
    ) -> None:
        """
        camera_clips INSERT 요청 (Stage C). clip_recorder 미설정이면 no-op.

        recorder 자체가 INSERT 실패를 pending 큐로 돌리지만,
        여기서 예외가 더 위로 올라가 캡처 루프를 죽이지 않도록 한 번 더 감싼다.
        """
        if self._clip_recorder is None:
            return
        try:
            size = path.stat().st_size if path.exists() else 0
            width, height = self._state.frame_size or (0, 0)
            started_iso = datetime.fromtimestamp(
                started_at, tz=timezone.utc
            ).isoformat()
            self._clip_recorder(
                {
                    "camera_id": self.camera_id,
                    "started_at": started_iso,
                    "duration_sec": float(duration_sec),
                    "has_motion": bool(is_motion),
                    "motion_frames": int(motion_frames_count),
                    "file_path": str(path),
                    "file_size": int(size),
                    "codec": self._fourcc_used,
                    "width": int(width) if width else None,
                    "height": int(height) if height else None,
                    "fps": float(self._state.fps) if self._state.fps else None,
                }
            )
        except Exception as exc:
            with self._lock:
                self._state.last_error = f"clip record error: {exc}"

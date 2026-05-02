"""
인코딩 + R2 업로드 worker queue (spec §3-4 / §4 결정 1).

캡처 워커(sync thread) 가 세그먼트 종료 시 `enqueue(clip_fields)` 호출만 하고
즉시 다음 루프. 인코딩 (`encode_lightweight`) + R2 업로드 (`upload_clip`) 는
asyncio worker pool 이 dequeue 해서 처리한 다음 `recorder` 에 R2 메타가 채워진
payload 를 넘긴다.

## 왜 분리?
ffmpeg 인코딩 + R2 업로드는 합쳐서 수 초 단위 blocking I/O. 캡처 thread 가 직접
실행하면 RTSP drift / 다음 세그먼트 시작 지연. spec §4 결정 1 (worker queue) 채택.

## 흐름
1. 캡처 thread → `enqueue_callback(clip_fields)` 호출 (capture._record_clip 안)
2. callback → `loop.call_soon_threadsafe(_try_enqueue, ...)` 로 asyncio Queue 에 put
3. worker task → `await queue.get()` → `_process_one`:
   a. clip_id pre-generate (UUID4) — DB row id + R2 key 모두에 동일하게 박힘
   b. R2 키 빌드 (`clips/{cam}/{date}/{HHMMSS}_{tag}_{clip_id}.mp4`)
   c. `storage/encoded/{date}/{cam}/{HHMMSS}_{tag}_{clip_id}.mp4` 로 인코딩
   d. R2 mp4 + thumbnail 업로드
   e. recorder 호출 (= Supabase INSERT)

## 실패 정책 (spec §4 결정 2 — 단일)
모든 실패 케이스 → `r2_key=NULL`, `encoded_file_size=NULL` 로 recorder 진행.
로컬 원본만 유지, 자동 재시도 없음. 후속 batch backfill 스크립트 (이번 스펙 Out).

| 실패 종류                    | r2_key | thumbnail_r2_key | recorder 호출 |
|------------------------------|--------|------------------|---------------|
| 인코딩 실패/타임아웃          | NULL   | NULL             | ✅            |
| R2 mp4 업로드 실패            | NULL   | NULL             | ✅            |
| R2 썸네일만 실패              | 채워짐 | NULL             | ✅            |
| Queue full (enqueue 시점)     | NULL   | NULL             | ✅ (즉시)     |
| Loop down (lifespan shutdown) | NULL   | NULL             | ✅ (즉시)     |

## 동시성
`DEFAULT_WORKER_CONCURRENCY=2` — 카메라 2 대 가정. 카메라당 1 worker 가용 = 60s
세그먼트당 인코딩+업로드 (보통 ≤5s) 충분 마진. 카메라 늘리면 N 도 같이.

## Queue maxsize
`DEFAULT_QUEUE_MAXSIZE=32` — 카메라 2 대 × 워커가 16 분 밀려도 흡수. 가득 차면
즉시 fallback 으로 record 만 진행. 메모리 폭발 방지가 단일 정책보다 우선.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from backend.encoding import FFmpegNotFound, encode_lightweight
from backend.r2_uploader import (
    BotoCoreError,
    ClientError,
    R2NotConfigured,
    upload_clip,
)

logger = logging.getLogger(__name__)

DEFAULT_QUEUE_MAXSIZE = 32
DEFAULT_WORKER_CONCURRENCY = 2

# stop() 시 진행 중 작업 + 큐 잔여분 처리 대기 시간. ffmpeg 1건 ≤30s + 업로드 ≤10s
# = 40s. concurrency=2 + 큐 잔여 가정해 90s 마진.
STOP_DRAIN_TIMEOUT_SEC = 90.0

# 큐 payload 타입 — (recorder, clip_fields). recorder 가 카메라마다 다른 closure 라
# 큐에 함께 실어 보낸다. dict 만 넣으면 worker 가 어느 recorder 를 부를지 모름.
_QueueItem = tuple[Callable[[dict[str, Any]], None], dict[str, Any]]


class EncodeUploadWorker:
    """
    asyncio worker pool. lifespan 에서 `start()` / `await stop()`.

    Args:
        encoded_dir: 인코딩 산출물 폴더. 원본 (`storage/clips/`) 와 분리해
            R2 키와 동일한 네이밍으로 저장 → 디버깅·고아 파일 추적 쉬움.
        concurrency: 동시 worker task 수. 보통 카메라 수와 동일.
        queue_maxsize: asyncio.Queue maxsize. 가득 차면 enqueue 시점에 fallback.
    """

    def __init__(
        self,
        encoded_dir: Path,
        concurrency: int = DEFAULT_WORKER_CONCURRENCY,
        queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE,
    ) -> None:
        self._encoded_dir = encoded_dir
        self._concurrency = concurrency
        self._queue_maxsize = queue_maxsize
        # asyncio.Queue 는 running loop 에 bind. start() 에서 생성.
        self._queue: Optional[asyncio.Queue[_QueueItem]] = None
        self._tasks: list[asyncio.Task] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stopping = False

    # ── lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        """N 개 worker task 부트스트랩. lifespan startup 안 (running loop 있어야 함)."""
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=self._queue_maxsize)
        self._stopping = False
        for i in range(self._concurrency):
            task = asyncio.create_task(
                self._worker_loop(i), name=f"encode-upload-{i}"
            )
            self._tasks.append(task)
        logger.info(
            "encode_upload_worker started: concurrency=%d maxsize=%d",
            self._concurrency,
            self._queue_maxsize,
        )

    async def stop(self, timeout: float = STOP_DRAIN_TIMEOUT_SEC) -> None:
        """진행 중·대기 중 모두 처리 후 종료. 시간 초과 시 강제 cancel.

        먼저 한 번 yield 해서 캡처 thread 가 직전에 호출한 `call_soon_threadsafe`
        콜백들이 실제로 큐에 put_nowait 까지 마치게 둔다. 안 그러면 `queue.join()`
        시점에 아직 enqueue 안 된 작업이 있어서 0 으로 즉시 리턴.
        """
        self._stopping = True
        if self._queue is None:
            return
        await asyncio.sleep(0)
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "encode_upload_worker drain timeout (%.1fs), force cancel "
                "(queue size=%d)",
                timeout,
                self._queue.qsize(),
            )

        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("encode_upload_worker stopped")

    def queue_size(self) -> int:
        """모니터링용. Queue 가 still None (start 전) 이면 0."""
        return self._queue.qsize() if self._queue is not None else 0

    # ── enqueue (캡처 thread 에서 호출됨) ──────────────────────────────

    def make_enqueue_callback(
        self, recorder: Callable[[dict[str, Any]], None]
    ) -> Callable[[dict[str, Any]], None]:
        """
        CaptureWorker 의 `clip_recorder` 슬롯에 끼울 callback.

        sync 캡처 thread → `loop.call_soon_threadsafe` 로 asyncio.Queue put_nowait.
        Queue full / loop down 시 즉시 recorder fallback (r2 메타 NULL) 로 데이터
        손실 없이 record 만이라도 진행.

        Args:
            recorder: 카메라당 한 번 만들어진 closure (`make_clip_recorder` 결과).
                      클로저에 `user_id` / `pet_id` 가 박혀있어 카메라마다 다름.

        Returns:
            CaptureWorker 가 sync 호출하는 callback.
        """

        def enqueue(clip_fields: dict[str, Any]) -> None:
            if self._stopping or self._loop is None or self._queue is None:
                logger.warning(
                    "enqueue while stopping/not-started → record without R2"
                )
                self._fallback_record(recorder, clip_fields, reason="not running")
                return

            try:
                self._loop.call_soon_threadsafe(
                    self._try_enqueue_threadsafe, recorder, clip_fields
                )
            except RuntimeError as exc:
                # loop 이 닫혔을 때 발생. fallback 으로 record.
                logger.warning("enqueue callback failed (loop down): %s", exc)
                self._fallback_record(recorder, clip_fields, reason="loop down")

        return enqueue

    def _try_enqueue_threadsafe(
        self,
        recorder: Callable[[dict[str, Any]], None],
        clip_fields: dict[str, Any],
    ) -> None:
        """asyncio thread (call_soon_threadsafe 경유) 안에서 실행됨."""
        assert self._queue is not None
        try:
            self._queue.put_nowait((recorder, clip_fields))
        except asyncio.QueueFull:
            logger.warning(
                "encode_upload queue full (size=%d) → record without R2: cam=%s",
                self._queue.qsize(),
                clip_fields.get("camera_id"),
            )
            self._fallback_record(recorder, clip_fields, reason="queue full")

    # ── worker body ───────────────────────────────────────────────────

    async def _worker_loop(self, idx: int) -> None:
        assert self._queue is not None
        while True:
            recorder, clip_fields = await self._queue.get()
            try:
                await self._process_one(recorder, clip_fields)
            except Exception as exc:  # noqa: BLE001 — 어떤 실수도 worker 죽이면 안 됨
                logger.exception(
                    "worker %d unexpected error (cam=%s): %s",
                    idx,
                    clip_fields.get("camera_id"),
                    exc,
                )
                # 마지막 보루 — 여기까지 왔으면 r2 fallback record 라도 시도.
                self._fallback_record(
                    recorder, clip_fields, reason=f"worker exception: {type(exc).__name__}"
                )
            finally:
                self._queue.task_done()

    async def _process_one(
        self,
        recorder: Callable[[dict[str, Any]], None],
        clip_fields: dict[str, Any],
    ) -> None:
        """1건 인코딩 + R2 업로드 + recorder 호출."""
        clip_id = str(uuid.uuid4())
        camera_id: str = clip_fields["camera_id"]
        original_path = Path(clip_fields["file_path"])
        thumb_path_raw = clip_fields.get("thumbnail_path")
        thumb_path = Path(thumb_path_raw) if thumb_path_raw else None
        original_size: int = clip_fields.get("file_size") or 0

        # R2 키 빌드 (spec §4 결정 7: clip_id 포함)
        date_str = _date_str_for_clip(original_path, clip_fields)
        stem = original_path.stem  # 예: "153012_motion"
        mp4_key = f"clips/{camera_id}/{date_str}/{stem}_{clip_id}.mp4"
        thumb_key = (
            f"thumbnails/{camera_id}/{date_str}/{stem}_{clip_id}.jpg"
            if thumb_path is not None
            else None
        )

        # 인코딩 산출물 경로 (R2 키 모양과 동일하게 로컬에 저장)
        encoded_dst = self._encoded_dir / date_str / camera_id / f"{stem}_{clip_id}.mp4"
        try:
            encoded_dst.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "encoded_dir mkdir failed (%s): %s", encoded_dst.parent, exc
            )
            self._fallback_record(
                recorder, clip_fields, reason="mkdir failed", clip_id=clip_id
            )
            return

        # 인코딩 (sync ffmpeg → to_thread)
        try:
            encode_ok = await asyncio.to_thread(
                encode_lightweight, original_path, encoded_dst
            )
        except (FileNotFoundError, ValueError, FFmpegNotFound) as exc:
            logger.warning(
                "encode pre-check failed (cam=%s src=%s): %s",
                camera_id,
                original_path,
                exc,
            )
            encode_ok = False

        if not encode_ok:
            self._fallback_record(
                recorder, clip_fields, reason="encode failed", clip_id=clip_id
            )
            return

        try:
            encoded_size = encoded_dst.stat().st_size
        except OSError:
            encoded_size = 0

        # R2 mp4 업로드
        mp4_uploaded = False
        try:
            await asyncio.to_thread(upload_clip, encoded_dst, mp4_key, "video/mp4")
            mp4_uploaded = True
        except (R2NotConfigured, ClientError, BotoCoreError, OSError) as exc:
            logger.warning(
                "R2 mp4 upload failed (key=%s): %s", mp4_key, exc
            )

        # 썸네일은 mp4 가 올라간 경우만 의미 있음 (라벨링 페이지가 mp4 못 받으면 썸도 무용)
        thumb_uploaded = False
        if mp4_uploaded and thumb_path is not None and thumb_key is not None:
            if thumb_path.is_file():
                try:
                    await asyncio.to_thread(
                        upload_clip, thumb_path, thumb_key, "image/jpeg"
                    )
                    thumb_uploaded = True
                except (R2NotConfigured, ClientError, BotoCoreError, OSError) as exc:
                    logger.warning(
                        "R2 thumbnail upload failed (key=%s): %s", thumb_key, exc
                    )
            else:
                logger.warning("thumbnail file missing on disk: %s", thumb_path)

        payload = {
            **clip_fields,
            "id": clip_id,
            "r2_key": mp4_key if mp4_uploaded else None,
            "thumbnail_r2_key": thumb_key if (mp4_uploaded and thumb_uploaded) else None,
            "encoded_file_size": encoded_size if mp4_uploaded else None,
            "original_file_size": original_size,
        }
        try:
            await asyncio.to_thread(recorder, payload)
        except Exception as exc:  # noqa: BLE001 — recorder 자체 예외도 worker 죽이면 안 됨
            logger.exception(
                "recorder failed after upload (cam=%s key=%s): %s",
                camera_id,
                mp4_key if mp4_uploaded else "(no r2)",
                exc,
            )

    # ── fallback ──────────────────────────────────────────────────────

    def _fallback_record(
        self,
        recorder: Callable[[dict[str, Any]], None],
        clip_fields: dict[str, Any],
        reason: str,
        clip_id: Optional[str] = None,
    ) -> None:
        """R2 메타 없이 recorder 호출. enqueue 실패·인코딩 실패·worker 예외 공통."""
        payload = {
            **clip_fields,
            "id": clip_id or str(uuid.uuid4()),
            "r2_key": None,
            "thumbnail_r2_key": None,
            "encoded_file_size": None,
            "original_file_size": clip_fields.get("file_size"),
        }
        try:
            recorder(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "fallback recorder failed (reason=%s, cam=%s): %s",
                reason,
                clip_fields.get("camera_id"),
                exc,
            )


# ── 헬퍼 ────────────────────────────────────────────────────────────────


def _date_str_for_clip(original_path: Path, clip_fields: dict[str, Any]) -> str:
    """
    R2 키의 날짜 부분 (`YYYY-MM-DD`).

    파일 경로 구조는 `storage/clips/<YYYY-MM-DD>/<camera_id>/<HHMMSS>_<tag>.mp4` 라
    `parent.parent.name` 이 날짜. 검증 실패 시 `started_at` 의 ISO 앞 10자로 fallback.
    """
    candidate = original_path.parent.parent.name
    if _is_iso_date(candidate):
        return candidate
    started = clip_fields.get("started_at", "")
    return started[:10] if _is_iso_date(started[:10]) else "unknown-date"


def _is_iso_date(s: str) -> bool:
    if not isinstance(s, str) or len(s) != 10:
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return False
    return True


__all__ = [
    "DEFAULT_QUEUE_MAXSIZE",
    "DEFAULT_WORKER_CONCURRENCY",
    "STOP_DRAIN_TIMEOUT_SEC",
    "EncodeUploadWorker",
]

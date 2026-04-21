"""
FastAPI 엔트리 — 앱 시작 시 RTSP 캡처 워커를 띄우고, 상태를 엔드포인트로 노출.

## 왜 lifespan?
- FastAPI 0.93+ 권장 패턴. `@app.on_event("startup")`은 deprecated.
- `yield` 이전이 startup, 이후가 shutdown. 컨텍스트 매니저 문법이라
  "정확히 shutdown에서 해제된다"가 보장됨.
- Node로 치면: Express의 `server.listen()` 앞뒤 + `process.on('SIGTERM')` 통합본.

## 왜 app.state?
- `Depends()`는 요청 스코프 주입이라 "앱 전체 하나 워커"와 맞지 않음.
  `app.state`는 라이프타임 싱글톤을 담는 표준 위치.
- Worker가 여러 개로 늘면 그 때 dict → Depends provider로 리팩터.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from backend.capture import CaptureWorker
from backend.clip_recorder import make_clip_recorder, make_flush_insert_fn
from backend.motion import MotionDetector
from backend.pending_inserts import PendingInsertQueue
from backend.routers.clips import router as clips_router
from backend.supabase_client import SupabaseNotConfigured, get_supabase_client

REPO_ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)

# 주기 flush 간격 (초). 스펙: 30초 — 자주 시도해도 Supabase 가 정상이면 빈 파일 read 1 번이라 저렴.
PENDING_FLUSH_INTERVAL_SEC = 30.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv(REPO_ROOT / ".env")

    # 기본 상태 초기화 (모든 분기에서 참조)
    app.state.capture_worker = None
    app.state.pending_queue = None
    app.state.startup_error = None

    rtsp_url = os.getenv("RTSP_URL")
    if not rtsp_url:
        # 캡처 없이도 /health는 뜨도록 — 설정 실수 디버깅 용이.
        app.state.startup_error = "RTSP_URL 미설정: 캡처 워커 없이 기동"
        yield
        return

    camera_id = os.getenv("CAMERA_ID", "cam-1")
    segment_seconds = int(os.getenv("SEGMENT_SECONDS", "60"))
    clips_dir = REPO_ROOT / os.getenv("CLIPS_DIR", "storage/clips")

    # Stage B — 움직임 감지 파라미터
    motion_detector = MotionDetector(
        pixel_threshold=int(os.getenv("MOTION_PIXEL_THRESHOLD", "25")),
        pixel_ratio_pct=float(os.getenv("MOTION_PIXEL_RATIO", "1.0")),
    )
    motion_min_frames = int(os.getenv("MOTION_MIN_DURATION_FRAMES", "12"))
    motion_seg_threshold = float(os.getenv("MOTION_SEGMENT_THRESHOLD_SEC", "3.0"))

    # Stage C — Supabase wiring. 미설정이면 INSERT 건너뛰고 캡처만 동작.
    clip_recorder = None
    pending_queue: Optional[PendingInsertQueue] = None
    flush_task: Optional[asyncio.Task] = None

    try:
        sb_client = get_supabase_client()
        dev_user_id = os.getenv("DEV_USER_ID")
        dev_pet_id = os.getenv("DEV_PET_ID") or None

        if not dev_user_id:
            app.state.startup_error = "DEV_USER_ID 미설정: 캡처는 동작, INSERT 없음"
        else:
            pending_queue = PendingInsertQueue(
                REPO_ROOT / "storage" / "pending_inserts.jsonl"
            )
            clip_recorder = make_clip_recorder(
                sb_client, pending_queue, dev_user_id, dev_pet_id
            )
            flush_insert = make_flush_insert_fn(sb_client)

            # 시작 시 1회 flush — 이전 실행에서 쌓인 pending 처리
            try:
                success, remaining = pending_queue.flush(flush_insert)
                if success or remaining:
                    logger.info(
                        "startup flush: %d sent, %d remaining",
                        success,
                        remaining,
                    )
            except Exception as exc:  # noqa: BLE001 — 시작 실패로 서버를 막지 말 것
                logger.warning("startup flush error: %s", exc)

            # 주기 flush — 네트워크 복구 시 밀린 pending 자동 전송
            async def _periodic_flush() -> None:
                while True:
                    await asyncio.sleep(PENDING_FLUSH_INTERVAL_SEC)
                    try:
                        s, r = await asyncio.to_thread(
                            pending_queue.flush, flush_insert
                        )
                        if s > 0:
                            logger.info(
                                "periodic flush: %d sent, %d remaining", s, r
                            )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("periodic flush error: %s", exc)

            flush_task = asyncio.create_task(_periodic_flush())
    except SupabaseNotConfigured as exc:
        app.state.startup_error = f"Supabase 미설정: 캡처만 동작 ({exc})"

    worker = CaptureWorker(
        camera_id=camera_id,
        rtsp_url=rtsp_url,
        storage_dir=clips_dir,
        segment_seconds=segment_seconds,
        motion_detector=motion_detector,
        motion_min_duration_frames=motion_min_frames,
        motion_segment_threshold_sec=motion_seg_threshold,
        clip_recorder=clip_recorder,
    )
    worker.start()

    app.state.capture_worker = worker
    app.state.pending_queue = pending_queue

    try:
        yield
    finally:
        worker.stop()
        if flush_task is not None:
            flush_task.cancel()
            try:
                await flush_task
            except asyncio.CancelledError:
                pass


app = FastAPI(lifespan=lifespan)
app.include_router(clips_router)


@app.get("/")
def root():
    return {"message": "petcam-lab is alive"}


@app.get("/health")
def health():
    worker: CaptureWorker | None = getattr(app.state, "capture_worker", None)
    return {
        "status": "ok",
        "capture_attached": worker is not None,
        "startup_error": getattr(app.state, "startup_error", None),
    }


@app.get("/streams/{camera_id}/status")
def stream_status(camera_id: str):
    """
    캡처 워커의 현재 상태 스냅샷.
    - 404: 해당 camera_id 워커가 없을 때 (설정된 CAMERA_ID와 다름)
    - 200: CaptureState dict
    """
    worker: CaptureWorker | None = getattr(app.state, "capture_worker", None)
    if worker is None or worker.camera_id != camera_id:
        raise HTTPException(
            status_code=404,
            detail=f"camera '{camera_id}' not found",
        )
    return asdict(worker.snapshot())

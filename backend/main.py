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

import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from backend.capture import CaptureWorker

REPO_ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv(REPO_ROOT / ".env")

    rtsp_url = os.getenv("RTSP_URL")
    if not rtsp_url:
        # 캡처 없이도 /health는 뜨도록 — 설정 실수 디버깅 용이.
        app.state.capture_worker = None
        app.state.startup_error = "RTSP_URL 미설정: 캡처 워커 없이 기동"
        yield
        return

    camera_id = os.getenv("CAMERA_ID", "cam-1")
    segment_seconds = int(os.getenv("SEGMENT_SECONDS", "60"))
    clips_dir = REPO_ROOT / os.getenv("CLIPS_DIR", "storage/clips")

    worker = CaptureWorker(
        camera_id=camera_id,
        rtsp_url=rtsp_url,
        storage_dir=clips_dir,
        segment_seconds=segment_seconds,
    )
    worker.start()

    app.state.capture_worker = worker
    app.state.startup_error = None

    try:
        yield
    finally:
        worker.stop()


app = FastAPI(lifespan=lifespan)


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

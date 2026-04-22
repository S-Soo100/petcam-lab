"""
FastAPI 엔트리 — 앱 시작 시 `cameras` 테이블에서 활성 카메라 N 대를 로드해서
각각 RTSP 캡처 워커 스레드를 띄우고, 상태를 엔드포인트로 노출.

## Stage D3 에서 바뀐 점
- 기존(D2 까지): `.env RTSP_URL` / `CAMERA_ID` 하나 → 워커 1 개.
- 이제: `cameras` 테이블 SELECT → 워커 N 개 (`app.state.capture_workers: dict`).
  카메라 정식 등록 경로(`POST /cameras`) 가 입구이자 유일 경로.

## 왜 lifespan?
- FastAPI 0.93+ 권장 패턴. `@app.on_event("startup")` 은 deprecated.
- `yield` 이전이 startup, 이후가 shutdown. 컨텍스트 매니저라
  "정확히 shutdown 에서 해제된다" 가 보장됨.
- Node 비유: Express 의 `server.listen()` 앞뒤 + `process.on('SIGTERM')` 통합.

## 왜 app.state?
- `Depends()` 는 요청 스코프라 "앱 전체 하나 dict(워커들)" 과 맞지 않음.
  `app.state` 는 라이프타임 싱글톤의 표준 위치.

## dev / prod 모드
- D3 범위 는 여전히 `DEV_USER_ID` 기반으로 cameras 조회.
- prod 는 앱 사용자별로 독립 서버 프로세스 또는 추후 확장. 지금은 1 유저 = 1 프로세스.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from backend.capture import CaptureWorker
from backend.clip_recorder import make_clip_recorder, make_flush_insert_fn
from backend.crypto import CryptoNotConfigured, decrypt_password
from backend.motion import MotionDetector
from backend.pending_inserts import PendingInsertQueue
from backend.routers.cameras import router as cameras_router
from backend.routers.clips import router as clips_router
from backend.rtsp_probe import build_rtsp_url
from backend.supabase_client import SupabaseNotConfigured, get_supabase_client

REPO_ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)

# 주기 flush 간격 (초). 스펙: 30 초 — 자주 시도해도 Supabase 정상이면 빈 파일 read 1 번.
PENDING_FLUSH_INTERVAL_SEC = 30.0


def _load_capture_config() -> dict[str, Any]:
    """캡처 공용 설정 (카메라 독립) 를 env 에서 한 번 읽어 dict 로.

    RTSP_URL / CAMERA_ID 는 D3 에서 폐기 — cameras 테이블이 원천.
    MOTION_* / SEGMENT_SECONDS / CLIPS_DIR 는 워커 공용 (카메라 별 override 는 아직 없음).
    """
    return {
        "segment_seconds": int(os.getenv("SEGMENT_SECONDS", "60")),
        "clips_dir": REPO_ROOT / os.getenv("CLIPS_DIR", "storage/clips"),
        "motion_pixel_threshold": int(os.getenv("MOTION_PIXEL_THRESHOLD", "25")),
        "motion_pixel_ratio": float(os.getenv("MOTION_PIXEL_RATIO", "1.0")),
        "motion_min_frames": int(os.getenv("MOTION_MIN_DURATION_FRAMES", "12")),
        "motion_seg_threshold_sec": float(
            os.getenv("MOTION_SEGMENT_THRESHOLD_SEC", "3.0")
        ),
    }


def _build_worker_for_camera(
    camera_row: dict[str, Any],
    sb_client,
    pending_queue: PendingInsertQueue,
    dev_user_id: str,
    config: dict[str, Any],
) -> Optional[CaptureWorker]:
    """카메라 행 1개 → CaptureWorker 1개. 비번 복호화 실패 시 None (호출부가 skip).

    clip_recorder 를 워커마다 새로 만드는 이유: 각 카메라의 `pet_id` 가 다를 수 있음.
    make_clip_recorder 는 closure 라 비용 저렴.
    """
    camera_id = camera_row["id"]  # UUID 문자열
    try:
        password = decrypt_password(camera_row["password_encrypted"])
    except Exception as exc:
        # InvalidToken (키 회전 / 변조) · ValueError (빈 ciphertext) 포함.
        # 해당 카메라만 skip, 나머지는 계속 돌려야 함.
        logger.error(
            "camera %s password decrypt failed: %s — worker skipped", camera_id, exc
        )
        return None

    rtsp_url = build_rtsp_url(
        host=camera_row["host"],
        port=camera_row["port"],
        path=camera_row["path"],
        username=camera_row["username"],
        password=password,
    )

    motion_detector = MotionDetector(
        pixel_threshold=config["motion_pixel_threshold"],
        pixel_ratio_pct=config["motion_pixel_ratio"],
    )
    clip_recorder = make_clip_recorder(
        sb_client, pending_queue, dev_user_id, camera_row.get("pet_id")
    )

    return CaptureWorker(
        camera_id=camera_id,
        rtsp_url=rtsp_url,
        storage_dir=config["clips_dir"],
        segment_seconds=config["segment_seconds"],
        motion_detector=motion_detector,
        motion_min_duration_frames=config["motion_min_frames"],
        motion_segment_threshold_sec=config["motion_seg_threshold_sec"],
        clip_recorder=clip_recorder,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv(REPO_ROOT / ".env")

    # 모든 분기에서 참조하는 기본 상태 — 실패 경로도 /health 는 살아있게.
    app.state.capture_workers: dict[str, CaptureWorker] = {}
    app.state.pending_queue = None
    app.state.startup_error: Optional[str] = None
    app.state.skipped_cameras: list[str] = []

    # Supabase 없으면 캡처 자체 불가 — /health 만 뜨게 (설정 실수 디버깅)
    try:
        sb_client = get_supabase_client()
    except SupabaseNotConfigured as exc:
        app.state.startup_error = f"Supabase 미설정: 캡처 없이 기동 ({exc})"
        yield
        return

    dev_user_id = os.getenv("DEV_USER_ID")
    if not dev_user_id:
        app.state.startup_error = "DEV_USER_ID 미설정: 캡처 없이 기동"
        yield
        return

    # cameras 로드 (service_role 이라 RLS 우회하지만 user_id 필터 명시)
    try:
        resp = (
            sb_client.table("cameras")
            .select("*")
            .eq("user_id", dev_user_id)
            .eq("is_active", True)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 — supabase-py 는 다양한 예외
        app.state.startup_error = f"cameras 조회 실패: {exc}"
        yield
        return

    camera_rows = resp.data or []
    if not camera_rows:
        app.state.startup_error = "등록된 카메라 없음. POST /cameras 로 등록 필요"
        yield
        return

    # 공용 pending queue — 파일 append only 라 워커 공유 안전.
    pending_queue = PendingInsertQueue(
        REPO_ROOT / "storage" / "pending_inserts.jsonl"
    )
    app.state.pending_queue = pending_queue
    flush_insert = make_flush_insert_fn(sb_client)

    # startup 1 회 flush — 이전 실행에서 밀린 pending 처리.
    try:
        sent, remaining = pending_queue.flush(flush_insert)
        if sent or remaining:
            logger.info("startup flush: %d sent, %d remaining", sent, remaining)
    except Exception as exc:  # noqa: BLE001 — 시작 실패로 서버를 막지 말 것
        logger.warning("startup flush error: %s", exc)

    # 주기 flush — 네트워크 복구 시 밀린 pending 자동 전송.
    async def _periodic_flush() -> None:
        while True:
            await asyncio.sleep(PENDING_FLUSH_INTERVAL_SEC)
            try:
                s, r = await asyncio.to_thread(pending_queue.flush, flush_insert)
                if s > 0:
                    logger.info("periodic flush: %d sent, %d remaining", s, r)
            except Exception as exc:  # noqa: BLE001
                logger.warning("periodic flush error: %s", exc)

    flush_task = asyncio.create_task(_periodic_flush())

    # 워커 N 개 부트스트랩
    config = _load_capture_config()
    try:
        # Fernet 싱글톤 선검증 — 전 카메라에 공통이므로 한 번만.
        # 실패 시 모든 워커 skip.
        from backend.crypto import get_camera_fernet

        get_camera_fernet()
    except CryptoNotConfigured as exc:
        app.state.startup_error = f"CAMERA_SECRET_KEY 문제: {exc}"
        flush_task.cancel()
        try:
            await flush_task
        except asyncio.CancelledError:
            pass
        yield
        return

    skipped: list[str] = []
    for row in camera_rows:
        worker = _build_worker_for_camera(
            row, sb_client, pending_queue, dev_user_id, config
        )
        if worker is None:
            skipped.append(f"{row['id']} ({row.get('display_name', '?')})")
            continue
        worker.start()
        app.state.capture_workers[row["id"]] = worker
        logger.info(
            "capture worker started: camera=%s (%s)",
            row["id"],
            row.get("display_name"),
        )

    app.state.skipped_cameras = skipped
    if skipped:
        app.state.startup_error = f"일부 카메라 skip: {', '.join(skipped)}"

    try:
        yield
    finally:
        for cam_id, worker in app.state.capture_workers.items():
            logger.info("stopping worker: %s", cam_id)
            worker.stop()
        flush_task.cancel()
        try:
            await flush_task
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan)
app.include_router(clips_router)
app.include_router(cameras_router)


@app.get("/")
def root():
    return {"message": "petcam-lab is alive"}


@app.get("/health")
def health():
    """상태 요약 — 워커 몇 대 떴는지 + 어떤 카메라가 skip 됐는지.

    D2 까진 `capture_attached: bool` 이었는데, 다중 워커라 개수/ID 로 확장.
    Flutter 앱이 이걸 보고 "서버 점검 중" 분기할 수 있음 (Stage D5 이후).
    """
    workers: dict[str, CaptureWorker] = getattr(app.state, "capture_workers", {})
    return {
        "status": "ok",
        "capture_workers": len(workers),
        "camera_ids": list(workers.keys()),
        "skipped_cameras": getattr(app.state, "skipped_cameras", []),
        "startup_error": getattr(app.state, "startup_error", None),
    }


@app.get("/streams/{camera_id}/status")
def stream_status(camera_id: str):
    """특정 카메라 워커의 현재 상태 스냅샷.

    - 404: `camera_id` UUID 에 해당하는 활성 워커 없음
    - 200: `CaptureState` dict (frames_read, segments_written, fps 등)
    """
    workers: dict[str, CaptureWorker] = getattr(app.state, "capture_workers", {})
    worker = workers.get(camera_id)
    if worker is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"camera '{camera_id}' not active "
                "(등록 안 됐거나 is_active=false 이거나 비번 복호화 실패)"
            ),
        )
    return asdict(worker.snapshot())

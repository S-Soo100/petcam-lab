"""
캡처 + 인코딩 + R2 업로드 워커 standalone entrypoint.

## 왜 분리했나
`backend.main:app` 한 프로세스가 (a) FastAPI HTTP API (b) RTSP 캡처 스레드 N개
(c) encode_upload asyncio pool 다 함이었던 모놀리식을 cloud-migration-roadmap §4-3
결정에 따라 떼냄. RTSP 가 LAN 의존이라 "API 만 cloud 로" 하려면 capture 가 별도
프로세스여야 함.

## 가동
```bash
uv run python -m backend.capture_main         # 단발
uv run petcam-capture                         # entrypoint 등록 후
```

## API 서버와 무엇을 공유?
- `.env` (같은 Supabase service_role / Fernet 키 / R2 키 / DEV_USER_ID)
- DB 스키마 (cameras / camera_clips / pets / clip_mirrors)
- contract = `clip_recorder` payload 시그니처. 자체 HW 등장 시 capture/encode 부분만
  교체되고 `clip_recorder` 와 `r2_uploader` 는 그대로 살아남음.

## 왜 asyncio.run + signal handler 인가?
FastAPI 의 lifespan 은 uvicorn 이 yield 로 제어해주지만, standalone 워커는 직접
SIGTERM/SIGINT 받아 graceful shutdown 해야 함. Node 비유:
`process.on('SIGTERM', () => server.close())` + `await drainQueue()`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from backend.capture import CaptureWorker
from backend.clip_recorder import make_clip_recorder, make_flush_insert_fn
from backend.crypto import CryptoNotConfigured, decrypt_password
from backend.encode_upload_worker import EncodeUploadWorker
from backend.motion import MotionDetector
from backend.pending_inserts import PendingInsertQueue
from backend.rtsp_probe import build_rtsp_url
from backend.supabase_client import SupabaseNotConfigured, get_supabase_client

REPO_ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)

# 주기 flush 간격 (초). 스펙: 30 초 — 자주 시도해도 Supabase 정상이면 빈 파일 read 1 번.
PENDING_FLUSH_INTERVAL_SEC = 30.0


def _load_capture_config() -> dict[str, Any]:
    """캡처 공용 설정 (카메라 독립) 를 env 에서 한 번 읽어 dict 로.

    MOTION_* / SEGMENT_SECONDS / CLIPS_DIR 는 워커 공용 (카메라 별 override 는 아직 없음).
    RTSP_URL / CAMERA_ID 는 D3 부터 폐기 — cameras 테이블이 원천.
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
    encode_upload_worker: EncodeUploadWorker,
) -> Optional[CaptureWorker]:
    """카메라 행 1개 → CaptureWorker 1개. 비번 복호화 실패 시 None (호출부가 skip).

    clip_recorder 를 워커마다 새로 만드는 이유: 각 카메라의 `pet_id` 가 다를 수 있음.
    encode_upload_worker enqueue callback 으로 한번 감싸서 캡처 thread 가 큐에 put 만
    하고 즉시 다음 프레임으로 — 인코딩+R2 업로드는 worker pool 처리.
    """
    camera_id = camera_row["id"]
    try:
        password = decrypt_password(camera_row["password_encrypted"])
    except Exception as exc:
        # InvalidToken (키 회전 / 변조) · ValueError (빈 ciphertext) 포함.
        # 해당 카메라만 skip, 나머지는 계속.
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
    recorder = make_clip_recorder(
        sb_client, pending_queue, dev_user_id, camera_row.get("pet_id")
    )
    enqueue_callback = encode_upload_worker.make_enqueue_callback(recorder)

    return CaptureWorker(
        camera_id=camera_id,
        rtsp_url=rtsp_url,
        storage_dir=config["clips_dir"],
        segment_seconds=config["segment_seconds"],
        motion_detector=motion_detector,
        motion_min_duration_frames=config["motion_min_frames"],
        motion_segment_threshold_sec=config["motion_seg_threshold_sec"],
        clip_recorder=enqueue_callback,
    )


@dataclass
class CaptureRuntime:
    """부팅된 워커들의 핸들. bootstrap → 이 객체 반환 → 테스트 / shutdown 이 사용."""

    capture_workers: dict[str, CaptureWorker] = field(default_factory=dict)
    encode_upload_worker: Optional[EncodeUploadWorker] = None
    pending_queue: Optional[PendingInsertQueue] = None
    flush_task: Optional[asyncio.Task] = None
    startup_error: Optional[str] = None
    skipped_cameras: list[str] = field(default_factory=list)


async def bootstrap() -> CaptureRuntime:
    """모든 부팅 단계 실행 후 핸들 반환. 부분 실패는 startup_error 로 표면화.

    실패 분기 (Supabase / DEV_USER_ID / cameras / Fernet) 는 runtime.startup_error
    에 사유 기록 후 비어있는 (또는 부분만 채워진) runtime 반환. 호출자가 결정:
    `amain()` 은 startup_error 가 있어도 워커 0개여도 stop_event 까지 대기 (재시작
    루프 방지) — systemd / launchd 가 외부 신호 줘야 종료.
    """
    load_dotenv(REPO_ROOT / ".env")
    # 운영 디버깅용 — capture 워커도 같은 .env 를 읽으니 AUTH_MODE 노출 (실제로는
    # 캡처는 JWT 검증 안 하지만 환경 일관성 확인용).
    logger.warning("AUTH_MODE=%s", os.getenv("AUTH_MODE", "dev"))

    runtime = CaptureRuntime()

    try:
        sb_client = get_supabase_client()
    except SupabaseNotConfigured as exc:
        runtime.startup_error = f"Supabase 미설정: {exc}"
        return runtime

    dev_user_id = os.getenv("DEV_USER_ID")
    if not dev_user_id:
        runtime.startup_error = "DEV_USER_ID 미설정"
        return runtime

    try:
        resp = (
            sb_client.table("cameras")
            .select("*")
            .eq("user_id", dev_user_id)
            .eq("is_active", True)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 — supabase-py 다양한 예외
        runtime.startup_error = f"cameras 조회 실패: {exc}"
        return runtime

    camera_rows = resp.data or []
    if not camera_rows:
        runtime.startup_error = "등록된 카메라 없음. POST /cameras 로 등록 필요"
        return runtime

    pending_queue = PendingInsertQueue(
        REPO_ROOT / "storage" / "pending_inserts.jsonl"
    )
    runtime.pending_queue = pending_queue
    flush_insert = make_flush_insert_fn(sb_client)

    # startup 1 회 flush — 이전 실행에서 밀린 pending 처리.
    try:
        sent, remaining = pending_queue.flush(flush_insert)
        if sent or remaining:
            logger.info("startup flush: %d sent, %d remaining", sent, remaining)
    except Exception as exc:  # noqa: BLE001
        logger.warning("startup flush error: %s", exc)

    async def _periodic_flush() -> None:
        while True:
            await asyncio.sleep(PENDING_FLUSH_INTERVAL_SEC)
            try:
                s, r = await asyncio.to_thread(pending_queue.flush, flush_insert)
                if s > 0:
                    logger.info("periodic flush: %d sent, %d remaining", s, r)
            except Exception as exc:  # noqa: BLE001
                logger.warning("periodic flush error: %s", exc)

    runtime.flush_task = asyncio.create_task(_periodic_flush())

    config = _load_capture_config()
    try:
        # Fernet 싱글톤 선검증 — 전 카메라 공통이므로 한 번만.
        from backend.crypto import get_camera_fernet

        get_camera_fernet()
    except CryptoNotConfigured as exc:
        runtime.startup_error = f"CAMERA_SECRET_KEY 문제: {exc}"
        runtime.flush_task.cancel()
        try:
            await runtime.flush_task
        except asyncio.CancelledError:
            pass
        runtime.flush_task = None
        return runtime

    # encode_upload worker 를 CaptureWorker 보다 먼저 start — enqueue 가 RuntimeError
    # 안 나려면 큐가 떠 있어야 함.
    encoded_dir = REPO_ROOT / os.getenv("ENCODED_DIR", "storage/encoded")
    encoded_dir.mkdir(parents=True, exist_ok=True)
    encode_upload_worker = EncodeUploadWorker(
        encoded_dir=encoded_dir,
        # 카메라 수와 동일 — 카메라당 1 worker 가용.
        concurrency=max(1, len(camera_rows)),
    )
    encode_upload_worker.start()
    runtime.encode_upload_worker = encode_upload_worker

    skipped: list[str] = []
    for row in camera_rows:
        worker = _build_worker_for_camera(
            row,
            sb_client,
            pending_queue,
            dev_user_id,
            config,
            encode_upload_worker,
        )
        if worker is None:
            skipped.append(f"{row['id']} ({row.get('display_name', '?')})")
            continue
        worker.start()
        runtime.capture_workers[row["id"]] = worker
        logger.info(
            "capture worker started: camera=%s (%s)",
            row["id"],
            row.get("display_name"),
        )

    runtime.skipped_cameras = skipped
    if skipped:
        runtime.startup_error = f"일부 카메라 skip: {', '.join(skipped)}"
    return runtime


async def shutdown(runtime: CaptureRuntime) -> None:
    """캡처 thread 먼저 멈춰서 새 enqueue 차단 → encode_upload drain → flush task 취소."""
    for cam_id, worker in runtime.capture_workers.items():
        logger.info("stopping worker: %s", cam_id)
        worker.stop()
    if runtime.encode_upload_worker is not None:
        await runtime.encode_upload_worker.stop()
    if runtime.flush_task is not None:
        runtime.flush_task.cancel()
        try:
            await runtime.flush_task
        except asyncio.CancelledError:
            pass


async def amain() -> None:
    """async entrypoint — bootstrap → SIGTERM / SIGINT 까지 wait → shutdown.

    워커 0개여도 stop_event 까지 대기. 무한 panic-restart 방지.
    """
    runtime = await bootstrap()
    if runtime.startup_error:
        logger.error("startup error: %s", runtime.startup_error)
    logger.info(
        "capture_main running: %d worker(s), %d skipped — Ctrl+C / SIGTERM 으로 정지",
        len(runtime.capture_workers),
        len(runtime.skipped_cameras),
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        logger.info("shutdown signal received — draining workers")
        await shutdown(runtime)


def run() -> None:
    """uv 스크립트 / `python -m backend.capture_main` 진입점."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(amain())


if __name__ == "__main__":
    run()

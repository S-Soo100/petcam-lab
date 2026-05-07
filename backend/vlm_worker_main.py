"""VLM 워커 standalone entrypoint.

## 왜 분리했나
`backend.main:app` 가 API HTTP 만 담당, capture 는 `backend.capture_main`, VLM 은 여기.
세 프로세스 분리 — `cloud-migration-roadmap.md` §4-3 결정.

VLM 은 (a) RTSP / 카메라 무관 → 클라우드 머신에서 가동 가능 (b) 처리량이 polling +
LIMIT 으로 평탄화 됨 → 별도 머신 자원 산정 쉬움 (c) Gemini API key 만 있으면 됨.

## 가동
```bash
uv run python -m backend.vlm_worker_main
uv run petcam-vlm                                 # entrypoint 등록 후
```

## 환경변수
- `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` — 폴링 + INSERT 용.
- `R2_ENDPOINT` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` — 영상 download.
- `GEMINI_API_KEY` — 모델 호출. AI Studio 발급.
- `VLM_POLL_INTERVAL_SEC` (선택, 기본 30) — 사이클 간격.
- `VLM_POLL_LIMIT` (선택, 기본 10) — 한 사이클 최대 건수.
- `HEALTH_PORT` (선택, 기본 8080) — fly.io health check 가 노릴 listen 포트.

## 엇갈림 차단 (idempotency)
- DB UNIQUE(clip_id, source) 가 최후 보호막 — 같은 clip 두 번 INSERT 안 됨.
- 폴링 SELECT 가 NOT EXISTS 1차 방어.
- 따라서 워커 N 인스턴스 동시 가동 안전 (race 의 패배자는 23505 catch + skip).

## graceful shutdown
SIGTERM / SIGINT → stop_event.set() → 진행 중 사이클 완료 후 종료. capture_main 패턴 동일.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from backend.health import make_health_app, run_health_server
from backend.supabase_client import SupabaseNotConfigured, get_supabase_client
from backend.vlm.gemini_client import GeminiNotConfigured, get_model
from backend.vlm.worker import (
    DEFAULT_POLL_INTERVAL_SEC,
    DEFAULT_POLL_LIMIT,
    VlmWorker,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)


@dataclass
class VlmRuntime:
    """부팅된 워커 핸들. 부분 실패는 startup_error 로."""

    worker: Optional[VlmWorker] = None
    startup_error: Optional[str] = None


async def bootstrap() -> VlmRuntime:
    """env / Supabase / Gemini 검증 후 VlmWorker 인스턴스 반환.

    capture_main.bootstrap 과 같은 패턴 — 실패 시 startup_error 만 채우고 빈 runtime 반환.
    `amain()` 이 stop_event 까지 대기하기 때문에 systemd 가 panic-restart 안 함.
    """
    load_dotenv(REPO_ROOT / ".env")
    logger.warning("AUTH_MODE=%s", os.getenv("AUTH_MODE", "dev"))

    runtime = VlmRuntime()
    try:
        sb_client = get_supabase_client()
    except SupabaseNotConfigured as exc:
        runtime.startup_error = f"Supabase 미설정: {exc}"
        return runtime

    try:
        # GenerativeModel 인스턴스화는 lazy — get_model() 한 번 부르면 env 검증.
        get_model()
    except GeminiNotConfigured as exc:
        runtime.startup_error = f"Gemini 미설정: {exc}"
        return runtime

    poll_interval = float(
        os.getenv("VLM_POLL_INTERVAL_SEC", str(DEFAULT_POLL_INTERVAL_SEC))
    )
    poll_limit = int(os.getenv("VLM_POLL_LIMIT", str(DEFAULT_POLL_LIMIT)))

    runtime.worker = VlmWorker(
        sb=sb_client,
        poll_interval_sec=poll_interval,
        poll_limit=poll_limit,
    )
    return runtime


async def amain() -> None:
    """async entrypoint — bootstrap → SIGTERM/SIGINT 까지 wait → drain.

    capture_main.amain 과 같은 패턴 + fly.io health check 용 /health endpoint.
    asyncio.gather 로 worker + health server 같은 이벤트 루프 동거.
    """
    runtime = await bootstrap()
    if runtime.startup_error:
        logger.error("startup error: %s", runtime.startup_error)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    health_port = int(os.getenv("HEALTH_PORT", "8080"))
    health_app = make_health_app(
        "vlm-worker",
        status_check=lambda: runtime.worker is not None and not stop_event.is_set(),
    )

    if runtime.worker is None:
        # 부팅 실패 — health 503 으로 fly 에 unhealthy 신호 보내며 stop 까지 대기.
        # systemd 패턴 호환 (panic-restart 회피) + fly 환경에선 fly 가 자동 restart.
        logger.warning("worker 미생성 — health 503 + stop_event 대기 (재기동 외부 신호 필요)")
        await run_health_server(health_app, stop_event, port=health_port)
        return

    try:
        await asyncio.gather(
            runtime.worker.run(stop_event),
            run_health_server(health_app, stop_event, port=health_port),
        )
    finally:
        logger.info("vlm_worker_main shutdown 완료")


def run() -> None:
    """uv 스크립트 / `python -m backend.vlm_worker_main` 진입점."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(amain())


if __name__ == "__main__":
    run()

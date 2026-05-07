"""HTTP /health endpoint — fly.io health check 용.

워커 프로세스 (capture / vlm) 안에서 같은 이벤트 루프에 작은 FastAPI 를 띄움.
fly 가 `GET /health` 200 받으면 healthy, 503 받으면 restart 트리거.

## 왜 같은 프로세스 안인가
- sidecar 로 분리하면 supervisor 문제 (워커 죽었는데 sidecar 만 200) 가 생김.
- 같은 이벤트 루프 → 워커 raise → asyncio.gather cancel → 프로세스 exit → fly restart.
- 정확한 신호 = 단순한 구조.

## 왜 uvicorn 직접 import?
- backend.main:app 처럼 별도 ASGI 앱 만드는 거 과함.
- mini FastAPI + uvicorn.Server.serve() 한 줄이면 충분.
- access_log=False — 매 30초 헬스체크가 로그 노이즈 만들지 않게.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def make_health_app(
    label: str,
    status_check: Optional[Callable[[], bool]] = None,
) -> FastAPI:
    """헬스체크 미니 FastAPI.

    Args:
        label: 식별 라벨 (예: "vlm-worker"). 응답에 포함되어 디버깅 용이.
        status_check: 워커가 살아있는지 확인하는 콜백. None 이면 항상 200.
            False 반환시 503 → fly 가 unhealthy 인식 → restart.
    """
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health() -> JSONResponse:
        ok = status_check() if status_check else True
        if not ok:
            return JSONResponse(
                {"ok": False, "service": label},
                status_code=503,
            )
        return JSONResponse({"ok": True, "service": label})

    return app


async def run_health_server(
    app: FastAPI,
    stop_event: asyncio.Event,
    host: str = "0.0.0.0",
    port: int = 8080,
) -> None:
    """워커와 같은 이벤트 루프에서 uvicorn 서버 가동.

    `stop_event` 가 set 되면 graceful shutdown.
    `host=0.0.0.0` 이라 fly 의 health checker (컨테이너 외부) 가 접근 가능.

    TS 비유: Express server 를 setInterval 워커와 같은 process 에서 띄우는 패턴.
    """
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    serve_task = asyncio.create_task(server.serve())
    try:
        await stop_event.wait()
    finally:
        server.should_exit = True
        try:
            await serve_task
        except Exception as exc:
            logger.warning("health server shutdown 중 에러: %s", exc)

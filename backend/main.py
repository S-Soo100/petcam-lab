"""
FastAPI HTTP API 엔트리.

## Stage R2 → Cloud Migration 분리 (2026-05-07)
이전: 한 프로세스가 (a) FastAPI API (b) RTSP 캡처 N 개 (c) encode_upload pool 다 함.
이제: API 만 — 캡처/인코딩/R2 업로드는 `backend.capture_main` standalone 프로세스.

이렇게 분리한 이유: RTSP 가 LAN 의존이라 "API 만 cloud 로" 하려면 capture 가 별도
프로세스여야 함. 자세한 결정 락인은 `specs/cloud-migration-roadmap.md` §4-3.

## 가동
```bash
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

캡처 워커는 별도 프로세스:
```bash
uv run python -m backend.capture_main
```

## 왜 lifespan?
FastAPI 0.93+ 권장 패턴. `@app.on_event("startup")` 은 deprecated. `yield` 이전이
startup, 이후가 shutdown. Node 비유: Express 의 `server.listen()` 앞뒤 + `process.on('SIGTERM')` 통합.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers.cameras import router as cameras_router
from backend.routers.clips import router as clips_router
from backend.routers.labels import router as labels_router
from backend.supabase_client import SupabaseNotConfigured, get_supabase_client

REPO_ROOT = Path(__file__).resolve().parent.parent

# `.env` 를 module import 시점에 로드 — CORSMiddleware 등 startup 이전에 평가되는
# 모듈 레벨 설정이 .env 값을 보려면 lifespan 보다 먼저 와야 함.
# lifespan 에서 한 번 더 호출되지만 idempotent.
load_dotenv(REPO_ROOT / ".env")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """API 서버 lifespan — Supabase 연결 가능 여부만 검증, 캡처는 별도 프로세스.

    Supabase 미설정이어도 /health 는 200 — 배포 디버깅 시 "서버는 떴는데 env 문제"
    분기 가능.
    """
    load_dotenv(REPO_ROOT / ".env")

    # 운영 디버깅용 — 실수로 prod 에서 AUTH_MODE=dev 켜져 JWT 우회되는 사고 즉시 감지.
    # warning 레벨: uvicorn 기본에서 INFO 가 커스텀 로거 억제되는 경우가 있어 항상 노출.
    logger.warning("AUTH_MODE=%s", os.getenv("AUTH_MODE", "dev"))

    app.state.startup_error: Optional[str] = None

    try:
        get_supabase_client()
    except SupabaseNotConfigured as exc:
        app.state.startup_error = f"Supabase 미설정: {exc}"

    yield


app = FastAPI(lifespan=lifespan)

# CORS — 라벨링 웹 (Vercel) + 로컬 dev (3000) 가 백엔드 호출.
# 와일드카드 대신 명시 origin 만 허용 (credentials/JWT 보안).
# `LABELING_WEB_ORIGINS` env 콤마 구분, 미설정 시 로컬 dev 만 허용.
_default_origins = "http://localhost:3000,http://127.0.0.1:3000"
_origins_env = os.getenv("LABELING_WEB_ORIGINS", _default_origins)
_allowed_origins = [o.strip() for o in _origins_env.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
    # /clips/{id}/file 의 Range 헤더 응답 노출 — 브라우저 video 가 Content-Range 읽음.
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)

app.include_router(clips_router)
app.include_router(cameras_router)
app.include_router(labels_router)


@app.get("/")
def root():
    return {"message": "petcam-lab is alive"}


@app.get("/health")
def health():
    """기본 상태 — Supabase 연결 가능 여부만.

    캡처 워커 상태 (`capture_workers` / `encode_upload_queue` 등) 는 별도 프로세스
    (`backend.capture_main`) 영역으로 이전. 워커 모니터링 엔드포인트는 후속 spec.
    """
    return {
        "status": "ok",
        "startup_error": getattr(app.state, "startup_error", None),
    }

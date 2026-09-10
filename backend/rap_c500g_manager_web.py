"""RAP C500G manager의 loopback-only FastAPI UI/API."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.rap_c500g_capture import CameraConfig
from backend.rap_c500g_manager_probe import (
    CameraProbeStatus,
    VolumeStatus,
    list_external_volumes,
    probe_camera,
)
from backend.rap_c500g_manager_store import ManagerStore
from backend.rap_c500g_manager_ui import DASHBOARD_HTML
from backend.rap_c500g_types import CAMERA_KEYS


class ManagerLike(Protocol):
    def is_production_active(self) -> bool: ...
    def run_diagnostic(self, *, duration_sec: float) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ManagerWebContext:
    manager: ManagerLike
    store: ManagerStore
    configs: Sequence[CameraConfig]
    list_volumes: Callable[[], list[VolumeStatus]] = list_external_volumes
    camera_probe: Callable[[CameraConfig], CameraProbeStatus] = probe_camera


class PendingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_local: str = Field(min_length=5, max_length=5)
    end_local: str = Field(min_length=5, max_length=5)
    selected_cameras: list[str] = Field(min_length=1, max_length=3)
    volume_name: str = Field(min_length=1, max_length=80)
    max_capture_retries: int = Field(ge=0, le=5)


_LOOPBACK_CLIENTS = frozenset({"127.0.0.1", "::1", "testclient"})
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "testserver"})


def _require_local_mutation(request: Request) -> None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and forwarded.split(",", 1)[0].strip() not in {"127.0.0.1", "::1"}:
        raise HTTPException(status_code=403, detail="local access only")
    client_host = request.client.host if request.client else ""
    if client_host not in _LOOPBACK_CLIENTS:
        raise HTTPException(status_code=403, detail="local access only")
    host = request.headers.get("host", "").split(":", 1)[0]
    if host not in _LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="invalid host")
    origin = request.headers.get("origin")
    if origin:
        parsed = urlparse(origin)
        if parsed.hostname not in {"127.0.0.1", "::1", "localhost", "testserver"}:
            raise HTTPException(status_code=403, detail="invalid origin")


def _public_probe(status: CameraProbeStatus) -> dict[str, Any]:
    return asdict(status)


def create_manager_app(context: ManagerWebContext) -> FastAPI:
    app = FastAPI(title="RAP C500G Manager", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[..., Any]) -> Any:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return DASHBOARD_HTML

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        snapshot = context.store.read_snapshot()
        if snapshot is None:
            return {
                "schema_version": "rap-c500g-manager-status/v1",
                "manager_state": "starting",
                "updated_at": None,
                "current_slot": None,
                "next_slot": None,
                "volume": {},
                "cameras": {},
                "recent_completed": [],
                "incidents": [],
                "sync": {"pending": 0, "failed": 0},
            }
        return snapshot.to_public_dict()

    @app.get("/api/settings")
    def settings() -> dict[str, Any]:
        pending = context.store.load_pending_plan()
        return {
            "active": context.store.load_plan().to_dict(),
            "pending": pending.to_dict() if pending else None,
            "registered_cameras": sorted(CAMERA_KEYS),
            "segment_minutes": 30,
        }

    @app.put("/api/settings/pending", dependencies=[Depends(_require_local_mutation)])
    def save_pending(payload: PendingSettings) -> dict[str, Any]:
        try:
            plan = context.store.save_pending_plan(**payload.model_dump())
        except ValueError as error:
            raise HTTPException(status_code=422, detail="invalid manager settings") from error
        return {"pending": plan.to_dict(), "applies_at": "next_boundary"}

    @app.get("/api/volumes")
    def volumes() -> list[dict[str, Any]]:
        return [item.to_public_dict() for item in context.list_volumes()]

    @app.post("/api/probes/cameras", dependencies=[Depends(_require_local_mutation)])
    def probes() -> list[dict[str, Any]]:
        return [_public_probe(context.camera_probe(config)) for config in context.configs]

    @app.post("/api/diagnostics/recording", dependencies=[Depends(_require_local_mutation)])
    def diagnostic() -> dict[str, Any]:
        if context.manager.is_production_active():
            raise HTTPException(status_code=409, detail="production capture is active")
        try:
            result = context.manager.run_diagnostic(duration_sec=60.0)
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail="diagnostic unavailable") from error
        cameras = result.get("cameras")
        sync = result.get("sync")
        if (
            isinstance(cameras, dict)
            and any(value == "failed" for value in cameras.values())
        ) or (isinstance(sync, dict) and int(sync.get("failed", 0)) > 0):
            raise HTTPException(status_code=409, detail="diagnostic failed")
        return result

    @app.get("/api/incidents")
    def incidents() -> list[dict[str, Any]]:
        return context.store.read_events(limit=50)

    return app

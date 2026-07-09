"""Standalone entrypoint for the Mac mini router feature worker."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from backend.health import make_health_app, run_health_server
from backend.router_features import (
    DEFAULT_POLL_INTERVAL_SEC,
    DEFAULT_POLL_LIMIT,
    DEFAULT_SAMPLE_FRAMES,
    DEFAULT_STALE_PROCESSING_MINUTES,
    RouterFeatureWorker,
)
from backend.supabase_client import SupabaseNotConfigured, get_supabase_client

REPO_ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)


@dataclass
class RouterFeatureRuntime:
    worker: RouterFeatureWorker | None = None
    startup_error: str | None = None


async def bootstrap() -> RouterFeatureRuntime:
    load_dotenv(REPO_ROOT / ".env")
    runtime = RouterFeatureRuntime()
    try:
        sb_client = get_supabase_client()
    except SupabaseNotConfigured as exc:
        runtime.startup_error = f"Supabase 미설정: {exc}"
        return runtime

    poll_interval = float(
        os.getenv("ROUTER_FEATURE_POLL_INTERVAL_SEC", str(DEFAULT_POLL_INTERVAL_SEC))
    )
    poll_limit = int(os.getenv("ROUTER_FEATURE_POLL_LIMIT", str(DEFAULT_POLL_LIMIT)))
    sample_frames = int(
        os.getenv("ROUTER_FEATURE_SAMPLE_FRAMES", str(DEFAULT_SAMPLE_FRAMES))
    )
    stale_processing_minutes = int(
        os.getenv(
            "ROUTER_FEATURE_STALE_PROCESSING_MINUTES",
            str(DEFAULT_STALE_PROCESSING_MINUTES),
        )
    )

    runtime.worker = RouterFeatureWorker(
        sb=sb_client,
        poll_interval_sec=poll_interval,
        poll_limit=poll_limit,
        sample_frames=sample_frames,
        stale_processing_minutes=stale_processing_minutes,
    )
    return runtime


async def amain() -> None:
    runtime = await bootstrap()
    if runtime.startup_error:
        logger.error("startup error: %s", runtime.startup_error)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    health_port = int(os.getenv("ROUTER_FEATURE_HEALTH_PORT", "8089"))
    health_app = make_health_app(
        "router-feature-worker",
        status_check=lambda: runtime.worker is not None and not stop_event.is_set(),
    )

    if runtime.worker is None:
        await run_health_server(health_app, stop_event, port=health_port)
        return

    await asyncio.gather(
        runtime.worker.run(stop_event),
        run_health_server(health_app, stop_event, port=health_port),
    )


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(amain())


if __name__ == "__main__":
    run()

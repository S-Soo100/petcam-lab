"""`rap-manager`: Mac mini 로컬 녹화 매니저 CLI."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv

from backend.rap_c500g_capture import load_camera_configs
from backend.rap_c500g_manager_runtime import RapC500GManager
from backend.rap_c500g_manager_notify import SlackWebhookNotifier
from backend.rap_c500g_manager_store import ManagerSnapshot, ManagerStore
from backend.rap_c500g_manager_web import ManagerWebContext, create_manager_app
from backend.rap_c500g_r2 import (
    R2BundleUploader,
    create_c500g_r2_client,
    load_c500g_r2_config,
)
from backend.rap_c500g_repository import RapRecordingRepository
from backend.rap_c500g_production_lock import production_lock
from backend.supabase_client import get_supabase_client


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANAGER_PORT = 8766
DEFAULT_STATE_PATH = (
    Path.home()
    / "Library"
    / "Application Support"
    / "rap-c500g-manager"
    / "manager.sqlite3"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rap-manager")
    parser.add_argument(
        "--state-path",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help="manager SQLite path",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve", help="loopback dashboard와 recorder manager 실행")
    status = subparsers.add_parser("status", help="저장된 상태를 읽기 전용으로 출력")
    status.add_argument("--json", action="store_true", dest="as_json")
    diagnostic = subparsers.add_parser("diagnostic", help="현장 60초 진단 녹화")
    diagnostic.add_argument("--duration", type=float, default=60.0)
    return parser


def read_status(path: Path) -> tuple[int, dict[str, Any]]:
    if not path.is_file():
        return 2, {
            "schema_version": "rap-c500g-manager-status/v1",
            "manager_state": "unavailable",
            "owner_action": "manager state database is missing",
        }
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as connection:
            row = connection.execute(
                "SELECT payload FROM manager_snapshot WHERE id = 1"
            ).fetchone()
        snapshot = (
            ManagerSnapshot.from_dict(json.loads(row[0])) if row is not None else None
        )
    except Exception:
        return 2, {
            "schema_version": "rap-c500g-manager-status/v1",
            "manager_state": "unavailable",
            "owner_action": "manager state database cannot be read",
        }
    if snapshot is None:
        return 2, {
            "schema_version": "rap-c500g-manager-status/v1",
            "manager_state": "unavailable",
            "owner_action": "manager has not written a snapshot",
        }
    payload = snapshot.to_public_dict()
    updated = datetime.fromisoformat(snapshot.updated_at)
    age_sec = (datetime.now(updated.tzinfo) - updated).total_seconds()
    if age_sec > 15 and snapshot.manager_state in {
        "idle",
        "recording",
        "finalizing",
        "scheduled",
    }:
        payload["manager_state"] = "unavailable"
        payload["owner_action"] = "manager snapshot is stale"
        return 2, payload
    open_incident = any(item.get("state") == "open" for item in snapshot.incidents)
    owner_action = snapshot.manager_state.startswith("blocked") or open_incident
    if owner_action:
        payload["owner_action"] = True
    return (3 if owner_action else 0), payload


def active_ffmpeg_count() -> int:
    result = subprocess.run(
        ["pgrep", "-x", "ffmpeg"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode == 1:
        return 0
    if result.returncode != 0:
        raise RuntimeError("cannot verify active ffmpeg processes")
    return len([line for line in result.stdout.splitlines() if line.strip()])


def legacy_recorder_loaded() -> bool:
    result = subprocess.run(
        [
            "launchctl",
            "print",
            f"gui/{os.getuid()}/com.teraai.rap-c500g-recorder",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    return result.returncode == 0


def _runtime(state_path: Path) -> tuple[RapC500GManager, ManagerStore, tuple]:
    if legacy_recorder_loaded():
        raise RuntimeError("legacy recorder service must be unloaded first")
    if active_ffmpeg_count() != 0:
        raise RuntimeError("active ffmpeg process prevents manager startup")
    load_dotenv(REPO_ROOT / ".env")
    configs = load_camera_configs(os.environ)
    r2_config = load_c500g_r2_config(os.environ)
    uploader = R2BundleUploader(
        create_c500g_r2_client(r2_config),
        r2_config.bucket,
    )
    repository = RapRecordingRepository(get_supabase_client())
    store = ManagerStore(state_path)
    store.release_unfinished_claims()
    manager = RapC500GManager(
        configs=configs,
        store=store,
        uploader=uploader,
        repository=repository,
        notifier=SlackWebhookNotifier(os.getenv("SLACK_WEBHOOK_URL")),
        fatal_callback=lambda: os.kill(os.getpid(), signal.SIGTERM),
    )
    return manager, store, configs


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "status":
        code, payload = read_status(args.state_path)
        if args.as_json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            print(f"manager={payload['manager_state']} updated={payload.get('updated_at', '—')}")
        return code

    if args.command == "diagnostic" and args.duration != 60.0:
        raise SystemExit("diagnostic duration must be exactly 60 seconds")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    with production_lock():
        manager, store, configs = _runtime(args.state_path)

        if args.command == "diagnostic":
            result = manager.run_diagnostic(duration_sec=60.0)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            failed = any(value == "failed" for value in result["cameras"].values())
            return 1 if failed or result["sync"]["failed"] else 0

        app = create_manager_app(
            ManagerWebContext(manager=manager, store=store, configs=configs)
        )
        manager.start()
        try:
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=DEFAULT_MANAGER_PORT,
                access_log=False,
                log_level="info",
            )
        finally:
            manager.stop()
    return 0


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run()

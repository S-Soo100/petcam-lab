"""`rap-c500g` CLI: test, production daemon, durable R2/DB sync."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from backend.rap_c500g_capture import load_camera_configs
from backend.rap_c500g_r2 import (
    R2BundleUploader,
    create_c500g_r2_client,
    load_c500g_r2_config,
)
from backend.rap_c500g_repository import RapRecordingRepository
from backend.rap_c500g_service import (
    make_test_run_id,
    run_production_loop,
    run_test_capture,
    sync_bundles,
)
from backend.supabase_client import get_supabase_client


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCAL_ROOT = Path("/Users/baek-end/RAP-c500g-recordings")
KST = ZoneInfo("Asia/Seoul")
logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rap-c500g",
        description="RAP C500G 원본 녹화와 이중 보관",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    test_parser = subparsers.add_parser("test", help="세 카메라 동시 테스트 녹화 후 동기화")
    test_parser.add_argument("--duration", type=float, default=60.0, help="녹화 초 (기본 60)")
    subparsers.add_parser("run", help="20:00~08:00 production scheduler 실행")
    subparsers.add_parser("sync", help="로컬 완료 bundle을 R2/DB와 재동기화")
    return parser


def _validate_required_mount(root: Path, required_mount_value: str | None) -> None:
    if not required_mount_value:
        return
    required_mount = Path(required_mount_value).expanduser().resolve()
    resolved_root = root.resolve()
    try:
        resolved_root.relative_to(required_mount)
    except ValueError as error:
        raise RuntimeError("local root must be inside required local mount") from error
    # USB가 빠진 채 /Volumes 아래 폴더를 만들면 내부 SSD에 기록될 수 있어 실제 mount만 허용해.
    if not required_mount.is_mount():
        raise RuntimeError("required local mount is unavailable")


def _runtime() -> tuple[Path, tuple, R2BundleUploader, RapRecordingRepository]:
    load_dotenv(REPO_ROOT / ".env")
    root = Path(os.getenv("RAP_C500G_LOCAL_ROOT", str(DEFAULT_LOCAL_ROOT))).expanduser()
    _validate_required_mount(root, os.getenv("RAP_C500G_REQUIRED_MOUNT"))
    configs = load_camera_configs(os.environ)
    r2_config = load_c500g_r2_config(os.environ)
    uploader = R2BundleUploader(
        create_c500g_r2_client(r2_config),
        r2_config.bucket,
    )
    repository = RapRecordingRepository(get_supabase_client())
    return root, configs, uploader, repository


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    root, configs, uploader, repository = _runtime()

    if args.command == "sync":
        summary = sync_bundles(root, uploader, repository)
        logger.info(
            "sync complete scanned=%d uploaded=%d failed=%d",
            summary.scanned,
            summary.uploaded,
            summary.failed,
        )
        return 1 if summary.failed else 0

    if args.command == "test":
        if args.duration <= 0:
            raise SystemExit("duration must be positive")
        now = datetime.now(KST)
        run_id = make_test_run_id(now)
        results = run_test_capture(
            configs,
            root,
            duration_sec=args.duration,
            now=now,
            test_run_id=run_id,
        )
        capture_failures = sum(isinstance(value, Exception) for value in results.values())
        logger.info(
            "test capture complete run_id=%s cameras=%d failed=%d",
            run_id,
            len(results),
            capture_failures,
        )
        summary = sync_bundles(root, uploader, repository)
        logger.info(
            "test sync complete scanned=%d uploaded=%d failed=%d",
            summary.scanned,
            summary.uploaded,
            summary.failed,
        )
        return 1 if capture_failures or summary.failed else 0

    stop = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    run_production_loop(
        configs,
        root,
        uploader,
        repository,
        clock=lambda: datetime.now(KST),
        stop_wait=stop.wait,
    )
    return 0


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run()

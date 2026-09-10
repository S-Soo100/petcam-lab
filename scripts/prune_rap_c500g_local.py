"""검증된 RAP C500G local bundle의 aggregate dry-run/명시 실행 CLI."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from backend.rap_c500g_local_prune import (
    PRODUCTION_ROOT,
    build_prune_plan,
    capture_prune_root_guard,
    execute_prune,
)
from backend.rap_c500g_manager_store import ManagerStore
from backend.rap_c500g_r2 import create_c500g_r2_client, load_c500g_r2_config
from backend.supabase_client import get_supabase_client


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE = Path.home() / "Library/Application Support/rap-c500g-manager/manager.sqlite3"
DEFAULT_RECEIPTS = Path.home() / "Library/Application Support/rap-c500g-manager/prune-audit"


class SystemMountInspector:
    def is_mount(self, path: Path) -> bool:
        return path.is_mount()

    def volume_uuid(self, path: Path) -> str:
        completed = subprocess.run(
            ["/usr/sbin/diskutil", "info", "-plist", str(path)],
            capture_output=True, check=False, timeout=10,
        )
        if completed.returncode != 0:
            return ""
        payload = plistlib.loads(completed.stdout)
        return str(payload.get("VolumeUUID") or payload.get("DiskUUID") or "")


class R2Heads:
    def __init__(self, client: Any, bucket: str) -> None:
        self.client, self.bucket = client, bucket

    def head_object(self, key: str) -> dict[str, object] | None:
        try:
            result = self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception:
            return None
        return {
            "ContentLength": result.get("ContentLength"),
            "Metadata": dict(result.get("Metadata") or {}),
            "LastModified": result.get("LastModified"),
        }


class RecordingRows:
    def __init__(self, client: Any) -> None:
        self.client = client

    def get_recording(self, bundle_id: str) -> dict[str, object] | None:
        response = (
            self.client.table("rap_c500g_recordings")
            .select("capture_status,upload_status,manifest_r2_key,uploaded_at")
            .eq("bundle_id", bundle_id)
            .limit(1)
            .execute()
        )
        rows = list(response.data or [])
        return dict(rows[0]) if len(rows) == 1 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=PRODUCTION_ROOT)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--receipt-dir", type=Path, default=DEFAULT_RECEIPTS)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--plan-digest")
    args = parser.parse_args(argv)
    if args.execute != bool(args.plan_digest):
        parser.error("--execute and --plan-digest must be supplied together")
    load_dotenv(REPO_ROOT / ".env")
    config = load_c500g_r2_config(os.environ)
    heads = R2Heads(create_c500g_r2_client(config), config.bucket)
    rows = RecordingRows(get_supabase_client())
    store = ManagerStore(args.state_path)
    inspector = SystemMountInspector()

    def build():
        guard = capture_prune_root_guard(args.root, inspector=inspector)
        return build_prune_plan(
            args.root, uploader=heads, repository=rows, store=store,
            now=datetime.now().astimezone(), guard=guard,
        )

    plan = build()
    if not args.execute:
        print(json.dumps(plan.to_public_dict(), sort_keys=True))
        return 0
    receipt = execute_prune(
        plan, supplied_digest=args.plan_digest, receipt_dir=args.receipt_dir,
        rebuild_plan=build,
    )
    print(json.dumps({
        "deleted_count": receipt.deleted_count,
        "deleted_bytes": receipt.deleted_bytes,
        "plan_digest": receipt.plan_digest,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

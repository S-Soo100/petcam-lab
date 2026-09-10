"""v2.7 C500G 준비 CLI (Task 10 부분) — `inventory` 와 `freeze-roles`.

실행 예 (레포 루트, uv 환경):
  uv run python -m scripts.yolo26n_v27_c500g.cli inventory \
      --attempt storage/yolo26n-v27-c500g/attempts/2026-09-10-a1 \
      --local-root storage/rap-c500g-mirror \
      --night-start 2026-08-27 --night-end 2026-09-09 \
      --test-sheet-sha256 <TEST-SHEET sha256>
  uv run python -m scripts.yolo26n_v27_c500g.cli freeze-roles \
      --attempt storage/yolo26n-v27-c500g/attempts/2026-09-10-a1 \
      --freeze-manifest /path/detector-freeze.private.json \
      --freeze-cutoff-utc 2026-08-31T13:51:52Z --seed v27-role-freeze-v1 \
      --test-sheet-sha256 <TEST-SHEET sha256>

콘솔에는 aggregate 요약만 찍는다. 원천·R2·DB 는 read-only, 파생물은 attempt 아래 0700/0600 새 파일로만.
카메라 키(cam01…)는 private artifact 에만 들어가며 콘솔·요약엔 digest 만 남는다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Sequence

from scripts.yolo26n_v27_c500g.inventory import build_expected_slots, collect_inventory, inventory_public_summary
from scripts.yolo26n_v27_c500g.private_io import sha256_file, write_private_json_new
from scripts.yolo26n_v27_c500g.roles import freeze_roles

DEFAULT_CAMERA_KEYS = ("cam01", "cam02", "cam03")


def run_inventory(*, local_root: Path, r2_reader, db_reader, attempt: Path, camera_keys: Sequence[str],
                  nights: Sequence[str], test_sheet_sha256: str) -> dict[str, object]:
    ledger = build_expected_slots(camera_keys, nights, test_sheet_sha256=test_sheet_sha256)
    inventory_dir = Path(attempt) / "inventory"
    write_private_json_new(inventory_dir / "expected-slots.private.json", ledger)
    inventory = collect_inventory(Path(local_root), r2_reader, db_reader, test_sheet_sha256=test_sheet_sha256, expected_slots=ledger)
    private_path = inventory_dir / "source-inventory.private.json"
    write_private_json_new(private_path, inventory)
    summary = inventory_public_summary(inventory)
    return {"inventory": inventory, "summary": summary, "private_path": private_path}


def run_freeze_roles(*, attempt: Path, freeze_manifest: Path, freeze_cutoff_utc: str | None, seed: str,
                     test_sheet_sha256: str) -> dict[str, object]:
    inventory = json.loads((Path(attempt) / "inventory" / "source-inventory.private.json").read_text(encoding="utf-8"))
    if inventory.get("test_sheet_sha256") != test_sheet_sha256:
        raise ValueError("inventory TEST-SHEET pin differs from the requested TEST-SHEET sha256")
    freeze_path = Path(freeze_manifest)
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    mtime = datetime.fromtimestamp(freeze_path.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z")
    result = freeze_roles(
        inventory, freeze, seed=seed, freeze_cutoff_utc=freeze_cutoff_utc,
        freeze_manifest_sha256=sha256_file(freeze_path), freeze_manifest_mtime_utc=mtime,
    )
    private_path = Path(attempt) / "roles" / "role-freeze.private.json"
    write_private_json_new(private_path, result)
    summary = {k: result[k] for k in ("schema", "status", "test_sheet_sha256", "seed", "freeze_cutoff_utc",
                                      "freeze_cutoff_source", "camera_night_counts", "date_blocks")}
    return {"status": result["status"], "summary": summary, "private_path": private_path}


def _nights_between(start: str, end: str) -> list[str]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if last < first:
        raise ValueError("--night-end must not precede --night-start")
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def _real_readers(bucket: str):
    """실제 R2(boto3)·DB(supabase) read-only 어댑터. 자격증명은 .env 에서만 읽고 출력하지 않는다."""
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    import boto3
    from supabase import create_client

    from scripts.yolo26n_v27_c500g.readers import ProductionDbReader, ReadOnlyR2

    client = boto3.client(
        "s3", endpoint_url=os.environ["R2_ENDPOINT"], aws_access_key_id=os.environ["R2_C500G_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_C500G_SECRET_ACCESS_KEY"], region_name="auto",
    )
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    return ReadOnlyR2(client, bucket=bucket), ProductionDbReader(sb.table("rap_c500g_recordings"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="yolo26n_v27_c500g", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    inv = sub.add_parser("inventory", help="read-only 3계층 inventory → attempt/inventory/*.private.json")
    inv.add_argument("--attempt", required=True)
    inv.add_argument("--local-root", required=True, help="미러 루트 (그 아래 recordings/…)")
    inv.add_argument("--night-start", required=True)
    inv.add_argument("--night-end", required=True)
    inv.add_argument("--test-sheet-sha256", required=True)
    inv.add_argument("--camera-keys", default=os.environ.get("RAP_C500G_CAMERA_KEYS", ",".join(DEFAULT_CAMERA_KEYS)))
    inv.add_argument("--bucket", default=os.environ.get("R2_C500G_BUCKET", "c500g"))

    fr = sub.add_parser("freeze-roles", help="metadata-only 역할 동결 → attempt/roles/role-freeze.private.json")
    fr.add_argument("--attempt", required=True)
    fr.add_argument("--freeze-manifest", required=True)
    fr.add_argument("--freeze-cutoff-utc", default=None)
    fr.add_argument("--seed", required=True)
    fr.add_argument("--test-sheet-sha256", required=True)

    args = parser.parse_args(argv)
    if args.command == "inventory":
        r2_reader, db_reader = _real_readers(args.bucket)
        out = run_inventory(
            local_root=Path(args.local_root), r2_reader=r2_reader, db_reader=db_reader, attempt=Path(args.attempt),
            camera_keys=[k.strip() for k in args.camera_keys.split(",") if k.strip()],
            nights=_nights_between(args.night_start, args.night_end), test_sheet_sha256=args.test_sheet_sha256,
        )
        print(json.dumps({"status": out["inventory"]["status"], **out["summary"]}, ensure_ascii=False, sort_keys=True))
        return 0 if out["inventory"]["status"] == "V27_SOURCE_INVENTORY_READY" else 1
    if args.command == "freeze-roles":
        out = run_freeze_roles(
            attempt=Path(args.attempt), freeze_manifest=Path(args.freeze_manifest), freeze_cutoff_utc=args.freeze_cutoff_utc,
            seed=args.seed, test_sheet_sha256=args.test_sheet_sha256,
        )
        print(json.dumps(out["summary"], ensure_ascii=False, sort_keys=True))
        return 0 if out["status"] == "V27_ROLE_FREEZE_READY" else 1
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())

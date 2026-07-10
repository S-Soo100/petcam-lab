#!/usr/bin/env python3
"""Seed a fixed router-review batch from manual_review_queue.csv."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.supabase_client import get_supabase_client  # noqa: E402

DEFAULT_BATCH_ID = "router-eval-v1-20260710"
DEFAULT_CSV = (
    REPO_ROOT
    / "reports"
    / "router-eval-v1-20260710"
    / "manual_review_queue.csv"
)


def build_review_item_payload(row: dict[str, str], batch_id: str) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "clip_id": _required(row, "clip_id"),
        "sample_group": _required(row, "sample_group"),
        "route": _required(row, "route"),
        "risk": _required(row, "risk"),
        "reason": _required(row, "reason"),
        "priority": _float_or_none(row.get("priority")) or 0.0,
        "camera_id": _str_or_none(row.get("camera_id")),
        "started_at": _str_or_none(row.get("started_at")),
        "evidence_reliability": _str_or_none(row.get("evidence_reliability")),
        "motion_mean": _float_or_none(row.get("motion_mean")),
        "motion_peak": _float_or_none(row.get("motion_peak")),
        "active_motion_ratio": _float_or_none(row.get("active_motion_ratio")),
        "motion_burst_count": _int_or_none(row.get("motion_burst_count")),
    }


def read_review_queue_csv(path: Path, batch_id: str) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [build_review_item_payload(row, batch_id=batch_id) for row in rows]


def seed_review_batch(path: Path, batch_id: str, *, dry_run: bool) -> int:
    payloads = read_review_queue_csv(path, batch_id=batch_id)
    if dry_run:
        print(f"dry-run: would upsert {len(payloads)} router_review_items")
        return len(payloads)

    sb = get_supabase_client()
    for chunk in _chunks(payloads, 100):
        (
            sb.table("router_review_items")
            .upsert(chunk, on_conflict="batch_id,clip_id")
            .execute()
        )
    print(f"seeded {len(payloads)} router_review_items batch={batch_id}")
    return len(payloads)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    seed_review_batch(args.csv, args.batch_id, dry_run=args.dry_run)
    return 0


def _required(row: dict[str, str], key: str) -> str:
    value = _str_or_none(row.get(key))
    if value is None:
        raise ValueError(f"{key} is required")
    return value


def _str_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _float_or_none(value: str | None) -> float | None:
    text = _str_or_none(value)
    if text is None:
        return None
    return float(text)


def _int_or_none(value: str | None) -> int | None:
    text = _str_or_none(value)
    if text is None:
        return None
    return int(float(text))


def _chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""R2 mp4 inventory dry-run.

R2 object 목록과 Supabase camera_clips.r2_key를 대조해, DB에 없는 R2 mp4를
분류 리포트로 남긴다. 이 스크립트는 DB/R2에 쓰지 않는다.

사용:
    uv run python scripts/r2_orphan_inventory.py
    uv run python scripts/r2_orphan_inventory.py --limit 100
    uv run python scripts/r2_orphan_inventory.py --out-dir reports/r2-inventory-20260710
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.r2_uploader import get_r2_bucket, get_r2_client  # noqa: E402
from backend.supabase_client import get_supabase_client  # noqa: E402

REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_PREFIX = "clips/"
PAGE_SIZE = 1000

R2_CLIP_RE = re.compile(
    r"^clips/"
    r"(?P<camera_id>[^/]+)/"
    r"(?P<date>\d{4}-\d{2}-\d{2})/"
    r"(?P<stem>.+)_"
    r"(?P<clip_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r"\.mp4$"
)
LEGACY_DATED_CLIP_RE = re.compile(
    r"^clips/"
    r"(?P<year>\d{4})/"
    r"(?P<month>\d{2})/"
    r"(?P<day>\d{2})/"
    r"(?P<camera_slug>[^/]+)/"
    r"(?P<clip_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r"\.mp4$"
)


@dataclass(frozen=True, slots=True)
class R2ObjectInfo:
    key: str
    size: int
    last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedR2ClipKey:
    key: str
    camera_id: str | None
    date: str | None
    clip_id: str | None
    inferred_has_motion: bool | None
    key_pattern: str
    classification: str
    import_confidence: str
    reason: str


def parse_r2_clip_key(key: str, *, known_r2_keys: set[str]) -> ParsedR2ClipKey:
    if key in known_r2_keys:
        base = _parse_key_shape(key)
        return ParsedR2ClipKey(
            key=key,
            camera_id=base.get("camera_id"),
            date=base.get("date"),
            clip_id=base.get("clip_id"),
            inferred_has_motion=_infer_has_motion(key),
            key_pattern=base["key_pattern"],
            classification="known_camera_clip",
            import_confidence="none",
            reason="r2_key already exists in camera_clips",
        )

    base = _parse_key_shape(key)
    if base["key_pattern"] == "canonical_clip":
        return ParsedR2ClipKey(
            key=key,
            camera_id=base["camera_id"],
            date=base["date"],
            clip_id=base["clip_id"],
            inferred_has_motion=_infer_has_motion(key),
            key_pattern=base["key_pattern"],
            classification="likely_missing_camera_clip",
            import_confidence="medium",
            reason="canonical clips/{camera}/{date}/{stem}_{uuid}.mp4 key missing from DB",
        )

    if base["key_pattern"] == "legacy_dated_clip":
        return ParsedR2ClipKey(
            key=key,
            camera_id=base["camera_id"],
            date=base["date"],
            clip_id=base["clip_id"],
            inferred_has_motion=_infer_has_motion(key),
            key_pattern=base["key_pattern"],
            classification="manual_review_clip",
            import_confidence="low",
            reason=(
                "legacy clips/{yyyy}/{mm}/{dd}/{camera_slug}/{uuid}.mp4 key "
                "has no canonical camera_id/stem"
            ),
        )

    if _looks_experiment_artifact(key):
        classification = "experiment_artifact"
        confidence = "none"
        reason = "key prefix/name looks like experiment or verification artifact"
    else:
        classification = "unknown_pattern"
        confidence = "none"
        reason = "key does not match canonical camera clip pattern"

    return ParsedR2ClipKey(
        key=key,
        camera_id=base.get("camera_id"),
        date=base.get("date"),
        clip_id=base.get("clip_id"),
        inferred_has_motion=_infer_has_motion(key),
        key_pattern=base["key_pattern"],
        classification=classification,
        import_confidence=confidence,
        reason=reason,
    )


def build_inventory(
    objects: Iterable[R2ObjectInfo],
    *,
    known_r2_keys: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    classes: Counter[str] = Counter()
    dates: Counter[str] = Counter()
    cameras: Counter[str] = Counter()
    total_size = 0

    for obj in objects:
        parsed = parse_r2_clip_key(obj.key, known_r2_keys=known_r2_keys)
        row = {
            **asdict(parsed),
            "size": obj.size,
            "last_modified": obj.last_modified,
        }
        rows.append(row)
        classes[parsed.classification] += 1
        if parsed.date:
            dates[parsed.date] += 1
        if parsed.camera_id:
            cameras[parsed.camera_id] += 1
        total_size += obj.size

    summary = {
        "generated_at": _utc_now_iso(),
        "total_r2_mp4": len(rows),
        "total_size_bytes": total_size,
        "classification_counts": dict(classes),
        "top_dates": dates.most_common(20),
        "top_camera_ids": cameras.most_common(20),
        "db_writes": 0,
        "r2_writes": 0,
    }
    return rows, summary


def write_reports(rows: list[dict[str, Any]], summary: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_jsonl(out_dir / "inventory.jsonl", rows)
    orphan_rows = [
        row for row in rows if row["classification"] != "known_camera_clip"
    ]
    _write_jsonl(out_dir / "orphans.jsonl", orphan_rows)
    (out_dir / "REPORT.md").write_text(
        _format_markdown_report(summary, out_dir),
        encoding="utf-8",
    )


def list_r2_mp4_objects(prefix: str, limit: int | None = None) -> list[R2ObjectInfo]:
    client = get_r2_client()
    bucket = get_r2_bucket()
    paginator = client.get_paginator("list_objects_v2")
    objects: list[R2ObjectInfo] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            if not key.lower().endswith(".mp4"):
                continue
            last_modified = item.get("LastModified")
            objects.append(
                R2ObjectInfo(
                    key=key,
                    size=int(item.get("Size") or 0),
                    last_modified=(
                        last_modified.astimezone(timezone.utc).isoformat()
                        if last_modified is not None
                        else None
                    ),
                )
            )
            if limit is not None and len(objects) >= limit:
                return objects
    return objects


def load_known_r2_keys() -> set[str]:
    sb = get_supabase_client()
    keys: set[str] = set()
    start = 0
    while True:
        end = start + PAGE_SIZE - 1
        resp = (
            sb.table("camera_clips")
            .select("r2_key")
            .not_.is_("r2_key", "null")
            .range(start, end)
            .execute()
        )
        rows = resp.data or []
        for row in rows:
            key = row.get("r2_key")
            if isinstance(key, str) and key:
                keys.add(key)
        if len(rows) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    return keys


def default_out_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return REPORTS_DIR / f"r2-inventory-{stamp}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="R2 key prefix")
    parser.add_argument("--limit", type=int, default=None, help="R2 mp4 scan limit")
    parser.add_argument("--out-dir", type=Path, default=None, help="report output dir")
    args = parser.parse_args()

    out_dir = args.out_dir or default_out_dir()
    known = load_known_r2_keys()
    objects = list_r2_mp4_objects(args.prefix, limit=args.limit)
    rows, summary = build_inventory(objects, known_r2_keys=known)
    write_reports(rows, summary, out_dir)

    print(f"R2 mp4: {summary['total_r2_mp4']}")
    print(f"classification: {summary['classification_counts']}")
    print(f"reports: {out_dir}")
    print("DB writes: 0 / R2 writes: 0")
    return 0


def _parse_key_shape(key: str) -> dict[str, str | None]:
    match = R2_CLIP_RE.match(key)
    if match:
        return {
            "key_pattern": "canonical_clip",
            "camera_id": match.group("camera_id"),
            "date": match.group("date"),
            "clip_id": match.group("clip_id").lower(),
        }
    legacy_match = LEGACY_DATED_CLIP_RE.match(key)
    if legacy_match:
        return {
            "key_pattern": "legacy_dated_clip",
            "camera_id": legacy_match.group("camera_slug"),
            "date": (
                f"{legacy_match.group('year')}-"
                f"{legacy_match.group('month')}-"
                f"{legacy_match.group('day')}"
            ),
            "clip_id": legacy_match.group("clip_id").lower(),
        }
    return {
        "key_pattern": "unknown",
        "camera_id": None,
        "date": None,
        "clip_id": None,
    }


def _infer_has_motion(key: str) -> bool | None:
    name = Path(key).name.lower()
    if "_motion" in name:
        return True
    if "_idle" in name:
        return False
    return None


def _looks_experiment_artifact(key: str) -> bool:
    lowered = key.lower()
    return any(
        token in lowered
        for token in (
            "verify/",
            "experiment",
            "eval",
            "test",
            "tmp",
            "sample",
        )
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _format_markdown_report(summary: dict[str, Any], out_dir: Path) -> str:
    counts = summary["classification_counts"]
    lines = [
        "# R2 Orphan Inventory Dry-run",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- total_r2_mp4: `{summary['total_r2_mp4']}`",
        f"- total_size_bytes: `{summary['total_size_bytes']}`",
        "- db_writes: `0`",
        "- r2_writes: `0`",
        "",
        "## Classification",
        "",
    ]
    for key in sorted(counts):
        lines.append(f"- `{key}`: {counts[key]}")
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- `{out_dir / 'summary.json'}`",
            f"- `{out_dir / 'inventory.jsonl'}`",
            f"- `{out_dir / 'orphans.jsonl'}`",
            "",
        ]
    )
    return "\n".join(lines)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())

"""Canonical motion GT head를 provenance와 함께 local JSONL로 export해."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "motion-clip-canonical-gt-v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/canonical-gt/exports")
PAGE_SIZE = 1000


@dataclass(frozen=True)
class ExportResult:
    data_path: Path
    manifest_path: Path
    record_count: int


def _default_client():
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("supabase_environment_missing")
    return create_client(url, key)


def _rows(value: Any, code: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise RuntimeError(code)
    return value


def _audit_digest(client: Any) -> str:
    data = client.rpc("fn_audit_motion_clip_canonical_gt", {}).execute().data
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict):
        raise TypeError("canonical_audit_response_invalid")
    digest = data.get("source_mutation_digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise RuntimeError("canonical_audit_digest_invalid")
    return digest


def _load_export_rows(client: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        data = (
            client.table("motion_clip_canonical_gt_export")
            .select(
                "clip_id,revision_id,final_decision,gt,source_type,source_version,updated_at"
            )
            .order("clip_id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data
        )
        page = _rows(data, "canonical_export_response_invalid")
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def _record(row: dict[str, Any]) -> dict[str, Any]:
    clip_id = row.get("clip_id")
    revision_id = row.get("revision_id")
    decision = row.get("final_decision")
    source_type = row.get("source_type")
    source_version = row.get("source_version")
    if not all(isinstance(value, str) and value for value in (
        clip_id, revision_id, decision, source_type, source_version,
    )):
        raise RuntimeError("canonical_export_row_invalid")
    gt = row.get("gt") if decision == "label" else None
    if decision == "label" and not isinstance(gt, dict):
        raise RuntimeError("canonical_export_gt_invalid")
    return {
        "clip_id": clip_id,
        "revision_id": revision_id,
        "decision": decision,
        "gt": gt,
        "provenance": {
            "source_type": source_type,
            "source_version": source_version,
        },
    }


def export_canonical_gt(
    client: Any,
    output_dir: Path,
    *,
    generated_at: str | None = None,
) -> ExportResult:
    """현재 head snapshot만 읽는다. R2 upload·DB write·prediction 결합은 하지 않아."""
    digest = _audit_digest(client)
    records = [_record(row) for row in _load_export_rows(client)]

    output_dir.mkdir(parents=True, exist_ok=True)
    data_path = output_dir / f"{SCHEMA_VERSION}.jsonl"
    manifest_path = output_dir / "manifest.json"
    lines = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for record in records
    )
    data_path.write_text(lines, encoding="utf-8")
    timestamp = generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source_snapshot_digest": digest,
        "generated_at": timestamp,
        "record_count": len(records),
        "data_file": data_path.name,
        "data_sha256": hashlib.sha256(lines.encode("utf-8")).hexdigest(),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ExportResult(data_path, manifest_path, len(records))


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[[], Any] = _default_client,
) -> int:
    parser = argparse.ArgumentParser(description="Export canonical motion GT JSONL")
    parser.add_argument("--source", choices=("canonical",), required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    result = export_canonical_gt(client_factory(), args.output_dir)
    print(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "record_count": result.record_count,
        "data_path": str(result.data_path),
        "manifest_path": str(result.manifest_path),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

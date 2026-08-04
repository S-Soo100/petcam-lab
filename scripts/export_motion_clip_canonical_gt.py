"""Canonical motion GT head를 provenance와 함께 local JSONL로 export해."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
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


def _snapshot(client: Any) -> dict[str, Any]:
    data = client.rpc(
        "fn_get_motion_clip_canonical_gt_export_snapshot", {}
    ).execute().data
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict):
        raise TypeError("canonical_export_snapshot_invalid")
    if not isinstance(data.get("head_count"), int) or data["head_count"] < 0:
        raise RuntimeError("canonical_export_snapshot_count_invalid")
    for field in ("head_digest", "source_mutation_digest"):
        value = data.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise RuntimeError(f"canonical_export_snapshot_{field}_invalid")
    return data


def _load_export_rows(client: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    after_clip_id: str | None = None
    while True:
        query = (
            client.table("motion_clip_canonical_gt_export")
            .select(
                "clip_id,revision_id,final_decision,gt,source_type,source_version,updated_at"
            )
            .order("clip_id")
        )
        if after_clip_id is not None:
            query = query.gt("clip_id", after_clip_id)
        data = query.limit(PAGE_SIZE).execute().data
        page = _rows(data, "canonical_export_response_invalid")
        if page and after_clip_id is not None and str(page[0].get("clip_id", "")) <= after_clip_id:
            raise RuntimeError("canonical_export_keyset_invalid")
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        after_clip_id = str(page[-1].get("clip_id", ""))
        if not after_clip_id:
            raise RuntimeError("canonical_export_keyset_invalid")


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


def _head_digest(records: list[dict[str, Any]]) -> str:
    payload = "\n".join(
        f"{record['clip_id']}|{record['revision_id']}" for record in records
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temp.unlink(missing_ok=True)


def export_canonical_gt(
    client: Any,
    output_dir: Path,
    *,
    generated_at: str | None = None,
) -> ExportResult:
    """현재 head snapshot만 읽는다. R2 upload·DB write·prediction 결합은 하지 않아."""
    before = _snapshot(client)
    records = [_record(row) for row in _load_export_rows(client)]
    after = _snapshot(client)
    canonical_digest = _head_digest(records)
    if before != after:
        raise RuntimeError("canonical_export_snapshot_changed")
    if before["head_count"] != len(records) or before["head_digest"] != canonical_digest:
        raise RuntimeError("canonical_export_snapshot_mismatch")

    output_dir.mkdir(parents=True, exist_ok=True)
    data_path = output_dir / f"{SCHEMA_VERSION}-{canonical_digest[:16]}.jsonl"
    manifest_path = output_dir / "manifest.json"
    lines = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for record in records
    )
    timestamp = generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source_snapshot_digest": before["source_mutation_digest"],
        "canonical_head_digest": canonical_digest,
        "generated_at": timestamp,
        "record_count": len(records),
        "data_file": data_path.name,
        "data_sha256": hashlib.sha256(lines.encode("utf-8")).hexdigest(),
    }
    # content-addressed data를 먼저 publish하고 manifest를 완료 marker로 마지막 교체해.
    _atomic_write_text(data_path, lines)
    _atomic_write_text(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
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

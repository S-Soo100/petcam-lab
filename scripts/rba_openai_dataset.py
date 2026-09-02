"""RBA OpenAI 연구용 dataset·smoke manifest 계약이야."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, Mapping


class DatasetContractError(ValueError):
    """사람 GT dataset 계약이 깨졌을 때 fail-closed해."""


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_dataset_manifest(rows: Iterable[Mapping[str, object]]) -> dict[str, int]:
    materialized = tuple(rows)
    if len(materialized) != 316:
        raise DatasetContractError("exact316")

    sample_ids: set[str] = set()
    media: set[str] = set()
    sources: Counter[str] = Counter()
    highlight_include = 0
    for row in materialized:
        sample_id = row.get("sample_id")
        source = row.get("source")
        media_sha = row.get("media_sha256")
        highlight = row.get("highlight")
        segment_status = row.get("segment_status")
        group_id = row.get("group_id")
        if not isinstance(sample_id, str) or not sample_id or sample_id in sample_ids:
            raise DatasetContractError("duplicate_sample")
        if source not in {"legacy_frozen", "recent_owner_final"}:
            raise DatasetContractError("source")
        if not isinstance(media_sha, str) or len(media_sha) != 64:
            raise DatasetContractError("media_sha256")
        if media_sha in media:
            raise DatasetContractError("duplicate_media")
        if highlight != "include":
            raise DatasetContractError("highlight_include")
        if source == "legacy_frozen" and segment_status != "not_measured":
            raise DatasetContractError("legacy_segment_status")
        if not isinstance(group_id, str) or not group_id:
            raise DatasetContractError("group_id")
        sample_ids.add(sample_id)
        media.add(media_sha)
        sources[source] += 1
        highlight_include += 1

    if sources != Counter({"legacy_frozen": 197, "recent_owner_final": 119}):
        raise DatasetContractError("source_counts")
    return {
        "total": len(materialized),
        "legacy_frozen": sources["legacy_frozen"],
        "recent_owner_final": sources["recent_owner_final"],
        "highlight_include": highlight_include,
        "unique_media": len(media),
    }


def split_dataset(
    rows: Iterable[Mapping[str, object]], *, development_target: int
) -> dict[str, str]:
    if development_target <= 0:
        raise DatasetContractError("development_target")
    groups: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        sample_id = row.get("sample_id")
        group_id = row.get("group_id")
        if not isinstance(sample_id, str) or not isinstance(group_id, str):
            raise DatasetContractError("split_row")
        groups[group_id].append(sample_id)
    if not groups:
        raise DatasetContractError("split_empty")

    ordered_groups = sorted(
        groups,
        key=lambda value: hashlib.sha256(f"rba-openai-split-v1:{value}".encode()).hexdigest(),
    )
    development: set[str] = set()
    count = 0
    for group_id in ordered_groups:
        if count >= development_target:
            break
        development.add(group_id)
        count += len(groups[group_id])
    if len(development) == len(groups):
        development.remove(ordered_groups[-1])

    return {
        sample_id: "development" if group_id in development else "evaluation"
        for group_id in sorted(groups)
        for sample_id in sorted(groups[group_id])
    }


def build_smoke_manifest(
    media_paths: Iterable[Path], *, output: Path, count: int = 3
) -> dict[str, object]:
    candidates: list[tuple[str, Path]] = []
    for raw_path in media_paths:
        path = raw_path.resolve()
        if not path.is_file() or path.is_symlink():
            raise DatasetContractError("smoke_media")
        candidates.append((_sha256(path), path))
    if count <= 0 or len(candidates) < count:
        raise DatasetContractError("smoke_count")
    if len({digest for digest, _ in candidates}) != len(candidates):
        raise DatasetContractError("duplicate_media")
    selected = sorted(candidates, key=lambda item: item[0])[:count]
    manifest: dict[str, object] = {
        "schema_version": "rba-openai-smoke-manifest-v1",
        "clip_count": count,
        "clips": [
            {
                "clip_ref": f"smoke-{digest[:12]}",
                "media_path": str(path),
                "media_sha256": digest,
            }
            for digest, path in selected
        ],
    }
    if output.exists() or output.is_symlink():
        raise DatasetContractError("output_exists")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(_canonical_bytes(manifest))
        handle.flush()
        os.fsync(handle.fileno())
    output.chmod(0o600)
    return manifest

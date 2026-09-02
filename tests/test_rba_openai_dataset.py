from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.rba_openai_dataset import (
    DatasetContractError,
    build_smoke_manifest,
    split_dataset,
    validate_dataset_manifest,
)


def _row(index: int, *, source: str, group: str | None = None) -> dict[str, object]:
    return {
        "sample_id": f"sample-{index:03d}",
        "source": source,
        "media_sha256": f"{index:064x}",
        "highlight": "include",
        "segment_status": "not_measured" if source == "legacy_frozen" else "measured",
        "group_id": group or f"night-{index:03d}",
        "media_path": f"/private/media/sample-{index:03d}.mp4",
    }


def test_validate_dataset_manifest_accepts_exact_197_plus_119() -> None:
    rows = [*(_row(i, source="legacy_frozen") for i in range(197))]
    rows.extend(_row(i + 197, source="recent_owner_final") for i in range(119))

    summary = validate_dataset_manifest(rows)

    assert summary == {
        "total": 316,
        "legacy_frozen": 197,
        "recent_owner_final": 119,
        "highlight_include": 316,
        "unique_media": 316,
    }


def test_validate_dataset_manifest_rejects_duplicate_media() -> None:
    rows = [*(_row(i, source="legacy_frozen") for i in range(197))]
    rows.extend(_row(i + 197, source="recent_owner_final") for i in range(119))
    rows[-1]["media_sha256"] = rows[0]["media_sha256"]

    with pytest.raises(DatasetContractError, match="duplicate_media"):
        validate_dataset_manifest(rows)


def test_split_dataset_is_deterministic_and_keeps_groups_together() -> None:
    rows = [
        _row(0, source="legacy_frozen", group="night-a"),
        _row(1, source="legacy_frozen", group="night-a"),
        _row(2, source="recent_owner_final", group="night-b"),
        _row(3, source="recent_owner_final", group="night-c"),
        _row(4, source="recent_owner_final", group="night-d"),
    ]

    first = split_dataset(rows, development_target=2)
    second = split_dataset(list(reversed(rows)), development_target=2)

    assert first == second
    assignments = {
        row["group_id"]: first[row["sample_id"]]  # type: ignore[index]
        for row in rows
    }
    assert len({assignments["night-a"]}) == 1
    assert set(first.values()) == {"development", "evaluation"}


def test_build_smoke_manifest_is_gt_free_and_hashes_files(tmp_path: Path) -> None:
    media_paths = []
    for index, payload in enumerate((b"one", b"two", b"three", b"four")):
        path = tmp_path / f"clip-{index}.mp4"
        path.write_bytes(payload)
        media_paths.append(path)

    output = tmp_path / "smoke.json"
    manifest = build_smoke_manifest(media_paths, output=output, count=3)

    assert manifest["schema_version"] == "rba-openai-smoke-manifest-v1"
    assert manifest["clip_count"] == 3
    assert len(manifest["clips"]) == 3
    assert all(set(row) == {"clip_ref", "media_path", "media_sha256"} for row in manifest["clips"])
    assert json.loads(output.read_text()) == manifest
    assert output.stat().st_mode & 0o777 == 0o600

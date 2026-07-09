from __future__ import annotations

from pathlib import Path

from scripts.r2_orphan_inventory import (
    R2ObjectInfo,
    build_inventory,
    parse_r2_clip_key,
    write_reports,
)


CANONICAL_KEY = (
    "clips/3a6cffbf-be83-4c77-9fa7-4fcc517c74a6/"
    "2026-05-02/153012_motion_"
    "685911a0-8b68-4d9e-a55b-b4db5ff27647.mp4"
)


def test_parse_known_camera_clip() -> None:
    parsed = parse_r2_clip_key(CANONICAL_KEY, known_r2_keys={CANONICAL_KEY})

    assert parsed.classification == "known_camera_clip"
    assert parsed.key_pattern == "canonical_clip"
    assert parsed.camera_id == "3a6cffbf-be83-4c77-9fa7-4fcc517c74a6"
    assert parsed.inferred_has_motion is True
    assert parsed.import_confidence == "none"


def test_parse_likely_missing_camera_clip() -> None:
    parsed = parse_r2_clip_key(CANONICAL_KEY, known_r2_keys=set())

    assert parsed.classification == "likely_missing_camera_clip"
    assert parsed.key_pattern == "canonical_clip"
    assert parsed.clip_id == "685911a0-8b68-4d9e-a55b-b4db5ff27647"
    assert parsed.import_confidence == "medium"


def test_parse_experiment_artifact() -> None:
    parsed = parse_r2_clip_key("verify/20260710_test.mp4", known_r2_keys=set())

    assert parsed.classification == "experiment_artifact"
    assert parsed.key_pattern == "unknown"


def test_parse_legacy_dated_clip_requires_manual_review() -> None:
    parsed = parse_r2_clip_key(
        "clips/2026/06/17/p4cam-79b5d844/"
        "0323b804-9b2e-4a1d-ba94-3c8a235a4e25.mp4",
        known_r2_keys=set(),
    )

    assert parsed.classification == "manual_review_clip"
    assert parsed.key_pattern == "legacy_dated_clip"
    assert parsed.camera_id == "p4cam-79b5d844"
    assert parsed.date == "2026-06-17"
    assert parsed.import_confidence == "low"


def test_build_inventory_summary_counts() -> None:
    rows, summary = build_inventory(
        [
            R2ObjectInfo(key=CANONICAL_KEY, size=100),
            R2ObjectInfo(key="verify/20260710_test.mp4", size=50),
        ],
        known_r2_keys={CANONICAL_KEY},
    )

    assert len(rows) == 2
    assert summary["db_writes"] == 0
    assert summary["r2_writes"] == 0
    assert summary["classification_counts"] == {
        "known_camera_clip": 1,
        "experiment_artifact": 1,
    }


def test_write_reports_creates_summary_inventory_and_orphans(tmp_path: Path) -> None:
    rows, summary = build_inventory(
        [
            R2ObjectInfo(key=CANONICAL_KEY, size=100),
            R2ObjectInfo(key="verify/20260710_test.mp4", size=50),
        ],
        known_r2_keys={CANONICAL_KEY},
    )

    write_reports(rows, summary, tmp_path)

    assert (tmp_path / "summary.json").is_file()
    assert (tmp_path / "inventory.jsonl").is_file()
    assert (tmp_path / "orphans.jsonl").read_text(encoding="utf-8").count("\n") == 1
    report = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
    assert "db_writes: `0`" in report
    assert "r2_writes: `0`" in report

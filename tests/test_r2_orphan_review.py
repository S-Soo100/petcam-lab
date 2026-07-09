from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.r2_orphan_review import (
    VideoEvidence,
    build_review_row,
    load_orphan_rows,
    write_review_pack,
)


ORPHAN_ROW = {
    "key": "clips/2026/06/17/p4cam-79b5d844/0323b804.mp4",
    "camera_id": "p4cam-79b5d844",
    "date": "2026-06-17",
    "clip_id": "0323b804",
    "classification": "manual_review_clip",
    "import_confidence": "low",
    "last_modified": "2026-06-17T14:44:03Z",
    "size": 1158651,
}


def test_load_orphan_rows_reads_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "orphans.jsonl"
    path.write_text(json.dumps(ORPHAN_ROW) + "\n", encoding="utf-8")

    assert load_orphan_rows(path) == [ORPHAN_ROW]


def test_build_review_row_defaults_to_manual_decision() -> None:
    evidence = VideoEvidence(
        local_clip_path="clips/0323b804.mp4",
        thumbnail_path="thumbnails/0323b804.jpg",
        openable=True,
        duration_sec=3.1,
        width=3840,
        height=2160,
        fps=29.97,
        frame_count=93,
        motion_score=0.22,
    )

    row = build_review_row(ORPHAN_ROW, evidence=evidence, db_match_count=0)

    assert row["decision"] == "needs_human_label"
    assert row["db_match"] == "no_match"
    assert row["visual_status"] == "openable"
    assert row["duration_sec"] == 3.1
    assert row["notes"] == "legacy path; camera/user mapping uncertain"


def test_build_review_row_marks_duplicates_for_ignore() -> None:
    evidence = VideoEvidence(
        local_clip_path="clips/0323b804.mp4",
        thumbnail_path=None,
        openable=True,
        duration_sec=3.1,
        width=3840,
        height=2160,
        fps=29.97,
        frame_count=93,
        motion_score=None,
    )

    row = build_review_row(ORPHAN_ROW, evidence=evidence, db_match_count=2)

    assert row["decision"] == "ignore"
    assert row["db_match"] == "possible_duplicate"


def test_write_review_pack_creates_csv_and_markdown(tmp_path: Path) -> None:
    review_rows = [
        {
            **ORPHAN_ROW,
            "local_clip_path": "clips/0323b804.mp4",
            "thumbnail_path": "thumbnails/0323b804.jpg",
            "visual_status": "openable",
            "db_match": "no_match",
            "decision": "needs_human_label",
            "notes": "legacy path; camera/user mapping uncertain",
            "duration_sec": 3.1,
            "width": 3840,
            "height": 2160,
            "fps": 29.97,
            "frame_count": 93,
            "motion_score": 0.22,
        }
    ]

    write_review_pack(review_rows, tmp_path)

    with (tmp_path / "review.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["decision"] == "needs_human_label"
    report = (tmp_path / "REVIEW.md").read_text(encoding="utf-8")
    assert "DB writes: `0`" in report
    assert "`needs_human_label`: 1" in report

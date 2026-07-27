from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent))

import verify_artifacts  # noqa: E402


ROOT = Path(__file__).parent


def test_raw_directory_is_gitignored(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("/raw/\n", encoding="utf-8")
    verify_artifacts.assert_raw_ignored(tmp_path)


def test_rejects_missing_raw_ignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="raw_not_ignored"):
        verify_artifacts.assert_raw_ignored(tmp_path)


def test_rejects_sensitive_field_names_in_tracked_json(tmp_path: Path) -> None:
    (tmp_path / "source-summary.json").write_text(
        '{"clip_id":"00000000-0000-0000-0000-000000000000"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="sensitive_tracked_content"):
        verify_artifacts.assert_no_sensitive_tracked_content(tmp_path)


def test_inventory_sql_is_select_only() -> None:
    sql = (ROOT / "inventory.sql").read_text(encoding="utf-8")
    verify_artifacts.assert_select_only_sql(sql)


def test_blind_review_aggregate_sql_is_select_only() -> None:
    sql = (ROOT / "blind-review-aggregate.sql").read_text(encoding="utf-8")
    verify_artifacts.assert_select_only_sql(sql)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO x VALUES (1)",
        "UPDATE x SET a=1",
        "DELETE FROM x",
        "CREATE TABLE x(a int)",
        "SELECT public.fn_write_something()",
    ],
)
def test_rejects_write_sql(statement: str) -> None:
    with pytest.raises(ValueError, match="non_select_sql"):
        verify_artifacts.assert_select_only_sql(statement)


def _write_fingerprint(path: Path, row_count: int, fingerprint: str) -> None:
    path.write_text(
        "snapshot_at_utc,table_name,row_count,ordered_fingerprint_md5\n"
        f"2026-07-27T00:00:00Z,t,{row_count},{fingerprint}\n",
        encoding="utf-8",
    )


def test_rejects_fingerprint_mutation(tmp_path: Path) -> None:
    _write_fingerprint(tmp_path / "fingerprints-start.csv", 1, "a" * 32)
    _write_fingerprint(tmp_path / "fingerprints-end.csv", 2, "b" * 32)
    with pytest.raises(ValueError, match="fingerprint_mutation"):
        verify_artifacts.assert_fingerprints_equal(tmp_path)


def test_accepts_identical_fingerprints_with_different_snapshot_time(
    tmp_path: Path,
) -> None:
    _write_fingerprint(tmp_path / "fingerprints-start.csv", 1, "a" * 32)
    _write_fingerprint(tmp_path / "fingerprints-end.csv", 1, "a" * 32)
    verify_artifacts.assert_fingerprints_equal(tmp_path)


def test_rejects_blind_review_fingerprint_mutation(tmp_path: Path) -> None:
    _write_fingerprint(
        tmp_path / "blind-review-fingerprints-start.csv", 1, "a" * 32
    )
    _write_fingerprint(
        tmp_path / "blind-review-fingerprints-end.csv", 2, "b" * 32
    )
    with pytest.raises(ValueError, match="blind_review_fingerprint_mutation"):
        verify_artifacts.assert_blind_review_fingerprints_equal(tmp_path)


def test_ready_requires_one_candidate_and_qualified_cause() -> None:
    summary = {
        "verdict": "UNIFIED_GT_FAILURE_AUDIT_READY_FOR_REVIEW",
        "top_causes": [
            {
                "cause": "TEMPORAL_SAMPLING",
                "qualified": True,
                "independent_episodes": 10,
                "camera_nights": 2,
                "largest_duplicate_share": 0.1,
            }
        ],
        "next_candidate": {"id": "segment_aware_sampling_experiment"},
    }
    verify_artifacts.assert_verdict_consistent(summary)


def test_rejects_ready_without_candidate() -> None:
    summary = {
        "verdict": "UNIFIED_GT_FAILURE_AUDIT_READY_FOR_REVIEW",
        "top_causes": [{"cause": "TEMPORAL_SAMPLING", "qualified": True}],
        "next_candidate": None,
    }
    with pytest.raises(ValueError, match="ready_without_candidate"):
        verify_artifacts.assert_verdict_consistent(summary)


def test_rejects_ready_with_underpowered_top_cause() -> None:
    summary = {
        "verdict": "UNIFIED_GT_FAILURE_AUDIT_READY_FOR_REVIEW",
        "top_causes": [
            {
                "cause": "TEMPORAL_SAMPLING",
                "qualified": True,
                "independent_episodes": 9,
                "camera_nights": 2,
                "largest_duplicate_share": 0.1,
            }
        ],
        "next_candidate": {"id": "segment_aware_sampling_experiment"},
    }
    with pytest.raises(ValueError, match="underpowered_top_cause"):
        verify_artifacts.assert_verdict_consistent(summary)


def test_rejects_candidate_not_mapped_to_top_cause() -> None:
    summary = {
        "verdict": "UNIFIED_GT_FAILURE_AUDIT_READY_FOR_REVIEW",
        "top_causes": [
            {
                "cause": "VISIBILITY_SCALE_OCCLUSION",
                "qualified": True,
                "independent_episodes": 19,
                "camera_nights": 4,
                "largest_duplicate_share": 0.0476,
            }
        ],
        "next_candidate": {"id": "segment_aware_sampling_experiment"},
    }
    with pytest.raises(ValueError, match="candidate_cause_mismatch"):
        verify_artifacts.assert_verdict_consistent(summary)


def test_hold_requires_no_candidate() -> None:
    summary = {
        "verdict": "UNIFIED_GT_FAILURE_AUDIT_HOLD_INSUFFICIENT_CONFIRMED_ROOT_CAUSES",
        "top_causes": [],
        "next_candidate": None,
    }
    verify_artifacts.assert_verdict_consistent(summary)


def test_blind_review_summary_partitions_all_reviewed_rows() -> None:
    summary = {
        "reviewed_clips": 44,
        "judgeable_clips": 44,
        "primary_causes": [
            {"cause": "VISIBILITY_SCALE_OCCLUSION", "clips": 21},
            {"cause": "TEMPORAL_SAMPLING", "clips": 14},
            {"cause": "INPUT_QUALITY", "clips": 8},
            {"cause": "IR_LIGHT_REFLECTION", "clips": 1},
        ],
    }
    verify_artifacts.assert_blind_review_summary(summary)


def test_failure_top_cause_matches_blind_review_qualified_cause() -> None:
    blind = {
        "primary_causes": [
            {
                "cause": "VISIBILITY_SCALE_OCCLUSION",
                "qualified": True,
            }
        ]
    }
    failure = {
        "top_causes": [
            {
                "cause": "VISIBILITY_SCALE_OCCLUSION",
                "qualified": True,
            }
        ]
    }
    verify_artifacts.assert_failure_matches_blind_review(failure, blind)


def test_real_verdict_is_ready_after_blind_review() -> None:
    failure = json.loads((ROOT / "failure-summary.json").read_text(encoding="utf-8"))
    assert failure["verdict"] == "UNIFIED_GT_FAILURE_AUDIT_READY_FOR_REVIEW"
    assert failure["next_candidate"] == {"id": "visibility_bbox_roi_experiment"}


def test_real_aggregate_arithmetic_is_consistent() -> None:
    root = Path(__file__).parent
    source = json.loads((root / "source-summary.json").read_text(encoding="utf-8"))
    overlap = json.loads((root / "overlap-summary.json").read_text(encoding="utf-8"))
    failure = json.loads((root / "failure-summary.json").read_text(encoding="utf-8"))
    verify_artifacts.assert_source_summary(source)
    verify_artifacts.assert_overlap_summary(source, overlap)
    verify_artifacts.assert_failure_summary(failure)

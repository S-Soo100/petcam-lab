from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))

import analyze  # noqa: E402


def test_blind_immutable_human_gt_is_t1() -> None:
    record = {
        "human": True,
        "blind": True,
        "immutable_initial_gt": True,
        "provenance_complete": True,
        "automatic": False,
        "tutorial": False,
    }
    assert analyze.assign_trust_tier(record) == "T1"


def test_reviewed_human_gt_is_t2() -> None:
    record = {
        "human": True,
        "blind": False,
        "immutable_initial_gt": False,
        "provenance_complete": True,
        "automatic": False,
        "tutorial": False,
    }
    assert analyze.assign_trust_tier(record) == "T2"


def test_automatic_result_is_excluded() -> None:
    record = {"automatic": True, "human": False}
    assert analyze.assign_trust_tier(record) == "X"


def test_unknown_mapping_is_not_inferred() -> None:
    result = analyze.canonicalize_targets(
        {"motion": None, "visibility": None, "primary_action": "legacy_unknown"}
    )
    assert result == {
        "motion": "unknown",
        "visibility": "unknown",
        "primary_action": "unknown",
        "care_event": "unknown",
        "highlight": "unavailable",
        "judgeability": "unavailable",
    }


def test_owner_mapping_uses_observed_actions_without_inference() -> None:
    result = analyze.canonicalize_targets(
        {
            "observed_actions": ["moving", "wheel"],
            "visibility": "partial",
            "primary_action": "moving",
            "highlight_recommendation": "include",
        }
    )
    assert result["motion"] == "moving"
    assert result["visibility"] == "partial"
    assert result["primary_action"] == "moving"
    assert result["care_event"] == "non-care"
    assert result["highlight"] == "include"


def test_exact_object_hash_precedes_temporal_match() -> None:
    record = {
        "source_fk_hash": None,
        "object_key_hash": "obj-a",
        "content_hash": None,
        "camera_hash": "cam-a",
        "started_at_epoch": 100,
        "duration_ms": 60000,
        "size_bytes": 1000,
    }
    assert analyze.dedup_key(record) == ("exact_object", "obj-a")


def test_five_minute_gap_groups_same_camera_episode() -> None:
    records = [
        {"record_hash": "a", "camera_hash": "cam", "started_at_epoch": 100},
        {"record_hash": "b", "camera_hash": "cam", "started_at_epoch": 399},
        {"record_hash": "c", "camera_hash": "cam", "started_at_epoch": 700},
    ]
    grouped = analyze.group_episodes(records)
    assert grouped[0]["episode_group_hash"] == grouped[1]["episode_group_hash"]
    assert grouped[1]["episode_group_hash"] != grouped[2]["episode_group_hash"]


def test_source_summary_separates_rows_unique_and_trust() -> None:
    records = [
        {"source": "owner", "canonical_clip_key": "x", "trust_tier": "T1"},
        {"source": "dataset203", "canonical_clip_key": "x", "trust_tier": "T3"},
        {"source": "dataset203", "canonical_clip_key": "y", "trust_tier": "T2"},
    ]
    summary = analyze.summarize_sources(records)
    assert summary["total_rows"] == 3
    assert summary["unique_clips"] == 2
    assert summary["sources"]["dataset203"]["rows"] == 2
    assert summary["trust_tiers"] == {"T1": 1, "T2": 1, "T3": 1}


def test_overlap_summary_counts_cross_source_clip_once() -> None:
    records = [
        {"source": "owner", "canonical_clip_key": "x"},
        {"source": "legacy", "canonical_clip_key": "x"},
        {"source": "legacy", "canonical_clip_key": "y"},
    ]
    overlap = analyze.summarize_overlap(records)
    assert overlap["source_pairs"]["legacy|owner"]["exact_unique_clips"] == 1

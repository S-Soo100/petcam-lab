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


def test_vlm_action_mismatch_creates_failure_without_using_vlm_as_gt() -> None:
    record = {
        "trust_tier": "T1",
        "gt": {"primary_action": "drinking"},
        "vlm": {"primary_action": "licking", "status": "success"},
        "evidence": None,
        "candidate_causes": ["SEMANTIC_ONTOLOGY"],
    }
    failures = analyze.derive_failures(record)
    assert failures[0]["failure_kind"] == "vlm_primary_action_mismatch"
    assert failures[0]["candidate_causes"] == ["SEMANTIC_ONTOLOGY"]


def test_gate_present_on_absent_gt_is_visibility_false_positive() -> None:
    record = {
        "trust_tier": "T1",
        "gt": {"visibility": "absent"},
        "gate": {"present": True, "status": "ok"},
        "candidate_causes": ["VISIBILITY_SCALE_OCCLUSION"],
    }
    failures = analyze.derive_failures(record)
    assert failures[0]["failure_kind"] == "gate_visibility_false_positive"


def test_top_cause_requires_episode_and_camera_night_support() -> None:
    failures = [
        {
            "cause": "TEMPORAL_SAMPLING",
            "episode_group_hash": f"e{i}",
            "camera_night_hash": "n1" if i < 5 else "n2",
            "source": "owner",
            "duplicate_group_hash": f"d{i}",
            "trust_tier": "T1",
            "care_or_highlight_miss": i < 3,
        }
        for i in range(10)
    ]
    ranked = analyze.rank_causes(failures)
    assert ranked[0]["qualified"] is True
    assert ranked[0]["independent_episodes"] == 10


def test_duplicate_dominated_cause_is_not_qualified() -> None:
    failures = [
        {
            "cause": "IR_LIGHT_REFLECTION",
            "episode_group_hash": f"e{i}",
            "camera_night_hash": "n1" if i < 5 else "n2",
            "source": "owner",
            "duplicate_group_hash": "same" if i < 3 else f"d{i}",
            "trust_tier": "T1",
            "care_or_highlight_miss": False,
        }
        for i in range(10)
    ]
    assert analyze.rank_causes(failures)[0]["qualified"] is False


def test_ready_verdict_selects_exactly_one_candidate() -> None:
    summary = {
        "ranked_causes": [
            {"cause": "TEMPORAL_SAMPLING", "qualified": True},
            {"cause": "CAMERA_DOMAIN", "qualified": True},
        ]
    }
    verdict, candidate = analyze.decide_verdict(summary)
    assert verdict == "UNIFIED_GT_FAILURE_AUDIT_READY_FOR_REVIEW"
    assert candidate == {"id": "segment_aware_sampling_experiment"}


def test_hold_when_no_cause_qualifies() -> None:
    verdict, candidate = analyze.decide_verdict(
        {"ranked_causes": [{"cause": "CAMERA_DOMAIN", "qualified": False}]}
    )
    assert verdict == "UNIFIED_GT_FAILURE_AUDIT_HOLD_INSUFFICIENT_INDEPENDENT_ERRORS"
    assert candidate is None

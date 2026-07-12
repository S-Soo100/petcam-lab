from __future__ import annotations

from scripts.build_router_care_guard_review_batch import (
    CandidateQuotas,
    build_review_payload,
    select_review_candidates,
)


def _row(clip_id: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "clip_id": clip_id,
        "camera_id": "cam-001",
        "started_at": "2026-07-10T00:00:00+00:00",
        "processing_status": "ready",
        "evidence_reliability": "medium",
        "motion_mean": 0.05,
        "motion_peak": 0.20,
        "motion_std": 0.06,
        "active_motion_ratio": 0.40,
        "center_motion_ratio": 0.40,
        "late_motion_ratio": 0.50,
        "last_motion_sec": 40.0,
        "motion_burst_count": 1,
    }
    row.update(overrides)
    return row


def test_select_review_candidates_prefers_guard_changed_groups_without_duplicates() -> None:
    rows = [
        _row("demote-1", center_motion_ratio=0.40, active_motion_ratio=0.40),
        _row("demote-2", center_motion_ratio=0.70, active_motion_ratio=0.80),
        _row(
            "promote-1",
            motion_mean=0.006,
            motion_peak=0.09,
            motion_std=0.01,
            active_motion_ratio=0.20,
            center_motion_ratio=1.20,
            late_motion_ratio=2.00,
        ),
        _row(
            "review-1",
            processing_status="ready",
            evidence_reliability="low",
            motion_mean=0.004,
            motion_peak=0.02,
            active_motion_ratio=0.10,
            center_motion_ratio=1.0,
            late_motion_ratio=1.0,
        ),
        _row("control-1", center_motion_ratio=1.20, active_motion_ratio=0.40),
    ]

    selected = select_review_candidates(
        rows,
        quotas=CandidateQuotas(
            guard_demote=2,
            guard_promote=1,
            review_candidate_low_motion=1,
            random_control=1,
        ),
    )

    assert [row["clip_id"] for row in selected] == [
        "demote-1",
        "promote-1",
        "review-1",
        "control-1",
        "demote-2",
    ]
    assert [row["sample_group"] for row in selected] == [
        "guard_demote_cloud_now",
        "guard_promote_late_care",
        "review_candidate_low_motion",
        "random_control",
        "quota_fill",
    ]
    assert len({row["clip_id"] for row in selected}) == len(selected)


def test_build_review_payload_uses_candidate_route_and_encodes_baseline_reason() -> None:
    candidate = {
        **_row("clip-001"),
        "sample_group": "guard_demote_cloud_now",
        "baseline_route": "cloud_now",
        "candidate_route": "cloud_later",
        "candidate_reason": "off_center_motion_batchable",
        "priority": 0.42,
        "risk": "medium",
    }

    payload = build_review_payload(candidate, batch_id="batch-care-v1")

    assert payload["batch_id"] == "batch-care-v1"
    assert payload["clip_id"] == "clip-001"
    assert payload["route"] == "cloud_later"
    assert payload["sample_group"] == "guard_demote_cloud_now"
    assert payload["reason"] == "care_guard_v1:baseline=cloud_now;rule=off_center_motion_batchable"
    assert payload["motion_mean"] == 0.05

from __future__ import annotations

from scripts.router_care_guard_v1_report import (
    route_care_guard_v1,
    summarize_dataset203,
    summarize_operational,
)


def test_off_center_cloud_now_demotes_to_cloud_later() -> None:
    decision = route_care_guard_v1(
        {
            "clip_id": "clip-001",
            "route": "cloud_now",
            "center_motion_ratio": 0.4,
            "active_motion_ratio": 0.5,
            "last_motion_sec": 40.0,
        }
    )

    assert decision.route == "cloud_later"
    assert decision.reason == "off_center_motion_batchable"


def test_off_center_but_persistent_motion_stays_cloud_now() -> None:
    decision = route_care_guard_v1(
        {
            "clip_id": "clip-care",
            "route": "cloud_now",
            "center_motion_ratio": 0.5,
            "active_motion_ratio": 1.0,
            "last_motion_sec": 40.0,
        }
    )

    assert decision.route == "cloud_now"
    assert decision.reason == "unchanged"


def test_off_center_but_late_motion_stays_cloud_now() -> None:
    decision = route_care_guard_v1(
        {
            "clip_id": "clip-late",
            "route": "cloud_now",
            "center_motion_ratio": 0.4,
            "active_motion_ratio": 0.5,
            "last_motion_sec": 58.0,
        }
    )

    assert decision.route == "cloud_now"
    assert decision.reason == "unchanged"


def test_late_low_motion_cloud_later_promotes_to_review_candidate() -> None:
    decision = route_care_guard_v1(
        {
            "clip_id": "clip-002",
            "route": "cloud_later",
            "late_motion_ratio": 2.0,
            "motion_peak": 0.09,
            "active_motion_ratio": 0.2,
        }
    )

    assert decision.route == "review_candidate"
    assert decision.reason == "late_low_motion_care_sentinel"


def test_operational_summary_tracks_two_goal_smoke() -> None:
    rows = [
        {
            "clip_id": "noise",
            "route": "cloud_now",
            "center_motion_ratio": 0.4,
            "active_motion_ratio": 0.5,
            "last_motion_sec": 40.0,
            "inspection": "yes",
            "inspection_label": "비검사",
            "action": "human_noise",
        },
        {
            "clip_id": "748c1b7d-b634-4793-a9bc-cdf87bee350e",
            "route": "cloud_later",
            "late_motion_ratio": 2.0,
            "motion_peak": 0.09,
            "active_motion_ratio": 0.2,
            "inspection": "no",
            "inspection_label": "검사",
            "action": "drinking",
        },
        {
            "clip_id": "8abccef4-430a-4d73-a338-3891b46beb3e",
            "route": "review_candidate",
            "inspection": "no",
            "inspection_label": "검사",
            "action": "drinking",
        },
        {
            "clip_id": "d9346cbe-9ae4-456c-a018-50ecf10ac476",
            "route": "review_candidate",
            "inspection": "no",
            "inspection_label": "검사",
            "action": "feeding",
        },
    ]

    summary = summarize_operational(rows)

    assert summary["non_inspection_cloud_now_before"] == 1
    assert summary["non_inspection_cloud_now_after"] == 0
    assert summary["regression_pass"] is True
    assert summary["inspection_activity_only_after"] == 0
    assert summary["inspection_low_after"] == 0


def test_dataset_summary_reports_care_recall_and_moving_reduction() -> None:
    rows = [
        {
            "clip_id": "moving-a",
            "route": "cloud_now",
            "gt": "moving",
            "center_motion_ratio": 0.4,
            "active_motion_ratio": 0.5,
            "last_motion_sec": 40.0,
        },
        {
            "clip_id": "moving-b",
            "route": "cloud_now",
            "gt": "moving",
            "center_motion_ratio": 1.2,
            "active_motion_ratio": 0.5,
        },
        {
            "clip_id": "drink-a",
            "route": "review_candidate",
            "gt": "drinking",
            "center_motion_ratio": 0.6,
            "active_motion_ratio": 1.0,
        },
    ]

    summary = summarize_dataset203(rows)

    assert summary["moving_cloud_now_before"] == 2
    assert summary["moving_cloud_now_after"] == 1
    assert summary["care_candidate_recall_after"] == 1.0

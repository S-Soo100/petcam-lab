from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.router_operational_v0_report import (
    ALLOWED_ROUTES,
    route_operational_feature,
    summarize_decisions,
    write_report,
)


def _feature(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "clip_id": "clip-001",
        "camera_id": "cam-001",
        "started_at": "2026-07-09T12:00:00+00:00",
        "duration_sec": 60.0,
        "fps": 29.97,
        "width": 3840,
        "height": 2160,
        "motion_mean": 0.006,
        "motion_peak": 0.020,
        "motion_std": 0.004,
        "active_motion_ratio": 0.08,
        "brightness_mean": 45.0,
        "brightness_std": 8.0,
        "motion_burst_count": 1,
        "longest_motion_burst_sec": 1.2,
        "processing_status": "ready",
    }
    row.update(overrides)
    return row


def test_allowed_routes_do_not_include_skip_or_auto_labels() -> None:
    assert ALLOWED_ROUTES == {
        "cloud_now",
        "cloud_later",
        "activity_only",
        "review_candidate",
    }


def test_failed_feature_routes_to_review_candidate() -> None:
    decision = route_operational_feature(
        _feature(processing_status="failed", processing_error="decode failed")
    )

    assert decision.route == "review_candidate"
    assert decision.risk == "high"
    assert "not_ready" in decision.reason


def test_high_motion_routes_to_cloud_now() -> None:
    decision = route_operational_feature(
        _feature(motion_mean=0.055, motion_peak=0.22, active_motion_ratio=0.82)
    )

    assert decision.route == "cloud_now"
    assert decision.priority >= 0.8


def test_low_but_nonzero_activity_routes_to_cloud_later() -> None:
    decision = route_operational_feature(
        _feature(motion_mean=0.007, motion_peak=0.018, active_motion_ratio=0.08)
    )

    assert decision.route == "cloud_later"
    assert decision.risk == "medium"


def test_extreme_static_reliable_clip_routes_to_activity_only() -> None:
    decision = route_operational_feature(
        _feature(motion_mean=0.0008, motion_peak=0.004, active_motion_ratio=0.005)
    )

    assert decision.route == "activity_only"
    assert decision.priority < 0.3


def test_summary_counts_decisions_and_estimated_cloud_now_reduction() -> None:
    decisions = [
        route_operational_feature(_feature(clip_id="a", motion_mean=0.055, motion_peak=0.22)),
        route_operational_feature(_feature(clip_id="b", motion_mean=0.007, motion_peak=0.018)),
        route_operational_feature(
            _feature(clip_id="c", motion_mean=0.0008, motion_peak=0.004, active_motion_ratio=0.005)
        ),
    ]

    summary = summarize_decisions(decisions)

    assert summary["n"] == 3
    assert summary["routes"] == {
        "cloud_now": 1,
        "cloud_later": 1,
        "activity_only": 1,
    }
    assert summary["reasons"]["strong_activity_or_burst"] == 1
    assert summary["cloud_now_rate"] == 1 / 3
    assert summary["estimated_immediate_vlm_reduction_rate"] == 2 / 3


def test_write_report_creates_json_csv_and_markdown(tmp_path: Path) -> None:
    rows = [_feature(clip_id="a", motion_mean=0.055, motion_peak=0.22)]
    decisions = [route_operational_feature(rows[0])]
    summary = summarize_decisions(decisions)

    write_report(rows, decisions, summary, tmp_path)

    assert json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))["n"] == 1
    with (tmp_path / "decisions.csv").open(newline="", encoding="utf-8") as f:
        csv_rows = list(csv.DictReader(f))
    assert csv_rows[0]["route"] == "cloud_now"
    report = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
    assert "DB writes: `0`" in report
    assert "LLM/VLM calls: `0`" in report


def test_write_report_marks_high_review_candidate_rate_as_hold(tmp_path: Path) -> None:
    rows = [
        _feature(clip_id="a", processing_status="ready", evidence_reliability="low"),
        _feature(clip_id="b", processing_status="ready", evidence_reliability="low"),
        _feature(clip_id="c", motion_mean=0.055, motion_peak=0.22),
    ]
    decisions = [route_operational_feature(row) for row in rows]
    summary = summarize_decisions(decisions)

    write_report(rows, decisions, summary, tmp_path)

    report = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
    assert "Decision: `hold-feature-reliability-low`" in report

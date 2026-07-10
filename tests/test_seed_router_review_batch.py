from __future__ import annotations

import csv
from pathlib import Path

from scripts.seed_router_review_batch import (
    build_review_item_payload,
    read_review_queue_csv,
)


def test_build_review_item_payload_maps_router_snapshot() -> None:
    row = {
        "sample_group": "cloud_later_all",
        "route": "cloud_later",
        "risk": "medium",
        "reason": "low_activity_batchable",
        "priority": "0.42",
        "clip_id": "clip-001",
        "camera_id": "cam-001",
        "started_at": "2026-07-03T12:48:41+00:00",
        "evidence_reliability": "medium",
        "motion_mean": "0.006",
        "motion_peak": "0.040",
        "active_motion_ratio": "0.13",
        "motion_burst_count": "2",
    }

    payload = build_review_item_payload(row, batch_id="router-eval-v1-20260710")

    assert payload == {
        "batch_id": "router-eval-v1-20260710",
        "clip_id": "clip-001",
        "sample_group": "cloud_later_all",
        "route": "cloud_later",
        "risk": "medium",
        "reason": "low_activity_batchable",
        "priority": 0.42,
        "camera_id": "cam-001",
        "started_at": "2026-07-03T12:48:41+00:00",
        "evidence_reliability": "medium",
        "motion_mean": 0.006,
        "motion_peak": 0.04,
        "active_motion_ratio": 0.13,
        "motion_burst_count": 2,
    }


def test_read_review_queue_csv_returns_payloads(tmp_path: Path) -> None:
    path = tmp_path / "queue.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "sample_group",
                "route",
                "risk",
                "reason",
                "priority",
                "clip_id",
                "camera_id",
                "started_at",
                "evidence_reliability",
                "motion_mean",
                "motion_peak",
                "active_motion_ratio",
                "motion_burst_count",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "sample_group": "review_candidate_quantiles",
                "route": "review_candidate",
                "risk": "medium",
                "reason": "feature_not_ready:missing_or_low_reliability",
                "priority": "0.78",
                "clip_id": "clip-002",
                "camera_id": "",
                "started_at": "2026-07-04T12:00:00+00:00",
                "evidence_reliability": "low",
                "motion_mean": "0",
                "motion_peak": "",
                "active_motion_ratio": "0",
                "motion_burst_count": "0",
            }
        )

    payloads = read_review_queue_csv(path, batch_id="batch-1")

    assert len(payloads) == 1
    assert payloads[0]["batch_id"] == "batch-1"
    assert payloads[0]["clip_id"] == "clip-002"
    assert payloads[0]["camera_id"] is None
    assert payloads[0]["motion_peak"] is None
    assert payloads[0]["motion_burst_count"] == 0

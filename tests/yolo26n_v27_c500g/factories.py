"""YOLO26n v2.7 preparation tests' deterministic, synthetic inputs."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any


ZERO_WRITES = {
    "db_write_count": 0,
    "r2_write_count": 0,
    "service_write_count": 0,
    "git_write_count": 0,
}
SHA_A = "a" * 64
SHA_B = "b" * 64


def valid_source(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "source_ref": "private/source/segment-001",
        "source_sha256": SHA_A,
        "anonymous_camera_digest": "cam-digest-01",
        "camera_night": "night-2026-08-20-a",
        "scheduled_start_utc": "2026-08-20T11:00:00Z",
        "duration_sec": 1800.0,
        "width": 2880,
        "height": 1620,
        "fps": 15.0,
        "codec": "hevc",
        "role": "v27_train",
    }
    value.update(overrides)
    return value


def inventory_7days() -> dict[str, object]:
    records: list[dict[str, object]] = []
    for day in range(1, 8):
        for camera in range(1, 4):
            records.append(
                valid_source(
                    source_ref=f"private/day-{day}/cam-{camera}",
                    source_sha256=hashlib.sha256(
                        f"day-{day}-cam-{camera}".encode("ascii")
                    ).hexdigest(),
                    anonymous_camera_digest=f"cam-digest-{camera:02d}",
                    camera_night=f"night-2026-08-{day + 19:02d}-{camera}",
                    scheduled_start_utc=f"2026-08-{day + 19:02d}T11:00:00Z",
                )
            )
    return {
        "schema": "yolo26n-v27-c500g-source-inventory-v1",
        "status": "V27_SOURCE_INVENTORY_READY",
        "test_sheet_sha256": SHA_A,
        "records": records,
        **ZERO_WRITES,
    }


def valid_v26_freeze() -> dict[str, object]:
    runs = [
        {"seed": seed, "initializer": initializer, "status": "completed"}
        for seed in (26, 27, 28)
        for initializer in ("warm-start", "clean-reference")
    ]
    return {
        "schema": "yolo26n-v26-teacher-freeze-v1",
        "status": "V26_TEACHER_FROZEN",
        "test_sheet_sha256": SHA_A,
        "freeze_cutoff_utc": "2026-08-19T11:00:00Z",
        "selected_checkpoint_sha256": SHA_B,
        "imgsz": 960,
        "raw_confidence": 0.001,
        "nms_iou": 0.7,
        "evaluation_threshold": 0.25,
        "temporal_fps": 10,
        "fixed_test_passed": True,
        "runs": runs,
        **ZERO_WRITES,
    }


def roles() -> dict[str, object]:
    rows = [
        {
            "source_ref": source["source_ref"],
            "source_sha256": source["source_sha256"],
            "anonymous_camera_digest": source["anonymous_camera_digest"],
            "camera_night": source["camera_night"],
            "role": source["role"],
        }
        for source in inventory_7days()["records"]
    ]
    return {
        "schema": "yolo26n-v27-c500g-role-freeze-v1",
        "status": "V27_ROLE_FREEZE_READY",
        "test_sheet_sha256": SHA_A,
        "rows": rows,
        **ZERO_WRITES,
    }


def roi_profile() -> dict[str, object]:
    rects = [
        {"x1": 0.02, "y1": 0.05, "x2": 0.31, "y2": 0.95},
        {"x1": 0.34, "y1": 0.05, "x2": 0.64, "y2": 0.95},
        {"x1": 0.67, "y1": 0.05, "x2": 0.98, "y2": 0.95},
    ]
    return {
        "schema": "yolo26n-v27-c500g-roi-profile-v1",
        "status": "V27_ROI_PROFILE_READY",
        "test_sheet_sha256": SHA_A,
        "profile_sha256": SHA_B,
        "frame_width": 2880,
        "frame_height": 1620,
        "padding_px": 12,
        "calibration_provenance": "v27_train",
        "day_verified": True,
        "ir_verified": True,
        "cameras": {
            f"cam-digest-{camera:02d}": {
                name: deepcopy(rect)
                for name, rect in zip(("left", "middle", "right"), rects, strict=True)
            }
            for camera in range(1, 4)
        },
        **ZERO_WRITES,
    }


def request(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "request_id": "request-0001",
        "source_ref": "private/source/segment-001",
        "source_sha256": SHA_A,
        "anonymous_camera_digest": "cam-digest-01",
        "camera_night": "night-2026-08-20-a",
        "enclosure_digest": "enclosure-digest-01-left",
        "roi_name": "left",
        "timestamp_ms": 60_000,
        "time_band": "20-22",
        "location_stratum": "central",
        "role": "v27_train",
        "roi_profile_sha256": SHA_B,
    }
    value.update(overrides)
    return value


def pilot_gt(*, fraction_large: float = 0.95, edge_rate: float = 0.02) -> dict[str, object]:
    return {
        "schema": "yolo26n-v27-c500g-human-gt-v1",
        "status": "HUMAN_GT_READY",
        "test_sheet_sha256": SHA_A,
        "roi_profile_sha256": SHA_B,
        "fraction_full_frame_short_side_ge_16px": fraction_large,
        "edge_issue_image_fraction": edge_rate,
        "items": [],
        **ZERO_WRITES,
    }


def contract() -> dict[str, object]:
    return {
        "schema": "yolo26n-v27-c500g-cvat-task-contract-v1",
        "status": "CVAT_CONTRACT_READY",
        "test_sheet_sha256": SHA_A,
        "queue_sha256": SHA_B,
        "status_labels": ["present", "absent", "uncertain", "media_error"],
        "rectangle_label": "gecko",
        **ZERO_WRITES,
    }


def queue() -> dict[str, object]:
    return {
        "schema": "yolo26n-v27-c500g-review-queue-v1",
        "status": "REVIEW_QUEUE_READY",
        "test_sheet_sha256": SHA_A,
        "items": [
            {
                "anonymous_sequence": "V27P0001",
                "image_name": "V27P0001.jpg",
                "image_sha256": SHA_B,
                "width": 900,
                "height": 1400,
            }
        ],
        **ZERO_WRITES,
    }


def lineage() -> dict[str, object]:
    return {
        "schema": "yolo26n-v27-c500g-private-lineage-v1",
        "status": "LINEAGE_READY",
        "test_sheet_sha256": SHA_A,
        "items": [
            {
                "anonymous_sequence": "V27P0001",
                "source_ref": "private/source/segment-001",
                "source_sha256": SHA_A,
                "timestamp_ms": 60_000,
                "roi_profile_sha256": SHA_B,
                "full_xy": [10.0, 20.0, 210.0, 320.0],
            }
        ],
        **ZERO_WRITES,
    }


def human_gt() -> dict[str, object]:
    return {
        "schema": "yolo26n-v27-c500g-human-gt-v1",
        "status": "HUMAN_GT_READY",
        "test_sheet_sha256": SHA_A,
        "items": [
            {
                "anonymous_sequence": "V27P0001",
                "status": "present",
                "boxes": [{"x1": 10.0, "y1": 20.0, "x2": 110.0, "y2": 120.0}],
                "revision": 1,
            }
        ],
        **ZERO_WRITES,
    }


def protected_ledgers() -> list[dict[str, object]]:
    return [
        {
            "schema": "yolo26n-protected-ledger-v1",
            "status": "PROTECTED",
            "test_sheet_sha256": SHA_A,
            "role": "v27_future_holdout",
            "source_sha256": [SHA_B],
            **ZERO_WRITES,
        }
    ]


def prediction_rows() -> list[dict[str, object]]:
    return [
        {
            "source_ref": "private/source/segment-001",
            "source_sha256": SHA_A,
            "camera_night": "night-2026-08-20-a",
            "role": "v27_train",
            "timestamp_ms": 60_000,
            "confidence": 0.93,
            "box": {"x1": 10.0, "y1": 20.0, "x2": 110.0, "y2": 120.0},
            "selection_reason": "base_gt_disagreement",
        }
    ]


def inputs_with_uncertain_sibling() -> dict[str, object]:
    value = human_gt()
    value["items"] = [
        {"anonymous_sequence": "V27P0001", "status": "present", "boxes": []},
        {"anonymous_sequence": "V27P0002", "status": "absent", "boxes": []},
        {"anonymous_sequence": "V27P0003", "status": "uncertain", "boxes": []},
    ]
    return value


def dataset_with_cross_role_night() -> dict[str, object]:
    return {
        "schema": "yolo26n-v27-c500g-dataset-v1",
        "status": "DATASET_BUILT_UNAUDITED",
        "test_sheet_sha256": SHA_A,
        "records": [
            {"sequence": "A", "camera_night": "same-night", "role": "v27_train"},
            {"sequence": "B", "camera_night": "same-night", "role": "v27_val"},
        ],
        **ZERO_WRITES,
    }


def inputs_with_mutated_replay(tmp_path: Path | None = None) -> dict[str, Any]:
    root = tmp_path or Path("synthetic-replay")
    return {
        "replay_root": root,
        "manifest_sha256": SHA_A,
        "expected_image_sha256": SHA_A,
        "actual_image_bytes": b"mutated replay bytes",
    }

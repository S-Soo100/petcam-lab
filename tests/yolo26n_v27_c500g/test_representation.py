"""Task 7 — 파일럿 GT 로 publication 표현(full_frame vs roi_3tile) 판정: 16px/95%/2% 사전 규칙."""
from __future__ import annotations

import hashlib

import pytest

from scripts.yolo26n_v27_c500g.representation import REPRESENTATION_SCHEMA, decide_representation
from tests.yolo26n_v27_c500g.factories import SHA_A, SHA_B, ZERO_WRITES

W, H = 2880, 1620
CROP = (300, 100, 1160, 1380)  # full_xy 860x1280 crop


def _gt(boxes_short_px: list[float], *, statuses: list[str] | None = None, edge_attr: int = 0, border: int = 0) -> tuple[dict, dict]:
    items, rows = [], []
    n = max(len(boxes_short_px), len(statuses or []))
    for i in range(n):
        seq = f"V27P{i + 1:04d}"
        status = (statuses[i] if statuses else "present")
        boxes = []
        if status == "present":
            s = boxes_short_px[i]
            x1 = 2.0 if i < border else 100.0
            boxes = [{"x1": x1, "y1": 200.0, "x2": x1 + s * 2, "y2": 200.0 + s}]
        items.append({"anonymous_sequence": seq, "status": status, "boxes": boxes, "revision": 2,
                      "attributes": {"edge_issue": "clipped" if i < edge_attr else "none"}, "cvat_frame": i,
                      "source_group_digest": hashlib.sha256(str(i // 3).encode()).hexdigest(), "full_frame_eligible": True})
        rows.append({"anonymous_sequence": seq, "full_xy": list(CROP), "roi_profile_sha256": SHA_B, "roi_name": "left",
                     "source_sha256": SHA_A, "timestamp_ms": 1000 * i})
    gt = {"schema": "yolo26n-v27-c500g-human-gt-v1", "status": "HUMAN_GT_READY", "test_sheet_sha256": SHA_A, "queue_sha256": SHA_B,
          "items": items, "summary": {}, **ZERO_WRITES}
    lineage = {"schema": "yolo26n-v27-c500g-private-lineage-v1", "status": "LINEAGE_READY", "test_sheet_sha256": SHA_A,
               "roi_profile_sha256": SHA_B, "items": rows, **ZERO_WRITES}
    return gt, lineage


def test_full_frame_requires_95_percent_boxes_at_least_16px_after_960_letterbox():
    # 960/2880 = 1/3 → 48px 원본 = 16px. 20개 중 19개 ≥48 → 0.95 통과
    gt, lineage = _gt([48.0] * 19 + [47.0])
    decision = decide_representation(gt, lineage, frame_width=W, frame_height=H)
    assert decision["schema"] == REPRESENTATION_SCHEMA and decision["mode"] == "full_frame" and decision["status"] == "REPRESENTATION_DECIDED"
    assert decision["metrics"]["fraction_ge_16px_full_frame"] == pytest.approx(0.95)
    gt, lineage = _gt([48.0] * 18 + [47.0, 47.0])
    assert decide_representation(gt, lineage, frame_width=W, frame_height=H)["mode"] == "roi_3tile"


def test_roi_3tile_fraction_uses_crop_letterbox_scale():
    gt, lineage = _gt([30.0] * 10)  # crop 860x1280 → scale 0.75 → 22.5px ≥ 16 ✓, full frame 10px ✗
    decision = decide_representation(gt, lineage, frame_width=W, frame_height=H)
    assert decision["metrics"]["fraction_ge_16px_roi_3tile"] == 1.0 and decision["metrics"]["fraction_ge_16px_full_frame"] == 0.0
    assert decision["mode"] == "roi_3tile"


def test_edge_rate_above_two_percent_requires_recalibration():
    gt, lineage = _gt([60.0] * 100, edge_attr=3)
    assert decide_representation(gt, lineage, frame_width=W, frame_height=H)["status"] == "ROI_RECALIBRATION_REQUIRED"
    gt, lineage = _gt([60.0] * 100, border=3)  # attribute 는 none 이지만 crop 테두리 접촉 3% → proxy 로도 잡는다
    decision = decide_representation(gt, lineage, frame_width=W, frame_height=H)
    assert decision["status"] == "ROI_RECALIBRATION_REQUIRED" and decision["metrics"]["edge_border_proxy_rate"] == pytest.approx(0.03)
    gt, lineage = _gt([60.0] * 100, border=2)
    assert decide_representation(gt, lineage, frame_width=W, frame_height=H)["status"] == "REPRESENTATION_DECIDED"


def test_decision_carries_negative_ratio_histogram_and_pins():
    gt, lineage = _gt([60.0] * 7 + [0.0] * 3, statuses=["present"] * 7 + ["absent"] * 3)
    decision = decide_representation(gt, lineage, frame_width=W, frame_height=H)
    m = decision["metrics"]
    assert m["status_counts"]["absent"] == 3 and m["negative_ratio"] == pytest.approx(0.3) and m["uncertain_media_error_ratio"] == 0.0
    assert m["box_count"] == 7 and sum(m["short_side_histogram_full_frame_px"].values()) == 7
    assert decision["roi_profile_sha256"] == SHA_B and decision["test_sheet_sha256"] == SHA_A and decision["imgsz"] == 960
    assert decision["negative_ratio_in_target"] is True  # 0.30–0.40
    gt2, lineage2 = _gt([60.0] * 9 + [0.0], statuses=["present"] * 9 + ["absent"])
    assert decide_representation(gt2, lineage2, frame_width=W, frame_height=H)["negative_ratio_in_target"] is False


def test_owner_decision_must_match_or_override_explicitly():
    gt, lineage = _gt([60.0] * 20)
    decision = decide_representation(gt, lineage, frame_width=W, frame_height=H, owner_decision="full_frame")
    assert decision["owner_decision"] == "full_frame" and decision["final_mode"] == "full_frame"
    with pytest.raises(ValueError, match="owner"):
        decide_representation(gt, lineage, frame_width=W, frame_height=H, owner_decision="roi_3tile")
    forced = decide_representation(gt, lineage, frame_width=W, frame_height=H, owner_decision="roi_3tile", override_reason="owner wants tiles")
    assert forced["final_mode"] == "roi_3tile" and forced["override_reason"] == "owner wants tiles"

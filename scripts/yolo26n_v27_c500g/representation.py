"""Task 7 — 파일럿 사람 GT 로 publication 표현을 판정한다 (사전 규칙 16px / 95% / 2%).

- full_frame: 원본(2880×1620) 한 장을 imgsz 로 letterbox → scale = min(imgsz/W, imgsz/H). 사람 박스 짧은 변 × scale ≥ 16px 인 비율이 95% 이상이면 통과.
- roi_3tile: 사육장 crop 한 장을 imgsz 로 → scale = min(imgsz/crop_w, imgsz/crop_h). 같은 규칙.
- edge: 사람 attribute `edge_issue != none` 이미지 비율과, crop 테두리(≤2px)에 닿은 박스 비율(자동 proxy) 중 큰 값이 2% 를 넘으면 ROI 재보정.
owner 결정이 계산 결과와 다르면 override_reason 없이는 거부한다(사후 threshold 변경 금지, 결정 근거는 남긴다).
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from scripts.yolo26n_v27_c500g.contracts import WRITE_COUNT_FIELDS

REPRESENTATION_SCHEMA = "yolo26n-v27-c500g-representation-decision-v1"
MIN_SHORT_PX = 16.0
MIN_FRACTION = 0.95
MAX_EDGE_RATE = 0.02
NEGATIVE_TARGET = (0.30, 0.40)
BORDER_TOUCH_PX = 2.0
HISTOGRAM_BINS: tuple[tuple[str, float, float | None], ...] = (
    ("<16", 0.0, 16.0), ("16-32", 16.0, 32.0), ("32-64", 32.0, 64.0), ("64-128", 64.0, 128.0), (">=128", 128.0, None),
)
MODES = ("full_frame", "roi_3tile")
_ZERO_WRITES = {field: 0 for field in WRITE_COUNT_FIELDS}


def _bin(value: float) -> str:
    for name, low, high in HISTOGRAM_BINS:
        if value >= low and (high is None or value < high):
            return name
    return HISTOGRAM_BINS[-1][0]


def decide_representation(
    pilot_gt: Mapping[str, object], lineage: Mapping[str, object], *, frame_width: int, frame_height: int, imgsz: int = 960,
    owner_decision: str | None = None, override_reason: str | None = None,
) -> dict[str, object]:
    if pilot_gt.get("schema") != "yolo26n-v27-c500g-human-gt-v1":
        raise ValueError("representation decision requires a human-gt-v1 pilot GT")
    if lineage.get("schema") != "yolo26n-v27-c500g-private-lineage-v1":
        raise ValueError("representation decision requires the private lineage of the pilot queue")
    lineage_by = {str(row["anonymous_sequence"]): row for row in lineage["items"]}  # type: ignore[index]
    scale_full = min(imgsz / frame_width, imgsz / frame_height)

    status_counts: Counter[str] = Counter({"present": 0, "absent": 0, "uncertain": 0, "media_error": 0})
    histogram: Counter[str] = Counter({name: 0 for name, _, _ in HISTOGRAM_BINS})
    box_count = ge16_full = ge16_tile = border_touch = 0
    edge_attr_images = 0
    items = list(pilot_gt["items"])  # type: ignore[arg-type]
    for item in items:
        status = str(item["status"])
        status_counts[status] += 1
        attributes = item.get("attributes") or {}
        if attributes.get("edge_issue") not in (None, "none"):
            edge_attr_images += 1
        row = lineage_by.get(str(item["anonymous_sequence"]))
        if row is None:
            raise ValueError(f"lineage has no row for {item['anonymous_sequence']}")
        x1, y1, x2, y2 = row["full_xy"]  # type: ignore[misc]
        crop_w, crop_h = float(x2 - x1), float(y2 - y1)
        scale_tile = min(imgsz / crop_w, imgsz / crop_h)
        for box in item["boxes"]:  # type: ignore[union-attr]
            short = min(float(box["x2"]) - float(box["x1"]), float(box["y2"]) - float(box["y1"]))
            box_count += 1
            ge16_full += short * scale_full >= MIN_SHORT_PX
            ge16_tile += short * scale_tile >= MIN_SHORT_PX
            histogram[_bin(short * scale_full)] += 1
            if (float(box["x1"]) <= BORDER_TOUCH_PX or float(box["y1"]) <= BORDER_TOUCH_PX
                    or float(box["x2"]) >= crop_w - BORDER_TOUCH_PX or float(box["y2"]) >= crop_h - BORDER_TOUCH_PX):
                border_touch += 1

    image_count = len(items)
    fraction_full = ge16_full / box_count if box_count else 0.0
    fraction_tile = ge16_tile / box_count if box_count else 0.0
    edge_attr_rate = edge_attr_images / image_count if image_count else 0.0
    border_rate = border_touch / box_count if box_count else 0.0
    edge_rate = max(edge_attr_rate, border_rate)
    negative_ratio = status_counts["absent"] / image_count if image_count else 0.0
    unsure_ratio = (status_counts["uncertain"] + status_counts["media_error"]) / image_count if image_count else 0.0

    mode = "full_frame" if fraction_full >= MIN_FRACTION else "roi_3tile"
    status = "ROI_RECALIBRATION_REQUIRED" if edge_rate > MAX_EDGE_RATE else "REPRESENTATION_DECIDED"
    final_mode = mode
    if owner_decision is not None:
        if owner_decision not in MODES:
            raise ValueError(f"owner decision must be one of {MODES}")
        if owner_decision != mode:
            if not override_reason:
                raise ValueError(f"owner decision {owner_decision} differs from the computed mode {mode}; pass override_reason to override")
            final_mode = owner_decision
    return {
        "schema": REPRESENTATION_SCHEMA, "status": status, "test_sheet_sha256": pilot_gt["test_sheet_sha256"],
        "roi_profile_sha256": lineage["roi_profile_sha256"], "queue_sha256": pilot_gt.get("queue_sha256"),
        "imgsz": imgsz, "frame": [frame_width, frame_height], "mode": mode, "final_mode": final_mode,
        "owner_decision": owner_decision, "override_reason": override_reason,
        "negative_ratio_in_target": NEGATIVE_TARGET[0] <= negative_ratio <= NEGATIVE_TARGET[1],
        "rules": {"min_short_px": MIN_SHORT_PX, "min_fraction": MIN_FRACTION, "max_edge_rate": MAX_EDGE_RATE, "negative_target": list(NEGATIVE_TARGET)},
        "metrics": {
            "image_count": image_count, "box_count": box_count, "status_counts": dict(status_counts),
            "fraction_ge_16px_full_frame": fraction_full, "fraction_ge_16px_roi_3tile": fraction_tile,
            "edge_issue_attribute_rate": edge_attr_rate, "edge_border_proxy_rate": border_rate, "edge_issue_rate": edge_rate,
            "negative_ratio": negative_ratio, "uncertain_media_error_ratio": unsure_ratio,
            "short_side_histogram_full_frame_px": dict(histogram),
        },
        **_ZERO_WRITES,
    }

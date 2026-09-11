"""Task 6 — CVAT 사람 판정 strict 정규화.

입력은 CVAT REST API 의 job annotation JSON (`/api/jobs/<id>/annotations` + `/api/jobs/<id>/data/meta` frames + labels) 을
로컬 inbox 로 받은 payload. 규칙(설계 §5·계획 Task 6):
- 이미지(frame)마다 status tag 정확히 1개(present|absent|uncertain|media_error). 미판정과 absent 는 다른 상태.
- present 는 gecko rectangle ≥1, 나머지는 0. rectangle 은 source=manual, rotation 0, 양수 면적, 이미지 경계 안.
- tag attribute 는 allowlist 값만. track 은 없어야 한다.
- 같은 timestamp 의 세 ROI(source group) 중 uncertain/media_error 가 하나라도 있으면 그 group 은 full-frame 발행 불가.
`audit_cvat_export` 는 위반을 모아 보고(진행 중 export 점검용), `normalize_cvat_export` 는 위반 0 일 때만 human-gt-v1 을 만든다.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath

from scripts.yolo26n_v27_c500g.contracts import WRITE_COUNT_FIELDS, Box, HumanBox

CONTRACT_SCHEMA = "yolo26n-v27-c500g-cvat-task-contract-v1"
HUMAN_GT_SCHEMA = "yolo26n-v27-c500g-human-gt-v1"
ADJUDICATION_SCHEMA = "yolo26n-v27-c500g-adjudication-queue-v1"
STATUS_LABELS: tuple[str, ...] = ("present", "absent", "uncertain", "media_error")
RECTANGLE_LABEL = "gecko"
STATUS_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "edge_issue": ("none", "clipped", "miss_suspected"),
    "lighting_state": ("ir", "color", "transition"),
    "occlusion_state": ("none", "partial", "heavy"),
    "hardcase_structure": ("none", "shed_skin", "feeder_insect", "human_hand", "reflection", "droplet", "mesh", "branch", "leaf",
                           "camera_body", "separator", "stationary_sleep"),
    "cross_enclosure_reflection": ("true", "false"),
}
IOU_DISAGREEMENT_THRESHOLD = 0.70
BOUNDS_TOLERANCE_PX = 0.5
_ZERO_WRITES = {field: 0 for field in WRITE_COUNT_FIELDS}


def queue_sha256(queue: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_cvat_contract(queue: Mapping[str, object]) -> dict[str, object]:
    """익명 큐 하나에 대한 CVAT 라벨 계약. owner 가 UI 로 만든 task 가 이 계약과 같은지 normalize 에서 대조한다."""
    if queue.get("schema") != "yolo26n-v27-c500g-review-queue-v1":
        raise ValueError("contract requires a review-queue-v1 manifest")
    items = queue.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("review queue has no items")
    return {
        "schema": CONTRACT_SCHEMA, "status": "CVAT_CONTRACT_READY", "test_sheet_sha256": queue["test_sheet_sha256"],
        "queue_sha256": queue_sha256(queue), "image_count": len(items), "status_labels": list(STATUS_LABELS),
        "rectangle_label": RECTANGLE_LABEL, "status_attributes": {k: list(v) for k, v in STATUS_ATTRIBUTES.items()},
        "iou_disagreement_threshold": IOU_DISAGREEMENT_THRESHOLD, **_ZERO_WRITES,
    }


def _sequence_from_frame_name(name: str) -> str:
    return PurePosixPath(str(name)).stem


def _label_index(export: Mapping[str, object]) -> tuple[dict[str, dict[str, object]], dict[int, dict[str, object]]]:
    labels = export.get("labels")
    if not isinstance(labels, list) or not labels:
        raise ValueError("labels: export has no label definitions")
    by_name: dict[str, dict[str, object]] = {}
    by_id: dict[int, dict[str, object]] = {}
    for label in labels:
        specs = {int(a["id"]): str(a["name"]) for a in label.get("attributes", [])}
        entry = {"id": int(label["id"]), "name": str(label["name"]), "type": str(label.get("type", "any")), "specs": specs}
        by_name[entry["name"]] = entry  # type: ignore[assignment]
        by_id[entry["id"]] = entry  # type: ignore[assignment]
    missing = [name for name in (*STATUS_LABELS, RECTANGLE_LABEL) if name not in by_name]
    if missing:
        raise ValueError(f"labels: task is missing contract labels {missing}")
    return by_name, by_id


def audit_cvat_export(
    contract: Mapping[str, object], queue: Mapping[str, object], lineage: Mapping[str, object], export: Mapping[str, object]
) -> dict[str, object]:
    """위반을 모아서 보고. 구조 자체가 안 맞으면(계약·라벨) ValueError, 프레임 단위 문제는 violations 로."""
    if contract.get("schema") != CONTRACT_SCHEMA or contract.get("queue_sha256") != queue_sha256(queue):
        raise ValueError("contract does not match the review queue (queue_sha256 differs)")
    if lineage.get("schema") != "yolo26n-v27-c500g-private-lineage-v1":
        raise ValueError("lineage: expected private-lineage-v1")
    frames = export.get("frames")
    annotations = export.get("annotations")
    if not isinstance(frames, list) or not isinstance(annotations, Mapping):
        raise ValueError("export must carry frames and annotations")
    by_name, by_id = _label_index(export)
    status_ids = {by_name[name]["id"]: name for name in STATUS_LABELS}
    rectangle_id = by_name[RECTANGLE_LABEL]["id"]

    queue_items = sorted(queue["items"], key=lambda item: str(item["anonymous_sequence"]))  # type: ignore[index]
    violations: list[dict[str, object]] = []

    def flag(index: int, sequence: str, kind: str, detail: str) -> None:
        violations.append({"cvat_frame": index, "anonymous_sequence": sequence, "kind": kind, "detail": detail})

    if len(frames) != len(queue_items):
        raise ValueError(f"frame count {len(frames)} differs from queue item count {len(queue_items)}")
    if annotations.get("tracks"):
        violations.append({"cvat_frame": None, "anonymous_sequence": None, "kind": "track", "detail": "track annotations are not allowed"})

    tags_by_frame: dict[int, list[Mapping[str, object]]] = defaultdict(list)
    for tag in annotations.get("tags", []):  # type: ignore[union-attr]
        tags_by_frame[int(tag["frame"])].append(tag)
    shapes_by_frame: dict[int, list[Mapping[str, object]]] = defaultdict(list)
    for shape in annotations.get("shapes", []):  # type: ignore[union-attr]
        shapes_by_frame[int(shape["frame"])].append(shape)

    per_frame: list[dict[str, object]] = []
    status_counts: Counter[str] = Counter({name: 0 for name in STATUS_LABELS})
    for index, (frame, item) in enumerate(zip(frames, queue_items, strict=True)):
        sequence = str(item["anonymous_sequence"])
        frame_violations_before = len(violations)
        if _sequence_from_frame_name(str(frame.get("name", ""))) != sequence:
            flag(index, sequence, "frame", f"frame name {frame.get('name')!r} is not queue item {sequence}")
        width, height = int(item["width"]), int(item["height"])
        if int(frame.get("width", -1)) != width or int(frame.get("height", -1)) != height:
            flag(index, sequence, "frame", "frame size differs from queue item size")

        status: str | None = None
        attributes: dict[str, str] = {}
        status_tags = [t for t in tags_by_frame.get(index, []) if int(t["label_id"]) in status_ids]
        for tag in tags_by_frame.get(index, []):
            if int(tag["label_id"]) not in status_ids:
                flag(index, sequence, "label", f"tag label {by_id.get(int(tag['label_id']), {}).get('name')} is not a status label")
        if len(status_tags) != 1:
            flag(index, sequence, "status tag", f"expected exactly 1 status tag, found {len(status_tags)}")
        else:
            tag = status_tags[0]
            status = status_ids[int(tag["label_id"])]
            status_counts[status] += 1
            if str(tag.get("source", "manual")) != "manual":
                flag(index, sequence, "manual", f"status tag source {tag.get('source')} is not manual")
            specs = by_id[int(tag["label_id"])]["specs"]  # type: ignore[index]
            for attribute in tag.get("attributes", []):
                name = specs.get(int(attribute["spec_id"]))  # type: ignore[union-attr]
                value = str(attribute.get("value"))
                if name not in STATUS_ATTRIBUTES or value not in STATUS_ATTRIBUTES[name]:
                    flag(index, sequence, "attribute", f"attribute {name}={value!r} is outside the allowlist")
                else:
                    attributes[name] = value

        boxes: list[Box] = []
        for shape in shapes_by_frame.get(index, []):
            label = by_id.get(int(shape["label_id"]), {}).get("name")
            if str(shape.get("type")) != "rectangle" or label != RECTANGLE_LABEL:
                flag(index, sequence, "rectangle", f"shape type={shape.get('type')} label={label} is not a gecko rectangle")
                continue
            if str(shape.get("source", "")) != "manual":
                flag(index, sequence, "manual", f"rectangle source {shape.get('source')} is not manual")
                continue
            if float(shape.get("rotation", 0.0) or 0.0) != 0.0:
                flag(index, sequence, "rotation", "rectangle rotation must be 0")
                continue
            points = [float(p) for p in shape.get("points", [])]
            if len(points) != 4:
                flag(index, sequence, "rectangle", "rectangle must have 4 point values")
                continue
            x1, y1, x2, y2 = min(points[0], points[2]), min(points[1], points[3]), max(points[0], points[2]), max(points[1], points[3])
            if x2 - x1 <= 0 or y2 - y1 <= 0:
                flag(index, sequence, "area", "rectangle must have positive area")
                continue
            tol = BOUNDS_TOLERANCE_PX
            if x1 < -tol or y1 < -tol or x2 > width + tol or y2 > height + tol:
                flag(index, sequence, "bounds", f"rectangle {[x1, y1, x2, y2]} leaves image bounds {width}x{height}")
                continue
            boxes.append(Box(max(0.0, x1), max(0.0, y1), min(float(width), x2), min(float(height), y2)))

        if status == "present" and not boxes:
            flag(index, sequence, "status/bbox", "present requires at least one gecko rectangle")
        elif status in ("absent", "uncertain", "media_error") and boxes:
            flag(index, sequence, "status/bbox", f"{status} must have no rectangles, found {len(boxes)}")

        per_frame.append({
            "cvat_frame": index, "anonymous_sequence": sequence, "status": status, "attributes": attributes,
            "boxes": boxes, "complete": len(violations) == frame_violations_before and status is not None,
        })

    return {
        "ok": not violations, "frames_total": len(per_frame), "frames_complete": sum(1 for f in per_frame if f["complete"]),
        "frames_missing_status": sum(1 for f in per_frame if f["status"] is None), "status_counts": dict(status_counts),
        "box_count": sum(len(f["boxes"]) for f in per_frame), "violations": violations, "cvat_job_id": _job_field(export, "id"),
        "_frames": per_frame,
    }


def _job_field(export: Mapping[str, object], field: str) -> object:
    job = export.get("job")
    return job.get(field) if isinstance(job, Mapping) else None


def _group_digest(row: Mapping[str, object]) -> str:
    return hashlib.sha256(f"{row['source_sha256']}|{row['timestamp_ms']}".encode("utf-8")).hexdigest()


def normalize_cvat_export(
    contract: Mapping[str, object], queue: Mapping[str, object], lineage: Mapping[str, object], export: Mapping[str, object]
) -> dict[str, object]:
    """위반 0 인 export 만 human-gt-v1 로. 첫 위반 kind 를 메시지 앞에 붙여 ValueError."""
    report = audit_cvat_export(contract, queue, lineage, export)
    if not report["ok"]:
        first = report["violations"][0]  # type: ignore[index]
        raise ValueError(f"{first['kind']}: {first['detail']} (frame {first['cvat_frame']}, {first['anonymous_sequence']})")
    lineage_by_sequence = {str(row["anonymous_sequence"]): row for row in lineage["items"]}  # type: ignore[index]
    frames: list[dict[str, object]] = report["_frames"]  # type: ignore[assignment]
    group_status: dict[str, list[str]] = defaultdict(list)
    for frame in frames:
        row = lineage_by_sequence.get(str(frame["anonymous_sequence"]))
        if row is None:
            raise ValueError(f"lineage has no row for {frame['anonymous_sequence']}")
        frame["group"] = _group_digest(row)
        group_status[frame["group"]].append(str(frame["status"]))  # type: ignore[index]
    eligible = {g for g, statuses in group_status.items() if all(s in ("present", "absent") for s in statuses)}

    items: list[dict[str, object]] = []
    for frame in frames:
        sequence = str(frame["anonymous_sequence"])
        boxes = [HumanBox(sequence, box).box.to_json() for box in frame["boxes"]]  # type: ignore[union-attr]
        items.append({
            "anonymous_sequence": sequence, "status": frame["status"], "boxes": boxes, "revision": 1,
            "attributes": frame["attributes"], "cvat_frame": frame["cvat_frame"], "source_group_digest": frame["group"],
            "full_frame_eligible": frame["group"] in eligible,
        })
    return {
        "schema": HUMAN_GT_SCHEMA, "status": "HUMAN_GT_READY", "test_sheet_sha256": contract["test_sheet_sha256"],
        "queue_sha256": contract["queue_sha256"], "cvat_job_id": report["cvat_job_id"], "cvat_task_id": _job_field(export, "task_id"),
        "items": items,
        "summary": {
            "status_counts": report["status_counts"], "box_count": report["box_count"],
            "source_groups": {"total": len(group_status), "full_frame_eligible": len(eligible),
                              "blocked_by_uncertain_or_media_error": len(group_status) - len(eligible)},
        },
        **_ZERO_WRITES,
    }


def iou(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    ix1, iy1 = max(a["x1"], b["x1"]), max(a["y1"], b["y1"])
    ix2, iy2 = min(a["x2"], b["x2"]), min(a["y2"], b["y2"])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a["x2"] - a["x1"]) * (a["y2"] - a["y1"]) + (b["x2"] - b["x1"]) * (b["y2"] - b["y1"]) - inter
    return inter / union if union > 0 else 0.0


def _min_matched_iou(primary: Sequence[Mapping[str, float]], secondary: Sequence[Mapping[str, float]]) -> float:
    remaining = list(secondary)
    worst = 1.0
    for box in primary:
        best_index = max(range(len(remaining)), key=lambda k: iou(box, remaining[k]))
        worst = min(worst, iou(box, remaining.pop(best_index)))
    return worst


def build_conflict_queue(
    primary: Mapping[str, object], secondary: Mapping[str, object], *, iou_threshold: float = IOU_DISAGREEMENT_THRESHOLD
) -> dict[str, object]:
    """이중검수(secondary)와 1차(primary)의 불일치: status 다름, 박스 수 다름, 매칭 IoU < threshold → adjudication."""
    for gt in (primary, secondary):
        if gt.get("schema") != HUMAN_GT_SCHEMA:
            raise ValueError("conflict queue requires human-gt-v1 inputs")
    primary_by = {str(i["anonymous_sequence"]): i for i in primary["items"]}  # type: ignore[index]
    items: list[dict[str, object]] = []
    compared = 0
    for second in secondary["items"]:  # type: ignore[index]
        sequence = str(second["anonymous_sequence"])
        first = primary_by.get(sequence)
        if first is None:
            raise ValueError(f"secondary item {sequence} is not in the primary GT")
        compared += 1
        reason: str | None = None
        min_iou: float | None = None
        if first["status"] != second["status"]:
            reason = "status"
        elif first["status"] == "present":
            if len(first["boxes"]) != len(second["boxes"]):  # type: ignore[arg-type]
                reason = "box_count"
            else:
                min_iou = _min_matched_iou(first["boxes"], second["boxes"])  # type: ignore[arg-type]
                if min_iou < iou_threshold:
                    reason = "iou"
        if reason is not None:
            items.append({
                "anonymous_sequence": sequence, "primary_status": first["status"], "secondary_status": second["status"],
                "primary_box_count": len(first["boxes"]), "secondary_box_count": len(second["boxes"]),  # type: ignore[arg-type]
                "min_iou": min_iou, "reason": reason,
            })
    return {
        "schema": ADJUDICATION_SCHEMA, "status": "ADJUDICATION_QUEUE_READY", "test_sheet_sha256": primary["test_sheet_sha256"],
        "iou_threshold": iou_threshold, "compared_count": compared, "conflict_count": len(items), "items": items, **_ZERO_WRITES,
    }

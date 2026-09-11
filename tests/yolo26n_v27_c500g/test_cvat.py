"""Task 6 — CVAT 사람 판정(status tag + gecko rectangle) strict 정규화, 감사(audit), 이중검수 불일치 큐."""
from __future__ import annotations

import hashlib
import json

import pytest

from scripts.yolo26n_v27_c500g.cvat import (
    ADJUDICATION_SCHEMA,
    CONTRACT_SCHEMA,
    HUMAN_GT_SCHEMA,
    audit_cvat_export,
    build_conflict_queue,
    build_cvat_contract,
    normalize_cvat_export,
)
from tests.yolo26n_v27_c500g.factories import SHA_A, SHA_B, ZERO_WRITES

W, H = 900, 1400
_attrs = [
    {"id": 21, "name": "edge_issue", "input_type": "select", "default_value": "none", "values": ["none", "clipped", "miss_suspected"]},
    {"id": 22, "name": "lighting_state", "input_type": "select", "default_value": "ir", "values": ["ir", "color", "transition"]},
    {"id": 23, "name": "occlusion_state", "input_type": "select", "default_value": "none", "values": ["none", "partial", "heavy"]},
    {"id": 24, "name": "hardcase_structure", "input_type": "select", "default_value": "none", "values": ["none", "shed_skin", "feeder_insect", "human_hand", "reflection", "droplet", "mesh", "branch", "leaf", "camera_body", "separator", "stationary_sleep"]},
    {"id": 25, "name": "cross_enclosure_reflection", "input_type": "checkbox", "default_value": "false", "values": ["false"]},
]
LABELS = [
    {"id": 24, "name": "present", "type": "tag", "attributes": _attrs},
    {"id": 25, "name": "absent", "type": "tag", "attributes": [{**a, "id": a["id"] + 5} for a in _attrs]},
    {"id": 26, "name": "uncertain", "type": "tag", "attributes": [{**a, "id": a["id"] + 10} for a in _attrs]},
    {"id": 27, "name": "media_error", "type": "tag", "attributes": [{**a, "id": a["id"] + 15} for a in _attrs]},
    {"id": 28, "name": "gecko", "type": "rectangle", "attributes": []},
]
LABEL_ID = {label["name"]: label["id"] for label in LABELS}


def _queue(n: int = 6, prefix: str = "P") -> dict[str, object]:
    items = [{"anonymous_sequence": f"V27{prefix}{i:04d}", "image_name": f"V27{prefix}{i:04d}.jpg",
              "image_sha256": hashlib.sha256(f"img{i}".encode()).hexdigest(), "width": W, "height": H} for i in range(1, n + 1)]
    return {"schema": "yolo26n-v27-c500g-review-queue-v1", "status": "REVIEW_QUEUE_READY", "test_sheet_sha256": SHA_A, "items": items, **ZERO_WRITES}


def _lineage(n: int = 6, prefix: str = "P") -> dict[str, object]:
    rows = []
    for i in range(1, n + 1):
        group = (i - 1) // 3  # 3 ROI = 1 timestamp
        rows.append({"anonymous_sequence": f"V27{prefix}{i:04d}", "request_id": f"req-{i}", "source_ref": f"recordings/cam01/night=2026-09-05/slot{group}",
                     "source_sha256": hashlib.sha256(f"src{group}".encode()).hexdigest(), "anonymous_camera_digest": "c" * 64, "camera_night": "n" * 64,
                     "enclosure_digest": "e" * 64, "roi_name": ["left", "middle", "right"][(i - 1) % 3], "timestamp_ms": 60_000 * (group + 1),
                     "time_band": "20-22", "location_stratum": "edge", "roi_profile_sha256": SHA_B, "full_xy": [0, 0, W, H],
                     "image_sha256": hashlib.sha256(f"img{i}".encode()).hexdigest(), "lighting_stratum": "ir"})
    return {"schema": "yolo26n-v27-c500g-private-lineage-v1", "status": "LINEAGE_READY", "test_sheet_sha256": SHA_A, "roi_profile_sha256": SHA_B, "items": rows, **ZERO_WRITES}


def _tag(frame: int, status: str, **attr_over: str) -> dict[str, object]:
    label = next(l for l in LABELS if l["name"] == status)
    attrs = [{"spec_id": a["id"], "value": attr_over.get(a["name"], a["default_value"])} for a in label["attributes"]]
    return {"id": 100 + frame, "frame": frame, "label_id": label["id"], "group": 0, "source": "manual", "attributes": attrs}


def _shape(frame: int, points=(100.0, 200.0, 300.0, 450.0), *, label="gecko", source="manual", rotation=0.0, kind="rectangle") -> dict[str, object]:
    return {"id": 500 + frame, "frame": frame, "label_id": LABEL_ID[label], "type": kind, "source": source, "rotation": rotation,
            "points": list(points), "occluded": False, "outside": False, "z_order": 0, "group": 0, "attributes": [], "elements": []}


def _export(tags, shapes, *, n: int = 6, prefix: str = "P", frames=None) -> dict[str, object]:
    frames = frames or [{"name": f"v27-c500g/V27{prefix}{i:04d}.jpg", "width": W, "height": H} for i in range(1, n + 1)]
    return {"source": "cvat-api-job-annotations", "cvat_version": "2.66.0", "job": {"id": 31, "task_id": 8, "stage": "annotation", "state": "in progress"},
            "frames": frames, "labels": LABELS, "annotations": {"version": 0, "tags": tags, "shapes": shapes, "tracks": [], "intervals": []}}


def _complete_export() -> dict[str, object]:
    # frames 0,1: present with box; 2: absent; 3: present; 4,5: absent
    tags = [_tag(0, "present"), _tag(1, "present"), _tag(2, "absent"), _tag(3, "present"), _tag(4, "absent"), _tag(5, "absent")]
    shapes = [_shape(0), _shape(1, (10.0, 10.0, 60.0, 90.0)), _shape(3, (400.0, 600.0, 700.0, 900.0))]
    return _export(tags, shapes)


@pytest.fixture
def contract():
    return build_cvat_contract(_queue())


def test_build_cvat_contract_pins_queue_sha_and_labels(contract):
    assert contract["schema"] == CONTRACT_SCHEMA and contract["status"] == "CVAT_CONTRACT_READY"
    assert contract["queue_sha256"] == hashlib.sha256(json.dumps(_queue(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert contract["status_labels"] == ["present", "absent", "uncertain", "media_error"] and contract["rectangle_label"] == "gecko"
    assert set(contract["status_attributes"]) == {"edge_issue", "lighting_state", "occlusion_state", "hardcase_structure", "cross_enclosure_reflection"}
    assert contract["image_count"] == 6 and contract["test_sheet_sha256"] == SHA_A


def test_normalize_happy_path_produces_human_gt(contract):
    gt = normalize_cvat_export(contract, _queue(), _lineage(), _complete_export())
    assert gt["schema"] == HUMAN_GT_SCHEMA and gt["status"] == "HUMAN_GT_READY"
    by = {i["anonymous_sequence"]: i for i in gt["items"]}
    assert len(by) == 6 and by["V27P0001"]["status"] == "present" and by["V27P0001"]["boxes"] == [{"x1": 100.0, "y1": 200.0, "x2": 300.0, "y2": 450.0}]
    assert by["V27P0003"]["status"] == "absent" and by["V27P0003"]["boxes"] == [] and by["V27P0003"]["revision"] == 1
    assert by["V27P0001"]["attributes"]["lighting_state"] == "ir"
    assert by["V27P0001"]["source_group_digest"] == by["V27P0003"]["source_group_digest"] != by["V27P0004"]["source_group_digest"]
    assert gt["summary"]["status_counts"] == {"present": 3, "absent": 3, "uncertain": 0, "media_error": 0}
    assert gt["summary"]["source_groups"] == {"total": 2, "full_frame_eligible": 2, "blocked_by_uncertain_or_media_error": 0}
    assert gt["cvat_job_id"] == 31 and "recordings/" not in json.dumps(gt)


@pytest.mark.parametrize("status,box_count", [("present", 0), ("absent", 1), ("uncertain", 1), ("media_error", 2)])
def test_status_box_mismatch_is_rejected(contract, status, box_count):
    tags = [_tag(i, "absent") for i in range(6)]
    tags[0] = _tag(0, status)
    shapes = [_shape(0, (10.0 + 50 * k, 10.0, 60.0 + 50 * k, 90.0)) for k in range(box_count)]
    for k, s in enumerate(shapes):
        s["id"] = 900 + k
    with pytest.raises(ValueError, match="status/bbox"):
        normalize_cvat_export(contract, _queue(), _lineage(), _export(tags, shapes))


def test_missing_or_duplicate_status_tag_is_rejected(contract):
    export = _complete_export()
    export["annotations"]["tags"].pop()  # frame 5 without tag
    with pytest.raises(ValueError, match="status tag"):
        normalize_cvat_export(contract, _queue(), _lineage(), export)
    export = _complete_export()
    export["annotations"]["tags"].append({**_tag(2, "uncertain"), "id": 999})
    with pytest.raises(ValueError, match="status tag"):
        normalize_cvat_export(contract, _queue(), _lineage(), export)


@pytest.mark.parametrize(
    "mutation,message",
    [
        (lambda s: s.update(source="auto"), "manual"),
        (lambda s: s.update(rotation=12.5), "rotation"),
        (lambda s: s.update(points=[100.0, 200.0, 100.0, 450.0]), "area"),
        (lambda s: s.update(points=[-5.0, 200.0, 300.0, 1500.0]), "bounds"),
        (lambda s: s.update(type="polygon", points=[1.0, 1.0, 5.0, 1.0, 5.0, 5.0]), "rectangle"),
        (lambda s: s.update(label_id=LABEL_ID["present"]), "rectangle"),
    ],
)
def test_bad_rectangles_are_rejected(contract, mutation, message):
    export = _complete_export()
    mutation(export["annotations"]["shapes"][0])
    with pytest.raises(ValueError, match=message):
        normalize_cvat_export(contract, _queue(), _lineage(), export)


def test_unknown_attribute_value_or_track_is_rejected(contract):
    export = _complete_export()
    export["annotations"]["tags"][0]["attributes"][0]["value"] = "somewhere"
    with pytest.raises(ValueError, match="attribute"):
        normalize_cvat_export(contract, _queue(), _lineage(), export)
    export = _complete_export()
    export["annotations"]["tracks"] = [{"id": 1}]
    with pytest.raises(ValueError, match="track"):
        normalize_cvat_export(contract, _queue(), _lineage(), export)


def test_frame_or_queue_mismatch_is_rejected(contract):
    export = _complete_export()
    export["frames"][2]["name"] = "v27-c500g/V27P0099.jpg"
    with pytest.raises(ValueError, match="frame"):
        normalize_cvat_export(contract, _queue(), _lineage(), export)
    export = _complete_export()
    export["frames"][0]["width"] = W - 1
    with pytest.raises(ValueError, match="frame"):
        normalize_cvat_export(contract, _queue(), _lineage(), export)
    other = build_cvat_contract(_queue(n=5))
    with pytest.raises(ValueError, match="contract"):
        normalize_cvat_export(other, _queue(), _lineage(), _complete_export())


def test_sibling_uncertain_blocks_full_frame_group(contract):
    export = _complete_export()
    export["annotations"]["tags"][2] = _tag(2, "uncertain")  # group 0 의 한 ROI 가 uncertain
    gt = normalize_cvat_export(contract, _queue(), _lineage(), export)
    assert gt["summary"]["source_groups"] == {"total": 2, "full_frame_eligible": 1, "blocked_by_uncertain_or_media_error": 1}
    blocked = {i["anonymous_sequence"] for i in gt["items"] if not i["full_frame_eligible"]}
    assert blocked == {"V27P0001", "V27P0002", "V27P0003"}


def test_audit_reports_progress_without_raising(contract):
    export = _complete_export()
    export["annotations"]["tags"].pop()  # frame 5 미판정
    export["annotations"]["shapes"].append(_shape(2, (1.0, 1.0, 50.0, 50.0)))  # absent 인데 박스
    report = audit_cvat_export(contract, _queue(), _lineage(), export)
    assert report["frames_total"] == 6 and report["frames_complete"] == 4
    kinds = {v["kind"] for v in report["violations"]}
    assert kinds == {"status tag", "status/bbox"}
    assert {v["anonymous_sequence"] for v in report["violations"]} == {"V27P0006", "V27P0003"}
    assert report["ok"] is False and report["status_counts"]["present"] == 3


def test_build_conflict_queue_flags_status_count_and_iou_disagreements(contract):
    primary = normalize_cvat_export(contract, _queue(), _lineage(), _complete_export())
    secondary_export = _complete_export()
    secondary_export["annotations"]["tags"][2] = _tag(2, "present")  # status 불일치 (absent → present)
    secondary_export["annotations"]["shapes"].append(_shape(2, (10.0, 10.0, 80.0, 80.0)))
    secondary_export["annotations"]["shapes"][1]["points"] = [10.0, 10.0, 60.0, 90.0]  # 동일 → 일치
    secondary_export["annotations"]["shapes"][2]["points"] = [400.0, 600.0, 500.0, 700.0]  # IoU 낮음
    secondary = normalize_cvat_export(contract, _queue(), _lineage(), secondary_export)
    queue = build_conflict_queue(primary, secondary)
    assert queue["schema"] == ADJUDICATION_SCHEMA and queue["status"] == "ADJUDICATION_QUEUE_READY"
    reasons = {i["anonymous_sequence"]: i["reason"] for i in queue["items"]}
    assert reasons == {"V27P0003": "status", "V27P0004": "iou"}
    assert queue["compared_count"] == 6 and queue["conflict_count"] == 2
    assert next(i for i in queue["items"] if i["anonymous_sequence"] == "V27P0004")["min_iou"] < 0.70

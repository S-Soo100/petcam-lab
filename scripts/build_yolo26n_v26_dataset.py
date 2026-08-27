"""Build the deterministic recent-cohort split for YOLO26n v2.6."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.build_yolo26n_owner_dataset_v24 import (
    _decode_size,
    _rename_exclusive,
    _validate_yolo_label,
    _write_new,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DHASH64 = re.compile(r"^[0-9a-f]{16}$")
_FINAL_GT_SHA_FIELDS = (
    "primary_export_sha256",
    "double_review_export_sha256",
    "adjudication_export_sha256",
    "adjudication_index_sha256",
    "review_index_sha256",
    "selection_sha256",
)
_FINAL_GT_KEYS = frozenset({"schema", "status", "records", *_FINAL_GT_SHA_FIELDS})
_PRODUCTION_DECISION_SOURCE_COUNTS = {"primary": 2487, "adjudication": 21}
_PRODUCTION_STRATA = {
    "coverage": 858,
    "uncertainty": 900,
    "hard-negative-candidate": 350,
    "iid-random": 400,
}


class _DisjointSet:
    def __init__(self, values: Sequence[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("source window started_at malformed")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("source window started_at must be timezone-aware")
    return parsed


def _strict_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} malformed")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} malformed")
    return result


def _episode_id(clip_refs: Sequence[str]) -> str:
    return hashlib.sha256("\0".join(sorted(clip_refs)).encode()).hexdigest()[:24]


def _component_rank(seed: str, episodes: Sequence[str]) -> str:
    return hashlib.sha256(f"{seed}\0{'\0'.join(sorted(episodes))}".encode()).hexdigest()


def _validate_bbox(box: object, width: int, height: int) -> list[float]:
    if not isinstance(box, list) or len(box) != 4:
        raise ValueError("bbox malformed")
    x1, y1, x2, y2 = (_strict_number(value, "bbox") for value in box)
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("bbox out of bounds")
    return [x1, y1, x2, y2]


def _normalize_gt_records(
    final_gt: Mapping[str, object],
    *,
    expected_recent_count: int,
    minimum_absent_count: int,
    minimum_absent_fraction: float,
    expected_decision_source_counts: Mapping[str, int],
    expected_strata: Mapping[str, int],
) -> list[dict[str, object]]:
    records = final_gt.get("records")
    if (
        set(final_gt) != _FINAL_GT_KEYS
        or final_gt.get("schema") != "yolo26n-v26-final-human-gt-v1"
        or final_gt.get("status") != "V26_HUMAN_GT_VALIDATED"
        or not isinstance(records, list)
        or len(records) != expected_recent_count
    ):
        raise ValueError("final human GT contract mismatch")
    if any(
        not isinstance(final_gt.get(field), str)
        or _SHA256.fullmatch(str(final_gt[field])) is None
        for field in _FINAL_GT_SHA_FIELDS
    ):
        raise ValueError("final human GT provenance SHA malformed")
    normalized: list[dict[str, object]] = []
    image_shas: set[str] = set()
    blind_filenames: set[str] = set()
    for raw in records:
        if not isinstance(raw, Mapping):
            raise ValueError("human GT record malformed")
        image_sha = raw.get("image_sha256")
        blind_filename = raw.get("blind_filename")
        clip_ref = raw.get("clip_ref")
        camera_night = raw.get("camera_night")
        decision = raw.get("decision")
        tags = raw.get("tags")
        width = raw.get("width")
        height = raw.get("height")
        timestamp_ms = raw.get("timestamp_ms")
        boxes = raw.get("boxes")
        decision_source = raw.get("decision_source")
        stratum = raw.get("stratum")
        if (
            not isinstance(image_sha, str)
            or _SHA256.fullmatch(image_sha) is None
            or image_sha in image_shas
            or not isinstance(blind_filename, str)
            or not blind_filename.endswith(".jpg")
            or "/" in blind_filename
            or blind_filename in blind_filenames
            or not isinstance(clip_ref, str)
            or not clip_ref
            or not isinstance(camera_night, str)
            or not camera_night
            or decision not in {"present", "absent"}
            or tags != []
            or type(width) is not int
            or type(height) is not int
            or width <= 0
            or height <= 0
            or type(timestamp_ms) is not int
            or timestamp_ms < 0
            or not isinstance(boxes, list)
        ):
            raise ValueError("human GT record malformed")
        if decision_source not in expected_decision_source_counts:
            raise ValueError("human GT decision source malformed")
        if stratum not in expected_strata:
            raise ValueError("human GT stratum malformed")
        normalized_boxes = [_validate_bbox(box, width, height) for box in boxes]
        if decision == "present" and not normalized_boxes:
            raise ValueError("present record requires bbox")
        if decision == "absent" and normalized_boxes:
            raise ValueError("absent record cannot contain bbox")
        image_shas.add(image_sha)
        blind_filenames.add(blind_filename)
        normalized.append(
            {
                "blind_filename": blind_filename,
                "boxes": normalized_boxes,
                "camera_night": camera_night,
                "clip_ref": clip_ref,
                "decision": decision,
                "decision_source": decision_source,
                "height": height,
                "image_sha256": image_sha,
                "stratum": stratum,
                "timestamp_ms": timestamp_ms,
                "width": width,
            }
        )
    decision_counts = Counter(str(row["decision_source"]) for row in normalized)
    if decision_counts != Counter(expected_decision_source_counts):
        raise ValueError("human GT decision source counts mismatch")
    strata_counts = Counter(str(row["stratum"]) for row in normalized)
    if strata_counts != Counter(expected_strata):
        raise ValueError("human GT strata counts mismatch")
    absent_count = sum(row["decision"] == "absent" for row in normalized)
    if absent_count < minimum_absent_count:
        raise ValueError("human GT absent minimum not met")
    if absent_count / len(normalized) < minimum_absent_fraction:
        raise ValueError("human GT absent fraction not met")
    absent_by_night = Counter(
        str(row["camera_night"]) for row in normalized if row["decision"] == "absent"
    )
    if any(absent_by_night[str(row["camera_night"])] == 0 for row in normalized):
        raise ValueError("every camera-night must include absent GT")
    return normalized


def verify_final_gt_artifacts(
    final_gt: Mapping[str, object], artifacts: Mapping[str, Path]
) -> None:
    """Verify the six immutable QA artifacts named by the final GT."""
    if set(artifacts) != set(_FINAL_GT_SHA_FIELDS):
        raise ValueError("final human GT artifact set mismatch")
    for field in _FINAL_GT_SHA_FIELDS:
        expected = final_gt.get(field)
        path = artifacts[field]
        if not isinstance(expected, str) or _SHA256.fullmatch(expected) is None:
            raise ValueError(f"{field} malformed")
        if not path.is_file():
            raise ValueError(f"{field} artifact SHA mismatch")
        if field == "selection_sha256":
            try:
                selection = json.loads(path.read_bytes())
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError("selection_sha256 artifact SHA mismatch") from error
            if (
                not isinstance(selection, Mapping)
                or selection.get("selection_sha256") != expected
                or _canonical_sha(
                    {
                        key: value
                        for key, value in selection.items()
                        if key != "selection_sha256"
                    }
                )
                != expected
            ):
                raise ValueError("selection_sha256 artifact SHA mismatch")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"{field} artifact SHA mismatch")


def _load_cvat_annotations(path: Path) -> dict[str, dict[str, object]]:
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None or archive.namelist() != ["annotations.xml"]:
                raise ValueError("CVAT export archive contract mismatch")
            root = ET.fromstring(archive.read("annotations.xml"))
    except (OSError, zipfile.BadZipFile, ET.ParseError) as error:
        raise ValueError("CVAT export parse failed") from error
    if root.tag != "annotations":
        raise ValueError("CVAT annotations root malformed")
    result: dict[str, dict[str, object]] = {}
    for image in root.findall("image"):
        raw_filename = image.get("name")
        filename = Path(raw_filename).name if isinstance(raw_filename, str) else None
        try:
            width = int(image.get("width", ""))
            height = int(image.get("height", ""))
        except ValueError as error:
            raise ValueError("CVAT image dimensions malformed") from error
        if (
            not isinstance(filename, str)
            or not filename
            or not isinstance(raw_filename, str)
            or Path(raw_filename).is_absolute()
            or ".." in Path(raw_filename).parts
            or filename in result
            or width <= 0
            or height <= 0
        ):
            raise ValueError("CVAT image record malformed")
        boxes: list[list[float]] = []
        for child in image:
            if child.tag != "box" or child.get("label") != "gecko":
                raise ValueError("CVAT annotation type malformed")
            try:
                box = [
                    float(str(child.get(name)))
                    for name in ("xtl", "ytl", "xbr", "ybr")
                ]
            except ValueError as error:
                raise ValueError("CVAT box coordinates malformed") from error
            if any(not math.isfinite(value) for value in box):
                raise ValueError("CVAT box coordinates malformed")
            boxes.append(list(_validate_bbox(box, width, height)))
        result[filename] = {
            "decision": "present" if boxes else "absent",
            "boxes": boxes,
            "width": width,
            "height": height,
        }
    if not result:
        raise ValueError("CVAT export has no images")
    return result


def _json_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} parse failed") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} root malformed")
    return value


def _max_bbox_iou(left: object, right: object) -> float:
    if not isinstance(left, list) or not isinstance(right, list):
        return 0.0
    maximum = 0.0
    for a in left:
        for b in right:
            if not isinstance(a, list) or not isinstance(b, list) or len(a) != 4 or len(b) != 4:
                continue
            intersection = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
                0.0, min(a[3], b[3]) - max(a[1], b[1])
            )
            union = (
                (a[2] - a[0]) * (a[3] - a[1])
                + (b[2] - b[0]) * (b[3] - b[1])
                - intersection
            )
            maximum = max(maximum, intersection / union if union > 0 else 0.0)
    return maximum


def _validate_dense_replacement(
    row: Mapping[str, object],
    *,
    dense_completion: Mapping[str, object] | None,
    dense_ledger_root: Path | None,
) -> None:
    if dense_completion is None or dense_ledger_root is None:
        raise ValueError("decode replacement requires dense provenance")
    clips = dense_completion.get("clips")
    if not isinstance(clips, list):
        raise ValueError("decode replacement dense completion malformed")
    private_ref = row.get("private_ref")
    clip_ref = row.get("clip_ref")
    matches = [
        raw
        for raw in clips
        if isinstance(raw, Mapping)
        and raw.get("private_ref") == private_ref
        and raw.get("clip_ref") == clip_ref
    ]
    if len(matches) != 1 or not isinstance(private_ref, str):
        raise ValueError("decode replacement dense clip lineage mismatch")
    ledger = dense_ledger_root / "clips" / private_ref / "ledger.jsonl"
    if (
        not ledger.is_file()
        or hashlib.sha256(ledger.read_bytes()).hexdigest()
        != matches[0].get("ledger_sha256")
    ):
        raise ValueError("decode replacement dense ledger SHA mismatch")
    found = 0
    with ledger.open(encoding="utf-8") as handle:
        for line in handle:
            raw = json.loads(line)
            if raw.get("image_sha256") != row.get("image_sha256"):
                continue
            if (
                raw.get("clip_ref") != clip_ref
                or raw.get("frame_index") != row.get("frame_index")
                or raw.get("timestamp_ms") != row.get("timestamp_ms")
            ):
                raise ValueError("decode replacement dense row lineage mismatch")
            found += 1
    if found != 1:
        raise ValueError("decode replacement dense row missing or duplicated")


def validate_final_gt_semantics(
    final_gt: Mapping[str, object],
    artifacts: Mapping[str, Path],
    *,
    dense_completion: Mapping[str, object] | None = None,
    dense_ledger_root: Path | None = None,
) -> None:
    """Rebuild final decisions from immutable CVAT exports and review indices."""
    verify_final_gt_artifacts(final_gt, artifacts)
    primary = _load_cvat_annotations(artifacts["primary_export_sha256"])
    double = _load_cvat_annotations(artifacts["double_review_export_sha256"])
    adjudicated = _load_cvat_annotations(artifacts["adjudication_export_sha256"])
    review = _json_object(artifacts["review_index_sha256"], "review index")
    selection = _json_object(artifacts["selection_sha256"], "selection")
    adjudication_index = _json_object(
        artifacts["adjudication_index_sha256"], "adjudication index"
    )
    selection_sha = selection.get("selection_sha256")
    if (
        not isinstance(selection_sha, str)
        or _SHA256.fullmatch(selection_sha) is None
        or _canonical_sha(
            {key: value for key, value in selection.items() if key != "selection_sha256"}
        )
        != selection_sha
        or review.get("selection_sha256") != selection_sha
    ):
        raise ValueError("selection/review index lineage mismatch")
    review_records = review.get("records")
    if not isinstance(review_records, list):
        raise ValueError("review index records malformed")
    primary_index: dict[str, Mapping[str, object]] = {}
    double_index: dict[str, Mapping[str, object]] = {}
    for raw in review_records:
        if not isinstance(raw, Mapping):
            raise ValueError("review index record malformed")
        round_name = raw.get("review_round")
        filename_key = "blind_filename" if round_name == "primary" else "review_filename"
        filename = raw.get(filename_key)
        target = primary_index if round_name == "primary" else double_index
        if (
            round_name not in {"primary", "double-review"}
            or not isinstance(filename, str)
            or not filename
            or filename in target
        ):
            raise ValueError("review index filename malformed")
        target[filename] = raw
    if (
        review.get("primary_count") != len(primary_index)
        or review.get("double_review_count") != len(double_index)
        or set(primary) != set(primary_index)
        or set(double) != set(double_index)
    ):
        raise ValueError("CVAT/review index count or filename mismatch")
    selection_records = selection.get("records")
    if not isinstance(selection_records, list):
        raise ValueError("selection records malformed")
    selection_by_sha = {
        str(raw.get("image_sha256")): raw
        for raw in selection_records
        if isinstance(raw, Mapping)
    }
    if (
        len(selection_by_sha) != len(selection_records)
        or len(selection_by_sha) != len(primary_index)
    ):
        raise ValueError("selection unique image count mismatch")
    selection_original_by_current: dict[str, str] = {}
    seen_original_shas: set[str] = set()
    for raw in primary_index.values():
        current_sha = raw.get("image_sha256")
        original_sha = raw.get("selection_image_sha256", current_sha)
        reason = raw.get("materialization_reason")
        selection_row = selection_by_sha.get(str(original_sha))
        if (
            not isinstance(current_sha, str)
            or _SHA256.fullmatch(current_sha) is None
            or not isinstance(original_sha, str)
            or _SHA256.fullmatch(original_sha) is None
            or original_sha in seen_original_shas
            or not isinstance(selection_row, Mapping)
            or any(
                raw.get(key) != selection_row.get(key)
                for key in ("clip_ref", "private_ref", "stratum", "double_review")
            )
        ):
            raise ValueError("selection/review image lineage mismatch")
        if reason in {None, "selected"}:
            if (
                current_sha != original_sha
                or raw.get("timestamp_ms") != selection_row.get("timestamp_ms")
                or raw.get("reasons") != selection_row.get("reasons")
            ):
                raise ValueError("selection/review image lineage mismatch")
        elif reason == "decode-replacement":
            expected_reasons = list(selection_row.get("reasons", [])) + [
                "decode-replacement"
            ]
            if current_sha == original_sha or raw.get("reasons") != expected_reasons:
                raise ValueError("selection/review image lineage mismatch")
            _validate_dense_replacement(
                raw,
                dense_completion=dense_completion,
                dense_ledger_root=dense_ledger_root,
            )
        else:
            raise ValueError("selection/review image lineage mismatch")
        if current_sha in selection_original_by_current:
            raise ValueError("selection/review image lineage mismatch")
        selection_original_by_current[current_sha] = original_sha
        seen_original_shas.add(original_sha)
    if seen_original_shas != set(selection_by_sha):
        raise ValueError("selection/review image lineage mismatch")
    actual_double_shas = [str(raw.get("image_sha256")) for raw in double_index.values()]
    expected_double_shas = {
        current_sha
        for current_sha, original_sha in selection_original_by_current.items()
        if selection_by_sha[original_sha].get("double_review") is True
    }
    if (
        len(actual_double_shas) != len(set(actual_double_shas))
        or set(actual_double_shas) != expected_double_shas
    ):
        raise ValueError("double-review selection set mismatch")
    adjudication_records = adjudication_index.get("records")
    final_records = final_gt.get("records")
    if not isinstance(adjudication_records, list) or not isinstance(final_records, list):
        raise ValueError("adjudication/final records malformed")
    if (
        adjudication_index.get("schema")
        != "yolo26n-v26-human-gt-adjudication-v1"
        or adjudication_index.get("count") != len(adjudication_records)
        or adjudication_index.get("selection_sha256") != selection_sha
        or adjudication_index.get("source_primary_export_sha256")
        != hashlib.sha256(artifacts["primary_export_sha256"].read_bytes()).hexdigest()
        or adjudication_index.get("source_double_review_export_sha256")
        != hashlib.sha256(
            artifacts["double_review_export_sha256"].read_bytes()
        ).hexdigest()
    ):
        raise ValueError("adjudication index lineage/count mismatch")
    adjudication_by_sha: dict[str, Mapping[str, object]] = {}
    seen_adjudication_filenames: set[str] = set()
    for raw in adjudication_records:
        if not isinstance(raw, Mapping):
            raise ValueError("adjudication index record malformed")
        image_sha = raw.get("image_sha256")
        primary_filename = raw.get("primary_filename")
        double_filename = raw.get("double_review_filename")
        adjudication_filename = raw.get("adjudication_filename")
        reasons = raw.get("reasons")
        if (
            not isinstance(image_sha, str)
            or _SHA256.fullmatch(image_sha) is None
            or image_sha in adjudication_by_sha
            or not isinstance(adjudication_filename, str)
            or adjudication_filename in seen_adjudication_filenames
            or primary_filename not in primary_index
            or double_filename not in double_index
            or adjudication_filename not in adjudicated
            or primary_index[str(primary_filename)].get("image_sha256") != image_sha
            or double_index[str(double_filename)].get("image_sha256") != image_sha
            or image_sha not in selection_original_by_current
            or not isinstance(reasons, list)
            or len(reasons) != 1
            or reasons[0] not in {"presence-disagreement", "bbox-iou-below-0.5"}
        ):
            raise ValueError("adjudication index filename/unique/reason mismatch")
        first = primary[str(primary_filename)]
        second = double[str(double_filename)]
        if reasons[0] == "presence-disagreement":
            valid_reason = first["decision"] != second["decision"]
        else:
            valid_reason = (
                first["decision"] == second["decision"] == "present"
                and _max_bbox_iou(first["boxes"], second["boxes"]) < 0.5
            )
        if not valid_reason:
            raise ValueError("adjudication reason does not match annotations")
        adjudication_by_sha[image_sha] = raw
        seen_adjudication_filenames.add(adjudication_filename)
    primary_filename_by_sha = {
        str(raw.get("image_sha256")): filename
        for filename, raw in primary_index.items()
    }
    computed_conflicts: set[str] = set()
    for double_filename, raw in double_index.items():
        image_sha = raw.get("image_sha256")
        primary_filename = primary_filename_by_sha.get(str(image_sha))
        if primary_filename is None:
            raise ValueError("double-review image lineage mismatch")
        first = primary[primary_filename]
        second = double[double_filename]
        if first["decision"] != second["decision"] or (
            first["decision"] == second["decision"] == "present"
            and _max_bbox_iou(first["boxes"], second["boxes"]) < 0.5
        ):
            computed_conflicts.add(str(image_sha))
    if computed_conflicts != set(adjudication_by_sha):
        raise ValueError("adjudication conflict set mismatch")
    if set(seen_adjudication_filenames) != set(adjudicated):
        raise ValueError("adjudication unique filenames mismatch")
    final_by_sha = {
        str(raw.get("image_sha256")): raw
        for raw in final_records
        if isinstance(raw, Mapping)
    }
    primary_by_sha = {
        str(raw.get("image_sha256")): filename
        for filename, raw in primary_index.items()
    }
    if (
        len(final_by_sha) != len(final_records)
        or set(final_by_sha) != set(primary_by_sha)
        or sum(raw.get("decision_source") == "adjudication" for raw in final_records)
        != len(adjudication_by_sha)
    ):
        raise ValueError("final GT semantic record set mismatch")
    for image_sha, final in final_by_sha.items():
        adjudication_row = adjudication_by_sha.get(image_sha)
        if adjudication_row is None:
            rebuilt = primary[primary_by_sha[image_sha]]
            source = "primary"
        else:
            rebuilt = adjudicated[str(adjudication_row["adjudication_filename"])]
            source = "adjudication"
        expected = {
            "decision": rebuilt["decision"],
            "boxes": rebuilt["boxes"],
            "width": rebuilt["width"],
            "height": rebuilt["height"],
            "decision_source": source,
        }
        if any(final.get(key) != value for key, value in expected.items()):
            raise ValueError("final GT semantic mismatch")
def _validate_selection_manifest(
    selection: Mapping[str, object],
    *,
    expected_recent_count: int,
    expected_dense_clip_count: int,
    expected_double_review_count: int,
    expected_strata: Mapping[str, int],
    enriched_completion_sha256: str,
) -> str:
    records = selection.get("records")
    aggregate = selection.get("aggregate")
    selection_sha = selection.get("selection_sha256")
    payload = {key: value for key, value in selection.items() if key != "selection_sha256"}
    if selection.get("dense_lineage_sha256") != enriched_completion_sha256:
        raise ValueError("selection enriched completion SHA mismatch")
    if (
        selection.get("schema") != "yolo26n-v26-recent-dense-selection-v1"
        or selection.get("status") != "SELECTION_FROZEN"
        or not isinstance(selection_sha, str)
        or _SHA256.fullmatch(selection_sha) is None
        or _canonical_sha(payload) != selection_sha
        or not isinstance(records, list)
        or len(records) != expected_recent_count
        or not isinstance(aggregate, Mapping)
        or aggregate.get("unique_image_count") != expected_recent_count
        or aggregate.get("review_task_count")
        != expected_recent_count + expected_double_review_count
        or aggregate.get("double_review_count") != expected_double_review_count
        or aggregate.get("clip_count") != expected_dense_clip_count
        or aggregate.get("strata_counts") != dict(expected_strata)
        or Counter(
            str(row.get("stratum")) for row in records if isinstance(row, Mapping)
        )
        != Counter(expected_strata)
        or sum(
            raw.get("double_review") is True
            for raw in records
            if isinstance(raw, Mapping)
        )
        != expected_double_review_count
    ):
        raise ValueError("selection manifest contract mismatch")
    return selection_sha


def _validate_enriched_completion(
    enriched_completion: Mapping[str, object],
    dense_completion: Mapping[str, object],
    *,
    expected_dense_clip_count: int,
    dense_completion_sha256: str,
) -> None:
    clips = enriched_completion.get("clips")
    dense_clips = dense_completion.get("clips")
    if enriched_completion.get("dense_completion_sha256") != dense_completion_sha256:
        raise ValueError("enriched completion dense completion SHA mismatch")
    if (
        enriched_completion.get("status") != "GME_JOIN_COMPLETE"
        or enriched_completion.get("clip_count") != expected_dense_clip_count
        or not isinstance(clips, list)
        or len(clips) != expected_dense_clip_count
        or not isinstance(dense_clips, list)
    ):
        raise ValueError("enriched completion contract mismatch")
    enriched_by_ref: dict[str, Mapping[str, object]] = {}
    row_count = 0
    for raw in clips:
        if not isinstance(raw, Mapping):
            raise ValueError("enriched completion clip malformed")
        clip_ref = raw.get("clip_ref")
        private_ref = raw.get("private_ref")
        rows = raw.get("row_count")
        if (
            not isinstance(clip_ref, str)
            or not clip_ref
            or clip_ref in enriched_by_ref
            or not isinstance(private_ref, str)
            or not private_ref
            or type(rows) is not int
            or rows <= 0
        ):
            raise ValueError("enriched completion clip malformed")
        enriched_by_ref[clip_ref] = raw
        row_count += rows
    dense_by_ref = {
        str(raw.get("clip_ref")): raw
        for raw in dense_clips
        if isinstance(raw, Mapping)
    }
    if (
        len(dense_by_ref) != len(dense_clips)
        or set(enriched_by_ref) != set(dense_by_ref)
        or any(
            enriched_by_ref[clip_ref].get("private_ref")
            != dense_by_ref[clip_ref].get("private_ref")
            for clip_ref in enriched_by_ref
        )
        or enriched_completion.get("row_count") != row_count
        or dense_completion.get("sampled_frame_count") != row_count
    ):
        raise ValueError("enriched completion lineage mismatch")


def _review_index_by_sha(
    review_index: Mapping[str, object],
    gt_records: Sequence[Mapping[str, object]],
    *,
    selection_sha256: str,
    expected_double_review_count: int,
) -> dict[str, Mapping[str, object]]:
    records = review_index.get("records")
    if (
        review_index.get("schema") != "yolo26n-v26-blind-review-index-v1"
        or review_index.get("selection_sha256") != selection_sha256
        or review_index.get("primary_count") != len(gt_records)
        or review_index.get("double_review_count") != expected_double_review_count
        or not isinstance(records, list)
    ):
        raise ValueError("review index contract mismatch")
    primary_records = [
        raw
        for raw in records
        if isinstance(raw, Mapping) and raw.get("review_round") == "primary"
    ]
    double_records = [
        raw
        for raw in records
        if isinstance(raw, Mapping) and raw.get("review_round") == "double-review"
    ]
    if (
        len(primary_records) != len(gt_records)
        or len(double_records) != expected_double_review_count
        or len(primary_records) + len(double_records) != len(records)
    ):
        raise ValueError("review index count mismatch")
    by_sha: dict[str, Mapping[str, object]] = {}
    for raw in primary_records:
        image_sha = raw.get("image_sha256")
        dhash = raw.get("historical_dhash64")
        if (
            not isinstance(image_sha, str)
            or _SHA256.fullmatch(image_sha) is None
            or image_sha in by_sha
            or not isinstance(dhash, str)
            or _DHASH64.fullmatch(dhash) is None
        ):
            raise ValueError("review index record malformed")
        by_sha[image_sha] = {**raw, "dhash64": dhash}
    gt_by_sha = {str(row["image_sha256"]): row for row in gt_records}
    if set(by_sha) != set(gt_by_sha):
        raise ValueError("review index does not match final GT")
    for image_sha, raw in by_sha.items():
        gt = gt_by_sha[image_sha]
        lineage_keys = ("blind_filename", "clip_ref", "timestamp_ms", "stratum")
        if any(raw.get(key) != gt[key] for key in lineage_keys):
            raise ValueError("review index lineage does not match final GT")
    return by_sha


def _dense_source_sha_by_clip(
    source_window: Mapping[str, object],
    dense_completion: Mapping[str, object],
    *,
    expected_dense_clip_count: int,
    source_window_sha256: str,
) -> dict[str, str]:
    sources = source_window.get("sources")
    aggregate = source_window.get("aggregate")
    clips = dense_completion.get("clips")
    if not isinstance(sources, list) or not isinstance(aggregate, Mapping):
        raise ValueError("source window contract mismatch")
    available_refs: set[str] = set()
    seen_refs: set[str] = set()
    for raw in sources:
        if not isinstance(raw, Mapping):
            raise ValueError("source window record malformed")
        clip_ref = raw.get("clip_id")
        if not isinstance(clip_ref, str) or not clip_ref or clip_ref in seen_refs:
            raise ValueError("source window clip malformed")
        object_status = raw.get("object_status", "available")
        if object_status not in {"available", "missing"}:
            raise ValueError("source window object status malformed")
        seen_refs.add(clip_ref)
        if object_status == "available":
            available_refs.add(clip_ref)
    if (
        aggregate.get("accessible_clip_count") != expected_dense_clip_count
        or len(available_refs) != expected_dense_clip_count
    ):
        raise ValueError("source window accessible count mismatch")
    if dense_completion.get("status") != "DENSE_EXTRACTION_COMPLETE":
        raise ValueError("dense completion status mismatch")
    if dense_completion.get("source_manifest_sha256") != source_window_sha256:
        raise ValueError("dense completion source manifest SHA mismatch")
    source_lineage_sha = source_window.get("lineage_sha256")
    if (
        not isinstance(source_lineage_sha, str)
        or _SHA256.fullmatch(source_lineage_sha) is None
        or dense_completion.get("source_lineage_sha256") != source_lineage_sha
    ):
        raise ValueError("dense completion source lineage mismatch")
    if (
        dense_completion.get("clip_count") != expected_dense_clip_count
        or not isinstance(clips, list)
        or len(clips) != expected_dense_clip_count
    ):
        raise ValueError("dense completion count mismatch")
    result: dict[str, str] = {}
    sampled_total = 0
    private_refs: set[str] = set()
    for raw in clips:
        if not isinstance(raw, Mapping):
            raise ValueError("dense completion clip malformed")
        clip_ref = raw.get("clip_ref")
        private_ref = raw.get("private_ref")
        source_sha = raw.get("source_sha256")
        ledger_sha = raw.get("ledger_sha256")
        sampled = raw.get("sampled_frame_count")
        if (
            not isinstance(clip_ref, str)
            or not clip_ref
            or clip_ref in result
            or not isinstance(private_ref, str)
            or not private_ref
            or private_ref in private_refs
            or not isinstance(source_sha, str)
            or _SHA256.fullmatch(source_sha) is None
            or not isinstance(ledger_sha, str)
            or _SHA256.fullmatch(ledger_sha) is None
            or type(sampled) is not int
            or sampled <= 0
        ):
            raise ValueError("dense completion clip malformed")
        result[clip_ref] = source_sha
        private_refs.add(private_ref)
        sampled_total += sampled
    if set(result) != available_refs:
        raise ValueError("dense completion source set mismatch")
    if dense_completion.get("sampled_frame_count") != sampled_total:
        raise ValueError("dense completion sampled count mismatch")
    return result


def _episode_by_clip(
    source_window: Mapping[str, object], gt_records: Sequence[Mapping[str, object]]
) -> tuple[dict[str, str], dict[str, int]]:
    sources = source_window.get("sources")
    if not isinstance(sources, list):
        raise ValueError("source window contract mismatch")
    needed = {str(row["clip_ref"]) for row in gt_records}
    by_camera_night: dict[str, list[tuple[datetime, datetime, str]]] = defaultdict(list)
    seen: set[str] = set()
    started_ms_by_clip: dict[str, int] = {}
    for raw in sources:
        if not isinstance(raw, Mapping):
            raise ValueError("source window record malformed")
        clip_ref = raw.get("clip_id")
        if clip_ref not in needed:
            continue
        if not isinstance(clip_ref, str) or clip_ref in seen:
            raise ValueError("source window clip malformed")
        camera_id = raw.get("camera_id")
        if not isinstance(camera_id, str) or not camera_id:
            raise ValueError("source window camera malformed")
        started = _parse_datetime(raw.get("started_at"))
        duration = _strict_number(raw.get("duration_sec"), "source duration")
        if duration <= 0:
            raise ValueError("source duration malformed")
        camera_night = f"{camera_id}:{started.astimezone().date().isoformat()}"
        by_camera_night[camera_night].append(
            (started, started + timedelta(seconds=duration), clip_ref)
        )
        started_ms_by_clip[clip_ref] = int(started.timestamp() * 1000)
        seen.add(clip_ref)
    if seen != needed:
        raise ValueError("source window is missing reviewed clip")
    gt_night_by_clip = {str(row["clip_ref"]): str(row["camera_night"]) for row in gt_records}
    result: dict[str, str] = {}
    for camera_night, clips in by_camera_night.items():
        clips.sort()
        current_refs: list[str] = []
        current_end: datetime | None = None
        groups: list[list[str]] = []
        for started, ended, clip_ref in clips:
            if gt_night_by_clip[clip_ref] != camera_night:
                raise ValueError("source window camera-night mismatch")
            if current_end is None or started > current_end + timedelta(seconds=60):
                if current_refs:
                    groups.append(current_refs)
                current_refs = [clip_ref]
                current_end = ended
            else:
                current_refs.append(clip_ref)
                current_end = max(current_end, ended)
        if current_refs:
            groups.append(current_refs)
        for refs in groups:
            episode = _episode_id(refs)
            for clip_ref in refs:
                result[clip_ref] = episode
    return result, started_ms_by_clip


def _split_components(
    records: Sequence[Mapping[str, object]],
    review_by_sha: Mapping[str, Mapping[str, object]],
    episode_by_clip: Mapping[str, str],
    started_ms_by_clip: Mapping[str, int],
    source_sha_by_clip: Mapping[str, str],
    *,
    seed: str,
    validation_fraction: float,
) -> dict[str, str]:
    episodes = sorted(set(episode_by_clip.values()))
    dsu = _DisjointSet(episodes)
    episodes_by_source_sha: dict[str, set[str]] = defaultdict(set)
    for clip_ref, episode in episode_by_clip.items():
        episodes_by_source_sha[source_sha_by_clip[clip_ref]].add(episode)
    for source_episodes in episodes_by_source_sha.values():
        first, *rest = sorted(source_episodes)
        for episode in rest:
            dsu.union(first, episode)
    rows = [
        (
            episode_by_clip[str(row["clip_ref"])],
            int(str(review_by_sha[str(row["image_sha256"])]["dhash64"]), 16),
            str(row["camera_night"]),
            started_ms_by_clip[str(row["clip_ref"])] + int(row["timestamp_ms"]),
        )
        for row in records
    ]
    for index, (left_episode, left_hash, left_night, left_time) in enumerate(rows):
        for right_episode, right_hash, right_night, right_time in rows[index + 1 :]:
            if (
                left_episode != right_episode
                and left_night == right_night
                and abs(left_time - right_time) <= 5 * 60 * 1000
                and (left_hash ^ right_hash).bit_count() <= 8
            ):
                dsu.union(left_episode, right_episode)
    episodes_by_component: dict[str, set[str]] = defaultdict(set)
    for episode in episodes:
        episodes_by_component[dsu.find(episode)].add(episode)
    counts_by_component: dict[str, Counter[str]] = defaultdict(Counter)
    for row in records:
        episode = episode_by_clip[str(row["clip_ref"])]
        counts_by_component[dsu.find(episode)][str(row["camera_night"])] += 1
    total_by_night = Counter(str(row["camera_night"]) for row in records)
    target = {night: total * validation_fraction for night, total in total_by_night.items()}
    val_counts: Counter[str] = Counter()
    split_by_component = {component: "train" for component in episodes_by_component}
    ranked = sorted(
        episodes_by_component,
        key=lambda component: _component_rank(seed, sorted(episodes_by_component[component])),
    )
    for component in ranked:
        before = sum(abs(val_counts[night] - target[night]) for night in total_by_night)
        after = sum(
            abs(val_counts[night] + counts_by_component[component][night] - target[night])
            for night in total_by_night
        )
        if after < before:
            split_by_component[component] = "val"
            val_counts.update(counts_by_component[component])
    for night in sorted(total_by_night):
        candidates = [component for component in ranked if counts_by_component[component][night]]
        if len(candidates) < 2:
            raise ValueError("camera-night has fewer than two leakage groups")
        if not any(split_by_component[component] == "val" for component in candidates):
            chosen = min(
                candidates,
                key=lambda component: (
                    abs(val_counts[night] + counts_by_component[component][night] - target[night]),
                    _component_rank(seed, sorted(episodes_by_component[component])),
                ),
            )
            split_by_component[chosen] = "val"
            val_counts.update(counts_by_component[chosen])
        if all(split_by_component[component] == "val" for component in candidates):
            chosen = min(
                candidates,
                key=lambda component: (
                    abs(val_counts[night] - counts_by_component[component][night] - target[night]),
                    _component_rank(seed, sorted(episodes_by_component[component])),
                ),
            )
            split_by_component[chosen] = "train"
            val_counts.subtract(counts_by_component[chosen])
    return {
        episode: split_by_component[dsu.find(episode)]
        for episode in episodes
    }


def build_recent_split_plan(
    final_gt: Mapping[str, object],
    review_index: Mapping[str, object],
    source_window: Mapping[str, object],
    dense_completion: Mapping[str, object],
    *,
    selection_manifest: Mapping[str, object],
    source_window_sha256: str,
    dense_completion_sha256: str,
    enriched_completion: Mapping[str, object],
    enriched_completion_sha256: str,
    expected_recent_count: int = 2508,
    expected_dense_clip_count: int = 429,
    expected_double_review_count: int = 200,
    minimum_absent_count: int = 700,
    minimum_absent_fraction: float = 0.35,
    expected_decision_source_counts: Mapping[str, int] | None = None,
    expected_strata: Mapping[str, int] | None = None,
    validation_fraction: float = 0.2,
    seed: str = "26",
) -> dict[str, object]:
    """Validate final human GT and produce a leakage-safe deterministic split."""
    if type(expected_recent_count) is not int or expected_recent_count <= 0:
        raise ValueError("expected recent count malformed")
    if type(expected_dense_clip_count) is not int or expected_dense_clip_count <= 0:
        raise ValueError("expected dense clip count malformed")
    if type(expected_double_review_count) is not int or expected_double_review_count < 0:
        raise ValueError("expected double-review count malformed")
    if type(minimum_absent_count) is not int or minimum_absent_count < 1:
        raise ValueError("minimum absent count malformed")
    if (
        isinstance(minimum_absent_fraction, bool)
        or not isinstance(minimum_absent_fraction, (int, float))
        or not 0 < float(minimum_absent_fraction) <= 1
    ):
        raise ValueError("minimum absent fraction malformed")
    for name, digest in (
        ("source window", source_window_sha256),
        ("dense completion", dense_completion_sha256),
        ("enriched completion", enriched_completion_sha256),
    ):
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise ValueError(f"{name} SHA malformed")
    if not 0 < validation_fraction < 1:
        raise ValueError("validation fraction malformed")
    decision_source_counts = dict(
        expected_decision_source_counts or _PRODUCTION_DECISION_SOURCE_COUNTS
    )
    strata = dict(expected_strata or _PRODUCTION_STRATA)
    if any(
        not isinstance(key, str)
        or not key
        or type(value) is not int
        or value < 0
        for counts in (decision_source_counts, strata)
        for key, value in counts.items()
    ):
        raise ValueError("expected GT counts malformed")
    if sum(decision_source_counts.values()) != expected_recent_count:
        raise ValueError("expected decision source counts malformed")
    if sum(strata.values()) != expected_recent_count:
        raise ValueError("expected strata counts malformed")
    gt_records = _normalize_gt_records(
        final_gt,
        expected_recent_count=expected_recent_count,
        minimum_absent_count=minimum_absent_count,
        minimum_absent_fraction=float(minimum_absent_fraction),
        expected_decision_source_counts=decision_source_counts,
        expected_strata=strata,
    )
    selection_sha = _validate_selection_manifest(
        selection_manifest,
        expected_recent_count=expected_recent_count,
        expected_dense_clip_count=expected_dense_clip_count,
        expected_double_review_count=expected_double_review_count,
        expected_strata=strata,
        enriched_completion_sha256=enriched_completion_sha256,
    )
    reviewed = _review_index_by_sha(
        review_index,
        gt_records,
        selection_sha256=selection_sha,
        expected_double_review_count=expected_double_review_count,
    )
    source_sha_by_clip = _dense_source_sha_by_clip(
        source_window,
        dense_completion,
        expected_dense_clip_count=expected_dense_clip_count,
        source_window_sha256=source_window_sha256,
    )
    _validate_enriched_completion(
        enriched_completion,
        dense_completion,
        expected_dense_clip_count=expected_dense_clip_count,
        dense_completion_sha256=dense_completion_sha256,
    )
    episode_by_clip, started_ms_by_clip = _episode_by_clip(source_window, gt_records)
    split_by_episode = _split_components(
        gt_records,
        reviewed,
        episode_by_clip,
        started_ms_by_clip,
        source_sha_by_clip,
        seed=seed,
        validation_fraction=validation_fraction,
    )
    recent_records: list[dict[str, object]] = []
    for row in gt_records:
        image_sha = str(row["image_sha256"])
        episode = episode_by_clip[str(row["clip_ref"])]
        recent_records.append(
            {
                **row,
                "dhash64": reviewed[image_sha]["dhash64"],
                "episode_id": episode,
                "source_sha256": source_sha_by_clip[str(row["clip_ref"])],
                "absolute_timestamp_ms": started_ms_by_clip[str(row["clip_ref"])] + int(row["timestamp_ms"]),
                "split": split_by_episode[episode],
            }
        )
    recent_records.sort(key=lambda row: (str(row["split"]), str(row["image_sha256"])))
    split_counts = Counter(str(row["split"]) for row in recent_records)
    camera_night_counts: dict[str, dict[str, int]] = {}
    for night in sorted({str(row["camera_night"]) for row in recent_records}):
        camera_night_counts[night] = dict(
            Counter(str(row["split"]) for row in recent_records if row["camera_night"] == night)
        )
    cross_split_dhash = 0
    train_rows = [row for row in recent_records if row["split"] == "train"]
    val_rows = [row for row in recent_records if row["split"] == "val"]
    for train in train_rows:
        train_hash = int(str(train["dhash64"]), 16)
        for val in val_rows:
            if (
                train["camera_night"] == val["camera_night"]
                and abs(int(train["absolute_timestamp_ms"]) - int(val["absolute_timestamp_ms"])) <= 5 * 60 * 1000
                and (train_hash ^ int(str(val["dhash64"]), 16)).bit_count() <= 8
            ):
                cross_split_dhash += 1
    if cross_split_dhash:
        raise ValueError("cross-split dHash leakage")
    splits_by_source_sha: dict[str, set[str]] = defaultdict(set)
    for row in recent_records:
        splits_by_source_sha[str(row["source_sha256"])].add(str(row["split"]))
    cross_split_source_sha = sum(
        len(splits) > 1 for splits in splits_by_source_sha.values()
    )
    if cross_split_source_sha:
        raise ValueError("cross-split source SHA leakage")
    return {
        "schema": "yolo26n-v26-recent-split-plan-v1",
        "status": "V26_RECENT_SPLIT_READY",
        "seed": seed,
        "validation_fraction": validation_fraction,
        "recent_image_count": len(recent_records),
        "recent_positive_count": sum(row["decision"] == "present" for row in recent_records),
        "recent_negative_count": sum(row["decision"] == "absent" for row in recent_records),
        "recent_box_count": sum(len(row["boxes"]) for row in recent_records),
        "final_gt_provenance_sha256": {
            field: final_gt[field] for field in _FINAL_GT_SHA_FIELDS
        },
        "source_window_sha256": source_window_sha256,
        "dense_completion_sha256": dense_completion_sha256,
        "enriched_completion_sha256": enriched_completion_sha256,
        "review_index_sha256": final_gt["review_index_sha256"],
        "selection_file_sha256": final_gt["selection_sha256"],
        "selection_lineage_sha256": selection_sha,
        "recent_split_counts": dict(split_counts),
        "camera_night_split_counts": camera_night_counts,
        "episode_count": len(set(episode_by_clip.values())),
        "cross_split_dhash_leq8_count": cross_split_dhash,
        "cross_split_source_sha256_count": cross_split_source_sha,
        "dhash_leakage_scope": "same-camera-night-within-5-minutes",
        "recent_records": recent_records,
    }


def _label_text(boxes: object, width: int, height: int) -> str:
    if not isinstance(boxes, list):
        raise ValueError("bbox list malformed")
    lines = []
    for box in boxes:
        x1, y1, x2, y2 = _validate_bbox(box, width, height)
        lines.append(
            "0 "
            f"{((x1 + x2) / 2) / width:.9f} "
            f"{((y1 + y2) / 2) / height:.9f} "
            f"{(x2 - x1) / width:.9f} "
            f"{(y2 - y1) / height:.9f}"
        )
    return "\n".join(lines) + ("\n" if lines else "")


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _repository_head() -> str:
    completed = subprocess.run(
        ["git", "-C", str(Path(__file__).resolve().parent.parent), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    value = completed.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("repository HEAD malformed")
    return value


def materialize_v26_dataset(
    *,
    parent_dataset: Path,
    parent_manifest: Mapping[str, object],
    parent_integrity_manifest: Mapping[str, object],
    recent_split_plan: Mapping[str, object],
    recent_zip: Path,
    output_dir: Path,
    expected_parent_splits: Mapping[str, int] | None = None,
) -> dict[str, object]:
    """Materialize v2.5 train replay + recent train/val, preserving old tests separately."""
    if output_dir.exists():
        raise FileExistsError(output_dir)
    parent_splits = dict(expected_parent_splits or {"train": 1659, "val": 153, "test": 151})
    parent_records = parent_manifest.get("records")
    parent_val_test_sha = parent_manifest.get("parent_val_test_sha256")
    if (
        parent_manifest.get("schema") != "yolo26n-owner-dataset-v25"
        or parent_manifest.get("status") != "V25_DATASET_READY"
        or parent_manifest.get("split_counts") != parent_splits
        or parent_manifest.get("image_count") != sum(parent_splits.values())
        or not isinstance(parent_records, list)
        or Counter(str(row.get("split")) for row in parent_records if isinstance(row, Mapping))
        != Counter(parent_splits)
        or not isinstance(parent_val_test_sha, str)
        or _SHA256.fullmatch(parent_val_test_sha) is None
    ):
        raise ValueError("v2.5 parent dataset contract mismatch")
    integrity_records = parent_integrity_manifest.get("records")
    if (
        parent_integrity_manifest.get("schema")
        != "yolo26n-v25-parent-integrity-v1"
        or parent_integrity_manifest.get("status")
        != "V25_PARENT_INTEGRITY_APPROVED"
        or parent_integrity_manifest.get("parent_manifest_sha256")
        != _canonical_sha(parent_manifest)
        or parent_integrity_manifest.get("parent_val_test_sha256")
        != parent_val_test_sha
        or parent_integrity_manifest.get("image_count") != len(parent_records)
        or parent_integrity_manifest.get("split_counts") != parent_splits
        or parent_integrity_manifest.get("records_sha256")
        != _canonical_sha(integrity_records)
        or not isinstance(integrity_records, list)
        or len(integrity_records) != len(parent_records)
    ):
        raise ValueError("v2.5 parent integrity manifest contract mismatch")
    integrity_by_sequence: dict[str, Mapping[str, object]] = {}
    for raw in integrity_records:
        if not isinstance(raw, Mapping):
            raise ValueError("parent integrity record malformed")
        sequence = raw.get("sequence")
        if (
            not isinstance(sequence, str)
            or not sequence
            or sequence in integrity_by_sequence
            or raw.get("split") not in parent_splits
            or not isinstance(raw.get("image_path"), str)
            or not isinstance(raw.get("label_path"), str)
            or not isinstance(raw.get("image_sha256"), str)
            or _SHA256.fullmatch(str(raw.get("image_sha256"))) is None
            or not isinstance(raw.get("label_sha256"), str)
            or _SHA256.fullmatch(str(raw.get("label_sha256"))) is None
            or type(raw.get("box_count")) is not int
            or int(raw.get("box_count")) < 0
        ):
            raise ValueError("parent integrity record malformed")
        integrity_by_sequence[sequence] = raw
    recent_records = recent_split_plan.get("recent_records")
    if (
        recent_split_plan.get("schema") != "yolo26n-v26-recent-split-plan-v1"
        or recent_split_plan.get("status") != "V26_RECENT_SPLIT_READY"
        or not isinstance(recent_records, list)
        or recent_split_plan.get("recent_image_count") != len(recent_records)
        or Counter(str(row.get("split")) for row in recent_records if isinstance(row, Mapping))
        != Counter(recent_split_plan.get("recent_split_counts"))
    ):
        raise ValueError("recent split plan contract mismatch")
    output_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.staging-", dir=output_dir.parent))
    materialized: list[dict[str, object]] = []
    seen_image_shas: set[str] = set()
    parent_manifest_sha = _canonical_sha(parent_manifest)
    try:
        val_test_digest = hashlib.sha256()
        for raw in parent_records:
            if not isinstance(raw, Mapping):
                raise ValueError("parent record malformed")
            split = raw.get("split")
            if split not in parent_splits:
                raise ValueError("parent split malformed")
            image_sha = raw.get("image_sha256")
            sequence = raw.get("sequence")
            approved = integrity_by_sequence.get(str(sequence))
            if (
                not isinstance(image_sha, str)
                or _SHA256.fullmatch(image_sha) is None
                or image_sha in seen_image_shas
                or approved is None
                or any(
                    approved.get(key) != raw.get(key)
                    for key in (
                        "sequence",
                        "split",
                        "image_path",
                        "label_path",
                        "image_sha256",
                        "box_count",
                    )
                )
            ):
                raise ValueError("parent integrity record mismatch")
            source_image = parent_dataset / str(raw.get("image_path"))
            source_label = parent_dataset / str(raw.get("label_path"))
            image_payload = source_image.read_bytes()
            label_payload = source_label.read_bytes()
            if hashlib.sha256(image_payload).hexdigest() != image_sha:
                raise ValueError("parent source bytes changed")
            label_sha = hashlib.sha256(label_payload).hexdigest()
            if label_sha != approved.get("label_sha256"):
                raise ValueError("parent integrity label SHA mismatch")
            declared_label_sha = raw.get("label_sha256")
            if declared_label_sha is not None and (
                not isinstance(declared_label_sha, str)
                or _SHA256.fullmatch(declared_label_sha) is None
                or declared_label_sha != label_sha
            ):
                raise ValueError("parent label SHA mismatch")
            _decode_size(image_payload)
            _validate_yolo_label(label_payload.decode(), int(raw.get("box_count", -1)))
            if split in {"val", "test"}:
                val_test_digest.update(image_payload)
                val_test_digest.update(label_payload)
            destination_split = "train" if split == "train" else f"regression-{split}"
            sequence = str(sequence)
            image_relative = Path("images") / destination_split / f"{sequence}.jpg"
            label_relative = Path("labels") / destination_split / f"{sequence}.txt"
            _write_new(staging / image_relative, image_payload)
            _write_new(staging / label_relative, label_payload)
            seen_image_shas.add(image_sha)
            materialized.append(
                {
                    **dict(raw),
                    "split": destination_split,
                    "image_path": str(image_relative),
                    "label_path": str(label_relative),
                    "label_sha256": label_sha,
                    "parent_manifest_sha256": parent_manifest_sha,
                    "source_dataset": str(raw.get("source_dataset", "v25-replay")),
                }
            )
        if val_test_digest.hexdigest() != parent_val_test_sha:
            raise ValueError("parent val/test SHA mismatch")
        with zipfile.ZipFile(recent_zip) as archive:
            zip_names = set(archive.namelist())
            for ordinal, raw in enumerate(
                sorted(recent_records, key=lambda row: str(row.get("image_sha256"))), start=1
            ):
                if not isinstance(raw, Mapping):
                    raise ValueError("recent record malformed")
                split = raw.get("split")
                if split not in {"train", "val"}:
                    raise ValueError("recent split malformed")
                filename = raw.get("blind_filename")
                image_sha = raw.get("image_sha256")
                width = raw.get("width")
                height = raw.get("height")
                if (
                    not isinstance(filename, str)
                    or not isinstance(image_sha, str)
                    or _SHA256.fullmatch(image_sha) is None
                    or image_sha in seen_image_shas
                    or type(width) is not int
                    or type(height) is not int
                ):
                    raise ValueError("recent image contract mismatch")
                zip_name = f"images/{filename}"
                if zip_name not in zip_names:
                    raise ValueError("recent ZIP image missing")
                image_payload = archive.read(zip_name)
                if hashlib.sha256(image_payload).hexdigest() != image_sha:
                    raise ValueError("recent ZIP image SHA mismatch")
                if _decode_size(image_payload) != (width, height):
                    raise ValueError("recent image dimensions changed")
                label_payload = _label_text(raw.get("boxes"), width, height).encode()
                _validate_yolo_label(label_payload.decode(), len(raw.get("boxes", [])))
                sequence = f"V26{ordinal:05d}"
                image_relative = Path("images") / str(split) / f"{sequence}.jpg"
                label_relative = Path("labels") / str(split) / f"{sequence}.txt"
                _write_new(staging / image_relative, image_payload)
                _write_new(staging / label_relative, label_payload)
                seen_image_shas.add(image_sha)
                materialized.append(
                    {
                        "sequence": sequence,
                        "split": split,
                        "image_path": str(image_relative),
                        "label_path": str(label_relative),
                        "image_sha256": image_sha,
                        "label_sha256": hashlib.sha256(label_payload).hexdigest(),
                        "box_count": len(raw.get("boxes", [])),
                        "positive": raw.get("decision") == "present",
                        "source_dataset": "recent-human-gt-v26",
                        "camera_night": raw.get("camera_night"),
                        "episode_id": raw.get("episode_id"),
                    }
                )
        active_counts = dict(Counter(str(row["split"]) for row in materialized if row["split"] in {"train", "val"}))
        regression_counts = dict(
            Counter(str(row["split"]) for row in materialized if str(row["split"]).startswith("regression-"))
        )
        expected_active = {
            "train": parent_splits["train"] + int(recent_split_plan["recent_split_counts"]["train"]),
            "val": int(recent_split_plan["recent_split_counts"]["val"]),
        }
        expected_regression = {
            "regression-val": parent_splits["val"],
            "regression-test": parent_splits["test"],
        }
        if active_counts != expected_active or regression_counts != expected_regression:
            raise ValueError("materialized split count mismatch")
        data_yaml_payload = (
            f"path: {output_dir.resolve()}\n"
            "train: images/train\n"
            "val: images/val\n"
            "names:\n"
            "  0: gecko\n"
        ).encode()
        _write_new(staging / "data.yaml", data_yaml_payload)
        manifest = {
            "schema": "yolo26n-owner-dataset-v26",
            "status": "V26_DATASET_READY",
            "evaluation_tier": "development",
            "source_commit": _repository_head(),
            "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "future_holdout_required": True,
            "image_count": len(materialized),
            "active_image_count": sum(active_counts.values()),
            "active_split_counts": active_counts,
            "regression_split_counts": regression_counts,
            "recent_split_sha256": _canonical_sha(recent_split_plan),
            "parent_manifest_sha256": _canonical_sha(parent_manifest),
            "parent_integrity_manifest_sha256": _canonical_sha(
                parent_integrity_manifest
            ),
            "recent_zip_sha256": hashlib.sha256(recent_zip.read_bytes()).hexdigest(),
            "data_yaml_sha256": hashlib.sha256(data_yaml_payload).hexdigest(),
            "records": materialized,
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
            "deploy_count": 0,
        }
        _write_new(
            staging / "manifest.private.json",
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode(),
        )
        for path in staging.rglob("*"):
            os.chmod(path, 0o600 if path.is_file() else 0o700)
        _rename_exclusive(staging, output_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "status": "V26_DATASET_READY",
        "image_count": len(materialized),
        "active_split_counts": active_counts,
        "regression_split_counts": regression_counts,
    }


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("JSON root must be object")
    return value


def _load_json_with_sha(path: Path) -> tuple[dict[str, object], str]:
    payload = path.read_bytes()
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be object")
    return value, hashlib.sha256(payload).hexdigest()


def _write_json_once(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _write_new(path, json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final-human-gt", type=Path, required=True)
    parser.add_argument("--review-index", type=Path, required=True)
    parser.add_argument("--selection-manifest", type=Path, required=True)
    parser.add_argument("--source-window", type=Path, required=True)
    parser.add_argument("--dense-completion", type=Path, required=True)
    parser.add_argument("--dense-ledger-root", type=Path, required=True)
    parser.add_argument("--enriched-completion", type=Path, required=True)
    parser.add_argument("--primary-export", type=Path, required=True)
    parser.add_argument("--double-review-export", type=Path, required=True)
    parser.add_argument("--adjudication-export", type=Path, required=True)
    parser.add_argument("--adjudication-index", type=Path, required=True)
    parser.add_argument("--plan-output", type=Path, required=True)
    parser.add_argument("--parent-dataset", type=Path)
    parser.add_argument("--parent-integrity-manifest", type=Path)
    parser.add_argument("--recent-zip", type=Path)
    parser.add_argument("--dataset-output", type=Path)
    args = parser.parse_args(argv)
    final_gt = _load_json(args.final_human_gt)
    review_index = _load_json(args.review_index)
    selection_manifest = _load_json(args.selection_manifest)
    source_window, source_window_sha = _load_json_with_sha(args.source_window)
    dense_completion, dense_completion_sha = _load_json_with_sha(
        args.dense_completion
    )
    enriched_completion, enriched_completion_sha = _load_json_with_sha(
        args.enriched_completion
    )
    artifacts = {
        "primary_export_sha256": args.primary_export,
        "double_review_export_sha256": args.double_review_export,
        "adjudication_export_sha256": args.adjudication_export,
        "adjudication_index_sha256": args.adjudication_index,
        "review_index_sha256": args.review_index,
        "selection_sha256": args.selection_manifest,
    }
    validate_final_gt_semantics(
        final_gt,
        artifacts,
        dense_completion=dense_completion,
        dense_ledger_root=args.dense_ledger_root,
    )
    plan = build_recent_split_plan(
        final_gt,
        review_index,
        source_window,
        dense_completion,
        selection_manifest=selection_manifest,
        source_window_sha256=source_window_sha,
        dense_completion_sha256=dense_completion_sha,
        enriched_completion=enriched_completion,
        enriched_completion_sha256=enriched_completion_sha,
    )
    _write_json_once(args.plan_output, plan)
    materialization = (
        args.parent_dataset,
        args.parent_integrity_manifest,
        args.recent_zip,
        args.dataset_output,
    )
    if any(materialization) and not all(materialization):
        raise ValueError("all dataset materialization arguments are required together")
    if all(materialization):
        parent_manifest = _load_json(args.parent_dataset / "manifest.private.json")
        parent_integrity_manifest = _load_json(args.parent_integrity_manifest)
        materialize_v26_dataset(
            parent_dataset=args.parent_dataset,
            parent_manifest=parent_manifest,
            parent_integrity_manifest=parent_integrity_manifest,
            recent_split_plan=plan,
            recent_zip=args.recent_zip,
            output_dir=args.dataset_output,
        )
    print("V26_RECENT_SPLIT_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

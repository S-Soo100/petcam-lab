"""Freeze CVAT exports into a deterministic YOLO26n v2.6.1 human-GT ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import ZipFile

REVIEW_SCHEMA = "yolo26n-v261-blind-review-index-v1"
QUEUE_SCHEMA = "yolo26n-v261-blind-queue-completion-v1"
QUEUE_STATUS = "BLIND_QUEUE_READY"
GT_SCHEMA = "yolo26n-v261-final-human-gt-v1"
GT_STATUS = "V261_HUMAN_GT_READY"
ALLOWED_LABELS = {"gecko", "uncertain", "media_error"}
PRODUCTION_GT_COUNTS = {
    "images": 4_096,
    "positive_images": 2_699,
    "empty_images": 1_397,
    "gecko_boxes": 2_732,
    "uncertain_images": 0,
    "media_error_images": 0,
}


@dataclass(frozen=True)
class PartSpec:
    export_name: str
    queue_name: str
    expected_count: int


DEFAULT_PART_SPECS = (
    PartSpec("task-04-cvat-for-images-1.1.zip", "cvat-upload-part-01.zip", 2_000),
    PartSpec("task-05-cvat-for-images-1.1.zip", "cvat-upload-part-02.zip", 2_000),
    PartSpec("task-06-cvat-for-images-1.1.zip", "cvat-upload-part-03.zip", 96),
)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def _write_json_new(path: Path, value: Mapping[str, Any]) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _queue_members(path: Path) -> tuple[list[str], dict[str, str]]:
    names: list[str] = []
    hashes: dict[str, str] = {}
    with ZipFile(path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            name = Path(member.filename).name
            if not name or name in hashes:
                raise ValueError(f"duplicate or invalid queue member: {name}")
            data = archive.read(member)
            names.append(name)
            hashes[name] = hashlib.sha256(data).hexdigest()
    return names, hashes


def _parse_export(path: Path) -> tuple[ET.Element, list[ET.Element]]:
    with ZipFile(path) as archive:
        if archive.namelist() != ["annotations.xml"]:
            raise ValueError(f"{path.name} must contain annotations.xml only")
        root = ET.fromstring(archive.read("annotations.xml"))
    labels = {
        node.findtext("name") for node in root.findall("./meta/task/labels/label")
    }
    if labels != ALLOWED_LABELS:
        raise ValueError(f"invalid CVAT label set: {sorted(str(v) for v in labels)}")
    return root, root.findall("image")


def _strict_float(value: str | None, *, label: str) -> float:
    if value is None:
        raise ValueError(f"missing {label}")
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"invalid {label}") from exc
    if not number.is_integer() and label in {"width", "height"}:
        raise ValueError(f"invalid {label}")
    return number


def _annotation_record(image: ET.Element, review: Mapping[str, Any]) -> dict[str, Any]:
    name = image.attrib.get("name")
    if name != review.get("blind_name"):
        raise ValueError("review/export blind name mismatch")
    width = int(_strict_float(image.attrib.get("width"), label="width"))
    height = int(_strict_float(image.attrib.get("height"), label="height"))
    if width <= 0 or height <= 0:
        raise ValueError("invalid image dimensions")
    if width != review.get("width") or height != review.get("height"):
        raise ValueError("review/export image dimension mismatch")

    tags = [tag.attrib.get("label") for tag in image.findall("tag")]
    if any(tag not in {"uncertain", "media_error"} for tag in tags):
        raise ValueError("invalid annotation tag")
    if len(tags) != len(set(tags)) or {"uncertain", "media_error"} <= set(tags):
        raise ValueError("conflicting tags")

    boxes_pixels: list[list[float]] = []
    boxes_yolo: list[list[float]] = []
    for box in image.findall("box"):
        if box.attrib.get("label") != "gecko":
            raise ValueError("invalid box label")
        xtl = _strict_float(box.attrib.get("xtl"), label="xtl")
        ytl = _strict_float(box.attrib.get("ytl"), label="ytl")
        xbr = _strict_float(box.attrib.get("xbr"), label="xbr")
        ybr = _strict_float(box.attrib.get("ybr"), label="ybr")
        if not (0 <= xtl < xbr <= width and 0 <= ytl < ybr <= height):
            raise ValueError(f"invalid bbox for {name}")
        boxes_pixels.append([xtl, ytl, xbr, ybr])
        boxes_yolo.append(
            [
                0,
                ((xtl + xbr) / 2) / width,
                ((ytl + ybr) / 2) / height,
                (xbr - xtl) / width,
                (ybr - ytl) / height,
            ]
        )
    if tags and boxes_pixels:
        raise ValueError("tagged image must not contain gecko boxes")
    if boxes_pixels:
        state = "gecko_present"
    elif tags:
        state = str(tags[0])
    else:
        state = "gecko_absent"

    retained = {
        key: review[key]
        for key in (
            "blind_name",
            "clip_ref",
            "camera_ref",
            "camera_night",
            "timestamp_sec",
            "frame_index",
            "image_sha256",
            "source_video_sha256",
            "cohort",
            "role",
            "zip_part",
            "dhash64",
            "selection_reasons",
            "source_reasons",
        )
        if key in review
    }
    return {
        **retained,
        "width": width,
        "height": height,
        "state": state,
        "boxes_pixels": boxes_pixels,
        "boxes_yolo": boxes_yolo,
    }


def normalize_exports(
    *,
    review_index_path: Path,
    queue_completion_path: Path,
    queue_root: Path,
    export_root: Path,
    output_root: Path,
    part_specs: Sequence[PartSpec] = DEFAULT_PART_SPECS,
    expected_counts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Validate all immutable inputs before creating the no-overwrite output root."""

    attempt_root = queue_root.resolve().parent
    if output_root.resolve().parent != attempt_root:
        raise ValueError("output root must be a direct child of the private attempt")
    if output_root.exists():
        raise FileExistsError(output_root)

    input_paths = [review_index_path, queue_completion_path]
    input_paths.extend(queue_root / part.queue_name for part in part_specs)
    input_paths.extend(export_root / part.export_name for part in part_specs)
    initial_input_sha = {path.resolve(): _sha(path) for path in input_paths}

    review_index = _load_object(review_index_path, label="review index")
    completion = _load_object(queue_completion_path, label="queue completion")
    if review_index.get("schema") != REVIEW_SCHEMA:
        raise ValueError("invalid review index schema")
    if (
        completion.get("schema") != QUEUE_SCHEMA
        or completion.get("status") != QUEUE_STATUS
    ):
        raise ValueError("queue is not ready")
    if completion.get("review_index_sha256") != _sha(review_index_path):
        raise ValueError("review index SHA mismatch")

    raw_records = review_index.get("records")
    if not isinstance(raw_records, list):
        raise TypeError("review index records must be a list")
    review_by_name: dict[str, dict[str, Any]] = {}
    for row in raw_records:
        if not isinstance(row, dict) or not isinstance(row.get("blind_name"), str):
            raise TypeError("invalid review index record")
        name = row["blind_name"]
        if name in review_by_name:
            raise ValueError("duplicate review blind name")
        review_by_name[name] = row

    expected_zip_hashes = completion.get("zip_sha256")
    if not isinstance(expected_zip_hashes, dict):
        raise TypeError("queue completion lacks ZIP hashes")
    export_hashes: dict[str, str] = {}
    queue_hashes: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    observed_names: list[str] = []
    for part in part_specs:
        queue_path = queue_root / part.queue_name
        export_path = export_root / part.export_name
        queue_sha = _sha(queue_path)
        if expected_zip_hashes.get(part.queue_name) != queue_sha:
            raise ValueError(f"queue ZIP SHA mismatch: {part.queue_name}")
        queue_names, queue_member_hashes = _queue_members(queue_path)
        _, images = _parse_export(export_path)
        export_names = [image.attrib.get("name", "") for image in images]
        if len(images) != part.expected_count:
            raise ValueError(f"unexpected image count: {part.export_name}")
        if export_names != queue_names:
            raise ValueError("queue/export image order mismatch")
        for image, name in zip(images, export_names, strict=True):
            review = review_by_name.get(name)
            if review is None:
                raise ValueError(f"missing review index row: {name}")
            if review.get("image_sha256") != queue_member_hashes[name]:
                raise ValueError(f"queue image SHA mismatch: {name}")
            records.append(_annotation_record(image, review))
            observed_names.append(name)
        queue_hashes[part.queue_name] = queue_sha
        export_hashes[part.export_name] = _sha(export_path)

    if len(records) != completion.get("accepted_frame_count"):
        raise ValueError("accepted frame count mismatch")
    if set(observed_names) != set(review_by_name) or len(observed_names) != len(
        set(observed_names)
    ):
        raise ValueError("export/review index coverage mismatch")
    expected_names = [f"V{index:07d}.jpg" for index in range(1, len(records) + 1)]
    if observed_names != expected_names:
        raise ValueError("global blind name sequence must be contiguous from 1")

    counts = {
        "images": len(records),
        "positive_images": sum(row["state"] == "gecko_present" for row in records),
        "empty_images": sum(row["state"] == "gecko_absent" for row in records),
        "gecko_boxes": sum(len(row["boxes_pixels"]) for row in records),
        "uncertain_images": sum(row["state"] == "uncertain" for row in records),
        "media_error_images": sum(row["state"] == "media_error" for row in records),
    }
    contract = expected_counts
    if contract is None and tuple(part_specs) == DEFAULT_PART_SPECS:
        contract = PRODUCTION_GT_COUNTS
    if contract is not None and counts != dict(contract):
        raise ValueError("exact GT count contract mismatch")
    if any(_sha(path) != digest for path, digest in initial_input_sha.items()):
        raise ValueError("input changed during normalization")
    freeze = {
        "schema": "yolo26n-v261-export-freeze-v1",
        "status": "V261_EXPORT_FROZEN",
        "review_index_sha256": _sha(review_index_path),
        "queue_completion_sha256": _sha(queue_completion_path),
        "queue_zip_sha256": queue_hashes,
        "cvat_export_sha256": export_hashes,
        "counts": counts,
    }
    result = {
        "schema": GT_SCHEMA,
        "status": GT_STATUS,
        "counts": counts,
        "export_freeze_sha256": hashlib.sha256(
            (
                json.dumps(freeze, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            ).encode()
        ).hexdigest(),
        "records": records,
    }

    output_root.mkdir(mode=0o700)
    _write_json_new(output_root / "export-freeze.private.json", freeze)
    _write_json_new(output_root / "final-human-gt.private.json", result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-index", type=Path, required=True)
    parser.add_argument("--queue-completion", type=Path, required=True)
    parser.add_argument("--queue-root", type=Path, required=True)
    parser.add_argument("--export-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    normalize_exports(
        review_index_path=args.review_index,
        queue_completion_path=args.queue_completion,
        queue_root=args.queue_root,
        export_root=args.export_root,
        output_root=args.output_root,
    )
    print(GT_STATUS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

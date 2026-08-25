"""Build deterministic YOLO v2.4 candidates from human-reviewed Gate data."""

from __future__ import annotations

import hashlib
import csv
import json
import math
import os
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

from PIL import Image, ImageDraw, UnidentifiedImageError


SEED = "yolo26n-gate-operational-reuse-v24-v1"
MINIMUMS = {"total": 300, "positive": 150, "negative": 100, "source_clip": 200}
_GATE_CLIP_FOLDER = re.compile(
    r"^\d{8}-\d{6}_([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$"
)


def _camera_night(camera_id: str, started_at: str) -> str:
    parsed = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("clip started_at must be timezone-aware")
    activity_day = parsed.astimezone(timezone(timedelta(hours=9))) - timedelta(hours=12)
    return hashlib.sha256(
        f"{camera_id}:{activity_day.date().isoformat()}".encode("utf-8")
    ).hexdigest()[:16]


def build_gate_lineage_rows(
    source_relpaths: Sequence[str], clip_rows: Sequence[Mapping[str, object]]
) -> list[dict[str, str]]:
    clips: dict[str, Mapping[str, object]] = {}
    for row in clip_rows:
        clip_id = row.get("id")
        camera_id = row.get("camera_id")
        started_at = row.get("started_at")
        if (
            not isinstance(clip_id, str)
            or not clip_id
            or clip_id in clips
            or not isinstance(camera_id, str)
            or not camera_id
            or not isinstance(started_at, str)
            or not started_at
        ):
            raise ValueError("clip lineage row malformed")
        clips[clip_id.lower()] = row

    resolved: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for source_relpath in source_relpaths:
        if source_relpath in seen_paths:
            raise ValueError("duplicate Gate source path")
        seen_paths.add(source_relpath)
        relative = PurePosixPath(source_relpath)
        if relative.is_absolute() or ".." in relative.parts or len(relative.parts) < 3:
            raise ValueError("Gate source path malformed")
        match = _GATE_CLIP_FOLDER.fullmatch(relative.parent.name.lower())
        if match is None:
            continue
        clip_id = match.group(1)
        clip = clips.get(clip_id)
        if clip is None:
            continue
        resolved.append(
            {
                "source_relpath": source_relpath,
                "source_clip_ref": clip_id,
                "camera_night_ref": _camera_night(
                    str(clip["camera_id"]), str(clip["started_at"])
                ),
            }
        )
    resolved.sort(key=lambda row: row["source_relpath"])
    return resolved


def collect_image_metadata(
    dataset_root: Path, source_relpaths: Sequence[str]
) -> dict[str, dict[str, object]]:
    """Bind each Gate image to the exact bytes decoded for selection."""
    metadata: dict[str, dict[str, object]] = {}
    root = dataset_root.resolve()
    for source_relpath in source_relpaths:
        relative = PurePosixPath(source_relpath)
        if (
            not source_relpath
            or relative.is_absolute()
            or ".." in relative.parts
            or relative.parts[0] != "operational"
            or relative.suffix.lower() not in {".jpg", ".jpeg"}
            or source_relpath in metadata
        ):
            raise ValueError("Gate image path contract mismatch")
        image_path = root.joinpath(*relative.parts)
        if not image_path.is_file():
            raise ValueError("Gate image missing")
        payload = image_path.read_bytes()
        try:
            with Image.open(BytesIO(payload)) as decoded:
                decoded.load()
                width, height = decoded.size
                grayscale = decoded.convert("L").resize(
                    (9, 8), Image.Resampling.LANCZOS
                )
                pixels = list(grayscale.get_flattened_data())
        except (OSError, UnidentifiedImageError) as error:
            raise ValueError("Gate image decode failed") from error
        if width <= 0 or height <= 0:
            raise ValueError("Gate image dimensions malformed")
        bits = 0
        for row in range(8):
            for column in range(8):
                bits = (bits << 1) | int(
                    pixels[row * 9 + column] > pixels[row * 9 + column + 1]
                )
        metadata[source_relpath] = {
            "image_sha256": hashlib.sha256(payload).hexdigest(),
            "decoded_width": width,
            "decoded_height": height,
            "dhash64": f"{bits:016x}",
        }
    return metadata


def _write_new(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def write_candidate_bundle(
    plan: Mapping[str, object], *, image_root: Path, output_dir: Path
) -> dict[str, object]:
    if (
        plan.get("schema") != "yolo26n-gate-operational-candidates-v24-plan-v1"
        or plan.get("status") != "V24_GATE_CANDIDATES_READY"
        or plan.get("seed") != SEED
        or any(plan.get(key) != 0 for key in ("db_write_count", "r2_write_count", "service_write_count"))
    ):
        raise ValueError("candidate plan is not ready")
    selected = plan.get("selected_records")
    if not isinstance(selected, list):
        raise ValueError("candidate records missing")
    audit_rows = select_policy_audit(selected, seed=SEED)

    root = image_root.resolve()
    created = False
    try:
        output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
        created = True
        os.chmod(output_dir, 0o700)
        frames_dir = output_dir / "audit-frames"
        frames_dir.mkdir(mode=0o700)
        os.chmod(frames_dir, 0o700)

        private_audit_rows: list[dict[str, object]] = []
        public_rows: list[dict[str, str]] = []
        for row in audit_rows:
            relative = PurePosixPath(str(row["source_relpath"]))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("audit source path malformed")
            source_path = root.joinpath(*relative.parts)
            payload = source_path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != row["image_sha256"]:
                raise ValueError("audit source bytes changed")
            with Image.open(BytesIO(payload)) as decoded:
                decoded.load()
                if decoded.size != (row["width"], row["height"]):
                    raise ValueError("audit source dimensions changed")
                rendered = decoded.convert("RGB")
            draw = ImageDraw.Draw(rendered)
            for box in row["boxes_xywh"]:
                x, y, width, height = map(float, box)
                draw.rectangle((x, y, x + width, y + height), outline=(255, 0, 0), width=2)
            sequence = str(row["sequence"])
            filename = f"{sequence}.jpg"
            encoded = BytesIO()
            rendered.save(encoded, format="JPEG", quality=95, subsampling=0)
            _write_new(frames_dir / filename, encoded.getvalue())
            public_rows.append(
                {
                    "sequence": sequence,
                    "filename": filename,
                    "expected_policy": "review",
                }
            )
            private_audit_rows.append(dict(row))

        csv_buffer = StringIO(newline="")
        writer = csv.DictWriter(
            csv_buffer,
            fieldnames=["sequence", "filename", "expected_policy"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(public_rows)
        _write_new(output_dir / "audit-index.csv", csv_buffer.getvalue().encode("utf-8"))

        verdict_buffer = StringIO(newline="")
        verdict_writer = csv.DictWriter(
            verdict_buffer,
            fieldnames=["sequence", "verdict"],
            lineterminator="\n",
        )
        verdict_writer.writeheader()
        verdict_writer.writerows(
            {"sequence": row["sequence"], "verdict": ""} for row in public_rows
        )
        _write_new(
            output_dir / "owner-verdict.csv",
            verdict_buffer.getvalue().encode("utf-8"),
        )

        candidate_manifest = {
            **dict(plan),
            "schema": "yolo26n-gate-operational-candidates-v24-manifest-v1",
            "status": "V24_GATE_HUMAN_AUDIT_REQUIRED",
            "selected_count": len(selected),
            "audit_count": len(private_audit_rows),
            "audit_records": private_audit_rows,
        }
        _write_new(
            output_dir / "candidate-manifest.private.json",
            (json.dumps(candidate_manifest, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
        )
        exclusions = {
            "schema": "yolo26n-gate-operational-exclusions-v24-v1",
            "counts": plan.get("exclusion_counts", {}),
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
        }
        _write_new(
            output_dir / "exclusions.private.json",
            (json.dumps(exclusions, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
        )
    except BaseException:
        if created:
            shutil.rmtree(output_dir)
        raise
    return {
        "status": "V24_GATE_HUMAN_AUDIT_REQUIRED",
        "selected_count": len(selected),
        "audit_count": 60,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def write_full_policy_review_bundle(
    records: Sequence[Mapping[str, object]],
    *,
    audit_summary: Mapping[str, object],
    review_class: str,
    image_root: Path,
    output_dir: Path,
) -> dict[str, object]:
    required_status = {
        "positive": {
            "V24_GATE_POSITIVE_FULL_REVIEW_REQUIRED",
            "V24_GATE_POSITIVE_AND_NEGATIVE_FULL_REVIEW_REQUIRED",
        },
        "negative": {
            "V24_GATE_NEGATIVE_FULL_REVIEW_REQUIRED",
            "V24_GATE_POSITIVE_AND_NEGATIVE_FULL_REVIEW_REQUIRED",
        },
    }
    if review_class not in required_status:
        raise ValueError("full review class malformed")
    if audit_summary.get("status") not in required_status[review_class]:
        raise PermissionError("full review is not required for this class")
    positive = review_class == "positive"
    selected = [dict(row) for row in records if row.get("positive") is positive]
    selected.sort(key=lambda row: (str(row.get("source_clip_ref")), str(row.get("image_sha256"))))
    if not selected:
        raise ValueError("full review candidate shortage")

    root = image_root.resolve()
    created = False
    try:
        output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
        created = True
        os.chmod(output_dir, 0o700)
        frames_dir = output_dir / "review-frames"
        frames_dir.mkdir(mode=0o700)
        os.chmod(frames_dir, 0o700)
        prefix = "P" if positive else "N"
        public_rows: list[dict[str, str]] = []
        private_rows: list[dict[str, object]] = []
        for index, row in enumerate(selected, 1):
            relative = PurePosixPath(str(row.get("source_relpath", "")))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("review source path malformed")
            payload = root.joinpath(*relative.parts).read_bytes()
            if hashlib.sha256(payload).hexdigest() != row.get("image_sha256"):
                raise ValueError("review source bytes changed")
            with Image.open(BytesIO(payload)) as decoded:
                decoded.load()
                if decoded.size != (row.get("width"), row.get("height")):
                    raise ValueError("review source dimensions changed")
                rendered = decoded.convert("RGB")
            draw = ImageDraw.Draw(rendered)
            boxes = row.get("boxes_xywh")
            if not isinstance(boxes, list) or len(boxes) != row.get("box_count"):
                raise ValueError("review bbox contract mismatch")
            for box in boxes:
                x, y, width, height = map(float, box)
                draw.rectangle((x, y, x + width, y + height), outline=(255, 0, 0), width=2)
            sequence = f"{prefix}{index:04d}"
            encoded = BytesIO()
            rendered.save(encoded, format="JPEG", quality=95, subsampling=0)
            _write_new(frames_dir / f"{sequence}.jpg", encoded.getvalue())
            public_rows.append({"sequence": sequence, "verdict": ""})
            private_rows.append({**row, "sequence": sequence})

        verdict_buffer = StringIO(newline="")
        writer = csv.DictWriter(
            verdict_buffer,
            fieldnames=["sequence", "verdict"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(public_rows)
        _write_new(
            output_dir / "owner-verdict.csv",
            verdict_buffer.getvalue().encode("utf-8"),
        )
        manifest = {
            "schema": "yolo26n-gate-operational-full-policy-review-v24-v1",
            "status": f"V24_GATE_{review_class.upper()}_FULL_REVIEW_PENDING",
            "review_class": review_class,
            "review_count": len(private_rows),
            "records": private_rows,
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
        }
        _write_new(
            output_dir / "review-manifest.private.json",
            (json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
        )
    except BaseException:
        if created:
            shutil.rmtree(output_dir)
        raise
    return {
        "status": f"V24_GATE_{review_class.upper()}_FULL_REVIEW_PENDING",
        "review_count": len(selected),
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def validate_full_policy_review(
    records: Sequence[Mapping[str, object]],
    verdict_rows: Sequence[Mapping[str, object]],
    *,
    review_class: str,
    minimum_accepted: int,
) -> dict[str, object]:
    contract = {
        "positive": (True, "P", "positive_needs_fix"),
        "negative": (False, "N", "negative_mislabeled"),
    }
    if review_class not in contract or type(minimum_accepted) is not int or minimum_accepted < 0:
        raise ValueError("full review validator contract mismatch")
    expected_positive, prefix, quarantine_verdict = contract[review_class]
    if not records or len(records) != len(verdict_rows):
        raise ValueError("full review row count mismatch")

    accepted: list[dict[str, object]] = []
    quarantined: list[dict[str, object]] = []
    for index, (record, verdict_row) in enumerate(
        zip(records, verdict_rows, strict=True), 1
    ):
        sequence = f"{prefix}{index:04d}"
        if (
            record.get("sequence") != sequence
            or record.get("positive") is not expected_positive
            or not isinstance(record.get("source_clip_ref"), str)
            or not record.get("source_clip_ref")
            or not _is_sha256(record.get("image_sha256"))
            or verdict_row.get("sequence") != sequence
        ):
            raise ValueError("full review sequence/record mismatch")
        verdict = verdict_row.get("verdict")
        if type(verdict) is not str or verdict not in {"accept", quarantine_verdict}:
            raise ValueError("full review verdict malformed")
        if verdict == "accept":
            accepted.append(dict(record))
        else:
            quarantined.append(dict(record))

    enough = len(accepted) >= minimum_accepted
    status = (
        f"V24_GATE_{review_class.upper()}_FULL_REVIEW_ACCEPTED"
        if enough
        else "V24_GATE_REUSE_SHORTAGE"
    )
    return {
        "schema": "yolo26n-gate-operational-full-policy-review-result-v24-v1",
        "status": status,
        "review_class": review_class,
        "review_count": len(records),
        "accepted_count": len(accepted),
        "quarantined_count": len(quarantined),
        "accepted_records": accepted,
        "quarantined_records": quarantined,
        "minimum_accepted": minimum_accepted,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_dhash64(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 16
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _rank(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(map(str, parts)).encode("utf-8")).hexdigest()


def _hamming(first: str, second: str) -> int:
    return (int(first, 16) ^ int(second, 16)).bit_count()


def _strict_number(value: object) -> float:
    if isinstance(value, bool) or type(value) not in {int, float}:
        raise ValueError("bbox coordinate malformed")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("bbox coordinate malformed")
    return result


def _validate_boxes(
    annotations: Sequence[Mapping[str, object]], *, width: int, height: int
) -> list[list[float]]:
    boxes: list[list[float]] = []
    for annotation in annotations:
        if annotation.get("category_id") != 1 or annotation.get("iscrowd") != 0:
            raise ValueError("annotation contract mismatch")
        raw = annotation.get("bbox")
        if not isinstance(raw, list) or len(raw) != 4:
            raise ValueError("bbox contract mismatch")
        x, y, box_width, box_height = map(_strict_number, raw)
        if not (
            0 <= x < width
            and 0 <= y < height
            and box_width > 0
            and box_height > 0
            and x + box_width <= width
            and y + box_height <= height
        ):
            raise ValueError("bbox outside image boundary")
        boxes.append([x, y, box_width, box_height])
    return boxes


def _select_clip_records(
    records: Sequence[dict[str, object]], *, seed: str
) -> list[dict[str, object]]:
    by_state: dict[bool, list[dict[str, object]]] = defaultdict(list)
    for record in records:
        by_state[bool(record["positive"])].append(record)

    selected: list[dict[str, object]] = []
    states = sorted(by_state, reverse=True)
    if len(states) == 2:
        for state in states:
            selected.append(
                min(
                    by_state[state],
                    key=lambda row: _rank(
                        seed,
                        row["source_clip_ref"],
                        state,
                        row["image_sha256"],
                    ),
                )
            )
        return selected

    state = states[0]
    ranked = sorted(
        by_state[state],
        key=lambda row: _rank(
            seed, row["source_clip_ref"], state, row["image_sha256"]
        ),
    )
    anchor = ranked[0]
    selected.append(anchor)
    eligible = [
        row
        for row in ranked[1:]
        if _hamming(str(anchor["dhash64"]), str(row["dhash64"])) > 2
    ]
    if eligible:
        selected.append(
            min(
                eligible,
                key=lambda row: (
                    -_hamming(str(anchor["dhash64"]), str(row["dhash64"])),
                    _rank(
                        seed,
                        row["source_clip_ref"],
                        state,
                        row["image_sha256"],
                    ),
                ),
            )
        )
    return selected


def build_gate_candidate_plan(
    *,
    coco_documents: Sequence[Mapping[str, object]],
    image_metadata: Mapping[str, Mapping[str, object]],
    protected_records: Sequence[Mapping[str, object]],
    lineage_rows: Sequence[Mapping[str, object]],
    seed: str,
) -> dict[str, object]:
    if seed != SEED:
        raise ValueError("selector seed mismatch")

    protected_shas = {row.get("image_sha256") for row in protected_records}
    protected_dhashes = {row.get("dhash64") for row in protected_records}
    protected_sources = {row.get("source_clip_ref") for row in protected_records}
    protected_nights = {row.get("camera_night_ref") for row in protected_records}
    if any(not _is_sha256(value) for value in protected_shas):
        raise ValueError("protected image SHA malformed")
    if any(not _is_dhash64(value) for value in protected_dhashes):
        raise ValueError("protected image dHash malformed")
    if any(not isinstance(value, str) or not value for value in protected_sources):
        raise ValueError("protected source lineage malformed")
    if any(not isinstance(value, str) or not value for value in protected_nights):
        raise ValueError("protected night lineage malformed")

    lineage_by_path: dict[str, Mapping[str, object]] = {}
    for row in lineage_rows:
        source_relpath = row.get("source_relpath")
        source_clip_ref = row.get("source_clip_ref")
        camera_night_ref = row.get("camera_night_ref")
        if (
            not isinstance(source_relpath, str)
            or not source_relpath
            or not isinstance(source_clip_ref, str)
            or not source_clip_ref
            or not isinstance(camera_night_ref, str)
            or not camera_night_ref
            or source_relpath in lineage_by_path
        ):
            raise ValueError("Gate lineage row malformed")
        lineage_by_path[source_relpath] = row

    source_counts: Counter[str] = Counter()
    exclusions: Counter[str] = Counter()
    eligible: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    seen_shas: set[str] = set()

    for document in coco_documents:
        if document.get("categories") != [{"id": 1, "name": "gecko"}]:
            raise ValueError("COCO category contract mismatch")
        images = document.get("images")
        annotations = document.get("annotations")
        if not isinstance(images, list) or not isinstance(annotations, list):
            raise ValueError("COCO document malformed")
        annotations_by_image: dict[int, list[Mapping[str, object]]] = defaultdict(list)
        for annotation in annotations:
            if not isinstance(annotation, Mapping) or type(annotation.get("image_id")) is not int:
                raise ValueError("COCO annotation malformed")
            annotations_by_image[int(annotation["image_id"])].append(annotation)

        for image in images:
            if not isinstance(image, Mapping):
                raise ValueError("COCO image malformed")
            image_id = image.get("id")
            source_relpath = image.get("file_name")
            width = image.get("width")
            height = image.get("height")
            if (
                type(image_id) is not int
                or not isinstance(source_relpath, str)
                or source_relpath in seen_paths
                or type(width) is not int
                or type(height) is not int
                or width <= 0
                or height <= 0
            ):
                raise ValueError("COCO image contract mismatch")
            seen_paths.add(source_relpath)
            if not source_relpath.startswith("operational/"):
                exclusions["non_operational_source"] += 1
                continue
            source_counts["operational"] += 1

            metadata = image_metadata.get(source_relpath)
            if not isinstance(metadata, Mapping):
                raise ValueError("image metadata missing")
            image_sha = metadata.get("image_sha256")
            dhash = metadata.get("dhash64")
            if (
                not _is_sha256(image_sha)
                or not _is_dhash64(dhash)
                or metadata.get("decoded_width") != width
                or metadata.get("decoded_height") != height
                or image_sha in seen_shas
            ):
                raise ValueError("image metadata contract mismatch")
            seen_shas.add(str(image_sha))

            try:
                boxes = _validate_boxes(
                    annotations_by_image[int(image_id)], width=width, height=height
                )
            except ValueError:
                exclusions["invalid_bbox_quarantine"] += 1
                continue

            lineage = lineage_by_path.get(source_relpath)
            if lineage is None:
                exclusions["unresolved_lineage"] += 1
                continue
            source_clip_ref = lineage["source_clip_ref"]
            camera_night_ref = lineage["camera_night_ref"]
            if image_sha in protected_shas:
                exclusions["exact_sha_overlap"] += 1
                continue
            if source_clip_ref in protected_sources:
                exclusions["source_clip_overlap"] += 1
                continue
            if camera_night_ref in protected_nights:
                exclusions["camera_night_overlap"] += 1
                continue
            if any(
                _hamming(str(dhash), str(protected_dhash)) <= 2
                for protected_dhash in protected_dhashes
            ):
                exclusions["protected_dhash_overlap"] += 1
                continue

            eligible.append(
                {
                    "source_relpath": source_relpath,
                    "source_clip_ref": source_clip_ref,
                    "camera_night_ref": camera_night_ref,
                    "image_sha256": image_sha,
                    "dhash64": dhash,
                    "positive": bool(boxes),
                    "box_count": len(boxes),
                    "width": width,
                    "height": height,
                    "boxes_xywh": boxes,
                }
            )

    by_clip: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in eligible:
        by_clip[str(record["source_clip_ref"])].append(record)
    selected_records: list[dict[str, object]] = []
    for source_clip_ref in sorted(by_clip):
        selected_records.extend(
            _select_clip_records(by_clip[source_clip_ref], seed=seed)
        )
    selected_records.sort(
        key=lambda row: (str(row["source_clip_ref"]), str(row["image_sha256"]))
    )

    positive_count = sum(bool(row["positive"]) for row in selected_records)
    negative_count = len(selected_records) - positive_count
    source_clip_count = len({row["source_clip_ref"] for row in selected_records})
    actual = {
        "total": len(selected_records),
        "positive": positive_count,
        "negative": negative_count,
        "source_clip": source_clip_count,
    }
    shortfall = {
        key: max(0, minimum - actual[key]) for key, minimum in MINIMUMS.items()
    }
    status = (
        "V24_GATE_CANDIDATES_READY"
        if not any(shortfall.values())
        else "V24_GATE_REUSE_SHORTAGE"
    )
    return {
        "schema": "yolo26n-gate-operational-candidates-v24-plan-v1",
        "status": status,
        "seed": seed,
        "source_counts": dict(sorted(source_counts.items())),
        "exclusion_counts": dict(sorted(exclusions.items())),
        "eligible_count": len(eligible),
        "selected_count": len(selected_records),
        "positive_count": positive_count,
        "negative_count": negative_count,
        "source_clip_count": source_clip_count,
        "shortfall": dict(sorted(shortfall.items())),
        "selected_records": selected_records,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def select_policy_audit(
    records: Sequence[Mapping[str, object]], *, seed: str
) -> list[dict[str, object]]:
    if seed != SEED:
        raise ValueError("selector seed mismatch")
    representatives: dict[str, dict[bool, Mapping[str, object]]] = defaultdict(dict)
    for row in records:
        source_clip = row.get("source_clip_ref")
        positive = row.get("positive")
        image_sha = row.get("image_sha256")
        if (
            not isinstance(source_clip, str)
            or not source_clip
            or type(positive) is not bool
            or not _is_sha256(image_sha)
        ):
            raise ValueError("policy audit record malformed")
        previous = representatives[source_clip].get(positive)
        if previous is None or _rank(
            seed, "audit-representative", source_clip, positive, image_sha
        ) < _rank(
            seed,
            "audit-representative",
            source_clip,
            positive,
            previous.get("image_sha256"),
        ):
            representatives[source_clip][positive] = row

    positive_only = [
        states[True]
        for states in representatives.values()
        if True in states and False not in states
    ]
    negative_only = [
        states[False]
        for states in representatives.values()
        if False in states and True not in states
    ]
    shared = [states for states in representatives.values() if len(states) == 2]
    positive_only.sort(
        key=lambda row: _rank(seed, "audit-positive", row["source_clip_ref"])
    )
    negative_only.sort(
        key=lambda row: _rank(seed, "audit-negative", row["source_clip_ref"])
    )
    selected_positive = positive_only[:40]
    selected_negative = negative_only[:20]
    used_clips = {
        str(row["source_clip_ref"])
        for row in selected_positive + selected_negative
    }
    remaining_shared = [
        states
        for states in shared
        if str(states[True]["source_clip_ref"]) not in used_clips
    ]
    remaining_shared.sort(
        key=lambda states: _rank(
            seed, "audit-shared-positive", states[True]["source_clip_ref"]
        )
    )
    positive_needed = 40 - len(selected_positive)
    selected_positive.extend(states[True] for states in remaining_shared[:positive_needed])
    remaining_shared = remaining_shared[positive_needed:]
    remaining_shared.sort(
        key=lambda states: _rank(
            seed, "audit-shared-negative", states[False]["source_clip_ref"]
        )
    )
    negative_needed = 20 - len(selected_negative)
    selected_negative.extend(states[False] for states in remaining_shared[:negative_needed])
    if len(selected_positive) != 40 or len(selected_negative) != 20:
        raise ValueError("policy audit candidate shortage")
    chosen = selected_positive + selected_negative
    chosen.sort(
        key=lambda row: _rank(
            seed,
            "audit-order",
            row.get("source_clip_ref"),
            row.get("image_sha256"),
        )
    )
    return [
        {**dict(row), "sequence": f"G{index:04d}"}
        for index, row in enumerate(chosen, 1)
    ]


def validate_owner_policy_audit(
    index_rows: Sequence[Mapping[str, object]],
    verdict_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    expected_sequences = [f"G{index:04d}" for index in range(1, 61)]
    if len(index_rows) != 60:
        raise ValueError("audit index must contain exactly 60 rows")
    if [row.get("sequence") for row in index_rows] != expected_sequences:
        raise ValueError("audit index sequence mismatch")
    if any(
        type(row.get("positive")) is not bool
        or row.get("expected_policy") != "review"
        or not isinstance(row.get("source_clip_ref"), str)
        or not row.get("source_clip_ref")
        for row in index_rows
    ):
        raise ValueError("audit index contract mismatch")
    if len({row["source_clip_ref"] for row in index_rows}) != 60:
        raise ValueError("audit index source clips must be distinct")
    positive_count = sum(row["positive"] is True for row in index_rows)
    negative_count = len(index_rows) - positive_count
    if (positive_count, negative_count) != (40, 20):
        raise ValueError("audit index class quota mismatch")

    if len(verdict_rows) != 60 or [
        row.get("sequence") for row in verdict_rows
    ] != expected_sequences:
        raise ValueError("audit verdict sequence mismatch")
    allowed = {"accept", "positive_needs_fix", "negative_mislabeled"}
    verdicts: list[str] = []
    for index_row, verdict_row in zip(index_rows, verdict_rows, strict=True):
        verdict = verdict_row.get("verdict")
        if type(verdict) is not str or verdict not in allowed:
            raise ValueError("audit verdict malformed")
        if verdict == "positive_needs_fix" and index_row["positive"] is not True:
            raise ValueError("audit verdict does not match positive row")
        if verdict == "negative_mislabeled" and index_row["positive"] is not False:
            raise ValueError("audit verdict does not match negative row")
        verdicts.append(verdict)

    positive_fix_count = verdicts.count("positive_needs_fix")
    negative_error_count = verdicts.count("negative_mislabeled")
    if positive_fix_count and negative_error_count:
        status = "V24_GATE_POSITIVE_AND_NEGATIVE_FULL_REVIEW_REQUIRED"
    elif positive_fix_count:
        status = "V24_GATE_POSITIVE_FULL_REVIEW_REQUIRED"
    elif negative_error_count:
        status = "V24_GATE_NEGATIVE_FULL_REVIEW_REQUIRED"
    else:
        status = "V24_GATE_AUDIT_ACCEPTED"
    return {
        "schema": "yolo26n-gate-operational-owner-audit-v24-v1",
        "status": status,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "positive_needs_fix_count": positive_fix_count,
        "negative_mislabeled_count": negative_error_count,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }

"""Build the development-only YOLO26n v2.2 dataset without group leakage."""

from __future__ import annotations

import hashlib
import argparse
import csv
import json
import math
import shutil
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from scripts.build_yolo26n_cvat_dataset import SPLITS, choose_group_splits


BUILDER_PATH = Path(__file__).resolve()
SPLIT_HELPER_PATH = Path(__file__).with_name("build_yolo26n_cvat_dataset.py").resolve()


@dataclass(frozen=True)
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True)
class DatasetRecord:
    sequence: str
    image_path: Path
    image_sha256: str
    width: int
    height: int
    boxes: tuple[BoundingBox, ...]
    camera_night_group: str
    source_dataset: str
    final_holdout_eligible: bool = False


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _box_from_snapshot(value: object, *, expected_label_id: int) -> BoundingBox:
    if not isinstance(value, dict):
        raise ValueError("snapshot box must be an object")
    if value.get("type") != "rectangle" or value.get("label_id") != expected_label_id:
        raise ValueError("only gecko rectangle boxes are accepted")
    points = value.get("points")
    if not isinstance(points, list) or len(points) != 4:
        raise ValueError("snapshot bbox needs four points")
    return BoundingBox(*(float(coordinate) for coordinate in points))


def load_v21_records(
    *, snapshot_path: Path, review_path: Path, images_dir: Path
) -> tuple[DatasetRecord, ...]:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if snapshot.get("schema") != "cvat-task160-owner-snapshot-v1":
        raise ValueError("unsupported v2.1 snapshot schema")
    header, review_rows = _read_csv(review_path)
    if header != ["sequence", "camera_night_group"]:
        raise ValueError("unexpected v2.1 review header")
    review_by_sequence = {row["sequence"]: row for row in review_rows}
    if len(review_by_sequence) != len(review_rows):
        raise ValueError("duplicate v2.1 review sequence")

    records = []
    seen: set[str] = set()
    for image in snapshot.get("images", []):
        sequence = Path(str(image.get("path", ""))).stem
        if sequence in seen or sequence not in review_by_sequence:
            raise ValueError("v2.1 snapshot/review sequence mismatch")
        seen.add(sequence)
        image_path = images_dir / f"{sequence}.jpg"
        records.append(
            DatasetRecord(
                sequence=sequence,
                image_path=image_path,
                image_sha256=_sha256(image_path),
                width=int(image["width"]),
                height=int(image["height"]),
                boxes=tuple(
                    _box_from_snapshot(box, expected_label_id=9)
                    for box in image.get("boxes", [])
                ),
                camera_night_group=review_by_sequence[sequence]["camera_night_group"],
                source_dataset="base-v21",
                final_holdout_eligible=False,
            )
        )
    if seen != set(review_by_sequence):
        raise ValueError("v2.1 snapshot/review must contain identical sequences")
    return tuple(records)


def load_v22_reinforcement_records(
    *,
    candidate_manifest_path: Path,
    snapshot_path: Path,
    review_path: Path,
    accepted_summary_path: Path,
    images_dir: Path,
) -> tuple[DatasetRecord, ...]:
    candidate_manifest = json.loads(
        candidate_manifest_path.read_text(encoding="utf-8")
    )
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    summary = json.loads(accepted_summary_path.read_text(encoding="utf-8"))
    if candidate_manifest.get("status") != "V22_CANDIDATE_QUEUE_READY":
        raise ValueError("candidate queue is not ready")
    if snapshot.get("schema") != "cvat-task160-owner-snapshot-v1":
        raise ValueError("unsupported v2.2 snapshot schema")
    if summary.get("status") != "V22_HUMAN_REVIEW_ACCEPTED":
        raise ValueError("human review is not accepted")

    candidate_by_sequence = {
        frame["sequence"]: frame for frame in candidate_manifest.get("frames", [])
    }
    if len(candidate_by_sequence) != len(candidate_manifest.get("frames", [])):
        raise ValueError("duplicate candidate sequence")
    header, review_rows = _read_csv(review_path)
    if header != ["sequence", "ambiguous"]:
        raise ValueError("unexpected v2.2 review header")
    review_by_sequence: dict[str, bool] = {}
    for row in review_rows:
        value = row.get("ambiguous")
        if value not in {"true", "false"} or row["sequence"] in review_by_sequence:
            raise ValueError("invalid v2.2 owner review row")
        review_by_sequence[row["sequence"]] = value == "true"

    images = snapshot.get("images", [])
    if not isinstance(images, list):
        raise ValueError("snapshot images must be a list")
    snapshot_sequences = [Path(str(image.get("path", ""))).stem for image in images]
    expected_sequences = set(candidate_by_sequence)
    if set(snapshot_sequences) != expected_sequences or set(review_by_sequence) != expected_sequences:
        raise ValueError("candidate/snapshot/review sequences must match")

    records = []
    ambiguous_count = 0
    positive_count = 0
    negative_count = 0
    box_count = 0
    for image in images:
        sequence = Path(str(image["path"])).stem
        if review_by_sequence[sequence]:
            ambiguous_count += 1
            continue
        frame = candidate_by_sequence[sequence]
        image_path = images_dir / f"{sequence}.jpg"
        actual_sha = _sha256(image_path)
        if actual_sha != image.get("image_sha256") or actual_sha != frame.get("image_sha256"):
            raise ValueError("reinforcement image sha256 mismatch")
        boxes = tuple(
            _box_from_snapshot(box, expected_label_id=1)
            for box in image.get("boxes", [])
        )
        positive_count += int(bool(boxes))
        negative_count += int(not boxes)
        box_count += len(boxes)
        records.append(
            DatasetRecord(
                # The base dataset already has V#### names, so namespace new review rows.
                sequence=f"R22_{sequence}",
                image_path=image_path,
                image_sha256=actual_sha,
                width=int(image["width"]),
                height=int(image["height"]),
                boxes=boxes,
                camera_night_group=str(frame["camera_night"]),
                source_dataset="reinforcement-v22",
                final_holdout_eligible=False,
            )
        )
    expected_counts = {
        "ambiguous_image_count": ambiguous_count,
        "positive_image_count": positive_count,
        "negative_image_count": negative_count,
        "box_count": box_count,
    }
    if any(summary.get(key) != value for key, value in expected_counts.items()):
        raise ValueError("accepted summary counts do not match review artifacts")
    return tuple(records)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_bbox(
    box: BoundingBox, *, width: int, height: int
) -> tuple[float, float, float, float]:
    values = (box.x1, box.y1, box.x2, box.y2)
    if any(isinstance(value, bool) or not math.isfinite(float(value)) for value in values):
        raise ValueError("bbox coordinates must be finite numbers")
    x1, y1, x2, y2 = (float(value) for value in values)
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("bbox must stay inside the image")
    normalized = (
        ((x1 + x2) / 2) / width,
        ((y1 + y2) / 2) / height,
        (x2 - x1) / width,
        (y2 - y1) / height,
    )
    if not all(0 < value <= 1 for value in normalized):
        raise ValueError("bbox normalized geometry must be in (0, 1]")
    return normalized


def _validated_records(records: Iterable[DatasetRecord]) -> tuple[DatasetRecord, ...]:
    rows = tuple(records)
    if not rows:
        raise ValueError("at least one dataset record is required")

    seen_sequences: set[str] = set()
    seen_hashes: set[str] = set()
    for row in rows:
        if not row.sequence or row.sequence.strip() != row.sequence:
            raise ValueError("sequence must be a non-empty normalized string")
        if row.sequence in seen_sequences:
            raise ValueError("duplicate sequence")
        seen_sequences.add(row.sequence)

        if not row.image_path.is_file():
            raise FileNotFoundError(row.image_path)
        if (
            len(row.image_sha256) != 64
            or row.image_sha256.lower() != row.image_sha256
            or any(character not in "0123456789abcdef" for character in row.image_sha256)
        ):
            raise ValueError("image sha256 must be lowercase hex")
        if _sha256(row.image_path) != row.image_sha256:
            raise ValueError("image sha256 mismatch")
        if row.image_sha256 in seen_hashes:
            raise ValueError("duplicate image sha256")
        seen_hashes.add(row.image_sha256)

        if type(row.width) is not int or type(row.height) is not int:
            raise ValueError("image dimensions must be integers")
        if row.width <= 0 or row.height <= 0:
            raise ValueError("image dimensions must be positive")
        if not row.camera_night_group.strip() or not row.source_dataset.strip():
            raise ValueError("camera-night and source dataset are required")
        if type(row.final_holdout_eligible) is not bool:
            raise ValueError("final_holdout_eligible must be boolean")
        for box in row.boxes:
            _normalized_bbox(box, width=row.width, height=row.height)
    return rows


def _source_input_digests(records: tuple[DatasetRecord, ...]) -> dict[str, str]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in records:
        grouped.setdefault(row.source_dataset, []).append(
            {
                "sequence": row.sequence,
                "image_sha256": row.image_sha256,
                "camera_night_group": row.camera_night_group,
                "width": row.width,
                "height": row.height,
                "boxes": [box.__dict__ for box in row.boxes],
                "final_holdout_eligible": row.final_holdout_eligible,
            }
        )
    return {
        source: _canonical_sha256(sorted(items, key=lambda item: str(item["sequence"])))
        for source, items in sorted(grouped.items())
    }


def build_v22_dataset(
    *,
    base_records: Iterable[DatasetRecord],
    reinforcement_records: Iterable[DatasetRecord],
    output_dir: Path,
    seed: int = 26,
    input_artifact_digests: dict[str, str] | None = None,
) -> dict[str, object]:
    """Validate first, then atomically materialize a grouped development dataset."""

    base = tuple(base_records)
    reinforcement = tuple(reinforcement_records)
    if any(row.source_dataset == "reinforcement-v22" and row.final_holdout_eligible for row in reinforcement):
        raise ValueError("reinforcement records cannot be final holdout eligible")
    records = _validated_records(base + reinforcement)
    if output_dir.exists():
        raise FileExistsError(output_dir)

    split_inputs = [
        {
            "sequence": row.sequence,
            "camera_night_group": row.camera_night_group,
            "box_count": len(row.boxes),
        }
        for row in records
    ]
    assignments = choose_group_splits(split_inputs, seed=seed)
    if set(assignments) != {row.sequence for row in records}:
        raise ValueError("every record must receive one split")

    source_counts = Counter(row.source_dataset for row in records)
    split_counts = Counter(assignments[row.sequence] for row in records)
    positive_counts = Counter(
        assignments[row.sequence] for row in records if row.boxes
    )
    box_counts = Counter()
    for row in records:
        box_counts[assignments[row.sequence]] += len(row.boxes)

    manifest_records: list[dict[str, object]] = []
    for row in sorted(records, key=lambda item: item.sequence):
        split = assignments[row.sequence]
        manifest_records.append(
            {
                "sequence": row.sequence,
                "image_sha256": row.image_sha256,
                "camera_night_group": row.camera_night_group,
                "source_dataset": row.source_dataset,
                "split": split,
                "image_path": f"images/{split}/{row.sequence}.jpg",
                "label_path": f"labels/{split}/{row.sequence}.txt",
                "positive": bool(row.boxes),
                "box_count": len(row.boxes),
                "final_holdout_eligible": row.final_holdout_eligible,
            }
        )

    manifest: dict[str, object] = {
        "schema": "yolo26n-owner-dataset-v22",
        "evaluation_tier": "development",
        "future_holdout_required": True,
        "seed": seed,
        "split_group": "camera_night_group",
        "class_names": ["gecko"],
        "image_count": len(records),
        "positive_image_count": sum(bool(row.boxes) for row in records),
        "box_count": sum(len(row.boxes) for row in records),
        "base_image_count": len(base),
        "reinforcement_image_count": len(reinforcement),
        "source_dataset_counts": dict(sorted(source_counts.items())),
        "camera_night_count": len({row.camera_night_group for row in records}),
        "split_counts": {split: split_counts[split] for split in SPLITS},
        "positive_counts": {split: positive_counts[split] for split in SPLITS},
        "box_counts": {split: box_counts[split] for split in SPLITS},
        "input_digests": _source_input_digests(records),
        "input_artifact_sha256": dict(sorted((input_artifact_digests or {}).items())),
        "code_sha256": {
            "build_yolo26n_v22_dataset.py": _sha256(BUILDER_PATH),
            "build_yolo26n_cvat_dataset.py": _sha256(SPLIT_HELPER_PATH),
        },
        "records": manifest_records,
    }
    exclusions = {
        "schema": "yolo26n-development-exclusions-v22",
        "future_holdout_required": True,
        "records": [
            {
                "sequence": row.sequence,
                "image_sha256": row.image_sha256,
                "reason": "development_dataset_member",
            }
            for row in sorted(records, key=lambda item: item.sequence)
        ],
    }

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = output_dir.parent / f".{output_dir.name}.tmp-{uuid.uuid4().hex}"
    try:
        for split in SPLITS:
            (staging / "images" / split).mkdir(parents=True)
            (staging / "labels" / split).mkdir(parents=True)
        for row in records:
            split = assignments[row.sequence]
            shutil.copy2(row.image_path, staging / "images" / split / f"{row.sequence}.jpg")
            label_lines = []
            for box in row.boxes:
                x, y, width, height = _normalized_bbox(
                    box, width=row.width, height=row.height
                )
                label_lines.append(
                    f"0 {x:.6f} {y:.6f} {width:.6f} {height:.6f}"
                )
            label_text = "\n".join(label_lines)
            if label_text:
                label_text += "\n"
            (staging / "labels" / split / f"{row.sequence}.txt").write_text(
                label_text, encoding="utf-8"
            )

        (staging / "data.yaml").write_text(
            "\n".join(
                [
                    f"path: {output_dir.resolve()}",
                    "train: images/train",
                    "val: images/val",
                    "test: images/test",
                    "names:",
                    "  0: gecko",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (staging / "manifest.private.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging / "development-exclusions.private.json").write_text(
            json.dumps(exclusions, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staging.replace(output_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-snapshot", type=Path, required=True)
    parser.add_argument("--base-review", type=Path, required=True)
    parser.add_argument("--base-images", type=Path, required=True)
    parser.add_argument("--reinforcement-manifest", type=Path, required=True)
    parser.add_argument("--reinforcement-snapshot", type=Path, required=True)
    parser.add_argument("--reinforcement-review", type=Path, required=True)
    parser.add_argument("--accepted-summary", type=Path, required=True)
    parser.add_argument("--reinforcement-images", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=26)
    args = parser.parse_args()

    base_records = load_v21_records(
        snapshot_path=args.base_snapshot,
        review_path=args.base_review,
        images_dir=args.base_images,
    )
    reinforcement_records = load_v22_reinforcement_records(
        candidate_manifest_path=args.reinforcement_manifest,
        snapshot_path=args.reinforcement_snapshot,
        review_path=args.reinforcement_review,
        accepted_summary_path=args.accepted_summary,
        images_dir=args.reinforcement_images,
    )
    manifest = build_v22_dataset(
        base_records=base_records,
        reinforcement_records=reinforcement_records,
        output_dir=args.output_dir,
        seed=args.seed,
        input_artifact_digests={
            "accepted_summary": _sha256(args.accepted_summary),
            "base_review": _sha256(args.base_review),
            "base_snapshot": _sha256(args.base_snapshot),
            "reinforcement_manifest": _sha256(args.reinforcement_manifest),
            "reinforcement_review": _sha256(args.reinforcement_review),
            "reinforcement_snapshot": _sha256(args.reinforcement_snapshot),
        },
    )
    print(
        json.dumps(
            {
                "status": "V22_DATASET_READY",
                "image_count": manifest["image_count"],
                "positive_image_count": manifest["positive_image_count"],
                "box_count": manifest["box_count"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

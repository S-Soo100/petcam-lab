"""Build a private YOLO v2.3 candidate by adding Owner training photos to v2.2."""

from __future__ import annotations

import argparse
import ctypes
import csv
import errno
import hashlib
import json
import math
import os
import shutil
import tempfile
from pathlib import Path
from typing import Mapping, Sequence


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_sha(payload: bytes, expected: str, label: str) -> None:
    if not _is_sha(expected) or _sha(payload) != expected:
        raise ValueError(f"{label} SHA mismatch")


def _snapshot_rows_by_sequence(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    """Bind CVAT rows to the frozen O#### filename instead of inventing an absent field."""
    indexed: dict[str, Mapping[str, object]] = {}
    for row in rows:
        path = row.get("path")
        if not isinstance(path, str):
            raise ValueError("Owner snapshot path malformed")
        sequence = Path(path).stem
        if path != f"images/{sequence}.jpg" or len(sequence) != 5 or not sequence.startswith("O") or not sequence[1:].isdigit():
            raise ValueError("Owner snapshot path malformed")
        if sequence in indexed:
            raise ValueError("Owner snapshot sequence duplicated")
        indexed[sequence] = row
    return indexed


def build_v23_plan(
    *, base_records: Sequence[Mapping[str, object]], snapshot: Mapping[str, object],
    owner_review: Mapping[str, bool], source_items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    base_counts = {split: 0 for split in ("train", "val", "test")}
    base_shas: set[str] = set()
    for row in base_records:
        split, image_sha = row.get("split"), row.get("image_sha256")
        if split not in base_counts or not _is_sha(image_sha) or image_sha in base_shas:
            raise ValueError("base dataset contract mismatch")
        base_counts[split] += 1
        base_shas.add(image_sha)
    images = snapshot.get("images")
    if not isinstance(images, list) or len(images) != 240 or len(owner_review) != 240 or len(source_items) != 240:
        raise ValueError("Owner candidate contract mismatch")
    capture_day = {row.get("sequence"): row.get("capture_day") for row in source_items}
    owner_records = []
    diagnostic = ambiguous = 0
    seen_shas: set[str] = set()
    for index, row in enumerate(images, 1):
        sequence = f"O{index:04d}"
        if not isinstance(row, Mapping) or row.get("frame") != index - 1 or row.get("path") != f"images/{sequence}.jpg":
            raise ValueError("Owner candidate sequence mismatch")
        image_sha = row.get("image_sha256")
        if not _is_sha(image_sha) or image_sha in seen_shas:
            raise ValueError("Owner candidate image SHA mismatch")
        seen_shas.add(image_sha)
        if row.get("partition") == "external_diagnostic":
            diagnostic += 1
            continue
        if row.get("partition") != "training_candidate":
            raise ValueError("Owner candidate partition mismatch")
        if owner_review.get(sequence) is True:
            ambiguous += 1
            continue
        if owner_review.get(sequence) is not False or not isinstance(capture_day.get(sequence), str):
            raise ValueError("Owner candidate review/provenance mismatch")
        boxes = row.get("boxes")
        if not isinstance(boxes, list):
            raise ValueError("Owner candidate boxes malformed")
        owner_records.append({
            "sequence": sequence,
            "split": "train",
            "image_sha256": image_sha,
            "box_count": len(boxes),
            "positive": bool(boxes),
            "capture_day": capture_day[sequence],
            "source_dataset": "owner-media-v1",
        })
    if diagnostic != 60 or ambiguous != 3 or len(owner_records) != 177:
        raise ValueError("Owner candidate exact count mismatch")
    owner_shas = {row["image_sha256"] for row in owner_records}
    if owner_shas & base_shas:
        raise ValueError("Owner candidate overlaps base dataset")
    v23_counts = dict(base_counts)
    v23_counts["train"] += len(owner_records)
    return {
        "schema": "yolo26n-owner-dataset-v23-plan-v1",
        "status": "V23_MATERIALIZATION_REQUIRED",
        "base_split_counts": base_counts,
        "v23_split_counts": v23_counts,
        "owner_added_count": len(owner_records),
        "owner_ambiguous_excluded_count": ambiguous,
        "external_diagnostic_excluded_count": diagnostic,
        "owner_records": owner_records,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def _label(boxes: Sequence[Mapping[str, object]], *, width: int, height: int) -> str:
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError("Owner image dimensions malformed")
    lines = []
    for box in boxes:
        if (
            box.get("type") != "rectangle"
            or type(box.get("label_id")) is not int
            or box.get("label_id") != 1
            or type(box.get("rotation")) not in {int, float}
            or isinstance(box.get("rotation"), bool)
            or float(box.get("rotation")) != 0.0
        ):
            raise ValueError("Owner box malformed")
        points = box.get("points")
        if not isinstance(points, list) or len(points) != 4:
            raise ValueError("Owner box malformed")
        x1, y1, x2, y2 = map(float, points)
        if not all(math.isfinite(value) for value in (x1, y1, x2, y2)) or not (
            0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height
        ):
            raise ValueError("Owner box malformed")
        lines.append(f"0 {(x1+x2)/(2*width):.9f} {(y1+y2)/(2*height):.9f} {(x2-x1)/width:.9f} {(y2-y1)/height:.9f}")
    return "\n".join(lines) + ("\n" if lines else "")


def _validate_yolo_label(payload: str, expected_count: int) -> None:
    lines = [line for line in payload.splitlines() if line]
    if type(expected_count) is not int or expected_count < 0 or len(lines) != expected_count:
        raise ValueError("base label count mismatch")
    for line in lines:
        parts = line.split()
        if len(parts) != 5 or parts[0] != "0":
            raise ValueError("base label malformed")
        x, y, width, height = map(float, parts[1:])
        if not all(math.isfinite(value) for value in (x, y, width, height)) or not (
            0 <= x <= 1 and 0 <= y <= 1 and 0 < width <= 1 and 0 < height <= 1
            and x - width / 2 >= -1e-6 and y - height / 2 >= -1e-6
            and x + width / 2 <= 1 + 1e-6 and y + height / 2 <= 1 + 1e-6
        ):
            raise ValueError("base label malformed")


def _validate_base_dataset(root: Path, manifest: Mapping[str, object]) -> None:
    records = manifest.get("records")
    if manifest.get("schema") != "yolo26n-owner-dataset-v22" or not isinstance(records, list) or len(records) != 1016 or manifest.get("image_count") != 1016:
        raise ValueError("base manifest contract mismatch")
    split_counts = {split: 0 for split in ("train", "val", "test")}
    box_counts = {split: 0 for split in split_counts}
    positive_counts = {split: 0 for split in split_counts}
    source_counts: dict[str, int] = {}
    seen: set[str] = set()
    expected_files: set[Path] = set()
    for record in records:
        split = record.get("split")
        sequence = record.get("sequence")
        image_rel, label_rel = record.get("image_path"), record.get("label_path")
        image_sha, box_count, positive = record.get("image_sha256"), record.get("box_count"), record.get("positive")
        if (
            split not in split_counts or not isinstance(sequence, str)
            or image_rel != f"images/{split}/{sequence}.jpg" or label_rel != f"labels/{split}/{sequence}.txt"
            or not _is_sha(image_sha) or image_sha in seen or type(box_count) is not int or box_count < 0
            or type(positive) is not bool or positive != (box_count > 0)
        ):
            raise ValueError("base record contract mismatch")
        image, label = root / str(image_rel), root / str(label_rel)
        if not image.is_file() or not label.is_file() or _sha(image.read_bytes()) != image_sha:
            raise ValueError("base file contract mismatch")
        _validate_yolo_label(label.read_text(), box_count)
        expected_files.update({Path(str(image_rel)), Path(str(label_rel))})
        seen.add(str(image_sha)); split_counts[str(split)] += 1; box_counts[str(split)] += box_count; positive_counts[str(split)] += int(positive)
        source = record.get("source_dataset")
        if not isinstance(source, str):
            raise ValueError("base source contract mismatch")
        source_counts[source] = source_counts.get(source, 0) + 1
    actual_files = {path.relative_to(root) for path in root.rglob("*") if path.is_file() and path.suffix in {".jpg", ".txt"}}
    if actual_files != expected_files:
        raise ValueError("base file set mismatch")
    if (
        manifest.get("split_counts") != split_counts or manifest.get("box_counts") != box_counts
        or manifest.get("box_count") != sum(box_counts.values()) or manifest.get("positive_counts") != positive_counts
        or manifest.get("positive_image_count") != sum(positive_counts.values()) or manifest.get("source_dataset_counts") != source_counts
    ):
        raise ValueError("base aggregate mismatch")


def _validate_owner_inputs(
    *, snapshot: Mapping[str, object], source_manifest: Mapping[str, object], summary: Mapping[str, object],
    review: Mapping[str, bool], owner_images: Path, source_manifest_sha: str, review_sha: str,
) -> None:
    provenance = snapshot.get("provenance")
    if snapshot.get("schema") != "yolo26n-owner-media-cvat-snapshot-v1" or snapshot.get("labels") != [{"id": 1, "name": "gecko"}]:
        raise ValueError("Owner snapshot contract mismatch")
    if not isinstance(provenance, Mapping) or provenance.get("cvat_job_id") != 163 or provenance.get("raw_gecko_label_id") != 10 or provenance.get("manifest_sha256") != source_manifest_sha or provenance.get("owner_review_sha256") != review_sha:
        raise ValueError("Owner provenance mismatch")
    if source_manifest.get("schema") != "yolo26n-owner-media-diagnostic-v1" or source_manifest.get("status") != "OWNER_MEDIA_HUMAN_REVIEW_REQUIRED" or source_manifest.get("image_count") != 240 or source_manifest.get("partition_counts") != {"external_diagnostic": 60, "training_candidate": 180}:
        raise ValueError("Owner source manifest mismatch")
    expected_summary = {
        "external_diagnostic": {"accepted": 60, "ambiguous": 0, "boxes": 57, "negative": 6, "positive": 54},
        "training_candidate": {"accepted": 177, "ambiguous": 3, "boxes": 169, "negative": 15, "positive": 162},
    }
    if summary.get("status") != "OWNER_MEDIA_HUMAN_REVIEW_ACCEPTED" or summary.get("image_count") != 240 or summary.get("accepted_image_count") != 237 or summary.get("ambiguous_image_count") != 3 or summary.get("positive_image_count") != 216 or summary.get("negative_image_count") != 21 or summary.get("box_count") != 226 or summary.get("partition_counts") != expected_summary or summary.get("provenance") != provenance:
        raise ValueError("Owner summary mismatch")
    items, images = source_manifest.get("items"), snapshot.get("images")
    if not isinstance(items, list) or not isinstance(images, list) or len(items) != 240 or len(images) != 240 or list(review) != [f"O{index:04d}" for index in range(1, 241)]:
        raise ValueError("Owner row count/order mismatch")
    if {path.name for path in owner_images.glob("*.jpg")} != {f"O{index:04d}.jpg" for index in range(1, 241)}:
        raise ValueError("Owner image set mismatch")
    partition_counts = {"external_diagnostic": 0, "training_candidate": 0}
    for index, (item, image) in enumerate(zip(items, images), 1):
        sequence = f"O{index:04d}"; partition = item.get("partition")
        if partition not in partition_counts:
            raise ValueError("Owner partition mismatch")
        partition_counts[partition] += 1
        if (
            item.get("sequence") != sequence or item.get("derived_filename") != f"{sequence}.jpg" or item.get("partition") != partition
            or not _is_sha(item.get("derived_sha256")) or image.get("frame") != index - 1 or image.get("path") != f"images/{sequence}.jpg"
            or image.get("partition") != partition or image.get("image_sha256") != item.get("derived_sha256")
            or image.get("width") != item.get("width") or image.get("height") != item.get("height")
            or _sha((owner_images / f"{sequence}.jpg").read_bytes()) != image.get("image_sha256")
        ):
            raise ValueError("Owner row binding mismatch")
        _label(image.get("boxes"), width=image.get("width"), height=image.get("height"))
    if partition_counts != {"external_diagnostic": 60, "training_candidate": 180}:
        raise ValueError("Owner partition count mismatch")


def _validate_materialized_dataset(root: Path, records: Sequence[Mapping[str, object]]) -> None:
    expected_files: set[Path] = set()
    seen_shas: set[str] = set()
    for record in records:
        image_rel, label_rel = Path(str(record["image_path"])), Path(str(record["label_path"]))
        image, label = root / image_rel, root / label_rel
        expected_sha = record.get("image_sha256")
        if not image.is_file() or not label.is_file() or not _is_sha(expected_sha) or _sha(image.read_bytes()) != expected_sha or expected_sha in seen_shas:
            raise ValueError("materialized image contract mismatch")
        _validate_yolo_label(label.read_text(), record.get("box_count"))
        expected_files.update({image_rel, label_rel}); seen_shas.add(str(expected_sha))
    actual_files = {path.relative_to(root) for path in root.rglob("*") if path.is_file() and path.suffix in {".jpg", ".txt"}}
    if actual_files != expected_files:
        raise ValueError("materialized file set mismatch")


def _rename_exclusive(source: Path, destination: Path) -> None:
    """Publish a completed directory without replacing even an empty destination on macOS."""
    libc = ctypes.CDLL(None, use_errno=True)
    renamex = getattr(libc, "renamex_np", None)
    if renamex is None:
        if destination.exists():
            raise FileExistsError(destination)
        os.rename(source, destination)
        return
    renamex.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    renamex.restype = ctypes.c_int
    if renamex(os.fsencode(source), os.fsencode(destination), 0x00000004) != 0:  # RENAME_EXCL
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(destination)
        raise OSError(error, os.strerror(error), destination)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dataset", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--owner-review", type=Path, required=True)
    parser.add_argument("--human-summary", type=Path, required=True)
    parser.add_argument("--owner-images", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-base-manifest-sha256", required=True)
    parser.add_argument("--expected-snapshot-sha256", required=True)
    parser.add_argument("--expected-source-manifest-sha256", required=True)
    parser.add_argument("--expected-owner-review-sha256", required=True)
    parser.add_argument("--expected-human-summary-sha256", required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(args.output)
    base_manifest_bytes = (args.base_dataset / "manifest.private.json").read_bytes()
    snapshot_bytes = args.snapshot.read_bytes()
    source_manifest_bytes = args.source_manifest.read_bytes()
    owner_review_bytes = args.owner_review.read_bytes()
    human_summary_bytes = args.human_summary.read_bytes()
    _require_sha(base_manifest_bytes, args.expected_base_manifest_sha256, "base manifest")
    _require_sha(snapshot_bytes, args.expected_snapshot_sha256, "Owner snapshot")
    _require_sha(source_manifest_bytes, args.expected_source_manifest_sha256, "Owner source manifest")
    _require_sha(owner_review_bytes, args.expected_owner_review_sha256, "Owner review")
    _require_sha(human_summary_bytes, args.expected_human_summary_sha256, "Owner summary")
    base_manifest = json.loads(base_manifest_bytes)
    snapshot = json.loads(snapshot_bytes)
    source_manifest = json.loads(source_manifest_bytes)
    human_summary = json.loads(human_summary_bytes)
    with args.owner_review.open(newline="") as handle:
        if handle.readline().rstrip("\r\n") != "sequence,ambiguous":
            raise ValueError("Owner review header mismatch")
        handle.seek(0)
        rows = list(csv.DictReader(handle))
    if len(rows) != 240 or any(row.get("ambiguous") not in {"true", "false"} for row in rows):
        raise ValueError("Owner review contract mismatch")
    review = {row["sequence"]: row["ambiguous"] == "true" for row in rows}
    if len(review) != 240:
        raise ValueError("Owner review sequence mismatch")
    _validate_base_dataset(args.base_dataset, base_manifest)
    _validate_owner_inputs(
        snapshot=snapshot, source_manifest=source_manifest, summary=human_summary,
        review=review, owner_images=args.owner_images,
        source_manifest_sha=_sha(source_manifest_bytes), review_sha=_sha(owner_review_bytes),
    )
    plan = build_v23_plan(
        base_records=base_manifest["records"], snapshot=snapshot,
        owner_review=review, source_items=source_manifest["items"],
    )
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{args.output.name}.staging-", dir=args.output.parent))
    try:
        shutil.copytree(args.base_dataset / "images", staging / "images")
        shutil.copytree(args.base_dataset / "labels", staging / "labels")
        owner_rows = _snapshot_rows_by_sequence(snapshot["images"])
        records = list(base_manifest["records"])
        for index, planned in enumerate(plan["owner_records"], 1):
            source_sequence = planned["sequence"]
            source = args.owner_images / f"{source_sequence}.jpg"
            if hashlib.sha256(source.read_bytes()).hexdigest() != planned["image_sha256"]:
                raise ValueError("Owner image SHA mismatch")
            sequence = f"O23{index:04d}"
            image_rel = f"images/train/{sequence}.jpg"
            label_rel = f"labels/train/{sequence}.txt"
            shutil.copy2(source, staging / image_rel)
            raw = owner_rows[source_sequence]
            (staging / label_rel).write_text(_label(raw["boxes"], width=raw["width"], height=raw["height"]))
            records.append({
                "sequence": sequence, "split": "train", "image_path": image_rel,
                "label_path": label_rel, "image_sha256": planned["image_sha256"],
                "box_count": planned["box_count"], "positive": planned["positive"],
                "source_dataset": "owner-media-v1", "final_holdout_eligible": False,
                "camera_night_group": hashlib.sha256(planned["capture_day"].encode()).hexdigest()[:20],
            })
        manifest = dict(base_manifest)
        split_box_counts = {split: 0 for split in ("train", "val", "test")}
        split_positive_counts = {split: 0 for split in ("train", "val", "test")}
        source_dataset_counts: dict[str, int] = {}
        camera_nights: set[str] = set()
        for record in records:
            split = record["split"]
            split_box_counts[split] += int(record["box_count"])
            split_positive_counts[split] += int(bool(record["positive"]))
            source_dataset = str(record["source_dataset"])
            source_dataset_counts[source_dataset] = source_dataset_counts.get(source_dataset, 0) + 1
            camera_nights.add(str(record["camera_night_group"]))
        owner_digest = hashlib.sha256(
            "".join(sorted(str(row["image_sha256"]) for row in plan["owner_records"])).encode()
        ).hexdigest()
        manifest.update({
            "schema": "yolo26n-owner-dataset-v23",
            "image_count": len(records),
            "split_counts": plan["v23_split_counts"],
            "box_count": sum(split_box_counts.values()),
            "box_counts": split_box_counts,
            "positive_image_count": sum(split_positive_counts.values()),
            "positive_counts": split_positive_counts,
            "source_dataset_counts": source_dataset_counts,
            "camera_night_count": len(camera_nights),
            "records": records,
            "owner_media_added_count": 177,
            "external_diagnostic_excluded_count": 60,
            "owner_ambiguous_excluded_count": 3,
            "future_holdout_required": True,
            "evaluation_tier": "development",
            "input_artifact_sha256": {
                **base_manifest.get("input_artifact_sha256", {}),
                "base_v22_manifest": hashlib.sha256(base_manifest_bytes).hexdigest(),
                "owner_media_snapshot": hashlib.sha256(snapshot_bytes).hexdigest(),
                "owner_media_source_manifest": hashlib.sha256(source_manifest_bytes).hexdigest(),
                "owner_media_review": hashlib.sha256(owner_review_bytes).hexdigest(),
                "owner_media_human_summary": hashlib.sha256(human_summary_bytes).hexdigest(),
            },
            "input_digests": {
                **base_manifest.get("input_digests", {}),
                "owner-media-v1": owner_digest,
            },
            "code_sha256": {
                **base_manifest.get("code_sha256", {}),
                "build_yolo26n_owner_dataset_v23.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            },
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
        })
        (staging / "manifest.private.json").write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")))
        (staging / "data.yaml").write_text("path: .\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: gecko\n")
        for cache in staging.rglob("*.cache"):
            cache.unlink()
        for path in staging.rglob("*"):
            if path.is_file():
                path.chmod(0o600)
            elif path.is_dir():
                path.chmod(0o700)
        staging.chmod(0o700)
        _validate_materialized_dataset(staging, records)
        _rename_exclusive(staging, args.output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(json.dumps({k: v for k, v in plan.items() if k != "owner_records"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

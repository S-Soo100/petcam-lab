"""CVAT Owner bbox snapshot을 누수 없는 YOLO 데이터셋으로 변환해."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Iterable


SPLITS = ("train", "val", "test")
DEFAULT_RATIOS = {"train": 0.70, "val": 0.15, "test": 0.15}


def normalize_bbox(
    points: list[float], *, width: int, height: int
) -> tuple[float, float, float, float]:
    if len(points) != 4 or width <= 0 or height <= 0:
        raise ValueError("invalid bbox or image size")
    x1, y1, x2, y2 = (float(value) for value in points)
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("bbox must stay inside the image")
    return (
        ((x1 + x2) / 2) / width,
        ((y1 + y2) / 2) / height,
        (x2 - x1) / width,
        (y2 - y1) / height,
    )


def _split_score(
    groups: dict[str, list[dict]],
    group_assignments: dict[str, str],
    ratios: dict[str, float],
) -> float:
    totals = {
        "images": sum(len(items) for items in groups.values()),
        "positive": sum(
            sum(int(item["box_count"] > 0) for item in items)
            for items in groups.values()
        ),
        "boxes": sum(
            sum(int(item["box_count"]) for item in items)
            for items in groups.values()
        ),
    }
    actual = {
        split: {"images": 0, "positive": 0, "boxes": 0} for split in SPLITS
    }
    for group, items in groups.items():
        split = group_assignments[group]
        actual[split]["images"] += len(items)
        actual[split]["positive"] += sum(
            int(item["box_count"] > 0) for item in items
        )
        actual[split]["boxes"] += sum(int(item["box_count"]) for item in items)

    score = 0.0
    for split in SPLITS:
        for metric in ("images", "positive", "boxes"):
            target = totals[metric] * ratios[split]
            score += ((actual[split][metric] - target) / max(target, 1.0)) ** 2
        if actual[split]["images"] == 0:
            score += 1_000.0
    return score


def choose_group_splits(
    records: Iterable[dict],
    *,
    seed: int = 26,
    trials: int = 20_000,
    ratios: dict[str, float] | None = None,
) -> dict[str, str]:
    ratios = dict(ratios or DEFAULT_RATIOS)
    if set(ratios) != set(SPLITS) or abs(sum(ratios.values()) - 1.0) > 1e-9:
        raise ValueError("split ratios must contain train/val/test and sum to 1")

    rows = list(records)
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        group = str(row.get("camera_night_group", "")).strip()
        sequence = str(row.get("sequence", "")).strip()
        if not group or not sequence:
            raise ValueError("sequence and camera_night_group are required")
        groups[group].append(row)
    if len(groups) < len(SPLITS):
        raise ValueError("at least three camera-night groups are required")

    rng = random.Random(seed)
    group_names = sorted(groups)
    weighted_splits = tuple(
        split
        for split in SPLITS
        for _ in range(max(1, round(ratios[split] * 100)))
    )
    best: tuple[float, tuple[tuple[str, str], ...]] | None = None
    for _ in range(max(1, trials)):
        shuffled = group_names.copy()
        rng.shuffle(shuffled)
        candidate = {
            shuffled[index]: split for index, split in enumerate(SPLITS)
        }
        for group in shuffled[len(SPLITS) :]:
            candidate[group] = rng.choice(weighted_splits)
        frozen = tuple(sorted(candidate.items()))
        scored = (_split_score(groups, candidate, ratios), frozen)
        if best is None or scored < best:
            best = scored

    assert best is not None
    group_assignments = dict(best[1])
    return {
        str(row["sequence"]): group_assignments[str(row["camera_night_group"])]
        for row in rows
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_dataset(
    *,
    snapshot_path: Path,
    review_csv_path: Path,
    images_dir: Path,
    output_dir: Path,
    assignments: dict[str, str] | None = None,
    seed: int = 26,
    trials: int = 20_000,
) -> dict:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if snapshot.get("schema") != "cvat-task160-owner-snapshot-v1":
        raise ValueError("unsupported CVAT snapshot schema")

    with review_csv_path.open(encoding="utf-8", newline="") as handle:
        review_rows = list(csv.DictReader(handle))
    review_by_sequence = {row["sequence"]: row for row in review_rows}

    images = snapshot.get("images", [])
    records = []
    seen_sequences: set[str] = set()
    label_ids: set[int] = set()
    for image in images:
        sequence = Path(image["path"]).stem
        if sequence in seen_sequences or sequence not in review_by_sequence:
            raise ValueError("snapshot and review CSV sequences must match uniquely")
        seen_sequences.add(sequence)
        boxes = image.get("boxes", [])
        for box in boxes:
            if box.get("type") != "rectangle":
                raise ValueError("only rectangle annotations are supported")
            label_ids.add(int(box["label_id"]))
            normalize_bbox(
                box["points"], width=int(image["width"]), height=int(image["height"])
            )
        records.append(
            {
                "sequence": sequence,
                "camera_night_group": review_by_sequence[sequence][
                    "camera_night_group"
                ],
                "box_count": len(boxes),
            }
        )
    if seen_sequences != set(review_by_sequence):
        raise ValueError("snapshot and review CSV must contain the same sequences")
    if len(label_ids) > 1:
        raise ValueError("exactly one gecko label is supported")

    split_by_sequence = assignments or choose_group_splits(
        records, seed=seed, trials=trials
    )
    if set(split_by_sequence) != seen_sequences:
        raise ValueError("every sequence needs exactly one split assignment")
    if not set(split_by_sequence.values()) <= set(SPLITS):
        raise ValueError("unknown split assignment")

    output_dir.mkdir(parents=True, exist_ok=False)
    for split in SPLITS:
        (output_dir / "images" / split).mkdir(parents=True)
        (output_dir / "labels" / split).mkdir(parents=True)

    split_counts = {split: 0 for split in SPLITS}
    positive_counts = {split: 0 for split in SPLITS}
    box_counts = {split: 0 for split in SPLITS}
    for image in images:
        sequence = Path(image["path"]).stem
        split = split_by_sequence[sequence]
        source_image = images_dir / f"{sequence}.jpg"
        if not source_image.is_file():
            raise FileNotFoundError(source_image)
        shutil.copy2(source_image, output_dir / "images" / split / source_image.name)

        label_lines = []
        for box in image.get("boxes", []):
            x, y, w, h = normalize_bbox(
                box["points"], width=int(image["width"]), height=int(image["height"])
            )
            label_lines.append(f"0 {x:.6f} {y:.6f} {w:.6f} {h:.6f}")
        label_text = "\n".join(label_lines)
        if label_text:
            label_text += "\n"
        (output_dir / "labels" / split / f"{sequence}.txt").write_text(
            label_text, encoding="utf-8"
        )
        split_counts[split] += 1
        positive_counts[split] += int(bool(label_lines))
        box_counts[split] += len(label_lines)

    (output_dir / "data.yaml").write_text(
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
    manifest = {
        "schema": "yolo26n-owner-dataset-v1",
        "snapshot_sha256": _sha256(snapshot_path),
        "image_count": len(images),
        "positive_image_count": sum(positive_counts.values()),
        "box_count": sum(box_counts.values()),
        "split_counts": split_counts,
        "positive_counts": positive_counts,
        "box_counts": box_counts,
        "assignments": split_by_sequence,
        "split_group": "camera_night_group",
        "seed": seed,
    }
    (output_dir / "manifest.private.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--review-csv", type=Path, required=True)
    parser.add_argument("--images-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=26)
    parser.add_argument("--trials", type=int, default=20_000)
    args = parser.parse_args()
    manifest = build_dataset(
        snapshot_path=args.snapshot,
        review_csv_path=args.review_csv,
        images_dir=args.images_dir,
        output_dir=args.output_dir,
        seed=args.seed,
        trials=args.trials,
    )
    print(
        json.dumps(
            {
                key: manifest[key]
                for key in (
                    "image_count",
                    "positive_image_count",
                    "box_count",
                    "split_counts",
                    "positive_counts",
                    "box_counts",
                )
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

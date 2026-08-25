from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping


CandidateRow = Mapping[str, object]


@dataclass(frozen=True)
class CandidatePolicy:
    bucket_quotas: Mapping[str, int]
    max_sources_per_camera_night: int
    seed: str

    def __post_init__(self) -> None:
        if self.max_sources_per_camera_night < 1:
            raise ValueError("max_sources_per_camera_night must be positive")
        if any(quota < 0 for quota in self.bucket_quotas.values()):
            raise ValueError("bucket quotas cannot be negative")


def _float(row: CandidateRow, key: str) -> float:
    return float(row.get(key, 0.0) or 0.0)


def _int(row: CandidateRow, key: str) -> int:
    return int(row.get(key, 0) or 0)


def classify_candidate(row: CandidateRow) -> str:
    """Use model disagreement only to choose what a human should inspect."""
    yolo_max_conf = _float(row, "yolo_max_conf")
    yolo_detection_count = _int(row, "yolo_detection_count")
    gme_visible_ratio = _float(row, "gme_visible_ratio")
    gme_max_geckos = _int(row, "gme_max_geckos")

    if gme_max_geckos >= 2:
        return "multi_gecko"
    if (
        yolo_detection_count >= 1
        and yolo_max_conf >= 0.25
        and gme_max_geckos == 0
        and gme_visible_ratio < 0.1
    ):
        return "hard_negative"
    if gme_max_geckos >= 1 and (
        yolo_detection_count == 0 or yolo_max_conf < 0.1
    ):
        return "hard_positive"
    if gme_max_geckos >= 1 and yolo_detection_count >= 2:
        return "multi_gecko"
    return "coverage"


def _rank(seed: str, bucket: str, source_ref: str) -> str:
    material = f"{seed}:{bucket}:{source_ref}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def select_candidate_sources(
    rows: Iterable[CandidateRow],
    *,
    policy: CandidatePolicy,
    excluded_source_refs: set[str] | None = None,
) -> list[dict[str, object]]:
    excluded = excluded_source_refs or set()
    classified: dict[str, list[CandidateRow]] = {
        bucket: [] for bucket in policy.bucket_quotas
    }
    seen_input: set[str] = set()

    for row in rows:
        source_ref = str(row.get("source_ref", "")).strip()
        camera_night = str(row.get("camera_night", "")).strip()
        if not source_ref or not camera_night:
            raise ValueError("source_ref and camera_night are required")
        if source_ref in excluded or source_ref in seen_input:
            continue
        seen_input.add(source_ref)
        bucket = classify_candidate(row)
        if bucket in classified:
            classified[bucket].append(row)

    selected: list[dict[str, object]] = []
    selected_refs: set[str] = set()
    night_counts: Counter[str] = Counter()

    for bucket, quota in policy.bucket_quotas.items():
        ranked = sorted(
            classified[bucket],
            key=lambda row: _rank(
                policy.seed,
                bucket,
                str(row["source_ref"]),
            ),
        )
        bucket_count = 0
        for row in ranked:
            source_ref = str(row["source_ref"])
            camera_night = str(row["camera_night"])
            if source_ref in selected_refs:
                continue
            if night_counts[camera_night] >= policy.max_sources_per_camera_night:
                continue
            selected.append(
                {
                    "source_ref": source_ref,
                    "camera_night": camera_night,
                    "candidate_bucket": bucket,
                    "review_required": True,
                }
            )
            selected_refs.add(source_ref)
            night_counts[camera_night] += 1
            bucket_count += 1
            if bucket_count >= quota:
                break

    target_total = sum(policy.bucket_quotas.values())
    if len(selected) < target_total:
        remaining = sorted(
            (
                (bucket, row)
                for bucket, bucket_rows in classified.items()
                for row in bucket_rows
                if str(row["source_ref"]) not in selected_refs
            ),
            key=lambda item: _rank(
                policy.seed,
                "backfill",
                str(item[1]["source_ref"]),
            ),
        )
        for bucket, row in remaining:
            source_ref = str(row["source_ref"])
            camera_night = str(row["camera_night"])
            if night_counts[camera_night] >= policy.max_sources_per_camera_night:
                continue
            selected.append(
                {
                    "source_ref": source_ref,
                    "camera_night": camera_night,
                    "candidate_bucket": bucket,
                    "review_required": True,
                }
            )
            selected_refs.add(source_ref)
            night_counts[camera_night] += 1
            if len(selected) >= target_total:
                break

    return selected

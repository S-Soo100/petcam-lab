from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping


CandidateRow = Mapping[str, object]
V22_FRAME_QUOTAS = {"hard_positive": 220, "hard_negative": 100}
V22_FRAMES_PER_SOURCE = 2
V22_MAX_FRAMES_PER_CAMERA_NIGHT = 12


@dataclass(frozen=True)
class V22CandidatePolicy:
    frame_quotas: Mapping[str, int]
    frames_per_source: int
    max_frames_per_camera_night: int
    seed: str

    def __post_init__(self) -> None:
        if dict(self.frame_quotas) != V22_FRAME_QUOTAS:
            raise ValueError("v2.2 frame quotas must be hard_positive=220 and hard_negative=100")
        if self.frames_per_source != V22_FRAMES_PER_SOURCE:
            raise ValueError("v2.2 frames_per_source must be 2")
        if self.max_frames_per_camera_night != V22_MAX_FRAMES_PER_CAMERA_NIGHT:
            raise ValueError("v2.2 max_frames_per_camera_night must be 12")
        object.__setattr__(
            self,
            "frame_quotas",
            MappingProxyType(dict(V22_FRAME_QUOTAS)),
        )

    def source_quota(self, bucket: str) -> int:
        frames = int(self.frame_quotas[bucket])
        return math.ceil(frames / self.frames_per_source)


def _float(row: CandidateRow, key: str) -> float:
    return float(row.get(key, 0.0) or 0.0)


def _int(row: CandidateRow, key: str) -> int:
    return int(row.get(key, 0) or 0)


def classify_v22_candidate(row: CandidateRow) -> str:
    """Use detector disagreement to route human review, never to make labels."""
    yolo_max_conf = _float(row, "yolo_max_conf")
    yolo_detection_count = _int(row, "yolo_detection_count")
    gme_visible_ratio = _float(row, "gme_visible_ratio")
    gme_max_geckos = _int(row, "gme_max_geckos")

    if gme_max_geckos >= 2:
        return "hard_positive"
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
    return "coverage"


def _strata_tags(row: CandidateRow, bucket: str) -> list[str]:
    if bucket == "hard_positive" and _int(row, "gme_max_geckos") >= 2:
        return ["multi_gecko"]
    if bucket == "hard_positive":
        return ["yolo_missed_gme_visible"]
    if bucket == "hard_negative":
        return ["yolo_high_conf_gme_absent"]
    return ["coverage"]


def _rank(seed: str, bucket: str, source_ref: str) -> str:
    material = f"{seed}:{bucket}:{source_ref}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _identity(row: CandidateRow) -> tuple[str, str, str]:
    source_ref = str(row.get("source_ref", "")).strip()
    camera_night = str(row.get("camera_night", "")).strip()
    camera_id = str(row.get("camera_id", "")).strip()
    if not source_ref or not camera_night or not camera_id:
        raise ValueError("source_ref, camera_night, and camera_id are required")
    return source_ref, camera_night, camera_id


def _canonical_row_key(row: CandidateRow) -> tuple[str, str, str, float, int, float, float, int]:
    """Choose one duplicate source row independently of the input stream order."""
    source_ref, camera_night, camera_id = _identity(row)
    return (
        source_ref,
        camera_night,
        camera_id,
        _float(row, "yolo_max_conf"),
        _int(row, "yolo_detection_count"),
        _float(row, "gme_visible_ratio"),
        _float(row, "gme_unknown_ratio"),
        _int(row, "gme_max_geckos"),
    )


def select_v22_candidate_sources(
    rows: Iterable[CandidateRow],
    *,
    policy: V22CandidatePolicy,
    excluded_source_refs: set[str] | None = None,
) -> list[dict[str, object]]:
    """Select each review bucket independently so shortages remain visible."""
    excluded = excluded_source_refs or set()
    classified: dict[str, list[CandidateRow]] = {
        bucket: [] for bucket in policy.frame_quotas
    }
    canonical_rows: dict[str, CandidateRow] = {}

    for row in rows:
        source_ref, _, _ = _identity(row)
        if source_ref in excluded:
            continue
        existing = canonical_rows.get(source_ref)
        if existing is None or _canonical_row_key(row) < _canonical_row_key(existing):
            canonical_rows[source_ref] = row

    for row in canonical_rows.values():
        bucket = classify_v22_candidate(row)
        if bucket in classified:
            classified[bucket].append(row)

    selected: list[dict[str, object]] = []
    selected_refs: set[str] = set()
    night_frames: Counter[str] = Counter()

    for bucket in policy.frame_quotas:
        remaining_bucket_frames = int(policy.frame_quotas[bucket])
        selected_sources = 0
        ranked = sorted(
            classified[bucket],
            key=lambda row: _rank(policy.seed, bucket, _identity(row)[0]),
        )
        for row in ranked:
            if selected_sources >= policy.source_quota(bucket):
                break
            source_ref, camera_night, camera_id = _identity(row)
            if source_ref in selected_refs:
                continue

            remaining_night_frames = (
                policy.max_frames_per_camera_night - night_frames[camera_night]
            )
            planned_frame_count = min(
                policy.frames_per_source,
                remaining_bucket_frames,
                remaining_night_frames,
            )
            if planned_frame_count < 1:
                continue

            selected.append(
                {
                    "source_ref": source_ref,
                    "camera_night": camera_night,
                    "camera_id": camera_id,
                    "candidate_bucket": bucket,
                    "strata_tags": _strata_tags(row, bucket),
                    "planned_frame_count": planned_frame_count,
                    "review_required": True,
                }
            )
            selected_refs.add(source_ref)
            night_frames[camera_night] += planned_frame_count
            remaining_bucket_frames -= planned_frame_count
            selected_sources += 1

    return selected

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any


CANONICAL_ACTIONS = {
    "basking",
    "defecating",
    "drinking",
    "eating_paste",
    "eating_prey",
    "hand_feeding",
    "moving",
    "shedding",
    "unseen",
}
CARE_ACTIONS = {
    "defecating",
    "drinking",
    "eating_paste",
    "eating_prey",
    "hand_feeding",
    "shedding",
}
VISIBILITY_VALUES = {"visible", "partial", "absent"}
HIGHLIGHT_VALUES = {"include", "exclude", "uncertain"}
JUDGEABILITY_VALUES = {"judgeable", "unjudgeable"}


def stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def assign_trust_tier(record: dict[str, Any]) -> str:
    if record.get("automatic") or record.get("tutorial") or not record.get("human"):
        return "X"
    if (
        record.get("blind")
        and record.get("immutable_initial_gt")
        and record.get("provenance_complete")
    ):
        return "T1"
    if record.get("provenance_complete"):
        return "T2"
    return "T3"


def canonicalize_targets(gt: dict[str, Any] | None) -> dict[str, str]:
    gt = gt or {}
    observed = gt.get("observed_actions")
    observed_set = set(observed) if isinstance(observed, list) else set()
    explicit_motion = gt.get("motion")
    if explicit_motion in {"moving", "static-only"}:
        motion = explicit_motion
    elif "moving" in observed_set:
        motion = "moving"
    elif "static" in observed_set and "moving" not in observed_set:
        motion = "static-only"
    else:
        motion = "unknown"

    visibility_raw = gt.get("visibility")
    visibility = visibility_raw if visibility_raw in VISIBILITY_VALUES else "unknown"

    action_raw = gt.get("primary_action")
    primary_action = action_raw if action_raw in CANONICAL_ACTIONS else "unknown"
    if primary_action in CARE_ACTIONS:
        care_event = "care"
    elif primary_action in CANONICAL_ACTIONS:
        care_event = "non-care"
    else:
        care_event = "unknown"

    highlight_raw = gt.get("highlight_recommendation", gt.get("highlight"))
    highlight = highlight_raw if highlight_raw in HIGHLIGHT_VALUES else "unavailable"
    judgeability_raw = gt.get("judgeability")
    judgeability = (
        judgeability_raw
        if judgeability_raw in JUDGEABILITY_VALUES
        else "unavailable"
    )
    return {
        "motion": motion,
        "visibility": visibility,
        "primary_action": primary_action,
        "care_event": care_event,
        "highlight": highlight,
        "judgeability": judgeability,
    }


def dedup_key(record: dict[str, Any]) -> tuple[str, str]:
    if record.get("source_fk_hash"):
        return "exact_source_fk", str(record["source_fk_hash"])
    if record.get("object_key_hash"):
        return "exact_object", str(record["object_key_hash"])
    if record.get("content_hash"):
        return "exact_content", str(record["content_hash"])
    probable_parts = (
        record.get("camera_hash"),
        record.get("started_at_epoch"),
        record.get("duration_ms"),
        record.get("size_bytes"),
    )
    if all(value is not None for value in probable_parts):
        return "probable_capture", stable_hash(probable_parts)
    return "record_only", str(
        record.get("canonical_clip_key")
        or record.get("source_record_hash")
        or record.get("record_hash")
        or stable_hash(record)
    )


def group_episodes(
    records: list[dict[str, Any]],
    gap_seconds: int = 300,
) -> list[dict[str, Any]]:
    ordered = sorted(
        (dict(record) for record in records),
        key=lambda item: (
            str(item.get("camera_hash", "")),
            int(item.get("started_at_epoch", 0)),
            str(item.get("source_record_hash", item.get("record_hash", ""))),
        ),
    )
    previous_by_camera: dict[str, int] = {}
    episode_number_by_camera: defaultdict[str, int] = defaultdict(int)
    for record in ordered:
        camera = str(record.get("camera_hash", "unknown-camera"))
        started_at = int(record.get("started_at_epoch", 0))
        previous = previous_by_camera.get(camera)
        if previous is None or started_at - previous > gap_seconds:
            episode_number_by_camera[camera] += 1
        episode_number = episode_number_by_camera[camera]
        record["episode_group_hash"] = stable_hash([camera, episode_number])
        previous_by_camera[camera] = started_at
    return ordered


def summarize_sources(records: list[dict[str, Any]]) -> dict[str, Any]:
    source_rows: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        source_rows[str(record["source"])].append(record)
    return {
        "total_rows": len(records),
        "unique_clips": len(
            {str(record["canonical_clip_key"]) for record in records}
        ),
        "sources": {
            source: {
                "rows": len(rows),
                "unique_clips": len(
                    {str(record["canonical_clip_key"]) for record in rows}
                ),
            }
            for source, rows in sorted(source_rows.items())
        },
        "trust_tiers": dict(
            sorted(Counter(str(record["trust_tier"]) for record in records).items())
        ),
    }


def summarize_overlap(records: list[dict[str, Any]]) -> dict[str, Any]:
    sources_by_clip: defaultdict[str, set[str]] = defaultdict(set)
    for record in records:
        sources_by_clip[str(record["canonical_clip_key"])].add(str(record["source"]))
    pair_counts: Counter[str] = Counter()
    for sources in sources_by_clip.values():
        for left, right in combinations(sorted(sources), 2):
            pair_counts[f"{left}|{right}"] += 1
    return {
        "source_pairs": {
            pair: {"exact_unique_clips": count}
            for pair, count in sorted(pair_counts.items())
        }
    }

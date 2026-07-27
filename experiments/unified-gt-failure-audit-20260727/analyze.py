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
CAUSE_TO_CANDIDATE = {
    "VISIBILITY_SCALE_OCCLUSION": "visibility_bbox_roi_experiment",
    "TEMPORAL_SAMPLING": "segment_aware_sampling_experiment",
    "IR_LIGHT_REFLECTION": "ir_illumination_evidence_experiment",
    "CAMERA_DOMAIN": "camera_stratified_calibration_audit",
    "SEMANTIC_ONTOLOGY": "ontology_prompt_blind_experiment",
    "INPUT_QUALITY": "judgeability_abstention_experiment",
    "EVIDENCE_SPURIOUS_OR_MISSING": "evidence_sensor_ablation",
    "GT_AMBIGUITY_OR_ERROR": "human_relabel_agreement_audit",
    "PIPELINE_PROVENANCE": "provenance_pipeline_fix_audit",
    "OTHER_UNRESOLVED": "manual_failure_review",
}


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


def derive_failures(record: dict[str, Any]) -> list[dict[str, Any]]:
    """사람 GT와 기존 결과의 불일치만 만든다.

    candidate_causes는 원인 정답이 아니라 후속 blind review 후보로 그대로 보존한다.
    """
    if record.get("trust_tier") not in {"T1", "T2"}:
        return []
    gt = record.get("gt") or {}
    candidate_causes = list(record.get("candidate_causes") or [])
    failures: list[dict[str, Any]] = []

    vlm = record.get("vlm") or {}
    vlm_status = vlm.get("status")
    if vlm_status in {"success", "succeeded"}:
        gt_action = gt.get("primary_action")
        vlm_action = vlm.get("primary_action")
        if (
            gt_action not in {None, "unknown"}
            and vlm_action not in {None, "unknown"}
            and gt_action != vlm_action
        ):
            failures.append(
                {
                    "failure_kind": "vlm_primary_action_mismatch",
                    "candidate_causes": candidate_causes,
                }
            )
        gt_care = gt.get("care_event")
        vlm_care = vlm.get("care_event")
        if gt_care == "care" and vlm_care == "non-care":
            failures.append(
                {
                    "failure_kind": "vlm_care_false_negative",
                    "candidate_causes": candidate_causes,
                    "care_or_highlight_miss": True,
                }
            )
        if gt_care == "non-care" and vlm_care == "care":
            failures.append(
                {
                    "failure_kind": "vlm_care_false_positive",
                    "candidate_causes": candidate_causes,
                }
            )

    gate = record.get("gate") or {}
    if gate.get("status") in {None, "ok"} and isinstance(gate.get("present"), bool):
        gt_visibility = gt.get("visibility")
        if gt_visibility == "absent" and gate["present"]:
            failures.append(
                {
                    "failure_kind": "gate_visibility_false_positive",
                    "candidate_causes": candidate_causes,
                }
            )
        elif gt_visibility in {"visible", "partial"} and not gate["present"]:
            failures.append(
                {
                    "failure_kind": "gate_visibility_false_negative",
                    "candidate_causes": candidate_causes,
                }
            )

    evidence = record.get("evidence")
    if evidence is not None and (
        evidence.get("level0_status") != "ok"
        or evidence.get("level1_status") != "ok"
    ):
        failures.append(
            {
                "failure_kind": "python_evidence_pipeline_failure",
                "candidate_causes": candidate_causes,
            }
        )
    return failures


def rank_causes(failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_cause: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    all_error_episodes = {
        str(row["episode_group_hash"])
        for row in failures
        if row.get("episode_group_hash") is not None
    }
    for row in failures:
        if row.get("trust_tier") not in {"T1", "T2"} or not row.get("cause"):
            continue
        by_cause[str(row["cause"])].append(row)

    ranked: list[dict[str, Any]] = []
    for cause, rows in by_cause.items():
        by_episode: dict[str, dict[str, Any]] = {}
        for row in rows:
            by_episode.setdefault(str(row["episode_group_hash"]), row)
        episode_rows = list(by_episode.values())
        episodes = len(episode_rows)
        camera_nights = len(
            {str(row["camera_night_hash"]) for row in episode_rows}
        )
        sources = len({str(row["source"]) for row in episode_rows})
        duplicate_counts = Counter(
            str(row["duplicate_group_hash"]) for row in episode_rows
        )
        largest_duplicate_share = (
            max(duplicate_counts.values()) / episodes if episodes else 1.0
        )
        care_miss_episodes = len(
            {
                str(row["episode_group_hash"])
                for row in episode_rows
                if row.get("care_or_highlight_miss")
            }
        )
        qualified = (
            episodes >= 10
            and camera_nights >= 2
            and largest_duplicate_share <= 0.20
        )
        ranked.append(
            {
                "cause": cause,
                "qualified": qualified,
                "independent_episodes": episodes,
                "camera_nights": camera_nights,
                "source_count": sources,
                "largest_duplicate_share": round(largest_duplicate_share, 6),
                "care_highlight_miss_episodes": care_miss_episodes,
                "addressable_error_mass": round(
                    episodes / len(all_error_episodes), 6
                )
                if all_error_episodes
                else 0.0,
            }
        )
    return sorted(
        ranked,
        key=lambda item: (
            not item["qualified"],
            -item["independent_episodes"],
            -item["care_highlight_miss_episodes"],
            -item["camera_nights"],
            -item["source_count"],
            item["cause"],
        ),
    )


def summarize_failures(records: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    candidate_counts: Counter[str] = Counter()
    for record in records:
        for failure in derive_failures(record):
            base = {
                "episode_group_hash": record.get("episode_group_hash"),
                "camera_night_hash": record.get("camera_night_hash"),
                "source": record.get("source"),
                "duplicate_group_hash": record.get("duplicate_group_hash"),
                "trust_tier": record.get("trust_tier"),
                **failure,
            }
            for cause in failure.get("candidate_causes", []):
                candidate_counts[str(cause)] += 1
            for cause in record.get("confirmed_causes", []):
                failures.append({**base, "cause": cause})
    ranked = rank_causes(failures)
    verdict, candidate = decide_verdict({"ranked_causes": ranked})
    return {
        "failure_rows_with_confirmed_cause": len(failures),
        "candidate_cause_mentions": dict(sorted(candidate_counts.items())),
        "ranked_causes": ranked,
        "top_causes": ranked[:3],
        "next_candidate": candidate,
        "verdict": verdict,
    }


def decide_verdict(summary: dict[str, Any]) -> tuple[str, dict[str, str] | None]:
    qualified = [
        cause for cause in summary.get("ranked_causes", []) if cause.get("qualified")
    ]
    if not qualified:
        return (
            "UNIFIED_GT_FAILURE_AUDIT_HOLD_INSUFFICIENT_INDEPENDENT_ERRORS",
            None,
        )
    candidate_id = CAUSE_TO_CANDIDATE[str(qualified[0]["cause"])]
    return "UNIFIED_GT_FAILURE_AUDIT_READY_FOR_REVIEW", {"id": candidate_id}

"""Independent GT validation and scoring for the frozen boundary study."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from scripts.prepare_rba_event_grouping_shadow import (
    BoundaryPair,
    write_private_new,
)

BoundaryDecision = Literal["same_event", "different_event", "uncertain"]
ALLOWED_DECISIONS = frozenset(
    {"same_event", "different_event", "uncertain"}
)
THRESHOLD_CANDIDATES = (0, 5, 15, 30, 60, 120)


class GTIntegrityError(ValueError):
    """A frozen GT or scoring provenance contract was violated."""


@dataclass(frozen=True, slots=True)
class ValidatedReviewer:
    decisions: dict[str, BoundaryDecision]
    fingerprint: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class FinalizedGT:
    decisions: dict[str, BoundaryDecision]
    raw_agreement: float
    unresolved_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class HoldoutMetrics:
    expected_pair_count: int
    reviewer_agreement: float
    uncertain_rate: float
    over_merge_count: int
    camera_over_merge_counts: dict[str, int]
    over_split_rate: float
    camera_over_split_rates: dict[str, float]
    camera_class_counts: dict[str, dict[str, int]]
    event_reduction_rate: float
    accounting_unassigned: int
    accounting_duplicates: int
    diagnostic_cross_merges: int
    protected_clip_contacts: int
    rerun_hashes: tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class ScoreSummary:
    verdict: str
    threshold_sec: int
    metrics_sha256: str


def _canonical(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _require_digest(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise GTIntegrityError(f"invalid_{field}")
    return value


def validate_reviewer_rows(
    rows: list[dict[str, object]],
    expected_pair_ids: set[str],
) -> ValidatedReviewer:
    decisions: dict[str, BoundaryDecision] = {}
    fingerprints: set[str] = set()
    source_hashes: set[str] = set()
    for row in rows:
        forbidden = {
            key
            for key in row
            if key.lower() in {"clip_id", "left_clip_id", "right_clip_id"}
        }
        if forbidden:
            raise GTIntegrityError("raw_clip_id_in_reviewer_row")
        pair_id = row.get("pair_id")
        decision = row.get("decision")
        reason = row.get("reason")
        fingerprint = row.get("reviewer_fingerprint")
        if not isinstance(pair_id, str) or pair_id in decisions:
            raise GTIntegrityError("duplicate_or_invalid_pair_id")
        if decision not in ALLOWED_DECISIONS:
            raise GTIntegrityError("invalid_decision")
        if reason is not None and (
            not isinstance(reason, str) or len(reason) > 200
        ):
            raise GTIntegrityError("invalid_reason")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise GTIntegrityError("invalid_reviewer_fingerprint")
        fingerprints.add(fingerprint)
        source_hashes.add(_require_digest(row.get("source_sha256"), "source_sha256"))
        decisions[pair_id] = decision  # type: ignore[assignment]

    if set(decisions) != expected_pair_ids:
        raise GTIntegrityError("reviewer_pair_set_mismatch")
    if len(fingerprints) != 1 or len(source_hashes) != 1:
        raise GTIntegrityError("reviewer_provenance_mismatch")
    return ValidatedReviewer(
        decisions=decisions,
        fingerprint=next(iter(fingerprints)),
        source_sha256=next(iter(source_hashes)),
    )


def finalize_boundary_gt(
    expected_pair_ids: set[str],
    reviewer_a: ValidatedReviewer,
    reviewer_b: ValidatedReviewer,
    owner_rows: list[dict[str, object]],
) -> FinalizedGT:
    if reviewer_a.fingerprint == reviewer_b.fingerprint:
        raise GTIntegrityError("reviewer_fingerprint_collision")
    if reviewer_a.source_sha256 != reviewer_b.source_sha256:
        raise GTIntegrityError("reviewer_source_mismatch")

    required_owner = {
        pair_id
        for pair_id in expected_pair_ids
        if reviewer_a.decisions[pair_id] != reviewer_b.decisions[pair_id]
        or reviewer_a.decisions[pair_id] == "uncertain"
        or reviewer_b.decisions[pair_id] == "uncertain"
    }
    owner: dict[str, BoundaryDecision] = {}
    for row in owner_rows:
        pair_id = row.get("pair_id")
        decision = row.get("decision")
        reason = row.get("reason")
        if (
            not isinstance(pair_id, str)
            or pair_id in owner
            or decision not in ALLOWED_DECISIONS
        ):
            raise GTIntegrityError("invalid_owner_row")
        if reason is not None and (
            not isinstance(reason, str) or len(reason) > 200
        ):
            raise GTIntegrityError("invalid_owner_reason")
        if any("clip_id" in key.lower() for key in row):
            raise GTIntegrityError("raw_clip_id_in_owner_row")
        owner[pair_id] = decision  # type: ignore[assignment]
    if set(owner) - required_owner:
        raise GTIntegrityError("unnecessary_owner_adjudication")
    if set(owner) != required_owner:
        raise GTIntegrityError("missing_owner_adjudication")

    final: dict[str, BoundaryDecision] = {}
    for pair_id in sorted(expected_pair_ids):
        a_value = reviewer_a.decisions[pair_id]
        b_value = reviewer_b.decisions[pair_id]
        final[pair_id] = (
            a_value
            if a_value == b_value and a_value != "uncertain"
            else owner[pair_id]
        )
    raw_agreement = (
        sum(
            reviewer_a.decisions[pair_id] == reviewer_b.decisions[pair_id]
            for pair_id in expected_pair_ids
        )
        / len(expected_pair_ids)
        if expected_pair_ids
        else 0.0
    )
    digest = hashlib.sha256(_canonical(final)).hexdigest()
    return FinalizedGT(final, raw_agreement, 0, digest)


def choose_development_threshold(
    pairs: tuple[BoundaryPair, ...],
    final_decisions: dict[str, BoundaryDecision],
) -> int:
    pair_ids = {item.pair_id for item in pairs}
    if pair_ids != set(final_decisions):
        raise GTIntegrityError("development_pair_set_mismatch")
    candidates: list[tuple[int, int]] = []
    for threshold in THRESHOLD_CANDIDATES:
        over_merge = 0
        over_split = 0
        for item in pairs:
            final = final_decisions[item.pair_id]
            if final == "uncertain":
                continue
            predicted_same = item.gap_sec <= threshold
            over_merge += int(final == "different_event" and predicted_same)
            over_split += int(final == "same_event" and not predicted_same)
        if over_merge == 0:
            candidates.append((over_split, threshold))
    if not candidates:
        raise GTIntegrityError("no_zero_overmerge_threshold")
    return min(candidates)[1]


def freeze_development_threshold(
    path: Path,
    *,
    threshold_sec: int,
    manifest_sha256: str,
    development_gt_sha256: str,
) -> str:
    if threshold_sec not in THRESHOLD_CANDIDATES:
        raise GTIntegrityError("invalid_frozen_threshold")
    payload = {
        "schema_version": "rba-event-threshold-freeze-v1",
        "threshold_sec": threshold_sec,
        "manifest_sha256": _require_digest(
            manifest_sha256, "manifest_sha256"
        ),
        "development_gt_sha256": _require_digest(
            development_gt_sha256, "development_gt_sha256"
        ),
    }
    return write_private_new(path, payload)


def _load_freeze(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GTIntegrityError("invalid_freeze_record") from exc
    if not isinstance(payload, dict):
        raise GTIntegrityError("invalid_freeze_record")
    return payload


def _metrics_payload(metrics: HoldoutMetrics) -> dict[str, object]:
    return {
        field: getattr(metrics, field)
        for field in metrics.__dataclass_fields__
    }


def _holdout_verdict(metrics: HoldoutMetrics) -> str:
    integrity_failure = (
        metrics.accounting_unassigned > 0
        or metrics.accounting_duplicates > 0
        or metrics.diagnostic_cross_merges > 0
        or metrics.protected_clip_contacts > 0
        or metrics.over_merge_count > 0
        or any(metrics.camera_over_merge_counts.values())
        or len(set(metrics.rerun_hashes)) != 1
        or metrics.over_split_rate > 0.25
        or any(rate > 0.30 for rate in metrics.camera_over_split_rates.values())
    )
    if integrity_failure:
        return "REJECT"
    class_diversity = all(
        counts.get("same_event", 0) >= 1
        and counts.get("different_event", 0) >= 1
        for counts in metrics.camera_class_counts.values()
    )
    insufficient = (
        metrics.expected_pair_count != 60
        or not class_diversity
        or metrics.reviewer_agreement < 0.80
        or metrics.uncertain_rate > 0.25
        or metrics.event_reduction_rate < 0.15
    )
    return "HOLD" if insufficient else "ADOPT_SHADOW_GROUPING_V1"


def score_frozen_holdout(
    *,
    freeze_path: Path,
    threshold_sec: int,
    manifest_sha256: str,
    metrics: HoldoutMetrics,
    output_path: Path,
) -> ScoreSummary:
    freeze = _load_freeze(freeze_path)
    if freeze.get("threshold_sec") != threshold_sec:
        raise GTIntegrityError("holdout_threshold_mismatch")
    if freeze.get("manifest_sha256") != manifest_sha256:
        raise GTIntegrityError("holdout_manifest_mismatch")
    metrics_payload = _metrics_payload(metrics)
    metrics_sha256 = hashlib.sha256(_canonical(metrics_payload)).hexdigest()
    verdict = _holdout_verdict(metrics)
    write_private_new(
        output_path,
        {
            "schema_version": "rba-event-holdout-score-v1",
            "threshold_sec": threshold_sec,
            "manifest_sha256": manifest_sha256,
            "metrics_sha256": metrics_sha256,
            "verdict": verdict,
        },
    )
    return ScoreSummary(verdict, threshold_sec, metrics_sha256)

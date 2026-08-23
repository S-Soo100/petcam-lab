"""Strict, independent scorer for the frozen GME-negative calibration audit.

The scorer consumes a canonical Task 1 manifest and an immutable read-only DB
export.  It never updates the audit database, R2, GME runs, or existing GT.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
from statistics import NormalDist
from typing import Protocol
from uuid import UUID

if __package__:
    from scripts.gme_negative_audit_sampling import (
        CHECKPOINT_SHA256,
        DETECTOR_IDENTITY,
        SCHEMA_VERSION,
        _canonical_json,
    )
else:
    # `python scripts/...py` puts scripts/ rather than the repo root on sys.path.
    from gme_negative_audit_sampling import (  # type: ignore[no-redef]
        CHECKPOINT_SHA256,
        DETECTOR_IDENTITY,
        SCHEMA_VERSION,
        _canonical_json,
    )


LEDGER_SCHEMA_VERSION = "gme-negative-audit-score-ledger-v1"
SAFE_SCHEMA_VERSION = "gme-negative-audit-score-safe-v1"
_MANIFEST_SHA_RULE = "sha256(utf8-canonical-json-v1-excluding-manifest_sha256)"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")
_DECIMAL = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_VERDICTS = frozenset({"gecko_present", "gecko_absent", "uncertain", "media_error"})
_DECISIONS = frozenset(
    {"include_candidate", "exclude_duplicate", "exclude_holdout", "exclude_quality", "defer"}
)
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "batch_kind",
        "test_sheet_sha256",
        "seed",
        "cutoff",
        "detector_identity",
        "checkpoint_sha256",
        "candidate_counts",
        "source_pools",
        "selection_sha256",
        "protected_manifest_sha256",
        "manifest_sha256_rule",
        "items",
        "manifest_sha256",
    }
)
_MANIFEST_ITEM_KEYS = frozenset(
    {
        "ordinal",
        "clip_id",
        "stratum",
        "started_at",
        "duration_sec",
        "camera_night_key",
        "episode_key",
        "gme_run_id",
        "detector_identity",
        "media_sha256",
        "media_dhash",
        "gme_detected",
        "human_gt_digest",
        "selection_provenance",
    }
)
_LEDGER_KEYS = frozenset(
    {
        "schema_version",
        "manifest_raw_sha256",
        "batch",
        "items",
        "submissions",
        "corrections",
        "adjudications",
        "dataset_decisions",
    }
)
_BATCH_KEYS = frozenset(
    {
        "id",
        "owner_id",
        "schema_version",
        "batch_kind",
        "manifest_sha256",
        "expected_negative_count",
        "expected_control_count",
        "expected_total_count",
    }
)
_LEDGER_ITEM_KEYS = _MANIFEST_ITEM_KEYS | frozenset(
    {"id", "batch_id", "assigned_reviewer_id", "media_sha256_before", "media_sha256_after"}
)
_SUBMISSION_KEYS = frozenset(
    {
        "id",
        "item_id",
        "reviewer_id",
        "verdict",
        "representative_sec",
        "bbox",
        "digest",
        "created_at",
    }
)
_CORRECTION_KEYS = frozenset(
    {
        "id",
        "item_id",
        "original_submission_id",
        "reviewer_id",
        "verdict",
        "representative_sec",
        "bbox",
        "reason",
        "expected_submission_digest",
        "digest",
        "created_at",
    }
)
_ADJUDICATION_KEYS = frozenset(
    {
        "id",
        "item_id",
        "original_submission_id",
        "owner_id",
        "final_verdict",
        "representative_sec",
        "bbox",
        "reason",
        "effective_submission_digest",
        "digest",
        "created_at",
    }
)
_DATASET_DECISION_KEYS = frozenset(
    {
        "id",
        "item_id",
        "owner_id",
        "decision",
        "reason",
        "effective_submission_digest",
        "adjudication_id",
        "digest",
        "created_at",
    }
)
_BBOX_KEYS = frozenset({"x", "y", "width", "height"})


class ScoreContractError(ValueError):
    """Raised when frozen scoring inputs do not satisfy the exact contract."""


class AuditLedgerReader(Protocol):
    """Narrow read-only boundary used by the CLI/export coordinator."""

    def export_batch_read_only(self, batch_id: str) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class AuditScore:
    random_negative: int
    negative_valid: int
    negative_present: int
    negative_absent: int
    negative_uncertain: int
    negative_media_error: int
    negative_pool_gecko_prevalence: float | None
    negative_pool_gecko_prevalence_wilson95: tuple[float, float] | None
    control_total: int
    control_detected: int
    control_absent: int
    control_uncertain: int
    control_media_error: int
    control_detection_rate: float | None
    control_detection_wilson95: tuple[float, float] | None
    stratum_counts: dict[str, int]
    camera_night_counts: dict[str, int]
    duplicate_clip_count: int
    duplicate_media_count: int
    duplicate_dhash_count: int
    present_total: int
    valid_bbox_count: int

    @property
    def valid_bbox_ratio(self) -> float | None:
        return self.valid_bbox_count / self.present_total if self.present_total else None

    def safe_aggregate(self, batch_id: str) -> dict[str, object]:
        anonymized_nights = {
            f"night-{index:03d}": self.camera_night_counts[key]
            for index, key in enumerate(sorted(self.camera_night_counts), start=1)
        }
        return {
            "schema_version": SAFE_SCHEMA_VERSION,
            "batch_id": batch_id,
            "random_negative": {
                "total": self.random_negative,
                "valid": self.negative_valid,
                "present": self.negative_present,
                "absent": self.negative_absent,
                "uncertain": self.negative_uncertain,
                "media_error": self.negative_media_error,
                "gecko_prevalence": self.negative_pool_gecko_prevalence,
                "gecko_prevalence_wilson95": _interval_json(
                    self.negative_pool_gecko_prevalence_wilson95
                ),
            },
            "positive_control": {
                "total": self.control_total,
                "detected": self.control_detected,
                "absent": self.control_absent,
                "uncertain": self.control_uncertain,
                "media_error": self.control_media_error,
                "detection_rate": self.control_detection_rate,
                "detection_wilson95": _interval_json(self.control_detection_wilson95),
            },
            "descriptive": {
                "stratum_counts": dict(sorted(self.stratum_counts.items())),
                "camera_night_counts": anonymized_nights,
                "duplicate_counts": {
                    "clip": self.duplicate_clip_count,
                    "media": self.duplicate_media_count,
                    "dhash": self.duplicate_dhash_count,
                },
                "bbox_coverage": {
                    "present": self.present_total,
                    "valid": self.valid_bbox_count,
                    "ratio": self.valid_bbox_ratio,
                },
            },
        }


@dataclass(frozen=True, slots=True)
class _EffectiveVerdict:
    verdict: str
    representative_sec: float | None
    bbox: dict[str, float] | None
    digest: str


def wilson_interval95(successes: int, total: int) -> tuple[float, float] | None:
    """Return the two-sided 95% Wilson score interval without NaN fallbacks."""
    if (
        isinstance(successes, bool)
        or isinstance(total, bool)
        or not isinstance(successes, int)
        or not isinstance(total, int)
        or successes < 0
        or total < 0
        or successes > total
    ):
        raise ScoreContractError("invalid Wilson counts")
    if total == 0:
        return None
    z = NormalDist().inv_cdf(0.975)
    observed = successes / total
    z_squared = z * z
    denominator = 1 + z_squared / total
    center = (observed + z_squared / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            observed * (1 - observed) / total + z_squared / (4 * total * total)
        )
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def score_audit(
    manifest: Mapping[str, object], ledger: Mapping[str, object]
) -> AuditScore:
    """Validate immutable inputs and calculate descriptive audit metrics."""
    manifest_items, canonical_manifest_raw_sha = _validate_manifest(manifest)
    validated = _validate_ledger(manifest, manifest_items, canonical_manifest_raw_sha, ledger)
    items = validated["items"]
    effective = validated["effective"]

    by_stratum: dict[str, Counter[str]] = {
        "random_negative": Counter(),
        "positive_control": Counter(),
    }
    camera_nights: Counter[str] = Counter()
    present_total = 0
    valid_bbox_count = 0
    for item in items:
        item_id = str(item["id"])
        verdict = effective[item_id]
        stratum = str(item["stratum"])
        by_stratum[stratum][verdict.verdict] += 1
        camera_nights[str(item["camera_night_key"])] += 1
        if verdict.verdict == "gecko_present":
            present_total += 1
            if verdict.bbox is not None:
                valid_bbox_count += 1

    negative = by_stratum["random_negative"]
    control = by_stratum["positive_control"]
    negative_valid = negative["gecko_present"] + negative["gecko_absent"]
    control_total = sum(control.values())
    media_counts = Counter(str(item["media_sha256"]) for item in items)
    clip_counts = Counter(str(item["clip_id"]) for item in items)
    dhash_counts = Counter(str(item["media_dhash"]) for item in items)
    return AuditScore(
        random_negative=sum(negative.values()),
        negative_valid=negative_valid,
        negative_present=negative["gecko_present"],
        negative_absent=negative["gecko_absent"],
        negative_uncertain=negative["uncertain"],
        negative_media_error=negative["media_error"],
        negative_pool_gecko_prevalence=(
            negative["gecko_present"] / negative_valid if negative_valid else None
        ),
        negative_pool_gecko_prevalence_wilson95=wilson_interval95(
            negative["gecko_present"], negative_valid
        ),
        control_total=control_total,
        control_detected=control["gecko_present"],
        control_absent=control["gecko_absent"],
        control_uncertain=control["uncertain"],
        control_media_error=control["media_error"],
        control_detection_rate=(
            control["gecko_present"] / control_total if control_total else None
        ),
        control_detection_wilson95=wilson_interval95(
            control["gecko_present"], control_total
        ),
        stratum_counts={key: sum(value.values()) for key, value in by_stratum.items()},
        camera_night_counts=dict(camera_nights),
        duplicate_clip_count=sum(count - 1 for count in clip_counts.values() if count > 1),
        duplicate_media_count=sum(count - 1 for count in media_counts.values() if count > 1),
        duplicate_dhash_count=sum(count - 1 for count in dhash_counts.values() if count > 1),
        present_total=present_total,
        valid_bbox_count=valid_bbox_count,
    )


def export_score_batch(
    manifest: Mapping[str, object],
    *,
    batch_id: str,
    private_ledger_path: Path | str,
    safe_aggregate_path: Path | str,
    reader: AuditLedgerReader | None = None,
) -> AuditScore:
    """Read once through an injected SELECT-only reader and create both artifacts once."""
    _require_uuid(batch_id, "batch_id")
    private_path = Path(private_ledger_path)
    safe_path = Path(safe_aggregate_path)
    # Fail before the DB/export boundary when retrying an already claimed output path.
    for path in (private_path, safe_path):
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
    if reader is None:
        raise ScoreContractError("a read-only ledger reader is required")
    try:
        exported = reader.export_batch_read_only(batch_id)
    except ScoreContractError:
        raise
    except Exception as error:
        raise ScoreContractError("read-only ledger export failed") from error
    if not isinstance(exported, Mapping):
        raise ScoreContractError("read-only ledger reader returned an invalid export")
    score = score_audit(manifest, exported)
    batch = _record(exported.get("batch"), "ledger batch")
    if batch.get("id") != batch_id:
        raise ScoreContractError("read-only ledger batch id mismatch")
    _write_json_new(private_path, exported)
    _write_json_new(safe_path, score.safe_aggregate(batch_id))
    return score


def _validate_manifest(
    manifest: Mapping[str, object],
) -> tuple[list[dict[str, object]], str]:
    row = _record(manifest, "manifest")
    _exact_keys(row, _MANIFEST_KEYS, "manifest")
    if row["schema_version"] != SCHEMA_VERSION or row["status"] != "prepared":
        raise ScoreContractError("manifest schema/status mismatch")
    if row["batch_kind"] != "calibration":
        raise ScoreContractError("scorer requires a calibration manifest")
    for key in ("test_sheet_sha256", "checkpoint_sha256", "selection_sha256", "manifest_sha256"):
        _require_sha(row[key], f"manifest {key}")
    if row["checkpoint_sha256"] != CHECKPOINT_SHA256:
        raise ScoreContractError("manifest checkpoint pin mismatch")
    if row["detector_identity"] != DETECTOR_IDENTITY:
        raise ScoreContractError("manifest detector pin mismatch")
    if row["manifest_sha256_rule"] != _MANIFEST_SHA_RULE:
        raise ScoreContractError("manifest SHA rule mismatch")
    _require_rfc3339(row["cutoff"], "manifest cutoff")
    if not isinstance(row["seed"], str) or not row["seed"]:
        raise ScoreContractError("manifest seed is invalid")
    candidate_counts = _record(row["candidate_counts"], "manifest candidate_counts")
    _exact_keys(candidate_counts, frozenset({"random_negative", "positive_control"}), "manifest candidate_counts")
    _require_count(candidate_counts["random_negative"], "candidate random_negative", minimum=120)
    _require_count(candidate_counts["positive_control"], "candidate positive_control", minimum=30)
    source_pools = _record(row["source_pools"], "manifest source_pools")
    _exact_keys(source_pools, frozenset({"random_negative", "positive_control"}), "manifest source_pools")
    for stratum in ("random_negative", "positive_control"):
        pool = _record(source_pools[stratum], f"manifest {stratum} pool")
        _exact_keys(pool, frozenset({"count", "sha256"}), f"manifest {stratum} pool")
        if pool["count"] != candidate_counts[stratum]:
            raise ScoreContractError("manifest source pool count mismatch")
        _require_sha(pool["sha256"], f"manifest {stratum} pool SHA")
    protected = row["protected_manifest_sha256"]
    if not isinstance(protected, list) or protected != sorted(set(protected)):
        raise ScoreContractError("manifest protected SHA list is not canonical")
    for digest in protected:
        _require_sha(digest, "manifest protected SHA")

    unsigned = dict(row)
    unsigned.pop("manifest_sha256")
    internal_sha = hashlib.sha256(_canonical_json(unsigned)).hexdigest()
    if row["manifest_sha256"] != internal_sha:
        raise ScoreContractError("manifest canonical digest mismatch")
    canonical_bytes = _canonical_json(row) + b"\n"
    items_raw = row["items"]
    if not isinstance(items_raw, list) or len(items_raw) != 150:
        raise ScoreContractError("manifest requires exactly 150 items")
    items: list[dict[str, object]] = []
    clip_ids: set[str] = set()
    media: set[str] = set()
    counts = Counter()
    blind_ranks: list[str] = []
    seed = str(row["seed"])
    for expected_ordinal, value in enumerate(items_raw, start=1):
        item = _record(value, "manifest item")
        _exact_keys(item, _MANIFEST_ITEM_KEYS, "manifest item")
        if item["ordinal"] != expected_ordinal:
            raise ScoreContractError("manifest item order is not exact")
        _validate_frozen_item(item, row)
        clip_id = str(item["clip_id"])
        media_sha = str(item["media_sha256"])
        if clip_id in clip_ids or media_sha in media:
            raise ScoreContractError("manifest item identity is not unique")
        clip_ids.add(clip_id)
        media.add(media_sha)
        counts[str(item["stratum"])] += 1
        candidate = {key: item[key] for key in _MANIFEST_ITEM_KEYS - {"ordinal", "selection_provenance"}}
        expected_provenance = hashlib.sha256(
            _canonical_json({"seed": seed, "ordinal": expected_ordinal, "candidate": candidate})
        ).hexdigest()
        if item["selection_provenance"] != expected_provenance:
            raise ScoreContractError("manifest selection provenance mismatch")
        blind_ranks.append(
            hashlib.sha256(
                f"{seed}:blind-order:{item['stratum']}:{clip_id}".encode("utf-8")
            ).hexdigest()
        )
        items.append(item)
    if counts != Counter({"random_negative": 120, "positive_control": 30}):
        raise ScoreContractError("manifest stratum count mismatch")
    if blind_ranks != sorted(blind_ranks):
        raise ScoreContractError("manifest blind order mismatch")
    return items, hashlib.sha256(canonical_bytes).hexdigest()


def _validate_frozen_item(item: Mapping[str, object], manifest: Mapping[str, object]) -> None:
    _require_count(item["ordinal"], "manifest ordinal", minimum=1)
    _require_uuid(item["clip_id"], "manifest clip_id")
    _require_rfc3339(item["started_at"], "manifest started_at")
    _require_decimal(item["duration_sec"], "manifest duration_sec")
    _require_uuid(item["gme_run_id"], "manifest gme_run_id")
    _require_sha(item["media_sha256"], "manifest media SHA")
    _require_hex16(item["media_dhash"], "manifest media dHash")
    _require_sha(item["selection_provenance"], "manifest selection provenance")
    for key in ("camera_night_key", "episode_key"):
        if not isinstance(item[key], str) or not item[key]:
            raise ScoreContractError(f"manifest {key} is invalid")
    if item["detector_identity"] != manifest["detector_identity"]:
        raise ScoreContractError("manifest item detector mismatch")
    if type(item["gme_detected"]) is not bool:
        raise ScoreContractError("manifest item gme_detected must be a bool")
    stratum = item["stratum"]
    if stratum == "random_negative":
        if item["gme_detected"] is not False or item["human_gt_digest"] is not None:
            raise ScoreContractError("manifest random_negative shape mismatch")
    elif stratum == "positive_control":
        _require_sha(item["human_gt_digest"], "manifest control GT digest")
    else:
        raise ScoreContractError("manifest stratum is invalid")


def _validate_ledger(
    manifest: Mapping[str, object],
    manifest_items: Sequence[Mapping[str, object]],
    manifest_raw_sha: str,
    ledger: Mapping[str, object],
) -> dict[str, object]:
    row = _record(ledger, "ledger")
    _exact_keys(row, _LEDGER_KEYS, "ledger")
    if row["schema_version"] != LEDGER_SCHEMA_VERSION:
        raise ScoreContractError("ledger schema mismatch")
    if row["manifest_raw_sha256"] != manifest_raw_sha:
        raise ScoreContractError("manifest raw SHA pin mismatch")
    batch = _record(row["batch"], "ledger batch")
    _exact_keys(batch, _BATCH_KEYS, "ledger batch")
    batch_id = _require_uuid(batch["id"], "ledger batch id")
    owner_id = _require_uuid(batch["owner_id"], "ledger owner id")
    if (
        batch["schema_version"] != SCHEMA_VERSION
        or batch["batch_kind"] != "calibration"
        or batch["manifest_sha256"] != manifest["manifest_sha256"]
        or batch["expected_negative_count"] != 120
        or batch["expected_control_count"] != 30
        or batch["expected_total_count"] != 150
    ):
        raise ScoreContractError("ledger batch pin/count mismatch")

    items_raw = _list(row["items"], "ledger items")
    if len(items_raw) != 150:
        raise ScoreContractError("ledger requires exactly 150 items")
    items: list[dict[str, object]] = []
    item_by_id: dict[str, dict[str, object]] = {}
    for frozen, value in zip(manifest_items, items_raw, strict=True):
        item = _record(value, "ledger item")
        _exact_keys(item, _LEDGER_ITEM_KEYS, "ledger item")
        item_id = _require_uuid(item["id"], "ledger item id")
        if item_id in item_by_id:
            raise ScoreContractError("ledger item id is not unique")
        if item["batch_id"] != batch_id:
            raise ScoreContractError("ledger item batch id mismatch")
        _require_uuid(item["assigned_reviewer_id"], "ledger assigned reviewer")
        if item["ordinal"] != frozen["ordinal"]:
            raise ScoreContractError("ledger item order does not match manifest")
        for key in _MANIFEST_ITEM_KEYS - {"ordinal"}:
            if item[key] != frozen[key]:
                raise ScoreContractError(f"ledger item {key} does not match manifest")
        if (
            item["media_sha256_before"] != frozen["media_sha256"]
            or item["media_sha256_after"] != frozen["media_sha256"]
        ):
            raise ScoreContractError("ledger media mutation detected")
        items.append(item)
        item_by_id[item_id] = item

    submissions = _list(row["submissions"], "ledger submissions")
    if len(submissions) != 150:
        raise ScoreContractError("ledger requires one submission per item")
    submission_by_item: dict[str, dict[str, object]] = {}
    submission_id_seen: set[str] = set()
    digest_seen: set[str] = set()
    effective: dict[str, _EffectiveVerdict] = {}
    for item, value in zip(items, submissions, strict=True):
        submission = _record(value, "ledger submission")
        _exact_keys(submission, _SUBMISSION_KEYS, "ledger submission")
        submission_id = _require_uuid(submission["id"], "submission id")
        item_id = str(item["id"])
        if submission["item_id"] != item_id:
            raise ScoreContractError("ledger submission order/item mismatch")
        if submission["reviewer_id"] != item["assigned_reviewer_id"]:
            raise ScoreContractError("ledger assignment mismatch")
        _require_uuid(submission["reviewer_id"], "submission reviewer")
        digest = _unique_digest(submission["digest"], digest_seen, "submission")
        _require_rfc3339(submission["created_at"], "submission created_at")
        verdict, representative, bbox = _validate_verdict_shape(
            submission["verdict"],
            submission["representative_sec"],
            submission["bbox"],
            _duration(item["duration_sec"]),
            "submission",
        )
        if submission_id in submission_id_seen or item_id in submission_by_item:
            raise ScoreContractError("ledger submission is not unique")
        submission_id_seen.add(submission_id)
        submission_by_item[item_id] = submission
        effective[item_id] = _EffectiveVerdict(verdict, representative, bbox, digest)

    corrections = _list(row["corrections"], "ledger corrections")
    _require_canonical_event_order(corrections, "correction")
    for value in corrections:
        correction = _record(value, "ledger correction")
        _exact_keys(correction, _CORRECTION_KEYS, "ledger correction")
        _require_uuid(correction["id"], "correction id")
        item_id = _require_uuid(correction["item_id"], "correction item id")
        if item_id not in item_by_id:
            raise ScoreContractError("correction references an unknown item")
        submission = submission_by_item[item_id]
        if (
            correction["original_submission_id"] != submission["id"]
            or correction["reviewer_id"] != submission["reviewer_id"]
            or correction["expected_submission_digest"] != effective[item_id].digest
        ):
            raise ScoreContractError("correction chain/digest mismatch")
        _reason(correction["reason"], "correction reason")
        _require_rfc3339(correction["created_at"], "correction created_at")
        verdict, representative, bbox = _validate_verdict_shape(
            correction["verdict"],
            correction["representative_sec"],
            correction["bbox"],
            _duration(item_by_id[item_id]["duration_sec"]),
            "correction",
        )
        digest = _unique_digest(correction["digest"], digest_seen, "correction")
        effective[item_id] = _EffectiveVerdict(verdict, representative, bbox, digest)

    adjudications = _list(row["adjudications"], "ledger adjudications")
    _require_canonical_event_order(adjudications, "adjudication")
    adjudication_by_item: dict[str, dict[str, object]] = {}
    for value in adjudications:
        adjudication = _record(value, "ledger adjudication")
        _exact_keys(adjudication, _ADJUDICATION_KEYS, "ledger adjudication")
        _require_uuid(adjudication["id"], "adjudication id")
        item_id = _require_uuid(adjudication["item_id"], "adjudication item id")
        if item_id not in item_by_id or item_id in adjudication_by_item:
            raise ScoreContractError("adjudication item is unknown or duplicated")
        submission = submission_by_item[item_id]
        if submission["reviewer_id"] == owner_id or effective[item_id].verdict == "gecko_absent":
            raise ScoreContractError("adjudication is not allowed for this submission")
        if (
            adjudication["original_submission_id"] != submission["id"]
            or adjudication["owner_id"] != owner_id
            or adjudication["effective_submission_digest"] != effective[item_id].digest
        ):
            raise ScoreContractError("adjudication chain/digest mismatch")
        _reason(adjudication["reason"], "adjudication reason")
        _require_rfc3339(adjudication["created_at"], "adjudication created_at")
        verdict, representative, bbox = _validate_verdict_shape(
            adjudication["final_verdict"],
            adjudication["representative_sec"],
            adjudication["bbox"],
            _duration(item_by_id[item_id]["duration_sec"]),
            "adjudication",
        )
        digest = _unique_digest(adjudication["digest"], digest_seen, "adjudication")
        effective[item_id] = _EffectiveVerdict(verdict, representative, bbox, digest)
        adjudication_by_item[item_id] = adjudication

    for item_id, submission in submission_by_item.items():
        if (
            submission["reviewer_id"] != owner_id
            and effective[item_id].verdict != "gecko_absent"
            and item_id not in adjudication_by_item
        ):
            raise ScoreContractError("Owner adjudication is required")

    decisions = _list(row["dataset_decisions"], "ledger dataset decisions")
    _require_canonical_event_order(decisions, "dataset decision")
    for value in decisions:
        decision = _record(value, "ledger dataset decision")
        _exact_keys(decision, _DATASET_DECISION_KEYS, "ledger dataset decision")
        _require_uuid(decision["id"], "dataset decision id")
        item_id = _require_uuid(decision["item_id"], "dataset decision item id")
        if item_id not in item_by_id or decision["owner_id"] != owner_id:
            raise ScoreContractError("dataset decision owner/item mismatch")
        if decision["decision"] not in _DECISIONS:
            raise ScoreContractError("dataset decision enum is invalid")
        if decision["effective_submission_digest"] != effective[item_id].digest:
            raise ScoreContractError("dataset decision effective digest is stale")
        adjudication = adjudication_by_item.get(item_id)
        if decision["adjudication_id"] != (adjudication["id"] if adjudication else None):
            raise ScoreContractError("dataset decision adjudication pin mismatch")
        if decision["decision"] == "include_candidate":
            if item_by_id[item_id]["stratum"] == "positive_control":
                raise ScoreContractError("control cannot be a Dataset candidate")
            if effective[item_id].verdict != "gecko_present":
                raise ScoreContractError("Dataset candidate requires gecko_present")
            if submission_by_item[item_id]["reviewer_id"] != owner_id and adjudication is None:
                raise ScoreContractError("Dataset candidate requires adjudication")
        _reason(decision["reason"], "dataset decision reason")
        _require_rfc3339(decision["created_at"], "dataset decision created_at")
        _unique_digest(decision["digest"], digest_seen, "dataset decision")

    return {"items": items, "effective": effective}


def _validate_verdict_shape(
    verdict: object,
    representative_sec: object,
    bbox: object,
    duration_sec: float,
    label: str,
) -> tuple[str, float | None, dict[str, float] | None]:
    if verdict not in _VERDICTS:
        raise ScoreContractError(f"{label} verdict is invalid")
    if verdict != "gecko_present":
        if representative_sec is not None or bbox is not None:
            raise ScoreContractError(f"{label} non-present geometry must be null")
        return str(verdict), None, None
    representative = _finite_number(representative_sec, f"{label} representative_sec")
    if representative < 0 or representative > duration_sec:
        raise ScoreContractError(f"{label} representative timestamp is out of range")
    box = _record(bbox, f"{label} bbox")
    _exact_keys(box, _BBOX_KEYS, f"{label} bbox")
    normalized = {
        key: _finite_number(box[key], f"{label} bbox.{key}")
        for key in ("x", "y", "width", "height")
    }
    if (
        normalized["x"] < 0
        or normalized["y"] < 0
        or normalized["width"] <= 0
        or normalized["height"] <= 0
        or normalized["x"] > 1
        or normalized["y"] > 1
        or normalized["x"] + normalized["width"] > 1
        or normalized["y"] + normalized["height"] > 1
    ):
        raise ScoreContractError(f"{label} bbox is outside normalized bounds")
    return str(verdict), representative, normalized


def _require_canonical_event_order(events: Sequence[object], label: str) -> None:
    keys: list[tuple[datetime, str]] = []
    for value in events:
        row = _record(value, f"ledger {label}")
        created_at = _require_rfc3339(row.get("created_at"), f"{label} created_at")
        event_id = _require_uuid(row.get("id"), f"{label} id")
        keys.append((created_at, event_id))
    if keys != sorted(keys):
        raise ScoreContractError(f"ledger {label} order is not canonical")


def _record(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ScoreContractError(f"{label} must be an object")
    return dict(value)


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ScoreContractError(f"{label} must be a list")
    return value


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], label: str) -> None:
    if set(value) != expected:
        raise ScoreContractError(f"{label} must have the exact key set")


def _require_uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ScoreContractError(f"{label} must be a canonical UUID")
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as error:
        raise ScoreContractError(f"{label} must be a canonical UUID") from error
    if str(parsed) != value:
        raise ScoreContractError(f"{label} must be a canonical UUID")
    return value


def _require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ScoreContractError(f"{label} must be a lowercase SHA-256")
    return value


def _require_hex16(value: object, label: str) -> str:
    if not isinstance(value, str) or _HEX16.fullmatch(value) is None:
        raise ScoreContractError(f"{label} must be lowercase 64-bit hexadecimal")
    return value


def _require_rfc3339(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ScoreContractError(f"{label} must be canonical RFC3339 UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ScoreContractError(f"{label} must be canonical RFC3339 UTC") from error
    canonical = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if parsed.tzinfo is None or canonical != value:
        raise ScoreContractError(f"{label} must be canonical RFC3339 UTC")
    return parsed


def _require_decimal(value: object, label: str) -> Decimal:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise ScoreContractError(f"{label} must be canonical positive decimal text")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ScoreContractError(f"{label} must be canonical positive decimal text") from error
    if not parsed.is_finite() or parsed <= 0:
        raise ScoreContractError(f"{label} must be canonical positive decimal text")
    return parsed


def _duration(value: object) -> float:
    parsed = _require_decimal(value, "duration_sec")
    try:
        duration = float(parsed)
    except (OverflowError, ValueError) as error:
        raise ScoreContractError("duration_sec is outside finite scorer range") from error
    if not math.isfinite(duration):
        raise ScoreContractError("duration_sec is outside finite scorer range")
    return duration


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScoreContractError(f"{label} must be finite")
    try:
        parsed = float(value)
    except (OverflowError, ValueError) as error:
        raise ScoreContractError(f"{label} must be finite") from error
    if not math.isfinite(parsed) or abs(parsed) > 2**53 - 1:
        raise ScoreContractError(f"{label} must be finite")
    return parsed


def _require_count(value: object, label: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ScoreContractError(f"{label} is invalid")
    return value


def _reason(value: object, label: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= 2_000:
        raise ScoreContractError(f"{label} is invalid")
    return value


def _unique_digest(value: object, seen: set[str], label: str) -> str:
    digest = _require_sha(value, f"{label} digest")
    if digest in seen:
        raise ScoreContractError(f"{label} digest is not unique")
    seen.add(digest)
    return digest


def _interval_json(interval: tuple[float, float] | None) -> dict[str, float] | None:
    if interval is None:
        return None
    return {"lower": interval[0], "upper": interval[1]}


def _write_json_new(path: Path, payload: Mapping[str, object]) -> None:
    encoded = _canonical_json(payload) + b"\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(encoded)
    finally:
        if descriptor != -1:
            os.close(descriptor)


class _JsonLedgerReader:
    """Explicit local copy of a prior read-only DB export; never a live DB client."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def export_batch_read_only(self, batch_id: str) -> Mapping[str, object]:
        try:
            raw = self.path.read_bytes()
            value = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ScoreContractError("read-only ledger export file is invalid") from error
        if not isinstance(value, Mapping):
            raise ScoreContractError("read-only ledger export file is invalid")
        batch = value.get("batch")
        if not isinstance(batch, Mapping) or batch.get("id") != batch_id:
            raise ScoreContractError("read-only ledger export batch id mismatch")
        return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--ledger-input", type=Path, required=True)
    parser.add_argument("--private-ledger-out", type=Path, required=True)
    parser.add_argument("--safe-aggregate-out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw_manifest = args.manifest.read_bytes()
        manifest = json.loads(raw_manifest)
        if not isinstance(manifest, Mapping):
            raise ScoreContractError("manifest file is invalid")
        canonical = _canonical_json(manifest) + b"\n"
        if raw_manifest != canonical:
            raise ScoreContractError("manifest file is not canonical raw bytes")
        export_score_batch(
            manifest,
            batch_id=args.batch_id,
            reader=_JsonLedgerReader(args.ledger_input),
            private_ledger_path=args.private_ledger_out,
            safe_aggregate_path=args.safe_aggregate_out,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ScoreContractError, FileExistsError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

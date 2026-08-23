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
import stat
from statistics import NormalDist
from typing import Callable, Protocol
from uuid import UUID, uuid4

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
        "batch_events",
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
        "test_sheet_sha256",
        "manifest_sha256",
        "seed",
        "cutoff",
        "detector_identity",
        "checkpoint_sha256",
        "negative_pool_sha256",
        "control_pool_sha256",
        "selection_sha256",
        "protected_manifest_sha256",
        "expected_negative_count",
        "expected_control_count",
        "expected_total_count",
        "candidate_negative_count",
        "candidate_control_count",
    }
)
_BATCH_EVENT_KEYS = frozenset(
    {"id", "batch_id", "event_type", "actor_id", "reason", "digest", "created_at"}
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


def canonical_ledger_digest(*parts: object) -> str:
    """Mirror Task 2's single `sha256(text[] joined by |)` ledger formula."""
    rendered: list[str] = []
    for value in parts:
        if value is None:
            rendered.append("null")
        elif isinstance(value, Mapping):
            rendered.append(_canonical_json(dict(value)).decode("utf-8"))
        elif isinstance(value, bool):
            rendered.append(str(value).lower())
        else:
            rendered.append(str(value))
    return hashlib.sha256("|".join(rendered).encode("utf-8")).hexdigest()


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
    media_root: Path | str | None = None,
    media_files: Mapping[str, Path | str] | None = None,
    reader: AuditLedgerReader | None = None,
    publish_replace: Callable[[Path, Path], None] = os.replace,
) -> AuditScore:
    """Verify frozen media and publish the private/safe pair as one claimed operation."""
    _require_uuid(batch_id, "batch_id")
    private_path = Path(private_ledger_path)
    safe_path = Path(safe_aggregate_path)
    _validate_distinct_output_paths(private_path, safe_path)
    claims = _claim_output_pair(private_path, safe_path)
    staged: list[Path] = []
    opened_media: list[tuple[int, str]] = []
    published: list[tuple[Path, tuple[int, int]]] = []
    try:
        manifest_items, _ = _validate_manifest(manifest)
        opened_media = _open_verified_media(manifest_items, media_root, media_files)
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
        _rehash_open_media(opened_media)

        private_stage = _stage_json(private_path, exported)
        safe_stage = _stage_json(safe_path, score.safe_aggregate(batch_id))
        staged.extend((private_stage, safe_stage))
        # Publish safe first. A second-step failure can never put private bytes under the safe name.
        for stage_path, final_path, claim in (
            (safe_stage, safe_path, claims[safe_path]),
            (private_stage, private_path, claims[private_path]),
        ):
            _verify_claim(final_path, claim)
            stage_stat = stage_path.stat()
            publish_replace(stage_path, final_path)
            final_stat = final_path.lstat()
            if final_path.is_symlink() or (final_stat.st_dev, final_stat.st_ino) != (
                stage_stat.st_dev, stage_stat.st_ino
            ):
                _unlink_if_exists(final_path)
                raise ScoreContractError("output publication race detected")
            published.append((final_path, (stage_stat.st_dev, stage_stat.st_ino)))
            staged.remove(stage_path)
        _fsync_parents({private_path.parent, safe_path.parent})
        return score
    except Exception as error:
        _cleanup_published(published)
        if published:
            _write_invalid_marker(private_path)
        if isinstance(error, (ScoreContractError, FileExistsError)):
            raise
        if published:
            raise ScoreContractError("output publication failed") from error
        raise
    finally:
        for descriptor, _expected in opened_media:
            os.close(descriptor)
        for path in staged:
            _unlink_if_exists(path)
        for path, claim in claims.items():
            _remove_owned_claim(path, claim)


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
    negative_episodes: Counter[str] = Counter()
    blind_ranks: list[str] = []
    selection_items: list[dict[str, object]] = []
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
        if item["stratum"] == "random_negative":
            negative_episodes[str(item["episode_key"])] += 1
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
        selection_items.append(
            {
                "ordinal": expected_ordinal,
                "candidate": candidate,
                "selection_provenance": item["selection_provenance"],
            }
        )
        items.append(item)
    if counts != Counter({"random_negative": 120, "positive_control": 30}):
        raise ScoreContractError("manifest stratum count mismatch")
    if any(count > 2 for count in negative_episodes.values()):
        raise ScoreContractError("manifest random_negative episode cap exceeded")
    if blind_ranks != sorted(blind_ranks):
        raise ScoreContractError("manifest blind order mismatch")
    expected_selection_sha = hashlib.sha256(
        _canonical_json(
            {
                "batch_kind": row["batch_kind"],
                "seed": seed,
                "negative_pool_sha256": source_pools["random_negative"]["sha256"],
                "control_pool_sha256": source_pools["positive_control"]["sha256"],
                "items": selection_items,
            }
        )
    ).hexdigest()
    if row["selection_sha256"] != expected_selection_sha:
        raise ScoreContractError("manifest selection SHA mismatch")
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
        or batch["test_sheet_sha256"] != manifest["test_sheet_sha256"]
        or batch["manifest_sha256"] != manifest["manifest_sha256"]
        or batch["seed"] != manifest["seed"]
        or batch["cutoff"] != manifest["cutoff"]
        or batch["detector_identity"] != manifest["detector_identity"]
        or batch["checkpoint_sha256"] != manifest["checkpoint_sha256"]
        or batch["negative_pool_sha256"] != manifest["source_pools"]["random_negative"]["sha256"]
        or batch["control_pool_sha256"] != manifest["source_pools"]["positive_control"]["sha256"]
        or batch["selection_sha256"] != manifest["selection_sha256"]
        or batch["protected_manifest_sha256"] != manifest["protected_manifest_sha256"]
        or batch["expected_negative_count"] != 120
        or batch["expected_control_count"] != 30
        or batch["expected_total_count"] != 150
        or batch["candidate_negative_count"] != manifest["candidate_counts"]["random_negative"]
        or batch["candidate_control_count"] != manifest["candidate_counts"]["positive_control"]
    ):
        raise ScoreContractError("ledger batch pin/count mismatch")

    events = _list(row["batch_events"], "ledger batch events")
    _require_canonical_event_order(events, "batch event")
    event_ids: set[str] = set()
    event_digests: set[str] = set()
    event_types: list[str] = []
    for value in events:
        event = _record(value, "ledger batch event")
        _exact_keys(event, _BATCH_EVENT_KEYS, "ledger batch event")
        event_id = _unique_uuid(event["id"], event_ids, "batch event")
        if event["batch_id"] != batch_id or event["actor_id"] != owner_id:
            raise ScoreContractError("ledger batch event identity mismatch")
        event_type = event["event_type"]
        if event_type not in {"prepared", "opened", "closed", "scored", "invalidated"}:
            raise ScoreContractError("ledger batch event type is invalid")
        event_reason = event["reason"]
        if event_reason is not None:
            _reason(event_reason, "batch event reason")
        _require_rfc3339(event["created_at"], "batch event created_at")
        expected_digest = canonical_ledger_digest(
            event_id, batch_id, event_type, owner_id, event_reason
        )
        if _unique_digest(event["digest"], event_digests, "batch event") != expected_digest:
            raise ScoreContractError("batch event digest mismatch")
        event_types.append(str(event_type))
    if not event_types or event_types[0] != "prepared" or event_types[:2] not in (["prepared"], ["prepared", "opened"]):
        raise ScoreContractError("ledger batch event transition mismatch")
    allowed_sequences = {
        ("prepared",),
        ("prepared", "opened"),
        ("prepared", "opened", "closed"),
        ("prepared", "opened", "closed", "scored"),
        ("prepared", "invalidated"),
        ("prepared", "opened", "invalidated"),
        ("prepared", "opened", "closed", "invalidated"),
    }
    if tuple(event_types) not in allowed_sequences:
        raise ScoreContractError("ledger batch event transition mismatch")

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
        submission_id = _unique_uuid(submission["id"], submission_id_seen, "submission")
        item_id = str(item["id"])
        if submission["item_id"] != item_id:
            raise ScoreContractError("ledger submission order/item mismatch")
        if submission["reviewer_id"] != item["assigned_reviewer_id"]:
            raise ScoreContractError("ledger assignment mismatch")
        _require_uuid(submission["reviewer_id"], "submission reviewer")
        _require_rfc3339(submission["created_at"], "submission created_at")
        verdict, representative, bbox = _validate_verdict_shape(
            submission["verdict"],
            submission["representative_sec"],
            submission["bbox"],
            _duration(item["duration_sec"]),
            "submission",
        )
        digest = _unique_digest(submission["digest"], digest_seen, "submission")
        if digest != canonical_ledger_digest(
            submission_id, item_id, submission["reviewer_id"], verdict,
            representative, bbox,
        ):
            raise ScoreContractError("submission digest mismatch")
        if item_id in submission_by_item:
            raise ScoreContractError("ledger submission is not unique")
        submission_by_item[item_id] = submission
        effective[item_id] = _EffectiveVerdict(verdict, representative, bbox, digest)

    corrections = _list(row["corrections"], "ledger corrections")
    _require_canonical_event_order(corrections, "correction")
    correction_ids: set[str] = set()
    for value in corrections:
        correction = _record(value, "ledger correction")
        _exact_keys(correction, _CORRECTION_KEYS, "ledger correction")
        correction_id = _unique_uuid(correction["id"], correction_ids, "correction")
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
        if digest != canonical_ledger_digest(
            correction_id, submission["id"], correction["expected_submission_digest"],
            verdict, representative, bbox, correction["reason"],
        ):
            raise ScoreContractError("correction digest mismatch")
        effective[item_id] = _EffectiveVerdict(verdict, representative, bbox, digest)

    adjudications = _list(row["adjudications"], "ledger adjudications")
    _require_canonical_event_order(adjudications, "adjudication")
    adjudication_by_item: dict[str, dict[str, object]] = {}
    adjudication_ids: set[str] = set()
    for value in adjudications:
        adjudication = _record(value, "ledger adjudication")
        _exact_keys(adjudication, _ADJUDICATION_KEYS, "ledger adjudication")
        adjudication_id = _unique_uuid(adjudication["id"], adjudication_ids, "adjudication")
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
        if digest != canonical_ledger_digest(
            adjudication_id, submission["id"], adjudication["effective_submission_digest"],
            verdict, representative, bbox, adjudication["reason"],
        ):
            raise ScoreContractError("adjudication digest mismatch")
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
    decision_ids: set[str] = set()
    for value in decisions:
        decision = _record(value, "ledger dataset decision")
        _exact_keys(decision, _DATASET_DECISION_KEYS, "ledger dataset decision")
        decision_id = _unique_uuid(decision["id"], decision_ids, "dataset decision")
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
        decision_digest = _unique_digest(decision["digest"], digest_seen, "dataset decision")
        if decision_digest != canonical_ledger_digest(
            decision_id, item_id, decision["decision"],
            decision["effective_submission_digest"], decision["reason"],
        ):
            raise ScoreContractError("dataset decision digest mismatch")

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


def _unique_uuid(value: object, seen: set[str], label: str) -> str:
    row_id = _require_uuid(value, f"{label} id")
    if row_id in seen:
        raise ScoreContractError(f"{label} id is not unique")
    seen.add(row_id)
    return row_id


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


def _validate_distinct_output_paths(private_path: Path, safe_path: Path) -> None:
    private_lexical = Path(os.path.abspath(private_path))
    safe_lexical = Path(os.path.abspath(safe_path))
    if private_lexical == safe_lexical or private_path.resolve(strict=False) == safe_path.resolve(strict=False):
        raise ScoreContractError("private and safe require distinct output paths")
    for path in (private_path, safe_path):
        parent = path.parent
        if not parent.exists() or not parent.is_dir() or parent.is_symlink():
            raise ScoreContractError("output parent must be an existing real directory")
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
    try:
        if os.path.samefile(private_path.parent, safe_path) or os.path.samefile(safe_path.parent, private_path):
            raise ScoreContractError("private and safe output/parent collision")
    except FileNotFoundError:
        pass


def _claim_output_pair(
    private_path: Path, safe_path: Path,
) -> dict[Path, tuple[int, tuple[int, int]]]:
    claims: dict[Path, tuple[int, tuple[int, int]]] = {}
    try:
        for path in (private_path, safe_path):
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.fchmod(descriptor, 0o600)
            current = os.fstat(descriptor)
            claims[path] = (descriptor, (current.st_dev, current.st_ino))
        return claims
    except Exception:
        for path, claim in claims.items():
            _remove_owned_claim(path, claim)
        raise


def _verify_claim(path: Path, claim: tuple[int, tuple[int, int]]) -> None:
    descriptor, expected = claim
    descriptor_stat = os.fstat(descriptor)
    try:
        path_stat = path.lstat()
    except FileNotFoundError as error:
        raise ScoreContractError("output claim changed during publication") from error
    if path.is_symlink() or (descriptor_stat.st_dev, descriptor_stat.st_ino) != expected or (
        path_stat.st_dev, path_stat.st_ino
    ) != expected:
        raise ScoreContractError("output claim changed during publication")


def _remove_owned_claim(path: Path, claim: tuple[int, tuple[int, int]]) -> None:
    descriptor, expected = claim
    try:
        current = path.lstat()
        if not path.is_symlink() and (current.st_dev, current.st_ino) == expected:
            path.unlink()
    except FileNotFoundError:
        pass
    finally:
        os.close(descriptor)


def _stage_json(path: Path, payload: Mapping[str, object]) -> Path:
    stage = path.parent / f".{path.name}.stage-{uuid4().hex}"
    encoded = _canonical_json(payload) + b"\n"
    descriptor = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor != -1:
            os.close(descriptor)
    return stage


def _cleanup_published(published: Sequence[tuple[Path, tuple[int, int]]]) -> None:
    for path, expected in published:
        try:
            current = path.lstat()
            if not path.is_symlink() and (current.st_dev, current.st_ino) == expected:
                path.unlink()
        except FileNotFoundError:
            pass


def _write_invalid_marker(private_path: Path) -> None:
    marker = private_path.with_name(f"{private_path.name}.invalid")
    try:
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    with os.fdopen(descriptor, "wb") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(b"invalid\n")
        handle.flush()
        os.fsync(handle.fileno())


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _fsync_parents(parents: set[Path]) -> None:
    for parent in parents:
        descriptor = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _open_verified_media(
    manifest_items: Sequence[Mapping[str, object]],
    media_root: Path | str | None,
    media_files: Mapping[str, Path | str] | None,
) -> list[tuple[int, str]]:
    if media_root is None or media_files is None:
        raise ScoreContractError("exact private media mapping/root is required")
    root = Path(media_root)
    if root.is_symlink() or not root.is_dir():
        raise ScoreContractError("private media root is invalid")
    root_resolved = root.resolve(strict=True)
    expected_ids = {str(item["clip_id"]) for item in manifest_items}
    if set(media_files) != expected_ids:
        raise ScoreContractError("private media mapping item set mismatch")
    opened: list[tuple[int, str]] = []
    inodes: set[tuple[int, int]] = set()
    try:
        for item in manifest_items:
            path = Path(media_files[str(item["clip_id"])])
            candidate = path if path.is_absolute() else root / path
            if candidate.is_symlink():
                raise ScoreContractError("private media symlink is forbidden")
            resolved = candidate.resolve(strict=True)
            try:
                resolved.relative_to(root_resolved)
            except ValueError as error:
                raise ScoreContractError("private media path escapes root") from error
            before = candidate.lstat()
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(candidate, flags)
            current = os.fstat(descriptor)
            inode = (current.st_dev, current.st_ino)
            if not stat.S_ISREG(current.st_mode) or inode != (before.st_dev, before.st_ino):
                os.close(descriptor)
                raise ScoreContractError("private media identity changed while opening")
            if inode in inodes:
                os.close(descriptor)
                raise ScoreContractError("private media paths alias the same inode")
            inodes.add(inode)
            expected_sha = str(item["media_sha256"])
            if _hash_descriptor(descriptor) != expected_sha:
                os.close(descriptor)
                raise ScoreContractError("private media SHA mismatch")
            opened.append((descriptor, expected_sha))
        return opened
    except OSError as error:
        for descriptor, _expected in opened:
            os.close(descriptor)
        raise ScoreContractError("private media file verification failed") from error
    except Exception:
        for descriptor, _expected in opened:
            os.close(descriptor)
        raise


def _hash_descriptor(descriptor: int) -> str:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _rehash_open_media(opened: Sequence[tuple[int, str]]) -> None:
    for descriptor, expected in opened:
        if _hash_descriptor(descriptor) != expected:
            raise ScoreContractError("private media mutated during scoring")


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ScoreContractError("duplicate JSON key")
        result[key] = value
    return result


def load_strict_json(path: Path | str, label: str) -> object:
    try:
        raw = Path(path).read_bytes()
        return json.loads(raw, object_pairs_hook=_reject_duplicate_pairs)
    except ScoreContractError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ScoreContractError(f"{label} file is invalid") from error


class _JsonLedgerReader:
    """Explicit local copy of a prior read-only DB export; never a live DB client."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def export_batch_read_only(self, batch_id: str) -> Mapping[str, object]:
        value = load_strict_json(self.path, "read-only ledger export")
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
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--media-map", type=Path, required=True)
    parser.add_argument("--private-ledger-out", type=Path, required=True)
    parser.add_argument("--safe-aggregate-out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw_manifest = args.manifest.read_bytes()
        manifest = load_strict_json(args.manifest, "manifest")
        if not isinstance(manifest, Mapping):
            raise ScoreContractError("manifest file is invalid")
        canonical = _canonical_json(manifest) + b"\n"
        if raw_manifest != canonical:
            raise ScoreContractError("manifest file is not canonical raw bytes")
        media_map = load_strict_json(args.media_map, "private media mapping")
        if not isinstance(media_map, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in media_map.items()
        ):
            raise ScoreContractError("private media mapping file is invalid")
        export_score_batch(
            manifest,
            batch_id=args.batch_id,
            reader=_JsonLedgerReader(args.ledger_input),
            private_ledger_path=args.private_ledger_out,
            safe_aggregate_path=args.safe_aggregate_out,
            media_root=args.media_root,
            media_files=media_map,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ScoreContractError, FileExistsError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

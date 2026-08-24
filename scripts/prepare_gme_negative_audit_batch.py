"""Read-only GME-negative audit preflight, freeze, and gated one-shot import."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Protocol
from uuid import UUID

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.gme_negative_audit_sampling import (
    CHECKPOINT_SHA256,
    DETECTOR_IDENTITY,
    AuditContractError,
    AuditShortageError,
    build_private_manifest,
    select_calibration_batch,
)


SEED = "gme-negative-audit-calibration-v1"
SELECTION_ALGORITHM_VERSION = "gme-negative-audit-selection-v1"
TRAINING_PIN_SCHEMA = "gme-negative-audit-training-pin-v1"
PROTECTED_PIN_SCHEMA = "gme-negative-audit-protected-pin-v1"
TEST_SHEET_SCHEMA = "gme-negative-audit-test-sheet-v1"
INVENTORY_SCHEMA = "gme-negative-audit-inventory-v1"
AVAILABILITY_SCHEMA = "gme-negative-audit-availability-v1"
MAX_PIN_BYTES = 16 * 1024 * 1024
MAX_TEST_SHEET_BYTES = 1024 * 1024
MAX_ROWS_PER_STRATUM = 10_000
MAX_MEDIA_BYTES = 128 * 1024 * 1024
MAX_TOTAL_MEDIA_BYTES = 64 * 1024 * 1024 * 1024
MEDIA_READ_CHUNK = 1024 * 1024
EPISODE_GAP_SEC = 300
NEGATIVE_COUNT = 120
CONTROL_COUNT = 30
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DHASH = re.compile(r"^[0-9a-f]{16}$")
_MACHINE_BEGIN = "GME_NEGATIVE_AUDIT_MACHINE_CONTRACT_BEGIN"
_MACHINE_END = "GME_NEGATIVE_AUDIT_MACHINE_CONTRACT_END"

# None means the future manifest must be non-empty but its exact count comes from
# the raw-SHA-pinned artifact itself. The other historical sets have frozen names.
PROTECTED_ROLE_COUNTS: Mapping[str, int | None] = {
    "validation153": 153,
    "internal-test151": 151,
    "owner-external60": 60,
    "future": None,
}

_SOURCE_ROW_KEYS = frozenset(
    {
        "clip_id",
        "camera_id",
        "started_at",
        "duration_sec",
        "r2_key",
        "clip_purpose",
        "dataset_role",
        "current_job_status",
        "current_job_detector_identity",
        "current_result_run_id",
        "current_run_id",
        "current_run_status",
        "current_detector_identity",
        "current_detected",
        "consensus_status",
        "consensus_final_decision",
        "consensus_visibility",
        "human_gt_digest",
        "research_quarantined",
    }
)
_TEST_SHEET_KEYS = frozenset(
    {
        "schema_version",
        "freeze_status",
        "owner_approval",
        "reviewed_import_schema",
        "seed",
        "selection_algorithm_version",
        "negative_count",
        "control_count",
        "episode_cap",
        "detector_identity",
        "checkpoint_sha256",
        "training_manifest_sha256",
        "cutoff",
        "protected_manifest_sha256",
        "approved_reviewer_ids",
    }
)


class PreflightError(ValueError):
    """Stable fail-closed error without source identities."""


class ReadDatabase(Protocol):
    def read(self, operation: str, params: dict[str, object]) -> list[dict[str, object]]: ...


class ImportDatabase(ReadDatabase, Protocol):
    def write_rpc(
        self, operation: str, params: dict[str, object]
    ) -> list[dict[str, object]]: ...


class ReadR2(Protocol):
    def head_object(self, *, Bucket: str, Key: str) -> Mapping[str, object]: ...

    def get_object(self, *, Bucket: str, Key: str) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class PinnedJson:
    role: str
    path: Path
    raw_sha256: str


@dataclass(frozen=True, slots=True)
class PreflightConfig:
    attempt_root: Path
    training_manifest: PinnedJson
    protected_manifests: tuple[PinnedJson, ...]
    test_sheet_path: Path
    owner_id: str
    r2_bucket: str


@dataclass(frozen=True, slots=True)
class _VerifiedInputs:
    cutoff: str
    cutoff_dt: datetime
    test_sheet_raw_sha256: str
    protected_manifest_raw_sha256: tuple[str, ...]
    protected_media_sha256: frozenset[str]
    protected_media_dhash: frozenset[str]
    protected_source_identity_sha256: frozenset[str]
    protected_r2_key_sha256: frozenset[str]


@dataclass(frozen=True, slots=True)
class _EligibleSource:
    clip_id: str
    camera_id: str
    started_at: datetime
    duration_sec: float
    r2_key: str
    gme_run_id: str
    gme_detected: bool
    human_gt_digest: str | None
    stratum: str
    media_sha256: str
    media_dhash: str


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    payload: bytes
    sha256: str
    dev: int
    ino: int
    uid: int
    mode: int
    nlink: int
    size: int
    mtime_ns: int


@dataclass(slots=True)
class _AttemptRoot:
    path: Path
    fd: int
    dev: int
    ino: int
    uid: int
    mode: int

    def close(self) -> None:
        if self.fd != -1:
            os.close(self.fd)
            self.fd = -1


def run_preflight(
    config: PreflightConfig,
    *,
    db: ReadDatabase,
    r2: ReadR2,
    media_probe: Callable[[bytes], str] | None = None,
) -> dict[str, object]:
    """Read current DB/R2 state and publish no service mutations or manifest."""
    verified = _verify_config_and_pins(config)
    root = _create_attempt_root(config.attempt_root)
    started_snapshot = _write_attempt_marker(
        root,
        "preflight.started.private.json",
        "GME_NEGATIVE_AUDIT_PREFLIGHT_STARTED",
        extra=_root_identity(root),
    )
    try:
        owner_rows = db.read("owner_exists", {"owner_id": config.owner_id})
        if owner_rows != [{"exists": True}]:
            raise PreflightError("OWNER_NOT_FOUND")
        negative_rows = db.read(
            "negative_candidates",
            {"cutoff": verified.cutoff, "detector_identity": DETECTOR_IDENTITY},
        )
        control_rows = db.read(
            "positive_controls",
            {"cutoff": verified.cutoff, "detector_identity": DETECTOR_IDENTITY},
        )
        if len(negative_rows) > MAX_ROWS_PER_STRATUM or len(control_rows) > MAX_ROWS_PER_STRATUM:
            raise PreflightError("SOURCE_ROW_BOUND_EXCEEDED")

        unavailable: dict[str, int] = {}
        eligible: list[_EligibleSource] = []
        eligible_keys: set[tuple[str, str]] = set()
        seen_media_sha = {
            "random_negative": set(),
            "positive_control": set(),
        }
        seen_media_dhash = {
            "random_negative": set(),
            "positive_control": set(),
        }
        verified_media_by_clip: dict[
            str, tuple[tuple[object, ...], str, str]
        ] = {}
        failed_media_by_clip: dict[str, tuple[tuple[object, ...], str]] = {}
        total_media_bytes = 0
        r2_counts = {"head": 0, "get": 0}
        protected_media_get_count = 0
        for stratum, rows in (
            ("random_negative", negative_rows),
            ("positive_control", control_rows),
        ):
            for raw in sorted(rows, key=_source_sort_key):
                try:
                    source = _validate_source_row(raw, stratum=stratum, verified=verified)
                except PreflightError as error:
                    _bump(unavailable, str(error))
                    continue
                if (
                    _source_identity_sha256(source["clip_id"])
                    in verified.protected_source_identity_sha256
                    or _r2_key_sha256(source["r2_key"])
                    in verified.protected_r2_key_sha256
                ):
                    _bump(unavailable, "protected_source_identity")
                    continue
                eligible_key = (stratum, source["clip_id"])
                if eligible_key in eligible_keys:
                    _bump(unavailable, "candidate_exact_duplicate")
                    continue
                media_identity = _source_media_identity(source)
                cached_failure = failed_media_by_clip.get(source["clip_id"])
                if cached_failure is not None:
                    if cached_failure[0] != media_identity:
                        _bump(unavailable, "source_cross_stratum_mismatch")
                    else:
                        _bump(unavailable, cached_failure[1])
                    continue
                cached_media = verified_media_by_clip.get(source["clip_id"])
                if cached_media is not None:
                    if cached_media[0] != media_identity:
                        _bump(unavailable, "source_cross_stratum_mismatch")
                        continue
                    media_sha256, media_dhash = cached_media[1:]
                else:
                    try:
                        payload = _read_media_bytes(
                            r2,
                            bucket=config.r2_bucket,
                            key=source["r2_key"],
                            remaining_total_bytes=MAX_TOTAL_MEDIA_BYTES - total_media_bytes,
                            read_counts=r2_counts,
                        )
                        total_media_bytes += len(payload)
                        if media_probe is None:
                            media_sha256, media_dhash = _probe_media_bytes(payload)
                        else:
                            media_sha256 = hashlib.sha256(payload).hexdigest()
                            media_dhash = media_probe(payload)
                            if _DHASH.fullmatch(media_dhash) is None:
                                raise PreflightError("MEDIA_DHASH_FAILED")
                    except PreflightError as error:
                        failed_media_by_clip[source["clip_id"]] = (
                            media_identity,
                            str(error),
                        )
                        _bump(unavailable, str(error))
                        continue
                    if media_sha256 in verified.protected_media_sha256:
                        protected_media_get_count += 1
                        failed_media_by_clip[source["clip_id"]] = (
                            media_identity,
                            "protected_exact_duplicate",
                        )
                        _bump(unavailable, "protected_exact_duplicate")
                        continue
                    if _near_any(media_dhash, verified.protected_media_dhash, maximum=2):
                        protected_media_get_count += 1
                        failed_media_by_clip[source["clip_id"]] = (
                            media_identity,
                            "protected_near_duplicate",
                        )
                        _bump(unavailable, "protected_near_duplicate")
                        continue
                    verified_media_by_clip[source["clip_id"]] = (
                        media_identity,
                        media_sha256,
                        media_dhash,
                    )
                if media_sha256 in seen_media_sha[stratum]:
                    _bump(unavailable, "candidate_exact_duplicate")
                    continue
                if _near_any(
                    media_dhash,
                    seen_media_dhash[stratum],
                    maximum=2,
                ):
                    _bump(unavailable, "candidate_near_duplicate")
                    continue
                seen_media_sha[stratum].add(media_sha256)
                seen_media_dhash[stratum].add(media_dhash)
                eligible_keys.add(eligible_key)
                eligible.append(
                    _EligibleSource(
                        clip_id=source["clip_id"],
                        camera_id=source["camera_id"],
                        started_at=source["started_at"],
                        duration_sec=source["duration_sec"],
                        r2_key=source["r2_key"],
                        gme_run_id=source["gme_run_id"],
                        gme_detected=source["gme_detected"],
                        human_gt_digest=source["human_gt_digest"],
                        stratum=stratum,
                        media_sha256=media_sha256,
                        media_dhash=media_dhash,
                    )
                )

        candidate_pools = _derive_manifest_candidates(eligible)
        negative_pool = candidate_pools["random_negative"]
        control_pool = candidate_pools["positive_control"]
        coverage_ready, post_negative_control_count = _coverage_ready(
            negative_pool, control_pool
        )
        status_value = (
            "GME_NEGATIVE_AUDIT_PREFLIGHT_READY"
            if coverage_ready
            else "GME_NEGATIVE_AUDIT_SHORTAGE"
        )
        inventory = {
            "schema_version": INVENTORY_SCHEMA,
            "status": status_value,
            "seed": SEED,
            "cutoff": verified.cutoff,
            "detector_identity": DETECTOR_IDENTITY,
            "checkpoint_sha256": CHECKPOINT_SHA256,
            "training_manifest_sha256": config.training_manifest.raw_sha256,
            "protected_manifest_sha256": list(verified.protected_manifest_raw_sha256),
            "candidate_pools": candidate_pools,
        }
        availability = _build_availability(
            status_value=status_value,
            negative_rows=len(negative_rows),
            control_rows=len(control_rows),
            candidate_pools=candidate_pools,
            eligible_sources=eligible,
            unavailable=unavailable,
            db_read_count=3,
            r2_head_count=r2_counts["head"],
            r2_get_count=r2_counts["get"],
            protected_media_get_count=protected_media_get_count,
            post_negative_control_count=post_negative_control_count,
        )
        inventory_snapshot = _write_attempt_json(root, "inventory.private.json", inventory)
        availability_snapshot = _write_attempt_json(
            root, "availability.private.json", availability
        )
        _assert_root_path_current(root)
        _write_attempt_marker(
            root,
            "preflight.complete.private.json",
            status_value,
            extra={
                **_snapshot_identity("started", started_snapshot),
                **_snapshot_identity("inventory", inventory_snapshot),
                **_snapshot_identity("availability", availability_snapshot),
            },
        )
        return availability
    except BaseException as error:
        _write_attempt_failure_best_effort(
            root,
            "preflight.failed.private.json",
            _safe_failure_code(error),
        )
        raise
    finally:
        root.close()


def freeze_batch_manifest(
    config: PreflightConfig, *, expected_test_sheet_sha256: str
) -> dict[str, object]:
    """Run the Task 1 selector once against one completed immutable inventory."""
    verified = _verify_config_and_pins(config)
    expected_test_sheet_sha256 = _require_sha(expected_test_sheet_sha256, "TEST_SHEET_PIN")
    if verified.test_sheet_raw_sha256 != expected_test_sheet_sha256:
        raise PreflightError("TEST_SHEET_PIN_MISMATCH")
    contract = _read_test_sheet_contract(config.test_sheet_path)
    _validate_frozen_test_sheet(contract, config=config, verified=verified)

    root = _open_attempt_root(config.attempt_root)
    try:
        started_snapshot = _validate_started_root(root)
        if _attempt_entry_exists(root, "batch-manifest.private.json") or _attempt_entry_exists(
            root, "manifest.started.private.json"
        ):
            raise PreflightError("MANIFEST_EXISTS")
        inventory_snapshot = _read_attempt_file(root, "inventory.private.json", MAX_PIN_BYTES)
        complete_snapshot = _read_attempt_file(
            root, "preflight.complete.private.json", MAX_PIN_BYTES
        )
        inventory = _strict_json_object(inventory_snapshot.payload)
        complete = _strict_json_object(complete_snapshot.payload)
        if (
            inventory.get("schema_version") != INVENTORY_SCHEMA
            or inventory.get("status") != "GME_NEGATIVE_AUDIT_PREFLIGHT_READY"
            or complete.get("status") != "GME_NEGATIVE_AUDIT_PREFLIGHT_READY"
            or not _marker_matches_node_identity(complete, complete_snapshot)
            or not _marker_matches_snapshot(complete, "started", started_snapshot)
            or not _marker_matches_snapshot(complete, "inventory", inventory_snapshot)
            or inventory.get("seed") != SEED
            or inventory.get("cutoff") != verified.cutoff
            or inventory.get("training_manifest_sha256")
            != config.training_manifest.raw_sha256
            or inventory.get("protected_manifest_sha256")
            != list(verified.protected_manifest_raw_sha256)
        ):
            raise PreflightError("INVENTORY_NOT_FROZEN")
        pools = inventory.get("candidate_pools")
        if not isinstance(pools, dict) or set(pools) != {
            "random_negative",
            "positive_control",
        }:
            raise PreflightError("INVENTORY_NOT_FROZEN")
        negative_rows = pools["random_negative"]
        control_rows = pools["positive_control"]
        if not isinstance(negative_rows, list) or not isinstance(control_rows, list):
            raise PreflightError("INVENTORY_NOT_FROZEN")

        _write_attempt_marker(
            root,
            "manifest.started.private.json",
            "GME_NEGATIVE_AUDIT_MANIFEST_STARTED",
        )
        try:
            selection = select_calibration_batch(
                negative_rows,
                control_rows,
                protected_sha256=set(verified.protected_media_sha256),
                protected_dhash64=set(verified.protected_media_dhash),
                seed=SEED,
            )
            manifest = build_private_manifest(
                selection,
                test_sheet_sha256=expected_test_sheet_sha256,
                cutoff=verified.cutoff,
                checkpoint_sha256=CHECKPOINT_SHA256,
                protected_manifest_sha256=(
                    config.training_manifest.raw_sha256,
                    *verified.protected_manifest_raw_sha256,
                ),
            )
            _assert_attempt_snapshot_current(
                root,
                "inventory.private.json",
                inventory_snapshot,
                code="INVENTORY_CHANGED",
            )
            _assert_attempt_snapshot_current(
                root,
                "preflight.started.private.json",
                started_snapshot,
                code="MARKER_CHANGED",
            )
            _assert_attempt_snapshot_current(
                root,
                "preflight.complete.private.json",
                complete_snapshot,
                code="MARKER_CHANGED",
            )
            _assert_root_path_current(root)
            manifest_snapshot = _write_attempt_json(
                root, "batch-manifest.private.json", manifest
            )
            _write_attempt_marker(
                root,
                "manifest.complete.private.json",
                "GME_NEGATIVE_AUDIT_MANIFEST_FROZEN",
                extra=_snapshot_identity("manifest", manifest_snapshot),
            )
            return manifest
        except (AuditContractError, AuditShortageError) as error:
            _write_attempt_failure_best_effort(
                root,
                "manifest.failed.private.json",
                "GME_NEGATIVE_AUDIT_SHORTAGE"
                if isinstance(error, AuditShortageError)
                else "MANIFEST_CONTRACT_FAILED",
            )
            raise PreflightError(
                "GME_NEGATIVE_AUDIT_SHORTAGE"
                if isinstance(error, AuditShortageError)
                else "MANIFEST_CONTRACT_FAILED"
            ) from None
        except BaseException as error:
            _write_attempt_failure_best_effort(
                root,
                "manifest.failed.private.json",
                _safe_failure_code(error),
            )
            raise
    finally:
        root.close()


def import_batch(
    config: PreflightConfig,
    *,
    db: ImportDatabase,
    expected_test_sheet_sha256: str,
    expected_manifest_raw_sha256: str,
    apply: object,
) -> dict[str, object]:
    """Execute exactly one append/import RPC after all local gates pass."""
    if apply is not True:
        raise PreflightError("APPLY_REQUIRED")
    verified = _verify_config_and_pins(config)
    expected_test_sheet_sha256 = _require_sha(expected_test_sheet_sha256, "TEST_SHEET_PIN")
    expected_manifest_raw_sha256 = _require_sha(
        expected_manifest_raw_sha256, "MANIFEST_RAW_PIN"
    )
    if verified.test_sheet_raw_sha256 != expected_test_sheet_sha256:
        raise PreflightError("TEST_SHEET_PIN_MISMATCH")
    contract = _read_test_sheet_contract(config.test_sheet_path)
    _validate_frozen_test_sheet(contract, config=config, verified=verified)

    root = _open_attempt_root(config.attempt_root)
    try:
        started_snapshot = _validate_started_root(root)
        manifest_snapshot = _read_attempt_file(
            root, "batch-manifest.private.json", MAX_PIN_BYTES
        )
        if manifest_snapshot.sha256 != expected_manifest_raw_sha256:
            raise PreflightError("MANIFEST_RAW_PIN_MISMATCH")
        manifest = _strict_json_object(manifest_snapshot.payload)
        _validate_import_manifest(
            manifest, expected_test_sheet_sha256=expected_test_sheet_sha256
        )
        marker_snapshot = _read_attempt_file(
            root, "manifest.complete.private.json", MAX_PIN_BYTES
        )
        marker = _strict_json_object(marker_snapshot.payload)
        if (
            marker.get("status") != "GME_NEGATIVE_AUDIT_MANIFEST_FROZEN"
            or not _marker_matches_node_identity(marker, marker_snapshot)
            or not _marker_matches_snapshot(marker, "manifest", manifest_snapshot)
        ):
            raise PreflightError("MANIFEST_NOT_COMPLETE")
        if _attempt_entry_exists(root, "import.started.private.json"):
            raise PreflightError("IMPORT_ALREADY_STARTED")

        owner_rows = db.read("owner_exists", {"owner_id": config.owner_id})
        if owner_rows != [{"exists": True}]:
            raise PreflightError("OWNER_NOT_FOUND")
        _write_attempt_marker(
            root,
            "import.started.private.json",
            "GME_NEGATIVE_AUDIT_IMPORT_STARTED",
        )
        try:
            _assert_attempt_snapshot_current(
                root,
                "batch-manifest.private.json",
                manifest_snapshot,
                code="MANIFEST_CHANGED",
            )
            _assert_attempt_snapshot_current(
                root,
                "preflight.started.private.json",
                started_snapshot,
                code="MARKER_CHANGED",
            )
            _assert_attempt_snapshot_current(
                root,
                "manifest.complete.private.json",
                marker_snapshot,
                code="MARKER_CHANGED",
            )
            _assert_root_path_current(root)
            rows = db.write_rpc(
                "fn_create_gme_negative_audit_batch",
                {"p_owner_id": config.owner_id, "p_manifest": manifest},
            )
            if (
                not isinstance(rows, list)
                or len(rows) != 1
                or not isinstance(rows[0], dict)
                or set(rows[0]) != {"batch_id", "status"}
                or rows[0].get("status") != "prepared"
                or not _is_canonical_uuid(rows[0].get("batch_id"))
            ):
                raise PreflightError("IMPORT_RESPONSE_INVALID")
            result = {"batch_id": rows[0]["batch_id"], "status": "prepared"}
            _write_attempt_marker(
                root,
                "import.complete.private.json",
                "GME_NEGATIVE_AUDIT_IMPORT_COMPLETE",
                extra={"batch_id": rows[0]["batch_id"]},
            )
            return result
        except BaseException as error:
            _write_attempt_failure_best_effort(
                root,
                "import.failed.private.json",
                _safe_failure_code(error),
            )
            raise
    finally:
        root.close()


def _verify_config_and_pins(config: PreflightConfig) -> _VerifiedInputs:
    if not isinstance(config, PreflightConfig):
        raise PreflightError("CONFIG_INVALID")
    if (
        not config.attempt_root.is_absolute()
        or not config.test_sheet_path.is_absolute()
        or not config.training_manifest.path.is_absolute()
        or not config.r2_bucket
        or not _is_canonical_uuid(config.owner_id)
    ):
        raise PreflightError("CONFIG_INVALID")
    if config.training_manifest.role != "train":
        raise PreflightError("TRAINING_PIN_INVALID")
    training_raw = _read_pinned(config.training_manifest, MAX_PIN_BYTES)
    training = _strict_json_object(training_raw)
    if set(training) != {
        "schema_version",
        "status",
        "cutoff",
        "detector_identity",
        "checkpoint_sha256",
        "record_count",
        "records",
    }:
        raise PreflightError("TRAINING_PIN_INVALID")
    if (
        training.get("schema_version") != TRAINING_PIN_SCHEMA
        or training.get("status") != "frozen"
        or training.get("detector_identity") != DETECTOR_IDENTITY
        or training.get("checkpoint_sha256") != CHECKPOINT_SHA256
    ):
        raise PreflightError("TRAINING_PIN_INVALID")
    cutoff = training.get("cutoff")
    cutoff_dt = _parse_rfc3339(cutoff, "TRAINING_CUTOFF_INVALID")
    training_sha, training_dhash, training_source, training_r2 = _validate_media_records(
        training.get("records"), training.get("record_count"), expected_count=None
    )

    protected_roles = {pin.role for pin in config.protected_manifests}
    if protected_roles != set(PROTECTED_ROLE_COUNTS) or len(config.protected_manifests) != len(
        PROTECTED_ROLE_COUNTS
    ):
        raise PreflightError("PROTECTED_PIN_SET_INVALID")
    protected_sha = set(training_sha)
    protected_dhash = set(training_dhash)
    protected_source = set(training_source)
    protected_r2 = set(training_r2)
    manifest_digests: list[str] = []
    for pin in sorted(config.protected_manifests, key=lambda value: value.role):
        raw = _read_pinned(pin, MAX_PIN_BYTES)
        value = _strict_json_object(raw)
        if set(value) != {
            "schema_version",
            "status",
            "role",
            "record_count",
            "records",
        }:
            raise PreflightError("PROTECTED_PIN_INVALID")
        if (
            value.get("schema_version") != PROTECTED_PIN_SCHEMA
            or value.get("status") != "frozen"
            or value.get("role") != pin.role
        ):
            raise PreflightError("PROTECTED_PIN_INVALID")
        media_sha, media_dhash, source_sha, r2_sha = _validate_media_records(
            value.get("records"),
            value.get("record_count"),
            expected_count=PROTECTED_ROLE_COUNTS[pin.role],
        )
        if (
            protected_sha.intersection(media_sha)
            or protected_dhash.intersection(media_dhash)
            or protected_source.intersection(source_sha)
            or protected_r2.intersection(r2_sha)
        ):
            raise PreflightError("PROTECTED_PIN_DUPLICATE")
        protected_sha.update(media_sha)
        protected_dhash.update(media_dhash)
        protected_source.update(source_sha)
        protected_r2.update(r2_sha)
        manifest_digests.append(pin.raw_sha256)
    test_sheet_raw = _read_regular_file(config.test_sheet_path, MAX_TEST_SHEET_BYTES)
    return _VerifiedInputs(
        cutoff=cutoff,
        cutoff_dt=cutoff_dt,
        test_sheet_raw_sha256=hashlib.sha256(test_sheet_raw).hexdigest(),
        protected_manifest_raw_sha256=tuple(manifest_digests),
        protected_media_sha256=frozenset(protected_sha),
        protected_media_dhash=frozenset(protected_dhash),
        protected_source_identity_sha256=frozenset(protected_source),
        protected_r2_key_sha256=frozenset(protected_r2),
    )


def _validate_media_records(
    raw_records: object, raw_count: object, *, expected_count: int | None
) -> tuple[set[str], set[str], set[str], set[str]]:
    if (
        isinstance(raw_count, bool)
        or not isinstance(raw_count, int)
        or raw_count < 1
        or not isinstance(raw_records, list)
        or len(raw_records) != raw_count
        or (expected_count is not None and raw_count != expected_count)
    ):
        raise PreflightError("PROTECTED_PIN_INVALID")
    media_sha: set[str] = set()
    media_dhash: set[str] = set()
    source_sha: set[str] = set()
    r2_sha: set[str] = set()
    for record in raw_records:
        if not isinstance(record, dict) or set(record) != {
            "media_sha256",
            "media_dhash",
            "source_identity_sha256",
            "r2_key_sha256",
        }:
            raise PreflightError("PROTECTED_PIN_INVALID")
        sha = record.get("media_sha256")
        dhash = record.get("media_dhash")
        source = record.get("source_identity_sha256")
        r2 = record.get("r2_key_sha256")
        if not isinstance(sha, str) or _SHA256.fullmatch(sha) is None:
            raise PreflightError("PROTECTED_PIN_INVALID")
        if not isinstance(dhash, str) or _DHASH.fullmatch(dhash) is None:
            raise PreflightError("PROTECTED_PIN_INVALID")
        if not isinstance(source, str) or _SHA256.fullmatch(source) is None:
            raise PreflightError("PROTECTED_PIN_INVALID")
        if not isinstance(r2, str) or _SHA256.fullmatch(r2) is None:
            raise PreflightError("PROTECTED_PIN_INVALID")
        if sha in media_sha or dhash in media_dhash or source in source_sha or r2 in r2_sha:
            raise PreflightError("PROTECTED_PIN_DUPLICATE")
        media_sha.add(sha)
        media_dhash.add(dhash)
        source_sha.add(source)
        r2_sha.add(r2)
    return media_sha, media_dhash, source_sha, r2_sha


def _validate_source_row(
    raw: Mapping[str, object], *, stratum: str, verified: _VerifiedInputs
) -> dict[str, object]:
    if not isinstance(raw, Mapping) or set(raw) != _SOURCE_ROW_KEYS:
        raise PreflightError("source_contract_mismatch")
    clip_id = _canonical_uuid(raw["clip_id"], "source_contract_mismatch")
    camera_id = _canonical_uuid(raw["camera_id"], "source_contract_mismatch")
    started_at = _parse_rfc3339(raw["started_at"], "source_contract_mismatch")
    duration = raw["duration_sec"]
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not (0 < float(duration) <= 3600)
    ):
        raise PreflightError("source_contract_mismatch")
    r2_key = raw["r2_key"]
    if not isinstance(r2_key, str) or not r2_key.strip() or len(r2_key.encode()) > 1024:
        raise PreflightError("media_missing")
    if started_at < verified.cutoff_dt:
        raise PreflightError("before_training_cutoff")
    if raw["research_quarantined"] is not False:
        raise PreflightError("research_quarantined")
    if (
        raw["current_job_status"] != "succeeded"
        or raw["current_job_detector_identity"] != DETECTOR_IDENTITY
        or raw["current_run_status"] != "ok"
        or raw["current_detector_identity"] != DETECTOR_IDENTITY
        or raw["current_result_run_id"] != raw["current_run_id"]
    ):
        raise PreflightError("lineage_mismatch")
    run_id = _canonical_uuid(raw["current_run_id"], "lineage_mismatch")
    detected = raw["current_detected"]
    if type(detected) is not bool:
        raise PreflightError("lineage_mismatch")
    human_gt = raw["human_gt_digest"]
    if stratum == "random_negative":
        if raw["clip_purpose"] != "production" or detected is not False:
            raise PreflightError("not_random_negative")
        human_gt = None
    else:
        if (
            raw["dataset_role"] != "development"
            or raw["consensus_status"] not in {"agreed", "owner_resolved"}
            or raw["consensus_final_decision"] != "label"
            or raw["consensus_visibility"] not in {"visible", "partial"}
            or not isinstance(human_gt, str)
            or _SHA256.fullmatch(human_gt) is None
        ):
            raise PreflightError("control_consensus_mismatch")
    return {
        "clip_id": clip_id,
        "camera_id": camera_id,
        "started_at": started_at,
        "duration_sec": float(duration),
        "r2_key": r2_key,
        "gme_run_id": run_id,
        "gme_detected": detected,
        "human_gt_digest": human_gt,
    }


def _source_media_identity(source: Mapping[str, object]) -> tuple[object, ...]:
    return (
        source["camera_id"],
        source["started_at"],
        source["duration_sec"],
        source["r2_key"],
        source["gme_run_id"],
        source["gme_detected"],
    )


def _source_sort_key(raw: Mapping[str, object]) -> tuple[str, str]:
    started = raw.get("started_at") if isinstance(raw, Mapping) else ""
    clip_id = raw.get("clip_id") if isinstance(raw, Mapping) else ""
    return (str(started), str(clip_id))


def _read_media_bytes(
    r2: ReadR2,
    *,
    bucket: str,
    key: str,
    remaining_total_bytes: int,
    read_counts: dict[str, int],
) -> bytes:
    read_counts["head"] += 1
    try:
        head = r2.head_object(Bucket=bucket, Key=key)
    except BaseException:
        raise PreflightError("media_missing") from None
    metadata = head.get("ResponseMetadata") if isinstance(head, Mapping) else None
    content_length = head.get("ContentLength") if isinstance(head, Mapping) else None
    content_type = head.get("ContentType") if isinstance(head, Mapping) else None
    if (
        not isinstance(metadata, Mapping)
        or metadata.get("HTTPStatusCode") != 200
        or isinstance(content_length, bool)
        or not isinstance(content_length, int)
        or content_length < 1
        or content_length > MAX_MEDIA_BYTES
        or content_length > remaining_total_bytes
        or not isinstance(content_type, str)
        or not content_type.startswith("video/")
    ):
        raise PreflightError("media_head_invalid")
    body: object | None = None
    try:
        read_counts["get"] += 1
        response = r2.get_object(Bucket=bucket, Key=key)
        metadata = response.get("ResponseMetadata") if isinstance(response, Mapping) else None
        response_length = response.get("ContentLength") if isinstance(response, Mapping) else None
        body = response.get("Body") if isinstance(response, Mapping) else None
        if (
            not isinstance(metadata, Mapping)
            or metadata.get("HTTPStatusCode") != 200
            or response_length != content_length
            or body is None
            or not callable(getattr(body, "read", None))
        ):
            raise PreflightError("media_get_invalid")
        payload = bytearray()
        while len(payload) <= content_length:
            chunk = body.read(min(MEDIA_READ_CHUNK, content_length + 1 - len(payload)))
            if not isinstance(chunk, bytes):
                raise PreflightError("media_get_invalid")
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) != content_length:
            raise PreflightError("media_length_mismatch")
        return bytes(payload)
    except PreflightError:
        raise
    except BaseException:
        raise PreflightError("media_get_failed") from None
    finally:
        if body is not None and callable(getattr(body, "close", None)):
            try:
                body.close()
            except BaseException:
                pass


def _probe_media_bytes(payload: bytes) -> tuple[str, str]:
    """Hash actual bytes and dHash the deterministic midpoint decoded frame."""
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_MEDIA_BYTES:
        raise PreflightError("MEDIA_DECODE_FAILED")
    media_sha = hashlib.sha256(payload).hexdigest()
    fd, temp_name = tempfile.mkstemp(prefix="gme-negative-audit-probe-", suffix=".mp4")
    capture = None
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(payload)
        written = 0
        while written < len(view):
            written += os.write(fd, view[written:])
        os.fsync(fd)
        os.close(fd)
        fd = -1
        import cv2

        capture = cv2.VideoCapture(temp_name)
        if not capture.isOpened():
            raise PreflightError("MEDIA_DECODE_FAILED")
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count > 1:
            capture.set(cv2.CAP_PROP_POS_FRAMES, (frame_count - 1) // 2)
        ok, frame = capture.read()
        if not ok or frame is None or frame.size == 0:
            capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = capture.read()
        if not ok or frame is None or frame.size == 0:
            raise PreflightError("MEDIA_DECODE_FAILED")
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
        bits = resized[:, 1:] > resized[:, :-1]
        value = 0
        for bit in bits.reshape(-1):
            value = (value << 1) | int(bit)
        return media_sha, f"{value:016x}"
    except PreflightError:
        raise
    except BaseException:
        raise PreflightError("MEDIA_DECODE_FAILED") from None
    finally:
        if capture is not None:
            capture.release()
        if fd != -1:
            os.close(fd)
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _derive_manifest_candidates(
    eligible: Sequence[_EligibleSource],
) -> dict[str, list[dict[str, object]]]:
    by_camera_night: dict[tuple[str, str], list[_EligibleSource]] = {}
    for source in eligible:
        activity_day = (source.started_at.astimezone(timezone(timedelta(hours=9))) - timedelta(hours=7)).date()
        by_camera_night.setdefault((source.camera_id, activity_day.isoformat()), []).append(source)
    derived: list[dict[str, object]] = []
    for (camera_id, activity_day), rows in sorted(by_camera_night.items()):
        rows = sorted(rows, key=lambda row: (row.started_at, row.clip_id))
        episode_number = 0
        previous_end: datetime | None = None
        for source in rows:
            if previous_end is None or (source.started_at - previous_end).total_seconds() > EPISODE_GAP_SEC:
                episode_number += 1
            previous_end = max(
                previous_end or source.started_at,
                source.started_at + timedelta(seconds=source.duration_sec),
            )
            camera_night_key = hashlib.sha256(
                f"camera-night-v1:{camera_id}:{activity_day}".encode()
            ).hexdigest()
            episode_key = hashlib.sha256(
                f"episode-v1:{camera_id}:{activity_day}:{episode_number}".encode()
            ).hexdigest()
            derived.append(
                {
                    "clip_id": source.clip_id,
                    "stratum": source.stratum,
                    "started_at": _format_rfc3339(source.started_at),
                    "duration_sec": source.duration_sec,
                    "camera_night_key": camera_night_key,
                    "episode_key": episode_key,
                    "gme_run_id": source.gme_run_id,
                    "detector_identity": DETECTOR_IDENTITY,
                    "media_sha256": source.media_sha256,
                    "media_dhash": source.media_dhash,
                    "gme_detected": source.gme_detected,
                    "human_gt_digest": source.human_gt_digest,
                }
            )
    return {
        "random_negative": sorted(
            (row for row in derived if row["stratum"] == "random_negative"),
            key=lambda row: (str(row["started_at"]), str(row["clip_id"])),
        ),
        "positive_control": sorted(
            (row for row in derived if row["stratum"] == "positive_control"),
            key=lambda row: (str(row["started_at"]), str(row["clip_id"])),
        ),
    }


def _coverage_ready(
    negative_pool: Sequence[Mapping[str, object]],
    control_pool: Sequence[Mapping[str, object]],
) -> tuple[bool, int]:
    try:
        selection = select_calibration_batch(
            negative_pool,
            control_pool,
            protected_sha256=set(),
            protected_dhash64=set(),
            seed=SEED,
        )
    except AuditShortageError as error:
        return False, error.eligible_count or 0
    except AuditContractError:
        return False, 0
    return True, len(selection.control_pool)


def _build_availability(
    *,
    status_value: str,
    negative_rows: int,
    control_rows: int,
    candidate_pools: Mapping[str, Sequence[Mapping[str, object]]],
    eligible_sources: Sequence[_EligibleSource],
    unavailable: Mapping[str, int],
    db_read_count: int,
    r2_head_count: int,
    r2_get_count: int,
    protected_media_get_count: int,
    post_negative_control_count: int,
) -> dict[str, object]:
    all_rows = [*candidate_pools["random_negative"], *candidate_pools["positive_control"]]
    return {
        "schema_version": AVAILABILITY_SCHEMA,
        "status": status_value,
        "source_counts": {
            "random_negative": negative_rows,
            "positive_control": control_rows,
        },
        "eligible_counts": {
            "random_negative": len(candidate_pools["random_negative"]),
            "positive_control": len(candidate_pools["positive_control"]),
        },
        "post_negative_control_count": post_negative_control_count,
        "camera_count": len({row.camera_id for row in eligible_sources}),
        "camera_night_count": len({row["camera_night_key"] for row in all_rows}),
        "episode_count": len({row["episode_key"] for row in all_rows}),
        "unavailable_reasons": dict(sorted(unavailable.items())),
        "db_read_count": db_read_count,
        "r2_head_count": r2_head_count,
        "r2_get_count": r2_get_count,
        "protected_media_get_count": protected_media_get_count,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def _read_test_sheet_contract(path: Path) -> dict[str, object]:
    raw = _read_regular_file(path, MAX_TEST_SHEET_BYTES)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise PreflightError("TEST_SHEET_CONTRACT_INVALID") from None
    begin = text.find(_MACHINE_BEGIN)
    end = text.find(_MACHINE_END)
    if begin < 0 or end < 0 or end <= begin or text.find(_MACHINE_BEGIN, begin + 1) >= 0:
        raise PreflightError("TEST_SHEET_CONTRACT_INVALID")
    payload = text[begin + len(_MACHINE_BEGIN) : end].strip()
    value = _strict_json_object(payload.encode())
    if set(value) != _TEST_SHEET_KEYS:
        raise PreflightError("TEST_SHEET_CONTRACT_INVALID")
    return value


def _validate_frozen_test_sheet(
    contract: Mapping[str, object], *, config: PreflightConfig, verified: _VerifiedInputs
) -> None:
    expected_protected = {
        pin.role: pin.raw_sha256
        for pin in sorted(config.protected_manifests, key=lambda value: value.role)
    }
    if (
        contract.get("schema_version") != TEST_SHEET_SCHEMA
        or contract.get("freeze_status") != "FROZEN"
        or contract.get("owner_approval") != "APPROVED"
        or contract.get("reviewed_import_schema") != "gme-negative-audit-v1"
        or contract.get("seed") != SEED
        or contract.get("selection_algorithm_version") != SELECTION_ALGORITHM_VERSION
        or contract.get("negative_count") != NEGATIVE_COUNT
        or contract.get("control_count") != CONTROL_COUNT
        or contract.get("episode_cap") != 2
        or contract.get("detector_identity") != DETECTOR_IDENTITY
        or contract.get("checkpoint_sha256") != CHECKPOINT_SHA256
        or contract.get("training_manifest_sha256") != config.training_manifest.raw_sha256
        or contract.get("cutoff") != verified.cutoff
        or contract.get("protected_manifest_sha256") != expected_protected
        or contract.get("approved_reviewer_ids") != [config.owner_id]
    ):
        raise PreflightError("TEST_SHEET_NOT_FROZEN")


def _validate_import_manifest(
    manifest: Mapping[str, object], *, expected_test_sheet_sha256: str
) -> None:
    required = {
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
    if set(manifest) != required:
        raise PreflightError("MANIFEST_CONTRACT_INVALID")
    unsigned = dict(manifest)
    claimed = unsigned.pop("manifest_sha256", None)
    actual = hashlib.sha256(_canonical_json(unsigned)).hexdigest()
    if (
        manifest.get("schema_version") != "gme-negative-audit-v1"
        or manifest.get("status") != "prepared"
        or manifest.get("batch_kind") != "calibration"
        or manifest.get("test_sheet_sha256") != expected_test_sheet_sha256
        or manifest.get("seed") != SEED
        or manifest.get("detector_identity") != DETECTOR_IDENTITY
        or manifest.get("checkpoint_sha256") != CHECKPOINT_SHA256
        or claimed != actual
        or not isinstance(manifest.get("items"), list)
        or len(manifest["items"]) != NEGATIVE_COUNT + CONTROL_COUNT
    ):
        raise PreflightError("MANIFEST_CONTRACT_INVALID")


def _create_attempt_root(path: Path) -> _AttemptRoot:
    if path.exists() or path.is_symlink():
        raise PreflightError("ATTEMPT_EXISTS")
    fd = -1
    try:
        path.mkdir(mode=0o700, parents=False)
    except FileExistsError:
        raise PreflightError("ATTEMPT_EXISTS") from None
    except OSError:
        raise PreflightError("ATTEMPT_CREATE_FAILED") from None
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
        os.fchmod(fd, 0o700)
        info = os.fstat(fd)
        path_info = os.stat(path, follow_symlinks=False)
        mode = stat.S_IMODE(info.st_mode)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != _expected_uid()
            or mode != 0o700
        ):
            raise PreflightError("ATTEMPT_ROOT_SECURITY_INVALID")
        if (
            not stat.S_ISDIR(path_info.st_mode)
            or path_info.st_dev != info.st_dev
            or path_info.st_ino != info.st_ino
            or path_info.st_uid != info.st_uid
            or stat.S_IMODE(path_info.st_mode) != mode
        ):
            raise PreflightError("ATTEMPT_ROOT_IDENTITY_MISMATCH")
        return _AttemptRoot(
            path=path,
            fd=fd,
            dev=info.st_dev,
            ino=info.st_ino,
            uid=info.st_uid,
            mode=mode,
        )
    except PreflightError:
        if fd != -1:
            os.close(fd)
        raise
    except OSError:
        if fd != -1:
            os.close(fd)
        raise PreflightError("ATTEMPT_CREATE_FAILED") from None


def _expected_uid() -> int:
    return os.geteuid()


def _open_attempt_root(path: Path) -> _AttemptRoot:
    if not path.is_absolute():
        raise PreflightError("ATTEMPT_ROOT_SECURITY_INVALID")
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError:
        raise PreflightError("ATTEMPT_ROOT_SECURITY_INVALID") from None
    try:
        info = os.fstat(fd)
        mode = stat.S_IMODE(info.st_mode)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != _expected_uid()
            or mode != 0o700
        ):
            raise PreflightError("ATTEMPT_ROOT_SECURITY_INVALID")
        return _AttemptRoot(
            path=path,
            fd=fd,
            dev=info.st_dev,
            ino=info.st_ino,
            uid=info.st_uid,
            mode=mode,
        )
    except BaseException:
        os.close(fd)
        raise


def _assert_root_path_current(root: _AttemptRoot) -> None:
    current = _open_attempt_root(root.path)
    try:
        if (current.dev, current.ino, current.uid, current.mode) != (
            root.dev,
            root.ino,
            root.uid,
            root.mode,
        ):
            raise PreflightError("ATTEMPT_ROOT_IDENTITY_MISMATCH")
    finally:
        current.close()


def _root_identity(root: _AttemptRoot) -> dict[str, int]:
    return {
        "attempt_root_dev": root.dev,
        "attempt_root_ino": root.ino,
        "attempt_root_uid": root.uid,
        "attempt_root_mode": root.mode,
    }


def _validate_started_root(root: _AttemptRoot) -> _FileSnapshot:
    snapshot = _read_attempt_file(root, "preflight.started.private.json", MAX_PIN_BYTES)
    marker = _strict_json_object(snapshot.payload)
    if (
        marker.get("schema_version") != "gme-negative-audit-attempt-v1"
        or marker.get("status") != "GME_NEGATIVE_AUDIT_PREFLIGHT_STARTED"
        or not _marker_matches_node_identity(marker, snapshot)
        or any(marker.get(key) != value for key, value in _root_identity(root).items())
    ):
        raise PreflightError("ATTEMPT_ROOT_IDENTITY_MISMATCH")
    return snapshot


def _write_attempt_json(
    root: _AttemptRoot,
    name: str,
    payload: Mapping[str, object],
    *,
    bind_node_identity: bool = False,
) -> _FileSnapshot:
    _validate_attempt_name(name)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, 0o600, dir_fd=root.fd)
    except OSError:
        raise PreflightError("ATTEMPT_FILE_EXISTS") from None
    try:
        os.fchmod(fd, 0o600)
        document = dict(payload)
        if bind_node_identity:
            document.update(_node_identity_from_stat(os.fstat(fd)))
        encoded = _canonical_json(document) + b"\n"
        written = 0
        while written < len(encoded):
            written += os.write(fd, encoded[written:])
        os.fsync(fd)
        info = os.fstat(fd)
        _validate_attempt_file_stat(info, expected_size=len(encoded))
    finally:
        os.close(fd)
    os.fsync(root.fd)
    snapshot = _read_attempt_file(root, name, max(len(encoded), 1))
    if bind_node_identity:
        marker = _strict_json_object(snapshot.payload)
        if not _marker_matches_node_identity(marker, snapshot):
            raise PreflightError("ATTEMPT_FILE_CHANGED")
    return snapshot


def _write_attempt_marker(
    root: _AttemptRoot,
    name: str,
    status_value: str,
    *,
    extra: Mapping[str, object] | None = None,
) -> _FileSnapshot:
    payload: dict[str, object] = {
        "schema_version": "gme-negative-audit-attempt-v1",
        "status": status_value,
    }
    if extra:
        payload.update(extra)
    return _write_attempt_json(root, name, payload, bind_node_identity=True)


def _write_attempt_failure_best_effort(
    root: _AttemptRoot, name: str, code: str
) -> None:
    try:
        _write_attempt_marker(root, name, "FAILED", extra={"failure_code": code})
    except BaseException:
        pass


def _read_attempt_file(root: _AttemptRoot, name: str, maximum: int) -> _FileSnapshot:
    _validate_attempt_name(name)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, dir_fd=root.fd)
    except OSError:
        raise PreflightError("ATTEMPT_FILE_INVALID") from None
    try:
        before = os.fstat(fd)
        _validate_attempt_file_stat(before, maximum=maximum)
        payload = bytearray()
        while len(payload) <= maximum:
            chunk = os.read(fd, min(1024 * 1024, maximum + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(fd)
        if _stat_identity(before) != _stat_identity(after) or len(payload) != before.st_size:
            raise PreflightError("ATTEMPT_FILE_CHANGED")
        return _FileSnapshot(
            payload=bytes(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            dev=before.st_dev,
            ino=before.st_ino,
            uid=before.st_uid,
            mode=stat.S_IMODE(before.st_mode),
            nlink=before.st_nlink,
            size=before.st_size,
            mtime_ns=before.st_mtime_ns,
        )
    finally:
        os.close(fd)


def _validate_attempt_file_stat(
    info: os.stat_result,
    *,
    maximum: int | None = None,
    expected_size: int | None = None,
) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != _expected_uid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
        or info.st_size < 1
        or (maximum is not None and info.st_size > maximum)
        or (expected_size is not None and info.st_size != expected_size)
    ):
        raise PreflightError("ATTEMPT_FILE_INVALID")


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        stat.S_IMODE(info.st_mode),
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
    )


def _snapshot_identity(prefix: str, snapshot: _FileSnapshot) -> dict[str, int | str]:
    return {
        f"{prefix}_raw_sha256": snapshot.sha256,
        f"{prefix}_dev": snapshot.dev,
        f"{prefix}_ino": snapshot.ino,
        f"{prefix}_uid": snapshot.uid,
        f"{prefix}_mode": snapshot.mode,
        f"{prefix}_nlink": snapshot.nlink,
        f"{prefix}_size": snapshot.size,
    }


def _node_identity_from_stat(info: os.stat_result) -> dict[str, int]:
    return {
        "marker_dev": info.st_dev,
        "marker_ino": info.st_ino,
        "marker_uid": info.st_uid,
        "marker_mode": stat.S_IMODE(info.st_mode),
        "marker_nlink": info.st_nlink,
    }


def _marker_matches_node_identity(
    marker: Mapping[str, object], snapshot: _FileSnapshot
) -> bool:
    return marker.get("marker_dev") == snapshot.dev and all(
        marker.get(key) == value
        for key, value in {
            "marker_ino": snapshot.ino,
            "marker_uid": snapshot.uid,
            "marker_mode": snapshot.mode,
            "marker_nlink": snapshot.nlink,
        }.items()
    )


def _marker_matches_snapshot(
    marker: Mapping[str, object], prefix: str, snapshot: _FileSnapshot
) -> bool:
    return all(marker.get(key) == value for key, value in _snapshot_identity(prefix, snapshot).items())


def _assert_attempt_snapshot_current(
    root: _AttemptRoot, name: str, snapshot: _FileSnapshot, *, code: str
) -> None:
    current = _read_attempt_file(root, name, max(snapshot.size, 1))
    if (
        current.sha256,
        current.dev,
        current.ino,
        current.uid,
        current.mode,
        current.nlink,
        current.size,
        current.mtime_ns,
    ) != (
        snapshot.sha256,
        snapshot.dev,
        snapshot.ino,
        snapshot.uid,
        snapshot.mode,
        snapshot.nlink,
        snapshot.size,
        snapshot.mtime_ns,
    ):
        raise PreflightError(code)


def _attempt_entry_exists(root: _AttemptRoot, name: str) -> bool:
    _validate_attempt_name(name)
    try:
        os.stat(name, dir_fd=root.fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError:
        raise PreflightError("ATTEMPT_FILE_INVALID") from None
    return True


def _validate_attempt_name(name: str) -> None:
    if not name or name in {".", ".."} or "/" in name or os.sep in name:
        raise PreflightError("ATTEMPT_FILE_INVALID")


def _safe_failure_code(error: BaseException) -> str:
    if isinstance(error, PreflightError):
        value = str(error)
        if re.fullmatch(r"[A-Za-z0-9_]+", value):
            return value
    return "PREFLIGHT_FAILED"


def _read_pinned(pin: PinnedJson, maximum: int) -> bytes:
    _require_sha(pin.raw_sha256, "PIN")
    raw = _read_regular_private(pin.path, maximum)
    if hashlib.sha256(raw).hexdigest() != pin.raw_sha256:
        raise PreflightError("PIN_MISMATCH")
    return raw


def _read_regular_private(path: Path, maximum: int) -> bytes:
    return _read_regular(path, maximum, require_private=True)


def _read_regular_file(path: Path, maximum: int) -> bytes:
    return _read_regular(path, maximum, require_private=False)


def _read_regular(path: Path, maximum: int, *, require_private: bool) -> bytes:
    if not path.is_absolute():
        raise PreflightError("PATH_INVALID")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError:
        raise PreflightError("PRIVATE_INPUT_INVALID") from None
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_size < 1
            or info.st_size > maximum
            or (require_private and stat.S_IMODE(info.st_mode) & 0o077)
        ):
            raise PreflightError("PRIVATE_INPUT_INVALID")
        payload = bytearray()
        while len(payload) <= maximum:
            chunk = os.read(fd, min(1024 * 1024, maximum + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) != info.st_size:
            raise PreflightError("PRIVATE_INPUT_CHANGED")
        after = os.fstat(fd)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
        ):
            raise PreflightError("PRIVATE_INPUT_CHANGED")
        return bytes(payload)
    finally:
        os.close(fd)


def _strict_json_object(raw: bytes) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise PreflightError("JSON_DUPLICATE_KEY")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except PreflightError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        raise PreflightError("JSON_INVALID") from None
    if not isinstance(value, dict):
        raise PreflightError("JSON_ROOT_INVALID")
    return value


def _parse_rfc3339(value: object, code: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PreflightError(code)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise PreflightError(code) from None
    if parsed.tzinfo is None or _format_rfc3339(parsed) != value:
        raise PreflightError(code)
    return parsed.astimezone(timezone.utc)


def _canonicalize_database_timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise PreflightError("DB_READ_FAILED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PreflightError("DB_READ_FAILED") from None
    if parsed.tzinfo is None:
        raise PreflightError("DB_READ_FAILED")
    return _format_rfc3339(parsed)


def _format_rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_uuid(value: object, code: str) -> str:
    if not _is_canonical_uuid(value):
        raise PreflightError(code)
    return str(value)


def _is_canonical_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def _require_sha(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PreflightError(f"{name}_INVALID")
    return value


def _near_any(value: str, protected: Sequence[str] | set[str] | frozenset[str], *, maximum: int) -> bool:
    candidate = int(value, 16)
    return any((candidate ^ int(other, 16)).bit_count() <= maximum for other in protected)


def _source_identity_sha256(clip_id: str) -> str:
    return hashlib.sha256(
        b"gme-negative-audit-source-identity-v1\0" + clip_id.encode("utf-8")
    ).hexdigest()


def _r2_key_sha256(r2_key: str) -> str:
    return hashlib.sha256(
        b"gme-negative-audit-r2-key-v1\0" + r2_key.encode("utf-8")
    ).hexdigest()


def _bump(counts: dict[str, int], reason: str) -> None:
    counts[reason] = counts.get(reason, 0) + 1


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        ensure_ascii=False,
    ).encode()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare the private, read-only GME negative audit calibration batch."
    )
    commands = parser.add_subparsers(dest="command")

    preflight = commands.add_parser(
        "preflight", help="read DB/R2 and publish only private local preflight artifacts"
    )
    _add_pin_arguments(preflight, include_r2=True)

    freeze = commands.add_parser(
        "freeze", help="freeze one manifest from a completed preflight inventory"
    )
    _add_pin_arguments(freeze, include_r2=False)
    freeze.add_argument("--expected-test-sheet-sha256", required=True)

    apply_command = commands.add_parser(
        "import", help="one-shot import; requires the literal --apply flag"
    )
    _add_pin_arguments(apply_command, include_r2=False)
    apply_command.add_argument("--expected-test-sheet-sha256", required=True)
    apply_command.add_argument("--expected-manifest-raw-sha256", required=True)
    apply_command.add_argument("--apply", action="store_true", required=True)
    return parser


def _add_pin_arguments(parser: argparse.ArgumentParser, *, include_r2: bool) -> None:
    parser.add_argument("--attempt-root", type=Path, required=True)
    parser.add_argument("--training-manifest", type=Path, required=True)
    parser.add_argument("--training-manifest-sha256", required=True)
    parser.add_argument("--protected-manifest", action="append", default=[], required=True)
    parser.add_argument(
        "--protected-manifest-sha256", action="append", default=[], required=True
    )
    parser.add_argument("--test-sheet", type=Path, required=True)
    if include_r2:
        parser.add_argument("--r2-bucket", required=True)


def _parse_role_values(values: Sequence[str], *, path_values: bool) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for value in values:
        if not isinstance(value, str) or value.count("=") != 1:
            raise PreflightError("CLI_PIN_INVALID")
        role, raw = value.split("=", 1)
        if role not in PROTECTED_ROLE_COUNTS or role in parsed or not raw:
            raise PreflightError("CLI_PIN_INVALID")
        parsed[role] = Path(raw) if path_values else _require_sha(raw, "CLI_PIN")
    if set(parsed) != set(PROTECTED_ROLE_COUNTS):
        raise PreflightError("CLI_PIN_INVALID")
    return parsed


def _config_from_args(args: argparse.Namespace) -> PreflightConfig:
    owner_id = os.environ.get("DEV_USER_ID", "")
    protected_paths = _parse_role_values(args.protected_manifest, path_values=True)
    protected_sha = _parse_role_values(
        args.protected_manifest_sha256, path_values=False
    )
    protected = tuple(
        PinnedJson(
            role=role,
            path=protected_paths[role],  # type: ignore[arg-type]
            raw_sha256=protected_sha[role],  # type: ignore[arg-type]
        )
        for role in sorted(PROTECTED_ROLE_COUNTS)
    )
    return PreflightConfig(
        attempt_root=args.attempt_root,
        training_manifest=PinnedJson(
            role="train",
            path=args.training_manifest,
            raw_sha256=args.training_manifest_sha256,
        ),
        protected_manifests=protected,
        test_sheet_path=args.test_sheet,
        owner_id=owner_id,
        r2_bucket=getattr(args, "r2_bucket", "not-used-by-this-command"),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    db_factory: Callable[[], object] | None = None,
    r2_factory: Callable[[], object] | None = None,
) -> int:
    args = list(argv) if argv is not None else None
    parser = build_parser()
    if args == [] or args == ["--help"] or args == ["-h"]:
        parser.print_help()
        return 0
    parsed = parser.parse_args(args)
    if parsed.command is None:
        parser.print_help()
        return 0
    config = _config_from_args(parsed)
    if parsed.command == "preflight":
        db = db_factory() if db_factory is not None else _create_live_db()
        r2 = r2_factory() if r2_factory is not None else _create_live_r2()
        result = run_preflight(config, db=db, r2=r2)  # type: ignore[arg-type]
    elif parsed.command == "freeze":
        result = freeze_batch_manifest(
            config,
            expected_test_sheet_sha256=parsed.expected_test_sheet_sha256,
        )
        result = {
            "status": "GME_NEGATIVE_AUDIT_MANIFEST_FROZEN",
            "manifest_sha256": result["manifest_sha256"],
            "item_count": len(result["items"]),
        }
    elif parsed.command == "import":
        db = db_factory() if db_factory is not None else _create_live_db()
        result = import_batch(
            config,
            db=db,  # type: ignore[arg-type]
            expected_test_sheet_sha256=parsed.expected_test_sheet_sha256,
            expected_manifest_raw_sha256=parsed.expected_manifest_raw_sha256,
            apply=parsed.apply,
        )
    else:
        parser.print_help()
        return 0
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


def _create_live_db() -> object:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise PreflightError("SUPABASE_CONFIG_REQUIRED")
    from supabase import create_client

    return _SupabaseAuditDb(create_client(url, key))


def _create_live_r2() -> object:
    from backend.r2_uploader import get_r2_client

    return get_r2_client()


class _SupabaseAuditDb:
    """Narrow adapter: preflight has table SELECT/auth GET; import has one RPC."""

    def __init__(self, client: object) -> None:
        self._client = client
        self._source_cache: list[dict[str, object]] | None = None

    def read(self, operation: str, params: dict[str, object]) -> list[dict[str, object]]:
        if operation == "owner_exists":
            return self._owner_exists(str(params.get("owner_id", "")))
        if operation not in {"negative_candidates", "positive_controls"}:
            raise PreflightError("DB_READ_OPERATION_REJECTED")
        cutoff = str(params.get("cutoff", ""))
        detector_identity = str(params.get("detector_identity", ""))
        if detector_identity != DETECTOR_IDENTITY:
            raise PreflightError("DB_READ_PIN_MISMATCH")
        if self._source_cache is None:
            self._source_cache = self._load_source_rows(cutoff=cutoff)
        if operation == "negative_candidates":
            return [
                row
                for row in self._source_cache
                if row["current_detected"] is False
            ]
        return [
            row
            for row in self._source_cache
            if row["consensus_visibility"] in {"visible", "partial"}
        ]

    def write_rpc(self, operation: str, params: dict[str, object]) -> list[dict[str, object]]:
        if operation != "fn_create_gme_negative_audit_batch" or set(params) != {
            "p_owner_id",
            "p_manifest",
        }:
            raise PreflightError("DB_WRITE_OPERATION_REJECTED")
        try:
            response = self._client.rpc(operation, params).execute()  # type: ignore[attr-defined]
        except BaseException:
            raise PreflightError("IMPORT_RPC_FAILED") from None
        data = getattr(response, "data", None)
        if not isinstance(data, list):
            raise PreflightError("IMPORT_RPC_FAILED")
        return data

    def _owner_exists(self, owner_id: str) -> list[dict[str, object]]:
        if not _is_canonical_uuid(owner_id):
            return [{"exists": False}]
        try:
            response = self._client.auth.admin.get_user_by_id(owner_id)  # type: ignore[attr-defined]
        except BaseException:
            raise PreflightError("OWNER_LOOKUP_FAILED") from None
        user = getattr(response, "user", None)
        user_id = getattr(user, "id", None)
        return [{"exists": str(user_id) == owner_id}]

    def _load_source_rows(self, *, cutoff: str) -> list[dict[str, object]]:
        # PostgREST does not expose a cross-table snapshot RPC for this task. Read
        # the minimum projections, then reproduce fn_current_gme_activity's exact
        # completed_at/id order locally. The import RPC re-locks and revalidates the
        # same lineage before any row can be created.
        clips = self._select_pages(
            "motion_clips",
            "id,camera_id,started_at,duration_sec,r2_key,clip_purpose",
            filters=(("eq", "clip_purpose", "production"), ("gte", "started_at", cutoff)),
        )
        if len(clips) > MAX_ROWS_PER_STRATUM * 2:
            raise PreflightError("SOURCE_ROW_BOUND_EXCEEDED")
        clip_ids = [str(row.get("id")) for row in clips]
        jobs = self._select_in_chunks(
            "gme_jobs",
            "id,clip_id,status,result_run_id,completed_at,detector_identity",
            "clip_id",
            clip_ids,
        )
        succeeded = [row for row in jobs if row.get("status") == "succeeded"]
        current_jobs: dict[str, dict[str, object]] = {}
        for row in succeeded:
            clip_id = str(row.get("clip_id"))
            current = current_jobs.get(clip_id)
            rank = (str(row.get("completed_at") or ""), str(row.get("id") or ""))
            current_rank = (
                str(current.get("completed_at") or ""),
                str(current.get("id") or ""),
            ) if current else ("", "")
            if current is None or rank > current_rank:
                current_jobs[clip_id] = row
        run_ids = [str(row.get("result_run_id")) for row in current_jobs.values() if row.get("result_run_id")]
        runs = self._select_in_chunks(
            "gme_runs",
            "id,clip_id,status,detector_identity,visible_sec,max_simultaneous_geckos",
            "id",
            run_ids,
        )
        runs_by_id = {str(row.get("id")): row for row in runs}
        consensus_rows = self._select_in_chunks(
            "motion_clip_consensus",
            "clip_id,status,final_decision,final_gt",
            "clip_id",
            clip_ids,
        )
        consensus_by_clip = {str(row.get("clip_id")): row for row in consensus_rows}
        exclusion_rows = self._select_in_chunks(
            "motion_clip_system_exclusions",
            "clip_id,state",
            "clip_id",
            clip_ids,
        )
        quarantined_clip_ids = {
            str(row.get("clip_id"))
            for row in exclusion_rows
            if row.get("state") in {"quarantined", "media_deleted"}
        }
        result: list[dict[str, object]] = []
        for clip in clips:
            clip_id = str(clip.get("id"))
            job = current_jobs.get(clip_id, {})
            run = runs_by_id.get(str(job.get("result_run_id")), {})
            consensus = consensus_by_clip.get(clip_id, {})
            final_gt = consensus.get("final_gt")
            visibility = final_gt.get("visibility") if isinstance(final_gt, dict) else None
            gt_digest = (
                self._canonical_gt_digest(final_gt)
                if isinstance(final_gt, dict)
                else None
            )
            visible_sec = run.get("visible_sec")
            max_geckos = run.get("max_simultaneous_geckos")
            detected = (
                float(visible_sec) > 0 and int(max_geckos) > 0
                if visible_sec is not None and max_geckos is not None
                else None
            )
            result.append(
                {
                    "clip_id": clip_id,
                    "camera_id": clip.get("camera_id"),
                    "started_at": _canonicalize_database_timestamp(
                        clip.get("started_at")
                    ),
                    "duration_sec": clip.get("duration_sec"),
                    "r2_key": clip.get("r2_key"),
                    "clip_purpose": clip.get("clip_purpose"),
                    "dataset_role": "development" if visibility in {"visible", "partial"} else None,
                    "current_job_status": job.get("status"),
                    "current_job_detector_identity": job.get("detector_identity"),
                    "current_result_run_id": job.get("result_run_id"),
                    "current_run_id": run.get("id"),
                    "current_run_status": run.get("status"),
                    "current_detector_identity": run.get("detector_identity"),
                    "current_detected": detected,
                    "consensus_status": consensus.get("status"),
                    "consensus_final_decision": consensus.get("final_decision"),
                    "consensus_visibility": visibility,
                    "human_gt_digest": gt_digest,
                    "research_quarantined": clip_id in quarantined_clip_ids,
                }
            )
        return result

    def _canonical_gt_digest(self, final_gt: Mapping[str, object]) -> str:
        try:
            response = self._client.rpc(
                "fn_gme_negative_audit_canonical_json", {"p_value": dict(final_gt)}
            ).execute()
        except BaseException:
            raise PreflightError("DB_READ_FAILED") from None
        canonical = getattr(response, "data", None)
        if not isinstance(canonical, str) or not canonical.startswith("{"):
            raise PreflightError("DB_READ_FAILED")
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _select_pages(
        self,
        table: str,
        projection: str,
        *,
        filters: Sequence[tuple[str, str, object]] = (),
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        page_size = 1000
        for start in range(0, MAX_ROWS_PER_STRATUM * 2, page_size):
            try:
                query = self._client.table(table).select(projection)  # type: ignore[attr-defined]
                for method, column, value in filters:
                    query = getattr(query, method)(column, value)
                response = query.range(start, start + page_size - 1).execute()
            except BaseException:
                raise PreflightError("DB_READ_FAILED") from None
            page = getattr(response, "data", None)
            if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
                raise PreflightError("DB_READ_FAILED")
            rows.extend(page)
            if len(page) < page_size:
                return rows
        raise PreflightError("SOURCE_ROW_BOUND_EXCEEDED")

    def _select_in_chunks(
        self,
        table: str,
        projection: str,
        column: str,
        values: Sequence[str],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for start in range(0, len(values), 200):
            chunk = list(values[start : start + 200])
            if not chunk:
                continue
            try:
                response = (
                    self._client.table(table)  # type: ignore[attr-defined]
                    .select(projection)
                    .in_(column, chunk)
                    .execute()
                )
            except BaseException:
                raise PreflightError("DB_READ_FAILED") from None
            data = getattr(response, "data", None)
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise PreflightError("DB_READ_FAILED")
            rows.extend(data)
        return rows


if __name__ == "__main__":
    raise SystemExit(main())

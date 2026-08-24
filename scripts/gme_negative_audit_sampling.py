"""Strict, deterministic sampling for the private GME-negative audit manifest."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Literal
from uuid import UUID


SCHEMA_VERSION = "gme-negative-audit-v1"
ASSIGNMENT_RULE = "stratum_round_robin_v1"
DETECTOR_IDENTITY = "d4654168af21d26697ab1bd9a5dc4a05bd92baf5c9328800915cc347803d05b6"
CHECKPOINT_SHA256 = "2b128f105e898bc472ed66861583ab80007dae6e94b291db497d7a2f8081f84a"
_CANDIDATE_KEYS = frozenset(
    {
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
    }
)
_BATCH_COUNTS = {
    "calibration": (120, 30),
    "preview_canary": (4, 2),
}
_MANIFEST_SHA256_RULE = "sha256(utf8-canonical-json-v1-excluding-manifest_sha256)"
_CANONICAL_DECIMAL = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


class AuditContractError(ValueError):
    """Raised when an audit input violates its frozen contract."""


class AuditShortageError(AuditContractError):
    """Raised when eligible candidates cannot fill the exact required batch."""

    def __init__(self, message: str, *, eligible_count: int | None = None) -> None:
        super().__init__(message)
        self.eligible_count = eligible_count


@dataclass(frozen=True, slots=True)
class AuditCandidate:
    clip_id: str
    stratum: Literal["random_negative", "positive_control"]
    started_at: datetime
    duration_sec: float
    camera_night_key: str
    episode_key: str
    gme_run_id: str
    detector_identity: str
    media_sha256: str
    media_dhash: str
    gme_detected: bool
    human_gt_digest: str | None


@dataclass(frozen=True, slots=True)
class AuditManifestItem:
    ordinal: int
    candidate: AuditCandidate
    selection_provenance: str


@dataclass(frozen=True, slots=True)
class AuditSelectionResult(Sequence[AuditManifestItem]):
    """The canonical source pools and their one exact deterministic selection."""

    batch_kind: Literal["calibration", "preview_canary"]
    seed: str
    negative_pool: tuple[AuditCandidate, ...]
    control_pool: tuple[AuditCandidate, ...]
    negative_pool_sha256: str
    control_pool_sha256: str
    items: tuple[AuditManifestItem, ...]
    selection_sha256: str

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int | slice) -> AuditManifestItem | tuple[AuditManifestItem, ...]:
        return self.items[index]

def parse_candidate(raw: Mapping[str, object]) -> AuditCandidate:
    """Validate one read-only candidate mapping without normalizing its identity."""
    if not isinstance(raw, Mapping) or set(raw) != _CANDIDATE_KEYS:
        raise AuditContractError("candidate must have the exact required key set")

    clip_id = _require_canonical_uuid(raw["clip_id"], "clip_id")
    stratum = raw["stratum"]
    if stratum not in {"random_negative", "positive_control"}:
        raise AuditContractError("invalid stratum")
    started_at = _require_canonical_rfc3339(raw["started_at"], "started_at")
    duration_sec = raw["duration_sec"]
    if isinstance(duration_sec, bool) or not isinstance(duration_sec, (int, float)):
        raise AuditContractError("duration_sec must be finite and positive")
    try:
        normalized_duration_sec = float(duration_sec)
    except (OverflowError, ValueError) as error:
        raise AuditContractError("duration_sec must be finite and positive") from error
    if not math.isfinite(normalized_duration_sec) or normalized_duration_sec <= 0:
        raise AuditContractError("duration_sec must be finite and positive")
    camera_night_key = _require_nonempty_string(raw["camera_night_key"], "camera_night_key")
    episode_key = _require_nonempty_string(raw["episode_key"], "episode_key")
    gme_run_id = _require_canonical_uuid(raw["gme_run_id"], "gme_run_id")
    detector_identity = raw["detector_identity"]
    if detector_identity != DETECTOR_IDENTITY:
        raise AuditContractError("detector_identity does not match the pinned detector")
    media_sha256 = _require_sha256(raw["media_sha256"], "media_sha256")
    media_dhash = _require_lower_hex(raw["media_dhash"], 16, "media_dhash")
    gme_detected = raw["gme_detected"]
    if type(gme_detected) is not bool:
        raise AuditContractError("gme_detected must be a bool")
    human_gt_digest = raw["human_gt_digest"]

    if stratum == "random_negative":
        if gme_detected is not False or human_gt_digest is not None:
            raise AuditContractError(
                "random_negative requires gme_detected=false and no human_gt_digest"
            )
    else:
        try:
            human_gt_digest = _require_sha256(human_gt_digest, "human_gt_digest")
        except AuditContractError as error:
            raise AuditContractError(
                "positive_control requires a human_gt_digest SHA-256"
            ) from error

    return AuditCandidate(
        clip_id=clip_id,
        stratum=stratum,
        started_at=started_at,
        duration_sec=normalized_duration_sec,
        camera_night_key=camera_night_key,
        episode_key=episode_key,
        gme_run_id=gme_run_id,
        detector_identity=DETECTOR_IDENTITY,
        media_sha256=media_sha256,
        media_dhash=media_dhash,
        gme_detected=gme_detected,
        human_gt_digest=human_gt_digest,
    )


def select_calibration_batch(
    negative_rows: Sequence[Mapping[str, object]],
    control_rows: Sequence[Mapping[str, object]],
    *,
    protected_sha256: set[str],
    protected_dhash64: set[str],
    seed: str,
    batch_kind: Literal["calibration", "preview_canary"] = "calibration",
    negative_count: int = 120,
    control_count: int = 30,
) -> AuditSelectionResult:
    """Select the one allowed exact batch shape without replacement or fallback."""
    _validate_batch_shape(batch_kind, negative_count, control_count)
    if not isinstance(seed, str) or not seed:
        raise AuditContractError("seed must be a non-empty string")

    negatives = tuple(parse_candidate(row) for row in negative_rows)
    controls = tuple(parse_candidate(row) for row in control_rows)
    if any(candidate.stratum != "random_negative" for candidate in negatives):
        raise AuditContractError("negative_rows must contain only random_negative candidates")
    if any(candidate.stratum != "positive_control" for candidate in controls):
        raise AuditContractError("control_rows must contain only positive_control candidates")

    _reject_overlap_and_duplicates(
        negatives,
        protected_sha256=protected_sha256,
        protected_dhash64=protected_dhash64,
    )
    _reject_overlap_and_duplicates(
        controls,
        protected_sha256=protected_sha256,
        protected_dhash64=protected_dhash64,
    )
    negative_pool = tuple(sorted(negatives, key=_canonical_candidate_key))
    control_source_pool = tuple(sorted(controls, key=_canonical_candidate_key))
    items = _select_manifest_items(
        negative_pool,
        control_source_pool,
        seed=seed,
        negative_count=negative_count,
        control_count=control_count,
    )
    selected_negatives = tuple(
        item.candidate
        for item in items
        if item.candidate.stratum == "random_negative"
    )
    control_pool = _eligible_controls_after_negative_selection(
        control_source_pool,
        selected_negatives,
    )
    negative_pool_sha256 = _pool_sha256("random_negative", negative_pool)
    control_pool_sha256 = _pool_sha256("positive_control", control_pool)
    return AuditSelectionResult(
        batch_kind=batch_kind,
        seed=seed,
        negative_pool=negative_pool,
        control_pool=control_pool,
        negative_pool_sha256=negative_pool_sha256,
        control_pool_sha256=control_pool_sha256,
        items=items,
        selection_sha256=_selection_result_sha256(
            batch_kind=batch_kind,
            seed=seed,
            negative_pool_sha256=negative_pool_sha256,
            control_pool_sha256=control_pool_sha256,
            items=items,
        ),
    )


def build_private_manifest(
    selection: AuditSelectionResult,
    *,
    test_sheet_sha256: str,
    cutoff: str,
    checkpoint_sha256: str,
    protected_manifest_sha256: Sequence[str],
    reviewer_ids: Sequence[str],
) -> dict[str, object]:
    """Build the complete canonical payload before it is written privately once."""
    _validate_selection_result(selection)
    test_sheet_sha256 = _require_sha256(test_sheet_sha256, "test_sheet_sha256")
    _require_canonical_rfc3339(cutoff, "cutoff")
    if checkpoint_sha256 != CHECKPOINT_SHA256:
        raise AuditContractError("checkpoint_sha256 does not match the pinned checkpoint")
    canonical_items = _validate_manifest_items(
        selection.items,
        seed=selection.seed,
        expected_negative_count=_batch_counts(selection.batch_kind)[0],
        expected_control_count=_batch_counts(selection.batch_kind)[1],
    )
    protected_manifest_digests = sorted(
        {_require_sha256(value, "protected_manifest_sha256") for value in protected_manifest_sha256}
    )
    if len(protected_manifest_digests) != len(protected_manifest_sha256):
        raise AuditContractError("protected_manifest_sha256 contains duplicates")
    if isinstance(reviewer_ids, (str, bytes)):
        raise AuditContractError("reviewer_ids must be an ordered UUID list")
    canonical_reviewer_ids = [
        _require_canonical_uuid(value, "reviewer_ids") for value in reviewer_ids
    ]
    expected_reviewer_count = 1 if selection.batch_kind == "calibration" else 2
    if len(canonical_reviewer_ids) != expected_reviewer_count:
        raise AuditContractError("batch kind requires its exact reviewer count")
    if len(set(canonical_reviewer_ids)) != len(canonical_reviewer_ids):
        raise AuditContractError("reviewer_ids contains duplicates")

    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "status": "prepared",
        "batch_kind": selection.batch_kind,
        "test_sheet_sha256": test_sheet_sha256,
        "seed": selection.seed,
        "cutoff": cutoff,
        "detector_identity": DETECTOR_IDENTITY,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "candidate_counts": {
            "random_negative": len(selection.negative_pool),
            "positive_control": len(selection.control_pool),
        },
        "source_pools": {
            "random_negative": {
                "count": len(selection.negative_pool),
                "sha256": selection.negative_pool_sha256,
            },
            "positive_control": {
                "count": len(selection.control_pool),
                "sha256": selection.control_pool_sha256,
            },
        },
        "selection_sha256": selection.selection_sha256,
        "protected_manifest_sha256": protected_manifest_digests,
        "reviewer_ids": canonical_reviewer_ids,
        "assignment_rule": ASSIGNMENT_RULE,
        "manifest_sha256_rule": _MANIFEST_SHA256_RULE,
        "items": canonical_items,
    }
    manifest["manifest_sha256"] = _sha256_canonical(manifest)
    return manifest


def write_private_json_new(path: Path | str, payload: Mapping[str, object]) -> None:
    """Atomically create a private JSON file, refusing to replace any existing path."""
    encoded = _canonical_json(payload) + b"\n"
    fd = os.open(os.fspath(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(encoded)
    finally:
        if fd != -1:
            os.close(fd)


def _validate_batch_shape(
    batch_kind: str, negative_count: int, control_count: int
) -> None:
    expected_negative_count, expected_control_count = _batch_counts(batch_kind)
    if (negative_count, control_count) != (expected_negative_count, expected_control_count):
        raise AuditContractError("batch kind requires its exact negative/control counts")


def _batch_counts(batch_kind: str) -> tuple[int, int]:
    if batch_kind not in _BATCH_COUNTS:
        raise AuditContractError("invalid batch_kind")
    return _BATCH_COUNTS[batch_kind]


def _reject_overlap_and_duplicates(
    candidates: Sequence[AuditCandidate],
    *,
    protected_sha256: set[str],
    protected_dhash64: set[str],
) -> None:
    protected_sha256 = {
        _require_sha256(value, "protected_sha256") for value in protected_sha256
    }
    protected_dhash64 = {
        _require_lower_hex(value, 16, "protected_dhash64")
        for value in protected_dhash64
    }
    media_sha256: set[str] = set()
    clip_ids: set[str] = set()
    for candidate in candidates:
        if candidate.clip_id in clip_ids:
            raise AuditContractError("duplicate clip_id")
        clip_ids.add(candidate.clip_id)
        if candidate.media_sha256 in media_sha256:
            raise AuditContractError("duplicate media sha256")
        media_sha256.add(candidate.media_sha256)
        if candidate.media_sha256 in protected_sha256:
            raise AuditContractError("protected overlap")
        candidate_dhash = int(candidate.media_dhash, 16)
        if any(
            (candidate_dhash ^ int(protected_dhash, 16)).bit_count() <= 2
            for protected_dhash in protected_dhash64
        ):
            raise AuditContractError("near-duplicate overlap")


def _select_manifest_items(
    negative_pool: Sequence[AuditCandidate],
    control_pool: Sequence[AuditCandidate],
    *,
    seed: str,
    negative_count: int,
    control_count: int,
) -> tuple[AuditManifestItem, ...]:
    selected_negatives = _select_stratified_negatives(
        negative_pool, seed=seed, count=negative_count
    )
    eligible_controls = _eligible_controls_after_negative_selection(
        control_pool,
        selected_negatives,
    )
    selected_controls = _select_ranked_controls(
        eligible_controls, seed=seed, count=control_count
    )
    blinded = sorted(
        (*selected_negatives, *selected_controls),
        key=lambda candidate: _blind_order_rank(seed, candidate),
    )
    return tuple(
        AuditManifestItem(
            ordinal=ordinal,
            candidate=candidate,
            selection_provenance=_selection_provenance(seed, ordinal, candidate),
        )
        for ordinal, candidate in enumerate(blinded, start=1)
    )


def _validate_selection_result(selection: object) -> None:
    if not isinstance(selection, AuditSelectionResult):
        raise AuditContractError("manifest requires an AuditSelectionResult")
    expected_negative_count, expected_control_count = _batch_counts(selection.batch_kind)
    if not isinstance(selection.seed, str) or not selection.seed:
        raise AuditContractError("selection result seed must be a non-empty string")
    negative_pool = _validate_canonical_pool(
        selection.negative_pool, stratum="random_negative"
    )
    control_pool = _validate_canonical_pool(
        selection.control_pool, stratum="positive_control"
    )
    _reject_overlap_and_duplicates(
        negative_pool,
        protected_sha256=set(),
        protected_dhash64=set(),
    )
    _reject_overlap_and_duplicates(
        control_pool,
        protected_sha256=set(),
        protected_dhash64=set(),
    )
    if (
        selection.negative_pool != negative_pool
        or selection.control_pool != control_pool
        or not isinstance(selection.items, tuple)
    ):
        raise AuditContractError("selection result source pools must be canonical tuples")
    negative_pool_sha256 = _pool_sha256("random_negative", negative_pool)
    control_pool_sha256 = _pool_sha256("positive_control", control_pool)
    if (
        selection.negative_pool_sha256 != negative_pool_sha256
        or selection.control_pool_sha256 != control_pool_sha256
    ):
        raise AuditContractError("selection result source pool digest mismatch")
    _validate_manifest_items(
        selection.items,
        seed=selection.seed,
        expected_negative_count=expected_negative_count,
        expected_control_count=expected_control_count,
    )
    expected_items = _select_manifest_items(
        negative_pool,
        control_pool,
        seed=selection.seed,
        negative_count=expected_negative_count,
        control_count=expected_control_count,
    )
    if selection.items != expected_items:
        raise AuditContractError("selection result does not match bound source pools")
    if selection.selection_sha256 != _selection_result_sha256(
        batch_kind=selection.batch_kind,
        seed=selection.seed,
        negative_pool_sha256=negative_pool_sha256,
        control_pool_sha256=control_pool_sha256,
        items=selection.items,
    ):
        raise AuditContractError("selection result digest mismatch")


def _validate_canonical_pool(
    pool: object, *, stratum: Literal["random_negative", "positive_control"]
) -> tuple[AuditCandidate, ...]:
    if not isinstance(pool, tuple):
        raise AuditContractError("selection result source pool must be a tuple")
    normalized: list[AuditCandidate] = []
    for candidate in pool:
        if not isinstance(candidate, AuditCandidate):
            raise AuditContractError("selection result source pool candidate is invalid")
        validated = parse_candidate(_candidate_validation_mapping(candidate))
        if validated.stratum != stratum:
            raise AuditContractError("selection result source pool has the wrong stratum")
        normalized.append(validated)
    return tuple(sorted(normalized, key=_canonical_candidate_key))


def _pool_sha256(stratum: str, pool: Sequence[AuditCandidate]) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "stratum": stratum,
                "candidates": [_candidate_mapping(candidate) for candidate in pool],
            }
        )
    ).hexdigest()


def _selection_result_sha256(
    *,
    batch_kind: str,
    seed: str,
    negative_pool_sha256: str,
    control_pool_sha256: str,
    items: Sequence[AuditManifestItem],
) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "batch_kind": batch_kind,
                "seed": seed,
                "negative_pool_sha256": negative_pool_sha256,
                "control_pool_sha256": control_pool_sha256,
                "items": [
                    {
                        "ordinal": item.ordinal,
                        "candidate": _candidate_mapping(item.candidate),
                        "selection_provenance": item.selection_provenance,
                    }
                    for item in items
                ],
            }
        )
    ).hexdigest()


def _select_stratified_negatives(
    candidates: Sequence[AuditCandidate], *, seed: str, count: int
) -> tuple[AuditCandidate, ...]:
    ordered = sorted(candidates, key=_canonical_candidate_key)
    by_night: dict[str, list[AuditCandidate]] = {}
    for candidate in ordered:
        by_night.setdefault(candidate.camera_night_key, []).append(candidate)
    for night_candidates in by_night.values():
        night_candidates.sort(
            key=lambda candidate: _selection_rank(seed, candidate)
        )

    selected: list[AuditCandidate] = []
    episode_counts: dict[str, int] = {}
    next_index = {night: 0 for night in by_night}
    nights = sorted(by_night)
    while len(selected) < count:
        selected_this_round = False
        for night in nights:
            night_candidates = by_night[night]
            index = next_index[night]
            while index < len(night_candidates):
                candidate = night_candidates[index]
                index += 1
                if episode_counts.get(candidate.episode_key, 0) >= 2:
                    continue
                next_index[night] = index
                episode_counts[candidate.episode_key] = (
                    episode_counts.get(candidate.episode_key, 0) + 1
                )
                selected.append(candidate)
                selected_this_round = True
                break
            else:
                next_index[night] = index
            if len(selected) == count:
                break
        if not selected_this_round:
            raise AuditShortageError("random_negative candidate shortage after episode cap")
    return tuple(selected)


def _eligible_controls_after_negative_selection(
    controls: Sequence[AuditCandidate],
    selected_negatives: Sequence[AuditCandidate],
) -> tuple[AuditCandidate, ...]:
    selected_clip_ids = {candidate.clip_id for candidate in selected_negatives}
    selected_media_sha256 = {
        candidate.media_sha256 for candidate in selected_negatives
    }
    selected_media_dhash = [
        int(candidate.media_dhash, 16) for candidate in selected_negatives
    ]
    return tuple(
        candidate
        for candidate in controls
        if candidate.clip_id not in selected_clip_ids
        and candidate.media_sha256 not in selected_media_sha256
        and all(
            (int(candidate.media_dhash, 16) ^ negative_dhash).bit_count() > 2
            for negative_dhash in selected_media_dhash
        )
    )


def _select_ranked_controls(
    candidates: Sequence[AuditCandidate], *, seed: str, count: int
) -> tuple[AuditCandidate, ...]:
    ordered = sorted(candidates, key=_canonical_candidate_key)
    ranked = sorted(
        ordered,
        key=lambda candidate: _selection_rank(seed, candidate),
    )
    if len(ranked) < count:
        raise AuditShortageError(
            "positive_control candidate shortage",
            eligible_count=len(ranked),
        )
    return tuple(ranked[:count])


def _validate_manifest_items(
    items: Sequence[AuditManifestItem],
    *,
    seed: str,
    expected_negative_count: int,
    expected_control_count: int,
) -> list[dict[str, object]]:
    expected_total = expected_negative_count + expected_control_count
    if len(items) != expected_total:
        raise AuditContractError("manifest item count does not match the batch contract")
    canonical_items: list[dict[str, object]] = []
    clip_ids: set[str] = set()
    media_sha256: set[str] = set()
    counts = {"random_negative": 0, "positive_control": 0}
    candidates: list[AuditCandidate] = []
    provenance_items: list[tuple[AuditManifestItem, AuditCandidate]] = []
    for expected_ordinal, item in enumerate(items, start=1):
        if not isinstance(item, AuditManifestItem) or item.ordinal != expected_ordinal:
            raise AuditContractError("manifest ordinals must be contiguous from one")
        if not isinstance(item.candidate, AuditCandidate):
            raise AuditContractError("manifest item candidate must be an AuditCandidate")
        candidate = parse_candidate(_candidate_validation_mapping(item.candidate))
        if candidate.clip_id in clip_ids or candidate.media_sha256 in media_sha256:
            raise AuditContractError("manifest items must have unique clip and media identities")
        clip_ids.add(candidate.clip_id)
        media_sha256.add(candidate.media_sha256)
        counts[candidate.stratum] += 1
        candidates.append(candidate)
        provenance_items.append((item, candidate))
        canonical_items.append(
            {
                "ordinal": item.ordinal,
                "clip_id": candidate.clip_id,
                "stratum": candidate.stratum,
                "started_at": _format_rfc3339(candidate.started_at),
                "duration_sec": _canonical_duration(candidate.duration_sec),
                "camera_night_key": candidate.camera_night_key,
                "episode_key": candidate.episode_key,
                "gme_run_id": candidate.gme_run_id,
                "detector_identity": candidate.detector_identity,
                "media_sha256": candidate.media_sha256,
                "media_dhash": candidate.media_dhash,
                "gme_detected": candidate.gme_detected,
                "human_gt_digest": candidate.human_gt_digest,
                "selection_provenance": item.selection_provenance,
            }
        )
    if counts != {
        "random_negative": expected_negative_count,
        "positive_control": expected_control_count,
    }:
        raise AuditContractError("manifest stratum counts do not match the batch contract")
    _validate_frozen_selection(candidates, seed=seed)
    for item, candidate in provenance_items:
        if item.selection_provenance != _selection_provenance(
            seed, item.ordinal, candidate
        ):
            raise AuditContractError("manifest item selection provenance mismatch")
    return canonical_items


def _canonical_candidate_key(candidate: AuditCandidate) -> tuple[str, str, datetime, str]:
    return (
        candidate.camera_night_key,
        candidate.episode_key,
        candidate.started_at,
        candidate.clip_id,
    )


def _candidate_mapping(candidate: AuditCandidate) -> dict[str, object]:
    return {
        "clip_id": candidate.clip_id,
        "stratum": candidate.stratum,
        "started_at": _format_rfc3339(candidate.started_at),
        "duration_sec": _canonical_duration(candidate.duration_sec),
        "camera_night_key": candidate.camera_night_key,
        "episode_key": candidate.episode_key,
        "gme_run_id": candidate.gme_run_id,
        "detector_identity": candidate.detector_identity,
        "media_sha256": candidate.media_sha256,
        "media_dhash": candidate.media_dhash,
        "gme_detected": candidate.gme_detected,
        "human_gt_digest": candidate.human_gt_digest,
    }


def _candidate_validation_mapping(candidate: AuditCandidate) -> dict[str, object]:
    mapping = _candidate_mapping(candidate)
    mapping["duration_sec"] = candidate.duration_sec
    return mapping


def _selection_provenance(
    seed: str, ordinal: int, candidate: AuditCandidate
) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "seed": seed,
                "ordinal": ordinal,
                "candidate": _candidate_mapping(candidate),
            }
        )
    ).hexdigest()


def _selection_rank(seed: str, candidate: AuditCandidate) -> str:
    """Use the Task 1 brief's frozen per-stratum sampling rank exactly."""
    return hashlib.sha256(
        f"{seed}:{candidate.stratum}:{candidate.clip_id}".encode("utf-8")
    ).hexdigest()


def _blind_order_rank(seed: str, candidate: AuditCandidate) -> str:
    """Keep UI-blind mixing in one explicit domain, separate from sampling rank."""
    return hashlib.sha256(
        f"{seed}:blind-order:{candidate.stratum}:{candidate.clip_id}".encode("utf-8")
    ).hexdigest()


def _validate_frozen_selection(
    candidates: Sequence[AuditCandidate], *, seed: str
) -> None:
    negative_episode_counts: dict[str, int] = {}
    for candidate in candidates:
        if candidate.stratum != "random_negative":
            continue
        negative_episode_counts[candidate.episode_key] = (
            negative_episode_counts.get(candidate.episode_key, 0) + 1
        )
    if any(count > 2 for count in negative_episode_counts.values()):
        raise AuditContractError("manifest violates random_negative episode cap")
    if list(candidates) != sorted(
        candidates,
        key=lambda candidate: _blind_order_rank(seed, candidate),
    ):
        raise AuditContractError("manifest items do not match the frozen blind order")


def _require_canonical_uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise AuditContractError(f"{field} must be a canonical UUID")
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError) as error:
        raise AuditContractError(f"{field} must be a canonical UUID") from error
    if str(parsed) != value:
        raise AuditContractError(f"{field} must be a canonical UUID")
    return value


def _require_canonical_rfc3339(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AuditContractError(f"{field} must be canonical RFC3339 UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise AuditContractError(f"{field} must be canonical RFC3339 UTC") from error
    if parsed.tzinfo is None or _format_rfc3339(parsed) != value:
        raise AuditContractError(f"{field} must be canonical RFC3339 UTC")
    return parsed.astimezone(timezone.utc)


def _format_rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuditContractError(f"{field} must be a non-empty string")
    return value


def _canonical_duration(value: float) -> str:
    """Freeze duration as exponent-free decimal text shared with PostgreSQL jsonb."""
    try:
        rendered = format(Decimal(str(value)), "f")
    except (InvalidOperation, ValueError) as error:
        raise AuditContractError("duration_sec must be finite and positive") from error
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if _CANONICAL_DECIMAL.fullmatch(rendered) is None or Decimal(rendered) <= 0:
        raise AuditContractError("duration_sec must be finite and positive")
    return rendered


def _require_sha256(value: object, field: str) -> str:
    return _require_lower_hex(value, 64, field)


def _require_lower_hex(value: object, length: int, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AuditContractError(f"{field} must be {length} lowercase hexadecimal characters")
    return value


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256_canonical(payload: Mapping[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("manifest_sha256", None)
    return hashlib.sha256(_canonical_json(unsigned)).hexdigest()

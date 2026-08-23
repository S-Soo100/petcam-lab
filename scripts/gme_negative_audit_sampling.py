"""Strict, deterministic sampling for the private GME-negative audit manifest."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Literal
from uuid import UUID


SCHEMA_VERSION = "gme-negative-audit-v1"
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
_MANIFEST_SHA256_RULE = "sha256(canonical-json-excluding-manifest_sha256)"


class AuditContractError(ValueError):
    """Raised when an audit input violates its frozen contract."""


class AuditShortageError(AuditContractError):
    """Raised when eligible candidates cannot fill the exact required batch."""


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
) -> tuple[AuditManifestItem, ...]:
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
        (*negatives, *controls),
        protected_sha256=protected_sha256,
        protected_dhash64=protected_dhash64,
    )
    selected_negatives = _select_stratified_negatives(
        negatives, seed=seed, count=negative_count
    )
    selected_controls = _select_ranked_controls(controls, seed=seed, count=control_count)
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


def build_private_manifest(
    items: Sequence[AuditManifestItem],
    *,
    batch_kind: Literal["calibration", "preview_canary"],
    seed: str,
    test_sheet_sha256: str,
    cutoff: str,
    checkpoint_sha256: str,
    candidate_counts: Mapping[str, int],
    protected_manifest_sha256: Sequence[str],
) -> dict[str, object]:
    """Build the complete canonical payload before it is written privately once."""
    expected_negative_count, expected_control_count = _batch_counts(batch_kind)
    if not isinstance(seed, str) or not seed:
        raise AuditContractError("seed must be a non-empty string")
    test_sheet_sha256 = _require_sha256(test_sheet_sha256, "test_sheet_sha256")
    _require_canonical_rfc3339(cutoff, "cutoff")
    if checkpoint_sha256 != CHECKPOINT_SHA256:
        raise AuditContractError("checkpoint_sha256 does not match the pinned checkpoint")
    if set(candidate_counts) != {"random_negative", "positive_control"}:
        raise AuditContractError("candidate_counts must have the exact stratum key set")
    normalized_candidate_counts: dict[str, int] = {}
    for stratum, count in candidate_counts.items():
        if type(count) is not int or count < 0:
            raise AuditContractError("candidate_counts must be non-negative integers")
        normalized_candidate_counts[stratum] = count

    canonical_items = _validate_manifest_items(
        items,
        seed=seed,
        expected_negative_count=expected_negative_count,
        expected_control_count=expected_control_count,
    )
    if normalized_candidate_counts["random_negative"] < expected_negative_count or (
        normalized_candidate_counts["positive_control"] < expected_control_count
    ):
        raise AuditContractError("candidate_counts cannot be smaller than selected counts")
    protected_manifest_digests = sorted(
        {_require_sha256(value, "protected_manifest_sha256") for value in protected_manifest_sha256}
    )
    if len(protected_manifest_digests) != len(protected_manifest_sha256):
        raise AuditContractError("protected_manifest_sha256 contains duplicates")

    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "status": "prepared",
        "batch_kind": batch_kind,
        "test_sheet_sha256": test_sheet_sha256,
        "seed": seed,
        "cutoff": cutoff,
        "detector_identity": DETECTOR_IDENTITY,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "candidate_counts": normalized_candidate_counts,
        "protected_manifest_sha256": protected_manifest_digests,
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


def _select_ranked_controls(
    candidates: Sequence[AuditCandidate], *, seed: str, count: int
) -> tuple[AuditCandidate, ...]:
    ordered = sorted(candidates, key=_canonical_candidate_key)
    ranked = sorted(
        ordered,
        key=lambda candidate: _selection_rank(seed, candidate),
    )
    if len(ranked) < count:
        raise AuditShortageError("positive_control candidate shortage")
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
        candidate = parse_candidate(_candidate_mapping(item.candidate))
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
                "duration_sec": candidate.duration_sec,
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
        "duration_sec": candidate.duration_sec,
        "camera_night_key": candidate.camera_night_key,
        "episode_key": candidate.episode_key,
        "gme_run_id": candidate.gme_run_id,
        "detector_identity": candidate.detector_identity,
        "media_sha256": candidate.media_sha256,
        "media_dhash": candidate.media_dhash,
        "gme_detected": candidate.gme_detected,
        "human_gt_digest": candidate.human_gt_digest,
    }


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
    ).encode("utf-8")


def _sha256_canonical(payload: Mapping[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("manifest_sha256", None)
    return hashlib.sha256(_canonical_json(unsigned)).hexdigest()

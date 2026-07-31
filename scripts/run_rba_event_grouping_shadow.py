"""SELECT-only runner for the Phase 1 event grouping shadow."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import socket
import sys
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path[:0] = [str(_REPO_ROOT)]

from scripts.prepare_rba_event_grouping_shadow import (
    SOURCE_CUTOFF,
    build_adjacent_pairs,
    build_blank_worksheet,
    build_private_manifest,
    build_public_summary,
    select_boundary_pairs,
    split_camera_nights,
    write_private_new,
)
from scripts.rba_event_grouping_core import (
    ExclusionState,
    SourceClip,
    account_source_clips,
    activity_day_kst,
    group_activity_events,
    verify_accounting,
)
from scripts.score_rba_event_grouping_shadow import (
    HoldoutMetrics,
    THRESHOLD_CANDIDATES,
    choose_development_threshold,
    finalize_boundary_gt,
    freeze_development_threshold,
    score_frozen_holdout,
    validate_reviewer_rows,
)

EXPECTED_HOST = "baeg-endeuui-Macmini.local"
ALLOWED_TABLES = {
    "motion_clips",
    "motion_clip_system_exclusions",
    "motion_clip_review_slots",
}
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
BLOCKED_FIELDS = frozenset(
    {"clip_id", "clip_ids", "clips", "selected", "durable_key"}
)


class SafetyContractError(RuntimeError):
    """The one-shot read or private artifact contract was violated."""


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def paginated_select(
    query: Any,
    *,
    page_size: int,
    identity_field: str,
    deduplicate_globally: bool = False,
) -> tuple[dict[str, object], ...]:
    if page_size <= 0:
        raise SafetyContractError("invalid_page_size")
    rows: list[dict[str, object]] = []
    identities: set[object] = set()
    start = 0
    while True:
        response = query.range(start, start + page_size - 1).execute()
        page = response.data
        if not isinstance(page, list):
            raise SafetyContractError("invalid_select_response")
        page_identities: set[object] = set()
        for row in page:
            if not isinstance(row, dict):
                raise SafetyContractError("invalid_select_row")
            identity = row.get(identity_field)
            if identity is None:
                raise SafetyContractError("duplicate_or_missing_snapshot_identity")
            if identity in page_identities or identity in identities:
                if deduplicate_globally:
                    continue
                raise SafetyContractError("duplicate_or_missing_snapshot_identity")
            page_identities.add(identity)
            identities.add(identity)
            rows.append(dict(row))
        if len(page) < page_size:
            break
        start += page_size
    return tuple(rows)


def load_select_snapshots(
    client: Any,
    *,
    page_size: int = 1000,
) -> dict[str, tuple[dict[str, object], ...]]:
    clips_query = (
        client.table("motion_clips")
        .select("id,camera_id,started_at,duration_sec")
        .lt("started_at", SOURCE_CUTOFF)
        .order("id")
    )
    exclusions_query = client.table(
        "motion_clip_system_exclusions"
    ).select("clip_id,state,reason_code,rule_version").order("clip_id")
    slots_query = (
        client.table("motion_clip_review_slots")
        .select("clip_id,cohort_kind")
        .order("id")
    )
    return {
        "motion_clips": paginated_select(
            clips_query, page_size=page_size, identity_field="id"
        ),
        "motion_clip_system_exclusions": paginated_select(
            exclusions_query,
            page_size=page_size,
            identity_field="clip_id",
        ),
        "motion_clip_review_slots": paginated_select(
            slots_query,
            page_size=page_size,
            identity_field="clip_id",
            deduplicate_globally=True,
        ),
    }


def _within_roots(path: Path, roots: Sequence[Path]) -> bool:
    resolved = path.resolve(strict=True)
    for root in roots:
        try:
            resolved.relative_to(root.resolve(strict=True))
            return True
        except ValueError:
            continue
    return False


def _collect_uuid_values(value: object, enabled: bool = False) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        if enabled and UUID_PATTERN.fullmatch(value):
            found.add(value.lower())
    elif isinstance(value, list):
        for item in value:
            found |= _collect_uuid_values(item, enabled)
    elif isinstance(value, dict):
        for key, item in value.items():
            found |= _collect_uuid_values(
                item, enabled or key in BLOCKED_FIELDS
            )
    return found


def _load_manifest_payload(path: Path) -> object:
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            with path.open(newline="", encoding="utf-8") as handle:
                return list(csv.DictReader(handle))
        text = path.read_text(encoding="utf-8")
        if suffix == ".jsonl":
            return [
                json.loads(line)
                for line in text.splitlines()
                if line.strip()
            ]
        return json.loads(text)
    except (OSError, csv.Error, json.JSONDecodeError) as exc:
        raise SafetyContractError(f"blocked_manifest_parse:{path.name}") from exc


def load_blocked_manifests(
    paths: Sequence[Path],
    *,
    allowed_roots: Sequence[Path],
) -> tuple[frozenset[str], str]:
    if not paths:
        raise SafetyContractError("blocked_manifest_required")
    blocked: set[str] = set()
    for path in paths:
        try:
            allowed = _within_roots(path, allowed_roots)
        except OSError as exc:
            raise SafetyContractError(
                f"blocked_manifest_missing:{path.name}"
            ) from exc
        if not allowed:
            raise SafetyContractError("blocked_manifest_outside_allowed_root")
        blocked |= _collect_uuid_values(_load_manifest_payload(path))
    if not blocked:
        raise SafetyContractError("empty_blocked_manifest_set")
    ordered = sorted(blocked)
    digest = hashlib.sha256(_canonical_bytes(ordered)).hexdigest()
    return frozenset(ordered), digest


def parse_as_of(value: str) -> datetime:
    if value == "now":
        parsed = datetime.now(UTC)
    else:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SafetyContractError("invalid_as_of") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SafetyContractError("as_of_must_be_aware")
    cutoff = datetime.fromisoformat(SOURCE_CUTOFF)
    if parsed < cutoff:
        raise SafetyContractError("as_of_before_source_cutoff")
    return parsed.astimezone(UTC)


def _source_rows(
    rows: Iterable[dict[str, object]],
) -> tuple[SourceClip, ...]:
    result: list[SourceClip] = []
    for row in rows:
        try:
            result.append(
                SourceClip(
                    clip_id=str(row["id"]),
                    camera_id=str(row["camera_id"]),
                    started_at=datetime.fromisoformat(
                        str(row["started_at"]).replace("Z", "+00:00")
                    ),
                    duration_sec=(
                        None
                        if row.get("duration_sec") is None
                        else float(row["duration_sec"])
                    ),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SafetyContractError("invalid_motion_clip_snapshot") from exc
    return tuple(result)


def _exclusion_rows(
    rows: Iterable[dict[str, object]],
    source_ids: set[str] | None = None,
) -> dict[str, ExclusionState]:
    result: dict[str, ExclusionState] = {}
    for row in rows:
        try:
            clip_id = str(row["clip_id"])
            if source_ids is not None and clip_id not in source_ids:
                continue
            if clip_id in result:
                raise SafetyContractError("duplicate_exclusion_identity")
            result[clip_id] = ExclusionState(
                clip_id=clip_id,
                state=str(row["state"]),
                reason_code=str(row["reason_code"]),
                rule_version=str(row["rule_version"]),
            )
        except KeyError as exc:
            raise SafetyContractError("invalid_exclusion_snapshot") from exc
    return result


def _snapshot_hash(payload: object) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _manifest_hash_valid(payload: dict[str, object]) -> bool:
    expected = payload.get("manifest_sha256")
    unhashed = {
        key: value
        for key, value in payload.items()
        if key != "manifest_sha256"
    }
    actual = hashlib.sha256(_canonical_bytes(unhashed)).hexdigest()
    return expected == actual


def prepare_artifacts(
    *,
    client: Any,
    as_of: datetime,
    out_dir: Path,
    blocked_paths: Sequence[Path],
    allowed_roots: Sequence[Path],
) -> dict[str, object]:
    if socket.gethostname() != EXPECTED_HOST:
        raise SafetyContractError("unexpected_execution_host")
    snapshots = load_select_snapshots(client)
    blocked, blocked_digest = load_blocked_manifests(
        blocked_paths, allowed_roots=allowed_roots
    )
    canary_ids = {
        str(row["clip_id"])
        for row in snapshots["motion_clip_review_slots"]
    }
    protected = frozenset(set(blocked) | canary_ids)
    source = _source_rows(snapshots["motion_clips"])
    source_ids = {row.clip_id for row in source}
    accounted = account_source_clips(
        source,
        _exclusion_rows(
            snapshots["motion_clip_system_exclusions"], source_ids
        ),
        protected,
    )
    current_day = activity_day_kst(as_of)
    closed_accounted = tuple(
        row for row in accounted if row.activity_day_kst < current_day
    )
    closed_source_ids = {row.clip_id for row in closed_accounted}
    closed_source = tuple(
        row for row in source if row.clip_id in closed_source_ids
    )
    pairs = build_adjacent_pairs(closed_accounted)
    split = split_camera_nights(pairs, "rba-event-grouping-shadow-v1")
    selected = select_boundary_pairs(split, "rba-event-grouping-shadow-v1")
    selected_nights = set(split.development_nights) | set(
        split.holdout_nights
    )
    selected_accounted = tuple(
        row
        for row in closed_accounted
        if (row.camera_id, row.activity_day_kst) in selected_nights
    )
    selected_source_ids = {row.clip_id for row in selected_accounted}
    selected_source = tuple(
        row for row in closed_source if row.clip_id in selected_source_ids
    )
    source_digest = _snapshot_hash(
        [
            {
                "id": row.clip_id,
                "camera_id": row.camera_id,
                "started_at": row.started_at.isoformat(),
                "duration_sec": row.duration_sec,
            }
            for row in sorted(selected_source, key=lambda row: row.clip_id)
        ]
    )
    manifest = build_private_manifest(
        source_snapshot_sha256=source_digest,
        blocked_set_sha256=blocked_digest,
        split=split,
        selected_pairs=selected,
        accounting_rows=selected_accounted,
    )
    out_dir.mkdir(parents=True, exist_ok=False)
    os.chmod(out_dir, 0o700)
    files = {
        "source": out_dir / "source-manifest.json",
        "pairs": out_dir / "boundary-pairs.json",
        "reviewer_a_development": out_dir / "reviewer-a-development.json",
        "reviewer_b_development": out_dir / "reviewer-b-development.json",
        "owner_development": out_dir / "owner-development.json",
        "reviewer_a_holdout": out_dir / "reviewer-a-holdout.json",
        "reviewer_b_holdout": out_dir / "reviewer-b-holdout.json",
        "owner_holdout": out_dir / "owner-holdout.json",
    }
    source_manifest: dict[str, object] = {
        "schema_version": "rba-event-source-v1",
        "source_cutoff": SOURCE_CUTOFF,
        "as_of": as_of.isoformat(),
        "source_snapshot_sha256": source_digest,
        "blocked_set_sha256": blocked_digest,
        "source_clip_ids": sorted(selected_source_ids),
        "accounting": manifest["accounting"],
    }
    source_manifest["manifest_sha256"] = hashlib.sha256(
        _canonical_bytes(source_manifest)
    ).hexdigest()
    write_private_new(files["source"], source_manifest)
    pair_file_sha256 = write_private_new(files["pairs"], manifest)
    development_nights = set(split.development_nights)
    development_pairs = tuple(
        item
        for item in selected
        if (item.camera_id, item.activity_day_kst) in development_nights
    )
    holdout_pairs = tuple(
        item
        for item in selected
        if (item.camera_id, item.activity_day_kst) not in development_nights
    )
    for split_name, split_pairs in (
        ("development", development_pairs),
        ("holdout", holdout_pairs),
    ):
        worksheet = build_blank_worksheet(split_pairs)
        write_private_new(files[f"reviewer_a_{split_name}"], worksheet)
        write_private_new(files[f"reviewer_b_{split_name}"], worksheet)
        write_private_new(
            files[f"owner_{split_name}"],
            {
                "schema_version": "rba-event-owner-worksheet-v1",
                "rows": [],
            },
        )
    public = build_public_summary(
        selected, split, salt=manifest["manifest_sha256"]  # type: ignore[arg-type]
    )
    return {
        **public,
        "source_count": len(selected_source),
        "accounting_count": len(selected_accounted),
        "blocked_research_count": sum(
            row.kind == "blocked_research" for row in selected_accounted
        ),
        "manifest_sha256": manifest["manifest_sha256"],
        "pair_file_sha256": pair_file_sha256,
        "output_dir": str(out_dir),
        "write_methods_called": 0,
        "rpc_called": 0,
        "r2_calls": 0,
        "model_calls": 0,
    }


def _accounting_from_manifest(
    payload: dict[str, object],
) -> tuple[Any, ...]:
    from scripts.rba_event_grouping_core import AccountedClip

    rows = payload.get("accounting")
    if not isinstance(rows, list):
        raise SafetyContractError("manifest_accounting_missing")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise SafetyContractError("manifest_accounting_invalid")
        result.append(
            AccountedClip(
                clip_id=str(row["clip_id"]),
                camera_id=str(row["camera_id"]),
                started_at=datetime.fromisoformat(str(row["started_at"])),
                activity_day_kst=datetime.fromisoformat(
                    str(row["activity_day_kst"])
                ).date(),
                duration_sec=(
                    None
                    if row.get("duration_sec") is None
                    else float(row["duration_sec"])
                ),
                kind=str(row["kind"]),
                reason_code=(
                    None
                    if row.get("reason_code") is None
                    else str(row["reason_code"])
                ),
            )
        )
    return tuple(result)


def group_manifest(
    manifest_path: Path,
    *,
    threshold_sec: int,
    output_path: Path,
) -> dict[str, object]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not _manifest_hash_valid(payload):
        raise SafetyContractError("manifest_hash_mismatch")
    accounted = _accounting_from_manifest(payload)
    final_events, run_hashes, event_rows = _run_grouping_three_times(
        accounted, threshold_sec
    )
    output = {
        "schema_version": "rba-event-membership-v1",
        "manifest_sha256": payload["manifest_sha256"],
        "threshold_sec": threshold_sec,
        "run_sha256": list(run_hashes),
        "event_count": len(final_events),
        "events": event_rows,
    }
    write_private_new(output_path, output)
    return {
        "event_count": len(final_events),
        "run_sha256": output["run_sha256"],
        "output_path": str(output_path),
    }


def _run_grouping_three_times(
    accounted: tuple[Any, ...],
    threshold_sec: int,
) -> tuple[tuple[Any, ...], tuple[str, str, str], list[dict[str, object]]]:
    run_bytes: list[bytes] = []
    final_events: tuple[Any, ...] = ()
    for _ in range(3):
        events = group_activity_events(accounted, threshold_sec)
        source = tuple(
            SourceClip(
                row.clip_id,
                row.camera_id,
                row.started_at,
                row.duration_sec,
            )
            for row in accounted
        )
        verify_accounting(source, accounted, events)
        event_payload = [
            {
                "event_id": item.event_id,
                "camera_id": item.camera_id,
                "activity_day_kst": item.activity_day_kst.isoformat(),
                "clip_ids": list(item.clip_ids),
                "started_at": item.started_at.isoformat(),
                "ended_at": item.ended_at.isoformat(),
            }
            for item in events
        ]
        run_bytes.append(_canonical_bytes(event_payload))
        final_events = events
    if len(set(run_bytes)) != 1:
        raise SafetyContractError("three_run_determinism_failure")
    hashes = tuple(hashlib.sha256(item).hexdigest() for item in run_bytes)
    return final_events, hashes, json.loads(run_bytes[0])


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SafetyContractError(f"invalid_json_input:{path.name}") from exc
    if not isinstance(payload, dict):
        raise SafetyContractError(f"invalid_json_object:{path.name}")
    return payload


def _worksheet_rows(path: Path) -> list[dict[str, object]]:
    payload = _load_json_object(path)
    rows = payload.get("rows")
    if not isinstance(rows, list) or not all(
        isinstance(row, dict) for row in rows
    ):
        raise SafetyContractError(f"invalid_worksheet:{path.name}")
    return rows


def _pairs_from_manifest(
    payload: dict[str, object],
) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    from datetime import date

    from scripts.prepare_rba_event_grouping_shadow import BoundaryPair

    splits = payload.get("splits")
    if not isinstance(splits, dict):
        raise SafetyContractError("manifest_splits_missing")

    def convert(name: str) -> tuple[BoundaryPair, ...]:
        rows = splits.get(name)
        if not isinstance(rows, list):
            raise SafetyContractError(f"manifest_split_missing:{name}")
        result: list[BoundaryPair] = []
        for row in rows:
            if not isinstance(row, dict):
                raise SafetyContractError(f"manifest_split_invalid:{name}")
            result.append(
                BoundaryPair(
                    pair_id=str(row["pair_id"]),
                    left_clip_id=str(row["left_clip_id"]),
                    right_clip_id=str(row["right_clip_id"]),
                    camera_id=str(row["camera_id"]),
                    activity_day_kst=date.fromisoformat(
                        str(row["activity_day_kst"])
                    ),
                    gap_sec=float(row["gap_sec"]),
                    gap_bin=str(row["gap_bin"]),
                )
            )
        return tuple(result)

    return convert("development"), convert("holdout")


def score_development(
    *,
    manifest_path: Path,
    reviewer_a_path: Path,
    reviewer_b_path: Path,
    owner_path: Path,
    freeze_path: Path,
) -> dict[str, object]:
    manifest = _load_json_object(manifest_path)
    if not _manifest_hash_valid(manifest):
        raise SafetyContractError("manifest_hash_mismatch")
    development, _ = _pairs_from_manifest(manifest)
    expected = {item.pair_id for item in development}
    reviewer_a = validate_reviewer_rows(
        _worksheet_rows(reviewer_a_path), expected
    )
    reviewer_b = validate_reviewer_rows(
        _worksheet_rows(reviewer_b_path), expected
    )
    final = finalize_boundary_gt(
        expected,
        reviewer_a,
        reviewer_b,
        _worksheet_rows(owner_path),
    )
    threshold = choose_development_threshold(
        development, final.decisions
    )
    freeze_sha256 = freeze_development_threshold(
        freeze_path,
        threshold_sec=threshold,
        manifest_sha256=str(manifest["manifest_sha256"]),
        development_gt_sha256=hashlib.sha256(
            _canonical_bytes(final.decisions)
        ).hexdigest(),
    )
    return {
        "threshold_sec": threshold,
        "raw_agreement": final.raw_agreement,
        "unresolved_count": final.unresolved_count,
        "freeze_sha256": freeze_sha256,
        "freeze_path": str(freeze_path),
    }


def score_holdout_file(
    *,
    manifest_path: Path,
    source_manifest_path: Path,
    freeze_path: Path,
    reviewer_a_path: Path,
    reviewer_b_path: Path,
    owner_path: Path,
    output_path: Path,
) -> dict[str, object]:
    manifest = _load_json_object(manifest_path)
    if not _manifest_hash_valid(manifest):
        raise SafetyContractError("manifest_hash_mismatch")
    source_manifest = _load_json_object(source_manifest_path)
    if not _manifest_hash_valid(source_manifest):
        raise SafetyContractError("source_manifest_hash_mismatch")
    freeze = _load_json_object(freeze_path)
    threshold_value = freeze.get("threshold_sec")
    if freeze.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise SafetyContractError("freeze_manifest_mismatch")
    if threshold_value not in THRESHOLD_CANDIDATES:
        raise SafetyContractError("invalid_frozen_threshold")
    if any(
        manifest.get(field) != source_manifest.get(field)
        for field in ("source_snapshot_sha256", "blocked_set_sha256")
    ):
        raise SafetyContractError("source_provenance_mismatch")

    _, holdout = _pairs_from_manifest(manifest)
    accounted = _accounting_from_manifest(source_manifest)
    source_clip_ids = source_manifest.get("source_clip_ids")
    if (
        not isinstance(source_clip_ids, list)
        or len(source_clip_ids) != len(set(source_clip_ids))
        or set(source_clip_ids) != {row.clip_id for row in accounted}
    ):
        raise SafetyContractError("source_accounting_set_mismatch")
    camera_nights = manifest.get("camera_nights")
    if not isinstance(camera_nights, dict):
        raise SafetyContractError("manifest_camera_nights_missing")
    frozen_nights = {
        tuple(night)
        for split_nights in camera_nights.values()
        if isinstance(split_nights, list)
        for night in split_nights
        if isinstance(night, list) and len(night) == 2
    }
    accounting_nights = {
        (row.camera_id, row.activity_day_kst.isoformat())
        for row in accounted
    }
    if len(frozen_nights) != 12 or accounting_nights != frozen_nights:
        raise SafetyContractError("source_camera_night_scope_mismatch")
    expected = {item.pair_id for item in holdout}
    reviewer_a = validate_reviewer_rows(
        _worksheet_rows(reviewer_a_path), expected
    )
    reviewer_b = validate_reviewer_rows(
        _worksheet_rows(reviewer_b_path), expected
    )
    final = finalize_boundary_gt(
        expected,
        reviewer_a,
        reviewer_b,
        _worksheet_rows(owner_path),
    )
    events, rerun_hashes, _ = _run_grouping_three_times(
        accounted, threshold_value
    )
    activity_count = sum(
        row.kind == "activity_candidate" for row in accounted
    )
    event_reduction_rate = (
        (activity_count - len(events)) / activity_count
        if activity_count
        else 0.0
    )
    camera_over_merge_counts: dict[str, int] = {}
    camera_over_split_counts: dict[str, int] = {}
    camera_same_counts: dict[str, int] = {}
    camera_class_counts: dict[str, dict[str, int]] = {}
    over_merge_count = 0
    over_split_count = 0
    same_count = 0
    uncertain_count = 0
    for item in holdout:
        decision = final.decisions[item.pair_id]
        classes = camera_class_counts.setdefault(
            item.camera_id,
            {"same_event": 0, "different_event": 0, "uncertain": 0},
        )
        classes[decision] += 1
        if decision == "uncertain":
            uncertain_count += 1
            continue
        predicted_same = item.gap_sec <= threshold_value
        if decision == "different_event" and predicted_same:
            over_merge_count += 1
            camera_over_merge_counts[item.camera_id] = (
                camera_over_merge_counts.get(item.camera_id, 0) + 1
            )
        if decision == "same_event":
            same_count += 1
            camera_same_counts[item.camera_id] = (
                camera_same_counts.get(item.camera_id, 0) + 1
            )
            if not predicted_same:
                over_split_count += 1
                camera_over_split_counts[item.camera_id] = (
                    camera_over_split_counts.get(item.camera_id, 0) + 1
                )
    cameras = set(camera_class_counts)
    metrics = HoldoutMetrics(
        expected_pair_count=len(holdout),
        reviewer_agreement=final.raw_agreement,
        uncertain_rate=uncertain_count / len(holdout) if holdout else 0.0,
        over_merge_count=over_merge_count,
        camera_over_merge_counts={
            camera: camera_over_merge_counts.get(camera, 0)
            for camera in cameras
        },
        over_split_rate=over_split_count / same_count if same_count else 0.0,
        camera_over_split_rates={
            camera: (
                camera_over_split_counts.get(camera, 0)
                / camera_same_counts[camera]
                if camera_same_counts.get(camera, 0)
                else 0.0
            )
            for camera in cameras
        },
        camera_class_counts=camera_class_counts,
        event_reduction_rate=event_reduction_rate,
        accounting_unassigned=0,
        accounting_duplicates=0,
        diagnostic_cross_merges=0,
        protected_clip_contacts=0,
        rerun_hashes=rerun_hashes,
    )
    summary = score_frozen_holdout(
        freeze_path=freeze_path,
        threshold_sec=threshold_value,
        manifest_sha256=str(manifest["manifest_sha256"]),
        metrics=metrics,
        output_path=output_path,
    )
    return {
        "verdict": summary.verdict,
        "threshold_sec": summary.threshold_sec,
        "metrics_sha256": summary.metrics_sha256,
        "rerun_hashes": list(rerun_hashes),
        "output_path": str(output_path),
    }


def _client() -> Any:
    from backend.supabase_client import get_supabase_client

    return get_supabase_client()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--as-of", required=True)
    prepare.add_argument("--out-dir", type=Path, required=True)
    prepare.add_argument(
        "--blocked-manifest", type=Path, action="append", required=True
    )
    group = commands.add_parser("group")
    group.add_argument("--manifest", type=Path, required=True)
    group.add_argument("--threshold", type=int, required=True)
    group.add_argument("--out", type=Path, required=True)
    score_dev = commands.add_parser("score-dev")
    score_dev.add_argument("--manifest", type=Path, required=True)
    score_dev.add_argument("--reviewer-a", type=Path, required=True)
    score_dev.add_argument("--reviewer-b", type=Path, required=True)
    score_dev.add_argument("--owner", type=Path, required=True)
    score_dev.add_argument("--freeze-out", type=Path, required=True)
    score_holdout = commands.add_parser("score-holdout")
    score_holdout.add_argument("--manifest", type=Path, required=True)
    score_holdout.add_argument(
        "--source-manifest", type=Path, required=True
    )
    score_holdout.add_argument("--freeze", type=Path, required=True)
    score_holdout.add_argument("--reviewer-a", type=Path, required=True)
    score_holdout.add_argument("--reviewer-b", type=Path, required=True)
    score_holdout.add_argument("--owner", type=Path, required=True)
    score_holdout.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "prepare":
        repo = Path(__file__).resolve().parents[1]
        result = prepare_artifacts(
            client=_client(),
            as_of=parse_as_of(args.as_of),
            out_dir=args.out_dir,
            blocked_paths=args.blocked_manifest,
            allowed_roots=(repo, repo / "storage"),
        )
    elif args.command == "group":
        result = group_manifest(
            args.manifest,
            threshold_sec=args.threshold,
            output_path=args.out,
        )
    elif args.command == "score-dev":
        result = score_development(
            manifest_path=args.manifest,
            reviewer_a_path=args.reviewer_a,
            reviewer_b_path=args.reviewer_b,
            owner_path=args.owner,
            freeze_path=args.freeze_out,
        )
    else:
        result = score_holdout_file(
            manifest_path=args.manifest,
            source_manifest_path=args.source_manifest,
            freeze_path=args.freeze,
            reviewer_a_path=args.reviewer_a,
            reviewer_b_path=args.reviewer_b,
            owner_path=args.owner,
            output_path=args.out,
        )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

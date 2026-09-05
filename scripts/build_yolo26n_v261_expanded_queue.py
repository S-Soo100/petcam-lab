"""Build the deterministic source split for the YOLO26n v2.6.1 review queue.

The module deliberately keeps GME summary fields as candidate signals only. Human
review remains the only source of presence and bbox ground truth.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
SEED = "yolo26n-v261-expanded-hardcase-v1"
SOURCE_PLAN_SCHEMA = "yolo26n-v261-source-plan-v1"


def _parse_instant(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("invalid started_at")
    if parsed.tzinfo is None:
        raise ValueError("started_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def camera_night(started_at: str | datetime) -> str:
    """Return the KST calendar date used as the camera-night grouping key."""
    return _parse_instant(started_at).astimezone(KST).date().isoformat()


def _stable_rank(seed: str, *parts: object) -> str:
    payload = "\0".join((seed, *(str(part) for part in parts))).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalized_source(raw: Mapping[str, object]) -> dict[str, object]:
    clip_ref = raw.get("clip_ref")
    camera_ref = raw.get("camera_ref")
    started_at = raw.get("started_at")
    duration_sec = raw.get("duration_sec")
    if not isinstance(clip_ref, str) or not clip_ref:
        raise ValueError("invalid clip_ref")
    if not isinstance(camera_ref, str) or not camera_ref:
        raise ValueError("invalid camera_ref")
    if not isinstance(started_at, (str, datetime)):
        raise ValueError("invalid started_at")
    if isinstance(duration_sec, bool) or not isinstance(duration_sec, (int, float)):
        raise ValueError("invalid duration_sec")
    if duration_sec <= 0:
        raise ValueError("invalid duration_sec")
    result = dict(raw)
    result["clip_ref"] = clip_ref
    result["camera_ref"] = camera_ref
    result["started_at"] = _parse_instant(started_at).isoformat()
    result["duration_sec"] = float(duration_sec)
    result["camera_night"] = camera_night(started_at)
    gme = raw.get("gme", {})
    if not isinstance(gme, Mapping):
        raise ValueError("invalid gme summary")
    result["gme"] = dict(gme)
    return result


def freeze_future_holdout(
    sources: Iterable[Mapping[str, object]],
    *,
    count: int,
    seed: str,
    minimum_camera_count: int = 2,
    minimum_night_count: int = 3,
) -> list[dict[str, object]]:
    """Freeze an exact, reproducible holdout with camera-night coverage.

    One row is taken from every available camera-night group before the remaining
    slots are filled globally. This protects rare camera/night combinations from
    disappearing behind the dominant camera.
    """
    normalized = [_normalized_source(row) for row in sources]
    if len(normalized) < count or count <= 0:
        raise ValueError("future holdout shortage")
    if len({row["camera_ref"] for row in normalized}) < minimum_camera_count:
        raise ValueError("future holdout camera diversity shortage")
    if len({row["camera_night"] for row in normalized}) < minimum_night_count:
        raise ValueError("future holdout night diversity shortage")

    by_group: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in normalized:
        by_group[(str(row["camera_ref"]), str(row["camera_night"]))].append(row)
    for group, rows in by_group.items():
        rows.sort(key=lambda row: _stable_rank(seed, *group, row["clip_ref"]))

    selected: list[dict[str, object]] = []
    # Round-robin across groups makes the behavior deterministic even if count is
    # smaller than the number of available camera-night groups.
    group_keys = sorted(by_group, key=lambda group: _stable_rank(seed, *group))
    while len(selected) < count:
        progressed = False
        for group in group_keys:
            rows = by_group[group]
            if not rows:
                continue
            selected.append(rows.pop(0))
            progressed = True
            if len(selected) == count:
                break
        if not progressed:
            raise ValueError("future holdout shortage")

    selected.sort(key=lambda row: str(row["clip_ref"]))
    return selected


def _number(metrics: Mapping[str, object], key: str) -> float | None:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def detector_candidate_reasons(
    metrics: Mapping[str, object], *, duration_sec: float
) -> tuple[str, ...]:
    """Convert GME quality summaries into detector-review signals, never GT."""
    reasons: list[str] = []
    visible = _number(metrics, "visible_sec")
    unknown = _number(metrics, "unknown_sec")
    if visible is not None and visible <= 0:
        reasons.append("zero_visible")
    if unknown is not None and duration_sec > 0 and unknown / duration_sec >= 0.8:
        reasons.append("unknown_high")
    gaps = _number(metrics, "detection_gap_count")
    if gaps is not None and gaps >= 10:
        reasons.append("detection_gap")
    fragmentation = _number(metrics, "fragmentation_count")
    if fragmentation is not None and fragmentation >= 10:
        reasons.append("fragmentation")
    jumps = _number(metrics, "position_jump_count")
    if jumps is not None and jumps >= 3:
        reasons.append("position_jump")
    simultaneous = _number(metrics, "max_simultaneous_geckos")
    if simultaneous is not None and simultaneous >= 2:
        reasons.append("multi_gecko_or_reflection")
    return tuple(reasons)


def _anomaly_score(row: Mapping[str, object]) -> tuple[int, float, str]:
    metrics = row["gme"]
    assert isinstance(metrics, Mapping)
    reasons = detector_candidate_reasons(
        metrics, duration_sec=float(row["duration_sec"])
    )
    magnitude = 0.0
    for key in (
        "detection_gap_count",
        "fragmentation_count",
        "position_jump_count",
        "max_simultaneous_geckos",
    ):
        magnitude += _number(metrics, key) or 0.0
    return (len(reasons), magnitude, str(row["clip_ref"]))


def _balanced_controls(
    rows: list[dict[str, object]], *, limit: int, seed: str
) -> list[dict[str, object]]:
    by_camera: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_camera[str(row["camera_ref"])].append(row)
    for camera, camera_rows in by_camera.items():
        camera_rows.sort(
            key=lambda row: _stable_rank(seed, "control", camera, row["clip_ref"])
        )
    cameras = sorted(by_camera, key=lambda camera: _stable_rank(seed, "camera", camera))
    selected: list[dict[str, object]] = []
    while len(selected) < limit:
        progressed = False
        for camera in cameras:
            if not by_camera[camera]:
                continue
            selected.append(by_camera[camera].pop(0))
            progressed = True
            if len(selected) == limit:
                break
        if not progressed:
            break
    return selected


def select_development_sources(
    sources: Iterable[Mapping[str, object]],
    *,
    owner_clip_refs: set[str],
    excluded_clip_refs: set[str],
    anomaly_limit: int,
    control_limit: int,
    seed: str,
) -> list[dict[str, Any]]:
    """Select owner-confirmed, anomaly-ranked, and IID control source clips."""
    if anomaly_limit < 0 or control_limit < 0:
        raise ValueError("selection limits must be non-negative")
    normalized = [
        _normalized_source(row)
        for row in sources
        if str(row.get("clip_ref")) not in excluded_clip_refs
    ]
    by_ref = {str(row["clip_ref"]): row for row in normalized}
    selected: dict[str, dict[str, Any]] = {}

    for clip_ref in sorted(owner_clip_refs):
        row = by_ref.get(clip_ref)
        if row is not None:
            selected[clip_ref] = {**row, "reasons": ["owner_confirmed"]}

    anomaly_rows: list[dict[str, object]] = []
    control_rows: list[dict[str, object]] = []
    for row in normalized:
        clip_ref = str(row["clip_ref"])
        if clip_ref in selected:
            continue
        metrics = row["gme"]
        assert isinstance(metrics, Mapping)
        reasons = detector_candidate_reasons(
            metrics, duration_sec=float(row["duration_sec"])
        )
        if reasons:
            anomaly_rows.append(row)
        else:
            control_rows.append(row)

    anomaly_rows.sort(key=_anomaly_score, reverse=True)
    for row in anomaly_rows[:anomaly_limit]:
        metrics = row["gme"]
        assert isinstance(metrics, Mapping)
        reasons = detector_candidate_reasons(
            metrics, duration_sec=float(row["duration_sec"])
        )
        selected[str(row["clip_ref"])] = {**row, "reasons": list(reasons)}

    for row in _balanced_controls(control_rows, limit=control_limit, seed=seed):
        selected[str(row["clip_ref"])] = {**row, "reasons": ["iid_control"]}

    return sorted(selected.values(), key=lambda row: str(row["clip_ref"]))


def build_source_plan(
    sources: Iterable[Mapping[str, object]],
    *,
    v26_used_clip_refs: set[str],
    owner_clip_refs: set[str],
    future_holdout_count: int,
    historical_anomaly_limit: int,
    historical_control_limit: int,
    seed: str,
) -> dict[str, list[dict[str, Any]]]:
    """Seal future sources, then select the disjoint development source pool."""
    normalized = [_normalized_source(row) for row in sources]
    post = [row for row in normalized if row.get("cohort") == "post_v26"]
    historical = [
        row for row in normalized if row.get("cohort") == "historical_unused"
    ]
    holdout = freeze_future_holdout(
        post,
        count=future_holdout_count,
        seed=f"{seed}:future-holdout",
    )
    holdout_refs = {str(row["clip_ref"]) for row in holdout}

    development: dict[str, dict[str, Any]] = {}
    for row in post:
        clip_ref = str(row["clip_ref"])
        if clip_ref in holdout_refs:
            continue
        metrics = row["gme"]
        assert isinstance(metrics, Mapping)
        reasons = ["post_v26_coverage"]
        reasons.extend(
            detector_candidate_reasons(
                metrics, duration_sec=float(row["duration_sec"])
            )
        )
        if clip_ref in owner_clip_refs:
            reasons.insert(0, "owner_confirmed")
        development[clip_ref] = {**row, "reasons": list(dict.fromkeys(reasons))}

    # A v2.6 source can only return through explicit Owner-confirmed evidence;
    # frame-level SHA/dHash checks still decide whether any extracted image is new.
    historical_exclusions = v26_used_clip_refs - owner_clip_refs
    historical_selected = select_development_sources(
        historical,
        owner_clip_refs=owner_clip_refs,
        excluded_clip_refs=historical_exclusions | holdout_refs,
        anomaly_limit=historical_anomaly_limit,
        control_limit=historical_control_limit,
        seed=f"{seed}:historical",
    )
    for row in historical_selected:
        development[str(row["clip_ref"])] = row

    return {
        "future_holdout": holdout,
        "development": sorted(
            development.values(), key=lambda row: str(row["clip_ref"])
        ),
    }


def deduplicate_candidate_frames(
    candidates: Iterable[Mapping[str, object]],
    protected_fingerprints: Iterable[Mapping[str, object]],
    *,
    hamming_distance: int = 2,
    perceptual_exception_limits: Mapping[str, int] | None = None,
) -> dict[str, object]:
    """Reject protected near-matches and repeated frames from the same clip.

    Perceptual similarity is intentionally scoped to one source for the candidate
    pool because different terrariums can share a static background layout.
    """
    protected_sha: set[str] = set()
    protected_dhash_by_source: dict[str, list[int]] = defaultdict(list)
    for raw in protected_fingerprints:
        image_sha = str(raw.get("image_sha256") or "")
        dhash = str(raw.get("dhash64") or "")
        source_key = str(raw.get("clip_ref") or raw.get("source_video_sha256") or "")
        if len(image_sha) != 64 or len(dhash) != 16 or not source_key:
            raise ValueError("protected fingerprint contract mismatch")
        protected_sha.add(image_sha)
        protected_dhash_by_source[source_key].append(int(dhash, 16))

    rows = sorted(
        (dict(row) for row in candidates),
        key=lambda row: (
            str(row.get("source_video_sha256") or ""),
            int(row.get("frame_index") or 0),
            str(row.get("image_sha256") or ""),
        ),
    )
    counts = {
        "input": len(rows),
        "protected_exact": 0,
        "protected_perceptual": 0,
        "pool_exact": 0,
        "same_source_perceptual": 0,
        "same_source_perceptual_exception": 0,
        "accepted": 0,
    }
    accepted: list[dict[str, object]] = []
    accepted_sha: set[str] = set()
    accepted_by_source: dict[str, list[int]] = defaultdict(list)
    exception_limits = dict(perceptual_exception_limits or {})
    if any(
        not isinstance(key, str)
        or not key
        or isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        for key, value in exception_limits.items()
    ):
        raise ValueError("perceptual exception contract mismatch")
    exceptions_used: dict[str, int] = defaultdict(int)
    for row in rows:
        source_sha = str(row.get("source_video_sha256") or "")
        source_key = str(row.get("clip_ref") or source_sha)
        image_sha = str(row.get("image_sha256") or "")
        dhash = str(row.get("dhash64") or "")
        frame_index = row.get("frame_index")
        if (
            len(source_sha) != 64
            or len(image_sha) != 64
            or len(dhash) != 16
            or isinstance(frame_index, bool)
            or not isinstance(frame_index, int)
            or frame_index < 0
        ):
            raise ValueError("candidate fingerprint contract mismatch")
        parsed = int(dhash, 16)
        if image_sha in protected_sha:
            counts["protected_exact"] += 1
        elif any(
            (parsed ^ value).bit_count() <= hamming_distance
            for value in protected_dhash_by_source[source_key]
        ):
            counts["protected_perceptual"] += 1
        elif image_sha in accepted_sha:
            counts["pool_exact"] += 1
        elif any(
            (parsed ^ value).bit_count() <= hamming_distance
            for value in accepted_by_source[source_sha]
        ):
            if exceptions_used[source_key] < exception_limits.get(source_key, 0):
                exceptions_used[source_key] += 1
                counts["same_source_perceptual_exception"] += 1
                accepted.append(row)
                accepted_sha.add(image_sha)
                accepted_by_source[source_sha].append(parsed)
            else:
                counts["same_source_perceptual"] += 1
        else:
            accepted.append(row)
            accepted_sha.add(image_sha)
            accepted_by_source[source_sha].append(parsed)
    counts["accepted"] = len(accepted)
    return {"counts": counts, "records": accepted}


def _paged(query_factory: Any, *, page_size: int = 1_000) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    offset = 0
    while True:
        response = query_factory().range(offset, offset + page_size - 1).execute()
        page = getattr(response, "data", None)
        if not isinstance(page, list):
            raise RuntimeError("database read returned an invalid page")
        rows.extend(dict(row) for row in page)
        if len(page) < page_size:
            break
        offset += page_size
    return rows


def _load_v26_source_refs(path: Path) -> set[str]:
    payload = json.loads(path.read_text())
    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise ValueError("invalid v2.6 source manifest")
    result = {
        str(row.get("clip_id"))
        for row in sources
        if isinstance(row, Mapping) and row.get("clip_id")
    }
    if not result:
        raise ValueError("empty v2.6 source manifest")
    return result


def _load_owner_confirmed_refs(path: Path) -> set[str]:
    result: set[str] = set()
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("reviewer_stage") != "owner_confirmed":
                continue
            if row.get("owner_final") != "confirmed":
                continue
            clip_ref = row.get("clip_ref", "")
            if clip_ref:
                result.add(clip_ref)
    if not result:
        raise ValueError("owner-confirmed source shortage")
    return result


def _discover_current_detector_identity(client: Any) -> str:
    response = (
        client.table("gme_runs")
        .select("detector_identity")
        .eq("status", "ok")
        .eq("algorithm_version", "gme-motion-v1")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = getattr(response, "data", None)
    if not isinstance(rows, list) or len(rows) != 1:
        raise RuntimeError("current detector identity unavailable")
    identity = str(rows[0].get("detector_identity") or "")
    if len(identity) != 64 or any(char not in "0123456789abcdef" for char in identity):
        raise RuntimeError("current detector identity invalid")
    return identity


def _load_current_gme_by_clip(client: Any, detector_identity: str) -> dict[str, dict[str, object]]:
    rows = _paged(
        lambda: client.table("gme_runs")
        .select(
            "clip_id,created_at,algorithm_version,duration_sec,visible_sec,unknown_sec,"
            "max_simultaneous_geckos,tracking_quality,status,detector_identity"
        )
        .eq("status", "ok")
        .eq("detector_identity", detector_identity)
        .order("created_at", desc=True)
    )
    by_clip: dict[str, dict[str, object]] = {}
    for row in rows:
        clip_ref = str(row.get("clip_id") or "")
        if not clip_ref:
            continue
        current = by_clip.get(clip_ref)
        rank = (
            1 if row.get("algorithm_version") == "gme-motion-v1" else 0,
            str(row.get("created_at") or ""),
        )
        current_rank = (
            1 if current and current.get("algorithm_version") == "gme-motion-v1" else 0,
            str(current.get("created_at") or "") if current else "",
        )
        if current is None or rank > current_rank:
            quality = row.get("tracking_quality")
            metrics = dict(quality) if isinstance(quality, Mapping) else {}
            for key in ("visible_sec", "unknown_sec", "max_simultaneous_geckos"):
                metrics[key] = row.get(key)
            by_clip[clip_ref] = {
                "algorithm_version": row.get("algorithm_version"),
                "created_at": row.get("created_at"),
                "metrics": metrics,
            }
    return by_clip


def _load_source_rows(
    client: Any,
    *,
    historical_start: str,
    snapshot_end: str,
    owner_clip_refs: set[str],
) -> list[dict[str, object]]:
    rows = _paged(
        lambda: client.table("motion_clips")
        .select("id,camera_id,started_at,duration_sec,r2_key,clip_purpose")
        .eq("clip_purpose", "production")
        .gte("started_at", historical_start)
        .lte("started_at", snapshot_end)
        .not_.is_("r2_key", "null")
        .order("started_at")
    )
    known = {str(row.get("id")) for row in rows}
    missing_owner = sorted(owner_clip_refs - known)
    for offset in range(0, len(missing_owner), 100):
        chunk = missing_owner[offset : offset + 100]
        if not chunk:
            continue
        response = (
            client.table("motion_clips")
            .select("id,camera_id,started_at,duration_sec,r2_key,clip_purpose")
            .in_("id", chunk)
            .execute()
        )
        page = getattr(response, "data", None)
        if not isinstance(page, list):
            raise RuntimeError("owner source read failed")
        rows.extend(dict(row) for row in page)
    return rows


def _load_excluded_clip_refs(client: Any) -> set[str]:
    rows = _paged(
        lambda: client.table("motion_clip_system_exclusions")
        .select("clip_id,state")
        .in_("state", ["quarantined", "media_deleted"])
        .order("clip_id")
    )
    return {str(row.get("clip_id")) for row in rows if row.get("clip_id")}


def _source_records(
    clip_rows: Iterable[Mapping[str, object]],
    *,
    gme_by_clip: Mapping[str, Mapping[str, object]],
    excluded_clip_refs: set[str],
    v26_cutoff: str,
    minimum_duration_sec: float,
) -> list[dict[str, object]]:
    cutoff = _parse_instant(v26_cutoff)
    result: list[dict[str, object]] = []
    for row in clip_rows:
        clip_ref = str(row.get("id") or "")
        camera_ref = str(row.get("camera_id") or "")
        started_at = row.get("started_at")
        r2_key = str(row.get("r2_key") or "")
        try:
            duration_sec = float(row.get("duration_sec") or 0.0)
            instant = _parse_instant(str(started_at))
        except (TypeError, ValueError):
            continue
        if (
            not clip_ref
            or not camera_ref
            or not r2_key
            or row.get("clip_purpose") != "production"
            or clip_ref in excluded_clip_refs
            or duration_sec < minimum_duration_sec
        ):
            continue
        gme = gme_by_clip.get(clip_ref, {})
        metrics = gme.get("metrics", {}) if isinstance(gme, Mapping) else {}
        result.append(
            {
                "clip_ref": clip_ref,
                "camera_ref": camera_ref,
                "started_at": instant.isoformat(),
                "duration_sec": duration_sec,
                "r2_key": r2_key,
                "cohort": "post_v26" if instant > cutoff else "historical_unused",
                "gme_algorithm_version": gme.get("algorithm_version") if isinstance(gme, Mapping) else None,
                "gme": dict(metrics) if isinstance(metrics, Mapping) else {},
            }
        )
    return sorted(result, key=lambda row: (str(row["started_at"]), str(row["clip_ref"])))


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_private_json(path: Path, payload: object) -> None:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def run_inventory(args: argparse.Namespace) -> dict[str, object]:
    from dotenv import load_dotenv
    from supabase import create_client

    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("output already exists")
    load_dotenv(args.env_file)
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("Supabase configuration missing")
    client = create_client(url, key)
    identity = _discover_current_detector_identity(client)
    v26_used_refs = _load_v26_source_refs(args.v26_source_manifest)
    owner_refs = _load_owner_confirmed_refs(args.owner_ledger)
    gme_by_clip = _load_current_gme_by_clip(client, identity)
    clips = _load_source_rows(
        client,
        historical_start=args.historical_start,
        snapshot_end=args.snapshot_end,
        owner_clip_refs=owner_refs,
    )
    exclusions = _load_excluded_clip_refs(client)
    sources = _source_records(
        clips,
        gme_by_clip=gme_by_clip,
        excluded_clip_refs=exclusions,
        v26_cutoff=args.v26_cutoff,
        minimum_duration_sec=args.minimum_duration_sec,
    )
    plan = build_source_plan(
        sources,
        v26_used_clip_refs=v26_used_refs,
        owner_clip_refs=owner_refs,
        future_holdout_count=args.future_holdout_count,
        historical_anomaly_limit=args.historical_anomaly_limit,
        historical_control_limit=args.historical_control_limit,
        seed=args.seed,
    )
    holdout_refs = {str(row["clip_ref"]) for row in plan["future_holdout"]}
    development_refs = {str(row["clip_ref"]) for row in plan["development"]}
    if holdout_refs & development_refs:
        raise ValueError("future/development source overlap")

    camera_count = len({row["camera_ref"] for row in plan["future_holdout"]})
    night_count = len({row["camera_night"] for row in plan["future_holdout"]})
    if camera_count < 2 or night_count < 3:
        raise ValueError("future holdout diversity shortage")

    output.mkdir(mode=0o700, parents=True)
    snapshot_payload = {
        "schema": "yolo26n-v261-source-snapshot-v1",
        "snapshot_end": args.snapshot_end,
        "historical_start": args.historical_start,
        "v26_cutoff": args.v26_cutoff,
        "detector_identity": identity,
        "records": sources,
    }
    holdout_payload = {
        "schema": "yolo26n-v261-future-holdout-v1",
        "status": "SEALED_SOURCE_ONLY",
        "seed": args.seed,
        "records": plan["future_holdout"],
    }
    development_payload = {
        "schema": "yolo26n-v261-development-sources-v1",
        "status": "SOURCE_SELECTED",
        "seed": args.seed,
        "records": plan["development"],
    }
    _write_private_json(output / "source-snapshot.private.json", snapshot_payload)
    _write_private_json(output / "future-holdout.private.json", holdout_payload)
    _write_private_json(output / "development-sources.private.json", development_payload)
    summary = {
        "schema": SOURCE_PLAN_SCHEMA,
        "status": "SOURCE_PLAN_READY",
        "source_count": len(sources),
        "post_v26_source_count": sum(row["cohort"] == "post_v26" for row in sources),
        "historical_source_count": sum(row["cohort"] == "historical_unused" for row in sources),
        "gme_available_count": sum(bool(row["gme"]) for row in sources),
        "owner_confirmed_source_count": len(owner_refs & {str(row["clip_ref"]) for row in sources}),
        "future_holdout_count": len(plan["future_holdout"]),
        "future_holdout_camera_count": camera_count,
        "future_holdout_night_count": night_count,
        "development_source_count": len(plan["development"]),
        "development_anomaly_source_count": sum(
            any(reason not in {"post_v26_coverage", "iid_control", "owner_confirmed"} for reason in row["reasons"])
            for row in plan["development"]
        ),
        "development_control_source_count": sum(
            "iid_control" in row["reasons"] for row in plan["development"]
        ),
        "snapshot_sha256": _canonical_sha256(snapshot_payload),
        "future_holdout_sha256": _canonical_sha256(holdout_payload),
        "development_sources_sha256": _canonical_sha256(development_payload),
        "db_write_count": 0,
        "r2_read_count": 0,
        "r2_write_count": 0,
        "service_change_count": 0,
        "model_change_count": 0,
    }
    _write_private_json(output / "source-plan-summary.private.json", summary)
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--v26-source-manifest", required=True, type=Path)
    parser.add_argument("--owner-ledger", required=True, type=Path)
    parser.add_argument("--historical-start", default="2026-08-15T00:00:00+09:00")
    parser.add_argument("--v26-cutoff", default="2026-08-26T16:13:29.838806+09:00")
    parser.add_argument("--snapshot-end", required=True)
    parser.add_argument("--minimum-duration-sec", type=float, default=55.0)
    parser.add_argument("--future-holdout-count", type=int, default=300)
    parser.add_argument("--historical-anomaly-limit", type=int, default=600)
    parser.add_argument("--historical-control-limit", type=int, default=150)
    parser.add_argument("--seed", default=SEED)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    summary = run_inventory(args)
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

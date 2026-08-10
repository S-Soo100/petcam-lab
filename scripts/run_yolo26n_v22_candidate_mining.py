"""Build a private, read-only YOLO26n v2.2 CVAT candidate queue.

The detector is only a reviewer-routing signal.  This runner never writes to
Supabase or R2 and deliberately keeps prediction boxes out of reviewer files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from scripts.build_yolo26n_v22_candidate_queue import (
    V22CandidatePolicy,
    select_v22_candidate_sources,
)


ACTIVE_EXCLUSION_STATES = {
    "candidate",
    "quarantined",
    "media_deleted",
    "deletion_blocked",
}
PROBE_FRAME_COUNT = 24
REVIEW_FRAMES_PER_SOURCE = 2
MAX_REVIEW_FRAMES_PER_CAMERA_NIGHT = 12
HARD_POSITIVE_REVIEW_FRAMES = 220
HARD_NEGATIVE_REVIEW_FRAMES = 100
HARD_POSITIVE_PROBE_SOURCES = 560
HARD_NEGATIVE_PROBE_SOURCES = 530
MAX_PROBE_SOURCES_PER_CAMERA_NIGHT = 28
APPROVED_SEED = "owner-v2.2"
APPROVED_CUTOFF = "2026-07-15T00:00:00Z"
APPROVED_IMGSZ = 960
APPROVED_INFERENCE_CONF = 0.05
APPROVED_OUTPUT_DIR = Path(
    "/Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260811-owner-v3"
)


def eligible_clips(
    clips: Iterable[Mapping[str, object]], exclusions: Mapping[str, str]
) -> list[Mapping[str, object]]:
    """Fail closed: only production clips without an active exclusion may enter."""
    return [
        row
        for row in clips
        if row.get("clip_purpose") == "production"
        and not str(row.get("r2_key", "")).startswith("test/")
        and exclusions.get(str(row["id"])) not in ACTIVE_EXCLUSION_STATES
    ]


def choose_probe_indices(total_frames: int, count: int = PROBE_FRAME_COUNT) -> list[int]:
    """Sample the inner 80% deterministically so damaged start/end frames lose priority."""
    if total_frames <= 0 or count <= 0:
        return []
    if total_frames <= count:
        return list(range(total_frames))
    if count == 1:
        return [total_frames // 2]
    inner_indices = sorted(
        {
            round((total_frames - 1) * (0.1 + 0.8 * position / (count - 1)))
            for position in range(count)
        }
    )
    if len(inner_indices) == count:
        return inner_indices
    # A 24-frame probe cannot avoid both endpoints of a 25-frame clip. Preserve
    # count/uniqueness first, then distribute across the full valid range.
    return [
        round((total_frames - 1) * position / (count - 1))
        for position in range(count)
    ]


def choose_review_probe_indices(
    probes: Iterable[Mapping[str, object]], bucket: str, *, count: int
) -> list[int]:
    rows = list(probes)
    if bucket == "hard_positive":
        ranked = sorted(
            rows,
            key=lambda row: (
                float(row.get("max_conf", 0.0) or 0.0),
                int(row.get("detection_count", 0) or 0),
                int(row["probe_index"]),
            ),
        )
    elif bucket == "hard_negative":
        ranked = sorted(
            rows,
            key=lambda row: (
                -float(row.get("max_conf", 0.0) or 0.0),
                -int(row.get("detection_count", 0) or 0),
                int(row["probe_index"]),
            ),
        )
    else:
        ranked = sorted(rows, key=lambda row: int(row["probe_index"]))
    return [int(row["probe_index"]) for row in ranked[:count]]


def _dhash(image, cv2) -> int:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = resized[:, 1:] > resized[:, :-1]
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bit)
    return value


def _near_duplicate(value: int, existing: Iterable[int], distance: int = 2) -> bool:
    return any((value ^ other).bit_count() <= distance for other in existing)


def review_frame_is_duplicate(
    *,
    image_sha256: str,
    existing_image_sha256: set[str],
    dhash: int,
    source_dhashes: set[int],
) -> bool:
    """Old exact bytes and near-identical frames from one source are both rejected."""
    return image_sha256 in existing_image_sha256 or _near_duplicate(
        dhash, source_dhashes
    )


def reserve_review_image(
    *,
    image_sha256: str,
    accepted_image_sha256: set[str],
    dhash: int,
    source_dhashes: set[int],
) -> bool:
    """Reserve an accepted image globally and its perceptual hash within one source."""
    if review_frame_is_duplicate(
        image_sha256=image_sha256,
        existing_image_sha256=accepted_image_sha256,
        dhash=dhash,
        source_dhashes=source_dhashes,
    ):
        return False
    accepted_image_sha256.add(image_sha256)
    source_dhashes.add(dhash)
    return True


def materialize_review_rows(
    selected_sources: Iterable[Mapping[str, object]],
    probes_by_source: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    frames_per_source: int = REVIEW_FRAMES_PER_SOURCE,
    max_frames_per_camera_night: int = MAX_REVIEW_FRAMES_PER_CAMERA_NIGHT,
) -> list[dict[str, object]]:
    """Apply the 2/source and 12/camera-night rules again at frame creation time."""
    accepted: list[dict[str, object]] = []
    source_counts: Counter[str] = Counter()
    night_counts: Counter[str] = Counter()
    for source in selected_sources:
        source_ref = str(source["source_ref"])
        camera_night = str(source["camera_night"])
        bucket = str(source["candidate_bucket"])
        requested = min(
            int(source.get("planned_frame_count", frames_per_source) or 0),
            frames_per_source,
        )
        for probe_index in choose_review_probe_indices(
            probes_by_source.get(source_ref, ()), bucket, count=requested
        ):
            if source_counts[source_ref] >= frames_per_source:
                break
            if night_counts[camera_night] >= max_frames_per_camera_night:
                break
            accepted.append(
                {
                    "source_ref": source_ref,
                    "camera_night": camera_night,
                    "camera_id": str(source["camera_id"]),
                    "candidate_bucket": bucket,
                    "strata_tags": list(source.get("strata_tags", ())),
                    "probe_index": probe_index,
                }
            )
            source_counts[source_ref] += 1
            night_counts[camera_night] += 1
    return accepted


def materialize_accepted_review_rows(
    selected_sources: Iterable[Mapping[str, object]],
    probes_by_source: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    inspect_probe: Callable[[str, int], tuple[str, Mapping[str, object]]],
    frame_quotas: Mapping[str, int],
    frames_per_source: int = REVIEW_FRAMES_PER_SOURCE,
    max_frames_per_camera_night: int = MAX_REVIEW_FRAMES_PER_CAMERA_NIGHT,
    probe_extraction_counts: Mapping[str, Mapping[str, int]] | None = None,
) -> tuple[list[dict[str, object]], dict[str, dict[str, int]]]:
    """Accept ranked probes with deterministic same-bucket backfill."""
    buckets = tuple(frame_quotas)
    sources_by_bucket: dict[str, list[Mapping[str, object]]] = {
        bucket: [] for bucket in buckets
    }
    for source in selected_sources:
        bucket = str(source["candidate_bucket"])
        if bucket in sources_by_bucket:
            sources_by_bucket[bucket].append(source)

    extraction_counts = probe_extraction_counts or {}
    summary = {
        bucket: {
            "planned": int(frame_quotas[bucket]),
            "accepted": 0,
            "exact_duplicate": 0,
            "dhash_duplicate": 0,
            "deduplicated": 0,
            "unreadable": 0,
            "candidate_sources": len(sources_by_bucket[bucket]),
            "candidate_exhausted": 0,
            "source_exhausted": 0,
            "night_cap_blocked": 0,
            "requested": int(extraction_counts.get(bucket, {}).get("requested", 0)),
            "readable": int(extraction_counts.get(bucket, {}).get("readable", 0)),
            "decode_failed": int(
                extraction_counts.get(bucket, {}).get("decode_failed", 0)
            ),
            "imwrite_failed": int(
                extraction_counts.get(bucket, {}).get("imwrite_failed", 0)
            ),
            "quota_shortfall": 0,
        }
        for bucket in buckets
    }
    accepted: list[dict[str, object]] = []
    source_counts: Counter[str] = Counter()
    night_counts: Counter[str] = Counter()
    source_offsets = {bucket: 0 for bucket in buckets}
    probe_offsets: dict[str, int] = {}
    ranked_probes: dict[str, list[int]] = {}

    def accept_next(bucket: str) -> bool:
        sources = sources_by_bucket[bucket]
        while source_offsets[bucket] < len(sources):
            source = sources[source_offsets[bucket]]
            source_ref = str(source["source_ref"])
            camera_night = str(source["camera_night"])
            if source_counts[source_ref] >= frames_per_source:
                source_offsets[bucket] += 1
                continue
            if night_counts[camera_night] >= max_frames_per_camera_night:
                summary[bucket]["night_cap_blocked"] += min(
                    frames_per_source - source_counts[source_ref],
                    summary[bucket]["planned"] - summary[bucket]["accepted"],
                )
                source_offsets[bucket] += 1
                continue
            if source_ref not in ranked_probes:
                probes = probes_by_source.get(source_ref, ())
                ranked_probes[source_ref] = choose_review_probe_indices(
                    probes, bucket, count=len(probes)
                )
            probe_indices = ranked_probes[source_ref]
            offset = probe_offsets.get(source_ref, 0)
            while offset < len(probe_indices):
                probe_index = probe_indices[offset]
                offset += 1
                probe_offsets[source_ref] = offset
                outcome, details = inspect_probe(source_ref, probe_index)
                if outcome in {"exact_duplicate", "dhash_duplicate"}:
                    summary[bucket][outcome] += 1
                    summary[bucket]["deduplicated"] += 1
                    continue
                if outcome == "unreadable":
                    summary[bucket]["unreadable"] += 1
                    continue
                if outcome != "accepted":
                    raise ValueError(f"unknown probe inspection outcome: {outcome}")
                accepted.append(
                    {
                        "source_ref": source_ref,
                        "camera_night": camera_night,
                        "camera_id": str(source["camera_id"]),
                        "candidate_bucket": bucket,
                        "strata_tags": list(source.get("strata_tags", ())),
                        "probe_index": probe_index,
                        **details,
                    }
                )
                source_counts[source_ref] += 1
                night_counts[camera_night] += 1
                summary[bucket]["accepted"] += 1
                return True
            if (
                source_counts[source_ref] < frames_per_source
                and summary[bucket]["accepted"] < summary[bucket]["planned"]
            ):
                summary[bucket]["source_exhausted"] += 1
            source_offsets[bucket] += 1
        return False

    exhausted: set[str] = set()
    while any(
        summary[bucket]["accepted"] < summary[bucket]["planned"]
        and bucket not in exhausted
        for bucket in buckets
    ):
        for bucket in buckets:
            if (
                bucket in exhausted
                or summary[bucket]["accepted"] >= summary[bucket]["planned"]
            ):
                continue
            if not accept_next(bucket):
                exhausted.add(bucket)

    for bucket in buckets:
        summary[bucket]["quota_shortfall"] = (
            summary[bucket]["planned"] - summary[bucket]["accepted"]
        )
        # This is a frame-slot count, while source_exhausted counts sources.
        # Keeping the units explicit makes terminal pool shortage auditable.
        summary[bucket]["candidate_exhausted"] = (
            summary[bucket]["quota_shortfall"] if bucket in exhausted else 0
        )
    return accepted, summary


def build_candidate_manifest(
    *,
    seed: str,
    model_name: str,
    checkpoint_sha256: str,
    analyzed_ledger_sha256: str,
    review_frames: Sequence[Mapping[str, object]],
    inventory_summary: Mapping[str, object] | None = None,
    materialization_summary: Mapping[str, object] | None = None,
) -> dict[str, object]:
    frame_quotas = {
        "hard_positive": HARD_POSITIVE_REVIEW_FRAMES,
        "hard_negative": HARD_NEGATIVE_REVIEW_FRAMES,
    }
    bucket_counts = {
        bucket: sum(
            str(frame.get("candidate_bucket", "")) == bucket
            for frame in review_frames
        )
        for bucket in frame_quotas
    }
    source_counts = Counter(str(frame.get("source_ref", "")) for frame in review_frames)
    night_counts = Counter(
        str(frame.get("camera_night", "")) for frame in review_frames
    )
    source_cap_violation_count = sum(
        max(0, count - REVIEW_FRAMES_PER_SOURCE)
        for count in source_counts.values()
    )
    camera_night_cap_violation_count = sum(
        max(0, count - MAX_REVIEW_FRAMES_PER_CAMERA_NIGHT)
        for count in night_counts.values()
    )
    exact_quota = bucket_counts == frame_quotas
    status = (
        "V22_CANDIDATE_QUEUE_READY"
        if exact_quota
        and source_cap_violation_count == 0
        and camera_night_cap_violation_count == 0
        else "V22_CANDIDATE_QUEUE_SHORTAGE"
    )
    manifest = {
        "schema": "yolo26n-v22-candidate-queue-v1",
        "status": status,
        "seed": seed,
        "model": model_name,
        "checkpoint_sha256": checkpoint_sha256,
        "analyzed_ledger_sha256": analyzed_ledger_sha256,
        "prediction_boxes_exposed_to_reviewer": False,
        "human_review_required": True,
        "db_write_count": 0,
        "r2_write_count": 0,
        "frame_quotas": frame_quotas,
        "bucket_counts": bucket_counts,
        "camera_night_count": len(night_counts),
        "source_cap_violation_count": source_cap_violation_count,
        "camera_night_cap_violation_count": camera_night_cap_violation_count,
        "review_frame_count": len(review_frames),
        "frames": list(review_frames),
    }
    if inventory_summary is not None:
        for key in (
            "inventory_pool_counts",
            "inventory_selection_counts",
            "inventory_selection_shortfalls",
        ):
            manifest[key] = dict(inventory_summary.get(key, {}))
        manifest["inventory_downloaded_source_count"] = int(
            inventory_summary.get("downloaded_source_count", 0)
        )
        manifest["inventory_missing_source_count"] = int(
            inventory_summary.get("missing_source_count", 0)
        )
        manifest["inventory_downloaded_counts"] = dict(
            inventory_summary.get("downloaded_bucket_counts", {})
        )
        manifest["inventory_missing_counts"] = dict(
            inventory_summary.get("missing_bucket_counts", {})
        )
    if materialization_summary is not None:
        manifest["materialization_counts"] = {
            str(bucket): dict(counts)
            for bucket, counts in materialization_summary.items()
            if isinstance(counts, Mapping)
        }
    return manifest


def _write_private_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _paged(query_factory, page_size: int = 1_000) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        page = query_factory().range(start, start + page_size - 1).execute().data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size


def _camera_night(camera_id: str, started_at: str) -> str:
    parsed = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    night = parsed.astimezone(timezone(timedelta(hours=9))) - timedelta(hours=12)
    raw = f"{camera_id}:{night.date().isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _extract_source_refs(payload: object) -> set[str]:
    if isinstance(payload, Mapping):
        refs: set[str] = set()
        for key, value in payload.items():
            if key == "source_ref":
                if not isinstance(value, str):
                    raise ValueError("source_ref must be a string")
                if source_ref := value.strip():
                    refs.add(source_ref)
                continue
            refs |= _extract_source_refs(value)
        return refs
    if isinstance(payload, list):
        return set().union(*(_extract_source_refs(item) for item in payload))
    return set()


def load_inventory_existing_source_refs(paths: Sequence[Path]) -> set[str]:
    """Every supplied provenance JSON must prove at least one excluded source."""
    if not paths:
        raise ValueError("at least one existing source selection is required")
    refs: set[str] = set()
    for path in paths:
        path_refs = _extract_source_refs(
            json.loads(path.read_text(encoding="utf-8"))
        )
        if not path_refs:
            raise ValueError(f"selection has no source_ref: {path}")
        refs |= path_refs
    return refs


def validate_existing_review_csv(path: Path) -> None:
    """A blind review artifact proves row identity but cannot supply source exclusion."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        required_header = ["sequence", "camera_night_group"]
        if fieldnames != required_header:
            raise ValueError(f"review CSV must use blind header {required_header}: {path}")
        sequences: set[str] = set()
        for row in reader:
            if None in row:
                raise ValueError(f"review CSV has an over-wide row: {path}")
            sequence = str(row.get("sequence") or "").strip()
            camera_night_group = str(row.get("camera_night_group") or "").strip()
            if not sequence or not camera_night_group:
                raise ValueError(f"review CSV has an empty blind field: {path}")
            if sequence in sequences:
                raise ValueError(f"review CSV has duplicate sequence: {path}")
            sequences.add(sequence)
    if not sequences:
        raise ValueError(f"review CSV has no rows: {path}")


def _sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _load_existing_image_hashes(images_dir: Path) -> set[str]:
    if not images_dir.is_dir():
        raise FileNotFoundError(images_dir)
    return {
        _sha256_file(path)
        for path in sorted(images_dir.glob("*"))
        if path.is_file()
    }


def _rank_inventory_source(seed: str, bucket: str, source_ref: str) -> str:
    material = f"{seed}:inventory:{bucket}:{source_ref}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _inventory_bucket(source: Mapping[str, object]) -> str:
    if int(source.get("gme_max_geckos", 0) or 0) >= 1:
        return "hard_positive"
    return "hard_negative"


def _select_inventory_sources(
    sources: Iterable[Mapping[str, object]], *, args: argparse.Namespace
) -> list[dict[str, object]]:
    """Bound R2 GETs before local inference without assigning a human label."""
    quotas = {
        "hard_positive": args.probe_hard_positive_sources,
        "hard_negative": args.probe_hard_negative_sources,
    }
    grouped: dict[str, list[Mapping[str, object]]] = {
        bucket: [] for bucket in quotas
    }
    for source in sources:
        grouped[_inventory_bucket(source)].append(source)

    ranked_by_bucket = {
        bucket: sorted(
            grouped[bucket],
            key=lambda row: _rank_inventory_source(
                args.seed, bucket, str(row["source_ref"])
            ),
        )
        for bucket in quotas
    }
    selected: list[dict[str, object]] = []
    selected_counts: Counter[str] = Counter()
    night_source_counts: Counter[str] = Counter()
    next_indices = {bucket: 0 for bucket in quotas}
    while len(selected) < args.inventory_max_sources:
        made_progress = False
        for bucket, quota in quotas.items():
            if selected_counts[bucket] >= quota:
                continue
            ranked = ranked_by_bucket[bucket]
            while next_indices[bucket] < len(ranked):
                source = ranked[next_indices[bucket]]
                next_indices[bucket] += 1
                camera_night = str(source["camera_night"])
                if (
                    night_source_counts[camera_night]
                    >= args.probe_max_sources_per_night
                ):
                    continue
                selected.append({**source, "probe_bucket": bucket})
                selected_counts[bucket] += 1
                night_source_counts[camera_night] += 1
                made_progress = True
                break
        if not made_progress or all(
            selected_counts[bucket] >= quota for bucket, quota in quotas.items()
        ):
            break
    return selected


def build_inventory_selection_summary(
    sources: Iterable[Mapping[str, object]],
    selected_sources: Iterable[Mapping[str, object]],
    *,
    args: argparse.Namespace,
) -> dict[str, object]:
    """Return identifier-free counts for the pre-download selection gate."""
    buckets = ("hard_positive", "hard_negative")
    quotas = {
        "hard_positive": args.probe_hard_positive_sources,
        "hard_negative": args.probe_hard_negative_sources,
    }
    pool_counts = Counter(_inventory_bucket(source) for source in sources)
    selected_counts = Counter(
        str(source["probe_bucket"]) for source in selected_sources
    )
    pool_by_bucket = {bucket: pool_counts[bucket] for bucket in buckets}
    selection_by_bucket = {bucket: selected_counts[bucket] for bucket in buckets}
    shortfalls = {
        bucket: max(0, quotas[bucket] - selection_by_bucket[bucket])
        for bucket in buckets
    }
    return {
        "status": (
            "V22_INVENTORY_SELECTION_READY"
            if not any(shortfalls.values())
            and sum(selection_by_bucket.values()) == args.inventory_max_sources
            else "V22_INVENTORY_SELECTION_SHORTAGE"
        ),
        "inventory_pool_counts": pool_by_bucket,
        "inventory_selection_counts": selection_by_bucket,
        "inventory_selection_shortfalls": shortfalls,
        "inventory_selected_source_count": sum(selection_by_bucket.values()),
        "probe_max_sources_per_night": args.probe_max_sources_per_night,
    }


def build_inventory_download_summary(
    selected_sources: Iterable[Mapping[str, object]],
    downloaded_sources: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Summarize R2 GET results by bucket without exposing source identity."""
    buckets = ("hard_positive", "hard_negative")
    selected = list(selected_sources)
    downloaded = list(downloaded_sources)
    downloaded_refs = {str(source["source_ref"]) for source in downloaded}
    downloaded_counts = Counter(
        str(source["probe_bucket"]) for source in downloaded
    )
    missing_counts = Counter(
        str(source["probe_bucket"])
        for source in selected
        if str(source["source_ref"]) not in downloaded_refs
    )
    return {
        "downloaded_source_count": len(downloaded),
        "missing_source_count": len(selected) - len(downloaded),
        "downloaded_bucket_counts": {
            bucket: downloaded_counts[bucket] for bucket in buckets
        },
        "missing_bucket_counts": {
            bucket: missing_counts[bucket] for bucket in buckets
        },
    }


def select_review_source_pool(
    rows: Iterable[Mapping[str, object]], *, policy: V22CandidatePolicy
) -> list[dict[str, object]]:
    """Keep deterministic same-bucket reserves beyond the initial frame quota."""
    materialized_rows = list(rows)
    selected: list[dict[str, object]] = []
    selected_refs: set[str] = set()
    while True:
        batch = select_v22_candidate_sources(
            materialized_rows,
            policy=policy,
            excluded_source_refs=selected_refs,
        )
        if not batch:
            return selected
        new_refs = {str(row["source_ref"]) for row in batch}
        if new_refs <= selected_refs:
            return selected
        selected.extend(batch)
        selected_refs |= new_refs


def _validate_approved_output(output: Path) -> None:
    if not output.is_absolute() or output != APPROVED_OUTPUT_DIR:
        raise ValueError(f"--output={output} (expected {APPROVED_OUTPUT_DIR})")


def validate_fresh_output(output: Path, *, phase: str) -> None:
    """Reject stale or mixed attempt artifacts before phase work begins."""
    if phase not in {"inventory", "analyze"}:
        raise ValueError(f"unknown phase: {phase}")
    if not output.exists():
        if phase == "analyze":
            raise ValueError("fresh output preflight: analyze output does not exist")
        return
    if not output.is_dir():
        raise ValueError("fresh output preflight: output is not a directory")

    allowed = {
        "inventory": {"code"},
        "analyze": {
            "code",
            "inventory-selection.private.json",
            "probe-sources.private.json",
            "source-clips",
        },
    }[phase]
    present = {path.name for path in output.iterdir()}
    unexpected = sorted(present - allowed)
    if unexpected:
        raise ValueError(
            "fresh output preflight: unexpected artifacts: " + ", ".join(unexpected)
        )
    if phase == "analyze":
        required = {
            "inventory-selection.private.json",
            "probe-sources.private.json",
            "source-clips",
        }
        missing = sorted(required - present)
        if missing:
            raise ValueError(
                "fresh output preflight: missing inventory artifacts: "
                + ", ".join(missing)
            )


def validate_cli_contract(args: argparse.Namespace) -> None:
    """Task 4 may only run the approved, bounded v2.2 data contract."""
    if args.phase == "inventory":
        expected = {
            "seed": APPROVED_SEED,
            "probe_hard_positive_sources": HARD_POSITIVE_PROBE_SOURCES,
            "probe_hard_negative_sources": HARD_NEGATIVE_PROBE_SOURCES,
            "probe_max_sources_per_night": MAX_PROBE_SOURCES_PER_CAMERA_NIGHT,
            "probe_frames_per_source": PROBE_FRAME_COUNT,
            "inventory_max_sources": (
                HARD_POSITIVE_PROBE_SOURCES + HARD_NEGATIVE_PROBE_SOURCES
            ),
        }
    else:
        expected = {
            "seed": APPROVED_SEED,
            "imgsz": APPROVED_IMGSZ,
            "inference_conf": APPROVED_INFERENCE_CONF,
            "probe_frames_per_source": PROBE_FRAME_COUNT,
            "review_frames_per_source": REVIEW_FRAMES_PER_SOURCE,
            "hard_positive_frames": HARD_POSITIVE_REVIEW_FRAMES,
            "hard_negative_frames": HARD_NEGATIVE_REVIEW_FRAMES,
            "max_frames_per_night": MAX_REVIEW_FRAMES_PER_CAMERA_NIGHT,
        }
    mismatched = [
        f"--{name.replace('_', '-')}={getattr(args, name)} (expected {value})"
        for name, value in expected.items()
        if getattr(args, name) != value
    ]
    try:
        _validate_approved_output(args.output)
    except ValueError as exc:
        mismatched.append(str(exc))
    if args.phase == "inventory":
        try:
            cutoff = datetime.fromisoformat(args.cutoff.replace("Z", "+00:00"))
            if cutoff.tzinfo is None:
                raise ValueError("cutoff must include an explicit UTC offset")
            canonical_cutoff = cutoff.astimezone(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            )
        except ValueError:
            canonical_cutoff = "invalid"
        if canonical_cutoff != APPROVED_CUTOFF:
            mismatched.append(
                f"--cutoff={args.cutoff} (expected {APPROVED_CUTOFF})"
            )
    if mismatched:
        raise ValueError("unsafe v2.2 CLI contract: " + ", ".join(mismatched))


def inventory(args: argparse.Namespace) -> None:
    """Read production metadata and download a bounded local probe corpus via R2 GET."""
    _validate_approved_output(args.output)
    validate_fresh_output(args.output.resolve(), phase="inventory")
    reporter_repo = args.reporter_repo.resolve()
    sys.path[:0] = [str(reporter_repo)]
    from supabase import create_client

    from reporter import config, r2

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o700)
    clips_dir = output / "source-clips"
    clips_dir.mkdir(exist_ok=True)
    clips_dir.chmod(0o700)

    existing_source_paths = list(args.existing_source_json)
    if args.existing_selection is not None:
        existing_source_paths.append(args.existing_selection)
    existing_refs = load_inventory_existing_source_refs(existing_source_paths)
    if args.existing_review_csv is not None:
        validate_existing_review_csv(args.existing_review_csv)
    sb = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    clip_rows = _paged(
        lambda: sb.table("motion_clips")
        .select("id,camera_id,started_at,duration_sec,r2_key,clip_purpose")
        .gte("started_at", args.cutoff)
        .not_.is_("r2_key", "null")
        .order("started_at")
    )
    exclusion_rows = _paged(
        lambda: sb.table("motion_clip_system_exclusions")
        .select("clip_id,state")
        .order("clip_id")
    )
    exclusions = {
        str(row["clip_id"]): str(row["state"])
        for row in exclusion_rows
        if row.get("clip_id") and row.get("state")
    }
    run_rows = _paged(
        lambda: sb.table("gme_runs")
        .select(
            "clip_id,created_at,duration_sec,visible_sec,unknown_sec,"
            "max_simultaneous_geckos,status"
        )
        .eq("status", "ok")
        .order("created_at", desc=True)
    )
    latest_runs: dict[str, dict] = {}
    for row in run_rows:
        latest_runs.setdefault(str(row["clip_id"]), row)

    private_by_ref: dict[str, dict[str, object]] = {}
    for clip in eligible_clips(clip_rows, exclusions):
        source_ref = str(clip["id"])
        if source_ref in existing_refs:
            continue
        run = latest_runs.get(source_ref)
        if run is None:
            continue
        duration = float(run.get("duration_sec") or clip.get("duration_sec") or 0.0)
        visible = float(run.get("visible_sec") or 0.0)
        unknown = float(run.get("unknown_sec") or 0.0)
        private_by_ref[source_ref] = {
            "source_ref": source_ref,
            "camera_id": str(clip["camera_id"]),
            "camera_night": _camera_night(
                str(clip["camera_id"]), str(clip["started_at"])
            ),
            "r2_key": str(clip["r2_key"]),
            "duration_sec": duration,
            "gme_visible_ratio": visible / duration if duration > 0 else 0.0,
            "gme_unknown_ratio": unknown / duration if duration > 0 else 1.0,
            "gme_max_geckos": int(run.get("max_simultaneous_geckos") or 0),
        }

    ranked = _select_inventory_sources(private_by_ref.values(), args=args)
    inventory_summary = build_inventory_selection_summary(
        private_by_ref.values(), ranked, args=args
    )
    _write_private_json(
        output / "inventory-selection.private.json", inventory_summary
    )
    print(json.dumps(inventory_summary, sort_keys=True))
    if inventory_summary["status"] != "V22_INVENTORY_SELECTION_READY":
        raise SystemExit("V22_INVENTORY_SELECTION_SHORTAGE")

    downloaded: list[dict[str, object]] = []
    for ordinal, source in enumerate(ranked, start=1):
        destination = clips_dir / f"S{ordinal:04d}.mp4"
        try:
            r2.download_clip(str(source["r2_key"]), destination)
        except r2.R2SourceMissing:
            continue
        downloaded.append({**source, "local_name": destination.name})
    download_summary = build_inventory_download_summary(ranked, downloaded)

    _write_private_json(
        output / "probe-sources.private.json",
        {
            "schema": "yolo26n-v22-probe-sources-v1",
            "seed": args.seed,
            "cutoff": args.cutoff,
            "db_write_count": 0,
            "r2_write_count": 0,
            "existing_source_ref_count": len(existing_refs),
            "probe_source_quotas": {
                "hard_positive": args.probe_hard_positive_sources,
                "hard_negative": args.probe_hard_negative_sources,
            },
            "probe_max_sources_per_night": args.probe_max_sources_per_night,
            **inventory_summary,
            **download_summary,
            "eligible_clip_count": len(private_by_ref),
            "selected_probe_source_count": len(ranked),
            "sources": downloaded,
        },
    )
    print(
        json.dumps(
            {
                "status": "PROBE_SOURCES_READY",
                "eligible": len(private_by_ref),
                "downloaded": download_summary["downloaded_source_count"],
                "missing": download_summary["missing_source_count"],
            },
            sort_keys=True,
        )
    )


def _extract_probes(
    capture, *, cv2, source_ordinal: int, probe_dir: Path, count: int
) -> tuple[list, list[dict[str, object]], dict[str, int]]:
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    frames: list = []
    probe_rows: list[dict[str, object]] = []
    frame_indices = choose_probe_indices(total_frames, count)
    extraction_counts = {
        "requested": len(frame_indices),
        "readable": 0,
        "decode_failed": 0,
        "imwrite_failed": 0,
    }
    for probe_index, frame_index in enumerate(frame_indices):
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok or frame is None:
            extraction_counts["decode_failed"] += 1
            continue
        extraction_counts["readable"] += 1
        path = probe_dir / f"S{source_ordinal:04d}-P{probe_index:02d}.jpg"
        if not cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95]):
            extraction_counts["imwrite_failed"] += 1
            continue
        frames.append(frame)
        probe_rows.append(
            {
                "probe_index": probe_index,
                "frame_index": frame_index,
                "local_name": path.name,
            }
        )
    return frames, probe_rows, extraction_counts


def aggregate_probe_extraction_counts(
    sources: Iterable[Mapping[str, object]],
) -> dict[str, dict[str, int]]:
    """Aggregate private per-source extraction provenance without identifiers."""
    fields = ("requested", "readable", "decode_failed", "imwrite_failed")
    totals = {
        bucket: {field: 0 for field in fields}
        for bucket in ("hard_positive", "hard_negative")
    }
    for source in sources:
        bucket = str(source.get("probe_bucket", ""))
        if bucket not in totals:
            continue
        counts = source.get("probe_extraction", {})
        if not isinstance(counts, Mapping):
            continue
        for field in fields:
            totals[bucket][field] += int(counts.get(field, 0) or 0)
    return totals


def analyze(args: argparse.Namespace) -> None:
    """Run local OpenCV/YOLO inference and create a blinded local CVAT ZIP."""
    _validate_approved_output(args.output)
    output = args.output.resolve()
    validate_fresh_output(output, phase="analyze")
    import cv2
    from ultralytics import YOLO

    payload = json.loads(
        (output / "probe-sources.private.json").read_text(encoding="utf-8")
    )
    if payload.get("status") != "V22_INVENTORY_SELECTION_READY":
        raise SystemExit("analyze requires a ready metadata-only inventory selection")
    probe_dir = output / "probe-frames"
    review_dir = output / "review-frames"
    probe_dir.mkdir(exist_ok=True)
    review_dir.mkdir(exist_ok=True)
    probe_dir.chmod(0o700)
    review_dir.chmod(0o700)

    accepted_image_sha256 = _load_existing_image_hashes(args.existing_images)
    checkpoint_sha256 = _sha256_file(args.model)
    model = YOLO(str(args.model))
    analyzed: list[dict[str, object]] = []
    probe_paths: dict[str, dict[int, Path]] = {}
    probes_by_source: dict[str, list[dict[str, object]]] = {}
    for ordinal, source in enumerate(payload["sources"], start=1):
        source_ref = str(source["source_ref"])
        capture = cv2.VideoCapture(str(output / "source-clips" / source["local_name"]))
        try:
            frames, probe_rows, extraction_counts = _extract_probes(
                capture,
                cv2=cv2,
                source_ordinal=ordinal,
                probe_dir=probe_dir,
                count=args.probe_frames_per_source,
            )
        finally:
            capture.release()
        if frames:
            predictions = model.predict(
                source=frames,
                imgsz=args.imgsz,
                conf=args.inference_conf,
                device=args.device,
                verbose=False,
            )
            for probe_row, prediction in zip(probe_rows, predictions, strict=True):
                confidences = (
                    prediction.boxes.conf.tolist()
                    if prediction.boxes is not None
                    else []
                )
                probe_row["detection_count"] = len(confidences)
                probe_row["max_conf"] = max(confidences, default=0.0)
        probes_by_source[source_ref] = probe_rows
        probe_paths[source_ref] = {
            int(row["probe_index"]): probe_dir / str(row["local_name"])
            for row in probe_rows
        }
        analyzed.append(
            {
                **source,
                "yolo_max_conf": max(
                    (float(row["max_conf"]) for row in probe_rows), default=0.0
                ),
                "yolo_detection_count": max(
                    (int(row["detection_count"]) for row in probe_rows), default=0
                ),
                "probe_extraction": extraction_counts,
                "probes": [
                    {
                        key: row[key]
                        for key in ("probe_index", "frame_index", "detection_count", "max_conf")
                    }
                    for row in probe_rows
                ],
            }
        )

    probe_extraction_counts = aggregate_probe_extraction_counts(analyzed)
    analyzed_ledger_path = output / "analyzed-sources.private.json"
    _write_private_json(
        analyzed_ledger_path,
        {
            "schema": "yolo26n-v22-analyzed-sources-v1",
            "imgsz": args.imgsz,
            "inference_conf": args.inference_conf,
            "model": args.model.name,
            "probe_frames_per_source": args.probe_frames_per_source,
            "db_write_count": 0,
            "r2_write_count": 0,
            "probe_extraction_counts": probe_extraction_counts,
            "sources": analyzed,
        },
    )
    analyzed_ledger_sha256 = _sha256_file(analyzed_ledger_path)
    policy = V22CandidatePolicy(
        frame_quotas={
            "hard_positive": args.hard_positive_frames,
            "hard_negative": args.hard_negative_frames,
        },
        frames_per_source=args.review_frames_per_source,
        max_frames_per_camera_night=args.max_frames_per_night,
        seed=args.seed,
    )
    selected = select_review_source_pool(analyzed, policy=policy)
    source_dhashes: dict[str, set[int]] = {}

    def inspect_probe(
        source_ref: str, probe_index: int
    ) -> tuple[str, Mapping[str, object]]:
        path = probe_paths.get(source_ref, {}).get(probe_index)
        if path is None:
            return "unreadable", {}
        image = cv2.imread(str(path))
        if image is None:
            return "unreadable", {}
        image_sha256 = _sha256_file(path)
        if image_sha256 in accepted_image_sha256:
            return "exact_duplicate", {}
        digest = _dhash(image, cv2)
        current_source_hashes = source_dhashes.setdefault(source_ref, set())
        if _near_duplicate(digest, current_source_hashes):
            return "dhash_duplicate", {}
        accepted_image_sha256.add(image_sha256)
        current_source_hashes.add(digest)
        source_probe = next(
            row
            for row in probes_by_source[source_ref]
            if int(row["probe_index"]) == probe_index
        )
        return "accepted", {
            "frame_index": int(source_probe["frame_index"]),
            "image_sha256": image_sha256,
        }

    private_frames, materialization_summary = materialize_accepted_review_rows(
        selected,
        probes_by_source,
        inspect_probe=inspect_probe,
        frame_quotas={
            "hard_positive": args.hard_positive_frames,
            "hard_negative": args.hard_negative_frames,
        },
        frames_per_source=args.review_frames_per_source,
        max_frames_per_camera_night=args.max_frames_per_night,
        probe_extraction_counts=probe_extraction_counts,
    )

    review_rows: list[dict[str, str]] = []
    for sequence, frame in enumerate(private_frames, start=1):
        source_ref = str(frame["source_ref"])
        path = probe_paths[source_ref][int(frame["probe_index"])]
        filename = f"V{sequence:04d}.jpg"
        shutil.copy2(path, review_dir / filename)
        frame["sequence"] = f"V{sequence:04d}"
        review_rows.append(
            {
                "sequence": f"V{sequence:04d}",
                "filename": filename,
                "instruction": "게코가 보이면 각 개체의 보이는 몸 영역에 bbox",
            }
        )

    with (output / "review-index.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["sequence", "filename", "instruction"]
        )
        writer.writeheader()
        writer.writerows(review_rows)
    manifest = build_candidate_manifest(
        seed=args.seed,
        model_name=args.model.name,
        checkpoint_sha256=checkpoint_sha256,
        analyzed_ledger_sha256=analyzed_ledger_sha256,
        review_frames=private_frames,
        inventory_summary=payload,
        materialization_summary=materialization_summary,
    )
    _write_private_json(output / "candidate-manifest.private.json", manifest)
    with zipfile.ZipFile(
        output / "cvat-upload.zip", "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for path in sorted(review_dir.glob("*.jpg")):
            archive.write(path, arcname=path.name)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "selected_sources": len(selected),
                "review_frames": len(private_frames),
            },
            sort_keys=True,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("inventory", "analyze"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", default=APPROVED_SEED)
    parser.add_argument("--cutoff", default=APPROVED_CUTOFF)
    parser.add_argument("--reporter-repo", type=Path)
    parser.add_argument("--existing-source-json", type=Path, nargs="+", default=[])
    parser.add_argument("--existing-selection", type=Path)
    parser.add_argument("--existing-review-csv", type=Path)
    parser.add_argument("--existing-images", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument(
        "--inventory-max-sources",
        type=int,
        default=HARD_POSITIVE_PROBE_SOURCES + HARD_NEGATIVE_PROBE_SOURCES,
    )
    parser.add_argument(
        "--probe-hard-positive-sources", type=int, default=HARD_POSITIVE_PROBE_SOURCES
    )
    parser.add_argument(
        "--probe-hard-negative-sources", type=int, default=HARD_NEGATIVE_PROBE_SOURCES
    )
    parser.add_argument(
        "--probe-max-sources-per-night",
        type=int,
        default=MAX_PROBE_SOURCES_PER_CAMERA_NIGHT,
    )
    parser.add_argument("--probe-frames-per-source", type=int, default=PROBE_FRAME_COUNT)
    parser.add_argument(
        "--review-frames-per-source", type=int, default=REVIEW_FRAMES_PER_SOURCE
    )
    parser.add_argument("--hard-positive-frames", type=int, default=HARD_POSITIVE_REVIEW_FRAMES)
    parser.add_argument("--hard-negative-frames", type=int, default=HARD_NEGATIVE_REVIEW_FRAMES)
    parser.add_argument(
        "--max-frames-per-night", type=int, default=MAX_REVIEW_FRAMES_PER_CAMERA_NIGHT
    )
    parser.add_argument("--imgsz", type=int, default=APPROVED_IMGSZ)
    parser.add_argument("--inference-conf", type=float, default=APPROVED_INFERENCE_CONF)
    parser.add_argument("--device", default="mps")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        validate_cli_contract(args)
    except ValueError as exc:
        parser.error(str(exc))
    if args.phase == "inventory":
        if args.reporter_repo is None or not (
            args.existing_source_json or args.existing_selection is not None
        ):
            raise SystemExit(
                "inventory requires --reporter-repo and an existing source selection"
            )
        inventory(args)
    else:
        if args.existing_images is None or args.model is None:
            raise SystemExit("analyze requires --existing-images and --model")
        analyze(args)


if __name__ == "__main__":
    main()

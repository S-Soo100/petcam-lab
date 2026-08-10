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
from typing import Iterable, Mapping, Sequence

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
HARD_POSITIVE_PROBE_SOURCES = 220
HARD_NEGATIVE_PROBE_SOURCES = 100
MAX_PROBE_FRAMES_PER_CAMERA_NIGHT = 24


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


def build_candidate_manifest(
    *,
    seed: str,
    model_name: str,
    checkpoint_sha256: str,
    analyzed_ledger_sha256: str,
    review_frames: Sequence[Mapping[str, object]],
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
        else "SHORTAGE"
    )
    return {
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
            if key == "source_ref" and value:
                refs.add(str(value))
            else:
                refs |= _extract_source_refs(value)
        return refs
    if isinstance(payload, list):
        return set().union(*(_extract_source_refs(item) for item in payload))
    return set()


def _load_existing_source_refs(paths: Sequence[Path]) -> set[str]:
    refs: set[str] = set()
    for path in paths:
        refs |= _extract_source_refs(json.loads(path.read_text(encoding="utf-8")))
    return refs


def load_existing_review_source_refs(path: Path) -> set[str]:
    """Read private review provenance; public CSVs without source_ref contribute zero."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            raise ValueError(f"review CSV has no header: {path}")
        if fieldnames.count("source_ref") > 1:
            raise ValueError(f"review CSV has duplicate source_ref columns: {path}")
        if "source_ref" not in fieldnames:
            return set()
        refs: set[str] = set()
        for row in reader:
            if None in row:
                raise ValueError(f"review CSV has an over-wide row: {path}")
            source_ref = str(row.get("source_ref") or "").strip()
            if not source_ref:
                raise ValueError(f"review CSV has an empty source_ref: {path}")
            refs.add(source_ref)
    return refs


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

    selected: list[dict[str, object]] = []
    night_probe_frames: Counter[str] = Counter()
    for bucket, quota in quotas.items():
        ranked = sorted(
            grouped[bucket],
            key=lambda row: _rank_inventory_source(
                args.seed, bucket, str(row["source_ref"])
            ),
        )
        selected_for_bucket = 0
        for source in ranked:
            if selected_for_bucket >= quota:
                break
            camera_night = str(source["camera_night"])
            if (
                night_probe_frames[camera_night] + args.probe_frames_per_source
                > args.probe_max_frames_per_night
            ):
                continue
            selected.append({**source, "probe_bucket": bucket})
            night_probe_frames[camera_night] += args.probe_frames_per_source
            selected_for_bucket += 1
    return selected[: args.inventory_max_sources]


def validate_cli_contract(args: argparse.Namespace) -> None:
    """Task 4 may only run the approved, bounded v2.2 data contract."""
    if args.phase == "inventory":
        expected = {
            "probe_hard_positive_sources": HARD_POSITIVE_PROBE_SOURCES,
            "probe_hard_negative_sources": HARD_NEGATIVE_PROBE_SOURCES,
            "probe_max_frames_per_night": MAX_PROBE_FRAMES_PER_CAMERA_NIGHT,
            "probe_frames_per_source": PROBE_FRAME_COUNT,
            "inventory_max_sources": (
                HARD_POSITIVE_PROBE_SOURCES + HARD_NEGATIVE_PROBE_SOURCES
            ),
        }
    else:
        expected = {
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
    if mismatched:
        raise ValueError("unsafe v2.2 CLI contract: " + ", ".join(mismatched))


def inventory(args: argparse.Namespace) -> None:
    """Read production metadata and download a bounded local probe corpus via R2 GET."""
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
    existing_refs = _load_existing_source_refs(existing_source_paths)
    if args.existing_review_csv is not None:
        existing_refs |= load_existing_review_source_refs(args.existing_review_csv)
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
    downloaded: list[dict[str, object]] = []
    missing = 0
    for ordinal, source in enumerate(ranked, start=1):
        destination = clips_dir / f"S{ordinal:04d}.mp4"
        try:
            r2.download_clip(str(source["r2_key"]), destination)
        except r2.R2SourceMissing:
            missing += 1
            continue
        downloaded.append({**source, "local_name": destination.name})

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
            "probe_max_frames_per_night": args.probe_max_frames_per_night,
            "probe_bucket_counts": dict(
                Counter(str(row["probe_bucket"]) for row in ranked)
            ),
            "eligible_clip_count": len(private_by_ref),
            "selected_probe_source_count": len(ranked),
            "downloaded_source_count": len(downloaded),
            "missing_source_count": missing,
            "sources": downloaded,
        },
    )
    print(
        json.dumps(
            {
                "status": "PROBE_SOURCES_READY",
                "eligible": len(private_by_ref),
                "downloaded": len(downloaded),
                "missing": missing,
            },
            sort_keys=True,
        )
    )


def _extract_probes(
    capture, *, cv2, source_ordinal: int, probe_dir: Path, count: int
) -> tuple[list, list[dict[str, object]]]:
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    frames: list = []
    probe_rows: list[dict[str, object]] = []
    for probe_index, frame_index in enumerate(
        choose_probe_indices(total_frames, count)
    ):
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok or frame is None:
            continue
        path = probe_dir / f"S{source_ordinal:04d}-P{probe_index:02d}.jpg"
        if not cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95]):
            continue
        frames.append(frame)
        probe_rows.append(
            {
                "probe_index": probe_index,
                "frame_index": frame_index,
                "local_name": path.name,
            }
        )
    return frames, probe_rows


def analyze(args: argparse.Namespace) -> None:
    """Run local OpenCV/YOLO inference and create a blinded local CVAT ZIP."""
    import cv2
    from ultralytics import YOLO

    output = args.output.resolve()
    payload = json.loads(
        (output / "probe-sources.private.json").read_text(encoding="utf-8")
    )
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
            frames, probe_rows = _extract_probes(
                capture,
                cv2=cv2,
                source_ordinal=ordinal,
                probe_dir=probe_dir,
                count=args.probe_frames_per_source,
            )
        finally:
            capture.release()
        if not frames:
            continue
        predictions = model.predict(
            source=frames,
            imgsz=args.imgsz,
            conf=args.inference_conf,
            device=args.device,
            verbose=False,
        )
        for probe_row, prediction in zip(probe_rows, predictions, strict=True):
            confidences = (
                prediction.boxes.conf.tolist() if prediction.boxes is not None else []
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
                "probes": [
                    {
                        key: row[key]
                        for key in ("probe_index", "frame_index", "detection_count", "max_conf")
                    }
                    for row in probe_rows
                ],
            }
        )

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
    selected = select_v22_candidate_sources(analyzed, policy=policy)
    desired_rows = materialize_review_rows(
        selected,
        probes_by_source,
        frames_per_source=args.review_frames_per_source,
        max_frames_per_camera_night=args.max_frames_per_night,
    )

    private_frames: list[dict[str, object]] = []
    review_rows: list[dict[str, str]] = []
    source_dhashes: dict[str, set[int]] = {}
    sequence = 1
    for desired in desired_rows:
        source_ref = str(desired["source_ref"])
        path = probe_paths[source_ref].get(int(desired["probe_index"]))
        if path is None:
            continue
        image = cv2.imread(str(path))
        if image is None:
            continue
        digest = _dhash(image, cv2)
        image_sha256 = _sha256_file(path)
        current_source_hashes = source_dhashes.setdefault(source_ref, set())
        if not reserve_review_image(
            image_sha256=image_sha256,
            accepted_image_sha256=accepted_image_sha256,
            dhash=digest,
            source_dhashes=current_source_hashes,
        ):
            continue
        filename = f"V{sequence:04d}.jpg"
        shutil.copy2(path, review_dir / filename)
        source_probe = next(
            row
            for row in probes_by_source[source_ref]
            if int(row["probe_index"]) == int(desired["probe_index"])
        )
        private_frames.append(
            {
                "sequence": f"V{sequence:04d}",
                **desired,
                "frame_index": int(source_probe["frame_index"]),
                "image_sha256": image_sha256,
            }
        )
        review_rows.append(
            {
                "sequence": f"V{sequence:04d}",
                "filename": filename,
                "instruction": "게코가 보이면 각 개체의 보이는 몸 영역에 bbox",
            }
        )
        sequence += 1

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
    parser.add_argument("--seed", default="yolo26n-v22-owner-20260810")
    parser.add_argument("--cutoff", default="2026-07-15T00:00:00+00:00")
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
        "--probe-max-frames-per-night", type=int, default=MAX_PROBE_FRAMES_PER_CAMERA_NIGHT
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
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--inference-conf", type=float, default=0.001)
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

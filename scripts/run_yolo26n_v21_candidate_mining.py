from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

from scripts.build_yolo26n_v21_candidate_queue import (
    CandidatePolicy,
    select_candidate_sources,
)


def choose_probe_indices(total_frames: int, count: int) -> list[int]:
    if total_frames <= 0 or count <= 0:
        return []
    if total_frames <= count:
        return list(range(total_frames))
    if count == 1:
        return [total_frames // 2]
    indices = {
        round((total_frames - 1) * (0.1 + 0.8 * position / (count - 1)))
        for position in range(count)
    }
    return sorted(indices)


def choose_review_probe_indices(
    probes: Iterable[Mapping[str, object]],
    bucket: str,
    *,
    count: int,
) -> list[int]:
    rows = list(probes)
    if bucket == "multi_gecko":
        ranked = sorted(
            rows,
            key=lambda row: (
                -int(row.get("detection_count", 0)),
                -float(row.get("max_conf", 0.0)),
                int(row["probe_index"]),
            ),
        )
    elif bucket == "hard_negative":
        ranked = sorted(
            rows,
            key=lambda row: (
                -float(row.get("max_conf", 0.0)),
                -int(row.get("detection_count", 0)),
                int(row["probe_index"]),
            ),
        )
    elif bucket == "hard_positive":
        ranked = sorted(
            rows,
            key=lambda row: (
                float(row.get("max_conf", 0.0)),
                int(row["probe_index"]),
            ),
        )
    else:
        ranked = sorted(rows, key=lambda row: int(row["probe_index"]))
    return [int(row["probe_index"]) for row in ranked[:count]]


def extract_source_refs(payload: Mapping[str, object]) -> set[str]:
    refs: set[str] = set()
    for value in payload.values():
        if not isinstance(value, list):
            continue
        for row in value:
            if isinstance(row, dict) and row.get("source_ref"):
                refs.add(str(row["source_ref"]))
    return refs


def _write_private_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    path.chmod(0o600)


def _paged(query_factory, page_size: int = 1000) -> list[dict]:
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
    kst = parsed.astimezone(timezone(timedelta(hours=9))) - timedelta(hours=12)
    raw = f"{camera_id}:{kst.date().isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _load_existing_refs(selection_path: Path, review_csv: Path) -> set[str]:
    payload = json.loads(selection_path.read_text(encoding="utf-8"))
    refs = extract_source_refs(payload)
    with review_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            for key in ("source_ref", "source_group", "media_ref"):
                value = str(row.get(key, "")).strip()
                if value:
                    refs.add(value)
    return refs


def inventory(args: argparse.Namespace) -> None:
    reporter_repo = args.reporter_repo.resolve()
    sys.path.insert(0, str(reporter_repo))
    from supabase import create_client

    from reporter import config, r2

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o700)
    clips_dir = output / "source-clips"
    clips_dir.mkdir(exist_ok=True)
    clips_dir.chmod(0o700)

    excluded = _load_existing_refs(args.existing_selection, args.existing_review_csv)
    sb = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    clip_rows = _paged(
        lambda: sb.table("motion_clips")
        .select("id,camera_id,started_at,duration_sec,r2_key,clip_purpose")
        .gte("started_at", args.cutoff)
        .eq("clip_purpose", "production")
        .not_.is_("r2_key", "null")
        .order("started_at")
    )
    run_rows = _paged(
        lambda: sb.table("gme_runs")
        .select(
            "clip_id,created_at,duration_sec,visible_sec,unknown_sec,"
            "max_simultaneous_geckos,status"
        )
        .eq("status", "ok")
        .order("created_at", desc=True)
    )
    latest_run: dict[str, dict] = {}
    for row in run_rows:
        latest_run.setdefault(str(row["clip_id"]), row)

    private_by_ref: dict[str, dict] = {}
    safe_rows: list[dict[str, object]] = []
    for clip in clip_rows:
        source_ref = str(clip["id"])
        if source_ref in excluded:
            continue
        run = latest_run.get(source_ref)
        if not run:
            continue
        duration = float(run.get("duration_sec") or clip.get("duration_sec") or 0.0)
        visible = float(run.get("visible_sec") or 0.0)
        unknown = float(run.get("unknown_sec") or 0.0)
        camera_night = _camera_night(str(clip["camera_id"]), str(clip["started_at"]))
        safe = {
            "source_ref": source_ref,
            "camera_night": camera_night,
            "yolo_max_conf": 0.0,
            "yolo_detection_count": 0,
            "gme_visible_ratio": visible / duration if duration > 0 else 0.0,
            "gme_unknown_ratio": unknown / duration if duration > 0 else 1.0,
            "gme_max_geckos": int(run.get("max_simultaneous_geckos") or 0),
        }
        safe_rows.append(safe)
        private_by_ref[source_ref] = {
            **safe,
            "r2_key": str(clip["r2_key"]),
            "duration_sec": duration,
        }

    probe_policy = CandidatePolicy(
        bucket_quotas={
            "multi_gecko": args.probe_multi_sources,
            "hard_negative": 0,
            "hard_positive": args.probe_visible_sources,
            "coverage": args.probe_coverage_sources,
        },
        max_sources_per_camera_night=args.probe_max_per_night,
        seed=args.seed,
    )
    selected = select_candidate_sources(
        safe_rows,
        policy=probe_policy,
        excluded_source_refs=excluded,
    )

    downloaded: list[dict] = []
    missing = 0
    for ordinal, safe in enumerate(selected, start=1):
        source_ref = str(safe["source_ref"])
        private = private_by_ref[source_ref]
        destination = clips_dir / f"S{ordinal:04d}.mp4"
        try:
            r2.download_clip(str(private["r2_key"]), destination)
        except r2.R2SourceMissing:
            missing += 1
            continue
        downloaded.append(
            {
                **private,
                "local_name": destination.name,
                "probe_bucket": safe["candidate_bucket"],
            }
        )

    _write_private_json(
        output / "probe-sources.private.json",
        {
            "schema": "yolo26n-v21-probe-sources-v1",
            "cutoff": args.cutoff,
            "seed": args.seed,
            "db_r2_write_count": 0,
            "excluded_source_count": len(excluded),
            "eligible_joined_count": len(safe_rows),
            "selected_source_count": len(selected),
            "downloaded_source_count": len(downloaded),
            "missing_source_count": missing,
            "sources": downloaded,
        },
    )
    print(
        json.dumps(
            {
                "status": "PROBE_SOURCES_READY",
                "eligible": len(safe_rows),
                "selected": len(selected),
                "downloaded": len(downloaded),
                "missing": missing,
            },
            sort_keys=True,
        )
    )


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
    digest: int,
    existing_hashes: set[int],
    source_hashes: set[int],
) -> bool:
    return digest in existing_hashes or _near_duplicate(digest, source_hashes)


def analyze(args: argparse.Namespace) -> None:
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

    existing_hashes: set[int] = set()
    for path in sorted(args.existing_images.glob("*")):
        image = cv2.imread(str(path))
        if image is not None:
            existing_hashes.add(_dhash(image, cv2))

    model = YOLO(str(args.model))
    analyzed_sources: list[dict] = []
    probe_paths_by_source: dict[str, list[Path]] = {}
    for source_ordinal, source in enumerate(payload["sources"], start=1):
        clip_path = output / "source-clips" / source["local_name"]
        capture = cv2.VideoCapture(str(clip_path))
        try:
            total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            indices = choose_probe_indices(total_frames, args.probe_frames_per_source)
            frames = []
            paths = []
            for probe_index, frame_index in enumerate(indices):
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = capture.read()
                if not ok or frame is None:
                    continue
                path = probe_dir / f"S{source_ordinal:04d}-P{probe_index:02d}.jpg"
                cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                frames.append(frame)
                paths.append(path)
        finally:
            capture.release()
        if not frames:
            continue
        results = model.predict(
            source=frames,
            imgsz=args.imgsz,
            conf=args.inference_conf,
            device="mps",
            verbose=False,
        )
        probes = []
        max_conf = 0.0
        max_detection_count = 0
        for probe_index, result in enumerate(results):
            confidences = result.boxes.conf.tolist() if result.boxes is not None else []
            detection_count = len(confidences)
            confidence = max(confidences, default=0.0)
            probes.append(
                {
                    "probe_index": probe_index,
                    "detection_count": detection_count,
                    "max_conf": confidence,
                }
            )
            max_conf = max(max_conf, confidence)
            max_detection_count = max(max_detection_count, detection_count)
        analyzed_sources.append(
            {
                **source,
                "yolo_max_conf": max_conf,
                "yolo_detection_count": max_detection_count,
                "probes": probes,
            }
        )
        probe_paths_by_source[str(source["source_ref"])] = paths

    _write_private_json(
        output / "analyzed-sources.private.json",
        {
            "schema": "yolo26n-v21-analyzed-sources-v1",
            "imgsz": args.imgsz,
            "inference_conf": args.inference_conf,
            "sources": analyzed_sources,
        },
    )

    final_policy = CandidatePolicy(
        bucket_quotas={
            "multi_gecko": args.final_multi_sources,
            "hard_negative": args.final_hard_negative_sources,
            "hard_positive": args.final_hard_positive_sources,
            "coverage": args.final_coverage_sources,
        },
        max_sources_per_camera_night=args.final_max_per_night,
        seed=args.seed,
    )
    selected = select_candidate_sources(analyzed_sources, policy=final_policy)
    analyzed_by_ref = {str(row["source_ref"]): row for row in analyzed_sources}
    private_frames: list[dict] = []
    public_rows: list[dict] = []
    sequence = 1
    for selected_source in selected:
        source_ref = str(selected_source["source_ref"])
        source = analyzed_by_ref[source_ref]
        paths = probe_paths_by_source[source_ref]
        ranked = choose_review_probe_indices(
            source["probes"],
            str(selected_source["candidate_bucket"]),
            count=len(source["probes"]),
        )
        accepted_for_source = 0
        source_hashes: set[int] = set()
        for probe_index in ranked:
            if probe_index >= len(paths):
                continue
            image = cv2.imread(str(paths[probe_index]))
            if image is None:
                continue
            digest = _dhash(image, cv2)
            if review_frame_is_duplicate(digest, existing_hashes, source_hashes):
                continue
            filename = f"V{sequence:04d}.jpg"
            shutil.copy2(paths[probe_index], review_dir / filename)
            source_hashes.add(digest)
            public_rows.append(
                {
                    "sequence": f"V{sequence:04d}",
                    "filename": filename,
                    "instruction": "게코가 보이면 각 개체의 보이는 몸 영역에 bbox",
                }
            )
            private_frames.append(
                {
                    "sequence": f"V{sequence:04d}",
                    "source_ref": source_ref,
                    "camera_night": source["camera_night"],
                    "candidate_bucket": selected_source["candidate_bucket"],
                    "probe_index": probe_index,
                }
            )
            sequence += 1
            accepted_for_source += 1
            if accepted_for_source >= args.review_frames_per_source:
                break

    with (output / "review-index.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["sequence", "filename", "instruction"],
        )
        writer.writeheader()
        writer.writerows(public_rows)
    _write_private_json(
        output / "candidate-manifest.private.json",
        {
            "schema": "yolo26n-v21-candidate-queue-v1",
            "seed": args.seed,
            "model": args.model.name,
            "imgsz": args.imgsz,
            "prediction_boxes_exposed_to_reviewer": False,
            "human_review_required": True,
            "db_r2_write_count": 0,
            "selected_source_count": len(selected),
            "review_frame_count": len(private_frames),
            "frames": private_frames,
        },
    )
    with zipfile.ZipFile(
        output / "yolo26n-v21-review-frames.zip",
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for path in sorted(review_dir.glob("*.jpg")):
            archive.write(path, arcname=path.name)
    bucket_counts: dict[str, int] = {}
    for row in private_frames:
        bucket = str(row["candidate_bucket"])
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
    summary = (
        "# YOLO26n v2.1 사람 검수 후보\n\n"
        f"- source: {len(selected)}\n"
        f"- frame: {len(private_frames)}\n"
        f"- bucket frame counts: {json.dumps(bucket_counts, sort_keys=True)}\n"
        "- reviewer prediction overlay: 없음\n"
        "- DB/R2 write: 0\n"
        "- 다음 단계: Owner CVAT bbox 검수\n"
    )
    (output / "SUMMARY.md").write_text(summary, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "CANDIDATE_QUEUE_READY",
                "sources": len(selected),
                "frames": len(private_frames),
                "bucket_frames": bucket_counts,
            },
            sort_keys=True,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("inventory", "analyze"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", default="yolo26n-v21-owner-20260810")
    parser.add_argument("--cutoff", default="2026-07-15T00:00:00+00:00")
    parser.add_argument("--reporter-repo", type=Path)
    parser.add_argument("--existing-selection", type=Path)
    parser.add_argument("--existing-review-csv", type=Path)
    parser.add_argument("--existing-images", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--probe-multi-sources", type=int, default=40)
    parser.add_argument("--probe-visible-sources", type=int, default=80)
    parser.add_argument("--probe-coverage-sources", type=int, default=120)
    parser.add_argument("--probe-max-per-night", type=int, default=10)
    parser.add_argument("--probe-frames-per-source", type=int, default=12)
    parser.add_argument("--final-multi-sources", type=int, default=30)
    parser.add_argument("--final-hard-negative-sources", type=int, default=30)
    parser.add_argument("--final-hard-positive-sources", type=int, default=30)
    parser.add_argument("--final-coverage-sources", type=int, default=70)
    parser.add_argument("--final-max-per-night", type=int, default=5)
    parser.add_argument("--review-frames-per-source", type=int, default=2)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--inference-conf", type=float, default=0.001)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.phase == "inventory":
        required = (
            args.reporter_repo,
            args.existing_selection,
            args.existing_review_csv,
        )
        if any(value is None for value in required):
            raise SystemExit("inventory paths are required")
        inventory(args)
    else:
        required = (args.existing_images, args.model)
        if any(value is None for value in required):
            raise SystemExit("analyze paths are required")
        analyze(args)


if __name__ == "__main__":
    main()

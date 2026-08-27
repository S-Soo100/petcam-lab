"""Join immutable v2.5 GME track artifacts onto the private 2fps dense ledger."""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any


_DENSE_CLIP_FILES = frozenset({"ledger.jsonl", "completion.private.json"})


def enrich_dense_rows(
    dense_rows: list[dict[str, object]],
    track_points: list[dict[str, object]],
    *,
    tolerance_ms: int = 60,
) -> list[dict[str, object]]:
    """Attach nearest per-track v2.5 observations without inventing negatives."""

    if type(tolerance_ms) is not int or tolerance_ms < 0:
        raise ValueError("tolerance must be a non-negative integer")
    validated_points: list[tuple[float, dict[str, object]]] = []
    for point in track_points:
        timestamp = point.get("timestamp_sec")
        track_id = point.get("track_id")
        confidence = point.get("confidence")
        bbox = point.get("bbox_norm")
        provenance = point.get("provenance")
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, (int, float))
            or not math.isfinite(float(timestamp))
            or float(timestamp) < 0
            or not isinstance(track_id, str)
            or not track_id
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0 <= float(confidence) <= 1
            or not isinstance(bbox, list)
            or len(bbox) != 4
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0 <= float(value) <= 1
                for value in bbox
            )
            or not isinstance(provenance, str)
            or not provenance
        ):
            raise ValueError("track point is malformed")
        validated_points.append((float(timestamp) * 1000.0, point))
    validated_points.sort(key=lambda item: (item[0], str(item[1]["track_id"])))
    timestamps = [item[0] for item in validated_points]

    enriched: list[dict[str, object]] = []
    for row in dense_rows:
        timestamp_ms = row.get("timestamp_ms")
        if type(timestamp_ms) is not int or timestamp_ms < 0:
            raise ValueError("dense row timestamp is invalid")
        left = bisect_left(timestamps, timestamp_ms - tolerance_ms)
        right = bisect_right(timestamps, timestamp_ms + tolerance_ms)
        nearest_by_track: dict[str, tuple[float, float, dict[str, object]]] = {}
        for point_timestamp, point in validated_points[left:right]:
            distance = abs(point_timestamp - timestamp_ms)
            track_id = str(point["track_id"])
            confidence = float(point["confidence"])
            rank = (distance, -confidence)
            existing = nearest_by_track.get(track_id)
            if existing is None or rank < (existing[0], existing[1]):
                nearest_by_track[track_id] = (distance, -confidence, point)
        detections = [
            {
                "track_id": track_id,
                "confidence": float(payload[2]["confidence"]),
                "bbox_norm": [float(value) for value in payload[2]["bbox_norm"]],
                "provenance": payload[2]["provenance"],
            }
            for track_id, payload in sorted(nearest_by_track.items())
        ]
        output = dict(row)
        output.update(
            {
                "detector_status": "joined-v2.5-gme-artifact",
                "detection_count": len(detections),
                "max_confidence": max(
                    (float(detection["confidence"]) for detection in detections),
                    default=0.0,
                ),
                "detections": detections,
            }
        )
        enriched.append(output)
    return enriched


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_validated_dense_inputs(
    dense_root: Path,
) -> tuple[dict[str, object], list[tuple[dict[str, object], list[dict[str, object]]]]]:
    """Bind the dense final manifest to the exact per-clip ledgers used by join."""

    final_path = dense_root / "completion.private.json"
    dense_final = json.loads(final_path.read_text())
    if dense_final.get("status") != "DENSE_EXTRACTION_COMPLETE":
        raise ValueError("dense completion status is invalid")
    clips = dense_final.get("clips")
    if not isinstance(clips, list):
        raise ValueError("dense completion clips are invalid")
    if dense_final.get("clip_count") != len(clips):
        raise ValueError("dense completion clip count drift")

    expected_private_refs: set[str] = set()
    expected_clip_refs: set[str] = set()
    declared_row_count = 0
    for item in clips:
        if not isinstance(item, dict):
            raise ValueError("dense completion clip is invalid")
        clip_ref = item.get("clip_ref")
        private_ref = item.get("private_ref")
        row_count = item.get("sampled_frame_count")
        if (
            not isinstance(clip_ref, str)
            or not clip_ref
            or clip_ref in expected_clip_refs
            or not isinstance(private_ref, str)
            or not private_ref
            or private_ref in expected_private_refs
            or type(row_count) is not int
            or row_count < 1
        ):
            raise ValueError("dense completion clip identity/count is invalid")
        expected_clip_refs.add(clip_ref)
        expected_private_refs.add(private_ref)
        declared_row_count += row_count
    if dense_final.get("sampled_frame_count") != declared_row_count:
        raise ValueError("dense completion row count drift")

    clips_root = dense_root / "clips"
    if not clips_root.is_dir():
        raise ValueError("dense clip set is missing")
    actual_private_refs = {path.name for path in clips_root.iterdir() if path.is_dir()}
    if actual_private_refs != expected_private_refs or any(
        not path.is_dir() for path in clips_root.iterdir()
    ):
        raise ValueError("dense clip set does not match completion")

    validated: list[tuple[dict[str, object], list[dict[str, object]]]] = []
    for item in clips:
        clip_ref = str(item["clip_ref"])
        private_ref = str(item["private_ref"])
        clip_root = clips_root / private_ref
        if {path.name for path in clip_root.iterdir()} != _DENSE_CLIP_FILES:
            raise ValueError("dense per-clip artifact is partial")
        clip_completion = json.loads(
            (clip_root / "completion.private.json").read_text()
        )
        if clip_completion.get("status") != "DENSE_CLIP_COMPLETE":
            raise ValueError("dense per-clip status is invalid")
        if clip_completion.get("clip_ref") != clip_ref:
            raise ValueError("dense per-clip identity drift")
        if clip_completion.get("sample_fps") != dense_final.get("sample_fps"):
            raise ValueError("dense per-clip sample fps drift")
        if clip_completion.get("source_sha256") != item.get("source_sha256"):
            raise ValueError("dense per-clip source SHA drift")

        ledger_path = clip_root / "ledger.jsonl"
        actual_sha256 = _sha256_file(ledger_path)
        if (
            actual_sha256 != item.get("ledger_sha256")
            or actual_sha256 != clip_completion.get("ledger_sha256")
        ):
            raise ValueError("dense ledger SHA drift")
        dense_rows = [json.loads(line) for line in ledger_path.open(encoding="utf-8")]
        if (
            len(dense_rows) != item.get("sampled_frame_count")
            or len(dense_rows) != clip_completion.get("sampled_frame_count")
        ):
            raise ValueError("dense ledger row count drift")
        if any(row.get("clip_ref") != clip_ref for row in dense_rows):
            raise ValueError("dense ledger clip identity drift")
        validated.append((item, dense_rows))
    return dense_final, validated


def _load_clients(env_file: Path) -> tuple[Any, Any, str]:
    import boto3
    from botocore.config import Config
    from dotenv import load_dotenv
    from supabase import create_client

    load_dotenv(env_file, override=False)
    required = (
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "R2_ENDPOINT",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
    )
    if any(not os.environ.get(name) for name in required):
        raise RuntimeError("required DB/R2 environment is incomplete")
    database = create_client(
        os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    )
    r2 = boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    return database, r2, os.environ["R2_BUCKET"]


def _chunks(values: list[str], size: int = 100) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _artifact_rows(database: Any, clip_ids: list[str], detector_identity: str) -> dict[str, dict[str, object]]:
    rows: list[dict[str, object]] = []
    for chunk in _chunks(clip_ids):
        rows.extend(
            database.table("gme_runs")
            .select(
                "clip_id,detector_identity,permanent_artifact_key,"
                "permanent_artifact_sha256,permanent_artifact_bytes,status"
            )
            .in_("clip_id", chunk)
            .eq("detector_identity", detector_identity)
            .execute()
            .data
        )
    by_clip: dict[str, dict[str, object]] = {}
    for row in rows:
        clip_id = str(row["clip_id"])
        if clip_id in by_clip:
            raise ValueError("duplicate GME artifact lineage")
        by_clip[clip_id] = row
    if set(by_clip) != set(clip_ids):
        raise ValueError("GME artifact lineage does not cover exact dense clip set")
    return by_clip


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dense-root", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--detector-identity", required=True)
    parser.add_argument("--tolerance-ms", type=int, default=60)
    args = parser.parse_args()

    dense_final, dense_inputs = load_validated_dense_inputs(args.dense_root)
    clip_ids = [str(row["clip_ref"]) for row, _dense_rows in dense_inputs]
    database, r2, bucket = _load_clients(args.env_file)
    artifacts = _artifact_rows(database, clip_ids, args.detector_identity)

    clips_root = args.output_root / "clips"
    final_path = args.output_root / "completion.private.json"
    if final_path.exists():
        raise FileExistsError(final_path)
    clips_root.mkdir(parents=True, exist_ok=True)
    final_rows: list[dict[str, object]] = []
    total_detections = 0
    for index, (dense_item, dense_rows) in enumerate(dense_inputs, start=1):
        clip_id = str(dense_item["clip_ref"])
        private_ref = str(dense_item["private_ref"])
        destination = clips_root / private_ref
        if destination.exists():
            raise FileExistsError(destination)
        artifact_row = artifacts[clip_id]
        if artifact_row.get("status") != "ok":
            raise ValueError("GME artifact status is not ok")
        with tempfile.TemporaryDirectory(prefix="yolo-v26-gme-join-") as temp_raw:
            temp = Path(temp_raw)
            artifact_path = temp / "artifact.json.gz"
            r2.download_file(bucket, str(artifact_row["permanent_artifact_key"]), str(artifact_path))
            if artifact_path.stat().st_size != int(artifact_row["permanent_artifact_bytes"]):
                raise ValueError("GME artifact byte drift")
            if _sha256_file(artifact_path) != artifact_row["permanent_artifact_sha256"]:
                raise ValueError("GME artifact SHA drift")
            raw = artifact_path.read_bytes()
            payload = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
            identity = payload.get("artifact_identity", {})
            if identity.get("detector_identity") != args.detector_identity:
                raise ValueError("GME artifact identity drift")
            enriched = enrich_dense_rows(
                dense_rows, payload.get("track_points", []), tolerance_ms=args.tolerance_ms
            )

            staging = temp / "complete"
            staging.mkdir()
            ledger_path = staging / "ledger.jsonl"
            with ledger_path.open("x", encoding="utf-8") as handle:
                for row in enriched:
                    handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            detection_frames = sum(int(row["detection_count"] > 0) for row in enriched)
            completion = {
                "status": "GME_JOIN_COMPLETE",
                "clip_ref": clip_id,
                "private_ref": private_ref,
                "dense_ledger_sha256": dense_item["ledger_sha256"],
                "gme_artifact_sha256": artifact_row["permanent_artifact_sha256"],
                "detector_identity": args.detector_identity,
                "row_count": len(enriched),
                "detection_frame_count": detection_frames,
                "ledger_sha256": _sha256_file(ledger_path),
                "tolerance_ms": args.tolerance_ms,
            }
            with (staging / "completion.private.json").open("x", encoding="utf-8") as handle:
                json.dump(completion, handle, sort_keys=True, indent=2)
                handle.write("\n")
            os.rename(staging, destination)
        total_detections += detection_frames
        final_rows.append(completion)
        if index % 25 == 0 or index == len(clip_ids):
            print(
                json.dumps(
                    {
                        "status": "GME_JOIN_PROGRESS",
                        "completed": index,
                        "expected": len(clip_ids),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    final = {
        "status": "GME_JOIN_COMPLETE",
        "detector_identity": args.detector_identity,
        "dense_completion_sha256": _sha256_file(
            args.dense_root / "completion.private.json"
        ),
        "clip_count": len(final_rows),
        "row_count": sum(int(row["row_count"]) for row in final_rows),
        "detection_frame_count": total_detections,
        "clips": final_rows,
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    with final_path.open("x", encoding="utf-8") as handle:
        json.dump(final, handle, sort_keys=True, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                "status": final["status"],
                "clip_count": final["clip_count"],
                "row_count": final["row_count"],
                "detection_frame_count": final["detection_frame_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

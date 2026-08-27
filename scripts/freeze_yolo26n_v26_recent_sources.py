"""Freeze the recent YOLO v2.6 source window into one private no-overwrite manifest."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_APPROVED_GME_SUCCESS_STATUSES = frozenset({"succeeded"})


@dataclass(frozen=True, slots=True)
class SourceFreezeContract:
    expected_clip_count: int
    expected_camera_count: int
    expected_detector_identity: str
    expected_success_status: str = "succeeded"
    expected_available_count: int | None = None
    allowed_missing_below_sec: float | None = None

    def validate(self) -> "SourceFreezeContract":
        if type(self.expected_clip_count) is not int or self.expected_clip_count < 1:
            raise ValueError("expected clip count must be positive")
        if type(self.expected_camera_count) is not int or self.expected_camera_count < 1:
            raise ValueError("expected camera count must be positive")
        if _SHA256.fullmatch(self.expected_detector_identity) is None:
            raise ValueError("expected detector identity is invalid")
        if self.expected_success_status not in _APPROVED_GME_SUCCESS_STATUSES:
            raise ValueError("expected GME success status is not approved")
        if (
            self.expected_available_count is not None
            and (
                type(self.expected_available_count) is not int
                or not 0 <= self.expected_available_count <= self.expected_clip_count
            )
        ):
            raise ValueError("expected available count is invalid")
        if self.allowed_missing_below_sec is not None and (
            isinstance(self.allowed_missing_below_sec, bool)
            or not isinstance(self.allowed_missing_below_sec, (int, float))
            or not math.isfinite(float(self.allowed_missing_below_sec))
            or float(self.allowed_missing_below_sec) <= 0
        ):
            raise ValueError("allowed missing duration is invalid")
        return self


def _parse_datetime(value: object, *, name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include timezone")
    return parsed


def build_source_manifest(
    source_rows: list[dict[str, object]],
    gme_rows: list[dict[str, object]],
    *,
    window_start: str,
    window_end: str,
    contract: SourceFreezeContract,
) -> dict[str, object]:
    """Validate exact source/GME lineage and return a deterministic manifest."""

    contract.validate()
    start = _parse_datetime(window_start, name="window_start")
    end = _parse_datetime(window_end, name="window_end")
    if end < start:
        raise ValueError("frozen window is reversed")
    if len(source_rows) != contract.expected_clip_count:
        raise ValueError("clip count does not match frozen contract")

    normalized_sources: list[dict[str, object]] = []
    seen_clips: set[str] = set()
    cameras: set[str] = set()
    available_count = 0
    for row in source_rows:
        clip_id = row.get("id")
        camera_id = row.get("camera_id")
        r2_key = row.get("r2_key")
        started_at = _parse_datetime(row.get("started_at"), name="started_at")
        duration = row.get("duration_sec")
        size_bytes = row.get("size_bytes")
        object_status = row.get("object_status", "available")
        if not isinstance(clip_id, str) or not clip_id or clip_id in seen_clips:
            raise ValueError("source clip identity is missing or duplicated")
        if not isinstance(camera_id, str) or not camera_id:
            raise ValueError("source camera identity is missing")
        if not isinstance(r2_key, str) or not r2_key:
            raise ValueError("source R2 key is missing")
        if not start <= started_at <= end:
            raise ValueError("source is outside frozen window")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(float(duration))
            or float(duration) <= 0
        ):
            raise ValueError("source duration is invalid")
        if object_status not in {"available", "missing"}:
            raise ValueError("source object status is invalid")
        if object_status == "available":
            if type(size_bytes) is not int or size_bytes < 1:
                raise ValueError("source size is invalid")
            available_count += 1
        elif (
            contract.allowed_missing_below_sec is None
            or float(duration) >= float(contract.allowed_missing_below_sec)
        ):
            raise ValueError("missing source is outside approved policy")
        seen_clips.add(clip_id)
        cameras.add(camera_id)
        normalized_sources.append(
            {
                "clip_id": clip_id,
                "camera_id": camera_id,
                "started_at": started_at.isoformat(),
                "duration_sec": round(float(duration), 6),
                "r2_key": r2_key,
                "size_bytes": size_bytes,
                "object_status": object_status,
            }
        )
    if len(cameras) != contract.expected_camera_count:
        raise ValueError("camera count does not match frozen contract")
    expected_available = (
        contract.expected_clip_count
        if contract.expected_available_count is None
        else contract.expected_available_count
    )
    if available_count != expected_available:
        raise ValueError("available source count does not match frozen contract")

    jobs_by_clip: dict[str, dict[str, object]] = {}
    for row in gme_rows:
        clip_id = row.get("clip_id")
        if not isinstance(clip_id, str) or clip_id in jobs_by_clip:
            raise ValueError("GME lineage contains duplicate clip")
        jobs_by_clip[clip_id] = row
    if set(jobs_by_clip) != seen_clips:
        raise ValueError("GME lineage must cover exact source set")
    if any(
        row.get("detector_identity") != contract.expected_detector_identity
        for row in jobs_by_clip.values()
    ):
        raise ValueError("GME detector identity does not match frozen contract")
    if any(
        row.get("status") != contract.expected_success_status
        for row in jobs_by_clip.values()
    ):
        raise ValueError("GME status does not match approved success contract")

    normalized_sources.sort(key=lambda row: (str(row["started_at"]), str(row["clip_id"])))
    statuses = Counter(str(row.get("status")) for row in jobs_by_clip.values())
    for row in normalized_sources:
        job = jobs_by_clip[str(row["clip_id"])]
        row["gme"] = {
            "status": job.get("status"),
            "detector_identity": job.get("detector_identity"),
            "algorithm_version": job.get("algorithm_version"),
            "engine_schema_version": job.get("engine_schema_version"),
        }

    aggregate = {
        "clip_count": len(normalized_sources),
        "accessible_clip_count": available_count,
        "tombstoned_clip_count": len(normalized_sources) - available_count,
        "camera_count": len(cameras),
        "duration_sec": round(sum(float(row["duration_sec"]) for row in normalized_sources), 6),
        "accessible_duration_sec": round(
            sum(
                float(row["duration_sec"])
                for row in normalized_sources
                if row["object_status"] == "available"
            ),
            6,
        ),
        "tombstoned_duration_sec": round(
            sum(
                float(row["duration_sec"])
                for row in normalized_sources
                if row["object_status"] == "missing"
            ),
            6,
        ),
        "source_bytes": sum(
            int(row["size_bytes"])
            for row in normalized_sources
            if row["object_status"] == "available"
        ),
        "gme_status_counts": dict(sorted(statuses.items())),
    }
    lineage_payload = {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "aggregate": aggregate,
        "sources": normalized_sources,
    }
    lineage_sha256 = hashlib.sha256(
        json.dumps(lineage_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {**lineage_payload, "lineage_sha256": lineage_sha256}


def write_manifest_once(destination: Path, manifest: dict[str, object]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def _chunks(values: list[str], size: int = 100) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _load_remote_rows(args: argparse.Namespace) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    from boto3 import client as boto3_client
    from botocore.config import Config
    from botocore.exceptions import ClientError
    from dotenv import load_dotenv
    from supabase import create_client

    load_dotenv(args.env_file, override=False)
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
    sources: list[dict[str, object]] = (
        database.table("motion_clips")
        .select("id,camera_id,started_at,duration_sec,r2_key")
        .gte("started_at", args.start)
        .lte("started_at", args.end)
        .order("started_at")
        .execute()
        .data
    )
    clip_ids = [str(row["id"]) for row in sources]
    jobs: list[dict[str, object]] = []
    for chunk in _chunks(clip_ids):
        jobs.extend(
            database.table("gme_jobs")
            .select(
                "clip_id,status,detector_identity,algorithm_version,engine_schema_version"
            )
            .in_("clip_id", chunk)
            .eq("detector_identity", args.detector_identity)
            .execute()
            .data
        )

    r2 = boto3_client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    bucket = os.environ["R2_BUCKET"]
    for row in sources:
        key = row.get("r2_key")
        if not isinstance(key, str) or not key:
            raise ValueError("source R2 key is missing")
        try:
            row["size_bytes"] = int(
                r2.head_object(Bucket=bucket, Key=key)["ContentLength"]
            )
            row["object_status"] = "available"
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code not in {"404", "NoSuchKey", "NotFound"}:
                raise
            row["size_bytes"] = None
            row["object_status"] = "missing"
    return sources, jobs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--expected-clips", type=int, default=566)
    parser.add_argument("--expected-cameras", type=int, default=2)
    parser.add_argument("--expected-available", type=int)
    parser.add_argument("--allowed-missing-below-sec", type=float)
    parser.add_argument("--detector-identity", required=True)
    parser.add_argument(
        "--expected-gme-success-status",
        choices=sorted(_APPROVED_GME_SUCCESS_STATUSES),
        default="succeeded",
    )
    args = parser.parse_args()

    sources, jobs = _load_remote_rows(args)
    manifest = build_source_manifest(
        sources,
        jobs,
        window_start=args.start,
        window_end=args.end,
        contract=SourceFreezeContract(
            expected_clip_count=args.expected_clips,
            expected_camera_count=args.expected_cameras,
            expected_detector_identity=args.detector_identity,
            expected_success_status=args.expected_gme_success_status,
            expected_available_count=args.expected_available,
            allowed_missing_below_sec=args.allowed_missing_below_sec,
        ),
    )
    write_manifest_once(args.output, manifest)
    aggregate = manifest["aggregate"]
    assert isinstance(aggregate, dict)
    print(
        json.dumps(
            {
                "status": "SOURCE_FREEZE_OK",
                "clip_count": aggregate["clip_count"],
                "camera_count": aggregate["camera_count"],
                "accessible_clip_count": aggregate["accessible_clip_count"],
                "tombstoned_clip_count": aggregate["tombstoned_clip_count"],
                "duration_sec": aggregate["duration_sec"],
                "source_bytes": aggregate["source_bytes"],
                "gme_status_counts": aggregate["gme_status_counts"],
                "lineage_sha256": manifest["lineage_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

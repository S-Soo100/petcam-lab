"""Owner 확인 기반 R2 초기 오염 영상 정리기.

기본값은 dry-run이다. ``--apply`` 없이는 DB/R2를 수정하지 않는다. 공개 출력에는
clip UUID, R2 key, 사용자 UUID, GT 원문을 싣지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


EXPERIMENT_ID = "rba-owner-cleanup-v1"
QUARANTINE_PREFIX = f"research-quarantine/{EXPERIMENT_ID}"
EXCLUDED_PREFIX = f"research-excluded/{EXPERIMENT_ID}"
PRIVATE_DIR = Path.home() / "Library" / "Application Support" / "petcam" / EXPERIMENT_ID
PRIVATE_MANIFEST = PRIVATE_DIR / "manifest.private.json"

_ALLOWED_REASONS = {
    "confirmed_gecko_absent",
    "confirmed_no_gecko_activity",
    "protected_gt",
    "owner_review_pending",
}
_APPROVED_INVALID_STRATA = {
    ("confirmed_gecko_absent", "2026-06-30"),
    ("confirmed_no_gecko_activity", "2026-07-14"),
}


@dataclass(frozen=True)
class ObjectHead:
    content_length: int
    etag: str
    last_modified: datetime
    content_sha256: str | None

    def to_private_dict(self) -> dict[str, object]:
        return {
            "content_length": self.content_length,
            "etag": self.etag,
            "last_modified": self.last_modified.astimezone(UTC).isoformat(),
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True)
class CleanupItem:
    clip_id: str
    camera_id: str
    started_at: str
    seed_reason: str
    has_canonical_gt: bool
    source_r2_key: str
    source_thumbnail_key: str | None
    video_head: ObjectHead | None
    thumbnail_head: ObjectHead | None

    def to_private_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["video_head"] = self.video_head.to_private_dict() if self.video_head else None
        payload["thumbnail_head"] = (
            self.thumbnail_head.to_private_dict() if self.thumbnail_head else None
        )
        payload["source_present"] = self.video_head is not None
        payload["thumbnail_present"] = (
            self.source_thumbnail_key is not None and self.thumbnail_head is not None
        )
        return payload


@dataclass(frozen=True)
class FrozenCounts:
    total: int
    confirmed_invalid: int
    protected_gt: int
    owner_review: int


def _validate_original_key(original_key: str) -> str:
    key = original_key.strip()
    if not key or key.startswith("/") or "\\" in key:
        raise ValueError("unsafe_r2_key")
    parts = PurePosixPath(key).parts
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("unsafe_r2_key")
    if key.startswith(("research-quarantine/", "research-excluded/")):
        raise ValueError("already_research_scoped_key")
    return key


def _validate_clip_id(clip_id: str) -> str:
    parsed = uuid.UUID(clip_id)
    if str(parsed) != clip_id.lower():
        raise ValueError("noncanonical_clip_id")
    return str(parsed)


def _build_scoped_key(prefix: str, original_key: str, clip_id: str) -> str:
    return f"{prefix}/{_validate_clip_id(clip_id)}/{_validate_original_key(original_key)}"


def build_quarantine_key(original_key: str, clip_id: str) -> str:
    return _build_scoped_key(QUARANTINE_PREFIX, original_key, clip_id)


def build_excluded_key(original_key: str, clip_id: str) -> str:
    return _build_scoped_key(EXCLUDED_PREFIX, original_key, clip_id)


def validate_frozen_counts(items: Sequence[CleanupItem]) -> FrozenCounts:
    clip_ids = [item.clip_id for item in items]
    if len(clip_ids) != len(set(clip_ids)):
        raise ValueError("duplicate_clip_id")
    if any(item.seed_reason not in _ALLOWED_REASONS for item in items):
        raise ValueError("unknown_seed_reason")
    if any(
        item.has_canonical_gt
        for item in items
        if item.seed_reason in {"confirmed_gecko_absent", "confirmed_no_gecko_activity"}
    ):
        raise ValueError("confirmed_invalid_overlaps_canonical_gt")
    if any(
        item.seed_reason == "protected_gt" and not item.has_canonical_gt for item in items
    ):
        raise ValueError("protected_gt_without_canonical_gt")

    counts = FrozenCounts(
        total=len(items),
        confirmed_invalid=sum(
            item.seed_reason in {"confirmed_gecko_absent", "confirmed_no_gecko_activity"}
            for item in items
        ),
        protected_gt=sum(item.seed_reason == "protected_gt" for item in items),
        owner_review=sum(item.seed_reason == "owner_review_pending" for item in items),
    )
    if counts != FrozenCounts(951, 46, 1, 904):
        raise ValueError(f"frozen_counts_mismatch:{counts}")
    return counts


def _normalized_etag(value: str) -> str:
    return value.strip().strip('"').lower()


def same_r2_object(source: ObjectHead, destination: ObjectHead) -> bool:
    if source.content_length != destination.content_length:
        return False
    if source.content_sha256 and destination.content_sha256:
        return source.content_sha256 == destination.content_sha256
    return _normalized_etag(source.etag) == _normalized_etag(destination.etag)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def manifest_digest(items: Sequence[CleanupItem]) -> str:
    return hashlib.sha256(canonical_bytes([item.to_private_dict() for item in items])).hexdigest()


def _parse_head(raw: Mapping[str, Any]) -> ObjectHead:
    metadata = raw.get("Metadata") or {}
    sha = metadata.get("sha256") or metadata.get("content-sha256")
    if sha is not None and not isinstance(sha, str):
        sha = None
    modified = raw["LastModified"]
    if not isinstance(modified, datetime):
        raise ValueError("r2_head_last_modified_invalid")
    return ObjectHead(
        content_length=int(raw["ContentLength"]),
        etag=str(raw["ETag"]),
        last_modified=modified,
        content_sha256=sha,
    )


def _head_object(r2: Any, bucket: str, key: str) -> ObjectHead:
    return _parse_head(r2.head_object(Bucket=bucket, Key=key))


def _head_object_optional(r2: Any, bucket: str, key: str) -> ObjectHead | None:
    from botocore.exceptions import ClientError

    try:
        return _head_object(r2, bucket, key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return None
        raise


def _head_keys_concurrently(
    r2: Any, bucket: str, keys: Sequence[str], *, workers: int = 16
) -> dict[str, ObjectHead | None]:
    unique_keys = sorted(set(keys))

    def fetch(key: str) -> tuple[str, ObjectHead | None]:
        return key, _head_object_optional(r2, bucket, key)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="r2-head") as executor:
        return dict(executor.map(fetch, unique_keys))


def _write_private_manifest(items: Sequence[CleanupItem], digest: str, owner_id: str) -> None:
    payload = {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "manifest_digest": digest,
        "owner_id": owner_id,
        "items": [item.to_private_dict() for item in items],
    }
    data = canonical_bytes(payload) + b"\n"
    PRIVATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if PRIVATE_MANIFEST.exists():
        existing = PRIVATE_MANIFEST.read_bytes()
        if existing == data:
            return
        existing_payload = json.loads(existing)
        if (
            existing_payload.get("manifest_digest") != digest
            or existing_payload.get("items") != payload["items"]
            or existing_payload.get("experiment_id") != EXPERIMENT_ID
        ):
            raise RuntimeError("private_manifest_changed_fail_closed")
        upgrade_path = PRIVATE_MANIFEST.with_suffix(".json.upgrade")
        fd = os.open(upgrade_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        os.replace(upgrade_path, PRIVATE_MANIFEST)
        PRIVATE_MANIFEST.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return
    fd = os.open(PRIVATE_MANIFEST, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    PRIVATE_MANIFEST.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _chunks(values: Sequence[str], size: int = 80) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _all_rows(query_factory: Any, *, page_size: int = 1000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        response = query_factory().range(offset, offset + page_size - 1).execute()
        page = list(response.data or [])
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


def _load_effective_invalid(supabase: Any) -> tuple[list[dict[str, Any]], str]:
    cohorts = (
        supabase.table("rba_boundary_review_cohorts")
        .select("id,owner_id,status,created_at")
        .order("created_at", desc=True)
        .limit(10)
        .execute()
        .data
        or []
    )
    for cohort in cohorts:
        pairs = (
            supabase.table("rba_boundary_review_pairs")
            .select("id,left_clip_id,right_clip_id")
            .eq("cohort_id", cohort["id"])
            .eq("split", "development")
            .execute()
            .data
            or []
        )
        if len(pairs) != 120:
            continue
        pair_ids = [row["id"] for row in pairs]
        reviews: list[dict[str, Any]] = []
        corrections: list[dict[str, Any]] = []
        for ids in _chunks(pair_ids):
            reviews.extend(
                supabase.table("rba_boundary_eligibility_reviews")
                .select("id,pair_id,decision")
                .in_("pair_id", list(ids))
                .execute()
                .data
                or []
            )
            corrections.extend(
                supabase.table("rba_boundary_eligibility_corrections")
                .select("review_id,pair_id,replacement_decision")
                .in_("pair_id", list(ids))
                .execute()
                .data
                or []
            )
        if len(reviews) != 120:
            continue
        correction_by_review = {row["review_id"]: row for row in corrections}
        effective = {
            row["pair_id"]: correction_by_review.get(row["id"], {}).get(
                "replacement_decision", row["decision"]
            )
            for row in reviews
        }
        invalid: dict[str, str] = {}
        for pair in pairs:
            decision = effective[pair["id"]]
            if decision in {"left_gecko_absent", "both_gecko_absent"}:
                invalid[pair["left_clip_id"]] = "confirmed_gecko_absent"
            if decision in {"right_gecko_absent", "both_gecko_absent"}:
                invalid[pair["right_clip_id"]] = "confirmed_gecko_absent"
            if decision in {"left_no_gecko_activity", "both_no_gecko_activity"}:
                invalid[pair["left_clip_id"]] = "confirmed_no_gecko_activity"
            if decision in {"right_no_gecko_activity", "both_no_gecko_activity"}:
                invalid[pair["right_clip_id"]] = "confirmed_no_gecko_activity"
        if len(invalid) >= 46:
            clip_rows = _fetch_clips_by_ids(supabase, list(invalid))
            kst = timezone(timedelta(hours=9))
            approved: list[dict[str, Any]] = []
            stratum_counts: dict[tuple[str, str], int] = {}
            for row in clip_rows:
                reason = invalid[row["id"]]
                started = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
                stratum = (reason, started.astimezone(kst).date().isoformat())
                if stratum not in _APPROVED_INVALID_STRATA:
                    continue
                approved.append({"clip_id": row["id"], "seed_reason": reason})
                stratum_counts[stratum] = stratum_counts.get(stratum, 0) + 1
            if len(approved) == 46 and set(stratum_counts.values()) == {23}:
                return sorted(approved, key=lambda row: row["clip_id"]), cohort["owner_id"]
    raise RuntimeError("exact_46_effective_invalid_not_found")


def _fetch_clips_by_ids(supabase: Any, clip_ids: Sequence[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ids in _chunks(clip_ids):
        rows.extend(
            supabase.table("motion_clips")
            .select(
                "id,camera_id,started_at,duration_sec,r2_key,thumbnail_key"
            )
            .in_("id", list(ids))
            .execute()
            .data
            or []
        )
    return rows


def _canonical_gt_clip_ids(supabase: Any, clip_ids: Sequence[str]) -> set[str]:
    result: set[str] = set()
    for ids in _chunks(clip_ids):
        consensus = (
            supabase.table("motion_clip_consensus")
            .select("clip_id")
            .in_("clip_id", list(ids))
            .in_("status", ["agreed", "owner_resolved"])
            .eq("final_decision", "label")
            .not_.is_("final_gt", "null")
            .execute()
            .data
            or []
        )
        sessions = (
            supabase.table("motion_clip_labeling_sessions")
            .select("clip_id,initial_gt,current_gt")
            .in_("clip_id", list(ids))
            .execute()
            .data
            or []
        )
        result.update(row["clip_id"] for row in consensus)
        result.update(
            row["clip_id"]
            for row in sessions
            if row.get("current_gt") is not None or row.get("initial_gt") is not None
        )
    return result


def _build_production_manifest(supabase: Any, r2: Any, bucket: str) -> tuple[list[CleanupItem], str]:
    invalid, owner_id = _load_effective_invalid(supabase)
    invalid_by_id = {row["clip_id"]: row["seed_reason"] for row in invalid}
    invalid_clips = _fetch_clips_by_ids(supabase, list(invalid_by_id))
    if len(invalid_clips) != 46:
        raise RuntimeError("confirmed_invalid_clip_count_mismatch")

    strata: set[tuple[str, str]] = set()
    for clip in invalid_clips:
        started = datetime.fromisoformat(clip["started_at"].replace("Z", "+00:00"))
        # Mac mini의 TZ가 KST라는 가정에 기대지 않고 +09:00으로 계산한다.
        kst_date = started.astimezone(timezone(timedelta(hours=9))).date().isoformat()
        strata.add((clip["camera_id"], kst_date))
    if len(strata) != 2:
        raise RuntimeError("contaminated_strata_count_mismatch")

    candidate_by_id: dict[str, dict[str, Any]] = {}
    kst = timezone(timedelta(hours=9))
    for camera_id, day_text in sorted(strata):
        day = datetime.fromisoformat(day_text).replace(tzinfo=kst)
        rows = _all_rows(
            lambda camera_id=camera_id, day=day: supabase.table("motion_clips")
            .select("id,camera_id,started_at,duration_sec,r2_key,thumbnail_key")
            .eq("camera_id", camera_id)
            .gte("started_at", day.astimezone(UTC).isoformat())
            .lt("started_at", (day + timedelta(days=1)).astimezone(UTC).isoformat())
            .not_.is_("r2_key", "null")
            .order("started_at")
            .order("id")
        )
        for row in rows:
            candidate_by_id[row["id"]] = row
    if len(candidate_by_id) != 951:
        raise RuntimeError(f"full_camera_day_count_mismatch:{len(candidate_by_id)}")

    canonical_ids = _canonical_gt_clip_ids(supabase, list(candidate_by_id))
    media_keys = [row["r2_key"] for row in candidate_by_id.values()]
    media_keys.extend(
        row["thumbnail_key"]
        for row in candidate_by_id.values()
        if row.get("thumbnail_key")
    )
    heads = _head_keys_concurrently(r2, bucket, media_keys)
    items: list[CleanupItem] = []
    for clip_id, row in sorted(candidate_by_id.items(), key=lambda pair: (pair[1]["started_at"], pair[0])):
        has_gt = clip_id in canonical_ids
        reason = invalid_by_id.get(clip_id)
        if reason is None:
            reason = "protected_gt" if has_gt else "owner_review_pending"
        video_key = row["r2_key"]
        thumb_key = row.get("thumbnail_key")
        items.append(
            CleanupItem(
                clip_id=clip_id,
                camera_id=row["camera_id"],
                started_at=row["started_at"],
                seed_reason=reason,
                has_canonical_gt=has_gt,
                source_r2_key=video_key,
                source_thumbnail_key=thumb_key,
                video_head=heads[video_key],
                thumbnail_head=heads[thumb_key] if thumb_key else None,
            )
        )
    validate_frozen_counts(items)
    return items, owner_id


def _public_summary(items: Sequence[CleanupItem], digest: str) -> dict[str, object]:
    counts = validate_frozen_counts(items)
    total_bytes = sum(item.video_head.content_length for item in items if item.video_head)
    thumbnail_key_count = sum(item.source_thumbnail_key is not None for item in items)
    thumbnail_count = sum(item.thumbnail_head is not None for item in items)
    missing_by_reason = {
        reason: sum(item.seed_reason == reason and item.video_head is None for item in items)
        for reason in sorted(_ALLOWED_REASONS)
    }
    return {
        "experiment_id": EXPERIMENT_ID,
        "manifest_digest": digest,
        "counts": asdict(counts),
        "video_head_ok": sum(item.video_head is not None for item in items),
        "thumbnail_key_count": thumbnail_key_count,
        "thumbnail_head_ok": thumbnail_count,
        "aggregate_video_bytes": total_bytes,
        "missing_video_objects_by_reason": missing_by_reason,
        "dry_run": True,
    }


def _load_runtime_clients() -> tuple[Any, Any, str]:
    from backend.r2_uploader import get_r2_bucket, get_r2_client
    from backend.supabase_client import get_supabase_client

    return get_supabase_client(), get_r2_client(), get_r2_bucket()


def command_prepare() -> int:
    supabase, r2, bucket = _load_runtime_clients()
    items, owner_id = _build_production_manifest(supabase, r2, bucket)
    digest = manifest_digest(items)
    summary = _public_summary(items, digest)
    missing_videos = sum(item.video_head is None for item in items)
    missing_thumbnails = sum(
        item.source_thumbnail_key is not None and item.thumbnail_head is None for item in items
    )
    summary["missing_video_objects"] = missing_videos
    summary["missing_thumbnail_objects"] = missing_thumbnails
    existing_exclusion_rows: list[dict[str, Any]] = []
    for clip_ids in _chunks([item.clip_id for item in items]):
        response = (
            supabase.table("motion_clip_system_exclusions")
            .select("clip_id,state,reason_code")
            .in_("clip_id", list(clip_ids))
            .execute()
        )
        existing_exclusion_rows.extend(response.data or [])
    existing_exclusions = len(existing_exclusion_rows)
    summary["existing_exclusion_conflicts"] = existing_exclusions
    reason_by_clip = {item.clip_id: item.seed_reason for item in items}
    existing_breakdown: dict[str, int] = {}
    for row in existing_exclusion_rows:
        key = "|".join(
            (
                str(row["reason_code"]),
                str(row["state"]),
                reason_by_clip[str(row["clip_id"])],
            )
        )
        existing_breakdown[key] = existing_breakdown.get(key, 0) + 1
    summary["existing_exclusion_breakdown"] = existing_breakdown
    item_by_clip = {item.clip_id: item for item in items}
    summary["existing_exclusion_source_missing"] = sum(
        item_by_clip[str(row["clip_id"])].video_head is None
        for row in existing_exclusion_rows
    )
    unsafe_missing = sum(
        item.video_head is None
        and item.seed_reason != "owner_review_pending"
        for item in items
    )
    migratable_existing = all(
        row["reason_code"] == "short_device_error"
        and row["state"] == "candidate"
        and reason_by_clip[str(row["clip_id"])] == "owner_review_pending"
        for row in existing_exclusion_rows
    )
    if missing_videos != 7 or unsafe_missing or existing_exclusions != 11 or not migratable_existing:
        summary["preflight"] = "R2_HEAD_UNSAFE_MISSING_FAIL_CLOSED"
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 2
    _write_private_manifest(items, digest, owner_id)
    summary["preflight"] = "READY_WITH_7_SOURCE_MISSING_AND_11_REUSED_CANDIDATES"
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def command_audit_missing() -> int:
    supabase, r2, bucket = _load_runtime_clients()
    items, _owner_id = _build_production_manifest(supabase, r2, bucket)
    missing = [item for item in items if item.video_head is None]
    suffixes = {item.source_r2_key: f"/{item.source_r2_key}" for item in missing}
    matches: dict[str, list[str]] = {key: [] for key in suffixes}
    token: str | None = None
    scanned = 0
    while True:
        kwargs: dict[str, object] = {"Bucket": bucket, "MaxKeys": 1000}
        if token:
            kwargs["ContinuationToken"] = token
        page = r2.list_objects_v2(**kwargs)
        for row in page.get("Contents", []):
            candidate = str(row["Key"])
            scanned += 1
            for original, suffix in suffixes.items():
                if candidate != original and candidate.endswith(suffix):
                    matches[original].append(candidate)
        if not page.get("IsTruncated"):
            break
        token = str(page["NextContinuationToken"])
    print(
        json.dumps(
            {
                "missing": len(missing),
                "recovered_unique": sum(len(values) == 1 for values in matches.values()),
                "ambiguous": sum(len(values) > 1 for values in matches.values()),
                "not_found": sum(not values for values in matches.values()),
                "bucket_objects_scanned": scanned,
                "dry_run": True,
            },
            sort_keys=True,
        )
    )
    return 0


def _load_private_manifest() -> dict[str, Any]:
    if not PRIVATE_MANIFEST.is_file():
        raise RuntimeError("private_manifest_missing")
    mode = stat.S_IMODE(PRIVATE_MANIFEST.stat().st_mode)
    if mode & 0o077:
        raise RuntimeError("private_manifest_permissions_unsafe")
    payload = json.loads(PRIVATE_MANIFEST.read_text(encoding="utf-8"))
    if payload.get("experiment_id") != EXPERIMENT_ID:
        raise RuntimeError("private_manifest_experiment_mismatch")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != 951:
        raise RuntimeError("private_manifest_item_count_mismatch")
    actual = hashlib.sha256(canonical_bytes(items)).hexdigest()
    if actual != payload.get("manifest_digest"):
        raise RuntimeError("private_manifest_digest_mismatch")
    return payload


def _head_from_private(value: Mapping[str, Any] | None) -> ObjectHead | None:
    if value is None:
        return None
    return ObjectHead(
        content_length=int(value["content_length"]),
        etag=str(value["etag"]),
        last_modified=datetime.fromisoformat(str(value["last_modified"])),
        content_sha256=value.get("content_sha256"),
    )


def _copy_verified(
    r2: Any, bucket: str, source_key: str, destination_key: str, expected: ObjectHead
) -> ObjectHead:
    existing = _head_object_optional(r2, bucket, destination_key)
    if existing is not None:
        if not same_r2_object(expected, existing):
            raise RuntimeError("destination_object_mismatch")
        return existing
    r2.copy_object(
        Bucket=bucket,
        Key=destination_key,
        CopySource={"Bucket": bucket, "Key": source_key},
        MetadataDirective="COPY",
    )
    copied = _head_object_optional(r2, bucket, destination_key)
    if copied is None or not same_r2_object(expected, copied):
        raise RuntimeError("copy_verification_failed")
    return copied


def _delete_verified(r2: Any, bucket: str, key: str) -> None:
    if _head_object_optional(r2, bucket, key) is None:
        return
    r2.delete_object(Bucket=bucket, Key=key)
    if _head_object_optional(r2, bucket, key) is not None:
        raise RuntimeError("source_delete_verification_failed")


def _head_payload(head: ObjectHead | None) -> dict[str, object] | None:
    return head.to_private_dict() if head else None


def _ensure_cleanup_cohort(supabase: Any, manifest: Mapping[str, Any]) -> None:
    existing = (
        supabase.table("rba_owner_media_cleanup_cohorts")
        .select("manifest_digest,total_count,confirmed_invalid_count,protected_gt_count,owner_review_count,source_missing_count,reused_short_candidate_count")
        .eq("experiment_id", EXPERIMENT_ID)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        row = existing[0]
        expected = {
            "manifest_digest": manifest["manifest_digest"],
            "total_count": 951,
            "confirmed_invalid_count": 46,
            "protected_gt_count": 1,
            "owner_review_count": 904,
            "source_missing_count": 7,
            "reused_short_candidate_count": 11,
        }
        if any(row.get(key) != value for key, value in expected.items()):
            raise RuntimeError("existing_cleanup_cohort_mismatch")
        return
    supabase.rpc(
        "fn_prepare_rba_owner_media_cleanup_v1",
        {
            "p_experiment_id": EXPERIMENT_ID,
            "p_owner_id": manifest["owner_id"],
            "p_manifest_digest": manifest["manifest_digest"],
            "p_items": manifest["items"],
        },
    ).execute()


def _claim(supabase: Any, stage: str, worker_host: str) -> list[dict[str, Any]]:
    return list(
        supabase.rpc(
            "fn_claim_rba_owner_media_move_v1",
            {"p_stage": stage, "p_worker_host": worker_host, "p_limit": 20},
        ).execute().data
        or []
    )


def _complete_move(
    supabase: Any,
    claim: Mapping[str, Any],
    destination_video: str,
    destination_thumbnail: str | None,
    source_head: ObjectHead,
    destination_head: ObjectHead,
) -> None:
    supabase.rpc(
        "fn_complete_rba_owner_media_move_v1",
        {
            "p_item_id": claim["item_id"],
            "p_lease_token": claim["lease_token"],
            "p_destination_r2_key": destination_video,
            "p_destination_thumbnail_key": destination_thumbnail,
            "p_source_fingerprint": _head_payload(source_head),
            "p_destination_fingerprint": _head_payload(destination_head),
        },
    ).execute()


def _fail_move(supabase: Any, claim: Mapping[str, Any], code: str) -> None:
    try:
        supabase.rpc(
            "fn_fail_rba_owner_media_move_v1",
            {
                "p_item_id": claim["item_id"],
                "p_lease_token": claim["lease_token"],
                "p_error_code": code[:100],
            },
        ).execute()
    except Exception:
        pass


def _move_claim_to_quarantine(
    supabase: Any,
    r2: Any,
    bucket: str,
    claim: Mapping[str, Any],
    private_item: Mapping[str, Any],
) -> None:
    source_video = str(claim["source_r2_key"])
    expected_video = _head_from_private(private_item["video_head"])
    if expected_video is None:
        raise RuntimeError("claimed_source_missing")
    destination_video = build_quarantine_key(
        str(private_item["source_r2_key"]), str(claim["clip_id"])
    )
    copied_video = _copy_verified(r2, bucket, source_video, destination_video, expected_video)

    source_thumbnail = claim.get("source_thumbnail_key")
    expected_thumbnail = _head_from_private(private_item.get("thumbnail_head"))
    destination_thumbnail: str | None = None
    if source_thumbnail and expected_thumbnail:
        destination_thumbnail = build_quarantine_key(
            str(private_item["source_thumbnail_key"]), str(claim["clip_id"])
        )
        _copy_verified(
            r2, bucket, str(source_thumbnail), destination_thumbnail, expected_thumbnail
        )

    _complete_move(
        supabase,
        claim,
        destination_video,
        destination_thumbnail,
        expected_video,
        copied_video,
    )
    _delete_verified(r2, bucket, source_video)
    if source_thumbnail and expected_thumbnail:
        _delete_verified(r2, bucket, str(source_thumbnail))


def command_quarantine(*, apply: bool) -> int:
    if not apply:
        print(json.dumps({"command": "quarantine", "dry_run": True}, sort_keys=True))
        return 0
    manifest = _load_private_manifest()
    supabase, r2, bucket = _load_runtime_clients()
    _ensure_cleanup_cohort(supabase, manifest)
    private_by_clip = {str(row["clip_id"]): row for row in manifest["items"]}
    worker_host = os.uname().nodename
    moved = 0

    def process_claim(claim: Mapping[str, Any]) -> tuple[Mapping[str, Any], Exception | None]:
        try:
            _move_claim_to_quarantine(
                supabase, r2, bucket, claim, private_by_clip[str(claim["clip_id"])]
            )
            return claim, None
        except Exception as exc:
            return claim, exc

    while True:
        claims = _claim(supabase, "quarantine", worker_host)
        if not claims:
            break
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="r2-quarantine") as executor:
            results = list(executor.map(process_claim, claims))
        errors: list[str] = []
        for claim, exc in results:
            if exc is None:
                moved += 1
                if moved % 100 == 0:
                    print(json.dumps({"stage": "quarantine", "moved": moved}), flush=True)
            else:
                api_code = getattr(exc, "code", None)
                safe_code = type(exc).__name__ + (f":{api_code}" if api_code else "")
                _fail_move(supabase, claim, safe_code)
                errors.append(safe_code)
        if errors:
            print(
                json.dumps(
                    {
                        "stage": "quarantine",
                        "moved": moved,
                        "status": "FAIL_CLOSED",
                        "error_codes": sorted(set(errors)),
                    }
                ),
                flush=True,
            )
            return 2
    print(
        json.dumps(
            {"stage": "quarantine", "moved": moved, "source_missing": 7, "status": "COMPLETE"},
            sort_keys=True,
        )
    )
    return 0


def _move_claim_to_excluded_and_delete(
    supabase: Any,
    r2: Any,
    bucket: str,
    claim: Mapping[str, Any],
    private_item: Mapping[str, Any],
) -> None:
    source_video = str(claim["source_r2_key"])
    expected_video = _head_from_private(private_item["video_head"])
    if expected_video is None:
        raise RuntimeError("confirmed_delete_source_missing")
    destination_video = build_excluded_key(
        str(private_item["source_r2_key"]), str(claim["clip_id"])
    )
    copied_video = _copy_verified(r2, bucket, source_video, destination_video, expected_video)

    source_thumbnail = claim.get("source_thumbnail_key")
    expected_thumbnail = _head_from_private(private_item.get("thumbnail_head"))
    destination_thumbnail: str | None = None
    if source_thumbnail and expected_thumbnail:
        destination_thumbnail = build_excluded_key(
            str(private_item["source_thumbnail_key"]), str(claim["clip_id"])
        )
        _copy_verified(
            r2, bucket, str(source_thumbnail), destination_thumbnail, expected_thumbnail
        )

    _complete_move(
        supabase,
        claim,
        destination_video,
        destination_thumbnail,
        expected_video,
        copied_video,
    )
    _delete_verified(r2, bucket, source_video)
    if source_thumbnail and expected_thumbnail:
        _delete_verified(r2, bucket, str(source_thumbnail))
    _delete_verified(r2, bucket, destination_video)
    if destination_thumbnail:
        _delete_verified(r2, bucket, destination_thumbnail)


def command_delete_confirmed(*, apply: bool) -> int:
    if not apply:
        print(
            json.dumps({"command": "delete-confirmed", "dry_run": True}, sort_keys=True)
        )
        return 0
    manifest = _load_private_manifest()
    supabase, r2, bucket = _load_runtime_clients()
    _ensure_cleanup_cohort(supabase, manifest)
    private_by_clip = {str(row["clip_id"]): row for row in manifest["items"]}
    worker_host = os.uname().nodename
    deleted = 0

    def process_claim(claim: Mapping[str, Any]) -> tuple[Mapping[str, Any], Exception | None]:
        try:
            _move_claim_to_excluded_and_delete(
                supabase, r2, bucket, claim, private_by_clip[str(claim["clip_id"])]
            )
            return claim, None
        except Exception as exc:
            return claim, exc

    while True:
        claims = _claim(supabase, "delete_confirmed", worker_host)
        if not claims:
            break
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="r2-delete") as executor:
            results = list(executor.map(process_claim, claims))
        errors: list[str] = []
        for claim, exc in results:
            if exc is None:
                deleted += 1
            else:
                api_code = getattr(exc, "code", None)
                safe_code = type(exc).__name__ + (f":{api_code}" if api_code else "")
                _fail_move(supabase, claim, safe_code)
                errors.append(safe_code)
        print(json.dumps({"stage": "delete-confirmed", "deleted": deleted}), flush=True)
        if errors:
            print(
                json.dumps(
                    {
                        "stage": "delete-confirmed",
                        "deleted": deleted,
                        "status": "FAIL_CLOSED",
                        "error_codes": sorted(set(errors)),
                    }
                ),
                flush=True,
            )
            return 2

    # DB 완료 뒤 마지막 R2 delete 응답이 끊겼어도 멱등하게 잔여 사본을 다시 지운다.
    confirmed = [
        row
        for row in manifest["items"]
        if row["seed_reason"]
        in {"confirmed_gecko_absent", "confirmed_no_gecko_activity"}
    ]
    for row in confirmed:
        clip_id = str(row["clip_id"])
        _delete_verified(
            r2, bucket, build_quarantine_key(str(row["source_r2_key"]), clip_id)
        )
        _delete_verified(r2, bucket, build_excluded_key(str(row["source_r2_key"]), clip_id))
        if row.get("source_thumbnail_key"):
            _delete_verified(
                r2,
                bucket,
                build_quarantine_key(str(row["source_thumbnail_key"]), clip_id),
            )
            _delete_verified(
                r2,
                bucket,
                build_excluded_key(str(row["source_thumbnail_key"]), clip_id),
            )
    print(
        json.dumps(
            {"stage": "delete-confirmed", "media_deleted": 46, "status": "COMPLETE"},
            sort_keys=True,
        )
    )
    return 0


def command_verify() -> int:
    manifest = _load_private_manifest()
    supabase, r2, bucket = _load_runtime_clients()
    db_rows = _all_rows(
        lambda: supabase.table("rba_owner_media_cleanup_items")
        .select("clip_id,state,seed_reason,source_r2_key,source_thumbnail_key")
        .order("created_at")
        .order("id")
    )
    if len(db_rows) != 951:
        raise RuntimeError("verify_db_item_count_mismatch")
    db_by_clip = {str(row["clip_id"]): row for row in db_rows}

    keys: set[str] = set()
    for row in manifest["items"]:
        clip_id = str(row["clip_id"])
        original_video = str(row["source_r2_key"])
        keys.add(original_video)
        keys.add(build_quarantine_key(original_video, clip_id))
        if row["seed_reason"] in {
            "confirmed_gecko_absent",
            "confirmed_no_gecko_activity",
        }:
            keys.add(build_excluded_key(original_video, clip_id))
        if row.get("source_thumbnail_key"):
            original_thumbnail = str(row["source_thumbnail_key"])
            keys.add(original_thumbnail)
            keys.add(build_quarantine_key(original_thumbnail, clip_id))
            if row["seed_reason"] in {
                "confirmed_gecko_absent",
                "confirmed_no_gecko_activity",
            }:
                keys.add(build_excluded_key(original_thumbnail, clip_id))
    heads = _head_keys_concurrently(r2, bucket, list(keys))

    violations = Counter()
    source_missing_thumbnail_present = 0
    for row in manifest["items"]:
        clip_id = str(row["clip_id"])
        db_row = db_by_clip[clip_id]
        state = str(db_row["state"])
        original_video = str(row["source_r2_key"])
        quarantine_video = build_quarantine_key(original_video, clip_id)
        expected_video = _head_from_private(row.get("video_head"))
        if heads[original_video] is not None:
            violations["original_video_still_present"] += 1
        if state == "quarantined":
            if expected_video is None or heads[quarantine_video] is None:
                violations["quarantine_video_missing"] += 1
            elif not same_r2_object(expected_video, heads[quarantine_video]):
                violations["quarantine_video_mismatch"] += 1
        elif state == "media_deleted":
            excluded_video = build_excluded_key(original_video, clip_id)
            if heads[quarantine_video] is not None or heads[excluded_video] is not None:
                violations["deleted_video_still_present"] += 1
        elif state != "source_missing":
            violations["unexpected_db_state"] += 1

        original_thumbnail = row.get("source_thumbnail_key")
        expected_thumbnail = _head_from_private(row.get("thumbnail_head"))
        if original_thumbnail:
            original_thumbnail = str(original_thumbnail)
            quarantine_thumbnail = build_quarantine_key(original_thumbnail, clip_id)
            if state != "source_missing" and heads[original_thumbnail] is not None:
                violations["original_thumbnail_still_present"] += 1
            if state == "quarantined" and expected_thumbnail is not None:
                if heads[quarantine_thumbnail] is None:
                    violations["quarantine_thumbnail_missing"] += 1
                elif not same_r2_object(expected_thumbnail, heads[quarantine_thumbnail]):
                    violations["quarantine_thumbnail_mismatch"] += 1
            elif state == "media_deleted":
                excluded_thumbnail = build_excluded_key(original_thumbnail, clip_id)
                if (
                    heads[quarantine_thumbnail] is not None
                    or heads[excluded_thumbnail] is not None
                ):
                    violations["deleted_thumbnail_still_present"] += 1
            elif state == "source_missing" and expected_thumbnail is not None:
                source_missing_thumbnail_present += 1

    state_counts = Counter(str(row["state"]) for row in db_rows)
    expected_states = Counter({"media_deleted": 46, "quarantined": 898, "source_missing": 7})
    if state_counts != expected_states:
        violations["db_state_counts"] += 1
    summary = {
        "db_states": dict(sorted(state_counts.items())),
        "r2_keys_checked": len(keys),
        "source_missing_thumbnail_present": source_missing_thumbnail_present,
        "violations": dict(sorted(violations.items())),
        "status": "VERIFIED" if not violations and source_missing_thumbnail_present == 0 else "FAIL_CLOSED",
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] == "VERIFIED" else 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Owner 기반 R2 초기 오염 영상 정리")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare", help="read-only manifest/HEAD preflight")
    subparsers.add_parser("audit-missing", help="read-only bucket-wide missing-key audit")
    for name in ("quarantine", "delete-confirmed", "verify"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        return command_prepare()
    if args.command == "audit-missing":
        return command_audit_missing()
    if args.command == "quarantine":
        return command_quarantine(apply=args.apply)
    if args.command == "delete-confirmed":
        return command_delete_confirmed(apply=args.apply)
    if args.command == "verify":
        return command_verify()
    if not getattr(args, "apply", False):
        print(json.dumps({"command": args.command, "dry_run": True}, sort_keys=True))
        return 0
    raise RuntimeError(f"apply_stage_not_implemented_fail_closed:{args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

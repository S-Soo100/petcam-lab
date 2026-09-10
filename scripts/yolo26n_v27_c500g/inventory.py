"""Read-only C500G source inventory across local, R2, and DB ledgers.

This stage verifies manifest/container-probe metadata and file hashes only.  It
does not decode media, open thumbnails, extract frames, or mutate any source.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Protocol
from zoneinfo import ZoneInfo


SCHEMA = "yolo26n-v27-c500g-source-inventory-v1"
SUMMARY_SCHEMA = "yolo26n-v27-c500g-inventory-summary-v1"
EXPECTED_SLOTS_SCHEMA = "yolo26n-v27-c500g-expected-slots-v1"
READY = "V27_SOURCE_INVENTORY_READY"
MISMATCH = "V27_SOURCE_INVENTORY_MISMATCH"
WRITE_COUNTS = {
    "db_write_count": 0,
    "r2_write_count": 0,
    "service_write_count": 0,
    "git_write_count": 0,
}
DB_FIELDS = (
    "bundle_id",
    "mode",
    "camera_key",
    "night_date",
    "scheduled_start_utc",
    "partial",
    "duration_sec",
    "codec",
    "width",
    "height",
    "fps",
    "video_size_bytes",
    "video_sha256",
    "video_r2_key",
    "manifest_r2_key",
    "relative_bundle_path",
    "capture_status",
    "upload_status",
)
DB_SELECT_COLUMNS = ",".join(DB_FIELDS)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BUNDLE_ID = re.compile(r"^rap-[a-z0-9-]+$")
_ROOT_KEYS = {
    "schema",
    "bundle_id",
    "mode",
    "camera_key",
    "test_run_id",
    "night_date",
    "scheduled_start_utc",
    "actual_start_utc",
    "ended_at_utc",
    "partial",
    "relative_bundle_path",
    "media",
    "capture",
    "artifacts",
    "manifest_r2_key",
    "upload_status",
    "r2_verified",
    "upload_attempts",
    "last_error_code",
    "uploaded_at",
}
_ROOT_REQUIRED = {
    "schema",
    "bundle_id",
    "mode",
    "camera_key",
    "test_run_id",
    "night_date",
    "scheduled_start_utc",
    "actual_start_utc",
    "partial",
    "relative_bundle_path",
    "media",
    "capture",
    "artifacts",
    "manifest_r2_key",
    "upload_status",
    "r2_verified",
}
_MEDIA_KEYS = {"duration_sec", "codec", "codec_tag", "width", "height", "fps"}
_MEDIA_REQUIRED = {"duration_sec", "codec", "width", "height", "fps"}
_CAPTURE_KEYS = {"ffmpeg_exit_code", "verified"}
_ARTIFACT_KEYS = {"name", "size_bytes", "sha256", "content_type", "r2_key"}
_DB_EXTRA_KEYS = {
    "test_run_id",
    "actual_start_utc",
    "ended_at_utc",
    "thumbnail_r2_key",
    "log_r2_key",
    "upload_attempts",
    "last_error_code",
    "uploaded_at",
}
_INVENTORY_KEYS = {
    "schema",
    "status",
    "test_sheet_sha256",
    "expected_slot_count",
    "actual_bundle_count",
    "complete_camera_night_count",
    "missing_slot_count",
    "mismatch_count",
    "decode_probe_failure_count",
    "storage_match_count",
    "records",
    "mismatches",
    *WRITE_COUNTS,
}


class R2Reader(Protocol):
    def list_objects_v2(self, **kwargs: object) -> Mapping[str, object]: ...

    def head_object(self, **kwargs: object) -> Mapping[str, object]: ...


class DbQuery(Protocol):
    def execute(self) -> object: ...


class DbReader(Protocol):
    def select(self, columns: str) -> DbQuery: ...


def _object(
    value: object,
    *,
    required: set[str],
    allowed: set[str],
    field: str,
) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object with string keys")
    missing = required.difference(value)
    if missing:
        raise ValueError(f"{field} missing required keys: {', '.join(sorted(missing))}")
    unknown = set(value).difference(allowed)
    if unknown:
        raise ValueError(f"{field} unknown keys: {', '.join(sorted(unknown))}")
    return dict(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{field} must be a non-empty canonical string")
    return value


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} must be exactly 64 lowercase hexadecimal characters")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return value


def _number(value: object, field: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number >= {minimum}")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < minimum:
        raise ValueError(f"{field} must be a finite number >= {minimum}")
    return parsed


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field} must be a boolean")
    return value


def _safe_relative(value: object, field: str) -> str:
    text = _string(value, field)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or "." in path.parts or "\\" in text:
        raise ValueError(f"{field} must be a safe relative POSIX path")
    if path.as_posix() != text or "//" in text:
        raise ValueError(f"{field} must be a canonical relative POSIX path")
    return text


def _utc(value: object, field: str) -> str:
    text = _string(value, field)
    if not (text.endswith("Z") or text.endswith("+00:00")):
        raise ValueError(f"{field} must be canonical UTC")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be a real UTC datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be UTC")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _calendar_date(value: object, field: str) -> str:
    text = _string(value, field)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{field} must be a real calendar date") from error
    if parsed.isoformat() != text:
        raise ValueError(f"{field} must be a canonical calendar date")
    return text


def _parse_manifest(data: bytes, actual_relative: str) -> dict[str, object]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("manifest must be valid UTF-8 JSON") from error
    manifest = _object(
        payload,
        required=_ROOT_REQUIRED,
        allowed=_ROOT_KEYS,
        field="manifest",
    )
    if manifest["schema"] != "rap-c500g-bundle/v1":
        raise ValueError("manifest schema is invalid")
    bundle_id = _string(manifest["bundle_id"], "manifest.bundle_id")
    if _BUNDLE_ID.fullmatch(bundle_id) is None:
        raise ValueError("manifest.bundle_id has invalid format")
    _string(manifest["camera_key"], "manifest.camera_key")
    night_date = _calendar_date(manifest["night_date"], "manifest.night_date")
    manifest["night_date"] = night_date
    manifest["scheduled_start_utc"] = _utc(
        manifest["scheduled_start_utc"], "manifest.scheduled_start_utc"
    )
    manifest["actual_start_utc"] = _utc(
        manifest["actual_start_utc"], "manifest.actual_start_utc"
    )
    _boolean(manifest["partial"], "manifest.partial")
    relative = _safe_relative(
        manifest["relative_bundle_path"], "manifest.relative_bundle_path"
    )
    if relative != actual_relative:
        raise ValueError("manifest relative_bundle_path does not match its location")
    manifest_key = _safe_relative(
        manifest["manifest_r2_key"], "manifest.manifest_r2_key"
    )
    if manifest_key != f"{relative}/manifest.json":
        raise ValueError("manifest R2 key must remain inside the declared bundle path")
    _boolean(manifest["r2_verified"], "manifest.r2_verified")

    media = _object(
        manifest["media"],
        required=_MEDIA_REQUIRED,
        allowed=_MEDIA_KEYS,
        field="manifest.media",
    )
    media["duration_sec"] = _number(media["duration_sec"], "media.duration_sec")
    media["codec"] = _string(media["codec"], "media.codec").lower()
    media["width"] = _integer(media["width"], "media.width", minimum=1)
    media["height"] = _integer(media["height"], "media.height", minimum=1)
    media["fps"] = _number(media["fps"], "media.fps")
    if "codec_tag" in media:
        media["codec_tag"] = _string(media["codec_tag"], "media.codec_tag")
    manifest["media"] = media

    capture = _object(
        manifest["capture"],
        required=_CAPTURE_KEYS,
        allowed=_CAPTURE_KEYS,
        field="manifest.capture",
    )
    capture["ffmpeg_exit_code"] = _integer(
        capture["ffmpeg_exit_code"], "capture.ffmpeg_exit_code"
    )
    capture["verified"] = _boolean(capture["verified"], "capture.verified")
    manifest["capture"] = capture

    artifacts_value = manifest["artifacts"]
    if not isinstance(artifacts_value, Sequence) or isinstance(
        artifacts_value, (str, bytes, bytearray)
    ):
        raise ValueError("manifest.artifacts must be a sequence")
    artifacts: list[dict[str, object]] = []
    for index, value in enumerate(artifacts_value):
        artifact = _object(
            value,
            required=_ARTIFACT_KEYS,
            allowed=_ARTIFACT_KEYS,
            field=f"manifest.artifacts[{index}]",
        )
        artifact["name"] = _string(artifact["name"], "artifact.name")
        artifact["size_bytes"] = _integer(
            artifact["size_bytes"], "artifact.size_bytes", minimum=1
        )
        artifact["sha256"] = _sha(artifact["sha256"], "artifact.sha256")
        artifact["content_type"] = _string(
            artifact["content_type"], "artifact.content_type"
        )
        artifact["r2_key"] = _safe_relative(artifact["r2_key"], "artifact.r2_key")
        artifacts.append(artifact)
    names = [str(item["name"]) for item in artifacts]
    if len(names) != len(set(names)) or set(names) != {
        "video.mp4",
        "thumbnail.jpg",
        "ffmpeg.sanitized.log",
    }:
        raise ValueError("manifest artifacts must contain each required name exactly once")
    if any(
        artifact["r2_key"] != f"{relative}/{artifact['name']}"
        for artifact in artifacts
    ):
        raise ValueError("artifact R2 key must remain inside the declared bundle path")
    manifest["artifacts"] = artifacts
    return manifest


def _open_root_fd(root: Path) -> int:
    absolute = Path(os.path.abspath(os.fspath(root)))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for component in absolute.parts[1:]:
            try:
                next_fd = os.open(component, flags, dir_fd=fd)
            except OSError as error:
                raise ValueError(
                    "local_root contains a symlink or non-directory component"
                ) from error
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_regular_fd(directory_fd: int, name: str) -> bytes:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError as error:
        raise ValueError(f"{name} must be a regular non-symlink file") from error
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"{name} must be a regular non-symlink file")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(fd)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ValueError(f"{name} changed during inventory")
        data = b"".join(chunks)
        if len(data) != after.st_size:
            raise ValueError(f"{name} changed during inventory")
        return data
    finally:
        os.close(fd)


def _hash_regular_fd(directory_fd: int, name: str) -> tuple[int, str]:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError as error:
        raise ValueError(f"{name} must be a regular non-symlink file") from error
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"{name} must be a regular non-symlink file")
        with os.fdopen(os.dup(fd), "rb") as source:
            digest = hashlib.file_digest(source, "sha256", _bufsize=1024 * 1024)
            byte_count = source.tell()
        after = os.fstat(fd)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or byte_count != after.st_size:
            raise ValueError(f"{name} changed during inventory")
        return after.st_size, digest.hexdigest()
    finally:
        os.close(fd)


def _scan_local(root_fd: int) -> list[tuple[dict[str, object], int, str]]:
    results: list[tuple[dict[str, object], int, str]] = []

    def walk(directory_fd: int, components: tuple[str, ...]) -> None:
        for name in sorted(os.listdir(directory_fd)):
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError("local source tree contains a symlink")
            if stat.S_ISDIR(metadata.st_mode):
                child_fd = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
                try:
                    opened = os.fstat(child_fd)
                    if (opened.st_dev, opened.st_ino) != (
                        metadata.st_dev,
                        metadata.st_ino,
                    ):
                        raise ValueError("source directory changed during inventory")
                    walk(child_fd, (*components, name))
                finally:
                    os.close(child_fd)
            elif name == "manifest.json":
                relative = PurePosixPath(*components).as_posix()
                manifest = _parse_manifest(
                    _read_regular_fd(directory_fd, "manifest.json"), relative
                )
                video_size, video_sha = _hash_regular_fd(directory_fd, "video.mp4")
                results.append(
                    (
                        manifest,
                        video_size,
                        video_sha,
                    )
                )

    walk(root_fd, ())
    return results


def _video_artifact(manifest: Mapping[str, object]) -> dict[str, object]:
    for artifact in manifest["artifacts"]:  # type: ignore[union-attr]
        if artifact["name"] == "video.mp4":
            return artifact
    raise ValueError("manifest video artifact is missing")


def _expected_slot_set(
    value: object, *, test_sheet_sha256: str
) -> set[tuple[str, str, str]]:
    ledger = _object(
        value,
        required={
            "schema",
            "test_sheet_sha256",
            "schedule_sha256",
            "timezone",
            "duration_sec",
            "slots",
        },
        allowed={
            "schema",
            "test_sheet_sha256",
            "schedule_sha256",
            "timezone",
            "duration_sec",
            "slots",
        },
        field="expected_slots",
    )
    if ledger["schema"] != EXPECTED_SLOTS_SCHEMA:
        raise ValueError("expected_slots schema is invalid")
    if _sha(ledger["test_sheet_sha256"], "expected_slots.test_sheet_sha256") != (
        test_sheet_sha256
    ):
        raise ValueError("expected_slots TEST-SHEET pin differs")
    schedule_sha = _sha(ledger["schedule_sha256"], "expected_slots.schedule_sha256")
    timezone = _string(ledger["timezone"], "expected_slots.timezone")
    if timezone != "Asia/Seoul":
        raise ValueError("expected_slots timezone must be Asia/Seoul")
    duration_sec = _integer(
        ledger["duration_sec"], "expected_slots.duration_sec", minimum=1
    )
    if duration_sec != 1800:
        raise ValueError("expected_slots duration_sec must be 1800")
    slots = ledger["slots"]
    if not isinstance(slots, list) or len(slots) != 504:
        raise ValueError("expected_slots must contain exactly 504 slots")
    parsed: set[tuple[str, str, str]] = set()
    physical_slots: set[tuple[str, str]] = set()
    canonical_slots: list[dict[str, str]] = []
    for index, value in enumerate(slots):
        slot = _object(
            value,
            required={
                "anonymous_camera_digest",
                "night_date",
                "scheduled_start_utc",
            },
            allowed={
                "anonymous_camera_digest",
                "night_date",
                "scheduled_start_utc",
            },
            field=f"expected_slots.slots[{index}]",
        )
        camera = _sha(
            slot["anonymous_camera_digest"],
            "expected slot anonymous_camera_digest",
        )
        night = _calendar_date(slot["night_date"], "expected slot night_date")
        scheduled = _utc(
            slot["scheduled_start_utc"], "expected slot scheduled_start_utc"
        )
        identity = (camera, night, scheduled)
        physical_identity = (camera, scheduled)
        if identity in parsed or physical_identity in physical_slots:
            raise ValueError("expected_slots contains a duplicate slot")
        parsed.add(identity)
        physical_slots.add(physical_identity)
        canonical_slots.append(
            {
                "anonymous_camera_digest": camera,
                "night_date": night,
                "scheduled_start_utc": scheduled,
            }
        )

    cameras = sorted({slot[0] for slot in parsed})
    nights = sorted({date.fromisoformat(slot[1]) for slot in parsed})
    if len(cameras) != 3 or len(nights) != 7:
        raise ValueError("expected_slots must cover 3 cameras and 7 nights")
    if any(later - earlier != timedelta(days=1) for earlier, later in zip(nights, nights[1:])):
        raise ValueError("expected_slots nights must be consecutive")

    kst = ZoneInfo("Asia/Seoul")
    for camera in cameras:
        for night in nights:
            group = sorted(
                scheduled
                for candidate_camera, candidate_night, scheduled in parsed
                if candidate_camera == camera and candidate_night == night.isoformat()
            )
            if len(group) != 24:
                raise ValueError("each camera-night must contain exactly 24 slots")
            expected_group = [
                (
                    datetime.combine(night, datetime.min.time(), tzinfo=kst)
                    + timedelta(hours=20, minutes=30 * index)
                )
                .astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z")
                for index in range(24)
            ]
            if group != expected_group:
                raise ValueError(
                    "camera-night slots must be half-hour starts from 20:00 to 07:30 KST"
                )

    canonical_payload = {
        "schema": EXPECTED_SLOTS_SCHEMA,
        "timezone": timezone,
        "duration_sec": duration_sec,
        "slots": sorted(
            canonical_slots,
            key=lambda item: (
                item["anonymous_camera_digest"],
                item["night_date"],
                item["scheduled_start_utc"],
            ),
        ),
    }
    calculated_sha = hashlib.sha256(
        json.dumps(
            canonical_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if calculated_sha != schedule_sha:
        raise ValueError("expected_slots schedule_sha256 mismatch")
    return parsed


def _db_rows(reader: DbReader) -> list[dict[str, object]]:
    response = reader.select(DB_SELECT_COLUMNS).execute()
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        raise ValueError("DB SELECT response data must be a list")
    rows: list[dict[str, object]] = []
    for index, value in enumerate(data):
        row = _object(
            value,
            required=set(DB_FIELDS),
            allowed=set(DB_FIELDS) | _DB_EXTRA_KEYS,
            field=f"db.rows[{index}]",
        )
        row["bundle_id"] = _string(row["bundle_id"], "db.bundle_id")
        if _BUNDLE_ID.fullmatch(row["bundle_id"]) is None:  # type: ignore[arg-type]
            raise ValueError("db.bundle_id has invalid format")
        row["mode"] = _string(row["mode"], "db.mode")
        row["camera_key"] = _string(row["camera_key"], "db.camera_key")
        row["night_date"] = _calendar_date(row["night_date"], "db.night_date")
        row["scheduled_start_utc"] = _utc(
            row["scheduled_start_utc"], "db.scheduled_start_utc"
        )
        row["partial"] = _boolean(row["partial"], "db.partial")
        row["duration_sec"] = _number(row["duration_sec"], "db.duration_sec")
        row["codec"] = _string(row["codec"], "db.codec").lower()
        row["width"] = _integer(row["width"], "db.width", minimum=1)
        row["height"] = _integer(row["height"], "db.height", minimum=1)
        row["fps"] = _number(row["fps"], "db.fps")
        row["video_size_bytes"] = _integer(
            row["video_size_bytes"], "db.video_size_bytes", minimum=1
        )
        row["video_sha256"] = _sha(row["video_sha256"], "db.video_sha256")
        row["video_r2_key"] = _safe_relative(row["video_r2_key"], "db.video_r2_key")
        row["manifest_r2_key"] = _safe_relative(
            row["manifest_r2_key"], "db.manifest_r2_key"
        )
        row["relative_bundle_path"] = _safe_relative(
            row["relative_bundle_path"], "db.relative_bundle_path"
        )
        row["capture_status"] = _string(row["capture_status"], "db.capture_status")
        row["upload_status"] = _string(row["upload_status"], "db.upload_status")
        rows.append(row)
    return rows


def _r2_listing(reader: R2Reader) -> dict[str, int]:
    objects: dict[str, int] = {}
    continuation: str | None = None
    seen_tokens: set[str] = set()
    page = 0
    response_keys = {
        "Contents",
        "IsTruncated",
        "Name",
        "Prefix",
        "Delimiter",
        "MaxKeys",
        "CommonPrefixes",
        "EncodingType",
        "KeyCount",
        "ContinuationToken",
        "NextContinuationToken",
        "StartAfter",
        "RequestCharged",
        "ResponseMetadata",
    }
    item_keys = {
        "Key",
        "Size",
        "LastModified",
        "ETag",
        "ChecksumAlgorithm",
        "ChecksumType",
        "StorageClass",
        "Owner",
        "RestoreStatus",
    }
    while True:
        kwargs = {} if continuation is None else {"ContinuationToken": continuation}
        response = _object(
            reader.list_objects_v2(**kwargs),
            required=set(),
            allowed=response_keys,
            field=f"R2 list response page {page}",
        )
        contents = response.get("Contents", [])
        if not isinstance(contents, list):
            raise ValueError("R2 Contents must be a list")
        if "KeyCount" in response:
            key_count = _integer(response["KeyCount"], "R2 KeyCount")
            if key_count != len(contents):
                raise ValueError("R2 KeyCount must equal the number of Contents items")
        response_token = response.get("ContinuationToken")
        if response_token is not None:
            parsed_response_token = _string(
                response_token, "R2 ContinuationToken"
            )
            if continuation is None or parsed_response_token != continuation:
                raise ValueError("R2 ContinuationToken does not match the request")
        for index, value in enumerate(contents):
            item = _object(
                value,
                required={"Key", "Size"},
                allowed=item_keys,
                field=f"R2 Contents page {page}[{index}]",
            )
            key = _safe_relative(item["Key"], "R2 object key")
            size = _integer(item["Size"], "R2 object size")
            if key in objects:
                raise ValueError("R2 list contains a duplicate object key")
            objects[key] = size

        truncated = response.get("IsTruncated", False)
        if type(truncated) is not bool:
            raise ValueError("R2 IsTruncated must be a boolean")
        if not truncated:
            if "NextContinuationToken" in response:
                raise ValueError(
                    "R2 NextContinuationToken is invalid when IsTruncated is false"
                )
            break
        next_token = _string(
            response.get("NextContinuationToken"), "R2 NextContinuationToken"
        )
        if next_token in seen_tokens:
            raise ValueError("R2 pagination token repeated")
        seen_tokens.add(next_token)
        continuation = next_token
        page += 1
    return objects


def _r2_head(
    reader: R2Reader, key: str
) -> tuple[int, str, str, str]:
    response = reader.head_object(Key=key)
    if not isinstance(response, Mapping) or any(
        not isinstance(item, str) for item in response
    ):
        raise ValueError("R2 head response must be an object with string keys")
    missing = {"ContentLength", "Metadata"}.difference(response)
    if missing:
        raise ValueError(
            f"R2 head response missing required keys: {', '.join(sorted(missing))}"
        )
    # boto/provider transport envelope keys are deliberately ignored here; the
    # integrity-bearing fields below remain exact and fail-closed.
    head = {
        "ContentLength": response["ContentLength"],
        "Metadata": response["Metadata"],
    }
    metadata = _object(
        head["Metadata"],
        required={"sha256", "bundle-id", "camera-key"},
        allowed={"sha256", "bundle-id", "camera-key"},
        field="R2 head Metadata",
    )
    return (
        _integer(head["ContentLength"], "R2 ContentLength", minimum=1),
        _sha(metadata["sha256"], "R2 sha256"),
        _string(metadata["bundle-id"], "R2 bundle-id"),
        _string(metadata["camera-key"], "R2 camera-key"),
    )


def _is_complete_manifest(manifest: Mapping[str, object]) -> bool:
    media = manifest["media"]
    capture = manifest["capture"]
    return bool(
        manifest["mode"] == "production"
        and manifest["partial"] is False
        and abs(float(media["duration_sec"]) - 1800.0) <= 2.0
        and media["codec"] in {"hevc", "h264"}
        and media["width"] == 2880
        and media["height"] == 1620
        and capture["ffmpeg_exit_code"] == 0
        and capture["verified"] is True
        and manifest["upload_status"] == "uploaded"
        and manifest["r2_verified"] is True
    )


def _db_matches_manifest(row: Mapping[str, object], manifest: Mapping[str, object]) -> bool:
    media = manifest["media"]
    video = _video_artifact(manifest)
    return bool(
        row["mode"] == manifest["mode"]
        and row["camera_key"] == manifest["camera_key"]
        and row["night_date"] == manifest["night_date"]
        and row["scheduled_start_utc"] == manifest["scheduled_start_utc"]
        and row["partial"] == manifest["partial"]
        and abs(float(row["duration_sec"]) - float(media["duration_sec"])) < 1e-6
        and row["codec"] == media["codec"]
        and row["width"] == media["width"]
        and row["height"] == media["height"]
        and abs(float(row["fps"]) - float(media["fps"])) < 1e-6
        and row["video_size_bytes"] == video["size_bytes"]
        and row["video_sha256"] == video["sha256"]
        and row["video_r2_key"] == video["r2_key"]
        and row["manifest_r2_key"] == manifest["manifest_r2_key"]
        and row["relative_bundle_path"] == manifest["relative_bundle_path"]
        and row["capture_status"] == "captured"
        and row["upload_status"] == "uploaded"
    )


def _record(manifest: Mapping[str, object]) -> dict[str, object]:
    media = manifest["media"]
    video = _video_artifact(manifest)
    camera = str(manifest["camera_key"])
    camera_night = f"{camera}/{manifest['night_date']}"
    return {
        "source_ref": manifest["relative_bundle_path"],
        "source_sha256": video["sha256"],
        "anonymous_camera_digest": _camera_digest(camera),
        "camera_night": hashlib.sha256(
            f"camera-night:{camera_night}".encode("utf-8")
        ).hexdigest(),
        "scheduled_start_utc": manifest["scheduled_start_utc"],
        "duration_sec": media["duration_sec"],
        "width": media["width"],
        "height": media["height"],
        "fps": media["fps"],
        "codec": media["codec"],
    }


def _camera_digest(camera_key: str) -> str:
    return hashlib.sha256(f"camera:{camera_key}".encode("utf-8")).hexdigest()


def collect_inventory(
    local_root: Path,
    r2_reader: R2Reader,
    db_reader: DbReader,
    *,
    test_sheet_sha256: str,
    expected_slots: Mapping[str, object],
) -> dict[str, object]:
    """Build a private, fail-closed inventory without any source mutation."""
    sheet_sha = _sha(test_sheet_sha256, "test_sheet_sha256")
    expected_slot_set = _expected_slot_set(
        expected_slots, test_sheet_sha256=sheet_sha
    )
    root = Path(local_root)
    root_fd = _open_root_fd(root)
    try:
        local_entries = _scan_local(root_fd)
    finally:
        os.close(root_fd)
    manifests = [entry[0] for entry in local_entries]
    local_identity = {
        str(entry[0]["bundle_id"]): (entry[1], entry[2]) for entry in local_entries
    }
    local_counts = Counter(str(item["bundle_id"]) for item in manifests)
    local_by_id = {str(item["bundle_id"]): item for item in manifests}

    db_rows = _db_rows(db_reader)
    db_counts = Counter(str(item["bundle_id"]) for item in db_rows)
    db_by_id = {str(item["bundle_id"]): item for item in db_rows}
    r2_objects = _r2_listing(r2_reader)

    all_ids = sorted(set(local_by_id) | set(db_by_id))
    reasons: dict[str, set[str]] = defaultdict(set)
    matched_ids: set[str] = set()
    decode_failures = 0

    def bundle_entity(bundle_id: str) -> str:
        return f"bundle:{bundle_id}"

    def slot_entity(slot: tuple[str, str, str]) -> str:
        return "slot:" + "|".join(slot)

    local_slots = [
        (
            _camera_digest(str(manifest["camera_key"])),
            str(manifest["night_date"]),
            str(manifest["scheduled_start_utc"]),
        )
        for manifest in manifests
    ]
    local_slot_counts = Counter(local_slots)
    for slot, count in local_slot_counts.items():
        if count != 1:
            reasons[slot_entity(slot)].add("duplicate_actual_slot")
        if slot not in expected_slot_set:
            reasons[slot_entity(slot)].add("unexpected_actual_slot")
    for slot in expected_slot_set.difference(local_slot_counts):
        reasons[slot_entity(slot)].add("missing_expected_slot")

    declared_video_keys = {
        str(_video_artifact(manifest)["r2_key"]) for manifest in manifests
    } | {str(row["video_r2_key"]) for row in db_rows}
    for key in r2_objects:
        if key.endswith("/video.mp4") and key not in declared_video_keys:
            reasons[f"r2-video:{key}"].add("orphan_r2_video")

    for bundle_id, count in local_counts.items():
        if count != 1:
            reasons[bundle_entity(bundle_id)].add("duplicate_local_bundle_id")
    for bundle_id, count in db_counts.items():
        if count != 1:
            reasons[bundle_entity(bundle_id)].add("duplicate_db_bundle_id")

    for bundle_id in all_ids:
        entity = bundle_entity(bundle_id)
        manifest = local_by_id.get(bundle_id)
        row = db_by_id.get(bundle_id)
        if manifest is None:
            reasons[entity].add("missing_local_bundle")
        if row is None:
            reasons[entity].add("missing_db_row")
        if manifest is None:
            if row is not None:
                video_key = str(row["video_r2_key"])
                if video_key not in r2_objects:
                    reasons[entity].add("missing_r2_video")
                else:
                    r2_size, r2_sha, r2_bundle, r2_camera = _r2_head(
                        r2_reader, video_key
                    )
                    if r2_objects[video_key] != r2_size:
                        reasons[entity].add("r2_list_head_size_mismatch")
                    if (r2_size, r2_sha) != (
                        row["video_size_bytes"],
                        row["video_sha256"],
                    ):
                        reasons[entity].add("r2_video_identity_mismatch")
                    if r2_bundle != bundle_id:
                        reasons[entity].add("r2_bundle_identity_mismatch")
                    if r2_camera != row["camera_key"]:
                        reasons[entity].add("r2_camera_identity_mismatch")
            continue

        video = _video_artifact(manifest)
        local_size, local_sha = local_identity[bundle_id]
        if (local_size, local_sha) != (video["size_bytes"], video["sha256"]):
            reasons[entity].add("local_video_identity_mismatch")

        capture = manifest["capture"]
        if capture["verified"] is not True:
            decode_failures += 1
            reasons[entity].add("recorded_decode_probe_failure")
        if not _is_complete_manifest(manifest):
            reasons[entity].add("incomplete_source_contract")

        video_key = str(video["r2_key"])
        if video_key not in r2_objects:
            reasons[entity].add("missing_r2_video")
        else:
            r2_size, r2_sha, r2_bundle, r2_camera = _r2_head(r2_reader, video_key)
            if r2_objects[video_key] != r2_size:
                reasons[entity].add("r2_list_head_size_mismatch")
            if (r2_size, r2_sha) != (video["size_bytes"], video["sha256"]):
                reasons[entity].add("r2_video_identity_mismatch")
            if r2_bundle != bundle_id:
                reasons[entity].add("r2_bundle_identity_mismatch")
            if r2_camera != manifest["camera_key"]:
                reasons[entity].add("r2_camera_identity_mismatch")

        if row is not None and not _db_matches_manifest(row, manifest):
            reasons[entity].add("db_manifest_mismatch")

        slot = (
            _camera_digest(str(manifest["camera_key"])),
            str(manifest["night_date"]),
            str(manifest["scheduled_start_utc"]),
        )
        if entity not in reasons and slot_entity(slot) not in reasons:
            matched_ids.add(bundle_id)

    mismatch_entities = sorted(entity for entity, values in reasons.items() if values)
    matched_slots = {
        (
            _camera_digest(str(local_by_id[bundle_id]["camera_key"])),
            str(local_by_id[bundle_id]["night_date"]),
            str(local_by_id[bundle_id]["scheduled_start_utc"]),
        )
        for bundle_id in matched_ids
    }
    complete_nights = {
        (camera, night)
        for camera, night in {(slot[0], slot[1]) for slot in expected_slot_set}
        if {
            slot
            for slot in expected_slot_set
            if slot[0] == camera and slot[1] == night
        }.issubset(matched_slots)
    }
    missing_slot_count = len(expected_slot_set.difference(matched_slots))
    records = [_record(manifest) for manifest in manifests]
    inventory: dict[str, object] = {
        "schema": SCHEMA,
        "status": READY if not mismatch_entities else MISMATCH,
        "test_sheet_sha256": sheet_sha,
        "expected_slot_count": len(expected_slot_set),
        "actual_bundle_count": len(manifests),
        "complete_camera_night_count": len(complete_nights),
        "missing_slot_count": missing_slot_count,
        "mismatch_count": len(mismatch_entities),
        "decode_probe_failure_count": decode_failures,
        "storage_match_count": len(matched_ids),
        "records": records,
        "mismatches": [
            {
                "entity_digest": hashlib.sha256(entity.encode("utf-8")).hexdigest(),
                "reasons": sorted(reasons[entity]),
            }
            for entity in mismatch_entities
        ],
        **WRITE_COUNTS,
    }
    return inventory


def inventory_public_summary(inventory: Mapping[str, object]) -> dict[str, object]:
    """Return the exact aggregate-only public inventory projection."""
    parsed = _object(
        inventory,
        required=_INVENTORY_KEYS,
        allowed=_INVENTORY_KEYS,
        field="inventory",
    )
    if parsed["schema"] != SCHEMA:
        raise ValueError("inventory schema is invalid")
    for field in (
        "expected_slot_count",
        "actual_bundle_count",
        "complete_camera_night_count",
        "missing_slot_count",
        "mismatch_count",
        "decode_probe_failure_count",
        "storage_match_count",
    ):
        _integer(parsed[field], f"inventory.{field}")
    for field in WRITE_COUNTS:
        if parsed[field] != 0 or type(parsed[field]) is not int:
            raise ValueError(f"inventory.{field} must be literal integer 0")
    return {
        "schema": SUMMARY_SCHEMA,
        "expected_slot_count": parsed["expected_slot_count"],
        "actual_bundle_count": parsed["actual_bundle_count"],
        "complete_camera_night_count": parsed["complete_camera_night_count"],
        "missing_slot_count": parsed["missing_slot_count"],
        "mismatch_count": parsed["mismatch_count"],
        "decode_probe_failure_count": parsed["decode_probe_failure_count"],
    }

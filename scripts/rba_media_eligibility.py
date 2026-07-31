"""R2 LIST 기반 사건 묶기 source eligibility 계약."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from scripts.rba_event_grouping_core import (
    ACTIVE_EXCLUSION_STATES,
    ExclusionState,
)

ALGORITHM_VERSION = "r2-list-intersection-v1"
BLOCKED_MEDIA_INVENTORY_FAILED = "BLOCKED_MEDIA_INVENTORY_FAILED"
DEFAULT_MAX_PAGES = 10_000


class MediaInventoryError(RuntimeError):
    """R2 inventory를 source eligibility로 안전하게 동결할 수 없을 때."""


@dataclass(frozen=True, slots=True)
class SourceKeyIndex:
    key_to_clip_id: Mapping[str, str]
    missing_key_clip_ids: frozenset[str]
    duplicate_key_clip_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class MediaInventory:
    available_clip_ids: frozenset[str]
    missing_key_clip_ids: frozenset[str]
    duplicate_key_clip_ids: frozenset[str]
    absent_object_clip_ids: frozenset[str]
    page_count: int
    started_at: datetime
    finished_at: datetime
    inventory_sha256: str

    @property
    def unavailable_clip_ids(self) -> frozenset[str]:
        return frozenset(
            set(self.missing_key_clip_ids)
            | set(self.duplicate_key_clip_ids)
            | set(self.absent_object_clip_ids)
        )

    def manifest_provenance(self) -> dict[str, object]:
        """동일 inventory에서 wall-clock과 무관하게 같은 hash 입력을 만든다."""

        return {
            "algorithm_version": ALGORITHM_VERSION,
            "page_count": self.page_count,
            "available_count": len(self.available_clip_ids),
            "unavailable_count": len(self.unavailable_clip_ids),
            "missing_key_count": len(self.missing_key_clip_ids),
            "duplicate_key_count": len(self.duplicate_key_clip_ids),
            "absent_object_count": len(self.absent_object_clip_ids),
            "inventory_sha256": self.inventory_sha256,
        }


def _fail() -> MediaInventoryError:
    return MediaInventoryError(BLOCKED_MEDIA_INVENTORY_FAILED)


def build_source_key_index(
    rows: Iterable[Mapping[str, object]],
) -> SourceKeyIndex:
    ids_by_key: dict[str, list[str]] = {}
    missing: set[str] = set()
    seen_ids: set[str] = set()
    try:
        for row in rows:
            clip_id = str(row["id"])
            if not clip_id or clip_id in seen_ids:
                raise _fail()
            seen_ids.add(clip_id)
            key = str(row.get("r2_key") or "").strip()
            if not key:
                missing.add(clip_id)
                continue
            ids_by_key.setdefault(key, []).append(clip_id)
    except MediaInventoryError:
        raise
    except Exception:
        raise _fail() from None

    unique: dict[str, str] = {}
    duplicate_ids: set[str] = set()
    for key, clip_ids in ids_by_key.items():
        if len(clip_ids) == 1:
            unique[key] = clip_ids[0]
        else:
            duplicate_ids.update(clip_ids)
    return SourceKeyIndex(
        key_to_clip_id=MappingProxyType(unique),
        missing_key_clip_ids=frozenset(missing),
        duplicate_key_clip_ids=frozenset(duplicate_ids),
    )


def _validated_contents(response: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(response, Mapping):
        raise _fail()
    metadata = response.get("ResponseMetadata")
    if (
        not isinstance(metadata, Mapping)
        or metadata.get("HTTPStatusCode") != 200
    ):
        raise _fail()
    truncated = response.get("IsTruncated")
    key_count = response.get("KeyCount")
    if (
        not isinstance(truncated, bool)
        or not isinstance(key_count, int)
        or isinstance(key_count, bool)
        or key_count < 0
    ):
        raise _fail()
    contents = response.get("Contents")
    if key_count == 0 and contents is None:
        return ()
    if not isinstance(contents, list) or len(contents) != key_count:
        raise _fail()
    if not all(isinstance(row, Mapping) for row in contents):
        raise _fail()
    return tuple(contents)


def _key_and_size(row: Mapping[str, object]) -> tuple[str, int]:
    key = row.get("Key")
    size = row.get("Size")
    if (
        not isinstance(key, str)
        or not key
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
    ):
        raise _fail()
    return key, size


def _inventory_digest(
    *,
    available: set[str],
    missing: frozenset[str],
    duplicate: frozenset[str],
    absent: set[str],
) -> str:
    rows = [
        *(f"available\0{clip_id}" for clip_id in sorted(available)),
        *(f"missing_key\0{clip_id}" for clip_id in sorted(missing)),
        *(f"duplicate_key\0{clip_id}" for clip_id in sorted(duplicate)),
        *(f"absent_object\0{clip_id}" for clip_id in sorted(absent)),
    ]
    encoded = (
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def list_media_inventory(
    client: object,
    *,
    bucket: str,
    source_index: SourceKeyIndex,
    max_pages: int = DEFAULT_MAX_PAGES,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> MediaInventory:
    if not bucket or max_pages <= 0:
        raise _fail()
    started_at = clock()
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise _fail()
    token: str | None = None
    seen_tokens: set[str] = set()
    seen_source_keys: set[str] = set()
    available: set[str] = set()
    page_count = 0
    try:
        for page_count in range(1, max_pages + 1):
            kwargs: dict[str, object] = {"Bucket": bucket}
            if token is not None:
                kwargs["ContinuationToken"] = token
            response = client.list_objects_v2(**kwargs)  # type: ignore[attr-defined]
            contents = _validated_contents(response)
            for row in contents:
                key, size = _key_and_size(row)
                clip_id = source_index.key_to_clip_id.get(key)
                if clip_id is None:
                    continue
                if key in seen_source_keys:
                    raise _fail()
                seen_source_keys.add(key)
                if size > 0:
                    available.add(clip_id)
            if not response["IsTruncated"]:  # type: ignore[index]
                break
            next_token = response.get("NextContinuationToken")  # type: ignore[union-attr]
            if (
                not isinstance(next_token, str)
                or not next_token
                or next_token in seen_tokens
            ):
                raise _fail()
            seen_tokens.add(next_token)
            token = next_token
        else:
            raise _fail()
    except MediaInventoryError:
        raise
    except Exception:
        raise _fail() from None

    finished_at = clock()
    if finished_at.tzinfo is None or finished_at.utcoffset() is None:
        raise _fail()
    absent = set(source_index.key_to_clip_id.values()) - available
    return MediaInventory(
        available_clip_ids=frozenset(available),
        missing_key_clip_ids=source_index.missing_key_clip_ids,
        duplicate_key_clip_ids=source_index.duplicate_key_clip_ids,
        absent_object_clip_ids=frozenset(absent),
        page_count=page_count,
        started_at=started_at.astimezone(UTC),
        finished_at=finished_at.astimezone(UTC),
        inventory_sha256=_inventory_digest(
            available=available,
            missing=source_index.missing_key_clip_ids,
            duplicate=source_index.duplicate_key_clip_ids,
            absent=absent,
        ),
    )


def merge_media_integrity_exclusions(
    existing: Mapping[str, ExclusionState],
    *,
    missing_key_clip_ids: frozenset[str],
    duplicate_key_clip_ids: frozenset[str],
    absent_object_clip_ids: frozenset[str],
) -> dict[str, ExclusionState]:
    categories = (
        (missing_key_clip_ids, "r2_key_missing"),
        (duplicate_key_clip_ids, "r2_key_duplicate"),
        (absent_object_clip_ids, "r2_object_absent"),
    )
    combined: set[str] = set()
    for clip_ids, _ in categories:
        if combined.intersection(clip_ids):
            raise _fail()
        combined.update(clip_ids)

    result = dict(existing)
    for clip_ids, reason_code in categories:
        for clip_id in clip_ids:
            current = result.get(clip_id)
            if current is not None and current.state in ACTIVE_EXCLUSION_STATES:
                continue
            result[clip_id] = ExclusionState(
                clip_id=clip_id,
                state="media_deleted",
                reason_code=reason_code,
                rule_version=ALGORITHM_VERSION,
            )
    return result

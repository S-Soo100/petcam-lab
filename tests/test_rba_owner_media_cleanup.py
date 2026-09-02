from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scripts.rba_owner_media_cleanup import (
    CleanupItem,
    FrozenCounts,
    ObjectHead,
    build_excluded_key,
    build_quarantine_key,
    same_r2_object,
    validate_frozen_counts,
)


def _item(index: int, reason: str, *, has_gt: bool = False) -> CleanupItem:
    return CleanupItem(
        clip_id=f"00000000-0000-4000-8000-{index:012d}",
        camera_id="10000000-0000-4000-8000-000000000001",
        started_at="2026-06-30T00:00:00+00:00",
        seed_reason=reason,
        has_canonical_gt=has_gt,
        source_r2_key=f"clips/camera/day/{index}.mp4",
        source_thumbnail_key=None,
        video_head=None,
        thumbnail_head=None,
    )


def test_keys_are_deterministic_and_keep_original_hierarchy() -> None:
    clip_id = "00000000-0000-4000-8000-000000000001"
    original = "clips/camera/date/file.mp4"
    assert build_quarantine_key(original, clip_id) == (
        "research-quarantine/rba-owner-cleanup-v1/"
        f"{clip_id}/{original}"
    )
    assert build_excluded_key(original, clip_id) == (
        "research-excluded/rba-owner-cleanup-v1/"
        f"{clip_id}/{original}"
    )


@pytest.mark.parametrize("key", ["", " ", "/absolute.mp4", "../escape.mp4", "a/../b.mp4"])
def test_keys_reject_blank_absolute_and_traversal(key: str) -> None:
    with pytest.raises(ValueError):
        build_quarantine_key(key, "00000000-0000-4000-8000-000000000001")


def test_exact_frozen_counts_pass() -> None:
    items = [
        *(_item(i, "confirmed_gecko_absent") for i in range(23)),
        *(_item(i + 23, "confirmed_no_gecko_activity") for i in range(23)),
        _item(46, "protected_gt", has_gt=True),
        *(_item(i + 47, "owner_review_pending") for i in range(904)),
    ]
    assert validate_frozen_counts(items) == FrozenCounts(951, 46, 1, 904)


def test_duplicate_clip_fails_closed() -> None:
    duplicate = _item(1, "confirmed_gecko_absent")
    with pytest.raises(ValueError, match="duplicate"):
        validate_frozen_counts([duplicate, duplicate])


def test_confirmed_invalid_with_gt_fails_closed() -> None:
    with pytest.raises(ValueError, match="canonical_gt"):
        validate_frozen_counts([_item(1, "confirmed_gecko_absent", has_gt=True)])


def test_wrong_counts_fail_closed() -> None:
    with pytest.raises(ValueError, match="frozen_counts"):
        validate_frozen_counts([_item(1, "owner_review_pending")])


def test_r2_head_equality_uses_size_and_etag() -> None:
    when = datetime(2026, 8, 3, tzinfo=UTC)
    source = ObjectHead(100, '"abc"', when, None)
    same = ObjectHead(100, "abc", when, None)
    wrong_size = ObjectHead(99, "abc", when, None)
    wrong_etag = ObjectHead(100, "def", when, None)
    assert same_r2_object(source, same)
    assert not same_r2_object(source, wrong_size)
    assert not same_r2_object(source, wrong_etag)


def test_r2_head_can_use_matching_content_sha_metadata() -> None:
    when = datetime(2026, 8, 3, tzinfo=UTC)
    source = ObjectHead(100, "multipart-a", when, "a" * 64)
    copied = ObjectHead(100, "multipart-b", when, "a" * 64)
    assert same_r2_object(source, copied)

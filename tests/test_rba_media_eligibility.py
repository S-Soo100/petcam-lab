from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scripts.rba_event_grouping_core import ExclusionState
from scripts.rba_media_eligibility import (
    ALGORITHM_VERSION,
    BLOCKED_MEDIA_INVENTORY_FAILED,
    MediaInventoryError,
    build_source_key_index,
    list_media_inventory,
    merge_media_integrity_exclusions,
)


class ListClient:
    def __init__(self, pages: list[object]) -> None:
        self.pages = list(pages)
        self.tokens: list[str | None] = []

    def list_objects_v2(self, **kwargs: object) -> object:
        self.tokens.append(kwargs.get("ContinuationToken"))  # type: ignore[arg-type]
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return page


def page(
    contents: list[dict[str, object]] | None,
    *,
    truncated: bool = False,
    token: str | None = None,
    key_count: int | None = None,
    status: int = 200,
) -> dict[str, object]:
    result: dict[str, object] = {
        "ResponseMetadata": {"HTTPStatusCode": status},
        "KeyCount": len(contents) if key_count is None and contents is not None else key_count,
        "IsTruncated": truncated,
    }
    if contents is not None:
        result["Contents"] = contents
    if token is not None:
        result["NextContinuationToken"] = token
    return result


def test_source_key_index_separates_missing_and_duplicate_keys() -> None:
    result = build_source_key_index(
        (
            {"id": "a", "r2_key": " motion/a.mp4 "},
            {"id": "b", "r2_key": None},
            {"id": "c", "r2_key": "same.mp4"},
            {"id": "d", "r2_key": "same.mp4"},
            {"id": "e", "r2_key": "same.mp4"},
        )
    )

    assert dict(result.key_to_clip_id) == {"motion/a.mp4": "a"}
    assert result.missing_key_clip_ids == frozenset({"b"})
    assert result.duplicate_key_clip_ids == frozenset({"c", "d", "e"})


def test_inventory_reads_every_page_and_ignores_unrelated_keys() -> None:
    index = build_source_key_index(
        (
            {"id": "a", "r2_key": "motion/a.mp4"},
            {"id": "b", "r2_key": None},
            {"id": "c", "r2_key": "motion/c.mp4"},
            {"id": "d", "r2_key": "same.mp4"},
            {"id": "e", "r2_key": "same.mp4"},
        )
    )
    client = ListClient(
        [
            page(
                [
                    {"Key": "motion/a.mp4", "Size": 10},
                    {"Key": "unrelated.mp4", "Size": 99},
                ],
                truncated=True,
                token="next",
            ),
            page([{"Key": "motion/c.mp4", "Size": 0}]),
        ]
    )

    result = list_media_inventory(client, bucket="bucket", source_index=index)

    assert result.available_clip_ids == frozenset({"a"})
    assert result.missing_key_clip_ids == frozenset({"b"})
    assert result.duplicate_key_clip_ids == frozenset({"d", "e"})
    assert result.absent_object_clip_ids == frozenset({"c"})
    assert result.unavailable_clip_ids == frozenset({"b", "c", "d", "e"})
    assert result.page_count == 2
    assert client.tokens == [None, "next"]
    assert len(result.inventory_sha256) == 64


def test_empty_bucket_page_may_omit_contents() -> None:
    index = build_source_key_index(({"id": "a", "r2_key": "a.mp4"},))
    client = ListClient([page(None, key_count=0)])

    result = list_media_inventory(client, bucket="bucket", source_index=index)

    assert result.available_clip_ids == frozenset()
    assert result.absent_object_clip_ids == frozenset({"a"})


@pytest.mark.parametrize(
    "bad_page",
    [
        page([], status=403),
        {"ResponseMetadata": {"HTTPStatusCode": 200}, "KeyCount": 0, "IsTruncated": "false"},
        page(None, key_count=1),
        page([], key_count=1),
        page([{"Key": "a.mp4", "Size": -1}]),
        page([{"Key": "a.mp4", "Size": True}]),
        page([{"Key": "", "Size": 1}]),
    ],
)
def test_invalid_inventory_pages_fail_without_key_leak(
    bad_page: dict[str, object],
) -> None:
    index = build_source_key_index(({"id": "a", "r2_key": "a.mp4"},))

    with pytest.raises(MediaInventoryError, match=BLOCKED_MEDIA_INVENTORY_FAILED) as error:
        list_media_inventory(ListClient([bad_page]), bucket="bucket", source_index=index)

    assert "a.mp4" not in str(error.value)


def test_inventory_rejects_missing_or_repeated_continuation_token() -> None:
    index = build_source_key_index(({"id": "a", "r2_key": "a.mp4"},))
    missing = ListClient([page([], truncated=True)])
    with pytest.raises(MediaInventoryError, match=BLOCKED_MEDIA_INVENTORY_FAILED):
        list_media_inventory(missing, bucket="bucket", source_index=index)

    repeated = ListClient(
        [
            page([], truncated=True, token="same"),
            page([], truncated=True, token="same"),
        ]
    )
    with pytest.raises(MediaInventoryError, match=BLOCKED_MEDIA_INVENTORY_FAILED):
        list_media_inventory(repeated, bucket="bucket", source_index=index)


def test_inventory_wraps_sdk_failure_without_message_leak() -> None:
    index = build_source_key_index(({"id": "a", "r2_key": "secret/a.mp4"},))
    client = ListClient([RuntimeError("secret/a.mp4 credential detail")])

    with pytest.raises(MediaInventoryError) as error:
        list_media_inventory(client, bucket="bucket", source_index=index)

    assert str(error.value) == BLOCKED_MEDIA_INVENTORY_FAILED


def test_inventory_provenance_is_independent_of_wall_clock() -> None:
    index = build_source_key_index(({"id": "a", "r2_key": "a.mp4"},))
    first = list_media_inventory(
        ListClient([page([{"Key": "a.mp4", "Size": 10}])]),
        bucket="bucket",
        source_index=index,
        clock=iter(
            (
                datetime(2026, 7, 31, 1, tzinfo=UTC),
                datetime(2026, 7, 31, 1, 0, 1, tzinfo=UTC),
            )
        ).__next__,
    )
    second = list_media_inventory(
        ListClient([page([{"Key": "a.mp4", "Size": 10}])]),
        bucket="bucket",
        source_index=index,
        clock=iter(
            (
                datetime(2026, 7, 31, 2, tzinfo=UTC),
                datetime(2026, 7, 31, 2, 0, 1, tzinfo=UTC),
            )
        ).__next__,
    )

    assert first.manifest_provenance() == second.manifest_provenance()
    assert "started_at" not in first.manifest_provenance()
    assert first.started_at != second.started_at


def test_media_reasons_are_distinct_and_active_exclusion_wins() -> None:
    existing = {
        "active": ExclusionState("active", "quarantined", "short", "v1"),
        "restored": ExclusionState("restored", "restored", "old", "v0"),
    }

    merged = merge_media_integrity_exclusions(
        existing,
        missing_key_clip_ids=frozenset({"missing"}),
        duplicate_key_clip_ids=frozenset({"duplicate"}),
        absent_object_clip_ids=frozenset({"active", "restored"}),
    )

    assert merged["active"].reason_code == "short"
    assert merged["missing"].reason_code == "r2_key_missing"
    assert merged["duplicate"].reason_code == "r2_key_duplicate"
    assert merged["restored"].reason_code == "r2_object_absent"
    assert merged["restored"].state == "media_deleted"
    assert merged["restored"].rule_version == ALGORITHM_VERSION

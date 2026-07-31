from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.run_rba_event_grouping_shadow import (
    ALLOWED_TABLES,
    SafetyContractError,
    load_blocked_manifests,
    load_select_snapshots,
    paginated_select,
    parse_as_of,
)


class Response:
    def __init__(self, data: list[dict[str, object]]) -> None:
        self.data = data


class Query:
    def __init__(self, pages: list[list[dict[str, object]]]) -> None:
        self.pages = pages
        self.ranges: list[tuple[int, int]] = []
        self.filters: list[tuple[str, str, object]] = []

    def select(self, columns: str) -> Query:
        self.columns = columns
        return self

    def lt(self, column: str, value: object) -> Query:
        self.filters.append(("lt", column, value))
        return self

    def eq(self, column: str, value: object) -> Query:
        self.filters.append(("eq", column, value))
        return self

    def range(self, start: int, end: int) -> Query:
        self.ranges.append((start, end))
        self.page_index = start // 2
        return self

    def execute(self) -> Response:
        return Response(self.pages[self.page_index])


class Client:
    def __init__(self, tables: dict[str, list[list[dict[str, object]]]]) -> None:
        self.tables = tables
        self.queries: dict[str, Query] = {}

    def table(self, name: str) -> Query:
        query = Query(self.tables[name])
        self.queries[name] = query
        return query


def test_source_has_no_forbidden_calls_or_inputs() -> None:
    source = Path("scripts/run_rba_event_grouping_shadow.py").read_text()
    forbidden = (
        ".insert(",
        ".update(",
        ".upsert(",
        ".delete(",
        ".rpc(",
        "clip_python_evidence",
        "clip_prelabels",
        "activity_assessment",
        "gate",
        "behavior_logs",
        "behavior_labels",
        "clip_vlm_jobs",
        "boto3",
        "r2_key",
        "signed_url",
    )
    assert not [token for token in forbidden if token in source.lower()]
    assert ALLOWED_TABLES == {
        "motion_clips",
        "motion_clip_system_exclusions",
        "motion_clip_review_slots",
    }


def test_paginated_select_reads_every_page_and_detects_duplicates() -> None:
    query = Query([[{"id": "a"}, {"id": "b"}], [{"id": "c"}]])
    rows = paginated_select(query, page_size=2, identity_field="id")
    assert [row["id"] for row in rows] == ["a", "b", "c"]
    assert query.ranges == [(0, 1), (2, 3)]

    duplicate = Query([[{"id": "a"}, {"id": "b"}], [{"id": "a"}]])
    with pytest.raises(SafetyContractError, match="duplicate"):
        paginated_select(duplicate, page_size=2, identity_field="id")


def test_three_snapshots_use_only_frozen_queries() -> None:
    client = Client(
        {
            "motion_clips": [[{"id": "a"}]],
            "motion_clip_system_exclusions": [[{"clip_id": "a"}]],
            "motion_clip_review_slots": [[{"clip_id": "b"}]],
        }
    )
    snapshots = load_select_snapshots(client, page_size=1000)
    assert set(snapshots) == ALLOWED_TABLES
    clips = client.queries["motion_clips"]
    assert clips.columns == "id,camera_id,started_at,duration_sec"
    assert clips.filters[0][0:2] == ("lt", "started_at")
    slots = client.queries["motion_clip_review_slots"]
    assert slots.filters == [("eq", "cohort_kind", "canary")]


def test_blocked_manifests_accept_only_named_uuid_fields(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    first.write_text(
        json.dumps(
            {
                "clip_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "ignored": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "selected": [
                    {"clip_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc"}
                ],
            }
        )
    )
    second = tmp_path / "second.csv"
    with second.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["durable_key", "other"])
        writer.writeheader()
        writer.writerow(
            {
                "durable_key": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                "other": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
            }
        )
    blocked, digest = load_blocked_manifests(
        [first, second], allowed_roots=(tmp_path,)
    )
    assert blocked == frozenset(
        {
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        }
    )
    assert len(digest) == 64


def test_blocked_manifest_rejects_empty_and_escaped_symlink(tmp_path: Path) -> None:
    empty = tmp_path / "empty.json"
    empty.write_text("{}")
    with pytest.raises(SafetyContractError, match="empty"):
        load_blocked_manifests([empty], allowed_roots=(tmp_path,))

    outside = tmp_path.parent / "outside-blocked.json"
    outside.write_text(
        '{"clip_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}'
    )
    link = tmp_path / "escape.json"
    link.symlink_to(outside)
    try:
        with pytest.raises(SafetyContractError, match="root"):
            load_blocked_manifests([link], allowed_roots=(tmp_path,))
    finally:
        outside.unlink()


def test_as_of_is_aware_and_after_cutoff() -> None:
    assert parse_as_of("2026-07-31T04:00:00+09:00").tzinfo is not None
    with pytest.raises(SafetyContractError):
        parse_as_of("2026-07-30T04:00:00+09:00")
    with pytest.raises(SafetyContractError):
        parse_as_of("2026-07-31T04:00:00")

from __future__ import annotations

import json
import stat
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from scripts.prepare_rba_event_grouping_shadow import (
    BLOCKED_INSUFFICIENT_BOUNDARY_PAIRS,
    BLOCKED_SELECTOR_SEARCH_EXHAUSTED,
    BoundaryPair,
    BoundarySelectionBlocked,
    build_adjacent_pairs,
    build_blank_worksheet,
    build_private_manifest,
    build_public_summary,
    search_boundary_selection,
    select_boundary_pairs,
    split_camera_nights,
    write_private_new,
)
from scripts.rba_event_grouping_core import AccountedClip


def row(
    clip_id: str,
    *,
    camera: str = "cam-a",
    day: date = date(2026, 7, 1),
    at: float = 0,
    duration: float = 10,
    kind: str = "activity_candidate",
) -> AccountedClip:
    return AccountedClip(
        clip_id=clip_id,
        camera_id=camera,
        started_at=datetime(2026, 7, 1, tzinfo=UTC) + timedelta(
            days=day.day - 1,
            seconds=at,
        ),
        activity_day_kst=day,
        duration_sec=duration,
        kind=kind,  # type: ignore[arg-type]
        reason_code=None if kind == "activity_candidate" else "probe",
    )


def pair(
    name: str,
    *,
    camera: str,
    day: date,
    gap: float,
    gap_bin: str,
) -> BoundaryPair:
    return BoundaryPair(
        pair_id=f"pair-{name}",
        left_clip_id=f"left-{name}",
        right_clip_id=f"right-{name}",
        camera_id=camera,
        activity_day_kst=day,
        gap_sec=gap,
        gap_bin=gap_bin,  # type: ignore[arg-type]
    )


def rich_pair_population() -> tuple[BoundaryPair, ...]:
    pairs: list[BoundaryPair] = []
    bins = (("le30", 5.0), ("30to60", 45.0), ("60to300", 120.0))
    for camera in ("cam-a", "cam-b"):
        for day_number in range(1, 7):
            day = date(2026, 7, day_number)
            for gap_bin, gap in bins:
                for index in range(12):
                    pairs.append(
                        pair(
                            f"{camera}-{day_number}-{gap_bin}-{index}",
                            camera=camera,
                            day=day,
                            gap=gap,
                            gap_bin=gap_bin,
                        )
                    )
    return tuple(pairs)


def test_adjacent_pairs_only_use_immediate_activity_neighbors() -> None:
    rows = (
        row("a", at=0),
        row("b", at=15),  # gap 5
        row("blocked", at=30, kind="blocked_research"),
        row("c", at=31),
        row("d", at=401),  # gap 360, outside GT candidate range
    )
    pairs = build_adjacent_pairs(rows)
    assert [(item.left_clip_id, item.right_clip_id) for item in pairs] == [
        ("a", "b"),
    ]
    assert pairs[0].gap_bin == "le30"
    assert len(pairs[0].pair_id) == 64


def test_pair_id_and_build_are_order_independent() -> None:
    rows = (row("a", at=0), row("b", at=41))
    first = build_adjacent_pairs(rows)
    second = build_adjacent_pairs(tuple(reversed(rows)))
    assert first == second
    assert first[0].gap_bin == "30to60"


def test_split_and_selection_meet_exact_frozen_contract() -> None:
    pairs = rich_pair_population()
    split, selected = search_boundary_selection(
        pairs, "rba-event-grouping-shadow-v2", max_attempts=20
    )

    assert len(split.development_nights) == 6
    assert len(split.holdout_nights) == 6
    assert set(split.development_nights).isdisjoint(split.holdout_nights)
    assert len(selected) == 120

    clip_ids = [
        clip_id
        for item in selected
        for clip_id in (item.left_clip_id, item.right_clip_id)
    ]
    assert len(clip_ids) == len(set(clip_ids))

    for split_name, nights in (
        ("development", set(split.development_nights)),
        ("holdout", set(split.holdout_nights)),
    ):
        scoped = [
            item
            for item in selected
            if (item.camera_id, item.activity_day_kst) in nights
        ]
        assert len(scoped) == 60, split_name
        for gap_bin in ("le30", "30to60", "60to300"):
            assert sum(item.gap_bin == gap_bin for item in scoped) == 20
        counts: dict[str, int] = {}
        for item in scoped:
            counts[item.camera_id] = counts.get(item.camera_id, 0) + 1
        assert max(counts.values()) <= 36


def test_selection_fails_closed_without_exact_inventory() -> None:
    pairs = rich_pair_population()
    sparse = tuple(item for item in pairs if item.gap_bin != "60to300")
    with pytest.raises(
        BoundarySelectionBlocked,
        match=BLOCKED_INSUFFICIENT_BOUNDARY_PAIRS,
    ):
        split_camera_nights(sparse, "rba-event-grouping-shadow-v2")


def test_bounded_search_is_order_independent_and_records_provenance() -> None:
    pairs = rich_pair_population()
    first_split, first_selected = search_boundary_selection(
        pairs, "rba-event-grouping-shadow-v2", max_attempts=20
    )
    second_split, second_selected = search_boundary_selection(
        tuple(reversed(pairs)),
        "rba-event-grouping-shadow-v2",
        max_attempts=20,
    )
    assert first_split == second_split
    assert first_selected == second_selected
    assert 0 <= first_split.search_attempt < 20
    assert set(first_split.selection_order) == {
        "le30",
        "30to60",
        "60to300",
    }


def test_bounded_search_reports_search_exhaustion_separately() -> None:
    with pytest.raises(
        BoundarySelectionBlocked,
        match=BLOCKED_SELECTOR_SEARCH_EXHAUSTED,
    ):
        search_boundary_selection(
            rich_pair_population(),
            "rba-event-grouping-shadow-v2",
            max_attempts=0,
        )


def test_split_can_choose_twelve_nights_from_seven_camera_pairs() -> None:
    pairs: list[BoundaryPair] = []
    for camera_index in range(7):
        camera = f"cam-{camera_index}"
        for day_number in (1, 2):
            for gap_bin, gap in (
                ("le30", 5.0),
                ("30to60", 45.0),
                ("60to300", 120.0),
            ):
                for pair_index in range(12):
                    pairs.append(
                        pair(
                            f"{camera}-{day_number}-{gap_bin}-{pair_index}",
                            camera=camera,
                            day=date(2026, 7, day_number),
                            gap=gap,
                            gap_bin=gap_bin,
                        )
                    )
    split, selected = search_boundary_selection(
        pairs, "rba-event-grouping-shadow-v2", max_attempts=100
    )
    assert len(split.development_nights) == 6
    assert len(split.holdout_nights) == 6
    assert len(selected) == 120


def test_split_bins_may_be_satisfied_across_nights() -> None:
    pairs: list[BoundaryPair] = []
    bin_sets = (
        (("le30", 5.0), ("30to60", 45.0)),
        (("30to60", 45.0), ("60to300", 120.0)),
        (("le30", 5.0), ("60to300", 120.0)),
    )
    for camera in ("cam-a", "cam-b"):
        for day_number in range(1, 7):
            for gap_bin, gap in bin_sets[(day_number - 1) % len(bin_sets)]:
                pairs.append(
                    pair(
                        f"{camera}-{day_number}-{gap_bin}",
                        camera=camera,
                        day=date(2026, 7, day_number),
                        gap=gap,
                        gap_bin=gap_bin,
                    )
                )
    split = split_camera_nights(pairs, "rba-event-grouping-shadow-v2")
    for nights in (split.development_nights, split.holdout_nights):
        scoped_bins = {
            item.gap_bin
            for item in pairs
            if (item.camera_id, item.activity_day_kst) in set(nights)
        }
        assert scoped_bins == {"le30", "30to60", "60to300"}


def test_manifest_and_blank_worksheets_are_answer_free_and_deterministic() -> None:
    pairs = rich_pair_population()
    split, selected = search_boundary_selection(
        pairs, "rba-event-grouping-shadow-v2", max_attempts=20
    )
    manifest = build_private_manifest(
        source_snapshot_sha256="a" * 64,
        blocked_set_sha256="b" * 64,
        split=split,
        selected_pairs=selected,
        accounting_rows=(),
    )
    reversed_manifest = build_private_manifest(
        source_snapshot_sha256="a" * 64,
        blocked_set_sha256="b" * 64,
        split=split,
        selected_pairs=tuple(reversed(selected)),
        accounting_rows=(),
    )
    assert manifest == reversed_manifest
    assert len(manifest["splits"]["development"]) == 60
    assert len(manifest["splits"]["holdout"]) == 60
    assert manifest["schema_version"] == "rba-event-boundary-manifest-v2"
    assert manifest["search"]["max_attempts"] == 20
    text = json.dumps(manifest, sort_keys=True)
    for forbidden in (
        "r2_key",
        "signed_url",
        "email",
        "reviewer_id",
        "behavior_label",
        "vlm",
        "gate",
        "python_evidence",
        "consensus",
        "ground_truth",
    ):
        assert forbidden not in text.lower()

    worksheet = build_blank_worksheet(selected)
    assert len(worksheet["rows"]) == 120
    assert all(item["decision"] is None for item in worksheet["rows"])
    assert all(item["reason"] is None for item in worksheet["rows"])


def test_public_summary_uses_only_salted_fingerprints() -> None:
    pairs = rich_pair_population()
    split, selected = search_boundary_selection(
        pairs, "rba-event-grouping-shadow-v2", max_attempts=20
    )
    summary = build_public_summary(selected, split, salt="private-test-salt")
    text = json.dumps(summary, sort_keys=True)
    assert "cam-a" not in text
    assert "cam-b" not in text
    assert "left-" not in text
    assert "right-" not in text
    assert all(
        12 <= len(value) <= 16
        for value in summary["camera_fingerprints"]
    )


def test_private_write_is_0600_no_overwrite_and_byte_stable(tmp_path: Path) -> None:
    payload = {"z": 1, "a": ["한글", 2]}
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first_hash = write_private_new(first, payload)
    second_hash = write_private_new(second, payload)
    assert first.read_bytes() == second.read_bytes()
    assert first_hash == second_hash
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        write_private_new(first, payload)

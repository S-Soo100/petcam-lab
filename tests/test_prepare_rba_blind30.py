"""Formal Blind30 metadata-only selector와 private manifest 계약."""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from scripts.prepare_rba_blind30 import (
    Blind30PreparationError,
    Candidate,
    build_manifest,
    select_formal30,
    write_manifest,
)

T0 = datetime(2026, 7, 31, 3, 0, tzinfo=UTC)


def _candidate(
    index: int,
    *,
    camera: int,
    night: int,
    minute: int,
) -> Candidate:
    return Candidate(
        clip_id=f"10000000-0000-0000-0000-{index:012d}",
        camera_id=f"20000000-0000-0000-0000-{camera:012d}",
        started_at=datetime(2026, 7, 20 + night, 12, minute, tzinfo=UTC),
        duration_sec=60.0,
        r2_ready=True,
        labelable=True,
        excluded=False,
        tutorial=False,
        canary_history=False,
        submission_count=0,
        live_terminal_consensus=False,
        legacy_gt_count=0,
    )


def _eligible_pool() -> list[Candidate]:
    rows: list[Candidate] = []
    index = 1
    for camera in (1, 2):
        for night in (0, 1, 2):
            for offset in range(5):
                rows.append(
                    _candidate(
                        index,
                        camera=camera,
                        night=night,
                        minute=offset * 6,
                    )
                )
                index += 1
    return rows


def test_selection_is_order_independent_exact_and_balanced() -> None:
    candidates = _eligible_pool()
    forward = select_formal30(candidates, t0=T0)
    reverse = select_formal30(list(reversed(candidates)), t0=T0)

    assert [row.clip_id for row in forward] == [row.clip_id for row in reverse]
    assert len(forward) == 30
    assert len({row.clip_id for row in forward}) == 30
    assert len({row.camera_id for row in forward}) >= 2


def test_five_minute_bucket_keeps_only_one_stable_candidate() -> None:
    candidates = _eligible_pool()
    original = candidates[0]
    duplicate = replace(
        original,
        clip_id="10000000-0000-0000-0000-999999999999",
        started_at=original.started_at + timedelta(minutes=2),
    )
    selected = select_formal30(candidates + [duplicate], t0=T0)

    assert len(
        {
            row.clip_id
            for row in selected
            if row.camera_id == original.camera_id
            and int(row.started_at.timestamp()) // 300
            == int(original.started_at.timestamp()) // 300
        }
    ) == 1


def test_stratum_is_capped_at_five_and_six_camera_nights_are_required() -> None:
    candidates = _eligible_pool()
    extra = [
        _candidate(100 + i, camera=1, night=0, minute=31 + i * 6)
        for i in range(5)
    ]
    selected = select_formal30(candidates + extra, t0=T0)
    counts: dict[tuple[str, str], int] = {}
    for row in selected:
        key = (row.camera_id, row.activity_day_kst.isoformat())
        counts[key] = counts.get(key, 0) + 1

    assert len(counts) >= 6
    assert max(counts.values()) <= 5


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("r2_ready", False),
        ("labelable", False),
        ("excluded", True),
        ("tutorial", True),
        ("canary_history", True),
        ("submission_count", 1),
        ("live_terminal_consensus", True),
        ("legacy_gt_count", 1),
    ),
)
def test_ineligible_history_or_media_is_excluded(field: str, value: object) -> None:
    candidates = _eligible_pool()
    candidates[0] = replace(candidates[0], **{field: value})
    with pytest.raises(
        Blind30PreparationError,
        match="INSUFFICIENT_ELIGIBLE_POOL",
    ):
        select_formal30(candidates, t0=T0)


def test_live_awaiting_bookkeeping_is_not_an_exclusion() -> None:
    # live awaiting은 terminal flag가 false인 metadata-only 후보로 표현한다.
    selected = select_formal30(_eligible_pool(), t0=T0)
    assert len(selected) == 30


def test_manifest_is_private_deterministic_and_answer_free(tmp_path) -> None:
    selected = select_formal30(_eligible_pool(), t0=T0)
    manifest = build_manifest(
        selected,
        t0=T0,
        reviewer_fingerprints=("aaaaaaaaaaaa", "bbbbbbbbbbbb"),
    )
    raw = json.dumps(manifest, sort_keys=True)
    for forbidden in (
        "email",
        "r2_key",
        "signed_url",
        "prediction",
        "ground_truth",
        "credential",
    ):
        assert forbidden not in raw

    out = tmp_path / "manifest.json"
    digest = write_manifest(out, manifest)
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert digest == hashlib.sha256(out.read_bytes()).hexdigest()

    second = tmp_path / "manifest-second.json"
    assert write_manifest(second, manifest) == digest
    assert second.read_bytes() == out.read_bytes()


@pytest.mark.parametrize(
    "fingerprints",
    (
        ("reviewer@example.com", "bbbbbbbbbbbb"),
        ("aaaaaaaaaaaa", "aaaaaaaaaaaa"),
        ("not-a-fingerprint", "bbbbbbbbbbbb"),
    ),
)
def test_manifest_rejects_identifying_or_invalid_reviewer_fingerprints(
    fingerprints: tuple[str, str],
) -> None:
    with pytest.raises(Blind30PreparationError, match="TWO_REVIEWER_FINGERPRINTS"):
        build_manifest(
            select_formal30(_eligible_pool(), t0=T0),
            t0=T0,
            reviewer_fingerprints=fingerprints,
        )

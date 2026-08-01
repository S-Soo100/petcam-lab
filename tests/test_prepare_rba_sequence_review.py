from datetime import UTC, date, datetime, timedelta

from scripts.prepare_rba_sequence_review import (
    BLOCKED_INSUFFICIENT_SEQUENCE_RUNS,
    SequenceSelectionBlocked,
    build_sequence_manifest,
    manifest_from_base_artifact,
    select_sequence_runs,
)
from scripts.rba_event_grouping_core import AccountedClip


def _inventory(*, edges_per_night: int = 30) -> tuple[AccountedClip, ...]:
    rows: list[AccountedClip] = []
    base = datetime(2026, 7, 1, 12, tzinfo=UTC)
    for night_index in range(6):
        camera = f"camera-{night_index % 2}"
        day = date(2026, 7, night_index + 1)
        for clip_index in range(edges_per_night + 1):
            rows.append(AccountedClip(
                clip_id=f"clip-{night_index:02d}-{clip_index:03d}",
                camera_id=camera,
                started_at=base + timedelta(days=night_index, seconds=clip_index * 40),
                activity_day_kst=day,
                duration_sec=30.0,
                kind="activity_candidate",
                reason_code=None,
            ))
    return tuple(rows)


def test_selects_exact120_complete_overlapping_run_edges() -> None:
    selected = select_sequence_runs(
        _inventory(),
        development_nights=tuple(
            (f"camera-{index % 2}", date(2026, 7, index + 1))
            for index in range(6)
        ),
        target_edges=120,
        seed="test-seed",
    )

    assert sum(len(run.pairs) for run in selected) == 120
    assert len(selected) == 6
    assert len({run.camera_id for run in selected}) == 2
    for run in selected:
        assert len(run.pairs) > 1
        assert all(
            left.right_clip_id == right.left_clip_id
            for left, right in zip(run.pairs, run.pairs[1:], strict=False)
        )


def test_selection_is_deterministic_and_marks_censored_windows() -> None:
    kwargs = {
        "development_nights": tuple(
            (f"camera-{index % 2}", date(2026, 7, index + 1))
            for index in range(6)
        ),
        "target_edges": 120,
        "seed": "test-seed",
    }
    first = select_sequence_runs(_inventory(), **kwargs)
    second = select_sequence_runs(reversed(_inventory()), **kwargs)

    assert first == second
    assert any(run.left_censored or run.right_censored for run in first)


def test_run_order_uses_time_not_clip_id_lexical_order() -> None:
    rows = []
    for row in _inventory():
        night_index, clip_index = row.clip_id.split('-')[1:]
        rows.append(AccountedClip(
            clip_id=f"z-{night_index}-{999 - int(clip_index):03d}",
            camera_id=row.camera_id,
            started_at=row.started_at,
            activity_day_kst=row.activity_day_kst,
            duration_sec=row.duration_sec,
            kind=row.kind,
            reason_code=row.reason_code,
        ))
    selected = select_sequence_runs(
        rows,
        development_nights=tuple(
            (f"camera-{index % 2}", date(2026, 7, index + 1))
            for index in range(6)
        ),
        target_edges=120,
        seed="test-seed",
    )
    assert sum(len(run.pairs) for run in selected) == 120


def test_negative_gap_boundary_is_never_selected() -> None:
    rows = list(_inventory())
    for index, row in enumerate(rows):
        if row.clip_id.endswith('-015'):
            rows[index] = AccountedClip(
                clip_id=row.clip_id,
                camera_id=row.camera_id,
                started_at=row.started_at - timedelta(seconds=15),
                activity_day_kst=row.activity_day_kst,
                duration_sec=row.duration_sec,
                kind=row.kind,
                reason_code=row.reason_code,
            )
    selected = select_sequence_runs(
        rows,
        development_nights=tuple(
            (f"camera-{index % 2}", date(2026, 7, index + 1))
            for index in range(6)
        ),
        target_edges=84,
        seed="test-seed",
    )
    assert all(pair.gap_sec >= 0 for run in selected for pair in run.pairs)


def test_fails_closed_when_six_nights_cannot_supply_target() -> None:
    try:
        select_sequence_runs(
            _inventory(edges_per_night=10),
            development_nights=tuple(
                (f"camera-{index % 2}", date(2026, 7, index + 1))
                for index in range(6)
            ),
            target_edges=120,
            seed="test-seed",
        )
    except SequenceSelectionBlocked as exc:
        assert str(exc) == BLOCKED_INSUFFICIENT_SEQUENCE_RUNS
    else:
        raise AssertionError("insufficient inventory must fail closed")


def test_manifest_has_exact120_pairs_and_six_run_censor_contract() -> None:
    nights = tuple(
        (f"camera-{index % 2}", date(2026, 7, index + 1))
        for index in range(6)
    )
    manifest = build_sequence_manifest(
        accounted=_inventory(),
        development_nights=nights,
        source_snapshot_sha256="a" * 64,
        blocked_set_sha256="b" * 64,
        seed="test-seed",
    )

    assert manifest["schema_version"] == "rba-event-sequence-review-manifest-v2"
    assert manifest["experiment_id"] == "rba-event-sequence-review-v2"
    assert len(manifest["pairs"]) == 120
    assert [row["ordinal"] for row in manifest["pairs"]] == list(range(1, 121))
    assert len(manifest["runs"]) == 6
    assert sum(row["pair_count"] for row in manifest["runs"]) == 120
    assert manifest["unique_clip_count"] == 126
    assert len(manifest["manifest_sha256"]) == 64


def test_builds_sequence_manifest_from_frozen_base_artifact() -> None:
    rows = _inventory()
    base = {
        "schema_version": "rba-event-boundary-manifest-v2",
        "source_snapshot_sha256": "a" * 64,
        "blocked_set_sha256": "b" * 64,
        "camera_nights": {
            "development": [
                [f"camera-{index % 2}", f"2026-07-{index + 1:02d}"]
                for index in range(6)
            ],
            "holdout": [["secret", "2099-01-01"]],
        },
        "accounting": [{
            "clip_id": row.clip_id,
            "camera_id": row.camera_id,
            "started_at": row.started_at.isoformat(),
            "activity_day_kst": row.activity_day_kst.isoformat(),
            "duration_sec": row.duration_sec,
            "kind": row.kind,
            "reason_code": row.reason_code,
        } for row in rows],
    }
    manifest = manifest_from_base_artifact(base, seed="test-seed")
    assert len(manifest["pairs"]) == 120
    assert all(row["camera_id"] != "secret" for row in manifest["pairs"])

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.freeze_yolo26n_v26_recent_sources import (
    SourceFreezeContract,
    build_source_manifest,
    write_manifest_once,
)


START = "2026-08-24T00:00:00+09:00"
END = "2026-08-26T16:13:29.838806+09:00"
IDENTITY = "d" * 64


def _source(index: int, *, camera: str = "camera-a") -> dict[str, object]:
    return {
        "id": f"clip-{index}",
        "camera_id": camera,
        "started_at": f"2026-08-24T00:00:0{index}+09:00",
        "duration_sec": 50.0,
        "r2_key": f"private/clip-{index}.mp4",
        "size_bytes": 1000 + index,
    }


def _job(index: int) -> dict[str, object]:
    return {
        "clip_id": f"clip-{index}",
        "status": "succeeded",
        "detector_identity": IDENTITY,
        "algorithm_version": "gme-v1",
        "engine_schema_version": "gme-shadow-v1",
    }


def test_manifest_sorts_sources_and_binds_exact_gme_lineage() -> None:
    manifest = build_source_manifest(
        [_source(1, camera="camera-b"), _source(0)],
        [_job(1), _job(0)],
        window_start=START,
        window_end=END,
        contract=SourceFreezeContract(
            expected_clip_count=2,
            expected_camera_count=2,
            expected_detector_identity=IDENTITY,
        ),
    )

    assert manifest["aggregate"] == {
        "clip_count": 2,
        "accessible_clip_count": 2,
        "tombstoned_clip_count": 0,
        "camera_count": 2,
        "duration_sec": 100.0,
        "accessible_duration_sec": 100.0,
        "tombstoned_duration_sec": 0.0,
        "source_bytes": 2001,
        "gme_status_counts": {"succeeded": 2},
    }
    assert [row["clip_id"] for row in manifest["sources"]] == ["clip-0", "clip-1"]
    assert len(manifest["lineage_sha256"]) == 64


def test_manifest_rejects_missing_gme_job_instead_of_silently_freezing_partial_input() -> None:
    with pytest.raises(ValueError, match="GME lineage must cover exact source set"):
        build_source_manifest(
            [_source(0), _source(1)],
            [_job(0)],
            window_start=START,
            window_end=END,
            contract=SourceFreezeContract(
                expected_clip_count=2,
                expected_camera_count=1,
                expected_detector_identity=IDENTITY,
            ),
        )


def test_manifest_rejects_duplicate_gme_job_instead_of_choosing_one() -> None:
    with pytest.raises(ValueError, match="GME lineage contains duplicate clip"):
        build_source_manifest(
            [_source(0)],
            [_job(0), _job(0)],
            window_start=START,
            window_end=END,
            contract=SourceFreezeContract(
                expected_clip_count=1,
                expected_camera_count=1,
                expected_detector_identity=IDENTITY,
            ),
        )


@pytest.mark.parametrize(
    "status",
    ["queued", "processing", "failed_retryable", "failed_terminal", None],
)
def test_manifest_rejects_any_non_success_gme_job(status: object) -> None:
    with pytest.raises(ValueError, match="GME status does not match approved success contract"):
        build_source_manifest(
            [_source(0)],
            [_job(0) | {"status": status}],
            window_start=START,
            window_end=END,
            contract=SourceFreezeContract(
                expected_clip_count=1,
                expected_camera_count=1,
                expected_detector_identity=IDENTITY,
            ),
        )


def test_freeze_contract_rejects_non_success_expected_status() -> None:
    with pytest.raises(ValueError, match="expected GME success status is not approved"):
        SourceFreezeContract(
            expected_clip_count=1,
            expected_camera_count=1,
            expected_detector_identity=IDENTITY,
            expected_success_status="failed_terminal",
        ).validate()


def test_manifest_rejects_wrong_count_camera_or_detector_identity() -> None:
    with pytest.raises(ValueError, match="clip count"):
        build_source_manifest(
            [_source(0)],
            [_job(0)],
            window_start=START,
            window_end=END,
            contract=SourceFreezeContract(2, 1, IDENTITY),
        )
    bad_job = _job(0) | {"detector_identity": "e" * 64}
    with pytest.raises(ValueError, match="detector identity"):
        build_source_manifest(
            [_source(0)],
            [bad_job],
            window_start=START,
            window_end=END,
            contract=SourceFreezeContract(1, 1, IDENTITY),
        )


def test_manifest_rejects_source_outside_frozen_window() -> None:
    source = _source(0) | {"started_at": "2026-08-27T00:00:00+09:00"}
    with pytest.raises(ValueError, match="outside frozen window"):
        build_source_manifest(
            [source],
            [_job(0)],
            window_start=START,
            window_end=END,
            contract=SourceFreezeContract(1, 1, IDENTITY),
        )


def test_manifest_writer_never_overwrites_an_existing_artifact(tmp_path: Path) -> None:
    destination = tmp_path / "source.private.json"
    write_manifest_once(destination, {"one": 1})

    with pytest.raises(FileExistsError):
        write_manifest_once(destination, {"two": 2})

    assert destination.read_text() == '{\n  "one": 1\n}\n'


def test_manifest_preserves_known_short_clip_tombstones_but_freezes_available_subset() -> None:
    deleted = _source(0) | {
        "duration_sec": 12.5,
        "object_status": "missing",
        "size_bytes": None,
    }
    available = _source(1, camera="camera-b") | {"object_status": "available"}

    manifest = build_source_manifest(
        [deleted, available],
        [_job(0), _job(1)],
        window_start=START,
        window_end=END,
        contract=SourceFreezeContract(
            expected_clip_count=2,
            expected_camera_count=2,
            expected_detector_identity=IDENTITY,
            expected_available_count=1,
            allowed_missing_below_sec=55.0,
        ),
    )

    assert manifest["aggregate"]["accessible_clip_count"] == 1
    assert manifest["aggregate"]["tombstoned_clip_count"] == 1
    assert manifest["aggregate"]["source_bytes"] == 1001


def test_manifest_rejects_missing_long_clip_outside_approved_deletion_policy() -> None:
    missing = _source(0) | {
        "duration_sec": 60.0,
        "object_status": "missing",
        "size_bytes": None,
    }

    with pytest.raises(ValueError, match="missing source is outside approved policy"):
        build_source_manifest(
            [missing],
            [_job(0)],
            window_start=START,
            window_end=END,
            contract=SourceFreezeContract(
                expected_clip_count=1,
                expected_camera_count=1,
                expected_detector_identity=IDENTITY,
                expected_available_count=0,
                allowed_missing_below_sec=55.0,
            ),
        )

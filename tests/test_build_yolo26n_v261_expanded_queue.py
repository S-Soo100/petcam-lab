from __future__ import annotations

from datetime import datetime, timezone

import pytest

import scripts.build_yolo26n_v261_expanded_queue as builder


def _source(
    clip_ref: str,
    *,
    camera_ref: str,
    started_at: str,
    cohort: str = "post_v26",
    **metrics: object,
) -> dict[str, object]:
    return {
        "clip_ref": clip_ref,
        "camera_ref": camera_ref,
        "started_at": started_at,
        "duration_sec": 60.0,
        "cohort": cohort,
        "gme": metrics,
    }


def test_freeze_future_holdout_is_exact_deterministic_and_diverse() -> None:
    sources = []
    for camera in ("cam-a", "cam-b"):
        for day in range(1, 5):
            for index in range(6):
                sources.append(
                    _source(
                        f"{camera}-{day}-{index}",
                        camera_ref=camera,
                        started_at=f"2026-09-0{day}T0{index}:00:00+00:00",
                    )
                )

    first = builder.freeze_future_holdout(sources, count=20, seed="fixed")
    second = builder.freeze_future_holdout(reversed(sources), count=20, seed="fixed")

    assert first == second
    assert len(first) == 20
    assert {row["camera_ref"] for row in first} == {"cam-a", "cam-b"}
    assert len({row["camera_night"] for row in first}) >= 3


def test_freeze_future_holdout_rejects_short_or_non_diverse_pool() -> None:
    short = [
        _source(
            f"clip-{index}",
            camera_ref="cam-a",
            started_at="2026-09-01T00:00:00+00:00",
        )
        for index in range(4)
    ]

    with pytest.raises(ValueError, match="holdout shortage"):
        builder.freeze_future_holdout(short, count=5, seed="fixed")
    with pytest.raises(ValueError, match="camera diversity"):
        builder.freeze_future_holdout(short, count=3, seed="fixed")


@pytest.mark.parametrize(
    ("metrics", "expected"),
    [
        ({"visible_sec": 0.0, "unknown_sec": 60.0}, ("zero_visible", "unknown_high")),
        ({"detection_gap_count": 12}, ("detection_gap",)),
        ({"fragmentation_count": 14}, ("fragmentation",)),
        ({"position_jump_count": 4}, ("position_jump",)),
        ({"max_simultaneous_geckos": 2}, ("multi_gecko_or_reflection",)),
        ({"moving_gecko_seconds": 40.0}, ()),
    ],
)
def test_detector_candidate_reasons_keep_activity_only_signals_separate(
    metrics: dict[str, object], expected: tuple[str, ...]
) -> None:
    assert builder.detector_candidate_reasons(metrics, duration_sec=60.0) == expected


def test_select_development_sources_prioritizes_owner_and_balances_controls() -> None:
    sources = [
        _source(
            "owner",
            camera_ref="cam-a",
            started_at="2026-09-01T00:00:00+00:00",
            detection_gap_count=20,
        ),
        _source(
            "anomaly-a",
            camera_ref="cam-a",
            started_at="2026-09-02T00:00:00+00:00",
            fragmentation_count=20,
        ),
        _source(
            "anomaly-b",
            camera_ref="cam-b",
            started_at="2026-09-02T01:00:00+00:00",
            position_jump_count=5,
        ),
        _source(
            "normal-a",
            camera_ref="cam-a",
            started_at="2026-09-03T00:00:00+00:00",
        ),
        _source(
            "normal-b",
            camera_ref="cam-b",
            started_at="2026-09-03T01:00:00+00:00",
        ),
    ]

    selected = builder.select_development_sources(
        sources,
        owner_clip_refs={"owner"},
        excluded_clip_refs=set(),
        anomaly_limit=2,
        control_limit=2,
        seed="fixed",
    )

    assert [row["clip_ref"] for row in selected if "owner_confirmed" in row["reasons"]] == ["owner"]
    assert sum("iid_control" in row["reasons"] for row in selected) == 2
    assert {row["camera_ref"] for row in selected if "iid_control" in row["reasons"]} == {"cam-a", "cam-b"}
    assert len({row["clip_ref"] for row in selected}) == len(selected)


def test_camera_night_uses_kst_calendar_date() -> None:
    assert builder.camera_night("2026-09-03T16:30:00+00:00") == "2026-09-04"
    instant = datetime(2026, 9, 3, 16, 30, tzinfo=timezone.utc)
    assert builder.camera_night(instant) == "2026-09-04"


def test_build_source_plan_seals_post_cutoff_before_development_selection() -> None:
    sources = []
    for camera in ("cam-a", "cam-b"):
        for day in range(1, 4):
            for index in range(4):
                sources.append(
                    _source(
                        f"post-{camera}-{day}-{index}",
                        camera_ref=camera,
                        started_at=f"2026-09-0{day}T0{index}:00:00+00:00",
                        detection_gap_count=20 if index == 0 else 0,
                    )
                )
    sources.extend(
        [
            _source(
                "old-used",
                camera_ref="cam-a",
                started_at="2026-08-20T00:00:00+00:00",
                cohort="historical_unused",
                detection_gap_count=30,
            ),
            _source(
                "old-anomaly",
                camera_ref="cam-b",
                started_at="2026-08-21T00:00:00+00:00",
                cohort="historical_unused",
                fragmentation_count=20,
            ),
            _source(
                "old-normal",
                camera_ref="cam-a",
                started_at="2026-08-22T00:00:00+00:00",
                cohort="historical_unused",
            ),
        ]
    )

    plan = builder.build_source_plan(
        sources,
        v26_used_clip_refs={"old-used"},
        owner_clip_refs={"old-anomaly"},
        future_holdout_count=8,
        historical_anomaly_limit=2,
        historical_control_limit=1,
        seed="fixed",
    )

    holdout_refs = {row["clip_ref"] for row in plan["future_holdout"]}
    development_refs = {row["clip_ref"] for row in plan["development"]}
    assert len(holdout_refs) == 8
    assert holdout_refs.isdisjoint(development_refs)
    assert "old-used" not in development_refs
    assert "old-anomaly" in development_refs
    assert "old-normal" in development_refs
    assert len(development_refs) == 24 - 8 + 2


def test_candidate_frame_dedup_is_global_exact_but_per_source_perceptual() -> None:
    protected = [
        {
            "clip_ref": "protected-source",
            "image_sha256": "a" * 64,
            "dhash64": "0000000000000000",
        }
    ]
    candidates = [
        {"clip_ref": "source-1", "source_video_sha256": "1" * 64, "frame_index": 1, "image_sha256": "b" * 64, "dhash64": "ffffffffffffffff"},
        {"clip_ref": "source-1", "source_video_sha256": "1" * 64, "frame_index": 2, "image_sha256": "c" * 64, "dhash64": "fffffffffffffffe"},
        {"clip_ref": "source-2", "source_video_sha256": "2" * 64, "frame_index": 1, "image_sha256": "d" * 64, "dhash64": "fffffffffffffffe"},
        {"clip_ref": "source-3", "source_video_sha256": "3" * 64, "frame_index": 1, "image_sha256": "e" * 64, "dhash64": "0000000000000001"},
        {"clip_ref": "source-4", "source_video_sha256": "4" * 64, "frame_index": 1, "image_sha256": "b" * 64, "dhash64": "1234567890abcdef"},
        {"clip_ref": "protected-source", "source_video_sha256": "5" * 64, "frame_index": 1, "image_sha256": "f" * 64, "dhash64": "0000000000000002"},
    ]

    result = builder.deduplicate_candidate_frames(candidates, protected)

    assert [row["image_sha256"] for row in result["records"]] == ["b" * 64, "d" * 64, "e" * 64]
    assert result["counts"] == {
        "input": 6,
        "protected_exact": 0,
        "protected_perceptual": 1,
        "pool_exact": 1,
        "same_source_perceptual": 1,
        "same_source_perceptual_exception": 0,
        "accepted": 3,
    }


def test_candidate_frame_dedup_allows_bounded_per_source_exceptions() -> None:
    candidates = [
        {
            "clip_ref": "source-1",
            "source_video_sha256": "1" * 64,
            "frame_index": index,
            "image_sha256": f"{index:064x}",
            "dhash64": f"{index:016x}",
        }
        for index in range(1, 6)
    ]

    result = builder.deduplicate_candidate_frames(
        candidates,
        [],
        perceptual_exception_limits={"source-1": 2},
    )

    assert len(result["records"]) == 3
    assert result["counts"]["same_source_perceptual_exception"] == 2
    assert result["counts"]["same_source_perceptual"] == 2

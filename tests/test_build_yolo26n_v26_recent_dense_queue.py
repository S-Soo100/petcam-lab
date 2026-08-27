from __future__ import annotations

import hashlib

import pytest

from scripts.build_yolo26n_v26_recent_dense_queue import (
    DenseFrame,
    SamplingContract,
    assert_human_export_ready,
    dense_timestamps_ms,
    select_review_queue,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _frame(
    clip: str,
    index: int,
    *,
    camera_night: str = "camera-a:2026-08-24",
    dhash: int | None = None,
    detection_count: int = 0,
    confidence: float = 0.0,
    motion: float = 0.0,
    scene: float = 0.0,
    feedback: bool = False,
) -> DenseFrame:
    return DenseFrame(
        clip_ref=clip,
        camera_night=camera_night,
        timestamp_ms=index * 500,
        image_sha256=_sha(f"{clip}:{index}"),
        dhash64=index if dhash is None else dhash,
        detection_count=detection_count,
        max_confidence=confidence,
        motion_score=motion,
        scene_score=scene,
        feedback_band=feedback,
    )


def test_dense_timestamps_are_exactly_two_fps_without_end_overrun() -> None:
    assert dense_timestamps_ms(1.01, sample_fps=2.0) == (0, 500, 1000)
    assert dense_timestamps_ms(1.0, sample_fps=2.0) == (0, 500)
    assert dense_timestamps_ms(0.1, sample_fps=2.0) == (0,)


@pytest.mark.parametrize("duration,fps", [(0, 2.0), (-1, 2.0), (1, 0), (1, -2)])
def test_dense_timestamps_reject_invalid_contract(duration: float, fps: float) -> None:
    with pytest.raises(ValueError):
        dense_timestamps_ms(duration, sample_fps=fps)


def test_queue_keeps_four_frames_from_every_clip_and_prioritizes_hard_cases() -> None:
    frames = []
    for clip in ("clip-a", "clip-b"):
        frames.extend(_frame(clip, index, dhash=index + (100 if clip == "clip-b" else 0)) for index in range(12))
    frames[1] = _frame("clip-a", 1, dhash=1, feedback=True)
    frames[3] = _frame("clip-a", 3, dhash=3, motion=20.0)
    frames[8] = _frame("clip-a", 8, dhash=8, detection_count=1, confidence=0.8)

    selected = select_review_queue(
        frames,
        contract=SamplingContract(coverage_per_clip=4, queue_min=8, queue_max=10),
    )

    by_clip = {clip: [row for row in selected if row.frame.clip_ref == clip] for clip in ("clip-a", "clip-b")}
    assert all(len(rows) >= 4 for rows in by_clip.values())
    # queue_min은 검수량 목표이고 queue_max는 hard-case가 많을 때의 상한이다.
    assert len(selected) == 8
    reasons = {row.frame.timestamp_ms: row.reasons for row in by_clip["clip-a"]}
    assert "feedback-band" in reasons[500]
    assert "motion-without-detection" in reasons[1500]
    assert "persistent-detection" in reasons[4000]


def test_queue_is_order_independent_and_drops_exact_duplicate_images() -> None:
    original = [_frame("clip-a", i, dhash=i) for i in range(8)]
    duplicate = DenseFrame(
        clip_ref="clip-a",
        camera_night=original[0].camera_night,
        timestamp_ms=9999,
        image_sha256=original[0].image_sha256,
        dhash64=999,
        detection_count=0,
        max_confidence=0.0,
        motion_score=0.0,
        scene_score=0.0,
        feedback_band=False,
    )
    contract = SamplingContract(coverage_per_clip=4, queue_min=4, queue_max=6)

    left = select_review_queue(original + [duplicate], contract=contract)
    right = select_review_queue(list(reversed(original + [duplicate])), contract=contract)

    assert [(row.frame.image_sha256, row.reasons) for row in left] == [
        (row.frame.image_sha256, row.reasons) for row in right
    ]
    assert len({row.frame.image_sha256 for row in left}) == len(left)


def test_queue_fails_closed_on_protected_exact_or_near_duplicate() -> None:
    frames = [_frame("clip-a", i, dhash=i + 10) for i in range(8)]
    contract = SamplingContract(coverage_per_clip=4, queue_min=4, queue_max=6)

    with pytest.raises(ValueError, match="protected exact overlap"):
        select_review_queue(frames, contract=contract, protected_sha256={frames[0].image_sha256})
    with pytest.raises(ValueError, match="protected near overlap"):
        select_review_queue(frames, contract=contract, protected_dhash64={frames[0].dhash64 ^ 1})


def test_queue_fails_when_one_clip_cannot_meet_coverage() -> None:
    frames = [_frame("clip-a", i) for i in range(4)] + [_frame("clip-b", i) for i in range(3)]
    with pytest.raises(ValueError, match="coverage shortage"):
        select_review_queue(
            frames,
            contract=SamplingContract(coverage_per_clip=4, queue_min=8, queue_max=12),
        )


def test_hard_case_overflow_never_consumes_another_clips_coverage_budget() -> None:
    frames = [
        _frame("clip-a", index, dhash=1000 + index, feedback=True)
        for index in range(20)
    ] + [
        _frame("clip-b", index, dhash=2000 + index)
        for index in range(4)
    ]

    selected = select_review_queue(
        frames,
        contract=SamplingContract(coverage_per_clip=2, queue_min=6, queue_max=6),
    )

    assert len(selected) == 6
    assert sum(row.frame.clip_ref == "clip-b" for row in selected) >= 2


def test_human_export_must_cover_every_selected_frame_and_keep_empty_gt() -> None:
    selected = select_review_queue(
        [_frame("clip-a", i, dhash=i + 100) for i in range(6)],
        contract=SamplingContract(coverage_per_clip=4, queue_min=4, queue_max=4),
    )
    rows = [
        {
            "image_sha256": selected[0].frame.image_sha256,
            "verdict": "gecko_present",
            "box_count": 1,
        },
        {
            "image_sha256": selected[1].frame.image_sha256,
            "verdict": "gecko_absent",
            "box_count": 0,
        },
        {
            "image_sha256": selected[2].frame.image_sha256,
            "verdict": "uncertain",
            "box_count": 0,
        },
        {
            "image_sha256": selected[3].frame.image_sha256,
            "verdict": "media_error",
            "box_count": 0,
        },
    ]

    summary = assert_human_export_ready(rows, selected)

    assert summary == {"present": 1, "absent": 1, "excluded": 2, "box_count": 1}


def test_human_export_rejects_missing_rows_and_inconsistent_boxes() -> None:
    selected = select_review_queue(
        [_frame("clip-a", i, dhash=i + 200) for i in range(4)],
        contract=SamplingContract(coverage_per_clip=4, queue_min=4, queue_max=4),
    )
    with pytest.raises(ValueError, match="exact selected frame set"):
        assert_human_export_ready([], selected)

    rows = [
        {"image_sha256": row.frame.image_sha256, "verdict": "gecko_absent", "box_count": 0}
        for row in selected
    ]
    rows[0]["box_count"] = 1
    with pytest.raises(ValueError, match="absent frame must have zero boxes"):
        assert_human_export_ready(rows, selected)

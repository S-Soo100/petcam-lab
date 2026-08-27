from __future__ import annotations

import hashlib

import pytest

from scripts.build_yolo26n_v26_recent_dense_queue import DenseFrame
from scripts.select_yolo26n_v26_stratified_queue import (
    StratifiedQueueContract,
    select_stratified_queue,
)


def _frame(
    clip: str,
    index: int,
    *,
    detection: bool = False,
    confidence: float = 0.0,
    motion: float = 0.0,
    scene: float = 0.0,
) -> DenseFrame:
    token = f"{clip}:{index}"
    digest = hashlib.sha256(token.encode()).digest()
    return DenseFrame(
        clip_ref=clip,
        camera_night=f"camera-{clip[-1]}:2026-08-24",
        timestamp_ms=index * 500,
        image_sha256=hashlib.sha256(f"image:{token}".encode()).hexdigest(),
        dhash64=int.from_bytes(digest[:8], "big"),
        detection_count=1 if detection else 0,
        max_confidence=confidence,
        motion_score=motion,
        scene_score=scene,
        feedback_band=False,
    )


def _pool() -> list[DenseFrame]:
    frames: list[DenseFrame] = []
    for clip in ("clip-a", "clip-b"):
        for index in range(14):
            frames.append(
                _frame(
                    clip,
                    index,
                    detection=index in {2, 3, 4, 8, 9, 10},
                    confidence=0.35 if index in {2, 8} else (0.9 if index in {3, 4, 9, 10} else 0.0),
                    motion=8.0 if index == 6 else 0.2,
                    scene=8.0 if index == 12 else 0.0,
                )
            )
    return frames


def test_selector_meets_each_disjoint_stratum_and_marks_double_review_subset() -> None:
    selection = select_stratified_queue(
        _pool(),
        contract=StratifiedQueueContract(
            coverage_per_clip=1,
            uncertainty_count=4,
            hard_negative_count=4,
            iid_random_count=4,
            gold_count=3,
            seed="test-seed",
        ),
    )

    assert selection.strata_counts == {
        "coverage": 2,
        "uncertainty": 4,
        "hard-negative-candidate": 4,
        "iid-random": 4,
    }
    assert len(selection.items) == 14
    assert sum(item.double_review for item in selection.items) == 3
    assert selection.review_task_count == 17
    assert {item.frame.clip_ref for item in selection.items if item.stratum == "coverage"} == {
        "clip-a",
        "clip-b",
    }


def test_selector_filters_protected_frame_before_selection() -> None:
    frames = _pool()
    protected = frames[0]
    selection = select_stratified_queue(
        frames,
        contract=StratifiedQueueContract(
            coverage_per_clip=1,
            uncertainty_count=0,
            hard_negative_count=0,
            iid_random_count=2,
            gold_count=0,
            seed="test-seed",
        ),
        protected_sha256={protected.image_sha256},
    )

    assert all(item.frame.image_sha256 != protected.image_sha256 for item in selection.items)
    assert selection.excluded_protected == 1


def test_selector_fails_closed_when_a_required_stratum_is_short() -> None:
    with pytest.raises(ValueError, match="hard-negative-candidate shortage"):
        select_stratified_queue(
            [_frame("clip-a", index) for index in range(10)],
            contract=StratifiedQueueContract(
                coverage_per_clip=1,
                uncertainty_count=0,
                hard_negative_count=1,
                iid_random_count=0,
                gold_count=0,
                seed="test-seed",
            ),
        )


def test_selector_is_order_independent() -> None:
    contract = StratifiedQueueContract(
        coverage_per_clip=1,
        uncertainty_count=3,
        hard_negative_count=3,
        iid_random_count=3,
        gold_count=2,
        seed="test-seed",
    )
    frames = _pool()

    left = select_stratified_queue(frames, contract=contract)
    right = select_stratified_queue(list(reversed(frames)), contract=contract)

    assert [
        (item.frame.image_sha256, item.stratum, item.double_review) for item in left.items
    ] == [
        (item.frame.image_sha256, item.stratum, item.double_review) for item in right.items
    ]


def test_uncertainty_keeps_two_near_duplicate_transition_frames_per_clip() -> None:
    frames = [
        _frame("clip-a", 0),
        _frame("clip-a", 1, detection=True, confidence=0.3),
        _frame("clip-a", 2),
        _frame("clip-a", 3, detection=True, confidence=0.3),
    ]
    frames = [
        DenseFrame(
            clip_ref=frame.clip_ref,
            camera_night=frame.camera_night,
            timestamp_ms=frame.timestamp_ms,
            image_sha256=frame.image_sha256,
            dhash64=0,
            detection_count=frame.detection_count,
            max_confidence=frame.max_confidence,
            motion_score=frame.motion_score,
            scene_score=frame.scene_score,
            feedback_band=frame.feedback_band,
        )
        for frame in frames
    ]

    selection = select_stratified_queue(
        frames,
        contract=StratifiedQueueContract(
            coverage_per_clip=1,
            uncertainty_count=2,
            hard_negative_count=0,
            iid_random_count=0,
            gold_count=0,
            seed="test-seed",
        ),
    )

    assert selection.strata_counts["uncertainty"] == 2


def test_iid_layer_can_keep_one_near_duplicate_to_represent_static_duration() -> None:
    frames = [_frame("clip-a", index) for index in range(3)]
    frames = [
        DenseFrame(
            clip_ref=frame.clip_ref,
            camera_night=frame.camera_night,
            timestamp_ms=frame.timestamp_ms,
            image_sha256=frame.image_sha256,
            dhash64=0,
            detection_count=frame.detection_count,
            max_confidence=frame.max_confidence,
            motion_score=frame.motion_score,
            scene_score=frame.scene_score,
            feedback_band=frame.feedback_band,
        )
        for frame in frames
    ]

    selection = select_stratified_queue(
        frames,
        contract=StratifiedQueueContract(
            coverage_per_clip=1,
            uncertainty_count=0,
            hard_negative_count=0,
            iid_random_count=1,
            gold_count=0,
            seed="test-seed",
        ),
    )

    assert selection.strata_counts["iid-random"] == 1

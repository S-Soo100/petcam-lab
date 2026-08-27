from __future__ import annotations

import pytest

from scripts.gme_temporal_decision import (
    TemporalDecisionContract,
    analysis_frame_indices,
    classify_clip_presence,
)


def test_analysis_rate_caps_thirty_fps_source_at_ten_without_duplicate_frames() -> None:
    # 30fps 원본의 0.0, 0.1, ... 1.0초 frame만 사용한다.
    assert analysis_frame_indices(frame_count=31, source_fps=30.0) == tuple(range(0, 31, 3))


def test_analysis_rate_keeps_fixed_tenth_second_deadlines_for_twenty_five_fps() -> None:
    # 다음 deadline을 실제 선택 시각에서 재설정하면 0, 3, 6, ...으로 drift한다.
    assert analysis_frame_indices(frame_count=25, source_fps=25.0) == (
        0,
        3,
        5,
        8,
        10,
        13,
        15,
        18,
        20,
        23,
    )


def test_analysis_rate_keeps_fixed_tenth_second_deadlines_for_ntsc_fps() -> None:
    assert analysis_frame_indices(frame_count=30, source_fps=29.97) == tuple(range(0, 30, 3))


def test_analysis_rate_keeps_every_frame_when_source_is_exactly_ten_fps() -> None:
    assert analysis_frame_indices(frame_count=11, source_fps=10.0) == tuple(range(11))


def test_analysis_rate_keeps_every_frame_when_source_is_below_ten_fps() -> None:
    assert analysis_frame_indices(frame_count=6, source_fps=6.0) == (0, 1, 2, 3, 4, 5)


@pytest.mark.parametrize(
    ("frame_count", "source_fps"),
    [(0, 30.0), (-1, 30.0), (10, 0.0), (10, float("nan"))],
)
def test_analysis_rate_rejects_invalid_video_metadata(frame_count: int, source_fps: float) -> None:
    with pytest.raises(ValueError):
        analysis_frame_indices(frame_count=frame_count, source_fps=source_fps)


def test_three_detections_inside_five_frame_window_confirm_clip_presence() -> None:
    decisions = (False, True, False, True, True, False)

    assert classify_clip_presence(decisions) == "present"


def test_one_or_two_isolated_detections_are_unknown_instead_of_present() -> None:
    assert classify_clip_presence((False, True, False, False, False)) == "unknown"
    assert classify_clip_presence((True, False, False, True, False)) == "unknown"


def test_zero_detections_are_absent() -> None:
    assert classify_clip_presence((False,) * 20) == "absent"


def test_short_clip_can_confirm_presence_when_all_three_frames_are_positive() -> None:
    assert classify_clip_presence((True, True, True)) == "present"


def test_temporal_contract_rejects_impossible_window() -> None:
    with pytest.raises(ValueError, match="min_positive_frames"):
        TemporalDecisionContract(window_frames=5, min_positive_frames=6).validate()

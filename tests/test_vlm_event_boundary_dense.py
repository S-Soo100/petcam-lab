import numpy as np

from scripts.vlm_event_boundary_dense import (
    A_BOUNDARY_OFFSETS_SEC,
    B_BOUNDARY_OFFSETS_SEC,
    DENSE_PROMPT,
    DENSE_PROMPT_VERSION,
    DENSE_REPRESENTATION,
    boundary_frame_indices,
    build_boundary_sheets,
)


def test_boundary_sampling_is_dense_around_a_end_and_b_start() -> None:
    assert A_BOUNDARY_OFFSETS_SEC == (6.0, 4.0, 2.0, 1.0, 0.5, 0.1)
    assert B_BOUNDARY_OFFSETS_SEC == (0.1, 0.5, 1.0, 2.0, 4.0, 6.0)

    a_indices = boundary_frame_indices(
        frame_count=901,
        fps=30.0,
        offsets_sec=A_BOUNDARY_OFFSETS_SEC,
        anchor="end",
    )
    b_indices = boundary_frame_indices(
        frame_count=901,
        fps=30.0,
        offsets_sec=B_BOUNDARY_OFFSETS_SEC,
        anchor="start",
    )

    assert a_indices == (720, 780, 840, 870, 885, 897)
    assert b_indices == (3, 15, 30, 60, 120, 180)
    assert tuple(sorted(a_indices)) == a_indices
    assert tuple(sorted(b_indices)) == b_indices


def test_boundary_sampling_rejects_invalid_video_metadata() -> None:
    for kwargs in (
        {"frame_count": 1, "fps": 30.0},
        {"frame_count": 100, "fps": 0.0},
    ):
        try:
            boundary_frame_indices(
                **kwargs,
                offsets_sec=A_BOUNDARY_OFFSETS_SEC,
                anchor="end",
            )
        except ValueError as exc:
            assert str(exc) == "video_metadata"
        else:
            raise AssertionError("invalid metadata must fail closed")


def test_boundary_sheets_keep_six_large_frames_per_video() -> None:
    frames_a = [np.full((60, 100, 3), i * 20, dtype=np.uint8) for i in range(6)]
    frames_b = [np.full((60, 100, 3), 120 + i * 20, dtype=np.uint8) for i in range(6)]

    sheet_a, sheet_b = build_boundary_sheets(frames_a, frames_b, gap_sec=38.2)

    for sheet in (sheet_a, sheet_b):
        assert sheet.ndim == 3
        assert sheet.shape[2] == 3
        assert sheet.shape[1] > sheet.shape[0]
        assert sheet.shape[1] <= 1536
        assert sheet[:24].mean() > 0
        assert sheet[-20:, :80].mean() >= 0  # 카메라 timestamp 영역을 overlay로 덮지 않아.


def test_dense_contract_names_the_actual_boundary_evidence() -> None:
    assert DENSE_REPRESENTATION == "boundary_dense_two_images_6x2"
    assert DENSE_PROMPT_VERSION == "vlm-event-boundary-dense-v2"
    assert "last six frames" in DENSE_PROMPT
    assert "first six frames" in DENSE_PROMPT
    assert "left-to-right, top-to-bottom" in DENSE_PROMPT
    assert "Judge the boundary between A and B" in DENSE_PROMPT

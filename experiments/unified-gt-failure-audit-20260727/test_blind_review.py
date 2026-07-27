from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import blind_review


def test_uniform_frame_indices_include_both_ends() -> None:
    assert blind_review.uniform_frame_indices(frame_count=10, samples=4) == [0, 3, 6, 9]


def test_uniform_frame_indices_do_not_duplicate_short_video_frames() -> None:
    assert blind_review.uniform_frame_indices(frame_count=3, samples=12) == [0, 1, 2]


def test_compose_contact_sheet_pads_incomplete_last_row() -> None:
    frames = [
        np.full((10, 20, 3), fill_value=value, dtype=np.uint8)
        for value in (10, 20, 30)
    ]

    sheet = blind_review.compose_contact_sheet(frames, columns=2)

    assert sheet.shape == (20, 40, 3)
    assert int(sheet[5, 5, 0]) == 10
    assert int(sheet[5, 25, 0]) == 20
    assert int(sheet[15, 5, 0]) == 30
    assert int(sheet[15, 25, 0]) == 0


def test_review_row_rejects_unknown_primary_cause() -> None:
    with pytest.raises(ValueError, match="unknown_primary_cause"):
        blind_review.validate_review_row(
            {
                "review_id": "review-001",
                "judgeability": "judgeable",
                "primary_cause": "MADE_UP",
                "secondary_causes": [],
            }
        )


def test_review_row_requires_no_cause_when_unjudgeable() -> None:
    blind_review.validate_review_row(
        {
            "review_id": "review-001",
            "judgeability": "unjudgeable",
            "primary_cause": None,
            "secondary_causes": [],
        }
    )


def test_summary_counts_primary_causes_and_judgeability() -> None:
    rows = [
        {
            "review_id": "review-001",
            "judgeability": "judgeable",
            "primary_cause": "IR_LIGHT_REFLECTION",
            "secondary_causes": ["VISIBILITY_SCALE_OCCLUSION"],
        },
        {
            "review_id": "review-002",
            "judgeability": "judgeable",
            "primary_cause": "IR_LIGHT_REFLECTION",
            "secondary_causes": [],
        },
        {
            "review_id": "review-003",
            "judgeability": "unjudgeable",
            "primary_cause": None,
            "secondary_causes": [],
        },
    ]

    assert blind_review.summarize_reviews(rows) == {
        "rows": 3,
        "judgeability": {"judgeable": 2, "unjudgeable": 1},
        "primary_causes": {"IR_LIGHT_REFLECTION": 2},
        "secondary_causes": {"VISIBILITY_SCALE_OCCLUSION": 1},
    }

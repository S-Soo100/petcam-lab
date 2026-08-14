from __future__ import annotations

import pytest

from scripts import build_yolo26n_v25_owner_hardcase_queue as legacy
from scripts import yolo26n_v25_hardcase_science as science


def _frame(
    source: str,
    index: int,
    timestamp: float,
    predictions: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "role": "owner-development-video",
        "source_video_sha256": source * 64,
        "frame_index": index,
        "timestamp_sec": timestamp,
        "image_sha256": f"{index:064x}",
        "width": 100,
        "height": 100,
        "predictions": predictions,
        "jpeg_bytes": b"jpeg",
    }


def _box(confidence: float, xyxy: list[float]) -> dict[str, object]:
    return {"class_id": 0, "confidence": confidence, "box_xyxy": xyxy}


def test_classification_uses_the_frozen_signal_boundaries() -> None:
    frames = [
        _frame("a", 1, 0.0, []),
        _frame("a", 2, 2.0, [_box(0.8, [10, 10, 50, 50])]),
        _frame("b", 3, 0.0, [_box(0.49, [20, 20, 60, 60])]),
        _frame(
            "c",
            4,
            0.0,
            [_box(0.8, [0, 10, 50, 50]), _box(0.7, [0, 10, 50, 50])],
        ),
    ]

    result = science.classify_hardcase_signals(frames)

    assert result[0]["signals"] == ["suspected_miss", "source_diversity"]
    assert result[1]["signals"] == ["source_diversity"]
    assert result[2]["signals"] == [
        "suspected_false_positive",
        "source_diversity",
    ]
    assert result[3]["signals"] == [
        "duplicate_box_signal",
        "partial_occlusion_signal",
        "source_diversity",
    ]


def test_selection_round_robins_sources_with_fixed_caps_and_priority() -> None:
    records: list[dict[str, object]] = []
    for source in ("a", "b"):
        for index in range(8):
            record = _frame(source, index + (0 if source == "a" else 20), float(index), [])
            record["signals"] = [
                "source_diversity" if index else "duplicate_box_signal"
            ]
            records.append(record)

    selected = science.select_blind_queue(records, per_source_cap=6, total_cap=10)

    assert len(selected) == 10
    assert [row["source_video_sha256"] for row in selected[:4]] == [
        "a" * 64,
        "b" * 64,
        "a" * 64,
        "b" * 64,
    ]
    assert selected[0]["signals"] == ["duplicate_box_signal"]
    assert selected[1]["signals"] == ["duplicate_box_signal"]
    assert max(
        sum(row["source_video_sha256"] == source * 64 for row in selected)
        for source in ("a", "b")
    ) <= 6
    assert science.POLICY_ID == "yolo26n-v25-blind-queue-v1"
    assert science.POLICY_SEED == "yolo26n-v25-historical-hardcase-reinforcement-v1"


def test_focused_policy_matches_the_approved_legacy_science() -> None:
    frames = [
        _frame("a", 1, 0.0, []),
        _frame("a", 2, 2.0, [_box(0.8, [10, 10, 50, 50])]),
        _frame("b", 3, 0.0, [_box(0.49, [20, 20, 60, 60])]),
    ]

    assert science.classify_hardcase_signals(frames) == legacy.classify_hardcase_signals(
        frames
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"frame_index": -1},
        {"timestamp_sec": -0.1},
        {"predictions": [_box(1.1, [10, 10, 50, 50])]},
        {"predictions": [_box(0.5, [10, 10, 50, 50])] * 51},
    ],
)
def test_focused_policy_rejects_the_same_invalid_boundaries_as_legacy(
    mutation: dict[str, object],
) -> None:
    frame = _frame("a", 1, 0.0, [])
    frame.update(mutation)

    with pytest.raises(ValueError, match="prediction"):
        science.classify_hardcase_signals([frame])

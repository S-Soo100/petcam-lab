from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

import scripts.materialize_yolo26n_v261_queue as materializer
import scripts.build_yolo26n_v25_owner_hardcase_queue as legacy_miner


@pytest.mark.parametrize(
    ("reasons", "expected"),
    [
        (["owner_confirmed", "position_jump"], (40, 40)),
        (["post_v26_coverage", "detection_gap"], (6, 6)),
        (["post_v26_coverage"], (4, 2)),
        (["iid_control"], (4, 2)),
    ],
)
def test_mining_limits_prioritize_owner_then_anomaly(
    reasons: list[str], expected: tuple[int, int]
) -> None:
    assert materializer.mining_limits(reasons) == expected


def test_load_protected_fingerprints_combines_dataset_exact_and_selection_dhash(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset.json"
    selection = tmp_path / "selection.json"
    dataset.write_text(
        json.dumps(
            {
                "records": [
                    {"image_sha256": "a" * 64},
                    {"image_sha256": "b" * 64},
                ]
            }
        )
    )
    selection.write_text(
        json.dumps(
            {
                "records": [
                    {"clip_ref": "clip-a", "image_sha256": "a" * 64, "dhash64": "0" * 16},
                    {"clip_ref": "clip-c", "image_sha256": "c" * 64, "dhash64": "1" * 16},
                ]
            }
        )
    )

    result = materializer.load_protected_fingerprints(dataset, selection)

    assert result == [
        {"clip_ref": "clip-a", "image_sha256": "a" * 64, "dhash64": "0" * 16},
        {"clip_ref": "clip-c", "image_sha256": "c" * 64, "dhash64": "1" * 16},
    ]
    assert materializer.load_protected_exact_shas(dataset) == {"a" * 64, "b" * 64}


def test_miner_can_use_actual_decoded_count_when_container_count_is_wrong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "source.mp4"
    writer = cv2.VideoWriter(
        str(video), cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (32, 24)
    )
    assert writer.isOpened()
    try:
        for index in range(10):
            writer.write(np.full((24, 32, 3), index * 10, dtype=np.uint8))
    finally:
        writer.release()

    real_capture = cv2.VideoCapture

    class WrongCountCapture:
        def __init__(self, path: str) -> None:
            self._capture = real_capture(path)

        def isOpened(self) -> bool:
            return self._capture.isOpened()

        def get(self, prop: int) -> float:
            value = self._capture.get(prop)
            return value + 3 if prop == cv2.CAP_PROP_FRAME_COUNT else value

        def read(self):
            return self._capture.read()

        def release(self) -> None:
            self._capture.release()

    monkeypatch.setattr(legacy_miner.cv2, "VideoCapture", WrongCountCapture)
    source = legacy_miner._snapshot_source(video)

    with pytest.raises(ValueError, match="frame count"):
        legacy_miner.mine_owner_video(source, uniform_limit=1, scene_limit=1)
    result = legacy_miner.mine_owner_video(
        source,
        uniform_limit=1,
        scene_limit=1,
        strict_reported_frame_count=False,
    )

    assert result["decoded_frame_count"] == 10
    assert result["reported_frame_count"] == 13
    assert result["frame_count_mismatch"] is True

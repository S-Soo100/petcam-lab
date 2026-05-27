"""local Track A artifact/normalization 단위 테스트."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from backend.local_track_a import (
    make_contact_sheet,
    normalize_local_result,
)


def test_normalize_local_result_defaults_unknown_label_to_unseen(tmp_path: Path) -> None:
    result = normalize_local_result(
        clip_id="clip-1",
        model="gemma3:4b",
        contact_sheet_path=tmp_path / "sheet.jpg",
        latency_sec=1.23456,
        raw={
            "label": "teleporting",
            "confidence": 2,
            "evidence": "test",
        },
    )

    assert result.label == "unseen"
    assert result.confidence == 1.0
    assert result.needs_review is True
    assert result.source == "local_vlm"
    assert result.latency_sec == 1.235


def test_normalize_local_result_marks_p0_for_review(tmp_path: Path) -> None:
    result = normalize_local_result(
        clip_id="clip-1",
        model="gemma3:4b",
        contact_sheet_path=tmp_path / "sheet.jpg",
        latency_sec=1,
        raw={
            "label": "drinking",
            "confidence": 0.9,
            "evidence": "head near water bowl",
        },
    )

    assert result.label == "drinking"
    assert result.needs_review is True


def test_make_contact_sheet_writes_jpeg(tmp_path: Path) -> None:
    frames = [
        Image.new("RGB", (80, 60), (255, 0, 0)),
        Image.new("RGB", (80, 60), (0, 255, 0)),
    ]
    out = make_contact_sheet(frames, tmp_path / "sheet.jpg", columns=2, thumb_width=40)

    assert out.is_file()
    with Image.open(out) as sheet:
        assert sheet.format == "JPEG"
        assert sheet.size[0] == 80

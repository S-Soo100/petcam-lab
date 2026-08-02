import base64
import json

import cv2
import numpy as np
import pytest

from scripts.local_vlm_clip_shadow_v2 import (
    FRAME_FRACTIONS,
    PROMPT_VERSION,
    build_ollama_payload,
    encode_individual_frames,
)


def test_fractions_are_twelve_even_points_from_five_to_ninety_five_percent() -> None:
    assert len(FRAME_FRACTIONS) == 12
    assert FRAME_FRACTIONS[0] == pytest.approx(0.05)
    assert FRAME_FRACTIONS[-1] == pytest.approx(0.95)
    gaps = np.diff(FRAME_FRACTIONS)
    assert max(gaps) - min(gaps) < 1e-9
    assert all(left < right for left, right in zip(FRAME_FRACTIONS, FRAME_FRACTIONS[1:]))


def test_encode_returns_twelve_separate_jpegs_without_contact_sheet() -> None:
    frames = [np.full((900, 1200, 3), index * 10, np.uint8) for index in range(12)]
    images = encode_individual_frames(frames)
    assert len(images) == 12
    decoded = [cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR) for image in images]
    assert all(max(frame.shape[:2]) <= 768 for frame in decoded)
    assert [round(float(frame.mean())) for frame in decoded] == [index * 10 for index in range(12)]
    with pytest.raises(ValueError, match="frame_count"):
        encode_individual_frames(frames[:11])


def test_payload_contains_twelve_ordered_images_and_frozen_options() -> None:
    images = tuple(f"image-{index}".encode() for index in range(12))
    payload = build_ollama_payload(images)
    encoded = payload["messages"][0]["images"]
    assert encoded == [base64.b64encode(image).decode("ascii") for image in images]
    assert "1 through 12" in payload["messages"][0]["content"]
    assert payload["think"] is False
    assert payload["options"] == {
        "temperature": 0,
        "seed": 20260802,
        "num_ctx": 4096,
        "num_predict": 320,
    }
    assert payload["format"]["additionalProperties"] is False
    assert PROMPT_VERSION.endswith("v2")
    json.dumps(payload, allow_nan=False)

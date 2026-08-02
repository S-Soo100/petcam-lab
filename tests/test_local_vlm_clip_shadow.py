from __future__ import annotations

from datetime import datetime, timezone
import json

import numpy as np
import pytest

from scripts.local_vlm_clip_shadow import (
    FRAME_FRACTIONS,
    ClipObservation,
    aggregate_public,
    build_contact_sheet,
    parse_observation,
    stop_reason,
)


def _valid_payload() -> dict[str, object]:
    return {
        "gecko_visibility": "visible",
        "activity_state": "active",
        "notable_change": "movement",
        "summary_ko": "게코가 화면 오른쪽으로 이동하는 모습이 보여.",
        "confidence": 0.8,
        "needs_human_review": False,
    }


def test_parse_observation_accepts_exact_schema() -> None:
    value = parse_observation(json.dumps(_valid_payload(), ensure_ascii=False))
    assert value == ClipObservation(
        gecko_visibility="visible",
        activity_state="active",
        notable_change="movement",
        summary_ko="게코가 화면 오른쪽으로 이동하는 모습이 보여.",
        confidence=0.8,
        needs_human_review=False,
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: {**p, "extra": 1},
        lambda p: {**p, "gecko_visibility": "yes"},
        lambda p: {**p, "activity_state": "sleeping"},
        lambda p: {**p, "notable_change": "eating"},
        lambda p: {**p, "summary_ko": "visible gecko"},
        lambda p: {**p, "summary_ko": "가" * 121},
        lambda p: {**p, "confidence": True},
        lambda p: {**p, "confidence": 1.1},
        lambda p: {**p, "needs_human_review": "false"},
    ],
)
def test_parse_observation_rejects_schema_drift(mutate) -> None:
    with pytest.raises(ValueError):
        parse_observation(json.dumps(mutate(_valid_payload()), ensure_ascii=False))


@pytest.mark.parametrize(
    "raw",
    [
        "```json\n{}\n```",
        '{"confidence": NaN}',
        "",
    ],
)
def test_parse_observation_rejects_non_json_contract(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_observation(raw)


def test_frame_fractions_and_contact_sheet_are_fixed() -> None:
    assert FRAME_FRACTIONS == (0.05, 0.20, 0.40, 0.60, 0.80, 0.95)
    frames = [np.full((120, 200, 3), index * 20, np.uint8) for index in range(6)]
    sheet = build_contact_sheet(frames)
    assert sheet.ndim == 3
    assert sheet.shape[2] == 3
    assert sheet.shape[0] == 24 + 120 * 2
    assert sheet.shape[1] == 200 * 3
    assert tuple(sheet[24 + 60, 100]) == (0, 0, 0)
    assert tuple(sheet[24 + 60, 300]) == (20, 20, 20)
    assert tuple(sheet[24 + 180, 500]) == (100, 100, 100)


def test_contact_sheet_rejects_wrong_frame_count_or_shape() -> None:
    frame = np.zeros((10, 10, 3), np.uint8)
    with pytest.raises(ValueError):
        build_contact_sheet([frame] * 5)
    with pytest.raises(ValueError):
        build_contact_sheet([np.zeros((10, 10), np.uint8)] * 6)


def test_stop_reason_prioritizes_completion_attempt_cap_and_deadline() -> None:
    end = datetime(2026, 8, 3, 7, tzinfo=timezone.utc)
    before = datetime(2026, 8, 3, 6, tzinfo=timezone.utc)
    after = datetime(2026, 8, 3, 8, tzinfo=timezone.utc)
    assert stop_reason(before, end, 20, 20, 20) == "LIVE_COMPLETE"
    assert stop_reason(before, end, 19, 20, 20) == "REJECT_RELIABILITY"
    assert stop_reason(after, end, 2, 20, 2) == "INCOMPLETE_LIVE_VOLUME"
    assert stop_reason(before, end, 2, 20, 2) is None


def test_public_aggregate_contains_counts_not_private_identity() -> None:
    records = [
        {"status": "schema_valid", "elapsed_sec": 1.0, "clip_id": "raw", "r2_key": "secret"},
        {"status": "media_error", "error": "r2_missing", "path": "/private"},
        {"status": "invalid", "elapsed_sec": 3.0, "raw": "model output"},
    ]
    aggregate = aggregate_public(records)
    assert aggregate["records"] == 3
    assert aggregate["schema_valid"] == 1
    assert aggregate["media_error"] == 1
    assert aggregate["invalid"] == 1
    encoded = json.dumps(aggregate)
    assert "raw" not in encoded
    assert "secret" not in encoded
    assert "/private" not in encoded

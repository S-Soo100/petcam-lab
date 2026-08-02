import json

import pytest

from scripts.local_vlm_event_boundary import (
    A_FRAME_FRACTIONS,
    B_FRAME_FRACTIONS,
    BoundaryPrediction,
    RESULT_SCHEMA,
    expected_sheet_count,
    parse_prediction,
    score_predictions,
    stable_pair_order,
    wilson_interval,
)


def test_sampler_is_asymmetric_and_boundary_heavy() -> None:
    assert A_FRAME_FRACTIONS == (0.15, 0.55, 0.85, 0.98)
    assert B_FRAME_FRACTIONS == (0.02, 0.15, 0.55, 0.85)


def test_sheet_accounting_depends_on_frozen_representation() -> None:
    assert expected_sheet_count("two_images", pair_count=74) == 148
    assert expected_sheet_count("combined_4x2", pair_count=74) == 74
    with pytest.raises(ValueError, match="representation"):
        expected_sheet_count("unknown", pair_count=74)


def test_result_schema_forbids_extra_fields() -> None:
    assert RESULT_SCHEMA["additionalProperties"] is False
    assert set(RESULT_SCHEMA["required"]) == {
        "decision",
        "confidence",
        "reason_code",
    }


def test_parse_prediction_accepts_exact_json_object() -> None:
    parsed = parse_prediction(json.dumps({
        "decision": "same_event",
        "confidence": 0.75,
        "reason_code": "continuous_motion",
    }))
    assert parsed == BoundaryPrediction(
        decision="same_event",
        confidence=0.75,
        reason_code="continuous_motion",
    )


@pytest.mark.parametrize(
    "payload",
    [
        "```json\n{}\n```",
        '{"decision":"same_event","confidence":NaN,"reason_code":"continuous_motion"}',
        '{"decision":"same_event","confidence":1.1,"reason_code":"continuous_motion"}',
        '{"decision":"maybe","confidence":0.5,"reason_code":"continuous_motion"}',
        '{"decision":"same_event","confidence":0.5,"reason_code":"invented"}',
        '{"decision":"same_event","confidence":0.5,"reason_code":"continuous_motion","extra":1}',
    ],
)
def test_parse_prediction_rejects_non_contract_output(payload: str) -> None:
    with pytest.raises(ValueError):
        parse_prediction(payload)


def test_score_prioritizes_overmerge_and_counts_failures() -> None:
    human = {
        "p1": "different_event",
        "p2": "same_event",
        "p3": "same_event",
    }
    predictions = {
        "p1": BoundaryPrediction("same_event", 0.8, "continuous_posture"),
        "p2": BoundaryPrediction("different_event", 0.6, "clear_stop"),
        "p3": None,
    }
    score = score_predictions(human, predictions, expected_count=3)
    assert score.overmerge == 1
    assert score.oversplit == 1
    assert score.schema_valid == 2
    assert score.completed == 3
    assert score.same_recall == 0.0
    assert score.verdict == "REJECT_RELIABILITY"


def test_development_candidate_requires_zero_overmerge_and_half_same_recall() -> None:
    human = {
        **{f"d{i}": "different_event" for i in range(17)},
        **{f"s{i}": "same_event" for i in range(57)},
    }
    predictions = {
        **{
            f"d{i}": BoundaryPrediction(
                "different_event", 0.9, "clear_stop"
            )
            for i in range(17)
        },
        **{
            f"s{i}": BoundaryPrediction(
                "same_event" if i < 29 else "uncertain",
                0.8,
                "continuous_motion" if i < 29 else "insufficient_visual",
            )
            for i in range(57)
        },
    }
    score = score_predictions(human, predictions, expected_count=74)
    assert score.overmerge == 0
    assert score.same_correct == 29
    assert score.verdict == "DEVELOPMENT_CANDIDATE"


def test_wilson_interval_contains_observed_rate() -> None:
    lower, upper = wilson_interval(29, 57)
    assert 0 <= lower < 29 / 57 < upper <= 1


def test_stable_pair_order_is_repeatable_and_complete() -> None:
    pair_keys = ["c", "a", "b"]
    first = stable_pair_order(pair_keys, seed="20260802")
    second = stable_pair_order(reversed(pair_keys), seed="20260802")
    assert first == second
    assert set(first) == set(pair_keys)

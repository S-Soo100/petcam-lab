import json

import numpy as np
import pytest

from scripts.local_vlm_purchase_gate import (
    MODELS,
    SyntheticPrediction,
    boundary_synthetic_cases,
    clip_synthetic_cases,
    parse_synthetic_prediction,
    purchase_verdict,
)


def test_clip_synthetic_cases_are_seven_twelve_frame_contrasts() -> None:
    cases = clip_synthetic_cases()
    assert len(cases) == 7
    assert {case.name for case in cases} == {
        "dark",
        "clean_static",
        "clean_moving",
        "shadow_static",
        "shadow_moving",
        "brightness_static",
        "brightness_moving",
    }
    assert all(len(case.frames) == 12 for case in cases)
    assert all(frame.shape == (360, 640, 3) for case in cases for frame in case.frames)
    assert np.array_equal(cases[1].frames[0], cases[1].frames[-1])
    assert not np.array_equal(cases[2].frames[0], cases[2].frames[-1])


def test_boundary_synthetic_cases_match_real_eight_image_contract() -> None:
    cases = boundary_synthetic_cases()
    assert len(cases) == 2
    assert [case.expected for case in cases] == ["same_event", "different_event"]
    assert all(len(case.frames) == 8 for case in cases)


def test_parse_synthetic_prediction_is_strict() -> None:
    parsed = parse_synthetic_prediction('{"background":"lit","position_change":"yes"}')
    assert parsed == SyntheticPrediction(background="lit", position_change="yes")
    with pytest.raises(ValueError):
        parse_synthetic_prediction('{"background":"lit","position_change":"yes","extra":1}')
    with pytest.raises(ValueError):
        parse_synthetic_prediction(json.dumps({"background": "night", "position_change": "yes"}))


def test_purchase_verdict_requires_all_small_models_to_be_evaluated() -> None:
    statuses = {model: "QUALITY_FAIL" for model in MODELS}
    statuses[MODELS[-1]] = "PASS"
    assert purchase_verdict(statuses) == "MAC_STUDIO_64GB_PURCHASE_EVIDENCE_PENDING_HOLDOUT"

    statuses[MODELS[1]] = "RESOURCE_FAIL"
    assert purchase_verdict(statuses) == "INCONCLUSIVE_NEEDS_COMPATIBLE_HARDWARE"

    statuses = {model: "QUALITY_FAIL" for model in MODELS}
    statuses[MODELS[1]] = "PASS"
    assert purchase_verdict(statuses) == "MAC_STUDIO_NOT_REQUIRED_FOR_QUALITY"

    statuses = {model: "SYNTHETIC_GATE_FAIL" for model in MODELS}
    assert purchase_verdict(statuses) == "NO_MAC_STUDIO_PURCHASE_EVIDENCE"


def test_purchase_verdict_rejects_incomplete_or_unknown_status() -> None:
    with pytest.raises(ValueError):
        purchase_verdict({MODELS[0]: "QUALITY_FAIL"})
    with pytest.raises(ValueError):
        purchase_verdict({model: "mystery" for model in MODELS})

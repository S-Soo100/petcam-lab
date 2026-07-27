from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent))

from analyze import (  # noqa: E402
    auc_higher,
    cluster_bootstrap,
    decide,
    summarize,
    validate_snapshot,
)


SMALL_EXPECTED = {
    "eligible_count": 4,
    "eligible_ordered_sha256": "a" * 64,
    "moving_count": 2,
    "static_only_count": 2,
    "excluded_count": 0,
    "episode_count": 4,
    "provenance_contract_count": 1,
}


def _record(
    sample: str,
    episode: str,
    camera: str,
    label: str,
    roi_mean: float | None,
) -> dict:
    return {
        "sample_key": sample,
        "episode_key": episode,
        "camera_group": camera,
        "camera_night": f"{camera}:2026-07-22",
        "label": label,
        "level0_status": "ok",
        "level1_status": "ok",
        "decoded_frame_count": 30,
        "global_series_length": 30,
        "roi_series_length": 30,
        "roi_mean": roi_mean,
        "observed_sec": 20.0,
        "peak_autocorr": 0.2,
    }


def fixture_snapshot() -> dict:
    return {
        "contract": dict(SMALL_EXPECTED),
        "records": [
            _record("s1", "e1", "camera_1", "moving", 4.0),
            _record("s2", "e2", "camera_1", "moving", 3.0),
            _record("s3", "e3", "camera_1", "static_only", 2.0),
            _record("s4", "e4", "camera_1", "static_only", 1.0),
        ],
    }


def test_validate_snapshot_accepts_injected_contract() -> None:
    validate_snapshot(fixture_snapshot(), expected=SMALL_EXPECTED)


def test_validate_snapshot_rejects_population_drift() -> None:
    snapshot = fixture_snapshot()
    snapshot["contract"]["eligible_count"] = 3

    with pytest.raises(ValueError, match="eligible_count"):
        validate_snapshot(snapshot, expected=SMALL_EXPECTED)


def test_validate_snapshot_rejects_duplicate_sample_key() -> None:
    snapshot = fixture_snapshot()
    snapshot["records"][1]["sample_key"] = "s1"

    with pytest.raises(ValueError, match="sample_key"):
        validate_snapshot(snapshot, expected=SMALL_EXPECTED)


def test_validate_snapshot_rejects_non_finite_feature() -> None:
    snapshot = fixture_snapshot()
    snapshot["records"][0]["roi_mean"] = math.inf

    with pytest.raises(ValueError, match="finite"):
        validate_snapshot(snapshot, expected=SMALL_EXPECTED)


def test_auc_higher_perfect_and_tied() -> None:
    perfect = fixture_snapshot()["records"]
    assert auc_higher(perfect, "roi_mean") == 1.0

    tied = [
        _record("s1", "e1", "camera_1", "moving", 1.0),
        _record("s2", "e2", "camera_1", "static_only", 1.0),
    ]
    assert auc_higher(tied, "roi_mean") == 0.5


def test_cluster_bootstrap_is_deterministic_and_clustered() -> None:
    records = fixture_snapshot()["records"]

    result_a = cluster_bootstrap(records, "roi_mean", iterations=200, seed=7)
    result_b = cluster_bootstrap(records, "roi_mean", iterations=200, seed=7)

    assert result_a == result_b
    assert 0 < result_a["valid_iterations"] <= 200
    assert result_a["sampled_episode_count"] == 4
    assert 0.0 <= result_a["ci_low"] <= result_a["ci_high"] <= 1.0


@pytest.mark.parametrize(
    ("primary", "expected"),
    [
        (
            {
                "coverage": 0.96,
                "ci_low": 0.60,
                "ci_high": 0.80,
                "valid_fraction": 1.0,
                "camera_auc": {"camera_1": 0.60, "camera_2": 0.70},
            },
            "PE_MOTION_SIGNAL_DESCRIPTIVE_SUPPORTED",
        ),
        (
            {
                "coverage": 0.96,
                "ci_low": 0.48,
                "ci_high": 0.75,
                "valid_fraction": 1.0,
                "camera_auc": {"camera_1": 0.60, "camera_2": 0.70},
            },
            "PE_MOTION_SIGNAL_INCONCLUSIVE",
        ),
        (
            {
                "coverage": 0.70,
                "ci_low": 0.40,
                "ci_high": 0.90,
                "valid_fraction": 1.0,
                "camera_auc": {"camera_1": 0.60, "camera_2": 0.70},
            },
            "PE_MOTION_SIGNAL_REJECTED",
        ),
    ],
)
def test_decide(primary: dict, expected: str) -> None:
    assert decide({"primary": primary}) == expected


def test_summarize_reports_primary_and_secondary_metrics() -> None:
    summary = summarize(
        fixture_snapshot(),
        expected=SMALL_EXPECTED,
        iterations=200,
        seed=7,
    )

    assert summary["technical"]["eligible_count"] == 4
    assert summary["technical"]["level0_ok"] == 4
    assert summary["labels"] == {"excluded": 0, "moving": 2, "static_only": 2}
    assert summary["primary"]["auc"] == 1.0
    assert summary["primary"]["coverage"] == 1.0
    assert summary["secondary"]["observed_sec"]["non_null"] == 4
    assert summary["verdict"] == "PE_MOTION_SIGNAL_INCONCLUSIVE"

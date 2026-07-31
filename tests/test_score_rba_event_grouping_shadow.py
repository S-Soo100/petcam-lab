from __future__ import annotations

import stat
from pathlib import Path

import pytest

from scripts.prepare_rba_event_grouping_shadow import BoundaryPair
from scripts.score_rba_event_grouping_shadow import (
    GTIntegrityError,
    HoldoutMetrics,
    choose_development_threshold,
    finalize_boundary_gt,
    freeze_development_threshold,
    score_frozen_holdout,
    validate_reviewer_rows,
)


def rows(
    decisions: dict[str, str],
    fingerprint: str,
) -> list[dict[str, object]]:
    return [
        {
            "pair_id": pair_id,
            "decision": decision,
            "reason": None,
            "reviewer_fingerprint": fingerprint,
            "source_sha256": "a" * 64,
        }
        for pair_id, decision in decisions.items()
    ]


def test_reviewer_and_owner_integrity() -> None:
    expected = {f"p{i:03d}" for i in range(120)}
    a_values = {pair_id: "same_event" for pair_id in expected}
    b_values = dict(a_values)
    b_values["p000"] = "different_event"
    b_values["p001"] = "uncertain"
    reviewer_a = validate_reviewer_rows(rows(a_values, "reviewer-a"), expected)
    reviewer_b = validate_reviewer_rows(rows(b_values, "reviewer-b"), expected)
    owner = [
        {"pair_id": "p000", "decision": "different_event", "reason": "break"},
        {"pair_id": "p001", "decision": "same_event", "reason": "visible"},
    ]
    final = finalize_boundary_gt(expected, reviewer_a, reviewer_b, owner)
    assert final.unresolved_count == 0
    assert final.decisions["p000"] == "different_event"
    assert final.decisions["p001"] == "same_event"
    assert final.raw_agreement == pytest.approx(118 / 120)


@pytest.mark.parametrize(
    "mutation",
    ("missing", "duplicate", "unexpected", "invalid", "raw_clip", "long_reason"),
)
def test_reviewer_rows_fail_closed(mutation: str) -> None:
    expected = {f"p{i:03d}" for i in range(120)}
    payload = rows({pair_id: "same_event" for pair_id in expected}, "reviewer-a")
    if mutation == "missing":
        payload.pop()
    elif mutation == "duplicate":
        payload.append(dict(payload[0]))
    elif mutation == "unexpected":
        payload[-1]["pair_id"] = "outside"
    elif mutation == "invalid":
        payload[-1]["decision"] = "maybe"
    elif mutation == "raw_clip":
        payload[-1]["clip_id"] = "secret"
    else:
        payload[-1]["reason"] = "x" * 201
    with pytest.raises(GTIntegrityError):
        validate_reviewer_rows(payload, expected)


def test_owner_rows_must_be_exactly_needed() -> None:
    expected = {f"p{i:03d}" for i in range(120)}
    values = {pair_id: "same_event" for pair_id in expected}
    reviewer_a = validate_reviewer_rows(rows(values, "a"), expected)
    reviewer_b = validate_reviewer_rows(rows(values, "b"), expected)
    with pytest.raises(GTIntegrityError, match="unnecessary_owner"):
        finalize_boundary_gt(
            expected,
            reviewer_a,
            reviewer_b,
            [{"pair_id": "p000", "decision": "same_event", "reason": None}],
        )


def test_reviewer_fingerprints_must_differ() -> None:
    expected = {f"p{i:03d}" for i in range(120)}
    values = {pair_id: "same_event" for pair_id in expected}
    reviewer_a = validate_reviewer_rows(rows(values, "same"), expected)
    reviewer_b = validate_reviewer_rows(rows(values, "same"), expected)
    with pytest.raises(GTIntegrityError, match="reviewer_fingerprint"):
        finalize_boundary_gt(expected, reviewer_a, reviewer_b, [])


def test_choose_threshold_requires_zero_overmerge_then_minimizes_oversplit() -> None:
    pairs = (
        BoundaryPair("a", "a1", "a2", "cam", __import__("datetime").date(2026, 7, 1), 4, "le15"),
        BoundaryPair("b", "b1", "b2", "cam", __import__("datetime").date(2026, 7, 1), 20, "15to60"),
        BoundaryPair("c", "c1", "c2", "cam", __import__("datetime").date(2026, 7, 1), 70, "60to300"),
    )
    decisions = {"a": "same_event", "b": "same_event", "c": "different_event"}
    assert choose_development_threshold(pairs, decisions) == 30


def test_freeze_is_0600_and_no_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "freeze.json"
    freeze_development_threshold(
        path,
        threshold_sec=15,
        manifest_sha256="a" * 64,
        development_gt_sha256="b" * 64,
    )
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        freeze_development_threshold(
            path,
            threshold_sec=15,
            manifest_sha256="a" * 64,
            development_gt_sha256="b" * 64,
        )


def good_metrics(**overrides: object) -> HoldoutMetrics:
    values: dict[str, object] = {
        "expected_pair_count": 60,
        "reviewer_agreement": 0.9,
        "uncertain_rate": 0.1,
        "over_merge_count": 0,
        "camera_over_merge_counts": {"a": 0, "b": 0},
        "over_split_rate": 0.2,
        "camera_over_split_rates": {"a": 0.2, "b": 0.2},
        "camera_class_counts": {
            "a": {"same_event": 10, "different_event": 10},
            "b": {"same_event": 10, "different_event": 10},
        },
        "event_reduction_rate": 0.2,
        "accounting_unassigned": 0,
        "accounting_duplicates": 0,
        "diagnostic_cross_merges": 0,
        "protected_clip_contacts": 0,
        "rerun_hashes": ("x", "x", "x"),
    }
    values.update(overrides)
    return HoldoutMetrics(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("metrics", "verdict"),
    (
        (good_metrics(over_merge_count=1), "REJECT"),
        (good_metrics(accounting_unassigned=1), "REJECT"),
        (good_metrics(rerun_hashes=("x", "y", "x")), "REJECT"),
        (good_metrics(camera_over_split_rates={"a": 0.31, "b": 0.2}), "REJECT"),
        (good_metrics(uncertain_rate=0.26), "HOLD"),
        (good_metrics(event_reduction_rate=0.149), "HOLD"),
        (good_metrics(), "ADOPT_SHADOW_GROUPING_V1"),
    ),
)
def test_holdout_verdict_order(
    tmp_path: Path,
    metrics: HoldoutMetrics,
    verdict: str,
) -> None:
    freeze = tmp_path / "freeze.json"
    freeze_development_threshold(
        freeze,
        threshold_sec=15,
        manifest_sha256="a" * 64,
        development_gt_sha256="b" * 64,
    )
    output = tmp_path / f"{verdict}.json"
    summary = score_frozen_holdout(
        freeze_path=freeze,
        threshold_sec=15,
        manifest_sha256="a" * 64,
        metrics=metrics,
        output_path=output,
    )
    assert summary.verdict == verdict
    with pytest.raises(FileExistsError):
        score_frozen_holdout(
            freeze_path=freeze,
            threshold_sec=15,
            manifest_sha256="a" * 64,
            metrics=metrics,
            output_path=output,
        )


def test_holdout_rejects_threshold_mismatch(tmp_path: Path) -> None:
    freeze = tmp_path / "freeze.json"
    freeze_development_threshold(
        freeze,
        threshold_sec=15,
        manifest_sha256="a" * 64,
        development_gt_sha256="b" * 64,
    )
    with pytest.raises(GTIntegrityError, match="threshold"):
        score_frozen_holdout(
            freeze_path=freeze,
            threshold_sec=30,
            manifest_sha256="a" * 64,
            metrics=good_metrics(),
            output_path=tmp_path / "result.json",
        )

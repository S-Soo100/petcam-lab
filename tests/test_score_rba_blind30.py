"""Formal Blind30 immutable raw submission scorer contract."""

from __future__ import annotations

import hashlib
import json
import stat
from copy import deepcopy

from scripts.score_rba_blind30 import (
    classify_result,
    main,
    match_segments,
    score_blind30,
    write_report,
)


def _gt() -> dict[str, object]:
    return {
        "visibility": "visible",
        "primary_action": "moving",
        "observed_actions": ["moving"],
        "segments": [{"action": "moving", "start_sec": 1.0, "end_sec": 6.0}],
        "target": "floor",
        "human_confidence": "certain",
        "context_tags": ["ir"],
        "activity_intensity": None,
        "highlight_recommendation": "include",
        "enrichment_object": "none",
        "interaction_types": [],
        "note": None,
    }


def _submission(
    index: int,
    *,
    decision: str = "label",
    confidence: str = "certain",
) -> dict[str, object]:
    gt = _gt() if decision == "label" else None
    if gt is not None:
        gt["human_confidence"] = confidence
    return {
        "clip_id": f"10000000-0000-0000-0000-{index:012d}",
        "decision": decision,
        "reason_code": "behavior_data" if decision == "label" else "ambiguous",
        "initial_gt": gt,
        "submitted_at": "2026-08-01T00:00:00Z",
        # non-label raw export may carry a derived abstain marker, never an answer.
        "confidence": confidence,
        "note": "must never be copied to the report",
    }


def _complete_pair() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    first = [_submission(index) for index in range(1, 31)]
    return first, deepcopy(first)


def test_agreement_is_scored_from_raw_submissions_not_consensus() -> None:
    a = _submission(1, decision="hold", confidence="uncertain")
    b = _submission(1, decision="hold", confidence="certain")
    result = score_blind30([a], [b])
    assert result["automatic_agreement"] == 0
    assert result["owner_adjudication"] == 1


def test_two_abstains_are_not_automatic_agreement() -> None:
    a = _submission(1, decision="hold", confidence="uncertain")
    b = _submission(1, decision="hold", confidence="unjudgeable")
    result = score_blind30([a], [b])
    assert result["automatic_agreement"] == 0
    assert result["owner_adjudication"] == 1


def test_segment_matching_uses_maximum_cardinality_and_is_order_independent() -> None:
    # A0 can match both B rows, A1 can only match B0. A greedy A0->B0 would lose one TP.
    a = [
        {"action": "moving", "start_sec": 0.0, "end_sec": 10.0},
        {"action": "moving", "start_sec": 0.0, "end_sec": 4.0},
        {"action": "licking", "start_sec": 20.0, "end_sec": 24.0},
    ]
    b = [
        {"action": "moving", "start_sec": 0.0, "end_sec": 5.0},
        {"action": "moving", "start_sec": 2.0, "end_sec": 10.0},
        {"action": "licking", "start_sec": 21.0, "end_sec": 25.0},
    ]
    assert match_segments(a, b) == {"tp": 3, "fp": 0, "fn": 0}
    assert match_segments(list(reversed(a)), list(reversed(b))) == {
        "tp": 3,
        "fp": 0,
        "fn": 0,
    }


def test_segment_unmatched_rows_become_fp_and_fn() -> None:
    a = [
        {"action": "moving", "start_sec": 0.0, "end_sec": 5.0},
        {"action": "licking", "start_sec": 10.0, "end_sec": 15.0},
    ]
    b = [
        {"action": "moving", "start_sec": 1.0, "end_sec": 6.0},
        {"action": "static", "start_sec": 10.0, "end_sec": 15.0},
    ]
    assert match_segments(a, b) == {"tp": 1, "fp": 1, "fn": 1}


def test_complete_identical_pair_passes() -> None:
    a, b = _complete_pair()
    metrics = score_blind30(a, b)
    assert classify_result(metrics) == "PASS"
    assert metrics["decision"]["agreements"] == 30
    assert metrics["segment"]["f1"] == 1.0
    assert metrics["automatic_agreement"] == 30


def test_seven_conflicts_fail_frozen_thresholds() -> None:
    a, b = _complete_pair()
    for row in b[:7]:
        row["decision"] = "hold"
        row["reason_code"] = "ambiguous"
        row["initial_gt"] = None
    metrics = score_blind30(a, b)
    assert metrics["owner_adjudication"] == 7
    assert classify_result(metrics) == "FAIL"


def test_low_evaluable_denominator_is_hold() -> None:
    a = [_submission(index, decision="hold") for index in range(1, 31)]
    b = deepcopy(a)
    metrics = score_blind30(a, b)
    assert metrics["visibility"]["evaluable"] == 0
    assert classify_result(metrics) == "HOLD"


def test_duplicate_and_missing_submissions_fail() -> None:
    a, b = _complete_pair()
    a[-1] = deepcopy(a[0])
    metrics = score_blind30(a, b)
    assert metrics["completeness"]["duplicate_a"] == 1
    assert metrics["completeness"]["missing_a"] == 1
    assert classify_result(metrics) == "FAIL"


def test_report_is_private_and_deterministic(tmp_path) -> None:
    a, b = _complete_pair()
    metrics = score_blind30(a, b)
    report = {"schema": "rba-blind30-report-v1", "verdict": "PASS", "metrics": metrics}
    output = tmp_path / "report.json"
    digest = write_report(output, report)
    raw = output.read_text()

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert digest == hashlib.sha256(output.read_bytes()).hexdigest()
    assert "must never be copied" not in raw
    for forbidden in ("email", "reviewer_id", "r2_key", "signed_url", "credential"):
        assert forbidden not in raw

    second = tmp_path / "report-second.json"
    assert write_report(second, json.loads(raw)) == digest
    assert second.read_bytes() == output.read_bytes()


def test_json_cli_requires_manifest_exact30_and_writes_private_report(
    tmp_path,
    capsys,
) -> None:
    a, b = _complete_pair()
    submissions = tmp_path / "submissions.json"
    manifest = tmp_path / "manifest.json"
    output = tmp_path / "report.json"
    submissions.write_text(json.dumps({"reviewer_a": a, "reviewer_b": b}))
    manifest.write_text(
        json.dumps(
            {
                "clips": [
                    {"clip_id": f"10000000-0000-0000-0000-{index:012d}"}
                    for index in range(1, 31)
                ]
            }
        )
    )

    assert main(
        [
            "--submissions",
            str(submissions),
            "--manifest",
            str(manifest),
            "--out",
            str(output),
        ]
    ) == 0
    assert "RBA_BLIND30_SCORE=PASS" in capsys.readouterr().out
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    raw = output.read_text()
    assert "must never be copied" not in raw
    assert "reviewer_id" not in raw

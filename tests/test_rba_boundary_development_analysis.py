from __future__ import annotations

import dataclasses
import json

import pytest

from scripts.rba_boundary_development_analysis import (
    AnalysisBlocked,
    AssignmentRow,
    ResolutionRow,
    StudySnapshot,
    SubmissionRow,
    analyze_study,
    render_public_report,
)


PINNED_DIGEST = "edd3f2c230adacb70c0b8bc70072eb632eb0ac48718bdd1ffbeca88649e9dfca"


@pytest.fixture
def manifest() -> dict[str, object]:
    pairs = []
    for index in range(120):
        pairs.append({
            "ordinal": index + 1,
            "run_ordinal": 1,
            "left_clip_id": f"clip-{index:03d}",
            "right_clip_id": f"clip-{index + 1:03d}",
            "camera_id": "secret-camera",
            "activity_day_kst": "2026-07-31",
            "gap_sec": float((index % 6) * 20),
            "gap_bin": f"bin-{index % 6}",
            "pair_digest": f"digest-{index:03d}",
        })
    return {
        "experiment_id": "rba-event-sequence-review-v2",
        "manifest_sha256": PINNED_DIGEST,
        "pairs": pairs,
    }


@pytest.fixture
def snapshot(manifest: dict[str, object]) -> StudySnapshot:
    manifest_pairs = manifest["pairs"]
    assert isinstance(manifest_pairs, list)
    effective_pairs = tuple({
        "pair_id": f"pair-{index:03d}",
        "pair_digest": manifest_pairs[index]["pair_digest"],
        "ordinal": index + 1,
        "gap_sec": manifest_pairs[index]["gap_sec"],
        "gap_bin": manifest_pairs[index]["gap_bin"],
    } for index in range(74))
    assignments = []
    submissions = []
    resolutions = []
    for index, pair in enumerate(effective_pairs):
        pair_id = str(pair["pair_id"])
        owner_decision = "same_event" if index % 3 == 0 else "different_event"
        peer_decision = owner_decision if index < 48 else (
            "different_event" if owner_decision == "same_event" else "same_event"
        )
        for reviewer_id, reviewer_role, decision in (
            ("owner-uuid@example.com", "owner", owner_decision),
            ("peer-uuid@example.com", "peer", peer_decision),
        ):
            assignment_id = f"assignment-{index:03d}-{reviewer_role}"
            assignments.append(AssignmentRow(
                assignment_id=assignment_id,
                pair_id=pair_id,
                reviewer_id=reviewer_id,
                reviewer_role=reviewer_role,
            ))
            submissions.append(SubmissionRow(
                assignment_id=assignment_id,
                pair_id=pair_id,
                reviewer_id=reviewer_id,
                decision=decision,
            ))
        if index >= 48:
            resolutions.append(ResolutionRow(
                pair_id=pair_id,
                final_decision=owner_decision,
            ))
    return StudySnapshot(
        experiment_id="rba-event-sequence-review-v2",
        manifest_digest=PINNED_DIGEST,
        total_pair_count=120,
        effective_pairs=effective_pairs,
        assignments=tuple(assignments),
        submissions=tuple(submissions),
        resolutions=tuple(resolutions),
    )


def test_count_drift_is_blocked(snapshot: StudySnapshot, manifest: dict[str, object]) -> None:
    broken = dataclasses.replace(snapshot, submissions=snapshot.submissions[:-1])
    with pytest.raises(AnalysisBlocked, match="COUNT_DRIFT"):
        analyze_study(broken, manifest, b"fixed-salt")


def test_missing_resolution_is_blocked(snapshot: StudySnapshot, manifest: dict[str, object]) -> None:
    wrong = list(snapshot.resolutions)
    wrong[0] = dataclasses.replace(wrong[0], pair_id="pair-000")
    with pytest.raises(AnalysisBlocked, match="RESOLUTION_SET_MISMATCH"):
        analyze_study(
            dataclasses.replace(snapshot, resolutions=tuple(wrong)),
            manifest,
            b"fixed-salt",
        )


def test_manifest_provenance_mismatch_is_blocked(
    snapshot: StudySnapshot,
    manifest: dict[str, object],
) -> None:
    broken = dict(manifest)
    broken["manifest_sha256"] = "0" * 64
    with pytest.raises(AnalysisBlocked, match="COHORT_PROVENANCE"):
        analyze_study(snapshot, broken, b"fixed-salt")


def test_each_effective_pair_requires_owner_and_peer_roles(
    snapshot: StudySnapshot,
    manifest: dict[str, object],
) -> None:
    assignments = list(snapshot.assignments)
    assignments[0] = dataclasses.replace(assignments[0], reviewer_role="peer")
    with pytest.raises(AnalysisBlocked, match="ASSIGNMENT_BIJECTION"):
        analyze_study(
            dataclasses.replace(snapshot, assignments=tuple(assignments)),
            manifest,
            b"fixed-salt",
        )


def test_database_float_roundtrip_noise_is_accepted(
    snapshot: StudySnapshot,
    manifest: dict[str, object],
) -> None:
    effective = list(snapshot.effective_pairs)
    effective[0] = {**effective[0], "gap_sec": float(effective[0]["gap_sec"]) + 4e-13}

    result = analyze_study(
        dataclasses.replace(snapshot, effective_pairs=tuple(effective)),
        manifest,
        b"fixed-salt",
    )

    assert result.gt_verdict == "DEVELOPMENT_EVENT_GT_READY_FOR_LOCAL_VLM_BASELINE"


def test_meaningful_gap_provenance_drift_is_blocked(
    snapshot: StudySnapshot,
    manifest: dict[str, object],
) -> None:
    effective = list(snapshot.effective_pairs)
    effective[0] = {**effective[0], "gap_sec": float(effective[0]["gap_sec"]) + 1e-6}

    with pytest.raises(AnalysisBlocked, match="PAIR_PROVENANCE:gap"):
        analyze_study(
            dataclasses.replace(snapshot, effective_pairs=tuple(effective)),
            manifest,
            b"fixed-salt",
        )


def test_analysis_builds_metrics_groups_and_threshold(snapshot: StudySnapshot, manifest: dict[str, object]) -> None:
    result = analyze_study(snapshot, manifest, b"fixed-salt")

    assert result.gt_verdict == "DEVELOPMENT_EVENT_GT_READY_FOR_LOCAL_VLM_BASELINE"
    assert result.counts == {
        "total_pairs": 120,
        "effective_pairs": 74,
        "assignments": 148,
        "submissions": 148,
        "resolutions": 26,
    }
    assert result.raw_agreement == pytest.approx(48 / 74)
    assert result.owner_intervention_rate == pytest.approx(26 / 74)
    assert result.owner_initial_adoption_rate == pytest.approx(1.0)
    assert result.source_clip_count == 75
    assert result.human_event_count == 50
    assert result.event_reduction == pytest.approx(1 - 50 / 75)
    assert sum(sum(row) for row in result.confusion_matrix) == 74
    assert result.selected_threshold_sec in (0, 5, 15, 30, 60, 120, None)
    assert result.selected_threshold_sec == 0
    assert result.utility_verdict == "EVENT_GT_READY_ROUTER_UTILITY_HOLD"


def test_final_uncertain_returns_hold_without_guessing(
    snapshot: StudySnapshot,
    manifest: dict[str, object],
) -> None:
    resolutions = list(snapshot.resolutions)
    resolutions[0] = dataclasses.replace(resolutions[0], final_decision="uncertain")
    result = analyze_study(
        dataclasses.replace(snapshot, resolutions=tuple(resolutions)),
        manifest,
        b"fixed-salt",
    )
    assert result.gt_verdict == "HOLD_UNRESOLVED_BOUNDARY"
    assert result.utility_verdict == "EVENT_GT_READY_ROUTER_UTILITY_HOLD"


def test_final_uncertain_forces_utility_hold_even_with_practical_threshold(
    snapshot: StudySnapshot,
    manifest: dict[str, object],
) -> None:
    changed_manifest = dict(manifest)
    changed_pairs = [dict(row) for row in manifest["pairs"]]  # type: ignore[union-attr]
    changed_effective = []
    for index, row in enumerate(snapshot.effective_pairs):
        gap = 20.0 if index % 3 == 0 else 100.0
        changed_pairs[index]["gap_sec"] = gap
        changed_effective.append({**row, "gap_sec": gap})
    changed_manifest["pairs"] = changed_pairs
    resolutions = list(snapshot.resolutions)
    resolutions[0] = dataclasses.replace(resolutions[0], final_decision="uncertain")

    result = analyze_study(
        dataclasses.replace(
            snapshot,
            effective_pairs=tuple(changed_effective),
            resolutions=tuple(resolutions),
        ),
        changed_manifest,
        b"fixed-salt",
    )

    assert result.selected_threshold_sec == 30
    assert result.event_reduction >= 0.15
    assert result.gt_verdict == "HOLD_UNRESOLVED_BOUNDARY"
    assert result.utility_verdict == "EVENT_GT_READY_ROUTER_UTILITY_HOLD"


def test_reordered_inputs_keep_identical_private_payload(
    snapshot: StudySnapshot,
    manifest: dict[str, object],
) -> None:
    first = analyze_study(snapshot, manifest, b"fixed-salt")
    reversed_snapshot = dataclasses.replace(
        snapshot,
        effective_pairs=tuple(reversed(snapshot.effective_pairs)),
        assignments=tuple(reversed(snapshot.assignments)),
        submissions=tuple(reversed(snapshot.submissions)),
        resolutions=tuple(reversed(snapshot.resolutions)),
    )
    second = analyze_study(reversed_snapshot, manifest, b"fixed-salt")
    assert first.private_payload_sha256 == second.private_payload_sha256
    assert first.public_report_sha256 == second.public_report_sha256


def test_public_report_redacts_source_identifiers(
    snapshot: StudySnapshot,
    manifest: dict[str, object],
) -> None:
    result = analyze_study(snapshot, manifest, b"fixed-salt")
    report = render_public_report(result)

    assert "0초는 실용 자동 묶기 기준으로 채택하지 않아" in report

    for forbidden in (
        "owner-uuid@example.com",
        "peer-uuid@example.com",
        "secret-camera",
        "2026-07-31",
        "clip-000",
        "pair-000",
        "digest-000",
    ):
        assert forbidden not in report
    json.dumps(result.to_private_dict(), ensure_ascii=False)

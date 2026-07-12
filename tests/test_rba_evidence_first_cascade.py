import pytest

from scripts.rba_evidence_first_cascade import (
    CascadeDecision,
    ScoredDecision,
    VideoEvidence,
    calibrate_moving_rule,
    route_with_conservative_rules,
    score_cascade,
)


def test_route_auto_labels_only_strong_simple_motion_as_moving() -> None:
    evidence = VideoEvidence(
        sample_id="sample-001",
        clip_id="clip-001",
        duration_sec=60.0,
        width=1920,
        height=1080,
        fps=30.0,
        frame_count=1800,
        brightness_mean=92.0,
        brightness_std=30.0,
        saturation_mean=18.0,
        motion_mean=0.035,
        motion_peak=0.14,
        motion_std=0.02,
        active_motion_ratio=0.82,
        center_motion_ratio=0.48,
        late_motion_ratio=0.34,
    )

    decision = route_with_conservative_rules(evidence)

    assert decision.route == "auto_label"
    assert decision.predicted_action == "moving"
    assert "strong_simple_motion" in decision.reason


def test_route_sends_ambiguous_low_motion_to_fallback() -> None:
    evidence = VideoEvidence(
        sample_id="sample-002",
        clip_id="clip-002",
        duration_sec=60.0,
        width=1920,
        height=1080,
        fps=30.0,
        frame_count=1800,
        brightness_mean=70.0,
        brightness_std=12.0,
        saturation_mean=10.0,
        motion_mean=0.006,
        motion_peak=0.025,
        motion_std=0.005,
        active_motion_ratio=0.12,
        center_motion_ratio=0.51,
        late_motion_ratio=0.31,
    )

    decision = route_with_conservative_rules(evidence)

    assert decision.route == "fallback_vlm"
    assert decision.predicted_action is None


def test_score_cascade_counts_non_vlm_rate_accuracy_and_token_reduction() -> None:
    rows = [
        ScoredDecision(
            sample_id="s1",
            gt="moving",
            baseline_action="moving",
            decision=CascadeDecision("auto_label", "moving", "strong_simple_motion"),
        ),
        ScoredDecision(
            sample_id="s2",
            gt="drinking",
            baseline_action="drinking",
            decision=CascadeDecision("fallback_vlm", None, "ambiguous"),
        ),
        ScoredDecision(
            sample_id="s3",
            gt="drinking",
            baseline_action="drinking",
            decision=CascadeDecision("auto_label", "moving", "strong_simple_motion"),
        ),
    ]

    summary = score_cascade(
        rows,
        baseline_avg_tokens=120_000,
        fallback_avg_tokens=20_000,
    )

    assert summary["n"] == 3
    assert summary["non_vlm_rate"] == 2 / 3
    assert summary["fallback_rate"] == 1 / 3
    assert summary["accuracy"] == 2 / 3
    assert summary["baseline_accuracy"] == 1.0
    assert summary["accuracy_drop_pp"] == pytest.approx(33.33333333333333)
    assert summary["false_auto_label_rate"] == 0.5
    assert summary["token_reduction"] == pytest.approx(0.9444444444444444)


def test_calibration_returns_no_auto_when_all_auto_candidates_are_false() -> None:
    evidences = [
        VideoEvidence(
            sample_id="sample-001",
            clip_id="clip-001",
            duration_sec=60.0,
            width=1920,
            height=1080,
            fps=30.0,
            frame_count=1800,
            brightness_mean=120.0,
            brightness_std=20.0,
            saturation_mean=30.0,
            motion_mean=0.08,
            motion_peak=0.30,
            motion_std=0.04,
            active_motion_ratio=1.0,
            center_motion_ratio=0.5,
            late_motion_ratio=1.0,
        )
    ]

    rule = calibrate_moving_rule(evidences, {"sample-001": "drinking"}, max_false_auto_rate=0.05)
    decision = route_with_conservative_rules(evidences[0])

    assert decision.route == "auto_label"
    assert rule.name == "no-auto"

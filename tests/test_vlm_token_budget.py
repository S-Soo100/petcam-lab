"""VLM 호출 토큰 절감 계산 테스트."""

from __future__ import annotations

import pytest

from backend.vlm.token_budget import (
    TokenBudget,
    TokenReductionPlan,
    estimate_claude_image_tokens,
    max_fallback_rate_for_target,
)


def test_estimate_claude_image_tokens_uses_area_rule() -> None:
    """Claude vision 문서/기존 실험에서 쓰는 w*h/750 근사."""
    assert estimate_claude_image_tokens(1536, 1995) == 4086


def test_token_reduction_plan_passes_when_primary_is_under_20_percent() -> None:
    """M0 몽타주 평균 3.2k/call은 v40 frames 평균 19.7k 대비 80%+ 절감."""
    plan = TokenReductionPlan(
        baseline=TokenBudget(input_tokens=3_650_000, calls=185),
        primary=TokenBudget(input_tokens=770_000, calls=240),
    )

    assert plan.baseline_avg_input_tokens == pytest.approx(19_729.73, rel=1e-4)
    assert plan.primary_avg_input_tokens == pytest.approx(3_208.33, rel=1e-4)
    assert plan.reduction_fraction == pytest.approx(0.83739, rel=1e-4)
    assert plan.meets_target(0.80) is True


def test_token_reduction_plan_accounts_for_direct_video_fallback() -> None:
    """fallback은 cheap primary 위에 원래 호출을 추가하므로 평균 토큰을 다시 올린다."""
    plan = TokenReductionPlan(
        baseline=TokenBudget(input_tokens=120_000, calls=1),
        primary=TokenBudget(input_tokens=3_208, calls=1),
        fallback_rate=0.16,
    )

    assert plan.expected_avg_input_tokens == pytest.approx(22_408)
    assert plan.reduction_fraction == pytest.approx(0.81327, rel=1e-4)
    assert plan.meets_target(0.80) is True


def test_max_fallback_rate_for_target_returns_hard_budget() -> None:
    """120k→3.2k primary라면 fallback은 약 17.3%까지 허용된다."""
    rate = max_fallback_rate_for_target(
        baseline_avg_tokens=120_000,
        primary_avg_tokens=3_208,
        target_reduction=0.80,
    )

    assert rate == pytest.approx(0.17326, rel=1e-4)


def test_max_fallback_rate_is_zero_when_primary_already_misses_target() -> None:
    rate = max_fallback_rate_for_target(
        baseline_avg_tokens=10_000,
        primary_avg_tokens=3_000,
        target_reduction=0.80,
    )

    assert rate == 0.0

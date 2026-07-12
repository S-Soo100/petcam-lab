"""VLM 입력 토큰 절감 계산 유틸.

실제 API 사용량은 provider 응답의 usage_metadata가 최종 진실이다. 이 모듈은 실험 전/후
수치나 운영 로그에서 평균 입력 토큰을 비교해, 목표 절감률과 fallback 허용 폭을 계산한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def estimate_claude_image_tokens(width: int, height: int) -> int:
    """이미지 토큰 근사치.

    Claude vision 계열 입력표현 실험에서 써 온 `width * height / 750` 규칙이다.
    provider마다 실제 과금 토큰은 다를 수 있으므로, 전략 비교용 추정치로만 쓴다.
    """
    if width <= 0 or height <= 0:
        raise ValueError("width/height는 양수여야 해")
    return math.ceil((width * height) / 750)


@dataclass(frozen=True, slots=True)
class TokenBudget:
    """한 전략의 총 입력 토큰과 호출 수."""

    input_tokens: int
    calls: int

    @property
    def avg_input_tokens(self) -> float:
        if self.input_tokens < 0:
            raise ValueError("input_tokens는 음수일 수 없어")
        if self.calls <= 0:
            raise ValueError("calls는 1 이상이어야 해")
        return self.input_tokens / self.calls


@dataclass(frozen=True, slots=True)
class TokenReductionPlan:
    """baseline 대비 primary(+선택 fallback) 평균 입력 토큰 절감 계산."""

    baseline: TokenBudget
    primary: TokenBudget
    fallback_rate: float = 0.0
    fallback: TokenBudget | None = None

    @property
    def baseline_avg_input_tokens(self) -> float:
        return self.baseline.avg_input_tokens

    @property
    def primary_avg_input_tokens(self) -> float:
        return self.primary.avg_input_tokens

    @property
    def fallback_avg_input_tokens(self) -> float:
        return (
            self.fallback.avg_input_tokens
            if self.fallback is not None
            else self.baseline_avg_input_tokens
        )

    @property
    def expected_avg_input_tokens(self) -> float:
        if not 0.0 <= self.fallback_rate <= 1.0:
            raise ValueError("fallback_rate는 0.0~1.0이어야 해")
        return self.primary_avg_input_tokens + (
            self.fallback_rate * self.fallback_avg_input_tokens
        )

    @property
    def reduction_fraction(self) -> float:
        baseline = self.baseline_avg_input_tokens
        if baseline <= 0:
            raise ValueError("baseline 평균 토큰은 0보다 커야 해")
        return 1.0 - (self.expected_avg_input_tokens / baseline)

    def meets_target(self, target_reduction: float) -> bool:
        """목표 절감률(예: 0.80)을 만족하는지 반환."""
        _validate_target(target_reduction)
        return self.reduction_fraction >= target_reduction


def max_fallback_rate_for_target(
    *,
    baseline_avg_tokens: float,
    primary_avg_tokens: float,
    target_reduction: float,
    fallback_avg_tokens: float | None = None,
) -> float:
    """목표 절감률을 유지하면서 허용 가능한 최대 fallback 비율.

    cascade 비용 모델:
      평균 토큰 = primary_avg_tokens + fallback_rate * fallback_avg_tokens

    fallback_avg_tokens를 생략하면 "원래 baseline direct call로 재호출"한다고 본다.
    """
    _validate_target(target_reduction)
    if baseline_avg_tokens <= 0:
        raise ValueError("baseline_avg_tokens는 0보다 커야 해")
    if primary_avg_tokens < 0:
        raise ValueError("primary_avg_tokens는 음수일 수 없어")

    fallback_avg = fallback_avg_tokens or baseline_avg_tokens
    if fallback_avg <= 0:
        raise ValueError("fallback_avg_tokens는 0보다 커야 해")

    target_avg = baseline_avg_tokens * (1.0 - target_reduction)
    remaining = target_avg - primary_avg_tokens
    if remaining <= 0:
        return 0.0
    return max(0.0, min(1.0, remaining / fallback_avg))


def _validate_target(target_reduction: float) -> None:
    if not 0.0 <= target_reduction < 1.0:
        raise ValueError("target_reduction은 0.0 이상 1.0 미만이어야 해")


__all__ = [
    "TokenBudget",
    "TokenReductionPlan",
    "estimate_claude_image_tokens",
    "max_fallback_rate_for_target",
]

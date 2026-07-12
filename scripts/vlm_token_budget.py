"""VLM 입력 토큰 절감률 계산 CLI.

실험 리포트나 운영 로그에서 얻은 "총 입력 토큰 / 호출 수"를 넣어 baseline 대비
primary 전략이 80% 절감 목표를 만족하는지 확인한다.

예:
  uv run python scripts/vlm_token_budget.py \
    --baseline-total-tokens 3650000 --baseline-calls 185 \
    --primary-total-tokens 770000 --primary-calls 240
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.vlm.token_budget import (
    TokenBudget,
    TokenReductionPlan,
    max_fallback_rate_for_target,
)


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description="VLM 토큰 절감률 계산")
    ap.add_argument("--baseline-total-tokens", type=int, required=True)
    ap.add_argument("--baseline-calls", type=int, required=True)
    ap.add_argument("--primary-total-tokens", type=int, required=True)
    ap.add_argument("--primary-calls", type=int, required=True)
    ap.add_argument("--fallback-rate", type=float, default=0.0)
    ap.add_argument("--fallback-total-tokens", type=int)
    ap.add_argument("--fallback-calls", type=int)
    ap.add_argument("--target-reduction", type=float, default=0.80)
    args = ap.parse_args()

    fallback = None
    if args.fallback_total_tokens is not None or args.fallback_calls is not None:
        if args.fallback_total_tokens is None or args.fallback_calls is None:
            ap.error("--fallback-total-tokens와 --fallback-calls는 같이 지정해야 해")
        fallback = TokenBudget(
            input_tokens=args.fallback_total_tokens,
            calls=args.fallback_calls,
        )

    plan = TokenReductionPlan(
        baseline=TokenBudget(
            input_tokens=args.baseline_total_tokens,
            calls=args.baseline_calls,
        ),
        primary=TokenBudget(
            input_tokens=args.primary_total_tokens,
            calls=args.primary_calls,
        ),
        fallback_rate=args.fallback_rate,
        fallback=fallback,
    )
    max_fallback = max_fallback_rate_for_target(
        baseline_avg_tokens=plan.baseline_avg_input_tokens,
        primary_avg_tokens=plan.primary_avg_input_tokens,
        target_reduction=args.target_reduction,
        fallback_avg_tokens=plan.fallback_avg_input_tokens,
    )

    print(f"baseline avg input tokens : {plan.baseline_avg_input_tokens:,.1f}")
    print(f"primary avg input tokens  : {plan.primary_avg_input_tokens:,.1f}")
    print(f"fallback avg input tokens : {plan.fallback_avg_input_tokens:,.1f}")
    print(f"fallback rate             : {_pct(args.fallback_rate)}")
    print(f"expected avg input tokens : {plan.expected_avg_input_tokens:,.1f}")
    print(f"reduction                 : {_pct(plan.reduction_fraction)}")
    print(f"target                    : {_pct(args.target_reduction)}")
    print(f"max fallback for target   : {_pct(max_fallback)}")
    print(f"decision                  : {'PASS' if plan.meets_target(args.target_reduction) else 'FAIL'}")

    return 0 if plan.meets_target(args.target_reduction) else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Operational Router v0 read-only report.

실제 `clip_router_features` 운영 데이터를 읽어 cheap metadata만으로
cloud VLM 우선순위를 시뮬레이션한다. DB/R2/LLM/VLM 쓰기나 호출은 없다.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.supabase_client import get_supabase_client  # noqa: E402

ALLOWED_ROUTES = {
    "cloud_now",
    "cloud_later",
    "activity_only",
    "review_candidate",
}
PAGE_SIZE = 1000
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "router-operational-v0-20260710"
SELECT_COLUMNS = ",".join(
    [
        "clip_id",
        "user_id",
        "pet_id",
        "camera_id",
        "started_at",
        "duration_sec",
        "has_motion",
        "motion_frames",
        "width",
        "height",
        "fps",
        "window_clip_count_10m",
        "window_clip_count_30m",
        "window_clip_count_60m",
        "seconds_since_prev_clip",
        "seconds_until_next_clip",
        "recent_activity_baseline",
        "same_hour_7d_avg_motion",
        "today_activity_percentile",
        "activity_delta_from_baseline",
        "motion_mean",
        "motion_peak",
        "motion_std",
        "active_motion_ratio",
        "center_motion_ratio",
        "late_motion_ratio",
        "motion_burst_count",
        "longest_motion_burst_sec",
        "first_motion_sec",
        "last_motion_sec",
        "motion_coverage_ratio",
        "evidence_reliability",
        "feature_version",
        "processing_status",
        "processing_error",
        "processed_at",
        "created_at",
        "updated_at",
    ]
)


@dataclass(frozen=True, slots=True)
class OperationalRouterDecision:
    clip_id: str
    route: str
    priority: float
    risk: str
    reason: str


def route_operational_feature(row: dict[str, Any]) -> OperationalRouterDecision:
    clip_id = str(row.get("clip_id") or "")
    status = str(row.get("processing_status") or "")
    reliability = row.get("evidence_reliability")
    motion_mean = _float(row.get("motion_mean"))
    motion_peak = _float(row.get("motion_peak"))
    motion_std = _float(row.get("motion_std"))
    active_ratio = _float(row.get("active_motion_ratio"))
    burst_count = _int(row.get("motion_burst_count"))
    longest_burst = _float(row.get("longest_motion_burst_sec"))
    delta = _float(row.get("activity_delta_from_baseline"))
    window_30m = _int(row.get("window_clip_count_30m"))
    duration = _float(row.get("duration_sec"))
    has_motion = row.get("has_motion")

    if status != "ready":
        return OperationalRouterDecision(
            clip_id=clip_id,
            route="review_candidate",
            priority=0.90,
            risk="high",
            reason=f"feature_not_ready:{status or 'missing'}",
        )

    missing_core = motion_mean is None or motion_peak is None or active_ratio is None
    if missing_core or reliability == "low":
        return OperationalRouterDecision(
            clip_id=clip_id,
            route="review_candidate",
            priority=0.78,
            risk="medium",
            reason="feature_not_ready:missing_or_low_reliability",
        )

    strong_activity = (
        motion_mean >= 0.035
        or motion_peak >= 0.140
        or (motion_std is not None and motion_std >= 0.045)
        or active_ratio >= 0.65
        or (delta is not None and delta >= 0.35)
        or burst_count >= 4
        or (longest_burst is not None and duration and longest_burst >= min(12.0, duration * 0.25))
    )
    if strong_activity:
        return OperationalRouterDecision(
            clip_id=clip_id,
            route="cloud_now",
            priority=0.88,
            risk="high",
            reason="strong_activity_or_burst",
        )

    extreme_static = (
        has_motion is False
        or (
            motion_mean < 0.002
            and motion_peak < 0.010
            and active_ratio < 0.02
            and (burst_count is None or burst_count <= 1)
            and (window_30m is None or window_30m <= 2)
            and reliability in {None, "medium", "high"}
        )
    )
    if extreme_static:
        return OperationalRouterDecision(
            clip_id=clip_id,
            route="activity_only",
            priority=0.18,
            risk="low",
            reason="extreme_static_reliable",
        )

    low_activity = (
        motion_mean < 0.012
        and motion_peak < 0.045
        and active_ratio < 0.20
        and (burst_count is None or burst_count <= 2)
    )
    if low_activity:
        return OperationalRouterDecision(
            clip_id=clip_id,
            route="cloud_later",
            priority=0.42,
            risk="medium",
            reason="low_activity_batchable",
        )

    return OperationalRouterDecision(
        clip_id=clip_id,
        route="cloud_later",
        priority=0.58,
        risk="medium",
        reason="moderate_activity_batchable",
    )


def summarize_decisions(decisions: Iterable[OperationalRouterDecision]) -> dict[str, Any]:
    items = list(decisions)
    routes = Counter(decision.route for decision in items)
    risks = Counter(decision.risk for decision in items)
    reasons = Counter(decision.reason for decision in items)
    n = len(items)
    cloud_now = routes["cloud_now"]
    cloud_eventual = routes["cloud_now"] + routes["cloud_later"]
    return {
        "generated_at": _utc_now_iso(),
        "n": n,
        "routes": dict(routes),
        "risks": dict(risks),
        "reasons": dict(reasons),
        "cloud_now_rate": cloud_now / n if n else 0.0,
        "cloud_eventual_rate": cloud_eventual / n if n else 0.0,
        "estimated_immediate_vlm_reduction_rate": (n - cloud_now) / n if n else 0.0,
        "activity_only_rate": routes["activity_only"] / n if n else 0.0,
        "review_candidate_rate": routes["review_candidate"] / n if n else 0.0,
        "db_writes": 0,
        "r2_writes": 0,
        "llm_vlm_calls": 0,
    }


def write_report(
    rows: list[dict[str, Any]],
    decisions: list[OperationalRouterDecision],
    summary: dict[str, Any],
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    decision_by_clip = {decision.clip_id: decision for decision in decisions}
    joined_rows = []
    for row in rows:
        decision = decision_by_clip.get(str(row.get("clip_id") or ""))
        if decision is None:
            continue
        joined_rows.append({**_compact_row(row), **asdict(decision)})

    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "decisions.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in joined_rows),
        encoding="utf-8",
    )
    with (out_dir / "decisions.csv").open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "clip_id",
            "camera_id",
            "started_at",
            "processing_status",
            "motion_mean",
            "motion_peak",
            "active_motion_ratio",
            "motion_burst_count",
            "evidence_reliability",
            "route",
            "priority",
            "risk",
            "reason",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(joined_rows)

    (out_dir / "REPORT.md").write_text(
        _format_markdown(summary, out_dir),
        encoding="utf-8",
    )


def load_feature_rows(limit: int | None = None) -> list[dict[str, Any]]:
    sb = get_supabase_client()
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        if limit is not None and len(rows) >= limit:
            return rows[:limit]
        page_size = PAGE_SIZE if limit is None else min(PAGE_SIZE, limit - len(rows))
        end = start + page_size - 1
        resp = (
            sb.table("clip_router_features")
            .select(SELECT_COLUMNS)
            .order("started_at", desc=False)
            .range(start, end)
            .execute()
        )
        page = resp.data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size


def run(out_dir: Path, *, limit: int | None = None) -> dict[str, Any]:
    rows = load_feature_rows(limit=limit)
    decisions = [route_operational_feature(row) for row in rows]
    summary = summarize_decisions(decisions)
    write_report(rows, decisions, summary, out_dir)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    summary = run(args.out_dir, limit=args.limit)
    print(f"rows: {summary['n']}")
    print(f"routes: {summary['routes']}")
    print(f"cloud_now_rate: {summary['cloud_now_rate']:.3f}")
    print(f"reports: {args.out_dir}")
    print("DB writes: 0 / R2 writes: 0 / LLM/VLM calls: 0")
    return 0


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "clip_id": row.get("clip_id"),
        "camera_id": row.get("camera_id"),
        "started_at": row.get("started_at"),
        "processing_status": row.get("processing_status"),
        "motion_mean": row.get("motion_mean"),
        "motion_peak": row.get("motion_peak"),
        "active_motion_ratio": row.get("active_motion_ratio"),
        "motion_burst_count": row.get("motion_burst_count"),
        "evidence_reliability": row.get("evidence_reliability"),
    }


def _format_markdown(summary: dict[str, Any], out_dir: Path) -> str:
    lines = [
        "# Router Operational v0 Report",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- rows: `{summary['n']}`",
        f"- cloud_now_rate: `{_pct(summary['cloud_now_rate'])}`",
        f"- estimated_immediate_vlm_reduction_rate: `{_pct(summary['estimated_immediate_vlm_reduction_rate'])}`",
        f"- cloud_eventual_rate: `{_pct(summary['cloud_eventual_rate'])}`",
        f"- activity_only_rate: `{_pct(summary['activity_only_rate'])}`",
        f"- review_candidate_rate: `{_pct(summary['review_candidate_rate'])}`",
        "- DB writes: `0`",
        "- R2 writes: `0`",
        "- LLM/VLM calls: `0`",
        "",
        "## Routes",
        "",
    ]
    for route, count in sorted(summary["routes"].items()):
        lines.append(f"- `{route}`: {count}")
    lines.extend(["", "## Reasons", ""])
    for reason, count in sorted(summary["reasons"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- `{reason}`: {count}")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            _decision_note(summary),
            "",
            "## Artifacts",
            "",
            f"- `{out_dir / 'summary.json'}`",
            f"- `{out_dir / 'decisions.csv'}`",
            f"- `{out_dir / 'decisions.jsonl'}`",
            "",
        ]
    )
    return "\n".join(lines)


def _decision_note(summary: dict[str, Any]) -> str:
    cloud_now_rate = float(summary["cloud_now_rate"])
    activity_only_rate = float(summary["activity_only_rate"])
    review_candidate_rate = float(summary["review_candidate_rate"])
    if activity_only_rate > 0.02:
        return "Decision: `reject-unsafe-activity-only-too-high`"
    if review_candidate_rate > 0.50:
        return "Decision: `hold-feature-reliability-low`"
    if cloud_now_rate <= 0.40:
        return "Decision: `candidate-for-recall-guard`"
    if cloud_now_rate < 0.7411167512690355:
        return "Decision: `hold-needs-recall-guard`"
    return "Decision: `hold-too-conservative`"


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build and optionally seed a care_guard_v1 operational review batch."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.supabase_client import get_supabase_client  # noqa: E402
from scripts.router_care_guard_v1_report import route_care_guard_v1  # noqa: E402
from scripts.router_operational_v0_report import (  # noqa: E402
    SELECT_COLUMNS,
    route_operational_feature,
)
from scripts.seed_router_review_batch import seed_review_batch  # noqa: E402

DEFAULT_BATCH_ID = "router-care-guard-v1_1-eval-20260711"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / DEFAULT_BATCH_ID


@dataclass(frozen=True, slots=True)
class CandidateQuotas:
    guard_demote: int = 60
    guard_promote: int = 30
    review_candidate_low_motion: int = 30
    random_control: int = 30

    @property
    def target_total(self) -> int:
        return (
            self.guard_demote
            + self.guard_promote
            + self.review_candidate_low_motion
            + self.random_control
        )


def select_review_candidates(
    rows: Iterable[dict[str, Any]],
    *,
    quotas: CandidateQuotas = CandidateQuotas(),
) -> list[dict[str, Any]]:
    enriched = [_enrich_row(row) for row in rows]
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(group_rows: list[dict[str, Any]], limit: int) -> None:
        for row in _stable_sort(group_rows):
            if len([item for item in selected if item["sample_group"] == row["sample_group"]]) >= limit:
                return
            clip_id = str(row["clip_id"])
            if clip_id in seen:
                continue
            selected.append(row)
            seen.add(clip_id)

    add(
        [
            _with_group(row, "guard_demote_cloud_now")
            for row in enriched
            if row["baseline_route"] == "cloud_now"
            and row["candidate_route"] == "cloud_later"
        ],
        quotas.guard_demote,
    )
    add(
        [
            _with_group(row, "guard_promote_late_care")
            for row in enriched
            if row["baseline_route"] == "cloud_later"
            and row["candidate_route"] == "review_candidate"
        ],
        quotas.guard_promote,
    )
    add(
        [
            _with_group(row, "review_candidate_low_motion")
            for row in enriched
            if row["baseline_route"] == "review_candidate"
            and _float(row.get("motion_peak"), 0.0) < 0.08
            and _float(row.get("motion_mean"), 0.0) < 0.015
        ],
        quotas.review_candidate_low_motion,
    )
    add(
        [
            _with_group(row, "random_control")
            for row in enriched
            if str(row["clip_id"]) not in seen
        ],
        quotas.random_control,
    )

    if len(selected) < quotas.target_total:
        filler = [
            _with_group(row, "quota_fill")
            for row in enriched
            if str(row["clip_id"]) not in seen
        ]
        for row in _stable_sort(filler):
            if len(selected) >= quotas.target_total:
                break
            selected.append(row)
            seen.add(str(row["clip_id"]))
    return selected[: quotas.target_total]


def build_review_payload(candidate: dict[str, Any], batch_id: str) -> dict[str, Any]:
    baseline_route = str(candidate["baseline_route"])
    candidate_reason = str(candidate["candidate_reason"])
    return {
        "batch_id": batch_id,
        "clip_id": candidate["clip_id"],
        "sample_group": candidate["sample_group"],
        "route": candidate["candidate_route"],
        "risk": candidate["risk"],
        "reason": f"care_guard_v1:baseline={baseline_route};rule={candidate_reason}",
        "priority": candidate["priority"],
        "camera_id": candidate.get("camera_id"),
        "started_at": candidate.get("started_at"),
        "evidence_reliability": candidate.get("evidence_reliability"),
        "motion_mean": candidate.get("motion_mean"),
        "motion_peak": candidate.get("motion_peak"),
        "active_motion_ratio": candidate.get("active_motion_ratio"),
        "motion_burst_count": candidate.get("motion_burst_count"),
    }


def write_review_batch(
    candidates: list[dict[str, Any]],
    *,
    batch_id: str,
    out_dir: Path,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "manual_review_queue.csv"
    json_path = out_dir / "manual_review_queue.json"
    payloads = [build_review_payload(candidate, batch_id) for candidate in candidates]
    fieldnames = [
        "sample_group",
        "clip_id",
        "baseline_route",
        "candidate_route",
        "candidate_reason",
        "route",
        "risk",
        "reason",
        "priority",
        "camera_id",
        "started_at",
        "evidence_reliability",
        "motion_mean",
        "motion_peak",
        "active_motion_ratio",
        "motion_burst_count",
        "center_motion_ratio",
        "late_motion_ratio",
        "motion_std",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for candidate, payload in zip(candidates, payloads, strict=True):
            writer.writerow({**candidate, **payload, "candidate_route": candidate["candidate_route"]})
    json_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "REPORT.md").write_text(
        _format_report(candidates, batch_id=batch_id, csv_path=csv_path),
        encoding="utf-8",
    )
    return csv_path


def load_feature_rows() -> list[dict[str, Any]]:
    sb = get_supabase_client()
    rows: list[dict[str, Any]] = []
    start = 0
    page_size = 1000
    while True:
        end = start + page_size - 1
        page = (
            sb.table("clip_router_features")
            .select(SELECT_COLUMNS)
            .order("started_at", desc=False)
            .range(start, end)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size


def run(
    *,
    batch_id: str = DEFAULT_BATCH_ID,
    out_dir: Path = DEFAULT_OUT_DIR,
    dry_run: bool = False,
    seed: bool = False,
) -> dict[str, Any]:
    candidates = select_review_candidates(load_feature_rows())
    csv_path = write_review_batch(candidates, batch_id=batch_id, out_dir=out_dir)
    seeded = 0
    if seed:
        seeded = seed_review_batch(csv_path, batch_id, dry_run=dry_run)
    summary = {
        "batch_id": batch_id,
        "out_dir": str(out_dir),
        "csv_path": str(csv_path),
        "n": len(candidates),
        "groups": dict(Counter(row["sample_group"] for row in candidates)),
        "baseline_routes": dict(Counter(row["baseline_route"] for row in candidates)),
        "candidate_routes": dict(Counter(row["candidate_route"] for row in candidates)),
        "seeded": seeded,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    summary = run(
        batch_id=args.batch_id,
        out_dir=args.out_dir,
        seed=args.seed,
        dry_run=args.dry_run,
    )
    print(f"batch: {summary['batch_id']}")
    print(f"selected: {summary['n']}")
    print(f"groups: {summary['groups']}")
    print(f"candidate_routes: {summary['candidate_routes']}")
    print(f"csv: {summary['csv_path']}")
    if args.seed:
        print(f"seeded: {summary['seeded']}")
    return 0


def _enrich_row(row: dict[str, Any]) -> dict[str, Any]:
    baseline = route_operational_feature(row)
    guard = route_care_guard_v1({**row, "route": baseline.route})
    route = guard.route
    if guard.reason == "off_center_motion_batchable":
        priority = 0.42
        risk = "medium"
    elif guard.reason == "late_low_motion_care_sentinel":
        priority = 0.74
        risk = "medium"
    elif route == "cloud_now":
        priority = 0.88
        risk = "high"
    elif route == "review_candidate":
        priority = 0.78
        risk = "medium"
    elif route == "activity_only":
        priority = 0.18
        risk = "low"
    else:
        priority = 0.58
        risk = "medium"
    return {
        **row,
        "baseline_route": baseline.route,
        "baseline_reason": baseline.reason,
        "candidate_route": route,
        "candidate_reason": guard.reason,
        "priority": priority,
        "risk": risk,
    }


def _with_group(row: dict[str, Any], group: str) -> dict[str, Any]:
    return {**row, "sample_group": group}


def _stable_sort(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (str(row.get("started_at") or ""), str(row["clip_id"])))


def _format_report(candidates: list[dict[str, Any]], *, batch_id: str, csv_path: Path) -> str:
    groups = Counter(row["sample_group"] for row in candidates)
    baseline_routes = Counter(row["baseline_route"] for row in candidates)
    candidate_routes = Counter(row["candidate_route"] for row in candidates)
    lines = [
        "# Router Care Guard v1.1 Review Batch",
        "",
        f"- batch_id: `{batch_id}`",
        f"- rows: `{len(candidates)}`",
        f"- csv: `{csv_path}`",
        "- DB writes: depends on `--seed`; build-only mode writes files only.",
        "- LLM/VLM calls: `0`",
        "",
        "## Groups",
        "",
    ]
    for key, value in sorted(groups.items()):
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Routes", ""])
    lines.append(f"- baseline_routes: `{dict(baseline_routes)}`")
    lines.append(f"- candidate_routes: `{dict(candidate_routes)}`")
    lines.extend(
        [
            "",
            "## Review Goal",
            "",
            "- guard가 내린 `cloud_now -> cloud_later` 후보가 정말 비검사인지 확인한다.",
            "- guard가 올린 `cloud_later -> review_candidate` 후보가 실제 검사 후보인지 확인한다.",
            "- low-motion review_candidate와 random control로 숨은 care miss를 확인한다.",
            "",
        ]
    )
    return "\n".join(lines)


def _float(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    raise SystemExit(main())

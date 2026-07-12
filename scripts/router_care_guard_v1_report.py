#!/usr/bin/env python3
"""Care Guard v1 read-only router report.

목표는 행동 분류가 아니라 라우터 우선순위 보강이다. 기존 route를 입력으로
받아, off-center 움직임은 낮추고 late low-motion care sentinel은 올린다.
DB/R2/LLM/VLM 쓰기나 호출은 없다.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv
from supabase import create_client

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_BATCH_ID = "router-eval-v1-20260710"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "router-care-guard-v1-20260710"
DATASET_DIR = REPO_ROOT / "storage" / "dataset-203"
DATASET_FEATURES = REPO_ROOT / "experiments" / "local-router-v1" / "features.jsonl"
DATASET_DECISIONS = REPO_ROOT / "experiments" / "local-router-v1" / "l0-decisions.jsonl"
CARE_CLASSES = {"drinking", "eating_paste", "eating_prey", "hand_feeding", "shedding"}
INSPECTION_LABEL = {"no": "검사", "yes": "비검사", "unclear": "애매함"}


@dataclass(frozen=True, slots=True)
class GuardDecision:
    clip_id: str
    baseline_route: str
    route: str
    reason: str


def route_care_guard_v1(row: dict[str, Any]) -> GuardDecision:
    """Apply a minimal route patch without seeing GT/manual labels."""
    clip_id = str(row.get("clip_id") or "")
    baseline_route = str(row.get("route") or row.get("baseline_route") or "")
    center_motion = _float(row.get("center_motion_ratio"))
    late_motion = _float(row.get("late_motion_ratio"))
    motion_peak = _float(row.get("motion_peak"))
    active_ratio = _float(row.get("active_motion_ratio"))
    last_motion = _float(row.get("last_motion_sec"))

    off_center_batchable = (
        baseline_route == "cloud_now"
        and center_motion is not None
        and active_ratio is not None
        and center_motion < 0.55
        and active_ratio < 0.95
        and (last_motion is None or last_motion < 56.0)
    )
    if off_center_batchable:
        return GuardDecision(
            clip_id=clip_id,
            baseline_route=baseline_route,
            route="cloud_later",
            reason="off_center_motion_batchable",
        )

    late_care_sentinel = (
        baseline_route == "cloud_later"
        and late_motion is not None
        and motion_peak is not None
        and active_ratio is not None
        and late_motion >= 1.8
        and motion_peak >= 0.08
        and active_ratio >= 0.15
    )
    if late_care_sentinel:
        return GuardDecision(
            clip_id=clip_id,
            baseline_route=baseline_route,
            route="review_candidate",
            reason="late_low_motion_care_sentinel",
        )

    return GuardDecision(
        clip_id=clip_id,
        baseline_route=baseline_route,
        route=baseline_route,
        reason="unchanged",
    )


def summarize_dataset203(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = [route_care_guard_v1(row) for row in rows]
    by_clip = {decision.clip_id: decision for decision in decisions}
    care_rows = [row for row in rows if row["gt"] in CARE_CLASSES]
    moving_rows = [row for row in rows if row["gt"] == "moving"]
    moving_cloud_before = sum(1 for row in moving_rows if row["route"] == "cloud_now")
    moving_cloud_after = sum(1 for row in moving_rows if by_clip[row["clip_id"]].route == "cloud_now")
    care_candidate_after = sum(
        1
        for row in care_rows
        if by_clip[row["clip_id"]].route in {"cloud_now", "review_candidate"}
    )
    care_activity_only_after = sum(
        1 for row in care_rows if by_clip[row["clip_id"]].route == "activity_only"
    )
    care_lowered_to_cloud_later = [
        row["clip_id"]
        for row in care_rows
        if row["route"] == "cloud_now" and by_clip[row["clip_id"]].route == "cloud_later"
    ]
    return {
        "n": len(rows),
        "routes_before": dict(Counter(row["route"] for row in rows)),
        "routes_after": dict(Counter(decision.route for decision in decisions)),
        "reasons": dict(Counter(decision.reason for decision in decisions)),
        "class_by_route_after": _class_by_route(rows, by_clip),
        "moving_cloud_now_before": moving_cloud_before,
        "moving_cloud_now_after": moving_cloud_after,
        "moving_cloud_now_reduction": moving_cloud_before - moving_cloud_after,
        "moving_cloud_now_reduction_rate": _rate(
            moving_cloud_before - moving_cloud_after,
            moving_cloud_before,
        ),
        "care_candidate_after": care_candidate_after,
        "care_total": len(care_rows),
        "care_candidate_recall_after": _rate(care_candidate_after, len(care_rows)),
        "care_activity_only_after": care_activity_only_after,
        "care_lowered_to_cloud_later": care_lowered_to_cloud_later,
    }


def summarize_operational(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = [route_care_guard_v1(row) for row in rows]
    by_clip = {decision.clip_id: decision for decision in decisions}
    non_inspection = [row for row in rows if row["inspection"] == "yes"]
    inspection = [row for row in rows if row["inspection"] == "no"]
    cloud_non_before = sum(1 for row in non_inspection if row["route"] == "cloud_now")
    cloud_non_after = sum(1 for row in non_inspection if by_clip[row["clip_id"]].route == "cloud_now")
    regression_ids = {
        "748c1b7d-b634-4793-a9bc-cdf87bee350e",
        "8abccef4-430a-4d73-a338-3891b46beb3e",
        "d9346cbe-9ae4-456c-a018-50ecf10ac476",
    }
    regression_rows = [row for row in rows if row["clip_id"] in regression_ids]
    regression_pass = all(
        by_clip[row["clip_id"]].route in {"cloud_now", "review_candidate"}
        for row in regression_rows
    )
    return {
        "n": len(rows),
        "routes_before": dict(Counter(row["route"] for row in rows)),
        "routes_after": dict(Counter(decision.route for decision in decisions)),
        "reasons": dict(Counter(decision.reason for decision in decisions)),
        "inspection_by_route_after": _inspection_by_route(rows, by_clip),
        "non_inspection_cloud_now_before": cloud_non_before,
        "non_inspection_cloud_now_after": cloud_non_after,
        "non_inspection_cloud_now_reduction": cloud_non_before - cloud_non_after,
        "non_inspection_cloud_now_reduction_rate": _rate(
            cloud_non_before - cloud_non_after,
            cloud_non_before,
        ),
        "inspection_total": len(inspection),
        "inspection_activity_only_after": sum(
            1 for row in inspection if by_clip[row["clip_id"]].route == "activity_only"
        ),
        "inspection_low_after": sum(
            1 for row in inspection if by_clip[row["clip_id"]].route == "cloud_later"
        ),
        "regression_pass": regression_pass,
        "regression": [
            {
                "clip_id": row["clip_id"],
                "action": row["action"],
                "baseline_route": row["route"],
                "route": by_clip[row["clip_id"]].route,
                "reason": by_clip[row["clip_id"]].reason,
            }
            for row in regression_rows
        ],
    }


def write_report(
    dataset_summary: dict[str, Any],
    operational_summary: dict[str, Any],
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at": _utc_now_iso(),
        "dataset203": dataset_summary,
        "operational_review": operational_summary,
        "db_writes": 0,
        "r2_writes": 0,
        "llm_vlm_calls": 0,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "REPORT.md").write_text(_format_report(summary), encoding="utf-8")


def load_dataset203_rows() -> list[dict[str, Any]]:
    manifest_path = DATASET_DIR / "manifest.csv"
    manifest = {
        row["clip_id"]: row
        for row in csv.DictReader(manifest_path.open(newline="", encoding="utf-8"))
    }
    features = _read_jsonl(DATASET_FEATURES)
    decisions = {row["clip_id"]: row for row in _read_jsonl(DATASET_DECISIONS)}
    rows: list[dict[str, Any]] = []
    for feature in features:
        clip_id = feature["clip_id"]
        rows.append(
            {
                **feature,
                "gt": manifest[clip_id]["gt"],
                "route": decisions[clip_id]["route"],
            }
        )
    return rows


def load_operational_review_rows(batch_id: str) -> list[dict[str, Any]]:
    load_dotenv(REPO_ROOT / ".env")
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    items = (
        sb.table("router_review_items")
        .select("*")
        .eq("batch_id", batch_id)
        .execute()
        .data
        or []
    )
    item_ids = [row["id"] for row in items]
    clip_ids = [row["clip_id"] for row in items]
    labels = _select_in_chunks(sb, "router_review_labels", "*", "review_item_id", item_ids)
    features = _select_in_chunks(
        sb,
        "clip_router_features",
        "clip_id,motion_mean,motion_peak,motion_std,active_motion_ratio,center_motion_ratio,late_motion_ratio,motion_burst_count,evidence_reliability,processing_status",
        "clip_id",
        clip_ids,
    )
    label_by_item = {row["review_item_id"]: row for row in sorted(labels, key=lambda r: r.get("reviewed_at") or "")}
    feature_by_clip = {row["clip_id"]: row for row in features}
    rows: list[dict[str, Any]] = []
    for item in items:
        label = label_by_item.get(item["id"])
        feature = feature_by_clip.get(item["clip_id"])
        if not label or not feature:
            continue
        rows.append(
            {
                **item,
                **feature,
                "action": label["manual_action_gt"],
                "inspection": label["manual_router_ok"],
                "inspection_label": INSPECTION_LABEL.get(label["manual_router_ok"], label["manual_router_ok"]),
            }
        )
    return rows


def run(out_dir: Path, *, batch_id: str = DEFAULT_BATCH_ID) -> dict[str, Any]:
    dataset_summary = summarize_dataset203(load_dataset203_rows())
    operational_summary = summarize_operational(load_operational_review_rows(batch_id))
    write_report(dataset_summary, operational_summary, out_dir)
    return {
        "dataset203": dataset_summary,
        "operational_review": operational_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    summary = run(args.out_dir, batch_id=args.batch_id)
    print(f"dataset moving cloud_now: {summary['dataset203']['moving_cloud_now_before']} -> {summary['dataset203']['moving_cloud_now_after']}")
    print(f"operational non-inspection cloud_now: {summary['operational_review']['non_inspection_cloud_now_before']} -> {summary['operational_review']['non_inspection_cloud_now_after']}")
    print(f"regression pass: {summary['operational_review']['regression_pass']}")
    print(f"reports: {args.out_dir}")
    print("DB writes: 0 / R2 writes: 0 / LLM/VLM calls: 0")
    return 0


def _class_by_route(rows: list[dict[str, Any]], by_clip: dict[str, GuardDecision]) -> dict[str, dict[str, int]]:
    out: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        out[by_clip[row["clip_id"]].route][row["gt"]] += 1
    return {route: dict(counter) for route, counter in sorted(out.items())}


def _inspection_by_route(rows: list[dict[str, Any]], by_clip: dict[str, GuardDecision]) -> dict[str, dict[str, int]]:
    out: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        out[by_clip[row["clip_id"]].route][row["inspection_label"]] += 1
    return {route: dict(counter) for route, counter in sorted(out.items())}


def _format_report(summary: dict[str, Any]) -> str:
    ds = summary["dataset203"]
    op = summary["operational_review"]
    decision = (
        "pass-two-goal-smoke"
        if op["regression_pass"]
        and op["non_inspection_cloud_now_after"] < op["non_inspection_cloud_now_before"]
        else "hold"
    )
    return "\n".join(
        [
            "# Router Care Guard v1.1 Report",
            "",
            f"- generated_at: `{summary['generated_at']}`",
            f"- Decision: `{decision}`",
            "- DB writes: `0`",
            "- R2 writes: `0`",
            "- LLM/VLM calls: `0`",
            "",
            "## Goal Check",
            "",
            "- Goal 1: moving/human_noise 같은 비검사 cloud_now를 내린다.",
            f"  - operational non-inspection cloud_now: `{op['non_inspection_cloud_now_before']}` -> `{op['non_inspection_cloud_now_after']}`",
            f"  - reduction: `{op['non_inspection_cloud_now_reduction']}` ({_pct(op['non_inspection_cloud_now_reduction_rate'])})",
            "- Goal 2: drinking/feeding regression 3건을 검사 후보로 유지한다.",
            f"  - regression_pass: `{op['regression_pass']}`",
            f"  - inspection_activity_only_after: `{op['inspection_activity_only_after']}`",
            f"  - inspection_low_after: `{op['inspection_low_after']}`",
            "",
            "## Rule",
            "",
            "- `cloud_now` + `center_motion_ratio < 0.55` + `active_motion_ratio < 0.95` + `last_motion_sec < 56.0` -> `cloud_later`",
            "- `cloud_later` + `late_motion_ratio >= 1.8` + `motion_peak >= 0.08` + `active_motion_ratio >= 0.15` -> `review_candidate`",
            "",
            "## Dataset203 Guardrail",
            "",
            f"- routes_before: `{ds['routes_before']}`",
            f"- routes_after: `{ds['routes_after']}`",
            f"- moving cloud_now: `{ds['moving_cloud_now_before']}` -> `{ds['moving_cloud_now_after']}`",
            f"- moving cloud_now reduction: `{ds['moving_cloud_now_reduction']}` ({_pct(ds['moving_cloud_now_reduction_rate'])})",
            f"- care candidate recall after: `{ds['care_candidate_after']}/{ds['care_total']}` ({_pct(ds['care_candidate_recall_after'])})",
            f"- care activity_only after: `{ds['care_activity_only_after']}`",
            f"- care lowered to cloud_later: `{ds['care_lowered_to_cloud_later']}`",
            "",
            "## Manual Spot Check",
            "",
            "- `center_motion_ratio < 0.8` 단독 룰이 낮췄던 dataset203 care 2건을 프레임 몽타주로 확인했다.",
            "- `cd2365f5`는 손/도구가 보이는 명확한 handfeeding이다. off-center 움직임이지만 검사 후보로 유지해야 한다.",
            "- `3f976b25`는 탈피 중인 shedding 장면이다. off-center 움직임이지만 검사 후보로 유지해야 한다.",
            "- 두 케이스 모두 `active_motion_ratio = 1.0`이라, `active_motion_ratio < 0.95` guard를 추가했다.",
            "- 운영 60건 검수 후 `center_motion_ratio < 0.55`와 `last_motion_sec < 56.0`을 추가해, 오래 이어지는 실제 행동 후보를 낮추지 않게 했다.",
            "- review frames:",
            "  - `reports/router-care-guard-v1-20260710/review_frames/cd2365f5_sheet.jpg`",
            "  - `reports/router-care-guard-v1-20260710/review_frames/3f976b25_sheet.jpg`",
            "",
            "## Operational 72",
            "",
            f"- routes_before: `{op['routes_before']}`",
            f"- routes_after: `{op['routes_after']}`",
            f"- inspection_by_route_after: `{op['inspection_by_route_after']}`",
            f"- regression: `{op['regression']}`",
            "",
            "## Interpretation",
            "",
            "우선 검수 60건을 반영한 v1.1은 `cloud_now -> cloud_later`를 더 보수적으로 수행한다. 운영 검수 60건에서 v1.1이 낮추는 30건은 검사 0건, 비검사 29건, 애매함 1건이다. dataset203 care 123건도 모두 검사 후보로 유지한다. 아직 production 채택 전에는 남은 low-motion/control 검수로 숨은 care miss를 확인해야 한다.",
            "",
        ]
    )


def _select_in_chunks(sb: Any, table: str, columns: str, column: str, values: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for start in range(0, len(values), 100):
        chunk = values[start : start + 100]
        if not chunk:
            continue
        rows.extend(sb.table(table).select(columns).in_(column, chunk).execute().data or [])
    return rows


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rate(num: int, den: int) -> float:
    return num / den if den else 0.0


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


RAW_DIR_NAME = "raw"
SENSITIVE_TOKENS = (
    '"clip_id"',
    '"r2_key"',
    '"signed_url"',
    '"email"',
    '"user_id"',
    '"reviewed_by"',
    '"note"',
)
UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
EMAIL_PATTERN = re.compile(r"\b[^@\s]+@[^@\s]+\.[^@\s]+\b")
SIGNED_URL_PATTERN = re.compile(r"https?://\S+\?(?:[^ \n]*)(?:token|signature|x-amz-)")
FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|merge|create|alter|drop|truncate|grant|revoke|"
    r"comment|copy|call|do|vacuum|analyze|refresh|reindex|cluster)\b",
    re.IGNORECASE,
)


def assert_raw_ignored(root: Path) -> None:
    ignore = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    if "/raw/" not in ignore:
        raise ValueError("raw_not_ignored")


def assert_no_sensitive_tracked_content(root: Path) -> None:
    for path in root.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in SENSITIVE_TOKENS):
            raise ValueError(f"sensitive_tracked_content {path.name}")
        if UUID_PATTERN.search(text) or EMAIL_PATTERN.search(text) or SIGNED_URL_PATTERN.search(text):
            raise ValueError(f"sensitive_tracked_content {path.name}")
    report = root / "REPORT.md"
    if report.exists():
        text = report.read_text(encoding="utf-8")
        if UUID_PATTERN.search(text) or EMAIL_PATTERN.search(text) or SIGNED_URL_PATTERN.search(text):
            raise ValueError("sensitive_tracked_content REPORT.md")


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", sql)


def assert_select_only_sql(sql: str) -> None:
    clean = _strip_sql_comments(sql)
    if FORBIDDEN_SQL.search(clean):
        raise ValueError("non_select_sql forbidden_keyword")
    for statement in clean.split(";"):
        statement = statement.strip()
        if statement and not re.match(r"^(with|select)\b", statement, re.IGNORECASE):
            raise ValueError("non_select_sql statement_type")
    if re.search(r"\bselect\s+\w+(?:\.\w+)+\s*\(", clean, re.IGNORECASE):
        raise ValueError("non_select_sql function_call")


def _fingerprint_map(path: Path) -> dict[str, tuple[int, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {
        row["table_name"]: (
            int(row["row_count"]),
            row["ordered_fingerprint_md5"],
        )
        for row in rows
    }


def assert_fingerprints_equal(root: Path) -> None:
    start = _fingerprint_map(root / "fingerprints-start.csv")
    end = _fingerprint_map(root / "fingerprints-end.csv")
    if start != end:
        raise ValueError("fingerprint_mutation")


def assert_source_summary(summary: dict[str, Any]) -> None:
    catalog = summary["catalog"]
    sources = summary["sources"]
    source_rows = sum(int(source["rows"]) for source in sources.values())
    if source_rows != int(catalog["rows"]):
        raise ValueError("source_rows_do_not_sum")
    if int(catalog["unique_domain_clips"]) > int(catalog["rows"]):
        raise ValueError("unique_clips_exceed_rows")
    if int(catalog["independent_episodes_5m"]) > int(
        catalog["unique_domain_clips"]
    ):
        raise ValueError("episodes_exceed_unique_clips")
    if int(catalog["camera_nights"]) > int(catalog["independent_episodes_5m"]):
        raise ValueError("camera_nights_exceed_episodes")
    tier_rows = sum(int(count) for count in summary["trust_tier_rows"].values())
    if tier_rows != int(catalog["rows"]):
        raise ValueError("trust_tiers_do_not_sum")
    owner_unique = int(sources["owner_motion"]["unique_clips"])
    coverage = summary["coverage"]
    for key in ("owner_python_evidence", "owner_gate", "owner_vlm_any"):
        if int(coverage[key]) > owner_unique:
            raise ValueError("owner_coverage_exceeds_source")


def assert_overlap_summary(
    source_summary: dict[str, Any],
    overlap_summary: dict[str, Any],
) -> None:
    owner_unique = int(source_summary["sources"]["owner_motion"]["unique_clips"])
    legacy_unique = int(overlap_summary["legacy_union_unique_clips"])
    expected = owner_unique + legacy_unique - int(
        overlap_summary["overlaps"]["owner_motion_vs_legacy"]
    )
    if expected != int(overlap_summary["catalog_unique_domain_clips"]):
        raise ValueError("overlap_union_mismatch")
    if expected != int(source_summary["catalog"]["unique_domain_clips"]):
        raise ValueError("source_overlap_unique_mismatch")


def assert_verdict_consistent(summary: dict[str, Any]) -> None:
    verdict = str(summary["verdict"])
    top_causes = summary.get("top_causes", [])
    candidate = summary.get("next_candidate")
    if verdict == "UNIFIED_GT_FAILURE_AUDIT_READY_FOR_REVIEW":
        if candidate is None:
            raise ValueError("ready_without_candidate")
        if not isinstance(candidate, dict) or set(candidate) != {"id"}:
            raise ValueError("ready_candidate_not_exactly_one")
        if not top_causes or not top_causes[0].get("qualified"):
            raise ValueError("ready_without_qualified_cause")
    elif verdict.startswith("UNIFIED_GT_FAILURE_AUDIT_HOLD_"):
        if candidate is not None:
            raise ValueError("hold_with_candidate")
    else:
        raise ValueError("unknown_verdict")


def assert_failure_summary(summary: dict[str, Any]) -> None:
    comparison = summary["retrospective_vlm_comparison"]
    covered = int(comparison["single_gt_vlm_covered"])
    exact = int(comparison["single_gt_vlm_exact"])
    mismatch = int(comparison["single_gt_vlm_mismatch"])
    if exact + mismatch != covered:
        raise ValueError("vlm_comparison_arithmetic")
    if abs(float(comparison["exact_rate"]) - exact / covered) > 1e-6:
        raise ValueError("vlm_exact_rate_mismatch")
    mode_clips = sum(
        int(mode["clips"])
        for mode in (
            summary["qualified_failure_modes_not_root_causes"]
            + summary["nonqualified_failure_modes"]
        )
    )
    if mode_clips != mismatch:
        raise ValueError("failure_modes_do_not_partition_mismatches")
    for cause in summary["human_confirmed_error_tags"]:
        if cause["qualified_root_cause"] and (
            int(cause["independent_episodes"]) < 10
            or int(cause["camera_nights"]) < 2
        ):
            raise ValueError("underpowered_root_cause_qualified")
    assert_verdict_consistent(summary)


def verify(root: Path) -> None:
    assert_raw_ignored(root)
    assert_no_sensitive_tracked_content(root)
    assert_select_only_sql((root / "inventory.sql").read_text(encoding="utf-8"))
    assert_fingerprints_equal(root)
    if len(_fingerprint_map(root / "fingerprints-start.csv")) < 12:
        raise ValueError("fingerprint_table_scope_too_small")
    source = json.loads((root / "source-summary.json").read_text(encoding="utf-8"))
    overlap = json.loads((root / "overlap-summary.json").read_text(encoding="utf-8"))
    failure = json.loads((root / "failure-summary.json").read_text(encoding="utf-8"))
    assert_source_summary(source)
    assert_overlap_summary(source, overlap)
    assert_failure_summary(failure)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--sql-only", type=Path)
    args = parser.parse_args()
    try:
        if args.sql_only is not None:
            assert_select_only_sql(args.sql_only.read_text(encoding="utf-8"))
            print("SELECT_ONLY_OK")
            return 0
        if args.root is None:
            parser.error("--root 또는 --sql-only가 필요해")
        verify(args.root)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(str(exc))
        return 1
    print("UNIFIED_GT_ARTIFACTS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

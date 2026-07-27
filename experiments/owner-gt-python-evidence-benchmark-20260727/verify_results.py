from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


FROZEN = {
    "eligible_count": 172,
    "eligible_ordered_sha256": (
        "8e2bf4e73f8f033288d7632e25e2fbfd"
        "69d3de98c62dade2996bbe33686c96ba"
    ),
    "moving_count": 108,
    "static_only_count": 32,
    "excluded_count": 32,
    "episode_count": 39,
    "provenance_contract_count": 1,
}
SOURCE_TABLES = {
    "motion_clips",
    "motion_clip_labeling_triage",
    "motion_clip_labeling_sessions",
    "motion_clip_labeling_session_revisions",
    "clip_python_evidence_runs",
    "clip_prelabels",
}
BOOTSTRAP_SEED = 20_260_727
BOOTSTRAP_ITERATIONS = 10_000
FORBIDDEN_JSON_KEYS = {
    "clip_id",
    "user_id",
    "reviewed_by",
    "r2_key",
    "signed_url",
    "url",
    "email",
    "note",
    "decision_note",
    "vlm_review_note",
}
WRITE_SQL = re.compile(
    r"\b(insert|update|delete|merge|alter|drop|truncate|create|grant|revoke|call)\b",
    re.IGNORECASE,
)
SENSITIVE_PATTERNS = {
    "uuid": re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
        re.IGNORECASE,
    ),
    "url": re.compile(r"https?://\S+", re.IGNORECASE),
    "email": re.compile(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        re.IGNORECASE,
    ),
    "r2_key": re.compile(
        r"\b(?:"
        + "clips"
        + r"|"
        + "terra"
        + r"-clips|"
        + "motion"
        + r"-clips)/\S+",
        re.IGNORECASE,
    ),
}


def _auc(records: list[dict], feature: str) -> float:
    positive = [
        float(row[feature])
        for row in records
        if row["label"] == "moving" and row.get(feature) is not None
    ]
    negative = [
        float(row[feature])
        for row in records
        if row["label"] == "static_only" and row.get(feature) is not None
    ]
    if not positive or not negative:
        raise ValueError("independent AUROC requires both classes")
    total = 0.0
    for positive_value in positive:
        for negative_value in negative:
            if positive_value > negative_value:
                total += 1.0
            elif positive_value == negative_value:
                total += 0.5
    return total / (len(positive) * len(negative))


def _percentile(values: list[float], proportion: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * proportion
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _bootstrap(
    records: list[dict],
    iterations: int,
    seed: int,
) -> dict[str, float | int]:
    episodes: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        if row["label"] in {"moving", "static_only"}:
            episodes[row["episode_key"]].append(row)
    keys = sorted(episodes)
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(iterations):
        selected = rng.choices(keys, k=len(keys))
        replicate = [row for key in selected for row in episodes[key]]
        available = {
            row["label"]
            for row in replicate
            if row.get("roi_mean") is not None
        }
        if {"moving", "static_only"} <= available:
            estimates.append(_auc(replicate, "roi_mean"))
    if not estimates:
        raise ValueError("independent bootstrap produced no valid iteration")
    return {
        "valid_iterations": len(estimates),
        "valid_fraction": len(estimates) / iterations,
        "ci_low": _percentile(estimates, 0.025),
        "ci_high": _percentile(estimates, 0.975),
    }


def _camera_auc(records: list[dict]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for camera in sorted({row["camera_group"] for row in records}):
        rows = [row for row in records if row["camera_group"] == camera]
        labels = {
            row["label"]
            for row in rows
            if row.get("roi_mean") is not None
        }
        result[camera] = (
            _auc(rows, "roi_mean")
            if {"moving", "static_only"} <= labels
            else None
        )
    return result


def _verdict(primary: dict) -> str:
    if primary["coverage"] < 0.80 or primary["ci_high"] <= 0.50:
        return "PE_MOTION_SIGNAL_REJECTED"
    camera_values = list(primary["camera_auc"].values())
    if (
        primary["coverage"] >= 0.95
        and primary["ci_low"] > 0.50
        and primary["valid_fraction"] >= 0.95
        and len(camera_values) == 2
        and all(value is not None and value > 0.50 for value in camera_values)
    ):
        return "PE_MOTION_SIGNAL_DESCRIPTIVE_SUPPORTED"
    return "PE_MOTION_SIGNAL_INCONCLUSIVE"


def _assert_same(path: str, actual: Any, expected: Any) -> None:
    if isinstance(actual, float) or isinstance(expected, float):
        if actual is None or expected is None or not math.isclose(
            float(actual),
            float(expected),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(f"SUMMARY_MISMATCH {path}: {actual!r} != {expected!r}")
    elif actual != expected:
        raise ValueError(f"SUMMARY_MISMATCH {path}: {actual!r} != {expected!r}")


def verify_summary(
    snapshot: dict,
    summary: dict,
    iterations: int,
    seed: int,
) -> None:
    records = snapshot["records"]
    labels = Counter(row["label"] for row in records)
    discrimination = [
        row for row in records if row["label"] in {"moving", "static_only"}
    ]
    primary_rows = [row for row in discrimination if row.get("roi_mean") is not None]
    bootstrap = _bootstrap(records, iterations=iterations, seed=seed)
    primary = {
        "auc": _auc(discrimination, "roi_mean"),
        "coverage": len(primary_rows) / len(discrimination),
        "ci_low": bootstrap["ci_low"],
        "ci_high": bootstrap["ci_high"],
        "valid_iterations": bootstrap["valid_iterations"],
        "valid_fraction": bootstrap["valid_fraction"],
        "camera_auc": _camera_auc(discrimination),
    }
    expected_values = {
        "technical.eligible_count": len(records),
        "technical.level0_ok": sum(row["level0_status"] == "ok" for row in records),
        "technical.level1_ok": sum(row["level1_status"] == "ok" for row in records),
        "technical.episodes": len({row["episode_key"] for row in records}),
        "technical.cameras": len({row["camera_group"] for row in records}),
        "technical.camera_nights": len({row["camera_night"] for row in records}),
        "labels.moving": labels["moving"],
        "labels.static_only": labels["static_only"],
        "labels.excluded": labels["excluded"],
        "primary.auc": primary["auc"],
        "primary.coverage": primary["coverage"],
        "primary.ci_low": primary["ci_low"],
        "primary.ci_high": primary["ci_high"],
        "primary.valid_iterations": primary["valid_iterations"],
        "primary.valid_fraction": primary["valid_fraction"],
        "primary.camera_auc": primary["camera_auc"],
        "secondary.observed_sec.non_null": sum(
            row.get("observed_sec") is not None for row in records
        ),
        "secondary.peak_autocorr.non_null": sum(
            row.get("peak_autocorr") is not None for row in records
        ),
        "secondary.decoded_frame_count.non_null": sum(
            row.get("decoded_frame_count") is not None for row in records
        ),
        "verdict": _verdict(primary),
    }
    for path, expected in expected_values.items():
        actual: Any = summary
        for component in path.split("."):
            actual = actual[component]
        _assert_same(path, actual, expected)
    _assert_same("contract", summary["contract"], snapshot["contract"])


def validate_frozen_analysis(summary: dict) -> None:
    analysis = summary.get("analysis", {})
    primary = summary.get("primary", {})
    expected = {
        "analysis.bootstrap_seed": (
            analysis.get("bootstrap_seed"),
            BOOTSTRAP_SEED,
        ),
        "analysis.bootstrap_iterations": (
            analysis.get("bootstrap_iterations"),
            BOOTSTRAP_ITERATIONS,
        ),
        "primary.bootstrap_seed": (
            primary.get("bootstrap_seed"),
            BOOTSTRAP_SEED,
        ),
        "primary.bootstrap_iterations": (
            primary.get("bootstrap_iterations"),
            BOOTSTRAP_ITERATIONS,
        ),
    }
    drift = [
        f"{path}={actual!r}"
        for path, (actual, frozen) in expected.items()
        if actual != frozen
    ]
    if drift:
        raise ValueError("ANALYSIS_CONTRACT_DRIFT " + ",".join(drift))


def _strip_sql_comments(sql: str) -> str:
    without_blocks = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", "", without_blocks)


def validate_select_only(sql_path: Path) -> None:
    sql = _strip_sql_comments(sql_path.read_text(encoding="utf-8"))
    for index, statement in enumerate(sql.split(";"), start=1):
        statement = statement.strip()
        if not statement:
            continue
        if not re.match(r"^(select|with)\b", statement, flags=re.IGNORECASE):
            raise ValueError(
                f"SQL_NOT_SELECT_ONLY statement {index} does not start with SELECT/WITH"
            )
        match = WRITE_SQL.search(statement)
        if match:
            raise ValueError(
                f"SQL_NOT_SELECT_ONLY statement {index} contains "
                f"{match.group(1).upper()}"
            )


def _load_fingerprint(path: Path) -> dict[str, tuple[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            row["table_name"]: (
                row["row_count"],
                row["ordered_fingerprint_md5"],
            )
            for row in csv.DictReader(handle)
        }


def validate_fingerprints(start_path: Path, end_path: Path) -> None:
    start = _load_fingerprint(start_path)
    end = _load_fingerprint(end_path)
    if start != end:
        changed = sorted(
            table
            for table in set(start) | set(end)
            if start.get(table) != end.get(table)
        )
        raise ValueError("SOURCE_MUTATION " + ",".join(changed))
    if set(start) != SOURCE_TABLES:
        missing = sorted(SOURCE_TABLES - set(start))
        unexpected = sorted(set(start) - SOURCE_TABLES)
        raise ValueError(
            "FINGERPRINT_SCOPE "
            f"missing={','.join(missing)} unexpected={','.join(unexpected)}"
        )


def _forbidden_json_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.casefold() in FORBIDDEN_JSON_KEYS:
                found.add(key)
            found.update(_forbidden_json_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            found.update(_forbidden_json_keys(nested))
    return found


def find_sensitive(root: Path) -> list[str]:
    errors: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {
            ".md",
            ".sql",
            ".py",
            ".json",
            ".csv",
        }:
            continue
        text = path.read_text(encoding="utf-8")
        for label, pattern in SENSITIVE_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{path.name}:{label}")
        if path.suffix.lower() == ".json":
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if _forbidden_json_keys(parsed):
                errors.append(f"{path.name}:forbidden_json_key")
    return errors


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        validate_select_only(args.root / "benchmark.sql")
        snapshot = json.loads(
            (args.root / "snapshot-aggregate.json").read_text(encoding="utf-8")
        )
        contract = snapshot.get("contract", {})
        for key, value in FROZEN.items():
            if contract.get(key) != value:
                raise ValueError(
                    f"COHORT_DRIFT {key}: {contract.get(key)!r} != {value!r}"
                )
        summary = json.loads(
            (args.root / "summary.json").read_text(encoding="utf-8")
        )
        validate_frozen_analysis(summary)
        verify_summary(
            snapshot,
            summary,
            iterations=BOOTSTRAP_ITERATIONS,
            seed=BOOTSTRAP_SEED,
        )
        validate_fingerprints(
            args.root / "fingerprints-start.csv",
            args.root / "fingerprints-end.csv",
        )
        sensitive = find_sensitive(args.root)
        if sensitive:
            raise ValueError("SENSITIVE_RAW_DATA " + ",".join(sensitive))
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print("PE_BENCHMARK_ARTIFACTS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

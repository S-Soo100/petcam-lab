from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent))

from analyze import summarize  # noqa: E402
from test_analyze import SMALL_EXPECTED, fixture_snapshot  # noqa: E402
from verify_results import (  # noqa: E402
    find_sensitive,
    validate_frozen_analysis,
    validate_fingerprints,
    validate_select_only,
    verify_summary,
)


def test_verify_summary_accepts_independent_recalculation() -> None:
    snapshot = fixture_snapshot()
    summary = summarize(
        snapshot,
        expected=SMALL_EXPECTED,
        iterations=200,
        seed=7,
    )

    verify_summary(snapshot, summary, iterations=200, seed=7)


def test_verify_summary_rejects_tampered_auc() -> None:
    snapshot = fixture_snapshot()
    summary = summarize(
        snapshot,
        expected=SMALL_EXPECTED,
        iterations=200,
        seed=7,
    )
    summary["primary"]["auc"] = 0.01

    with pytest.raises(ValueError, match="SUMMARY_MISMATCH"):
        verify_summary(snapshot, summary, iterations=200, seed=7)


def _write_fingerprint(path: Path, row_count: str, fingerprint: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "snapshot_at_utc",
                "table_name",
                "row_count",
                "ordered_fingerprint_md5",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "snapshot_at_utc": "2026-07-27T00:00:00Z",
                "table_name": "motion_clips",
                "row_count": row_count,
                "ordered_fingerprint_md5": fingerprint,
            }
        )


def test_validate_fingerprints_rejects_source_mutation(tmp_path: Path) -> None:
    start = tmp_path / "fingerprints-start.csv"
    end = tmp_path / "fingerprints-end.csv"
    _write_fingerprint(start, "172", "a" * 32)
    _write_fingerprint(end, "173", "b" * 32)

    with pytest.raises(ValueError, match="SOURCE_MUTATION"):
        validate_fingerprints(start, end)


def test_validate_fingerprints_requires_exact_source_scope(tmp_path: Path) -> None:
    start = tmp_path / "fingerprints-start.csv"
    end = tmp_path / "fingerprints-end.csv"
    _write_fingerprint(start, "172", "a" * 32)
    _write_fingerprint(end, "172", "a" * 32)

    with pytest.raises(ValueError, match="FINGERPRINT_SCOPE"):
        validate_fingerprints(start, end)


def test_validate_frozen_analysis_rejects_seed_or_iteration_drift() -> None:
    summary = {
        "analysis": {
            "bootstrap_seed": 7,
            "bootstrap_iterations": 17,
        },
        "primary": {
            "bootstrap_seed": 7,
            "bootstrap_iterations": 17,
        },
    }

    with pytest.raises(ValueError, match="ANALYSIS_CONTRACT_DRIFT"):
        validate_frozen_analysis(summary)


def test_find_sensitive_detects_constructed_raw_values(tmp_path: Path) -> None:
    uuid_value = "-".join(
        ["123e4567", "e89b", "12d3", "a456", "426614174000"],
    )
    url_value = "https" + "://" + "example.invalid/video"
    email_value = "owner" + "@" + "example.invalid"
    (tmp_path / "raw.json").write_text(
        json.dumps(
            {
                "clip": uuid_value,
                "signed": url_value,
                "contact": email_value,
            }
        ),
        encoding="utf-8",
    )

    errors = find_sensitive(tmp_path)

    assert {"uuid", "url", "email"} <= {error.split(":")[-1] for error in errors}


def test_find_sensitive_detects_real_r2_prefix_and_forbidden_json_keys(
    tmp_path: Path,
) -> None:
    (tmp_path / "raw.json").write_text(
        json.dumps(
            {
                "r2_key": "clips" + "/uploaded/2026-01-01/private.mp4",
                "note": "owner private observation",
            }
        ),
        encoding="utf-8",
    )

    errors = find_sensitive(tmp_path)

    labels = {error.split(":")[-1] for error in errors}
    assert "r2_key" in labels
    assert "forbidden_json_key" in labels


def test_validate_select_only_rejects_write_statement(tmp_path: Path) -> None:
    sql_path = tmp_path / "benchmark.sql"
    sql_path.write_text(
        "SELECT count(*) FROM public.motion_clips;\n"
        "UPDATE public.motion_clips SET duration_sec = 0;\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="SQL_NOT_SELECT_ONLY"):
        validate_select_only(sql_path)

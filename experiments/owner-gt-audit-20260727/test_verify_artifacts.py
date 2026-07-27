from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).with_name("verify_artifacts.py")


def run_validator(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_validator_accepts_select_only_anonymized_artifacts(tmp_path: Path) -> None:
    (tmp_path / "audit.sql").write_text(
        "WITH eligible AS (SELECT 1 AS n) SELECT n FROM eligible;\n",
        encoding="utf-8",
    )
    (tmp_path / "REPORT.md").write_text(
        "표본 172건, fingerprint 8e2bf4e73f8f033288d7632e25e2fbfd.\n",
        encoding="utf-8",
    )

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "ARTIFACT_CONTRACT_OK" in result.stdout


def test_validator_rejects_sql_write_statement(tmp_path: Path) -> None:
    (tmp_path / "audit.sql").write_text(
        "SELECT count(*) FROM public.motion_clips;\n"
        "UPDATE public.motion_clips SET duration_sec = 0;\n",
        encoding="utf-8",
    )

    result = run_validator(tmp_path)

    assert result.returncode == 1
    assert "SQL_NOT_SELECT_ONLY" in result.stderr


def test_validator_rejects_sensitive_raw_identifiers(tmp_path: Path) -> None:
    (tmp_path / "audit.sql").write_text("SELECT 1;\n", encoding="utf-8")
    uuid_value = "-".join(
        ["123e4567", "e89b", "12d3", "a456", "426614174000"],
    )
    url_value = "https" + "://" + "example.invalid/file.mp4?token=secret"
    email_value = "owner" + "@" + "example.com"
    (tmp_path / "REPORT.md").write_text(
        f"clip {uuid_value}\n"
        f"signed {url_value}\n"
        f"contact {email_value}\n",
        encoding="utf-8",
    )

    result = run_validator(tmp_path)

    assert result.returncode == 1
    assert "SENSITIVE_RAW_DATA" in result.stderr


def test_validator_rejects_fingerprint_mutation(tmp_path: Path) -> None:
    (tmp_path / "audit.sql").write_text("SELECT 1;\n", encoding="utf-8")
    header = "snapshot_at_utc,table_name,row_count,ordered_fingerprint_md5\n"
    (tmp_path / "fingerprints-start.csv").write_text(
        header + "2026-07-27T00:00:00Z,sessions,172,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
        encoding="utf-8",
    )
    (tmp_path / "fingerprints-end.csv").write_text(
        header + "2026-07-27T01:00:00Z,sessions,173,bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n",
        encoding="utf-8",
    )

    result = run_validator(tmp_path)

    assert result.returncode == 1
    assert "FINGERPRINT_MUTATION" in result.stderr


def test_validator_rejects_cohort_fingerprint_mutation(tmp_path: Path) -> None:
    (tmp_path / "audit.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (tmp_path / "cohort-fingerprints.csv").write_text(
        "phase,snapshot_at_utc,eligible_count,eligible_ordered_sha256\n"
        "start,2026-07-27T00:00:00Z,172,aaaaaaaa\n"
        "end,2026-07-27T01:00:00Z,171,bbbbbbbb\n",
        encoding="utf-8",
    )

    result = run_validator(tmp_path)

    assert result.returncode == 1
    assert "FINGERPRINT_MUTATION" in result.stderr

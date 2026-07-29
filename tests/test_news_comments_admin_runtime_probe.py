"""news comments/admin migration을 disposable PostgreSQL에서 실증한다."""

from pathlib import Path
import os
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_news_comments_admin_probe.py"


def test_news_comments_admin_probe_runner_exists() -> None:
    assert RUNNER.is_file()


def test_news_comments_admin_runtime_probe() -> None:
    pg_bin = Path("/opt/homebrew/opt/postgresql@15/bin")
    if not (pg_bin / "psql").is_file():
        pytest.skip("local PostgreSQL 15 client is unavailable")
    completed = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(RUNNER),
            "--pg-bin",
            str(pg_bin),
        ],
        cwd=ROOT,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=150,
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode == 0, output
    assert "NEWS_COMMENTS_RUNTIME_OK" in output
    assert "NEWS_ADMIN_RLS_OK" in output
    assert "NEWS_COMMENT_RATE_LIMIT_OK" in output
    assert "NEWS_STORAGE_POLICY_OK" in output
    assert "PROBE_RESIDUE=0" in output

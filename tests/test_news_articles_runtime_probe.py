"""news_articles migration을 disposable PostgreSQL에서 실증한다."""

from pathlib import Path
import os
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_news_articles_probe.py"


def test_news_articles_probe_runner_exists() -> None:
    assert RUNNER.is_file()


def test_news_articles_runtime_probe() -> None:
    pg_bin = Path("/opt/homebrew/opt/postgresql@15/bin")
    if not (pg_bin / "psql").is_file():
        pytest.skip("local PostgreSQL 15 client is unavailable")
    env = os.environ.copy()
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
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode == 0, output
    assert "NEWS_ARTICLES_RUNTIME_OK" in output
    assert "NEWS_ARTICLES_RLS_OK" in output
    assert "PROBE_RESIDUE=0" in output

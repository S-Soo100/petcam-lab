from pathlib import Path
import subprocess

import pytest


RUNNER = Path("scripts/run_rba_boundary_review_dashboard_probe.py")


def test_probe_runner_exists() -> None:
    assert RUNNER.is_file()


def test_boundary_runtime_probe() -> None:
    pg_bin = Path("/opt/homebrew/opt/postgresql@15/bin")
    if not (pg_bin / "psql").is_file():
        pytest.skip("local PostgreSQL 15 client is unavailable")
    completed = subprocess.run(
        ["uv", "run", "python", str(RUNNER), "--pg-bin", str(pg_bin)],
        text=True, capture_output=True, timeout=120, check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode == 0, output
    assert "RBA_BOUNDARY_RUNTIME_OK" in output
    assert "RBA_BOUNDARY_APPEND_ONLY_OK" in output
    assert "RBA_BOUNDARY_PRIVILEGE_OK" in output
    assert "PROBE_RESIDUE=0" in output

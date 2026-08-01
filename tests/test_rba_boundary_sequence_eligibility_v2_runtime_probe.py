from pathlib import Path
import os
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_rba_boundary_sequence_eligibility_v2_probe.py"


def test_sequence_eligibility_runtime_probe() -> None:
    pg_bin = Path("/opt/homebrew/opt/postgresql@15/bin")
    if not (pg_bin / "psql").is_file():
        pytest.skip("local PostgreSQL 15 client is unavailable")
    assert RUNNER.is_file(), f"runtime probe missing: {RUNNER}"
    completed = subprocess.run(
        ["uv", "run", "python", str(RUNNER), "--pg-bin", str(pg_bin)],
        cwd=ROOT,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=150,
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode == 0, output
    assert "RBA_SEQUENCE_ELIGIBILITY_RUNTIME_OK" in output
    assert "RBA_SEQUENCE_ELIGIBILITY_PRIVILEGE_OK" in output
    assert "PROBE_RESIDUE=0" in output

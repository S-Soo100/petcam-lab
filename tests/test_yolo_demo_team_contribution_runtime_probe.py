from pathlib import Path
import subprocess

import pytest


RUNNER = Path("scripts/run_yolo_demo_team_contribution_probe.py")


def test_probe_runner_exists() -> None:
    assert RUNNER.is_file()


def test_yolo_runtime_probe() -> None:
    pg_bin = Path("/opt/homebrew/opt/postgresql@15/bin")
    if not (pg_bin / "psql").is_file():
        pytest.skip("local PostgreSQL 15 client is unavailable")
    completed = subprocess.run(
        ["uv", "run", "python", str(RUNNER), "--pg-bin", str(pg_bin)],
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode == 0, output
    assert "YOLO_PROBE_OK" in output
    assert "YOLO_BLIND_OK" in output
    assert "YOLO_DATASET_GATE_OK" in output
    assert "YOLO_MODEL_ACTIVATION_OK" in output
    assert "YOLO_APPEND_ONLY_OK" in output
    assert "PROBE_RESIDUE=0" in output
    assert "ROLE_RESIDUE=0" in output

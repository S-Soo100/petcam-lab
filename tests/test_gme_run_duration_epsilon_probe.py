from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
PG_BIN_CANDIDATES = (
    Path("/opt/homebrew/opt/postgresql@17/bin"),
    Path("/opt/homebrew/opt/postgresql@15/bin"),
    Path("/usr/local/opt/postgresql@17/bin"),
    Path("/usr/local/opt/postgresql@15/bin"),
)


def _postgres_bin() -> Path | None:
    for candidate in PG_BIN_CANDIDATES:
        if all((candidate / name).is_file() for name in ("psql", "initdb", "pg_ctl", "createdb")):
            return candidate
    psql = shutil.which("psql")
    if psql:
        candidate = Path(psql).resolve().parent
        if all((candidate / name).is_file() for name in ("psql", "initdb", "pg_ctl", "createdb")):
            return candidate
    return None


def test_duration_epsilon_migration_accepts_float_noise_but_rejects_real_inversion():
    pg_bin = _postgres_bin()
    if pg_bin is None:
        pytest.skip("local PostgreSQL binaries are unavailable")
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(ROOT / "scripts" / "run_gme_run_duration_epsilon_probe.py"),
            "--pg-bin",
            str(pg_bin),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "GME_RUN_DURATION_EPSILON_RUNTIME_OK"

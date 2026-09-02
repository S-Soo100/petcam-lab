"""Owner R2 cleanup migration을 일회용 로컬 PostgreSQL에서 검증한다."""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.run_motion_double_blind_concurrency_probe import (  # noqa: E402
    _BLIND_ROLES,
    LocalPostgresBackend,
    ProbeBlocked,
    ProbeFailed,
    _drop_created_roles,
    _existing_blind_roles,
    _find_pg_tool,
    _run,
    roles_to_cleanup,
)


def main() -> int:
    pg_bin = "/opt/homebrew/opt/postgresql@15/bin"
    psql = _find_pg_tool("psql", pg_bin)
    createdb = _find_pg_tool("createdb", pg_bin)
    dropdb = _find_pg_tool("dropdb", pg_bin)
    name = f"blind_probe_owner_cleanup_{secrets.token_hex(8)}"
    if not name.startswith("blind_probe_owner_cleanup_"):
        raise ProbeBlocked("unsafe_temp_database_name")
    created = False
    roles_to_drop: list[str] = []
    try:
        proc = _run([createdb, "-h", "127.0.0.1", name], timeout=30)
        if proc.returncode:
            raise ProbeBlocked(f"createdb_failed:{proc.stderr.strip()[:200]}")
        created = True
        backend = LocalPostgresBackend(psql, f"postgresql://127.0.0.1/{name}")
        pre_existing = _existing_blind_roles(backend)
        roles_to_drop = roles_to_cleanup(_BLIND_ROLES, pre_existing)
        for path in (
            _ROOT / "tests/sql/rba_owner_media_cleanup_v1_prerequisites.sql",
            _ROOT / "migrations/2026-08-03_rba_owner_media_cleanup_v1.sql",
            _ROOT / "migrations/2026-08-03_rba_owner_media_cleanup_v1_complete_hotfix.sql",
            _ROOT / "migrations/2026-08-03_rba_owner_media_cleanup_v1_ui_contract.sql",
        ):
            result = backend.psql_run(path.read_text())
            if result.returncode:
                raise ProbeFailed(f"apply_failed:{path.name}:{result.stderr.strip()[:800]}")
        probe = backend.psql_run(
            (_ROOT / "tests/sql/rba_owner_media_cleanup_v1_probe.sql").read_text()
        )
        if probe.returncode:
            raise ProbeFailed(f"probe_failed:{probe.stderr.strip()[:800]}")
        combined = probe.stdout + probe.stderr
        if "RBA_OWNER_MEDIA_CLEANUP_PROBE_OK" not in combined or "PROBE_RESIDUE=0" not in combined:
            raise ProbeFailed(f"marker_missing:{combined[-800:]}")
        print("RBA_OWNER_MEDIA_CLEANUP_PROBE_OK")
        print("PROBE_RESIDUE=0")
        return 0
    except (ProbeBlocked, ProbeFailed) as exc:
        print(f"RBA_OWNER_MEDIA_CLEANUP_PROBE_FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        if created:
            if not name.startswith("blind_probe_owner_cleanup_"):
                raise RuntimeError("unsafe_drop_target")
            _run([dropdb, "-h", "127.0.0.1", "--if-exists", name], timeout=30)
            _drop_created_roles(psql, "127.0.0.1", 5432, roles_to_drop)


if __name__ == "__main__":
    raise SystemExit(main())

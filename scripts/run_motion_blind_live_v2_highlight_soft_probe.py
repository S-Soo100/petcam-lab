"""Live comparator v2 local-only PostgreSQL probe runner."""

from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.run_motion_double_blind_concurrency_probe import (  # noqa: E402
    _BLIND_ROLES,
    LOCAL_HOSTS,
    LocalPostgresBackend,
    ProbeBlocked,
    ProbeFailed,
    _drop_created_roles,
    _existing_blind_roles,
    _find_pg_tool,
    _run,
    roles_to_cleanup,
    validate_database_url,
)

BLOCKED_VERDICT = "MOTION_BLIND_LIVE_V2_HIGHLIGHT_SOFT_BLOCKED_DB_RUNTIME"
REQUIRED_MARKER = "MOTION_BLIND_LIVE_V2_HIGHLIGHT_SOFT_PROBE_OK"
_APPLY_ORDER = (
    ("base_prerequisites", "tests/sql/motion_double_blind_prerequisites.sql"),
    ("motion_v3", "migrations/2026-07-22_motion_clip_labeling_v3.sql"),
    ("double_blind", "migrations/2026-07-23_motion_double_blind_labeling.sql"),
    (
        "single_adopt_prerequisites",
        "tests/sql/motion_blind_single_adopt_prerequisites.sql",
    ),
    (
        "minimum_duration",
        "migrations/2026-07-28_motion_blind_minimum_duration_normalization.sql",
    ),
    ("formal30_prerequisites", "tests/sql/motion_blind_formal30_prerequisites.sql"),
    ("formal30_v1", "migrations/2026-07-31_motion_blind_formal30.sql"),
    ("formal30_v2", "migrations/2026-07-31_motion_blind_formal30_v2.sql"),
    (
        "live_v2",
        "migrations/2026-07-31_motion_blind_live_v2_highlight_soft.sql",
    ),
)
_PROBE_SQL = "tests/sql/motion_blind_live_v2_highlight_soft_probe.sql"
_RESIDUE_TABLES = (
    "public.motion_clips",
    "public.cameras",
    "public.motion_labeling_review_groups",
    "public.motion_blind_review_cohorts",
    "public.motion_clip_review_slots",
    "public.motion_clip_blind_submissions",
    "public.motion_clip_consensus",
    "public.motion_clip_consensus_events",
    "auth.users",
)


def live_v2_temp_database_name(token: str) -> str:
    return f"blind_probe_live_v2_{token}"


def validate_live_v2_temp_database_name(name: str) -> None:
    if not re.fullmatch(r"blind_probe_live_v2_[a-f0-9]+", name):
        raise ProbeBlocked(f"unsafe_temp_database_name: {name!r}")


def apply_order() -> list[tuple[str, Path]]:
    return [(label, _REPO_ROOT / rel) for label, rel in _APPLY_ORDER]


def _residue_count(backend: LocalPostgresBackend) -> int:
    expression = " + ".join(
        f"(SELECT count(*) FROM {table})" for table in _RESIDUE_TABLES
    )
    proc = backend.psql_run(f"SELECT {expression};")
    if proc.returncode != 0:
        raise ProbeFailed(f"residue_query_failed: {proc.stderr.strip()[:300]}")
    return int((proc.stdout or "0").strip() or "0")


def _run_steps(
    backend: LocalPostgresBackend,
    paths: list[tuple[str, Path]],
    probe: Path,
) -> int:
    for label, path in paths:
        proc = backend.psql_run(path.read_text(encoding="utf-8"))
        if proc.returncode != 0:
            raise ProbeFailed(f"{label}_apply_failed: {proc.stderr.strip()[:800]}")

    result = backend.psql_run(probe.read_text(encoding="utf-8"), timeout=120.0)
    if result.returncode != 0:
        detail = (result.stderr.strip() or result.stdout.strip())[:1200]
        raise ProbeFailed(f"probe_failed: {detail}")
    if REQUIRED_MARKER not in result.stdout:
        raise ProbeFailed(f"marker_absent:{REQUIRED_MARKER}")

    residue = _residue_count(backend)
    print(REQUIRED_MARKER)
    print(f"PROBE_RESIDUE={residue}")
    return 0 if residue == 0 else 1


def run_local_live_v2_probe(
    paths: list[tuple[str, Path]],
    probe: Path,
    *,
    pg_bin: str | None = None,
    host: str = "127.0.0.1",
    port: int = 5432,
) -> int:
    if host not in LOCAL_HOSTS:
        raise ProbeBlocked(f"non_local_database_forbidden: host={host!r}")
    psql = _find_pg_tool("psql", pg_bin)
    createdb = _find_pg_tool("createdb", pg_bin)
    dropdb = _find_pg_tool("dropdb", pg_bin)

    name = live_v2_temp_database_name(secrets.token_hex(8))
    validate_live_v2_temp_database_name(name)
    dsn = f"postgresql://{host}:{port}/{name}"
    validate_database_url(dsn)

    created = False
    created_roles: list[str] = []
    result: int | None = None
    cleanup_errors: list[str] = []
    try:
        create = _run([createdb, "-h", host, "-p", str(port), name], timeout=30)
        if create.returncode != 0:
            raise ProbeBlocked(f"createdb_failed: {create.stderr.strip()[:300]}")
        created = True
        backend = LocalPostgresBackend(psql, dsn)
        pre_existing = _existing_blind_roles(backend)
        created_roles = roles_to_cleanup(_BLIND_ROLES, pre_existing)
        result = _run_steps(backend, paths, probe)
    finally:
        if created:
            validate_live_v2_temp_database_name(name)
            dropped = _run(
                [dropdb, "-h", host, "-p", str(port), "--if-exists", name],
                timeout=30,
            )
            if dropped.returncode != 0:
                cleanup_errors.append(
                    f"dropdb_failed: {dropped.stderr.strip()[:200]}"
                )
            role_drop = _drop_created_roles(psql, host, port, created_roles)
            if role_drop is not None and role_drop.returncode != 0:
                cleanup_errors.append(
                    f"role_cleanup_failed: {role_drop.stderr.strip()[:200]}"
                )
    if cleanup_errors:
        raise ProbeFailed("cleanup_failed: " + "; ".join(cleanup_errors))
    return result if result is not None else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live comparator v2 local DB probe")
    parser.add_argument("--backend", choices=("local-postgres",), default="local-postgres")
    parser.add_argument("--pg-bin", default=None)
    parser.add_argument("--pg-host", default="127.0.0.1")
    parser.add_argument("--pg-port", default=5432, type=int)
    args = parser.parse_args(argv)

    paths = apply_order()
    probe = _REPO_ROOT / _PROBE_SQL
    for _label, path in paths:
        if not path.is_file():
            print(f"{BLOCKED_VERDICT}: missing_file:{path}", file=sys.stderr)
            return 2
    if not probe.is_file():
        print(f"{BLOCKED_VERDICT}: missing_file:{probe}", file=sys.stderr)
        return 2

    try:
        return run_local_live_v2_probe(
            paths,
            probe,
            pg_bin=args.pg_bin,
            host=args.pg_host,
            port=args.pg_port,
        )
    except ProbeBlocked as exc:
        print(f"{BLOCKED_VERDICT}: {exc}", file=sys.stderr)
        return 2
    except ProbeFailed as exc:
        print(f"MOTION_BLIND_LIVE_V2_HIGHLIGHT_SOFT_PROBE_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

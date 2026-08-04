"""Canonical GT consumer migration을 disposable PostgreSQL에서 실행해."""

from __future__ import annotations

import argparse
import re
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLY_ORDER = (
    ROOT / "tests/sql/motion_double_blind_prerequisites.sql",
    ROOT / "migrations/2026-07-22_motion_clip_labeling_v3.sql",
    ROOT / "migrations/2026-07-23_motion_double_blind_labeling.sql",
    ROOT / "migrations/2026-07-24_role_based_labeling_reads.sql",
    ROOT / "tests/sql/motion_blind_single_adopt_prerequisites.sql",
    ROOT / "migrations/2026-07-30_motion_blind_single_adopt_provenance.sql",
    ROOT / "migrations/2026-08-04_motion_clip_canonical_gt_ledger.sql",
    ROOT / "migrations/2026-08-04_motion_clip_canonical_gt_consumers.sql",
)
PROBE = ROOT / "tests/sql/motion_clip_canonical_gt_consumers_probe.sql"
DB_NAME = re.compile(r"^canonical_gt_consumers_probe_[0-9a-f]{12}$")
ROLES = ("anon", "authenticated", "service_role")
FLAGS = ("-X", "-v", "ON_ERROR_STOP=1", "-qAt")


class ProbeError(RuntimeError):
    pass


def run(argv: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )


def require_ok(result: subprocess.CompletedProcess[str], label: str) -> str:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:1600]
        raise ProbeError(f"{label}:{detail}")
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-bin", type=Path, required=True)
    args = parser.parse_args()
    psql, createdb, dropdb = (
        args.pg_bin / name for name in ("psql", "createdb", "dropdb")
    )
    for binary in (psql, createdb, dropdb):
        if not binary.is_file():
            raise ProbeError(f"missing:{binary.name}")

    database = f"canonical_gt_consumers_probe_{secrets.token_hex(6)}"
    if not DB_NAME.fullmatch(database):
        raise ProbeError("unsafe_database_name")

    def sql(db: str, statement: str) -> subprocess.CompletedProcess[str]:
        return run(
            [str(psql), "-h", "127.0.0.1", "-p", "5432", "-d", db, *FLAGS],
            input_text=statement,
        )

    existing_text = require_ok(
        sql(
            "postgres",
            "select rolname from pg_roles where rolname in "
            "('anon','authenticated','service_role') order by 1;",
        ),
        "roles",
    )
    existing = set(existing_text.splitlines()) if existing_text else set()
    created_roles = [role for role in ROLES if role not in existing]

    try:
        if created_roles:
            require_ok(
                sql(
                    "postgres",
                    "\n".join(f"create role {role} nologin;" for role in created_roles),
                ),
                "role_setup",
            )
        require_ok(
            run([str(createdb), "-h", "127.0.0.1", "-p", "5432", database]),
            "createdb",
        )
        require_ok(
            sql(
                database,
                "create schema if not exists extensions; "
                "create extension if not exists pgcrypto with schema extensions;",
            ),
            "extensions",
        )
        for path in APPLY_ORDER:
            require_ok(sql(database, path.read_text(encoding="utf-8")), path.name)
        output = require_ok(sql(database, PROBE.read_text(encoding="utf-8")), "probe")
        if "CANONICAL_GT_CONSUMERS_PROBE_OK" not in output:
            raise ProbeError("probe_marker_missing")
        print("CANONICAL_GT_CONSUMERS_PROBE_OK")
        return 0
    finally:
        if DB_NAME.fullmatch(database):
            run([
                str(dropdb), "-h", "127.0.0.1", "-p", "5432",
                "--if-exists", "--force", database,
            ])
        if created_roles:
            sql(
                "postgres",
                "\n".join(f"drop role if exists {role};" for role in created_roles),
            )


if __name__ == "__main__":
    raise SystemExit(main())

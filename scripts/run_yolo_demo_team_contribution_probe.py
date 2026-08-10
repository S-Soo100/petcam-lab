"""YOLO bbox/model migration을 disposable PostgreSQL DB에서 검증해."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import secrets
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "2026-08-10_yolo_demo_team_contribution.sql"
PROBE = ROOT / "tests" / "sql" / "yolo_demo_team_contribution_probe.sql"
DB_NAME = re.compile(r"^yolo_contribution_probe_[0-9a-f]{12}$")
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
        timeout=90,
        check=False,
    )


def require_ok(result: subprocess.CompletedProcess[str], label: str) -> str:
    if result.returncode != 0:
        raise ProbeError(f"{label}: {(result.stderr or result.stdout).strip()[:1000]}")
    return result.stdout.strip()


def require_denied(result: subprocess.CompletedProcess[str], label: str) -> None:
    if result.returncode == 0:
        raise ProbeError(f"{label}: unexpectedly allowed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-bin", type=Path, required=True)
    args = parser.parse_args()
    psql, createdb, dropdb = (args.pg_bin / name for name in ("psql", "createdb", "dropdb"))
    for binary in (psql, createdb, dropdb):
        if not binary.is_file():
            raise ProbeError(f"missing:{binary.name}")
    database = f"yolo_contribution_probe_{secrets.token_hex(6)}"
    if not DB_NAME.fullmatch(database):
        raise ProbeError("unsafe database name")

    def sql(db: str, statement: str) -> subprocess.CompletedProcess[str]:
        return run(
            [str(psql), "-h", "127.0.0.1", "-p", "5432", "-d", db, *FLAGS],
            input_text=statement,
        )

    existing_text = require_ok(
        sql(
            "postgres",
            "select rolname from pg_roles where rolname in ('anon','authenticated','service_role') order by 1;",
        ),
        "roles",
    )
    existing = set(existing_text.splitlines()) if existing_text else set()
    created_roles = [role for role in ROLES if role not in existing]
    try:
        if created_roles:
            statements = []
            for role in created_roles:
                bypass = " bypassrls" if role == "service_role" else ""
                statements.append(f"create role {role} nologin{bypass};")
            require_ok(
                sql("postgres", "\n".join(statements)),
                "role setup",
            )
        require_ok(
            run([str(createdb), "-h", "127.0.0.1", "-p", "5432", database]),
            "createdb",
        )
        require_ok(sql(database, "create extension if not exists pgcrypto;"), "extension")
        require_ok(sql(database, MIGRATION.read_text(encoding="utf-8")), "migration")
        for role in ("anon", "authenticated"):
            require_denied(
                sql(database, f"set role {role}; select count(*) from public.yolo_model_versions;"),
                f"{role} table boundary",
            )
            require_denied(
                sql(
                    database,
                    f"set role {role}; select public.fn_get_yolo_bbox_workspace('00000000-0000-4000-8000-000000000002');",
                ),
                f"{role} rpc boundary",
            )
        require_ok(
            sql(database, "set role service_role; select count(*) from public.yolo_model_versions;"),
            "service role table boundary",
        )
        require_ok(
            sql(database, "set role service_role; select public.fn_validate_yolo_boxes('[]'::jsonb, true);"),
            "service role helper boundary",
        )
        print("YOLO_ROLE_BOUNDARY_OK")
        output = require_ok(sql(database, PROBE.read_text(encoding="utf-8")), "probe")
        for marker in (
            "YOLO_PROBE_OK",
            "YOLO_BLIND_OK",
            "YOLO_DATASET_GATE_OK",
            "YOLO_MODEL_ACTIVATION_OK",
            "YOLO_APPEND_ONLY_OK",
            "YOLO_ROLE_BOUNDARY_OK",
        ):
            if marker == "YOLO_ROLE_BOUNDARY_OK":
                continue
            if marker not in output:
                raise ProbeError(f"marker missing:{marker}")
            print(marker)
    finally:
        if DB_NAME.fullmatch(database):
            run([str(dropdb), "-h", "127.0.0.1", "-p", "5432", "--if-exists", database])
        if created_roles:
            require_ok(
                sql(
                    "postgres",
                    "\n".join(f"drop role if exists {role};" for role in reversed(created_roles)),
                ),
                "role cleanup",
            )
        residue = require_ok(
            sql("postgres", f"select count(*) from pg_database where datname='{database}';"),
            "residue",
        )
        if created_roles:
            quoted = ",".join(f"'{role}'" for role in created_roles)
            role_query = f"select count(*) from pg_roles where rolname in ({quoted});"
        else:
            role_query = "select 0;"
        role_residue = require_ok(sql("postgres", role_query), "role residue")
        print(f"PROBE_RESIDUE={residue}")
        print(f"ROLE_RESIDUE={role_residue}")
        if residue != "0" or role_residue != "0":
            raise ProbeError("cleanup failed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError, ProbeError) as exc:
        print(f"YOLO_PROBE_FAILED type={type(exc).__name__} detail={exc}", file=sys.stderr)
        raise SystemExit(2) from exc

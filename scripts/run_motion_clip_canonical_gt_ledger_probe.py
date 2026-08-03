"""Canonical GT ledger migration을 disposable PostgreSQL DB에서 실증해."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import secrets
import subprocess


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "2026-08-04_motion_clip_canonical_gt_ledger.sql"
PROBE = ROOT / "tests" / "sql" / "motion_clip_canonical_gt_ledger_probe.sql"
DB_NAME = re.compile(r"^canonical_gt_probe_[0-9a-f]{12}$")
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
        detail = (result.stderr or result.stdout).strip()[:1200]
        raise ProbeError(f"{label}:{detail}")
    return result.stdout.strip()


def run_override_concurrency(
    psql: Path,
    database: str,
    expected_revision_id: str,
) -> None:
    statement = f"""
    select public.fn_override_motion_clip_canonical_gt(
      '10000000-0000-4000-8000-000000000001',
      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      '{expected_revision_id}',
      '{{"primary_action":"moving"}}'::jsonb,
      '동일 revision에 대한 열 개 연결의 동시 정정 검증'
    );
    """
    argv = [
        str(psql), "-h", "127.0.0.1", "-p", "5432", "-d", database, *FLAGS
    ]
    processes = [
        subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(10)
    ]
    results: list[tuple[int, str, str]] = []
    for process in processes:
        stdout, stderr = process.communicate(statement, timeout=30)
        results.append((process.returncode, stdout, stderr))
    succeeded = [result for result in results if result[0] == 0]
    stale = [
        result
        for result in results
        if result[0] != 0 and "expected_revision_mismatch" in result[2]
    ]
    if len(succeeded) != 1 or len(stale) != 9:
        raise ProbeError(
            f"override_concurrency_mismatch:success={len(succeeded)} stale={len(stale)}"
        )


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

    database = f"canonical_gt_probe_{secrets.token_hex(6)}"
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
        schema = """
        create schema if not exists extensions;
        create extension if not exists pgcrypto with schema extensions;
        create schema auth;
        create table auth.users(id uuid primary key);
        create table public.motion_clips(id uuid primary key);
        create table public.motion_clip_consensus(
          id uuid primary key, clip_id uuid not null references public.motion_clips(id),
          cohort_kind text not null, status text not null, comparator_version text,
          final_decision text, final_gt jsonb, updated_at timestamptz not null default now()
        );
        create table public.motion_clip_labeling_sessions(
          id uuid primary key, clip_id uuid not null references public.motion_clips(id),
          reviewed_by uuid not null references auth.users(id), stage text not null,
          initial_gt jsonb, current_gt jsonb, completed_at timestamptz,
          updated_at timestamptz not null default now()
        );
        """
        require_ok(sql(database, schema), "schema")
        require_ok(
            sql(database, MIGRATION.read_text(encoding="utf-8")),
            "migration",
        )
        output = require_ok(
            sql(database, PROBE.read_text(encoding="utf-8")),
            "probe",
        )
        if "CANONICAL_GT_LEDGER_PROBE_OK" not in output:
            raise ProbeError("probe_marker_missing")
        expected_revision_id = require_ok(
            sql(
                database,
                "select revision_id from public.motion_clip_gt_heads "
                "where clip_id='10000000-0000-4000-8000-000000000001';",
            ),
            "concurrency_head",
        )
        run_override_concurrency(psql, database, expected_revision_id)
        revision_count = require_ok(
            sql(
                database,
                "select count(*) from public.motion_clip_gt_revisions "
                "where clip_id='10000000-0000-4000-8000-000000000001';",
            ),
            "concurrency_revision_count",
        )
        if revision_count != "3":
            raise ProbeError(f"concurrency_revision_count:{revision_count}")
        print("CANONICAL_GT_LEDGER_PROBE_OK")
        return 0
    finally:
        if DB_NAME.fullmatch(database):
            run(
                [
                    str(dropdb), "-h", "127.0.0.1", "-p", "5432",
                    "--if-exists", "--force", database,
                ]
            )
        if created_roles:
            sql(
                "postgres",
                "\n".join(f"drop role if exists {role};" for role in created_roles),
            )


if __name__ == "__main__":
    raise SystemExit(main())

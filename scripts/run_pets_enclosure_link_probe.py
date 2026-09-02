"""pets.enclosure_id migration을 로컬 일회용 PostgreSQL DB에서 실증해."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import secrets
import subprocess


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "2026-08-06_pets_enclosure_link.sql"
DB_NAME = re.compile(r"^pets_enclosure_probe_[0-9a-f]{12}$")
ROLES = ("anon", "authenticated", "service_role")
PSQL_FLAGS = ("-X", "-v", "ON_ERROR_STOP=1", "-qAt")

USER_A = "10000000-0000-0000-0000-000000000001"
USER_B = "10000000-0000-0000-0000-000000000002"
ENC_A = "20000000-0000-0000-0000-000000000001"
ENC_B = "20000000-0000-0000-0000-000000000002"
PET_A1 = "30000000-0000-0000-0000-000000000001"
PET_A2 = "30000000-0000-0000-0000-000000000002"
PET_B = "30000000-0000-0000-0000-000000000003"


class ProbeError(RuntimeError):
    """migration 계약이 실제 PostgreSQL 동작과 다를 때 발생해."""


def run(
    argv: list[str],
    *,
    input_text: str | None = None,
    timeout: float = 30,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def require_ok(result: subprocess.CompletedProcess[str], label: str) -> str:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:400]
        raise ProbeError(f"{label}_failed: {detail}")
    return result.stdout.strip()


def psql(
    binary: Path,
    database: str,
    sql: str,
    *,
    timeout: float = 30,
) -> subprocess.CompletedProcess[str]:
    return run(
        [
            str(binary),
            "-h",
            "127.0.0.1",
            "-p",
            "5432",
            "-d",
            database,
            *PSQL_FLAGS,
        ],
        input_text=sql,
        timeout=timeout,
    )


def authenticated_sql(user_id: str, statement: str) -> str:
    return f"""
    begin;
    set local role authenticated;
    select pg_catalog.set_config('request.jwt.claim.sub', '{user_id}', true);
    {statement}
    commit;
    """


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-bin", type=Path, required=True)
    args = parser.parse_args()

    psql_bin = args.pg_bin / "psql"
    createdb_bin = args.pg_bin / "createdb"
    dropdb_bin = args.pg_bin / "dropdb"
    for binary in (psql_bin, createdb_bin, dropdb_bin):
        if not binary.is_file():
            raise ProbeError(f"tool_missing:{binary.name}")

    database = f"pets_enclosure_probe_{secrets.token_hex(6)}"
    if not DB_NAME.fullmatch(database):
        raise ProbeError("unsafe_database_name")

    existing_text = require_ok(
        psql(
            psql_bin,
            "postgres",
            "select rolname from pg_roles "
            "where rolname in ('anon','authenticated','service_role') "
            "order by rolname;",
        ),
        "role_inventory",
    )
    existing = set(existing_text.splitlines()) if existing_text else set()
    created_roles = [role for role in ROLES if role not in existing]

    cleanup_errors: list[str] = []
    try:
        role_sql = [
            f"create role {role} nologin"
            + (" bypassrls" if role == "service_role" else "")
            + ";"
            for role in created_roles
        ]
        if role_sql:
            require_ok(
                psql(psql_bin, "postgres", "\n".join(role_sql)),
                "role_setup",
            )

        require_ok(
            run(
                [
                    str(createdb_bin),
                    "-h",
                    "127.0.0.1",
                    "-p",
                    "5432",
                    database,
                ]
            ),
            "createdb",
        )

        prerequisite = f"""
        create schema auth;
        create function auth.uid()
        returns uuid language sql stable set search_path = '' as $$
          select nullif(pg_catalog.current_setting(
            'request.jwt.claim.sub', true
          ), '')::uuid
        $$;

        create table public.enclosures (
          id uuid primary key,
          owner_id uuid not null
        );
        create table public.pets (
          id uuid primary key,
          user_id uuid not null,
          name text not null,
          updated_at timestamptz not null default pg_catalog.now()
        );

        alter table public.enclosures enable row level security;
        alter table public.pets enable row level security;
        create policy own_enclosures_all on public.enclosures
          for all to authenticated
          using (auth.uid() = owner_id)
          with check (auth.uid() = owner_id);
        create policy own_pets_all on public.pets
          for all to authenticated
          using (auth.uid() = user_id)
          with check (auth.uid() = user_id);

        grant usage on schema public, auth to authenticated;
        grant execute on function auth.uid() to authenticated;
        grant select, insert, update, delete
          on public.enclosures, public.pets to authenticated;

        insert into public.enclosures(id, owner_id) values
          ('{ENC_A}', '{USER_A}'),
          ('{ENC_B}', '{USER_B}');
        insert into public.pets(id, user_id, name) values
          ('{PET_A1}', '{USER_A}', 'a1'),
          ('{PET_A2}', '{USER_A}', 'a2'),
          ('{PET_B}', '{USER_B}', 'b');
        """
        require_ok(psql(psql_bin, database, prerequisite), "prerequisite")
        require_ok(
            psql(psql_bin, database, MIGRATION.read_text(), timeout=60),
            "migration",
        )

        schema_contract = require_ok(
            psql(
                psql_bin,
                database,
                """
                select
                  (select count(*) from information_schema.columns
                    where table_schema='public' and table_name='pets'
                      and column_name='enclosure_id')::text || '|' ||
                  (select count(*) from pg_indexes
                    where schemaname='public' and tablename='pets'
                      and indexname='pets_enclosure_id_unique')::text || '|' ||
                  (select count(*) from pg_trigger
                    where tgrelid='public.pets'::regclass
                      and tgname='pets_enclosure_owner_guard_trg')::text || '|' ||
                  (select count(*) from public.pets
                    where enclosure_id is not null)::text || '|' ||
                  has_function_privilege(
                    'authenticated',
                    'public.assign_pet_to_enclosure(uuid,uuid)',
                    'execute'
                  )::text || '|' ||
                  has_function_privilege(
                    'anon',
                    'public.assign_pet_to_enclosure(uuid,uuid)',
                    'execute'
                  )::text;
                """,
            ),
            "schema_contract",
        ).splitlines()[-1]
        if schema_contract != "1|1|1|0|true|false":
            raise ProbeError(f"schema_contract_mismatch:{schema_contract}")

        require_ok(
            psql(
                psql_bin,
                database,
                authenticated_sql(
                    USER_A,
                    f"select public.assign_pet_to_enclosure('{PET_A1}', '{ENC_A}');",
                ),
            ),
            "first_assignment",
        )
        require_ok(
            psql(
                psql_bin,
                database,
                authenticated_sql(
                    USER_A,
                    f"select public.assign_pet_to_enclosure('{PET_A2}', '{ENC_A}');",
                ),
            ),
            "swap_assignment",
        )
        swapped = require_ok(
            psql(
                psql_bin,
                database,
                f"""
                select
                  (select enclosure_id is null from public.pets where id='{PET_A1}')::text
                  || '|' ||
                  (select enclosure_id='{ENC_A}' from public.pets where id='{PET_A2}')::text;
                """,
            ),
            "swap_result",
        ).splitlines()[-1]
        if swapped != "true|true":
            raise ProbeError(f"swap_mismatch:{swapped}")

        cross_owner = psql(
            psql_bin,
            database,
            authenticated_sql(
                USER_A,
                f"select public.assign_pet_to_enclosure('{PET_A1}', '{ENC_B}');",
            ),
        )
        if (
            cross_owner.returncode == 0
            or "enclosure is not owned by caller" not in cross_owner.stderr
        ):
            raise ProbeError("cross_owner_rpc_was_not_rejected")

        direct_cross_owner = psql(
            psql_bin,
            database,
            authenticated_sql(
                USER_A,
                f"update public.pets set enclosure_id='{ENC_B}' where id='{PET_A1}';",
            ),
        )
        if (
            direct_cross_owner.returncode == 0
            or "pet and enclosure ownership mismatch" not in direct_cross_owner.stderr
        ):
            raise ProbeError("cross_owner_direct_update_was_not_rejected")

        user_id_change = psql(
            psql_bin,
            database,
            f"update public.pets set user_id='{USER_B}' where id='{PET_A2}';",
        )
        if (
            user_id_change.returncode == 0
            or "pet and enclosure ownership mismatch" not in user_id_change.stderr
        ):
            raise ProbeError("user_id_only_update_bypassed_guard")

        require_ok(
            psql(
                psql_bin,
                database,
                authenticated_sql(
                    USER_A,
                    f"select public.assign_pet_to_enclosure('{PET_A2}', null);",
                ),
            ),
            "unassign",
        )
        assigned_after = require_ok(
            psql(
                psql_bin,
                database,
                "select count(*) from public.pets where enclosure_id is not null;",
            ),
            "assigned_after",
        ).splitlines()[-1]
        if assigned_after != "0":
            raise ProbeError(f"unassign_failed:{assigned_after}")

        # 같은 사용자의 두 요청을 실제 동시 실행한다. 첫 트랜잭션이 advisory
        # lock을 잠시 유지해도 둘 다 성공하고 최종 점유자는 정확히 하나여야 한다.
        command_a = authenticated_sql(
            USER_A,
            f"""
            select public.assign_pet_to_enclosure('{PET_A1}', '{ENC_A}');
            select pg_catalog.pg_sleep(1);
            """,
        )
        command_b = authenticated_sql(
            USER_A,
            f"select public.assign_pet_to_enclosure('{PET_A2}', '{ENC_A}');",
        )
        argv = [
            str(psql_bin),
            "-h",
            "127.0.0.1",
            "-p",
            "5432",
            "-d",
            database,
            *PSQL_FLAGS,
        ]
        proc_a = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert proc_a.stdin is not None
        proc_a.stdin.write(command_a)
        proc_a.stdin.close()
        proc_b = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        out_b, err_b = proc_b.communicate(command_b, timeout=10)
        proc_a.wait(timeout=10)
        err_a = proc_a.stderr.read() if proc_a.stderr is not None else ""
        if proc_a.returncode != 0 or proc_b.returncode != 0:
            raise ProbeError(
                "concurrent_assignment_failed:"
                f"a={err_a[:160]!r}:b={(err_b or out_b)[:160]!r}"
            )
        occupant_count = require_ok(
            psql(
                psql_bin,
                database,
                f"select count(*) from public.pets where enclosure_id='{ENC_A}';",
            ),
            "occupant_count",
        ).splitlines()[-1]
        if occupant_count != "1":
            raise ProbeError(f"concurrent_occupant_mismatch:{occupant_count}")

        print("PETS_ENCLOSURE_LINK_PROBE_OK")
        return 0
    finally:
        dropped = run(
            [
                str(dropdb_bin),
                "-h",
                "127.0.0.1",
                "-p",
                "5432",
                "--if-exists",
                database,
            ]
        )
        if dropped.returncode != 0:
            cleanup_errors.append("dropdb")
        for role in reversed(created_roles):
            result = psql(psql_bin, "postgres", f"drop role if exists {role};")
            if result.returncode != 0:
                cleanup_errors.append(f"drop_role:{role}")
        if cleanup_errors:
            raise ProbeError("cleanup_failed:" + ",".join(cleanup_errors))


if __name__ == "__main__":
    raise SystemExit(main())

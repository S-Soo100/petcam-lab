"""news_articles migration을 로컬 임시 PostgreSQL DB에서 실증해.

기존 DB는 읽거나 수정하지 않고 `news_probe_<hex>` DB와 probe가 새로 만든 역할만 정리한다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import secrets
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "2026-07-29_news_articles.sql"
DB_NAME = re.compile(r"^news_probe_[0-9a-f]{12}$")
ROLES = ("anon", "authenticated", "service_role")
PSQL_FLAGS = ("-X", "-v", "ON_ERROR_STOP=1", "-qAt")


class ProbeError(RuntimeError):
    """실증 또는 정리가 계약과 다를 때 발생해."""


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

    database = f"news_probe_{secrets.token_hex(6)}"
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
    role_sql = []
    for role in created_roles:
        bypass = " bypassrls" if role == "service_role" else ""
        role_sql.append(f"create role {role} nologin{bypass};")

    cleanup_errors: list[str] = []
    try:
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
        require_ok(
            psql(psql_bin, database, MIGRATION.read_text(), timeout=60),
            "migration",
        )
        seed_sql = """
        insert into public.news_articles
          (slug,title,summary,body_md,status,published_at)
        values
          ('probe-published','발행','요약','# 발행','published',now()-interval '1 minute'),
          ('probe-draft','초안',null,'# 초안','draft',null),
          ('probe-future','예약',null,'# 예약','published',now()+interval '1 day');
        """
        require_ok(psql(psql_bin, database, seed_sql), "seed")

        public_query = """
        set role {role};
        select coalesce(string_agg(slug, ',' order by slug),'')
        from public.news_articles;
        reset role;
        """
        for role in ("anon", "authenticated"):
            visible = require_ok(
                psql(psql_bin, database, public_query.format(role=role)),
                f"{role}_read",
            ).splitlines()[-1]
            if visible != "probe-published":
                raise ProbeError(f"{role}_visibility_mismatch:{visible}")

        denied = psql(
            psql_bin,
            database,
            """
            set role anon;
            insert into public.news_articles(slug,title,body_md)
            values ('probe-hack','hack','hack');
            """,
        )
        if denied.returncode == 0:
            raise ProbeError("anon_write_allowed")

        # 로컬 cluster의 기존 service_role 속성은 건드리지 않는다. production의
        # BYPASSRLS는 production probe에서 확인하고, 여기서는 명시 GRANT와 row 동작을 분리 실증한다.
        require_ok(
            psql(
                psql_bin,
                database,
                """
                insert into public.news_articles(slug,title,body_md)
                values ('probe-service','서비스','본문');
                """,
            ),
            "owner_insert",
        )
        touched = require_ok(
            psql(
                psql_bin,
                database,
                """
                update public.news_articles
                set title='서비스 수정'
                where slug='probe-service';
                select (updated_at > created_at)::text
                from public.news_articles where slug='probe-service';
                """,
            ),
            "owner_update",
        ).splitlines()[-1]
        if touched != "true":
            raise ProbeError("touch_trigger_failed")

        bad_slug = psql(
            psql_bin,
            database,
            """
            insert into public.news_articles(slug,title,body_md)
            values ('../escape','escape','body');
            """,
        )
        if bad_slug.returncode == 0:
            raise ProbeError("invalid_slug_allowed")

        security = require_ok(
            psql(
                psql_bin,
                database,
                """
                select
                  (select relrowsecurity from pg_class
                   where oid='public.news_articles'::regclass)::text
                  || '|' ||
                  (select count(*)::text from pg_policy
                   where polrelid='public.news_articles'::regclass
                     and polcmd='r')
                  || '|' ||
                  has_function_privilege(
                    'anon','public.fn_news_articles_touch()','execute'
                  )::text
                  || '|' ||
                  has_table_privilege(
                    'service_role','public.news_articles',
                    'select,insert,update,delete'
                  )::text;
                """,
            ),
            "security_contract",
        )
        if security != "true|1|false|true":
            raise ProbeError(f"security_contract_mismatch:{security}")

        print("NEWS_ARTICLES_RUNTIME_OK")
        print("NEWS_ARTICLES_RLS_OK")
    finally:
        if DB_NAME.fullmatch(database):
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
        if created_roles:
            role_drop_sql = "\n".join(
                f"drop role if exists {role};" for role in reversed(created_roles)
            )
            dropped_roles = psql(psql_bin, "postgres", role_drop_sql)
            if dropped_roles.returncode != 0:
                cleanup_errors.append("drop_roles")
        residue = require_ok(
            psql(
                psql_bin,
                "postgres",
                f"select count(*) from pg_database where datname='{database}';",
            ),
            "residue_check",
        )
        print(f"PROBE_RESIDUE={residue}")
        if residue != "0" or cleanup_errors:
            raise ProbeError(f"cleanup_failed:{','.join(cleanup_errors)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError, ProbeError) as exc:
        print(f"NEWS_ARTICLES_PROBE_FAILED type={type(exc).__name__}", file=sys.stderr)
        raise SystemExit(2) from exc

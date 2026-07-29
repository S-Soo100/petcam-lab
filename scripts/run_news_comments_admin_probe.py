"""뉴스 댓글·관리자 migration을 로컬 임시 PostgreSQL DB에서 실증해.

기존 DB는 수정하지 않고 `news_admin_probe_<hex>` DB와 이 probe가 만든 역할만 정리한다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
ARTICLES_MIGRATION = ROOT / "migrations" / "2026-07-29_news_articles.sql"
MIGRATION = ROOT / "migrations" / "2026-07-29_news_comments_admin.sql"
DB_NAME = re.compile(r"^news_admin_probe_[0-9a-f]{12}$")
ROLES = ("anon", "authenticated", "service_role")
PSQL_FLAGS = ("-X", "-v", "ON_ERROR_STOP=1", "-qAt")
ADMIN_ID = "10000000-0000-0000-0000-000000000001"
NON_ADMIN_ID = "10000000-0000-0000-0000-000000000002"


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
        detail = (result.stderr or result.stdout).strip()[:500]
        raise ProbeError(f"{label}_failed: {detail}")
    return result.stdout.strip()


def psql_argv(binary: Path, database: str) -> list[str]:
    return [
        str(binary),
        "-h",
        "127.0.0.1",
        "-p",
        "5432",
        "-d",
        database,
        *PSQL_FLAGS,
    ]


def psql(
    binary: Path,
    database: str,
    sql: str,
    *,
    timeout: float = 30,
) -> subprocess.CompletedProcess[str]:
    return run(psql_argv(binary, database), input_text=sql, timeout=timeout)


def expected_failure(
    result: subprocess.CompletedProcess[str],
    *,
    label: str,
    contains: str,
) -> None:
    if result.returncode == 0:
        raise ProbeError(f"{label}_unexpected_success")
    output = f"{result.stdout}\n{result.stderr}".lower()
    if contains.lower() not in output:
        raise ProbeError(f"{label}_wrong_error:{output.strip()[:300]}")


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

    database = f"news_admin_probe_{secrets.token_hex(6)}"
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
        if created_roles:
            role_sql = "\n".join(
                f"create role {role} nologin;" for role in created_roles
            )
            require_ok(psql(psql_bin, "postgres", role_sql), "role_setup")

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

        fixture = f"""
        create schema auth;
        create table auth.users(id uuid primary key);
        insert into auth.users(id) values ('{ADMIN_ID}'), ('{NON_ADMIN_ID}');
        create function auth.uid()
        returns uuid
        language sql
        stable
        as $$
          select nullif(
            pg_catalog.current_setting('request.jwt.claim.sub', true),
            ''
          )::uuid
        $$;

        create schema storage;
        create table storage.buckets(
          id text primary key,
          name text not null unique,
          public boolean not null default false
        );
        create table storage.objects(
          id uuid primary key default pg_catalog.gen_random_uuid(),
          bucket_id text not null references storage.buckets(id),
          name text not null
        );
        alter table storage.objects enable row level security;
        grant usage on schema storage to anon, authenticated, service_role;
        grant select on storage.objects to anon;
        grant select, insert, update, delete on storage.objects
          to authenticated, service_role;

        create table public.motion_clips(id uuid primary key);
        revoke all on table public.motion_clips from public, anon, authenticated;
        """
        require_ok(psql(psql_bin, database, fixture), "fixture")
        require_ok(
            psql(
                psql_bin,
                database,
                ARTICLES_MIGRATION.read_text(encoding="utf-8"),
                timeout=60,
            ),
            "articles_migration",
        )
        require_ok(
            psql(
                psql_bin,
                database,
                MIGRATION.read_text(encoding="utf-8"),
                timeout=60,
            ),
            "migration",
        )

        seed = f"""
        insert into public.news_admins(user_id,note)
        values ('{ADMIN_ID}','probe admin');
        insert into public.news_articles(slug,title,body_md,status,published_at)
        values
          ('probe-public','공개','본문','published',pg_catalog.now()-interval '1 minute'),
          ('probe-draft','초안','본문','draft',null);
        """
        require_ok(psql(psql_bin, database, seed), "seed")

        direct = psql(
            psql_bin,
            database,
            """
            set role anon;
            insert into public.news_comments(article_id,nickname,body,fingerprint)
            select id,'x','x',repeat('a',64)
            from public.news_articles where slug='probe-public';
            """,
        )
        expected_failure(direct, label="anon_direct_insert", contains="permission denied")

        first_comment = require_ok(
            psql(
                psql_bin,
                database,
                """
                set role anon;
                set request.headers =
                  '{"x-forwarded-for":"192.0.2.1","user-agent":"probe-a"}';
                select public.fn_submit_news_comment(
                  'probe-public','테스터','첫 댓글'
                );
                reset role;
                """,
            ),
            "anon_rpc_insert",
        ).splitlines()[-1]
        if not re.fullmatch(r"[0-9a-f-]{36}", first_comment):
            raise ProbeError("comment_uuid_invalid")

        limited = psql(
            psql_bin,
            database,
            """
            set role anon;
            set request.headers =
              '{"x-forwarded-for":"192.0.2.1","user-agent":"probe-a"}';
            select public.fn_submit_news_comment(
              'probe-public','테스터','두 번째 댓글'
            );
            """,
        )
        expected_failure(limited, label="sequential_rate_limit", contains="too many requests")

        draft = psql(
            psql_bin,
            database,
            """
            set role anon;
            set request.headers =
              '{"x-forwarded-for":"192.0.2.2","user-agent":"probe-b"}';
            select public.fn_submit_news_comment(
              'probe-draft','테스터','초안 댓글'
            );
            """,
        )
        expected_failure(draft, label="draft_comment", contains="not published")

        hidden = require_ok(
            psql(
                psql_bin,
                database,
                f"""
                set role authenticated;
                set request.jwt.claim.sub = '{ADMIN_ID}';
                select public.fn_admin_set_comment_hidden('{first_comment}',true);
                reset role;
                set role anon;
                select count(*) from public.news_comments;
                reset role;
                """,
            ),
            "hidden_visibility",
        ).splitlines()[-1]
        if hidden != "0":
            raise ProbeError(f"hidden_comment_visible:{hidden}")

        non_admin = psql(
            psql_bin,
            database,
            f"""
            set role authenticated;
            set request.jwt.claim.sub = '{NON_ADMIN_ID}';
            select public.fn_admin_delete_comment(
              '00000000-0000-0000-0000-000000000000'
            );
            """,
        )
        expected_failure(non_admin, label="non_admin_rpc", contains="forbidden")

        motion = psql(
            psql_bin,
            database,
            "set role anon; select count(*) from public.motion_clips;",
        )
        expected_failure(motion, label="motion_rls_regression", contains="permission denied")

        storage_denied = psql(
            psql_bin,
            database,
            f"""
            set role authenticated;
            set request.jwt.claim.sub = '{NON_ADMIN_ID}';
            insert into storage.objects(bucket_id,name)
            values ('news-media','denied.png');
            """,
        )
        expected_failure(
            storage_denied,
            label="storage_non_admin",
            contains="row-level security",
        )
        require_ok(
            psql(
                psql_bin,
                database,
                f"""
                set role authenticated;
                set request.jwt.claim.sub = '{ADMIN_ID}';
                insert into storage.objects(bucket_id,name)
                values ('news-media','allowed.png');
                update storage.objects set name='allowed-2.png'
                where bucket_id='news-media' and name='allowed.png';
                delete from storage.objects
                where bucket_id='news-media' and name='allowed-2.png';
                reset role;
                """,
            ),
            "storage_admin",
        )

        # 첫 transaction이 INSERT 후 commit 전 1초 대기한다. advisory lock이 없다면
        # 두 번째 transaction도 미커밋 행을 못 보고 성공하므로 이 테스트가 회귀를 잡는다.
        headers = '{"x-forwarded-for":"192.0.2.50","user-agent":"probe-race"}'
        first_sql = f"""
        begin;
        set role anon;
        set request.headers = '{headers}';
        select public.fn_submit_news_comment(
          'probe-public','race-a','동시 첫 댓글'
        );
        select pg_catalog.pg_sleep(1);
        commit;
        """
        first = subprocess.Popen(
            psql_argv(psql_bin, database),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert first.stdin is not None
        first.stdin.write(first_sql)
        first.stdin.close()
        time.sleep(0.2)
        second = psql(
            psql_bin,
            database,
            f"""
            begin;
            set role anon;
            set request.headers = '{headers}';
            select public.fn_submit_news_comment(
              'probe-public','race-b','동시 두 번째 댓글'
            );
            commit;
            """,
            timeout=10,
        )
        first_returncode = first.wait(timeout=10)
        first_stdout = first.stdout.read() if first.stdout else ""
        first_stderr = first.stderr.read() if first.stderr else ""
        if first_returncode != 0:
            raise ProbeError(
                f"concurrency_first_failed:{(first_stderr or first_stdout)[:300]}"
            )
        expected_failure(
            second,
            label="concurrency_rate_limit",
            contains="too many requests",
        )

        security = require_ok(
            psql(
                psql_bin,
                database,
                """
                select
                  (select count(*) from pg_policy
                   where polrelid='public.news_comments'::regclass)::text
                  || '|' ||
                  has_table_privilege(
                    'anon','public.news_comments','insert'
                  )::text
                  || '|' ||
                  has_function_privilege(
                    'anon',
                    'public.fn_admin_delete_comment(uuid)',
                    'execute'
                  )::text
                  || '|' ||
                  has_function_privilege(
                    'anon',
                    'public.fn_submit_news_comment(text,text,text)',
                    'execute'
                  )::text
                  || '|' ||
                  (select count(*) from storage.buckets
                   where id='news-media' and public=true)::text
                  || '|' ||
                  (select count(*) from pg_policy
                   where polrelid='storage.objects'::regclass
                     and polname like 'news_media_%')::text;
                """,
            ),
            "security_contract",
        )
        if security != "2|false|false|true|1|4":
            raise ProbeError(f"security_contract_mismatch:{security}")

        print("NEWS_COMMENTS_RUNTIME_OK")
        print("NEWS_ADMIN_RLS_OK")
        print("NEWS_COMMENT_RATE_LIMIT_OK")
        print("NEWS_STORAGE_POLICY_OK")
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
        failure_code = str(exc).partition(":")[0]
        print(
            "NEWS_COMMENTS_ADMIN_PROBE_FAILED "
            f"type={type(exc).__name__} code={failure_code}",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc

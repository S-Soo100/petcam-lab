"""terra ai News 댓글·관리자 migration 정적 보안 계약."""

from pathlib import Path
import re

import pytest


SQL_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "2026-07-29_news_comments_admin.sql"
)


@pytest.fixture(scope="module")
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def lower(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.lower()).strip()


def test_migration_is_atomic_forward_only_and_collision_fail_closed(lower: str) -> None:
    assert lower.startswith("begin;")
    assert lower.endswith("commit;")
    assert "create table public.news_admins" in lower
    assert "create table public.news_comments" in lower
    assert "if not exists" not in lower
    assert "create or replace" not in lower
    assert "drop table" not in lower
    assert "drop policy" not in lower


def test_news_admin_membership_is_service_role_only(lower: str) -> None:
    assert "user_id uuid primary key references auth.users(id) on delete cascade" in lower
    assert "alter table public.news_admins enable row level security" in lower
    assert (
        "revoke all on table public.news_admins "
        "from public, anon, authenticated" in lower
    )
    assert (
        "grant select, insert, update, delete on table public.news_admins "
        "to service_role" in lower
    )
    assert "create policy" not in _table_section(lower, "news_admins", "fn_is_news_admin")


def test_comments_are_public_read_only_at_table_boundary(lower: str) -> None:
    assert "fingerprint text not null" in lower
    assert "fingerprint ~ '^[0-9a-f]{64}$'" in lower
    assert "alter table public.news_comments enable row level security" in lower
    assert (
        "revoke all on table public.news_comments "
        "from public, anon, authenticated" in lower
    )
    assert (
        "grant select on table public.news_comments "
        "to anon, authenticated" in lower
    )
    assert "for select to anon, authenticated" in lower
    assert "is_hidden = false" in lower
    assert "public.fn_news_article_is_public(article_id)" in lower
    comments_grants = _table_section(lower, "news_comments", "fn_submit_news_comment")
    assert "grant insert on table public.news_comments to anon" not in comments_grants
    assert "grant update on table public.news_comments to authenticated" not in comments_grants
    assert "grant delete on table public.news_comments to authenticated" not in comments_grants


def test_all_definer_functions_have_empty_search_path_and_explicit_execute(lower: str) -> None:
    functions = (
        "fn_is_news_admin",
        "fn_news_article_is_public",
        "fn_submit_news_comment",
        "fn_admin_save_news_article",
        "fn_admin_delete_news_article",
        "fn_admin_set_comment_hidden",
        "fn_admin_delete_comment",
    )
    for name in functions:
        start = lower.index(f"create function public.{name}")
        body = lower[start : lower.index("$$;", start) + 3]
        assert "security definer" in body
        assert "set search_path = ''" in body
    assert (
        "revoke all on function public.fn_submit_news_comment(text, text, text) "
        "from public" in lower
    )
    assert (
        "grant execute on function public.fn_submit_news_comment(text, text, text) "
        "to anon, authenticated, service_role" in lower
    )


def test_submit_rpc_validates_headers_and_serializes_rate_limit(lower: str) -> None:
    submit = _function_section(lower, "fn_submit_news_comment", "fn_admin_save_news_article")
    # NULLIF/COALESCE는 PostgreSQL 특수 구문이라 pg_catalog 함수처럼 수식하면 실행이 깨진다.
    assert "pg_catalog.nullif" not in submit
    assert "pg_catalog.coalesce" not in submit
    assert "current_setting('request.headers', true)" in submit
    assert "nullif(" in submit
    assert "'{}'::jsonb" in submit
    assert "x-forwarded-for" in submit
    assert "user-agent" in submit
    assert "|news-comment-v1" in submit
    assert "pg_catalog.sha256" in submit
    assert "pg_catalog.pg_advisory_xact_lock" in submit
    assert "pg_catalog.hashtextextended(v_fp, 0)" in submit
    assert "v_recent_1m >= 1" in submit
    assert "v_recent_1h >= 5" in submit
    assert "errcode = '53400'" in submit
    assert "status = 'published'" in submit
    assert "published_at <= pg_catalog.now()" in submit


def test_admin_rpc_requires_membership_and_anon_cannot_execute(lower: str) -> None:
    admin_functions = (
        "fn_admin_save_news_article",
        "fn_admin_delete_news_article",
        "fn_admin_set_comment_hidden",
        "fn_admin_delete_comment",
    )
    for index, name in enumerate(admin_functions):
        next_name = admin_functions[index + 1] if index + 1 < len(admin_functions) else None
        section = _function_section(lower, name, next_name)
        assert "if public.fn_is_news_admin() is not true then" in section
        assert "errcode = '42501'" in section
    assert re.search(
        r"revoke all on function public\.fn_admin_save_news_article\([^;]+\) "
        r"from public, anon;",
        lower,
    )
    assert re.search(
        r"grant execute on function public\.fn_admin_save_news_article\([^;]+\) "
        r"to authenticated, service_role;",
        lower,
    )


def test_storage_bucket_and_policies_are_bounded(lower: str) -> None:
    assert "insert into storage.buckets" in lower
    assert "'news-media'" in lower
    assert "news_media_public_read" in lower
    assert "news_media_admin_write" in lower
    assert "news_media_admin_modify" in lower
    assert "news_media_admin_delete" in lower
    modify = lower[lower.index("create policy news_media_admin_modify") :]
    modify = modify[: modify.index("create policy news_media_admin_delete")]
    assert "for update to authenticated" in modify
    predicate = r"\(\s*bucket_id = 'news-media'\s+and public\.fn_is_news_admin\(\)\s*\)"
    assert re.search(r"using\s+" + predicate, modify)
    assert re.search(r"with check\s+" + predicate, modify)


def test_existing_video_labeling_and_rba_domains_are_not_mutated(lower: str) -> None:
    forbidden = (
        "motion_clips",
        "camera_clips",
        "behavior_logs",
        "clip_labeling",
        "motion_blind",
        "python_evidence",
    )
    for name in forbidden:
        assert name not in lower
    altered = re.findall(r"alter table ([a-z0-9_.]+)", lower)
    assert altered == ["public.news_admins", "public.news_comments"]


def _table_section(lower: str, table: str, next_marker: str) -> str:
    start = lower.index(f"create table public.{table}")
    return lower[start : lower.index(next_marker, start)]


def _function_section(lower: str, function: str, next_function: str | None) -> str:
    start = lower.index(f"create function public.{function}")
    if next_function is None:
        return lower[start:]
    return lower[start : lower.index(f"create function public.{next_function}", start)]

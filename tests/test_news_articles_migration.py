"""terra ai News 공개 읽기 migration 정적 계약 테스트."""

from pathlib import Path
import re

import pytest


SQL_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "2026-07-29_news_articles.sql"
)


@pytest.fixture(scope="module")
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def lower(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.lower()).strip()


def test_migration_is_atomic_and_collision_fail_closed(lower: str) -> None:
    assert lower.startswith("begin;")
    assert lower.endswith("commit;")
    assert "create table public.news_articles" in lower
    assert "create function public.fn_news_articles_touch()" in lower
    assert "create trigger news_articles_touch" in lower
    assert "if not exists" not in lower
    assert "create or replace" not in lower
    assert "drop trigger" not in lower
    assert "drop policy" not in lower


def test_schema_has_publication_and_slug_guards(lower: str) -> None:
    assert "slug text not null unique" in lower
    assert "char_length(slug) between 1 and 120" in lower
    assert "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'" in lower
    assert "status in ('draft', 'published')" in lower
    assert "status <> 'published' or published_at is not null" in lower
    assert "body_md text not null" in lower
    assert "char_length(body_md) > 0" in lower


def test_public_read_is_select_only_and_row_scoped(lower: str) -> None:
    assert "alter table public.news_articles enable row level security" in lower
    assert (
        "revoke all on table public.news_articles "
        "from public, anon, authenticated" in lower
    )
    assert (
        "grant select on table public.news_articles "
        "to anon, authenticated" in lower
    )
    assert "for select to anon, authenticated" in lower
    assert "status = 'published'" in lower
    assert "published_at is not null" in lower
    assert "published_at <= now()" in lower
    assert "grant insert" not in lower
    assert "grant update" not in lower
    assert "grant delete" not in lower


def test_service_role_and_trigger_function_are_explicit(lower: str) -> None:
    assert (
        "grant select, insert, update, delete on table public.news_articles "
        "to service_role" in lower
    )
    assert "security invoker" in lower
    assert "set search_path = ''" in lower
    assert (
        "revoke all on function public.fn_news_articles_touch() "
        "from public, anon, authenticated" in lower
    )


def test_migration_does_not_touch_existing_domains(lower: str) -> None:
    forbidden = (
        "motion_clips",
        "camera_clips",
        "behavior_logs",
        "clip_labeling",
        "motion_blind",
        "python_evidence",
        "auth.users",
    )
    for name in forbidden:
        assert name not in lower
    assert "insert into" not in lower
    altered = re.findall(r"alter table ([a-z0-9_.]+)", lower)
    assert altered == ["public.news_articles"]

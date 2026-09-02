"""pets.enclosure_id forward migration의 정적 안전 계약."""

from pathlib import Path
import re

import pytest


SQL_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "2026-08-06_pets_enclosure_link.sql"
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
    assert "if not exists" not in lower
    assert "create or replace" not in lower
    assert "drop trigger" not in lower


def test_adds_nullable_fk_and_partial_unique_index(lower: str) -> None:
    assert "alter table public.pets add column enclosure_id uuid" in lower
    assert "constraint pets_enclosure_id_fkey" in lower
    assert "references public.enclosures(id) on delete set null" in lower
    assert "enclosure_id uuid not null" not in lower
    assert "create unique index pets_enclosure_id_unique" in lower
    assert "where enclosure_id is not null" in lower
    assert "on delete cascade" not in lower


def test_owner_guard_is_mandatory_and_covers_user_id_changes(lower: str) -> None:
    assert "create function public.pets_enclosure_owner_guard()" in lower
    assert "security definer" in lower
    assert "set search_path = ''" in lower
    assert "new.user_id" in lower
    assert "e.owner_id" in lower
    assert (
        "before insert or update of enclosure_id, user_id on public.pets"
        in lower
    )
    assert (
        "revoke all on function public.pets_enclosure_owner_guard() "
        "from public, anon, authenticated" in lower
    )


def test_assignment_rpc_is_authenticated_atomic_and_serialized(lower: str) -> None:
    assert (
        "create function public.assign_pet_to_enclosure( "
        "p_pet_id uuid, p_enclosure_id uuid" in lower
    )
    assert "v_uid uuid := auth.uid()" in lower
    assert "pg_catalog.pg_advisory_xact_lock" in lower
    assert "for update" in lower
    assert "where enclosure_id = p_enclosure_id" in lower
    assert "and user_id = v_uid" in lower
    assert "set enclosure_id = p_enclosure_id" in lower
    assert "set search_path = ''" in lower
    assert (
        "grant execute on function public.assign_pet_to_enclosure(uuid, uuid) "
        "to authenticated" in lower
    )


def test_rpc_fails_closed_on_cross_owner_integrity_damage(lower: str) -> None:
    assert "cross-owner enclosure assignment already exists" in lower
    assert "errcode = 'integrity_constraint_violation'" in lower
    assert "user_id <> v_uid" in lower


def test_migration_does_not_rewrite_existing_rows(lower: str) -> None:
    prefix = lower.split("create function public.assign_pet_to_enclosure", 1)[0]
    assert "update public.pets" not in prefix
    assert "delete from public.pets" not in lower
    assert "truncate public.pets" not in lower

"""경계 해결은 두 검수자의 전체 최초 판정 뒤에만 열리는 forward migration 계약."""

from pathlib import Path


SQL_PATH = Path("migrations/2026-08-02_rba_boundary_adjudication_blind_gate.sql")


def _sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8").lower()


def test_conflict_list_is_empty_until_the_whole_split_is_complete() -> None:
    sql = _sql()
    assert "create or replace function public.fn_list_rba_boundary_conflicts" in sql
    assert "count(s.id) = count(a.id)" in sql
    assert "count(a.id) > 0" in sql
    assert "'ready', false" in sql
    assert "'items', '[]'::jsonb" in sql
    assert "'total', 0" in sql


def test_resolution_rechecks_the_same_gate_server_side() -> None:
    sql = _sql()
    assert "create or replace function public.fn_resolve_rba_boundary_conflict" in sql
    assert "adjudication_not_ready" in sql
    assert "errcode = 'pt409'" in sql
    assert "count(s.id) = count(a.id)" in sql


def test_migration_preserves_human_history_and_service_role_boundary() -> None:
    sql = _sql()
    for forbidden in (
        "delete from public.rba_boundary",
        "truncate public.rba_boundary",
        "update public.rba_boundary_review_submissions",
        "update public.rba_boundary_review_resolutions",
    ):
        assert forbidden not in sql
    for signature in (
        "fn_list_rba_boundary_conflicts(uuid)",
        "fn_resolve_rba_boundary_conflict(uuid, uuid, text, text)",
    ):
        assert f"revoke all on function public.{signature} from public, anon, authenticated" in sql
        assert f"grant execute on function public.{signature} to service_role" in sql

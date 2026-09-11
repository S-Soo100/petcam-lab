"""표본 항목 제거 RPC migration 정적 계약 — owner 전용, 사람 확정 항목 보호, service_role 만."""
from pathlib import Path

import pytest

SQL_PATH = Path(__file__).resolve().parent.parent / "migrations" / "2026-09-12_eval_sample_remove.sql"


@pytest.fixture()
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


def norm(t: str) -> str:
    return " ".join(t.lower().split())


def test_signature_and_guards(sql: str) -> None:
    n = norm(sql)
    assert "create function public.fn_remove_eval_sample_items(p_sample_id text, p_clip_ids uuid[], p_actor uuid, p_is_owner boolean) returns integer" in n
    assert "raise exception 'owner only' using errcode = 'pt403'" in n
    assert "and not exists (select 1 from public.motion_clip_highlight_verdicts v where v.clip_id = s.clip_id)" in n
    assert "delete from public.motion_clip_eval_samples s" in n
    assert "revoke all on function public.fn_remove_eval_sample_items(text, uuid[], uuid, boolean) from public, anon, authenticated;" in n
    assert "grant execute on function public.fn_remove_eval_sample_items(text, uuid[], uuid, boolean) to service_role;" in n
    for bad in ("drop table", "truncate", "delete from public.motion_clip_highlight_verdicts"):
        assert bad not in n, bad

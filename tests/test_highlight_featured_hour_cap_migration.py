"""대표 tier v0.1(10분 묶기·시간당 3·하루 상한 없음) migration 정적 계약."""

from pathlib import Path

import pytest

SQL_PATH = Path(__file__).resolve().parent.parent / "migrations" / "2026-09-11_highlight_featured_hour_cap.sql"
SIG = "uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer"


@pytest.fixture()
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def test_replaces_old_signature_atomically(sql: str) -> None:
    n = norm(sql)
    assert n.startswith("-- ") and "begin;" in n and n.rstrip().endswith("commit;")
    assert "drop function public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text);" in n
    assert n.index("drop function") < n.index("create function")


def test_new_defaults_and_hour_cap(sql: str) -> None:
    n = norm(sql)
    assert "p_top_n integer default null" in n
    assert "p_gap_sec integer default 600" in n
    assert "p_hour_cap integer default 3" in n
    assert "episode_hour_rank integer" in n
    assert "extract(hour from (p.rep_started_at at time zone p_tz))" in n
    assert "and (p_top_n is null or h.ep_rank <= p_top_n) and (p_hour_cap is null or h.hour_rank <= p_hour_cap) then 'featured' else 'candidate'" in n


def test_keeps_guards_and_privileges(sql: str) -> None:
    n = norm(sql)
    assert "on rr.run_id is not null" in n and "run_row is not null" not in n
    assert "#variable_conflict use_column" in n
    assert f"revoke all on function public.fn_highlight_featured({SIG}) from public, anon, authenticated;" in n
    assert f"grant execute on function public.fn_highlight_featured({SIG}) to service_role;" in n
    for bad in ("drop table", "delete from", "insert into"):
        assert bad not in n, bad

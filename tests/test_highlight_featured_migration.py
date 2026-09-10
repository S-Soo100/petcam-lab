"""대표 tier 함수 migration 정적 계약 — 시그니처·기본값·권한·composite IS NOT NULL 함정 회피."""

from pathlib import Path

import pytest

SQL_PATH = Path(__file__).resolve().parent.parent / "migrations" / "2026-09-10_highlight_featured_tier.sql"


@pytest.fixture()
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def test_signature_and_defaults(sql: str) -> None:
    n = norm(sql)
    assert "create function public.fn_highlight_featured( p_camera_ids uuid[], p_from timestamptz, p_to timestamptz, p_engine_schema_version text, p_algorithm_version text, p_detector_identity text, p_top_n integer default 3, p_gap_sec integer default 1800, p_day_start_hour integer default 20, p_tz text default 'asia/seoul' )" in n
    for col in ("tier text", "episode_rank integer", "episode_clip_count integer", "episode_activity_sec numeric", "is_representative boolean", "day_key date", "reviewer_id uuid", "behavior_flagged boolean"):
        assert col in n, col
    assert "#variable_conflict use_column" in n
    assert "language plpgsql stable security definer set search_path = ''" in n


def test_avoids_composite_is_not_null_and_uses_eligibility(sql: str) -> None:
    n = norm(sql)
    assert "on rr.run_id is not null" in n
    assert "run_row is not null" not in n
    assert "public.fn_is_motion_clip_production_labeling_eligible(c.id)" in n
    assert "x.state = 'media_deleted'" in n


def test_ranking_order_and_tier_rule(sql: str) -> None:
    n = norm(sql)
    assert "order by a.ep_flagged desc, a.ep_human_o desc, a.ep_activity desc, a.ep_start desc" in n
    assert "when r.ep_rank <= p_top_n and p.rep_clip_id = e.clip_id then 'featured' else 'candidate'" in n
    assert "make_interval(secs => p_gap_sec)" in n


def test_privileges_and_no_writes(sql: str) -> None:
    n = norm(sql)
    assert "revoke all on function public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text) from public, anon, authenticated;" in n
    assert "grant execute on function public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text) to service_role;" in n
    for bad in ("drop table", "delete from", "update public.motion_clip_highlight_verdicts", "insert into"):
        assert bad not in n, bad

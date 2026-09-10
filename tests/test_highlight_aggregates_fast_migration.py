"""overview/stats 집계 교체 migration 정적 계약 (시그니처 동일, 상관 서브쿼리 제거)."""

from pathlib import Path

import pytest

SQL_PATH = Path(__file__).resolve().parent.parent / "migrations" / "2026-09-08_highlight_aggregates_fast.sql"


@pytest.fixture()
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def test_overview_keeps_signature_and_joins_once(sql: str) -> None:
    n = norm(sql)
    assert "create or replace function public.fn_get_labeling_v4_overview( p_engine_schema_version text, p_algorithm_version text, p_detector_identity text ) returns jsonb" in n
    assert "left join latest l on l.clip_id = c.id" in n
    assert "public.fn_is_motion_clip_production_labeling_eligible(c.id)" in n
    assert "left join public.cameras cam on cam.id = pc.camera_id" in n  # INNER → LEFT: 합계와 카메라 breakdown 일치
    assert "not exists (select 1 from labeled" not in n


def test_stats_keeps_signature_and_uses_filter_counts(sql: str) -> None:
    n = norm(sql)
    assert "create or replace function public.fn_highlight_rule_stats(p_from timestamptz, p_to timestamptz)" in n
    for col in ("verdict_count bigint", "kept_count bigint", "decided_count bigint", "o_to_x bigint", "x_to_o bigint", "pending_initial bigint", "reason_counts jsonb"):
        assert col in n, col
    for reason in ("false_detection", "gecko_not_visible", "camera_shake", "too_short", "interesting_low_numbers", "other"):
        assert f"filter (where v.change_reason = '{reason}')" in n, reason
    assert "jsonb_object_agg" not in n  # 상관 서브쿼리 제거


def test_no_drops_or_ledger_mutation(sql: str) -> None:
    n = norm(sql)
    for bad in ("drop function", "drop table", "update public.motion_clip_highlight_verdicts", "delete from"):
        assert bad not in n, bad

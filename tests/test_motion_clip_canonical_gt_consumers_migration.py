"""Canonical GT consumer RPC가 legacy source 우선순위를 다시 만들지 않는지 검사해."""

from pathlib import Path

SQL = Path("migrations/2026-08-04_motion_clip_canonical_gt_consumers.sql")


def test_consumers_read_heads_not_source_precedence() -> None:
    sql = SQL.read_text(encoding="utf-8").lower()
    assert "motion_clip_gt_heads" in sql
    assert "motion_clip_gt_revisions" in sql
    assert "m.r2_key is not null" in sql
    assert "motion_clip_system_exclusions" in sql
    assert "quarantined" in sql and "media_deleted" in sql
    for forbidden in (
        "motion_clip_consensus",
        "motion_clip_labeling_sessions",
        "coalesce(s.current_gt",
    ):
        assert forbidden not in sql


def test_consumer_migration_does_not_replace_existing_rpc() -> None:
    sql = SQL.read_text(encoding="utf-8").lower()
    assert "create or replace function public.fn_list_motion_labeling_library(" not in sql
    assert "create or replace function public.fn_get_labeling_data_dashboard(" not in sql


def test_consumer_rpcs_are_service_role_only_and_additive() -> None:
    sql = SQL.read_text(encoding="utf-8").lower()
    assert "fn_list_motion_labeling_library_canonical" in sql
    assert "fn_get_labeling_data_dashboard_canonical" in sql
    assert "motion_clip_canonical_gt_export" in sql
    assert "fn_get_motion_clip_canonical_gt_export_snapshot" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    for forbidden in ("delete from", "update public.motion_clip_gt_revisions"):
        assert forbidden not in sql

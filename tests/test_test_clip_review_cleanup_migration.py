from pathlib import Path


SQL_PATH = Path("migrations/2026-08-06_test_clip_review_cleanup.sql")


def sql_text() -> str:
    return SQL_PATH.read_text(encoding="utf-8")


def test_cleanup_is_test_purpose_scoped_and_protects_any_submitted_clip() -> None:
    sql = sql_text()

    assert "m.clip_purpose = 'test'" in sql
    assert "motion_clip_blind_submissions" in sql
    assert "submitted_test_clips" in sql
    assert "expected exactly 4 submitted test clips" in sql


def test_cleanup_removes_only_review_material_not_source_clip_or_r2() -> None:
    sql = sql_text().lower()

    assert "delete from public.motion_clip_review_slots" in sql
    assert "delete from public.motion_clip_consensus" in sql
    assert "delete from public.motion_clip_blind_submissions" not in sql
    assert "delete from public.motion_clips" not in sql
    assert "delete_object" not in sql


def test_cleanup_postcondition_leaves_only_the_four_submitted_test_clips() -> None:
    sql = sql_text()

    assert "test review material survived cleanup" in sql
    assert "NOT EXISTS" in sql
    assert "submitted_test_clips" in sql


def test_cleanup_locks_review_tables_before_target_selection() -> None:
    sql = sql_text()

    assert "LOCK TABLE public.motion_clip_review_slots" in sql
    assert "LOCK TABLE public.motion_clip_blind_submissions" in sql
    assert "LOCK TABLE public.motion_clip_consensus" in sql

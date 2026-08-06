from pathlib import Path


SQL_PATH = Path("migrations/2026-08-06_motion_clip_purpose_labeling_guard.sql")


def sql_text() -> str:
    return SQL_PATH.read_text(encoding="utf-8")


def test_migration_requires_terra_server_owned_clip_purpose_column() -> None:
    sql = sql_text()

    assert "information_schema.columns" in sql
    assert "clip_purpose" in sql
    assert "RAISE EXCEPTION 'motion_clips.clip_purpose prerequisite missing'" in sql


def test_eligibility_is_explicit_production_canonical_not_negative_test_match() -> None:
    sql = sql_text()

    assert "clip_purpose = 'production'" in sql
    assert "terra-clips/clips/%" in sql
    assert "research-quarantine" not in sql
    assert "research-excluded" not in sql
    assert "NOT LIKE 'test/%'" not in sql


def test_all_active_labeling_entry_points_are_guarded() -> None:
    sql = sql_text()

    for function_name in (
        "fn_is_motion_clip_production_labeling_eligible",
        "fn_ensure_motion_review_slots",
        "fn_list_motion_blind_queue",
        "fn_list_motion_clip_labeling_queue",
        "fn_list_motion_labeling_library",
    ):
        assert function_name in sql

    assert sql.count("fn_is_motion_clip_production_labeling_eligible") >= 5


def test_migration_does_not_purge_or_touch_r2() -> None:
    sql = sql_text().lower()

    assert "delete from public.motion_clips" not in sql
    assert "delete from public.motion_clip_review_slots" not in sql
    assert "put_object" not in sql
    assert "delete_object" not in sql

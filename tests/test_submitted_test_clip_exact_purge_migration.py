from pathlib import Path


SQL_PATH = Path("migrations/2026-08-06_submitted_test_clip_exact_purge.sql")


def sql_text() -> str:
    return SQL_PATH.read_text(encoding="utf-8")


def test_target_is_derived_not_hardcoded_and_exactly_four() -> None:
    sql = sql_text()

    assert "m.clip_purpose = 'test'" in sql
    assert "motion_clip_blind_submissions" in sql
    assert "expected exactly 4 submitted test clips" in sql
    assert "VALUES ('" not in sql


def test_known_dependency_counts_are_asserted_before_delete() -> None:
    sql = sql_text()

    for marker in (
        "expected 8 review slots",
        "expected 4 blind submissions",
        "expected 4 consensus rows",
        "expected 4 gme jobs",
        "expected 4 gme runs",
        "unexpected loose or labeling references",
    ):
        assert marker in sql


def test_only_specific_append_only_triggers_are_temporarily_disabled() -> None:
    sql = sql_text()

    assert "DISABLE TRIGGER trg_block_motion_blind_submission_mutation" in sql
    assert "DISABLE TRIGGER trg_block_gme_run_delete" in sql
    assert "ENABLE TRIGGER trg_block_motion_blind_submission_mutation" in sql
    assert "ENABLE TRIGGER trg_block_gme_run_delete" in sql
    assert "DISABLE TRIGGER USER" not in sql


def test_fk_safe_delete_order_and_final_zero_assertion() -> None:
    sql = sql_text().lower()

    consensus = sql.index("delete from public.motion_clip_consensus")
    submissions = sql.index("delete from public.motion_clip_blind_submissions")
    slots = sql.index("delete from public.motion_clip_review_slots")
    runs = sql.index("delete from public.gme_runs")
    jobs = sql.index("delete from public.gme_jobs")
    clips = sql.index("delete from public.motion_clips")
    assert consensus < submissions < slots < clips
    assert runs < jobs < clips
    assert "exact purge postcondition failed" in sql


def test_sql_never_performs_r2_or_prefix_delete() -> None:
    sql = sql_text().lower()

    assert "delete_object" not in sql
    assert "delete_objects" not in sql
    assert "like 'test/%'" not in sql

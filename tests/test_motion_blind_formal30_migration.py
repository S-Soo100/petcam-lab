"""Formal Blind30 exact reservation migration contract."""

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "2026-07-31_motion_blind_formal30.sql"
)


def migration_sql() -> str:
    return MIGRATION.read_text()


def test_formal30_migration_has_exact_atomic_contract() -> None:
    sql = migration_sql()
    normalized = " ".join(sql.split())
    assert "fn_create_motion_blind_formal30" in sql
    assert "array_length(p_clip_ids, 1) <> 30" in sql
    assert "count(DISTINCT clip_id) FROM" in normalized
    assert ") <> 30 THEN" in normalized
    assert "array_length(p_reviewer_ids, 1) <> 2" in sql
    assert "b30v1:" in sql
    assert "cohort_kind = 'canary'" in sql
    assert "v_slot_count <> 60" in sql
    assert "v_consensus_count <> 30" in sql
    assert "GRANT EXECUTE" in sql and "TO service_role" in sql
    assert "FROM PUBLIC, anon, authenticated" in sql
    assert "SECURITY INVOKER SET search_path = ''" in normalized


def test_formal30_revalidates_reviewer_tutorial_contract() -> None:
    sql = migration_sql()
    assert "labelers" in sql
    assert "labeler_applications" in sql
    assert "motion_labeling_review_group_members" in sql
    assert "labeling_tutorial_sets" in sql
    assert "labeling_tutorial_progress" in sql
    assert "labeling_tutorial_attempts" in sql
    assert "current_run_no" in sql
    assert "waived_at IS NULL" in sql
    assert "count(DISTINCT tl.position) = 5" in sql
    assert "p_actor_id = ANY(p_reviewer_ids)" in sql


def test_formal30_revalidates_clip_eligibility_without_rewriting_history() -> None:
    sql = migration_sql()
    assert "fn_motion_blind_clip_is_labelable" in sql
    assert "started_at < p_selection_t0" in sql
    assert "r2_key IS NOT NULL" in sql
    assert "motion_clip_system_exclusions" in sql
    assert "labeling_tutorial_lessons" in sql
    assert "motion_clip_blind_submissions" in sql
    assert "motion_clip_labeling_sessions" in sql
    assert "status IN ('agreed','conflict','owner_resolved')" in sql
    assert "cohort_kind = 'canary'" in sql

    upper = sql.upper()
    assert "DELETE FROM PUBLIC.MOTION_CLIP_REVIEW_SLOTS" not in upper
    assert "DELETE FROM PUBLIC.MOTION_CLIP_BLIND_SUBMISSIONS" not in upper
    assert "DELETE FROM PUBLIC.MOTION_CLIP_CONSENSUS" not in upper
    assert "UPDATE PUBLIC.MOTION_CLIP_CONSENSUS" not in upper
    assert "ON CONFLICT DO NOTHING" not in upper


def test_formal30_function_signature_is_exact() -> None:
    normalized = " ".join(migration_sql().split())
    assert (
        "public.fn_create_motion_blind_formal30( "
        "p_actor_id uuid, p_group_id uuid, p_clip_ids uuid[], "
        "p_reviewer_ids uuid[], p_manifest_sha256 text, "
        "p_selection_t0 timestamptz ) RETURNS uuid"
    ) in normalized
    assert (
        "public.fn_create_motion_blind_formal30( "
        "uuid, uuid, uuid[], uuid[], text, timestamptz )"
    ) in normalized

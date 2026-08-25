from pathlib import Path


MIGRATION = Path("migrations/2026-08-25_motion_clip_gme_unified_feedback_events.sql")
LEGACY_MIGRATION = Path("migrations/2026-08-25_motion_clip_gme_miss_events.sql")
BAD_BOX_MIGRATION = Path("migrations/2026-08-25_z_motion_clip_gme_bad_box_feedback.sql")


def test_feedback_events_are_private_append_only_and_kind_scoped() -> None:
    assert MIGRATION.is_file(), "GME feedback-event migration is missing"
    sql = MIGRATION.read_text().lower()

    assert "create table public.motion_clip_gme_feedback_events" in sql
    assert "feedback_kind text not null" in sql
    assert "'miss','false_positive'" in sql
    assert "surface text not null" in sql
    assert "'blind_live','blind_canary','owner_direct'" in sql
    assert "gme_run_id uuid not null references public.gme_runs" in sql
    assert "before update or delete" in sql
    assert "before truncate" in sql
    assert "enable row level security" in sql
    assert "revoke all on public.motion_clip_gme_feedback_events" in sql
    assert "from public, anon, authenticated, service_role" in sql
    assert "create policy" not in sql


def test_feedback_rpc_revalidates_blind_scope_and_current_run() -> None:
    sql = MIGRATION.read_text().lower()

    assert "create function public.fn_append_motion_clip_gme_feedback" in sql
    assert "security definer" in sql
    assert "motion_clip_review_slots" in sql
    assert "motion_blind_review_cohorts" in sql
    assert "p_surface = 'owner_direct'" in sql
    assert "j.status = 'succeeded'" in sql
    assert "overlay_changed" in sql
    assert "round(p_timestamp_sec, 3)" in sql
    assert "on conflict on constraint uq_motion_clip_gme_feedback_digest" in sql
    assert "to service_role" in sql
    assert "to authenticated" not in sql


def test_legacy_miss_rows_are_migrated_and_legacy_writer_is_retired() -> None:
    sql = MIGRATION.read_text().lower()

    assert LEGACY_MIGRATION.is_file()
    assert MIGRATION.name > LEGACY_MIGRATION.name
    assert "from public.motion_clip_gme_miss_events" in sql
    assert "'miss'::text" in sql
    assert "when legacy.cohort_kind = 'canary' then 'blind_canary'" in sql
    assert "drop function public.fn_append_motion_clip_gme_miss" in sql
    assert "구 미탐 원장은 읽기 전용 archive" in sql


def test_bad_box_feedback_is_added_forward_only_without_rewriting_history() -> None:
    assert BAD_BOX_MIGRATION.is_file(), "bad-box forward migration is missing"
    assert BAD_BOX_MIGRATION.name > MIGRATION.name
    sql = BAD_BOX_MIGRATION.read_text().lower()

    assert "drop constraint motion_clip_gme_feedback_events_feedback_kind_check" in sql
    assert "'miss','false_positive','bad_box'" in sql
    assert "create or replace function public.fn_append_motion_clip_gme_feedback" in sql
    assert "p_feedback_kind not in ('miss','false_positive','bad_box')" in sql
    assert "security definer" in sql
    assert "to service_role" in sql

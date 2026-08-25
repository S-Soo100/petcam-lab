from pathlib import Path


MIGRATION = Path("migrations/2026-08-25_motion_clip_gme_miss_events.sql")
PROBE = Path("tests/sql/motion_clip_gme_miss_events_probe.sql")


def test_miss_events_are_private_append_only_and_bound_to_gme_run() -> None:
    assert MIGRATION.is_file(), "GME miss-event migration is missing"
    sql = MIGRATION.read_text().lower()

    assert "create table public.motion_clip_gme_miss_events" in sql
    assert "gme_run_id uuid not null references public.gme_runs" in sql
    assert "detector_identity text not null" in sql
    assert "permanent_artifact_sha256 text not null" in sql
    assert "before update or delete" in sql
    assert "before truncate" in sql
    assert "enable row level security" in sql
    assert "revoke all on public.motion_clip_gme_miss_events" in sql
    assert "from public, anon, authenticated, service_role" in sql
    assert "grant select, insert on public.motion_clip_gme_miss_events" not in sql
    assert "create policy" not in sql


def test_append_rpc_revalidates_slot_current_run_and_timestamp() -> None:
    sql = MIGRATION.read_text().lower()

    assert "create function public.fn_append_motion_clip_gme_miss" in sql
    assert "security definer" in sql
    assert "motion_clip_review_slots" in sql
    assert "motion_blind_review_cohorts" in sql
    assert "j.status = 'succeeded'" in sql
    assert "j.result_run_id = r.id" in sql
    assert "order by j.completed_at desc nulls last, j.id desc" in sql
    assert "overlay_changed" in sql
    assert "timestamp_sec" in sql
    assert "round(p_timestamp_sec, 3)" in sql
    assert "unique (digest)" in sql
    assert "on conflict on constraint uq_motion_clip_gme_miss_event_digest" in sql
    assert "e.cohort_id is not distinct from p_cohort_id" in sql
    assert "to service_role" in sql
    assert "to authenticated" not in sql


def test_append_rpc_uses_core_sha256_without_extension_ddl() -> None:
    sql = MIGRATION.read_text().lower()

    assert "create extension" not in sql
    assert "public.digest(" not in sql
    assert "encode(sha256(convert_to(" in sql


def test_runtime_probe_covers_idempotency_scope_staleness_and_append_only() -> None:
    assert PROBE.is_file(), "GME miss-event runtime probe is missing"
    sql = PROBE.read_text().lower()

    for marker in (
        "miss_append_ok",
        "miss_duplicate_idempotent_ok",
        "miss_other_timestamp_ok",
        "miss_scope_distinct_ok",
        "miss_service_rpc_ok",
        "miss_service_direct_insert_blocked",
        "miss_wrong_reviewer_rejected",
        "miss_stale_overlay_rejected",
        "miss_canary_closed_rejected",
        "miss_update_blocked",
        "miss_delete_blocked",
        "miss_truncate_blocked",
        "gme_miss_events_runtime_probe_ok",
    ):
        assert marker in sql

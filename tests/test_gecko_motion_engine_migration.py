from pathlib import Path


SQL = Path("migrations/2026-08-03_gecko_motion_engine_shadow.sql").read_text()


def test_base_migration_creates_independent_queue_and_append_only_ledger():
    assert "create table public.gme_jobs" in SQL
    assert "create table public.gme_runs" in SQL
    assert "unique (clip_id, engine_schema_version, algorithm_version, detector_identity)" in SQL
    assert "fn_block_gme_run_mutation" in SQL
    assert "before update on public.gme_runs" in SQL
    assert "before delete on public.gme_runs" in SQL
    assert "before truncate on public.gme_runs" in SQL


def test_base_migration_is_service_role_only_and_rls_policy_zero():
    assert "alter table public.gme_jobs enable row level security" in SQL
    assert "alter table public.gme_runs enable row level security" in SQL
    assert "revoke all on public.gme_jobs from public, anon, authenticated" in SQL
    assert "revoke all on public.gme_runs from public, anon, authenticated" in SQL
    assert "grant all on public.gme_jobs to service_role" in SQL
    assert "grant all on public.gme_runs to service_role" in SQL
    assert "create policy" not in SQL.lower()


def test_base_migration_has_live_first_lease_queue_and_allowlists():
    assert "source in ('smoke','live','historical')" in SQL
    assert "status in ('queued','processing','succeeded','failed_retryable','failed_terminal')" in SQL
    assert "order by priority desc, created_at asc, id asc" in SQL
    assert "for update skip locked" in SQL
    assert "lease_expires_at < p_now" in SQL
    assert "attempt_count < max_attempts" in SQL
    assert "attempt_count >= max_attempts" in SQL
    assert "claimed_by=null" in SQL
    for code in (
        "r2_download_failed", "source_media_missing", "r2_access_denied", "decode_no_frames",
        "invalid_metadata", "detector_failed", "gme_compute_failed", "artifact_upload_failed",
        "db_transient", "internal_error",
    ):
        assert f"'{code}'" in SQL


def test_base_migration_validates_bounded_json_and_cross_job_completion():
    assert "jsonb_array_length(state_intervals) <= 10000" in SQL
    assert "jsonb_typeof" in SQL
    assert "run does not belong to job" in SQL
    assert "run payload does not match job" in SQL
    assert "permanent_artifact_sha256" in SQL
    assert "debug_artifact_sha256" in SQL
    assert "candidate_moving_sec_any_gecko <= visible_sec" in SQL
    assert "moving_gecko_seconds >= candidate_moving_sec_any_gecko" in SQL
    assert "visible_sec + unknown_sec + camera_motion_sec <= duration_sec" in SQL


def test_base_migration_has_no_live_trigger_or_python_evidence_mutation():
    lowered = SQL.lower()
    assert "create trigger trg_enqueue_gme_live_job" not in lowered
    assert "drop trigger" not in lowered
    assert "python_evidence_jobs" not in lowered
    assert "clip_python_evidence_runs" not in lowered
    assert "fn_enqueue_gme_jobs" in SQL

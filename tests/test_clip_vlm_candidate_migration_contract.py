from pathlib import Path


SQL = Path("migrations/2026-07-15_clip_vlm_candidate_jobs.sql")


def test_vlm_job_migration_contains_safety_contracts():
    text = SQL.read_text().lower()
    required = [
        "unique (camera_id, window_start, selector_version)",
        "unique (clip_id, selector_version)",
        "unique (selector_run_id, slot)",
        "jsonb_array_length(p_jobs) > 4",
        "fn_create_clip_vlm_selector_run",
        "fn_reserve_clip_vlm_job",
        "pg_advisory_xact_lock",
        "owner reads own vlm selector runs",
        "owner reads own vlm jobs",
        "revoke all on public.clip_vlm_jobs from anon, authenticated",
    ]
    assert all(item in text for item in required)


def test_vlm_job_status_and_slot_enums_are_closed():
    text = SQL.read_text().lower()
    for value in ("held_model_mismatch", "held_budget", "customer_highlight", "exclusion_audit"):
        assert value in text

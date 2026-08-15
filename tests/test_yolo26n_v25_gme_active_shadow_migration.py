from pathlib import Path


MIGRATION = Path("migrations/2026-08-15_yolo26n_v25_gme_active_shadow.sql")
V25_SHA = "2b128f105e898bc472ed66861583ab80007dae6e94b291db497d7a2f8081f84a"
OLD_SHA = "7997e853e851ac6592e03d13e7d5098ebfcbcb49b408077d83d7d6359df60a2a"


def _sql() -> str:
    return MIGRATION.read_text()


def test_v25_live_transition_requires_ten_matching_smoke_runs():
    sql = _sql().lower()
    assert "smoke_complete < 10" in sql
    assert "j.source = 'smoke'" in sql
    assert "j.status = 'succeeded'" in sql
    assert f"j.detector_identity = '{V25_SHA}'" in sql
    assert "j.result_run_id = r.id" in sql


def test_v25_live_enqueue_is_production_only_and_uses_append_only_identity():
    sql = _sql().lower()
    assert "new.clip_purpose <> 'production'" in sql
    assert "'gme-shadow-v1'" in sql
    assert "'gme-motion-v0'" in sql
    assert f"'{V25_SHA}'" in sql
    assert "on conflict (clip_id, engine_schema_version, algorithm_version, detector_identity) do nothing" in sql


def test_v25_transition_preserves_existing_jobs_runs_and_original_media():
    sql = _sql().lower()
    for forbidden in (
        "delete from public.gme_jobs",
        "delete from public.gme_runs",
        "update public.gme_jobs",
        "update public.gme_runs",
        "delete from public.motion_clips",
        "update public.motion_clips",
        "truncate",
        "drop table",
    ):
        assert forbidden not in sql


def test_v25_transition_documents_exact_old_identity_rollback():
    sql = _sql().lower()
    assert "rollback contract" in sql
    assert f"'{OLD_SHA}'" in sql
    assert "gme history remains append-only" in sql

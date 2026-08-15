from pathlib import Path


MIGRATION = Path("migrations/2026-08-15_yolo26n_v25_gme_active_shadow.sql")
V25_IDENTITY = "d4654168af21d26697ab1bd9a5dc4a05bd92baf5c9328800915cc347803d05b6"
OLD_SHA = "7997e853e851ac6592e03d13e7d5098ebfcbcb49b408077d83d7d6359df60a2a"


def _sql() -> str:
    return MIGRATION.read_text()


def test_v25_live_transition_requires_ten_matching_smoke_runs():
    sql = _sql().lower()
    assert "smoke_complete < 10" in sql
    assert "j.source = 'smoke'" in sql
    assert "j.status = 'succeeded'" in sql
    assert f"j.detector_identity = '{V25_IDENTITY}'" in sql
    assert "j.result_run_id = r.id" in sql


def test_v25_live_enqueue_is_production_only_and_uses_append_only_identity():
    sql = _sql().lower()
    assert "new.clip_purpose <> 'production'" in sql
    assert "'gme-shadow-v1'" in sql
    assert "'gme-motion-v0'" in sql
    assert f"'{V25_IDENTITY}'" in sql
    assert "on conflict (clip_id, engine_schema_version, algorithm_version, detector_identity) do nothing" in sql


def test_v25_transition_preserves_existing_jobs_runs_and_original_media():
    sql = _sql().lower()
    for forbidden in (
        "delete from public.gme_jobs",
        "delete from public.gme_runs",
        "update public.gme_runs",
        "delete from public.motion_clips",
        "update public.motion_clips",
        "truncate",
        "drop table",
    ):
        assert forbidden not in sql
    assert sql.count("update public.gme_jobs") == 1


def test_v25_transition_documents_exact_old_identity_rollback():
    sql = _sql().lower()
    assert "rollback contract" in sql
    assert f"'{OLD_SHA}'" in sql
    assert "gme history remains append-only" in sql


def test_v25_transition_requeues_only_the_bounded_wrong_worker_incident():
    sql = _sql().lower()
    assert "wrong_worker_claims <> 10" in sql
    assert "j.source = 'historical'" in sql
    assert f"j.detector_identity = '{V25_IDENTITY}'" in sql
    assert "j.result_run_id is null" in sql
    assert "j.attempt_count = 1" in sql
    assert "j.status in ('processing','failed_terminal')" in sql
    assert "j.failure_code is null or j.failure_code = 'gme_compute_failed'" in sql
    assert "set status = 'queued'" in sql
    assert "attempt_count = 0" in sql

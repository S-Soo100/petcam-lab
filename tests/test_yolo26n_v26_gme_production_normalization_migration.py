from pathlib import Path


MIGRATION = Path("migrations/2026-08-31_yolo26n_v26_gme_production_normalization.sql")
V25_IDENTITY = "d4654168af21d26697ab1bd9a5dc4a05bd92baf5c9328800915cc347803d05b6"
V26_IDENTITY = "89e4738a60ebb71900e05e96f5b7262e8b900f5c9bba9b9cb9e34fca36f789b7"


def _sql() -> str:
    return MIGRATION.read_text().lower()


def test_v26_live_transition_requires_exact_recovery_smoke_and_current_v25_function():
    sql = _sql()
    assert "smoke_total <> 20" in sql
    assert "smoke_terminal_invalid <> 10" in sql
    assert "smoke_complete <> 10" in sql
    assert "smoke_other <> 0" in sql
    assert "smoke_unique_clips <> 20" in sql
    assert "j.source = 'smoke'" in sql
    assert "j.status = 'succeeded'" in sql
    assert "j.status = 'failed_terminal'" in sql
    assert "j.failure_code = 'invalid_metadata'" in sql
    assert "j.result_run_id is null" in sql
    assert "r.status = 'ok'" in sql
    assert f"j.detector_identity = '{V26_IDENTITY}'" in sql
    assert f"'{V25_IDENTITY}'" in sql
    assert "in current_function" in sql


def test_v26_live_enqueue_is_production_only_and_append_only():
    sql = _sql()
    assert "new.clip_purpose <> 'production'" in sql
    assert "new.id, 'live', 100, 'gme-shadow-v1', 'gme-motion-v0'" in sql
    assert f"'{V26_IDENTITY}'" in sql
    assert "on conflict (clip_id, engine_schema_version, algorithm_version, detector_identity) do nothing" in sql
    for forbidden in (
        "delete from public.gme_jobs",
        "delete from public.gme_runs",
        "update public.gme_runs",
        "update public.gme_jobs",
        "delete from public.motion_clips",
        "update public.motion_clips",
        "truncate public.gme_jobs",
        "drop table public.gme_jobs",
    ):
        assert forbidden not in sql


def test_rate_limit_rpc_serializes_hashed_keys_and_is_service_role_only():
    sql = _sql()
    signature = "public.fn_consume_yolo_demo_rate_limit(text,timestamptz,integer,integer)"
    assert "create table public.yolo_demo_rate_limits" in sql
    assert "check (key_hash ~ '^[0-9a-f]{64}$')" in sql
    assert "pg_advisory_xact_lock(hashtextextended(p_key_hash, 0))" in sql
    assert "p_now - interval '24 hours'" in sql
    assert "limit 100" in sql
    assert f"revoke all on function {signature} from public, anon, authenticated" in sql
    assert f"grant execute on function {signature} to service_role" in sql
    assert "grant select, insert, update, delete on table public.yolo_demo_rate_limits to service_role" in sql


def test_rate_limit_rpc_returns_allowed_and_retry_contract():
    sql = _sql()
    assert "'allowed', true" in sql
    assert "'allowed', false" in sql
    assert "'retry_after_sec', 0" in sql
    assert "ceil(extract(epoch from" in sql

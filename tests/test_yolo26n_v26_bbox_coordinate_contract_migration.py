import re
from pathlib import Path


MIGRATION = Path("migrations/2026-09-01_yolo26n_v26_bbox_coordinate_contract.sql")
OLD_IDENTITY = "89e4738a60ebb71900e05e96f5b7262e8b900f5c9bba9b9cb9e34fca36f789b7"
NEW_IDENTITY = "deccfc8315d3c00edb5bf59db3c573dca568e9d6d7a5da8d7dc93d2082bdb899"


def _sql() -> str:
    return MIGRATION.read_text().lower()


def test_bbox_contract_transition_requires_the_previous_live_identity():
    sql = _sql()
    assert "pg_get_functiondef('public.fn_enqueue_gme_live_job()'::regprocedure)" in sql
    assert "gme_trigger_count <> 1" in sql
    assert "tgfoid = 'public.fn_enqueue_gme_live_job()'::regprocedure" in sql
    assert "tgenabled = 'o'" in sql
    assert re.search(r"regexp_count\(\s*current_function", sql)
    assert f"'{OLD_IDENTITY}'" in sql
    assert "in current_function" in sql


def test_bbox_contract_transition_revalidates_identity_isolated_claim_body():
    sql = _sql()
    assert "pg_get_functiondef(to_regprocedure(" in sql
    assert re.search(r"regexp_count\(\s*claim_function", sql)
    assert "detector_identity\\s*=\\s*p_detector_identity" in sql
    assert "attempt_count >= max_attempts" in sql
    assert "attempt_count < max_attempts" in sql
    assert "for update skip locked" in sql
    assert "p_include_historical or c.source <> ''historical''" in sql
    assert "p_now + interval ''30 minutes''" in sql


def test_bbox_contract_transition_is_append_only_and_selects_new_identity():
    sql = _sql()
    assert "new.clip_purpose <> 'production'" in sql
    assert f"'{NEW_IDENTITY}'" in sql
    assert "on conflict (clip_id, engine_schema_version, algorithm_version, detector_identity) do nothing" in sql
    for forbidden in (
        "delete from public.gme_jobs",
        "delete from public.gme_runs",
        "update public.gme_jobs",
        "update public.gme_runs",
        "truncate public.gme_jobs",
        "truncate public.gme_runs",
        "drop table public.gme_jobs",
        "drop table public.gme_runs",
    ):
        assert forbidden not in sql


def test_bbox_contract_live_enqueue_remains_service_role_only():
    sql = _sql()
    signature = "public.fn_enqueue_gme_live_job()"
    assert f"revoke all on function {signature} from public, anon, authenticated" in sql
    assert f"grant execute on function {signature} to service_role" in sql

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "migrations/2026-09-03_gme_slow_motion_v1_contract.sql"
CUTOVER = ROOT / "migrations/2026-09-03_gme_slow_motion_v1_live_cutover.sql"
STATS = ROOT / "migrations/2026-09-03_gme_contract_operational_stats.sql"


def test_contract_migration_is_exact_and_does_not_cut_over_live_jobs() -> None:
    sql = CONTRACT.read_text()
    assert "fn_claim_gme_jobs_for_contract" in sql
    assert "fn_get_gme_observed_moving_time_v2" in sql
    assert sql.count("algorithm_version = p_algorithm_version") >= 5
    assert sql.count("detector_identity = p_detector_identity") >= 5
    assert "engine_schema_version = p_engine_schema_version" in sql
    assert "fn_enqueue_gme_live_job" not in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql


def test_live_cutover_changes_only_new_jobs_to_v1() -> None:
    sql = CUTOVER.read_text()
    assert "create or replace function public.fn_enqueue_gme_live_job" in sql
    assert "'gme-shadow-v1', 'gme-motion-v1'" in sql
    assert "on conflict (clip_id, engine_schema_version, algorithm_version, detector_identity) do nothing" in sql
    assert "delete from" not in sql.lower()
    assert "update public.gme_jobs" not in sql.lower()


def test_operational_stats_are_filtered_by_the_exact_contract() -> None:
    sql = STATS.read_text()
    assert "fn_gme_operational_stats_for_contract" in sql
    assert "detector_identity = p_detector_identity" in sql
    assert "algorithm_version = p_algorithm_version" in sql
    assert "engine_schema_version = p_engine_schema_version" in sql
    assert "oldest_live_age_sec" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql

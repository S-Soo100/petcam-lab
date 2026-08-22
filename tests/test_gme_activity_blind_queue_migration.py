from pathlib import Path


SQL = Path("migrations/2026-08-22_gme_activity_blind_queue.sql").read_text().lower()
PREREQUISITES = Path("tests/sql/gme_activity_blind_queue_prerequisites.sql")


def test_live_queue_orders_gme_detected_then_activity_without_filtering_absent() -> None:
    assert "left join lateral public.fn_current_gme_activity(m.id)" in SQL
    assert "order by rank_detected desc, rank_activity_sec desc" in SQL
    assert "where gme.detected" not in SQL
    assert "rank_detected boolean" in SQL
    assert "rank_activity_sec numeric" in SQL


def test_canary_keeps_frozen_time_order() -> None:
    assert "case when p_cohort_kind = 'live'" in SQL


def test_disposable_probe_bootstraps_blind_and_gme_dependencies() -> None:
    sql = PREREQUISITES.read_text().lower()
    assert "\\ir migrations/2026-07-23_motion_double_blind_labeling.sql" in sql
    assert "add column clip_purpose" in sql
    assert "fn_is_motion_clip_production_labeling_eligible" in sql
    assert "create table public.gme_jobs" in sql
    assert "create table public.gme_runs" in sql

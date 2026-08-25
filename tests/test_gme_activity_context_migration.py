from pathlib import Path


SQL = Path("migrations/2026-08-22_gme_activity_blind_queue.sql").read_text().lower()


def test_current_gme_activity_uses_only_completed_success_result_pointer() -> None:
    assert "create function public.fn_current_gme_activity" in SQL
    assert "j.status = 'succeeded'" in SQL
    assert "r.id = j.result_run_id" in SQL
    assert "r.status = 'ok'" in SQL
    assert "order by j.completed_at desc nulls last, j.id desc" in SQL


def test_detection_requires_visibility_and_gecko_count() -> None:
    assert "r.visible_sec > 0 and r.max_simultaneous_geckos > 0" in SQL
    assert "security invoker" in SQL
    assert "to service_role" in SQL
    assert "to authenticated" not in SQL

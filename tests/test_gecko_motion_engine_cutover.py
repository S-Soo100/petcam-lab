from pathlib import Path


SQL = Path("migrations/2026-08-03_gecko_motion_engine_direct_cutover.sql").read_text()


def test_cutover_requires_smoke_and_zero_legacy_processing_jobs():
    assert "smoke_complete < 10" in SQL
    assert "source='smoke'" in SQL
    assert "status='processing'" in SQL
    assert "cutover preflight failed" in SQL


def test_cutover_creates_one_gme_trigger_and_removes_only_legacy_enqueue_trigger():
    assert "create trigger trg_enqueue_gme_live_job" in SQL
    assert "after insert on public.motion_clips" in SQL
    assert "drop trigger trg_enqueue_python_evidence_job on public.motion_clips" in SQL
    assert "drop table" not in SQL.lower()
    assert "delete from" not in SQL.lower()
    assert "truncate" not in SQL.lower()


def test_cutover_pins_approved_engine_and_detector_identity():
    assert "'gme-shadow-v1'" in SQL
    assert "'gme-motion-v0'" in SQL
    assert "'7997e853e851ac6592e03d13e7d5098ebfcbcb49b408077d83d7d6359df60a2a'" in SQL


def test_cutover_documents_exact_reversible_trigger_rollback_without_deleting_history():
    assert "ROLLBACK CONTRACT" in SQL
    assert "drop trigger if exists trg_enqueue_gme_live_job on public.motion_clips" in SQL
    assert "create trigger trg_enqueue_python_evidence_job" in SQL
    assert "GME history remains append-only" in SQL

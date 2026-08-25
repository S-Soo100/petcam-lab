from pathlib import Path


MIGRATION = Path(
    "migrations/2026-08-25_gme_negative_audit_close_completion_guard.sql"
)


def test_close_guard_is_a_forward_migration_that_blocks_incomplete_batches() -> None:
    assert MIGRATION.is_file(), "close completion guard forward migration is missing"
    sql = MIGRATION.read_text().lower()

    assert (
        "create or replace function public.fn_validate_gme_negative_audit_batch_event()"
        in sql
    )
    assert "new.event_type = 'closed'" in sql
    assert "batch.expected_total_count" in sql
    assert "gme_negative_audit_items" in sql
    assert "gme_negative_audit_submissions" in sql
    assert "batch_incomplete" in sql
    assert "errcode = 'pt409'" in sql
    assert "for update" in sql

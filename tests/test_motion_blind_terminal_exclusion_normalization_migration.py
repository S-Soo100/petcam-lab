"""삭제된 media의 기존 blind slot이 큐·workspace에 재노출되지 않는 계약."""

from pathlib import Path


SQL_PATH = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "2026-07-28_motion_blind_terminal_exclusion_normalization.sql"
)


def _sql() -> str:
    return SQL_PATH.read_text().lower() if SQL_PATH.exists() else ""


def test_forward_migration_replaces_blind_queue_and_workspace() -> None:
    sql = _sql()

    assert SQL_PATH.exists(), "terminal exclusion normalization migration is missing"
    assert "create or replace function public.fn_list_motion_blind_queue" in sql
    assert "create or replace function public.fn_get_motion_blind_workspace" in sql


def test_queue_and_workspace_exclude_only_terminal_system_states() -> None:
    sql = _sql()
    predicate = "sx.state in ('quarantined','media_deleted')"

    assert sql.count(predicate) >= 9
    assert "candidate" not in sql
    assert "restored" not in sql
    assert "deletion_blocked" not in sql


def test_forward_migration_preserves_data_and_service_role_boundary() -> None:
    sql = _sql()

    assert "delete from public.motion_clip_review_slots" not in sql
    assert "delete from public.motion_clip_consensus" not in sql
    assert "update public.motion_clip_review_slots" not in sql
    assert "update public.motion_clip_consensus" not in sql
    assert sql.count("from public, anon, authenticated") == 2
    assert sql.count("to service_role") == 2


def test_runtime_probe_applies_normalization_last_and_asserts_stale_slots() -> None:
    root = Path(__file__).resolve().parent.parent
    runner = (root / "scripts" / "run_short_clip_retention_probe.py").read_text()
    probe = (root / "tests" / "sql" / "short_clip_device_error_retention_probe.sql").read_text()

    assert runner.index("2026-07-27_motion_blind_workspace_runtime_fix.sql") < runner.index(
        "2026-07-28_motion_blind_terminal_exclusion_normalization.sql"
    )
    assert "SHORT_CLIP_BLIND_TERMINAL_NORMALIZATION_OK" in runner
    assert "SHORT_CLIP_BLIND_TERMINAL_NORMALIZATION_OK" in probe
    assert "media_deleted clip remained in blind queue" in probe
    assert "workspace clip_total includes terminal clip" in probe

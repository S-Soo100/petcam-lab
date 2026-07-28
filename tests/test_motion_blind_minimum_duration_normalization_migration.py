"""blind 라벨링 큐·workspace가 50초 이상 영상만 노출하는 계약."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SQL_PATH = (
    ROOT
    / "migrations"
    / "2026-07-28_motion_blind_minimum_duration_normalization.sql"
)


def _sql() -> str:
    return SQL_PATH.read_text().lower() if SQL_PATH.exists() else ""


def test_forward_migration_replaces_queue_and_workspace_with_shared_eligibility() -> None:
    sql = _sql()

    assert SQL_PATH.exists(), "minimum duration normalization migration is missing"
    assert "create or replace function public.fn_motion_blind_clip_is_labelable" in sql
    assert "m.duration_sec >= 50" in sql
    assert "m.camera_id not in" in sql
    assert "f6599924-d133-4562-a48c-a06ff59db29d" in sql
    assert "90119209-4cdf-46f0-a151-c16d2445a1f1" in sql
    assert "sx.state in ('quarantined','media_deleted')" in sql
    assert "create or replace function public.fn_list_motion_blind_queue" in sql
    assert "create or replace function public.fn_get_motion_blind_workspace" in sql
    assert sql.count("public.fn_motion_blind_clip_is_labelable(") >= 12


def test_duration_filter_is_scoped_to_group_b_cameras() -> None:
    sql = _sql()
    scope_start = sql.index("m.camera_id not in")
    scope_end = sql.index("or m.duration_sec >= 50")

    assert scope_start < scope_end
    assert sql.count("m.duration_sec >= 50") == 1


def test_forward_migration_preserves_rows_and_service_role_boundary() -> None:
    sql = _sql()

    assert "delete from public.motion_clip_review_slots" not in sql
    assert "delete from public.motion_clip_consensus" not in sql
    assert "update public.motion_clip_review_slots" not in sql
    assert "update public.motion_clip_consensus" not in sql
    assert sql.count("from public, anon, authenticated") == 3
    assert sql.count("to service_role") == 3


def test_runtime_probe_applies_duration_normalization_last() -> None:
    runner = (ROOT / "scripts" / "run_short_clip_retention_probe.py").read_text()
    probe = (ROOT / "tests" / "sql" / "short_clip_device_error_retention_probe.sql").read_text()

    assert runner.index(
        "2026-07-28_motion_blind_terminal_exclusion_normalization.sql"
    ) < runner.index("2026-07-28_motion_blind_minimum_duration_normalization.sql")
    assert "SHORT_CLIP_BLIND_MIN_DURATION_OK" in runner
    assert "SHORT_CLIP_BLIND_MIN_DURATION_OK" in probe
    assert "under-50 clip remained in blind queue" in probe
    assert "labelable 60s clip missing from blind queue" in probe
    assert "other camera under-50 clip was filtered" in probe
    assert "workspace clip_total includes under-50 clip" in probe

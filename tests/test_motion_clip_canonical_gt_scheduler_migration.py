"""Supabase pg_cron canonical GT scheduler 정적 안전 계약."""

from pathlib import Path

import pytest


SQL_PATH = Path("migrations/2026-08-04_motion_clip_canonical_gt_scheduler.sql")


@pytest.fixture
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8").lower()


def test_scheduler_requires_existing_pg_cron_and_defaults_disabled(sql: str) -> None:
    assert "from pg_catalog.pg_extension" in sql
    assert "extname = 'pg_cron'" in sql
    assert "pg_cron_required" in sql
    assert "enabled boolean not null default false" in sql
    assert "insert into public.motion_clip_gt_projection_config" in sql
    assert "false" in sql


def test_scheduler_is_separate_from_blind_writers(sql: str) -> None:
    assert "fn_run_motion_clip_canonical_gt_schedule" in sql
    assert "fn_project_motion_clip_canonical_gt" in sql
    for forbidden in (
        "fn_submit_motion_blind_review",
        "fn_resolve_motion_blind_consensus",
        "update public.motion_clip_consensus",
        "update public.motion_clip_labeling_sessions",
    ):
        assert forbidden not in sql


def test_scheduler_job_is_named_idempotent_and_ten_minute(sql: str) -> None:
    assert "canonical-motion-gt-projector-v1" in sql
    assert "*/10 * * * *" in sql
    assert "cron.schedule" in sql
    assert "select public.fn_run_motion_clip_canonical_gt_schedule()" in sql


def test_config_and_scheduler_rpcs_are_service_role_only(sql: str) -> None:
    assert "enable row level security" in sql
    assert (
        "revoke all on table public.motion_clip_gt_projection_config "
        "from public, anon, authenticated"
    ) in sql
    for signature in (
        "fn_configure_motion_clip_gt_projection(uuid, boolean)",
        "fn_run_motion_clip_canonical_gt_schedule()",
    ):
        assert f"revoke all on function public.{signature}" in sql
        assert f"grant execute on function public.{signature}" in sql
    assert "security definer" in sql
    assert "set search_path = ''" in sql


def test_scheduler_records_stable_failure_without_gt_payload(sql: str) -> None:
    assert "projection_schedule_failed" in sql
    assert "fn_record_motion_clip_gt_projection_run" in sql
    assert "final_gt" not in sql
    assert "initial_gt" not in sql
    assert "current_gt" not in sql

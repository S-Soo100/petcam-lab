"""Canonical motion GT ledger forward migration 정적 안전 계약."""

from pathlib import Path
import re

import pytest


SQL_PATH = Path("migrations/2026-08-04_motion_clip_canonical_gt_ledger.sql")


@pytest.fixture
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8").lower()


def test_adds_isolated_append_only_ledger(sql: str) -> None:
    for table in (
        "motion_clip_gt_revisions",
        "motion_clip_gt_heads",
        "motion_clip_gt_reconciliation",
        "motion_clip_gt_projection_runs",
    ):
        assert f"create table public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
        assert f"revoke all on table public.{table} from public, anon, authenticated" in sql
    assert (
        "before update or delete or truncate on public.motion_clip_gt_revisions"
        in sql
    )
    assert (
        "before update or delete or truncate on public.motion_clip_gt_projection_runs"
        in sql
    )


def test_does_not_touch_blind_writers_or_source_rows(sql: str) -> None:
    for forbidden in (
        "create or replace function public.fn_submit_motion_blind_review",
        "create or replace function public.fn_resolve_motion_blind_consensus",
        "update public.motion_clip_consensus",
        "delete from public.motion_clip_consensus",
        "update public.motion_clip_labeling_sessions",
        "delete from public.motion_clip_labeling_sessions",
    ):
        assert forbidden not in sql


def test_projection_excludes_non_final_sources(sql: str) -> None:
    start = sql.index("create or replace function public.fn_project_motion_clip_canonical_gt")
    end = sql.index(
        "create or replace function public.fn_get_motion_clip_canonical_gt", start
    )
    projection = sql[start:end]
    assert "c.cohort_kind = 'live'" in projection
    assert "c.status in ('agreed', 'owner_resolved')" in projection
    assert "c.final_decision in ('label', 'hold', 'exclude')" in projection
    assert "c.cohort_kind = 'canary'" not in projection
    assert "c.status in ('awaiting', 'conflict')" not in projection
    assert "s.reviewed_by = p_owner_id" in projection
    assert "s.stage = 'completed'" in projection


def test_rpc_surface_is_service_role_only(sql: str) -> None:
    signatures = (
        "fn_project_motion_clip_canonical_gt(uuid, boolean, integer, uuid, uuid)",
        "fn_get_motion_clip_canonical_gt(uuid, uuid)",
        "fn_override_motion_clip_canonical_gt(uuid, uuid, uuid, jsonb, text)",
        "fn_resolve_motion_clip_gt_reconciliation(uuid, uuid, uuid, text, jsonb, text)",
        "fn_record_motion_clip_gt_projection_run(uuid, text, integer, integer, text, timestamptz)",
        "fn_get_motion_clip_gt_projection_health()",
        "fn_audit_motion_clip_canonical_gt()",
    )
    for signature in signatures:
        escaped = re.escape(f"public.{signature}")
        assert re.search(
            rf"revoke all on function {escaped}\s+from public, anon, authenticated",
            sql,
        )
        assert re.search(
            rf"grant execute on function {escaped}\s+to service_role",
            sql,
        )
    assert "security definer" in sql
    assert "set search_path = ''" in sql


def test_owner_writes_lock_head_and_use_optimistic_concurrency(sql: str) -> None:
    assert "for update" in sql
    assert "pg_advisory_xact_lock" in sql
    assert "expected_revision_mismatch" in sql
    assert "errcode = 'pt409'" in sql
    assert "reason_required" in sql


def test_projection_is_idempotent_and_does_not_swallow_candidate_errors(sql: str) -> None:
    assert "source_event_key text not null unique" in sql
    assert "on conflict (source_event_key) do nothing" in sql
    assert "exception when others" not in sql
    assert "projection batch is atomic" in sql


def test_canonical_tables_never_reference_ai_or_boundary_sources(sql: str) -> None:
    for forbidden in (
        "clip_vlm_jobs",
        "python_evidence",
        "gecko_vision",
        "router_review",
        "rba_boundary_review",
        "labeling_tutorial",
    ):
        assert forbidden not in sql


def test_health_and_audit_cover_direct_sources_and_real_parity(sql: str) -> None:
    health_start = sql.index("create or replace function public.fn_get_motion_clip_gt_projection_health")
    audit_start = sql.index("create or replace function public.fn_audit_motion_clip_canonical_gt")
    health = sql[health_start:audit_start]
    audit = sql[audit_start:]
    assert "motion_clip_labeling_sessions" in health
    assert "s.stage = 'completed'" in health
    assert "parity_mismatches" in audit
    assert "'parity_mismatch_count', 0" not in audit
    assert "digest(" in audit and "'sha256'" in audit

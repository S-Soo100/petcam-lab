"""사건 경계 검수·팀 대시보드 forward migration 정적 안전 계약."""

from pathlib import Path
import re

import pytest


SQL_PATH = Path("migrations/2026-07-31_rba_boundary_review_dashboard.sql")


@pytest.fixture
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8").lower()


def test_creates_isolated_boundary_domain(sql: str) -> None:
    for table in (
        "rba_boundary_review_cohorts",
        "rba_boundary_review_pairs",
        "rba_boundary_review_assignments",
        "rba_boundary_review_submissions",
        "rba_boundary_review_resolutions",
    ):
        assert f"create table public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
        assert f"revoke all on table public.{table} from public, anon, authenticated" in sql


def test_boundary_decisions_and_roles_are_closed_enums(sql: str) -> None:
    assert "check (decision in ('same_event','different_event','uncertain'))" in sql
    assert "check (reviewer_role in ('owner','peer'))" in sql
    assert "check (split in ('development','holdout'))" in sql
    assert "unique (pair_id, reviewer_id)" in sql
    assert "unique (pair_id, reviewer_role)" in sql


def test_human_answers_are_append_only(sql: str) -> None:
    assert "fn_reject_rba_boundary_history_mutation" in sql
    assert "is append-only" in sql
    assert "errcode = '0a000'" in sql
    for table in (
        "rba_boundary_review_submissions",
        "rba_boundary_review_resolutions",
    ):
        assert f"before update or delete or truncate on public.{table}" in sql


def test_rpc_surface_is_service_role_only(sql: str) -> None:
    functions = (
        "fn_get_rba_boundary_access(uuid)",
        "fn_get_rba_boundary_workspace(uuid)",
        "fn_get_rba_boundary_pair_media(uuid, uuid, text)",
        "fn_submit_rba_boundary_decision(uuid, uuid, text)",
        "fn_list_rba_boundary_conflicts(uuid)",
        "fn_resolve_rba_boundary_conflict(uuid, uuid, text, text)",
        "fn_get_labeling_data_dashboard(uuid)",
        "fn_seed_rba_boundary_review(text, text, uuid, uuid, uuid, jsonb)",
    )
    for signature in functions:
        escaped = re.escape(f"public.{signature}")
        assert re.search(
            rf"revoke all on function {escaped}\s+from public, anon, authenticated",
            sql,
        )
        assert re.search(
            rf"grant execute on function {escaped}\s+to service_role",
            sql,
        )


def test_open_split_and_assignment_are_checked_server_side(sql: str) -> None:
    assert "a.reviewer_id = p_reviewer_id" in sql
    assert "c.status = 'development_open'" in sql
    assert "p.split = 'development'" in sql
    assert "c.status = 'holdout_open'" in sql
    assert "p.split = 'holdout'" in sql
    assert "reviewer_forbidden" in sql
    assert "split_closed" in sql


def test_submit_is_immutable_and_resolution_requires_real_conflict(sql: str) -> None:
    assert "already_submitted" in sql
    assert "on conflict (assignment_id) do nothing" in sql
    assert "bool_or(s.decision = 'uncertain')" in sql
    assert "resolution_reason_required" in sql
    assert "owner_forbidden" in sql


def test_dashboard_reuses_canonical_human_gt_without_ai_outputs(sql: str) -> None:
    assert "motion_clip_consensus" in sql
    assert "motion_clip_labeling_sessions" in sql
    assert "coalesce(s.current_gt, s.initial_gt)" in sql
    assert "reviewed_by = p_owner_id" in sql
    assert "final_decision = 'label'" in sql
    assert "status in ('agreed','owner_resolved')" in sql
    assert "primary_action" in sql
    assert "motion_clip_system_exclusions" in sql
    assert "('quarantined','media_deleted')" in sql
    for forbidden in (
        "clip_vlm",
        "python_evidence",
        "router_review",
        "gecko_vision",
    ):
        assert forbidden not in sql


def test_migration_never_mutates_existing_labeling_domain(sql: str) -> None:
    for table in (
        "motion_clip_review_slots",
        "motion_clip_blind_submissions",
        "motion_clip_consensus",
        "motion_clip_labeling_sessions",
    ):
        assert f"insert into public.{table}" not in sql
        assert f"update public.{table}" not in sql
        assert f"delete from public.{table}" not in sql


def test_seed_rpc_is_atomic_exact120_and_idempotent(sql: str) -> None:
    assert "jsonb_array_length(p_pairs) <> 120" in sql
    assert "v_development_count <> 60 or v_holdout_count <> 60" in sql
    assert "seed_manifest_mismatch" in sql
    assert "seed_partial_state" in sql
    assert "on conflict (experiment_id) do nothing" in sql
    assert "uq_rba_boundary_single_open_cohort" in sql

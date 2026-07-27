"""운영 규모의 blind slot 자재화가 행별 loop로 퇴행하지 않는지 고정한다."""

from pathlib import Path


SQL_PATH = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "2026-07-27_motion_blind_slot_materialization_scale.sql"
)
WORKSPACE_FIX_PATH = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "2026-07-27_motion_blind_workspace_runtime_fix.sql"
)


def _sql() -> str:
    return SQL_PATH.read_text().lower()


def test_forward_migration_replaces_ensure_rpc_with_set_based_inserts() -> None:
    sql = _sql()

    assert "create or replace function public.fn_ensure_motion_review_slots" in sql
    assert "insert into public.motion_clip_consensus" in sql
    assert "insert into public.motion_clip_review_slots" in sql
    assert "cross join unnest(v_members)" in sql
    assert "for v_clip" not in sql


def test_materialization_preserves_group_and_slot_invariants() -> None:
    sql = _sql()

    assert "pg_advisory_xact_lock" in sql
    assert "live clip must have zero or two slots" in sql
    assert "c.group_id = v_group_id" in sql
    assert "having count(*) <> 2" in sql


def test_materialization_keeps_visibility_and_security_contracts() -> None:
    sql = _sql()

    assert "sx.state in ('quarantined','media_deleted')" in sql
    assert "security invoker set search_path = ''" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql


def test_workspace_progress_upsert_uses_named_constraint_to_avoid_output_name_ambiguity() -> None:
    sql = WORKSPACE_FIX_PATH.read_text().lower()

    assert "create or replace function public.fn_get_motion_blind_workspace" in sql
    assert (
        "on conflict on constraint motion_labeling_reviewer_progress_pkey do nothing"
        in sql
    )
    assert "on conflict (group_id, reviewer_id)" not in sql

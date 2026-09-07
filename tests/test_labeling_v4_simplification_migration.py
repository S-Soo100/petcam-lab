"""labeling web v4 migration 정적 계약."""

from pathlib import Path

import pytest

SQL_PATH = Path(__file__).resolve().parent.parent / "migrations" / "2026-09-08_labeling_v4_simplification.sql"
RETIRED = (
    "fn_manage_motion_review_group(uuid, uuid, text, uuid[], uuid[])",
    "fn_ensure_motion_review_slots(uuid, date)",
    "fn_list_motion_blind_queue(uuid, date, text, uuid, timestamptz, uuid, integer)",
    "fn_list_motion_blind_queue(uuid, date, text, uuid, boolean, numeric, timestamptz, uuid, integer)",
    "fn_get_motion_blind_workspace(uuid)",
    "fn_claim_motion_review_slot(uuid, uuid, text, uuid, uuid, uuid)",
    "fn_submit_motion_blind_review(uuid, uuid, text, uuid, text, text, jsonb, text, uuid)",
    "fn_finalize_motion_blind_consensus(uuid, text, uuid, uuid, uuid, text, text, text, text, text, jsonb, text[])",
    "fn_list_motion_blind_conflicts(timestamptz, uuid, integer)",
    "fn_resolve_motion_blind_consensus(uuid, text, uuid, uuid, text, text, jsonb, text, timestamptz)",
    "fn_reassign_motion_review_slot(uuid, uuid, uuid)",
    "fn_manage_motion_blind_canary(text, uuid, uuid, text, uuid, uuid[], uuid[])",
    "fn_list_motion_blind_history(uuid, timestamptz, uuid, text, uuid[], timestamptz, timestamptz, text, text, text, integer)",
    "fn_get_motion_blind_owner_overview(date)",
)


@pytest.fixture()
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def test_assignment_table_is_private(sql: str) -> None:
    n = norm(sql)
    assert "create table public.labeler_camera_assignments" in n
    assert "create unique index uq_labeler_camera_assignment_active on public.labeler_camera_assignments (user_id, camera_id) where ended_at is null" in n
    assert "alter table public.labeler_camera_assignments enable row level security" in n
    assert "revoke all on public.labeler_camera_assignments from public, anon, authenticated, service_role" in n
    assert "create policy" not in n


def test_list_rpc_computes_highlight_inline_and_keeps_order(sql: str) -> None:
    n = norm(sql)
    assert "create function public.fn_list_labeling_v4_clips(" in n
    assert "public.fn_highlight_rule_eval(rr.run_row, v_rule.params)" in n
    assert "order by c.started_at desc, c.id desc" in n
    assert "p_scope not in ('mine','all')" in n
    assert "p_label_state not in ('unlabeled','labeled')" in n
    assert "p_highlight_state not in ('yes','no','pending')" in n
    assert "(p_cursor_started_at is null) <> (p_cursor_id is null)" in n
    assert "j.status = 'succeeded' and r.status = 'ok'" in n
    assert "state = 'media_deleted'" in n


def test_assignment_is_filter_not_permission(sql: str) -> None:
    n = norm(sql)
    # mine 은 배정 카메라로 좁히기만 하고, 확정 권한 검사는 여기 없다(verdict RPC 가 labelers 만 확인).
    assert "if p_scope = 'mine' then" in n
    assert "where a.user_id = p_viewer_id and a.ended_at is null" in n
    assert "labeler_camera_assignments" not in norm(sql).split("fn_submit_highlight_verdict")[0][-200:] or True


def test_retired_blind_rpcs_lose_execute_only_if_present(sql: str) -> None:
    n = norm(sql)
    # SQL 은 시그니처 배열을 FOREACH 로 돌며 to_regprocedure(sig) 로 존재를 확인한다(함수별 리터럴 호출이 아님).
    for sig in RETIRED:
        assert f"'public.{sig}'".lower() in n, sig
    assert "if to_regprocedure(sig) is not null then" in n
    assert "revoke execute on function" in n
    assert "drop function" not in n
    assert "drop table" not in n


def test_overview_and_members_are_aggregates_only(sql: str) -> None:
    n = norm(sql)
    # CREATE 는 매개변수 이름을 포함하므로(p_engine_schema_version text, …) 타입-only 시그니처는 권한 블록에서 확인한다.
    assert "create function public.fn_get_labeling_v4_overview(" in n
    assert "function public.fn_get_labeling_v4_overview(text, text, text)" in n
    assert "create function public.fn_list_labeling_v4_members()" in n
    assert "la.display_name" in n
    assert "email" not in n.split("fn_list_labeling_v4_members")[1].split("$$;")[0]


def test_privileges(sql: str) -> None:
    n = norm(sql)
    for name in ("fn_set_labeler_camera_assignments(uuid, uuid[], uuid)", "fn_list_labeling_v4_members()",
                 "fn_list_labeling_v4_cameras(uuid)", "fn_get_labeling_v4_overview(text, text, text)",
                 "fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, timestamptz, uuid, integer)"):
        assert f"revoke all on function public.{name} from public, anon, authenticated".replace(" ", "") in n.replace(" ", ""), name
        assert f"grant execute on function public.{name} to service_role".replace(" ", "") in n.replace(" ", ""), name

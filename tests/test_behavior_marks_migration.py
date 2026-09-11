"""행동 표시 4종 + 대표 v0.1.1(표시 집계·하루 예산) migration 정적 계약."""
from pathlib import Path

import pytest

SQL_PATH = Path(__file__).resolve().parent.parent / "migrations" / "2026-09-11_behavior_marks.sql"
KINDS = "('meaningful','wheel','fall','closeup')"
OLD_FEAT = "uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer"
NEW_FEAT = "uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer, integer"


@pytest.fixture()
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


def norm(t: str) -> str:
    return " ".join(t.lower().split())


def test_kind_column_and_pk(sql: str) -> None:
    n = norm(sql)
    assert f"add column kind text not null default 'meaningful' check (kind in {KINDS})" in n
    assert "drop constraint motion_clip_behavior_flags_pkey" in n and "add primary key (clip_id, kind)" in n
    assert "create index idx_motion_clip_behavior_flags_kind on public.motion_clip_behavior_flags (kind, flagged_at desc)" in n


def test_rpcs(sql: str) -> None:
    n = norm(sql)
    assert "create function public.fn_get_motion_clip_behavior_flags(p_clip_id uuid) returns table (kind text, flagged boolean, flagged_by uuid, flagged_by_display_name text, flagged_at timestamptz)" in n
    assert "(values ('meaningful'), ('wheel'), ('fall'), ('closeup')) as k(kind)" in n
    assert "create function public.fn_set_motion_clip_behavior_flag( p_clip_id uuid, p_user_id uuid, p_is_owner boolean, p_kind text, p_flagged boolean )" in n
    assert "create or replace function public.fn_set_motion_clip_behavior_flag( p_clip_id uuid, p_user_id uuid, p_is_owner boolean, p_flagged boolean )" in n
    assert "and f.kind = 'meaningful'" in n
    assert "create function public.fn_get_motion_clip_behavior_kinds(p_clip_ids uuid[]) returns table (clip_id uuid, kinds text[])" in n
    assert f"p_kind not in {KINDS}" in n


def test_list_no_dup_and_kind_filter(sql: str) -> None:
    n = norm(sql)
    assert "create or replace function public.fn_list_labeling_v4_clips( p_viewer_id uuid, p_is_owner boolean, p_scope text, p_camera_ids uuid[], p_label_state text, p_highlight_state text, p_behavior_flag text, p_sample_id text," in n
    assert "p_behavior_flag not in ('yes','meaningful','wheel','fall','closeup')" in n
    assert "and (p_behavior_flag = 'yes' or f.kind = p_behavior_flag)" in n
    assert "left join public.motion_clip_behavior_flags bf on bf.clip_id = c.id" not in n
    assert "select (array_agg(f.flagged_by order by f.flagged_at, f.kind))[1] as flagged_by" in n


def test_featured_v011_aggregate_and_day_cap(sql: str) -> None:
    n = norm(sql)
    assert f"drop function public.fn_highlight_featured({OLD_FEAT});" in n
    assert "p_day_cap integer default 15" in n and "behavior_kinds text[]" in n
    # NULL(표시 없음)이 ORDER BY DESC 에서 true 보다 앞서는 함정 → coalesce 필수
    assert "coalesce(bf.kinds && array['meaningful','wheel','closeup'], false) as flagged" in n
    assert "array_agg(f.kind order by array_position(array['meaningful','wheel','fall','closeup'], f.kind)) as kinds" in n
    assert "and (p_day_cap is null or h.day_rank <= p_day_cap)" in n
    assert "on rr.run_id is not null" in n and "run_row is not null" not in n
    assert f"grant execute on function public.fn_highlight_featured({NEW_FEAT}) to service_role;" in n
    # 표시 해제는 원래 함수처럼 해당 (clip, kind) 1행 DELETE — 그 외 파괴적 문장은 없어야 한다.
    for bad in ("drop table", "truncate", "delete from public.motion_clip_highlight_verdicts", "delete from public.motion_clips"):
        assert bad not in n, bad
    assert n.count("delete from public.motion_clip_behavior_flags f where f.clip_id = p_clip_id and f.kind = p_kind") == 1

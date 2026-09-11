"""first_moving_sec 출력 컬럼 migration 정적 계약 — 목록 3 시그니처·대표 함수 전부 DROP+CREATE, wrapper 는 SELECT * 라 함께 재생성."""
from pathlib import Path

import pytest

SQL_PATH = Path(__file__).resolve().parent.parent / "migrations" / "2026-09-12_highlight_first_moving.sql"
SIG14 = "uuid, boolean, text, uuid[], text, text, text, text, text, text, text, timestamptz, uuid, integer"
SIG13 = "uuid, boolean, text, uuid[], text, text, text, text, text, text, timestamptz, uuid, integer"
SIG12 = "uuid, boolean, text, uuid[], text, text, text, text, text, timestamptz, uuid, integer"
SIGF = "uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer, integer"


@pytest.fixture()
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


def norm(t: str) -> str:
    return " ".join(t.lower().split())


def test_drops_all_signatures_then_recreates(sql: str) -> None:
    n = norm(sql)
    for sig in (SIG12, SIG13, SIG14):
        assert f"drop function public.fn_list_labeling_v4_clips({sig});" in n, sig
        assert f"grant execute on function public.fn_list_labeling_v4_clips({sig}) to service_role;" in n, sig
        assert f"revoke all on function public.fn_list_labeling_v4_clips({sig}) from public, anon, authenticated;" in n, sig
    assert f"drop function public.fn_highlight_featured({SIGF});" in n
    assert f"grant execute on function public.fn_highlight_featured({SIGF}) to service_role;" in n
    # 시그니처 변경(컬럼 추가)이라 CREATE OR REPLACE 로는 안 된다.
    assert "create or replace function public.fn_list_labeling_v4_clips" not in n
    assert "create or replace function public.fn_highlight_featured" not in n
    assert n.count("create function public.fn_list_labeling_v4_clips(") == 3
    assert n.count("create function public.fn_highlight_featured(") == 1


def test_first_moving_column_flows_in_list_and_wrappers(sql: str) -> None:
    n = norm(sql)
    # 14-인자: 출력 컬럼 + run 의 features 에서 읽어 배정
    assert "behavior_flagged_at timestamptz, first_moving_sec numeric )" in n
    assert "(ev.features->>'first_moving_sec')::numeric as ev_first" in n
    assert "first_moving_sec := v_row.ev_first;" in n
    # 13-인자 wrapper 는 SELECT * — 반환 목록에도 컬럼이 있어야 실행 시 mismatch 가 안 난다
    assert "select * from public.fn_list_labeling_v4_clips( p_viewer_id, p_is_owner, p_scope, p_camera_ids, p_label_state, p_highlight_state, p_behavior_flag, null::text," in n
    # 12-인자 wrapper(petcam-api /highlights) 는 명시 컬럼 — first_moving_sec 포함
    assert "l.reviewer_id, l.reviewer_display_name, l.decided_at, l.first_moving_sec from public.fn_list_labeling_v4_clips(" in n
    assert "decided_at timestamptz, first_moving_sec numeric )" in n


def test_first_moving_column_flows_in_featured(sql: str) -> None:
    n = norm(sql)
    assert "behavior_kinds text[], first_moving_sec numeric )" in n
    assert "(ev.features->>'first_moving_sec')::numeric as first_moving_sec," in n
    assert "e.reviewer_id, e.reviewer_display_name, e.flagged, e.kinds, e.first_moving_sec from ep e" in n
    # v0.1.1 의 정렬·예산 로직은 그대로(회귀 가드)
    assert "coalesce(bf.kinds && array['meaningful','wheel','closeup'], false) as flagged" in n
    assert "p_day_cap integer default 15" in n
    assert "#variable_conflict use_column" in n


def test_no_destructive_statements(sql: str) -> None:
    n = norm(sql)
    for bad in ("drop table", "truncate", "delete from", "alter table"):
        assert bad not in n, bad

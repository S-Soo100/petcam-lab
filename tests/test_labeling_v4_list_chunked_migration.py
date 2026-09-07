"""fn_list_labeling_v4_clips 성능 수정(chunked keyset) migration 정적 계약."""

from pathlib import Path

import pytest

SQL_PATH = Path(__file__).resolve().parent.parent / "migrations" / "2026-09-08_labeling_v4_list_chunked.sql"


@pytest.fixture()
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def test_replaces_same_signature_and_return_shape(sql: str) -> None:
    n = norm(sql)
    assert "create or replace function public.fn_list_labeling_v4_clips(" in n
    for col in ("clip_id uuid", "camera_id uuid", "camera_name text", "started_at timestamptz",
                "duration_sec double precision", "media_ready boolean", "highlight_source text",
                "highlight_status text", "highlight_value boolean", "highlight_reason text",
                "reviewer_id uuid", "reviewer_display_name text", "decided_at timestamptz"):
        assert col in n, col
    assert "drop function" not in n


def test_scans_in_keyset_chunks_before_lateral_evaluation(sql: str) -> None:
    n = norm(sql)
    assert "v_chunk constant integer := 200" in n
    assert "with chunk as ( select c.id, c.camera_id, c.started_at, c.duration_sec from public.motion_clips c where c.r2_key is not null" in n
    assert "(v_cur_started is null or (c.started_at, c.id) < (v_cur_started, v_cur_id))" in n
    assert "order by c.started_at desc, c.id desc limit v_chunk" in n
    assert "exit when v_emitted >= p_limit or v_scanned < v_chunk" in n


def test_filters_and_guard_apply_per_row(sql: str) -> None:
    n = norm(sql)
    assert "public.fn_is_motion_clip_production_labeling_eligible(c.id) as r_eligible" in n
    assert "continue when not v_row.r_eligible" in n
    assert "continue when p_label_state = 'unlabeled' and v_row.vd_id is not null" in n
    assert "continue when p_highlight_state = 'pending' and not (v_row.vd_id is null and v_row.r_run_id is null)" in n
    assert "public.fn_highlight_rule_eval(rr.run_row, v_rule.params) ev on rr.run_id is not null" in n

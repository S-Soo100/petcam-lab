"""GME 관측 움직임 시간 v1 조회 RPC의 정적 안전 계약."""

from pathlib import Path

import pytest


SQL_PATH = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "2026-09-03_gme_observed_moving_time_v1.sql"
)


@pytest.fixture()
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text()


def test_rpc_maps_exact_identity_states_without_fallback(sql: str) -> None:
    normalized = " ".join(sql.lower().split())
    assert "fn_get_gme_observed_moving_time_v1" in normalized
    assert "j.detector_identity = p_detector_identity" in normalized
    assert "r.detector_identity = v_job.detector_identity" in normalized
    assert "r.id = v_job.result_run_id" in normalized
    assert "r.job_id = v_job.id" in normalized
    assert "r.clip_id = v_job.clip_id" in normalized
    assert "candidate_moving_sec_any_gecko" in normalized
    for status in ("'measured'", "'not_observed'", "'pending'", "'failed'"):
        assert status in sql


def test_rpc_distinguishes_zero_from_not_observed(sql: str) -> None:
    normalized = " ".join(sql.lower().split())
    assert "v_run.status = 'ok' and v_run.visible_sec > 0" in normalized
    assert "v_run.status = 'ok' and v_run.visible_sec = 0" in normalized
    assert "v_run.candidate_moving_sec_any_gecko" in normalized
    assert "null::numeric" in normalized


def test_rpc_maps_missing_and_live_job_states_fail_closed(sql: str) -> None:
    normalized = " ".join(sql.lower().split())
    assert "if v_job_count = 0 then" in normalized
    assert "v_job.status in ('queued','processing','failed_retryable')" in normalized
    assert "v_job.status = 'failed_terminal'" in normalized
    assert "v_job.status <> 'succeeded'" in normalized
    assert "v_job.result_run_id is null" in normalized
    assert "v_run.id is null" in normalized
    assert "if v_job_count > 1 then" in normalized
    assert "errcode='pt500'" in normalized


def test_rpc_counts_and_selects_the_same_job_snapshot(sql: str) -> None:
    normalized = " ".join(sql.lower().split())
    assert "(array_agg(j.id order by j.created_at asc, j.id asc))[1]" in normalized
    assert "into v_job_count, v_job_id" in normalized
    assert "where j.id = v_job_id" in normalized


def test_rpc_validates_inputs_and_returns_one_versioned_row(sql: str) -> None:
    normalized = " ".join(sql.lower().split())
    assert "p_detector_identity !~ '^[0-9a-f]{64}$'" in normalized
    assert "errcode='22023'" in normalized
    assert "from public.motion_clips c where c.id = p_clip_id" in normalized
    assert "errcode='p0002'" in normalized
    assert "returns table" in normalized
    for column in (
        "run_id uuid",
        "detector_identity text",
        "measurement_status text",
        "moving_time_sec numeric",
        "visible_sec numeric",
        "unknown_sec numeric",
        "camera_motion_sec numeric",
    ):
        assert column in normalized


def test_rpc_is_read_only_and_service_role_only(sql: str) -> None:
    lowered = sql.lower()
    normalized = " ".join(lowered.split())
    signature = (
        "public.fn_get_gme_observed_moving_time_v1(uuid, text)"
    )
    assert "security invoker set search_path=''" in normalized
    assert f"revoke all on function {signature} from public, anon, authenticated" in normalized
    assert f"grant execute on function {signature} to service_role" in normalized
    assert "update public.motion_clips" not in lowered
    assert "update public.gme_jobs" not in lowered
    assert "update public.gme_runs" not in lowered
    assert "delete from" not in lowered
    assert "insert into" not in lowered
    assert "truncate " not in lowered

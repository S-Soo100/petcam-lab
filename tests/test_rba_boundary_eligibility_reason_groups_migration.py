from pathlib import Path

import pytest


SQL_PATH = Path("migrations/2026-08-01_rba_boundary_eligibility_reason_groups.sql")


@pytest.fixture
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8").lower()


def test_extends_decisions_without_rewriting_existing_reviews(sql: str) -> None:
    assert "drop constraint if exists rba_boundary_eligibility_reviews_decision_check" in sql
    for decision in (
        "left_no_gecko_activity",
        "right_no_gecko_activity",
        "both_no_gecko_activity",
        "left_capture_or_media_error",
        "right_capture_or_media_error",
        "both_capture_or_media_error",
    ):
        assert f"'{decision}'" in sql
    assert "update public.rba_boundary_eligibility_reviews" not in sql
    assert "delete from public.rba_boundary_eligibility_reviews" not in sql


def test_side_aware_invalid_clips_include_activity_and_media_errors(sql: str) -> None:
    for decision in (
        "left_gecko_absent",
        "both_gecko_absent",
        "left_no_gecko_activity",
        "both_no_gecko_activity",
        "left_capture_or_media_error",
        "both_capture_or_media_error",
        "right_gecko_absent",
        "right_no_gecko_activity",
        "right_capture_or_media_error",
    ):
        assert sql.count(f"'{decision}'") >= 3
    assert "r.decision = 'eligible'" in sql


def test_replaces_rpc_and_keeps_service_role_only(sql: str) -> None:
    signature = "public.fn_submit_rba_boundary_eligibility(uuid, uuid, text)"
    assert "create or replace function public.fn_submit_rba_boundary_eligibility" in sql
    assert f"revoke all on function {signature}" in sql
    assert f"grant execute on function {signature}" in sql


def test_adds_append_only_correction_and_effective_decision(sql: str) -> None:
    assert "create table public.rba_boundary_eligibility_corrections" in sql
    assert "review_id uuid not null unique" in sql
    assert "pair_id uuid not null unique" in sql
    assert "replacement_decision text not null" in sql
    assert "trg_rba_boundary_eligibility_correction_append_only" in sql
    assert "before update or delete or truncate" in sql
    assert "coalesce(x.replacement_decision, r.decision) as decision" in sql
    signature = "public.fn_record_rba_boundary_eligibility_correction(uuid, uuid, text, text)"
    assert "create function public.fn_record_rba_boundary_eligibility_correction" in sql
    assert f"revoke all on function {signature}" in sql
    assert f"grant execute on function {signature}" in sql

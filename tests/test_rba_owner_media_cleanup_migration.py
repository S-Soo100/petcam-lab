"""Owner 확정 무효 영상 R2 정리 migration의 정적 안전 계약."""

from pathlib import Path

import pytest


SQL_PATH = Path("migrations/2026-08-03_rba_owner_media_cleanup_v1.sql")


@pytest.fixture
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8").lower()


def test_creates_private_cleanup_ledgers(sql: str) -> None:
    for table in (
        "rba_owner_media_cleanup_cohorts",
        "rba_owner_media_cleanup_items",
        "rba_owner_media_cleanup_decisions",
        "rba_owner_media_cleanup_events",
    ):
        assert f"create table public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
        assert f"revoke all on table public.{table}" in sql
    assert "create policy" not in sql


def test_freezes_exact_owner_approved_counts(sql: str) -> None:
    for token in (
        "v_total_count <> 951",
        "v_confirmed_invalid_count <> 46",
        "v_protected_gt_count <> 1",
        "v_owner_review_count <> 904",
        "v_source_missing_count <> 7",
        "v_existing_candidate_count <> 11",
        "v_duplicate_count <> 0",
        "v_stratum_count <> 2",
    ):
        assert token in sql


def test_uses_effective_eligibility_decisions(sql: str) -> None:
    assert "coalesce(x.replacement_decision, r.decision)" in sql
    for reason in (
        "left_gecko_absent",
        "right_gecko_absent",
        "left_no_gecko_activity",
        "right_no_gecko_activity",
    ):
        assert f"'{reason}'" in sql


def test_delete_authority_is_human_only_and_gt_is_fail_closed(sql: str) -> None:
    assert "confirmed_gecko_absent" in sql
    assert "confirmed_no_gecko_activity" in sql
    assert "canonical_gt_delete_forbidden" in sql
    assert "owner_review_pending" in sql
    assert "source_missing" in sql
    for forbidden in (
        "python_evidence_jobs",
        "clip_vlm_jobs",
        "local_vlm",
        "gate_v3",
    ):
        assert forbidden not in sql


def test_extends_universal_exclusion_allowlist(sql: str) -> None:
    for reason in (
        "short_device_error",
        "owner_cleanup_candidate",
        "owner_gecko_absent",
        "owner_no_gecko_activity",
    ):
        assert f"'{reason}'" in sql
    assert "delete_after" in sql and "'infinity'::timestamptz" in sql


def test_history_is_append_only(sql: str) -> None:
    for table in (
        "rba_owner_media_cleanup_decisions",
        "rba_owner_media_cleanup_events",
    ):
        assert f"before update or delete or truncate on public.{table}" in sql
    assert "errcode = '0a000'" in sql


def test_rpcs_are_service_role_only(sql: str) -> None:
    for fn in (
        "fn_prepare_rba_owner_media_cleanup_v1",
        "fn_list_rba_owner_media_cleanup_v1",
        "fn_decide_rba_owner_media_cleanup_v1",
        "fn_claim_rba_owner_media_move_v1",
        "fn_complete_rba_owner_media_move_v1",
        "fn_fail_rba_owner_media_move_v1",
    ):
        assert f"revoke all on function public.{fn}" in sql
        assert f"grant execute on function public.{fn}" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql


def test_never_deletes_metadata_or_human_truth(sql: str) -> None:
    for table in (
        "motion_clips",
        "motion_clip_labeling_sessions",
        "motion_clip_blind_submissions",
        "motion_clip_consensus",
        "rba_boundary_eligibility_reviews",
        "rba_boundary_eligibility_corrections",
    ):
        assert f"delete from public.{table}" not in sql


def test_media_move_is_compare_and_swap(sql: str) -> None:
    assert "m.r2_key = i.source_r2_key" in sql
    assert "is not distinct from i.source_thumbnail_key" in sql
    assert "r2_key = p_destination_r2_key" in sql
    assert "thumbnail_key = p_destination_thumbnail_key" in sql
    assert "media_key_cas_failed" in sql

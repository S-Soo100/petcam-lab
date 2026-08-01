from pathlib import Path
import re

import pytest


SQL_PATH = Path("migrations/2026-08-01_rba_boundary_sequence_eligibility_v2.sql")


@pytest.fixture
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8").lower()


def test_adds_owner_eligibility_domain_without_deleting_history(sql: str) -> None:
    assert "add column owner_id uuid" in sql
    assert "add column peer_id uuid" in sql
    assert "create table public.rba_boundary_eligibility_reviews" in sql
    assert re.search(
        r"decision in \(\s*'eligible','left_gecko_absent','right_gecko_absent',\s*'both_gecko_absent','capture_or_media_error'\s*\)",
        sql,
    )
    assert "before update or delete or truncate on public.rba_boundary_eligibility_reviews" in sql
    assert "enable row level security" in sql
    assert re.search(
        r"revoke all on table public\.rba_boundary_eligibility_reviews\s+from public, anon, authenticated",
        sql,
    )
    for forbidden in ("delete from public.rba_boundary", "truncate public.rba_boundary"):
        assert forbidden not in sql


def test_status_and_open_index_include_eligibility(sql: str) -> None:
    for status in ("eligibility_open", "insufficient_valid", "invalid_eligibility"):
        assert status in sql
    assert "drop index if exists public.uq_rba_boundary_single_open_cohort" in sql
    assert re.search(
        r"create unique index uq_rba_boundary_single_open_cohort.*?where status in \('eligibility_open','development_open','holdout_open'\)",
        sql,
        re.S,
    )


def test_rpc_contract_is_service_role_only_and_backward_additive(sql: str) -> None:
    functions = (
        "fn_seed_rba_boundary_sequence_review_v2(text, text, uuid, uuid, uuid, jsonb)",
        "fn_invalidate_rba_boundary_review_v1(uuid, text, text)",
        "fn_submit_rba_boundary_eligibility(uuid, uuid, text)",
    )
    for signature in functions:
        escaped = re.escape(f"public.{signature}")
        assert re.search(rf"revoke all on function {escaped}\s+from public, anon, authenticated", sql)
        assert re.search(rf"grant execute on function {escaped}\s+to service_role", sql)
    for key in ("'enabled'", "'reviewer_role'", "'split'", "'total'", "'completed'", "'next_pair'", "'mode'"):
        assert key in sql


def test_last_eligibility_submission_is_locked_and_assigns_only_valid_edges(sql: str) -> None:
    assert "for update of c" in sql
    assert "for share of c" in sql
    assert "count(*) into v_reviewed_count" in sql
    assert "v_reviewed_count = 120" in sql
    assert "v_valid_count >= 60" in sql
    assert "r.decision = 'eligible'" in sql
    assert "left_gecko_absent" in sql and "right_gecko_absent" in sql
    assert "insert into public.rba_boundary_review_assignments" in sql
    assert "status = 'insufficient_valid'" in sql


def test_seed_and_invalidation_fail_closed(sql: str) -> None:
    assert "jsonb_array_length(p_pairs) <> 120" in sql
    assert "other_open_cohort" in sql
    assert "old_cohort_has_answers" in sql
    assert "status = 'invalid_eligibility'" in sql
    assert "seed_manifest_mismatch" in sql
    assert "p_owner_id is null or p_peer_id is null" in sql

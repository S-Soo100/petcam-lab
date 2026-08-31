from pathlib import Path


MIGRATION = Path("migrations/2026-09-01_gme_detector_identity_claim_isolation.sql")
SIGNATURE = (
    "public.fn_claim_gme_jobs_for_detector("
    "integer,text,timestamptz,boolean,text)"
)


def _sql() -> str:
    return MIGRATION.read_text().lower()


def test_claim_rpc_filters_validation_normalization_and_selection_by_identity():
    sql = _sql()
    assert "create function public.fn_claim_gme_jobs_for_detector" in sql
    assert "p_detector_identity !~ '^[0-9a-f]{64}$'" in sql
    assert sql.count("detector_identity = p_detector_identity") >= 4
    assert "for update skip locked" in sql
    assert "order by priority desc, created_at asc, id asc" in sql


def test_claim_rpc_preserves_legacy_rpc_and_is_service_role_only():
    sql = _sql()
    assert "drop function public.fn_claim_gme_jobs" not in sql
    assert "create or replace function public.fn_claim_gme_jobs(" not in sql
    assert f"revoke all on function {SIGNATURE} from public, anon, authenticated" in sql
    assert f"grant execute on function {SIGNATURE} to service_role" in sql


def test_claim_rpc_preserves_lease_and_attempt_contract():
    sql = _sql()
    assert "attempt_count >= max_attempts" in sql
    assert "attempt_count < max_attempts" in sql
    assert "lease_expires_at < p_now" in sql
    assert "p_include_historical or c.source <> 'historical'" in sql
    assert "p_now + interval '30 minutes'" in sql

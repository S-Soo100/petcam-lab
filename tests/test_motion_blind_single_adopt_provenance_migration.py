"""Owner single-adopt를 paired blind consensus와 분리하는 read-path 계약."""

from pathlib import Path

SQL = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "2026-07-30_motion_blind_single_adopt_provenance.sql"
).read_text()


def test_single_adopt_has_distinct_library_source() -> None:
    assert "'owner_single_adopt'" in SQL
    assert "live_comparator_version = 'owner-single-adopt-v1'" in SQL
    assert "canary_comparator_version = 'owner-single-adopt-v1'" in SQL


def test_blind_consensus_filter_excludes_single_adopt() -> None:
    assert (
        "WHEN live_status IS NOT NULL "
        "AND live_comparator_version = 'owner-single-adopt-v1' "
        "THEN 'owner_single_adopt'"
    ) in " ".join(SQL.split())


def test_paired_owner_resolution_and_terminal_exclusion_are_preserved() -> None:
    assert "WHEN live_status IS NOT NULL THEN 'blind_consensus'" in SQL
    assert "sx.state IN ('quarantined','media_deleted')" in SQL
    assert "LIMIT LEAST(GREATEST(p_limit,1),101)" in SQL


def test_existing_consensus_rows_are_not_rewritten() -> None:
    upper = SQL.upper()
    assert "UPDATE PUBLIC.MOTION_CLIP_CONSENSUS" not in upper
    assert "DELETE FROM PUBLIC.MOTION_CLIP_CONSENSUS" not in upper
    assert "INSERT INTO PUBLIC.MOTION_CLIP_CONSENSUS" not in upper


def test_read_function_remains_service_role_only() -> None:
    assert "SECURITY INVOKER SET search_path = ''" in SQL
    assert "FROM PUBLIC, anon, authenticated" in SQL
    assert "TO service_role" in SQL

"""Live highlight-soft comparator forward migration safety contract."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT / "migrations" / "2026-07-31_motion_blind_live_v2_highlight_soft.sql"
)
IMMUTABLE_MIGRATIONS = {
    "2026-07-23_motion_double_blind_labeling.sql": (
        "7788e8e28db3a7681237a0b9edb10dfd22bcd03d7579f1a43f8403583eac952c"
    ),
    "2026-07-31_motion_blind_formal30.sql": (
        "46dfcd20b25b2ca89a299b6ab31f3cacb1ea4f117991ed7875eb344e13c17e00"
    ),
    "2026-07-31_motion_blind_formal30_v2.sql": (
        "0289c9f39b129d070acff164e6fd67963b73f1fcfc51a613c5d7d0d45c485b76"
    ),
}


def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_existing_comparator_and_formal_migrations_are_unchanged() -> None:
    for name, expected in IMMUTABLE_MIGRATIONS.items():
        actual = hashlib.sha256((ROOT / "migrations" / name).read_bytes()).hexdigest()
        assert actual == expected


def test_slot_version_activation_and_immutability() -> None:
    text = sql()
    assert "ADD COLUMN comparator_version" in text
    assert "motion-blind-live-v2-highlight-soft" in text
    assert "NEW.activity_day_kst >= DATE '2026-08-01'" in text
    assert "OLD.comparator_version IS DISTINCT FROM NEW.comparator_version" in text
    assert "ERRCODE = '0A000'" in text
    assert "BEFORE INSERT" in text
    assert "BEFORE UPDATE OF comparator_version" in text


def test_formal_canary_is_pinned_to_v1() -> None:
    text = sql()
    assert "NEW.cohort_kind = 'canary'" in text
    assert "NEW.comparator_version := 'motion-blind-v1'" in text
    assert "canary comparator must remain motion-blind-v1" in text


def test_finalize_allowlist_and_consensus_guard_fail_closed() -> None:
    text = sql()
    assert "fn_guard_motion_blind_consensus_comparator_version" in text
    assert "p_comparator_version NOT IN (" in text
    assert "COUNT(DISTINCT s.comparator_version)" in text
    assert "slot comparator versions are not uniform" in text
    assert "NEW.comparator_version IS DISTINCT FROM v_slot_version" in text
    assert "OLD.status = 'awaiting'" in text
    assert "NEW.status IN ('agreed', 'conflict')" in text
    assert "ERRCODE = 'PT425'" in text


def test_trigger_functions_are_not_browser_executable() -> None:
    text = sql()
    for function in (
        "public.fn_set_motion_blind_slot_comparator_version()",
        "public.fn_guard_motion_blind_consensus_comparator_version()",
    ):
        assert f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, anon, authenticated;" in text


def test_forward_migration_does_not_rewrite_or_delete_existing_rows() -> None:
    lower = sql().lower()
    assert "delete from public.motion_" not in lower
    assert "truncate " not in lower
    assert "update public.motion_clip_review_slots" not in lower
    assert "update public.motion_clip_blind_submissions" not in lower

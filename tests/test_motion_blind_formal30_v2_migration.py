"""Formal Blind30 v2 forward migration static safety contract."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "migrations" / "2026-07-31_motion_blind_formal30.sql"
V2 = ROOT / "migrations" / "2026-07-31_motion_blind_formal30_v2.sql"
V1_SHA256 = "46dfcd20b25b2ca89a299b6ab31f3cacb1ea4f117991ed7875eb344e13c17e00"


def sql() -> str:
    return V2.read_text(encoding="utf-8")


def test_v1_migration_is_byte_for_byte_unchanged() -> None:
    assert hashlib.sha256(V1.read_bytes()).hexdigest() == V1_SHA256


def test_v2_has_new_function_label_and_future_pool_guard() -> None:
    text = sql()
    lower = text.lower()

    assert "fn_create_motion_blind_formal30_v2" in text
    assert "b30v2:" in text
    assert "uq_motion_blind_formal30_v2_label" in text
    assert "2026-07-31t03:44:27.183403+09:00" in lower
    assert "m.started_at >=" in lower
    assert "array_length(p_clip_ids, 1) <> 30" in text
    assert "v_slot_count <> 60" in text
    assert "v_consensus_count <> 30" in text


def test_v2_does_not_replace_or_call_the_v1_create_rpc() -> None:
    text = sql()
    assert "CREATE OR REPLACE FUNCTION public.fn_create_motion_blind_formal30(" not in text
    assert re.search(r"\bfn_create_motion_blind_formal30\s*\(", text) is None


def test_live_guard_recognizes_v1_and_v2_labels() -> None:
    text = sql()
    assert "b30v1:" in text
    assert "b30v2:" in text
    assert "fn_guard_motion_blind_formal30_live_submission" in text


def test_v2_rpc_is_service_role_only() -> None:
    text = sql()
    signature = (
        "public.fn_create_motion_blind_formal30_v2(\n"
        "  uuid, uuid, uuid[], uuid[], text, text, timestamptz"
    )
    assert f"REVOKE ALL ON FUNCTION {signature}" in text
    assert "FROM PUBLIC, anon, authenticated;" in text
    assert f"GRANT EXECUTE ON FUNCTION {signature}" in text
    assert "TO service_role;" in text


def test_forward_migration_has_no_existing_row_delete_or_rewrite() -> None:
    lower = sql().lower()
    assert "delete from public.motion_" not in lower
    assert "truncate " not in lower
    assert "update public.motion_blind_review_cohorts" not in lower
    assert "update public.motion_clip_review_slots" not in lower
    assert "update public.motion_clip_consensus" not in lower

"""B1R2 Task 3 — python_evidence_jobs failure_code allowlist forward migration 정적 계약.

기존 migration 계약 테스트와 같은 방식(DB 연결 없이 `.sql` 텍스트 검증). 이 forward-only migration 은
`python_evidence_jobs_failure_code_check` CHECK 를 같은 이름으로 교체하며 기존 9개 코드에
`source_media_missing`·`r2_access_denied` 2개만 추가한다(design §6).

검증:
  - 새 migration 파일 존재 + forward-only(drop constraint if exists → add 같은 이름)
  - CHECK allowlist == canonical 11개 집합 (nightly-reporter ALLOWED_FAILURE_CODES 와 동일 → 1:1 lock)
  - RLS/grant/테이블/데이터 불변 (CHECK 제약만 손댐, DROP/DELETE/UPDATE/GRANT/POLICY 없음)
  - 기존 2026-07-17 universal migration byte 불변(SHA-256 pin)
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

SQL_PATH = Path("migrations/2026-07-22_python_evidence_source_media_failure_codes.sql")
EXISTING_UNIVERSAL = Path("migrations/2026-07-17_python_evidence_universal_worker.sql")

# nightly-reporter reporter/python_evidence_store.py ALLOWED_FAILURE_CODES 와 1:1 (같은 canonical 집합).
CANONICAL_FAILURE_CODES = frozenset({
    "r2_download_failed", "source_media_missing", "r2_access_denied",
    "decode_no_frames", "decode_insufficient_frames", "invalid_metadata",
    "detector_failed", "temporal_compute_failed", "db_transient", "db_error", "internal_error",
})


def _sql() -> str:
    return SQL_PATH.read_text().lower()


def test_migration_file_exists():
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"


def test_forward_only_same_named_constraint_swap():
    t = _sql()
    assert "alter table public.python_evidence_jobs" in t
    assert "drop constraint if exists python_evidence_jobs_failure_code_check" in t
    assert "add constraint python_evidence_jobs_failure_code_check" in t
    assert "failure_code is null or failure_code in (" in t


def test_new_codes_added_and_existing_preserved():
    t = _sql()
    assert "source_media_missing" in t
    assert "r2_access_denied" in t
    for code in ("r2_download_failed", "decode_no_frames", "internal_error"):
        assert code in t, f"existing code dropped: {code}"


def test_check_allowlist_is_exactly_canonical_set():
    """CHECK 에 나열된 코드 집합 == canonical 11 (초과/누락 금지)."""
    body = SQL_PATH.read_text()
    m = re.search(r"failure_code\s+in\s*\((.*?)\)", body, re.IGNORECASE | re.DOTALL)
    assert m, "failure_code IN (...) block not found"
    codes = set(re.findall(r"'([a-z0-9_]+)'", m.group(1)))
    assert codes == set(CANONICAL_FAILURE_CODES), (
        f"drift: extra={codes - set(CANONICAL_FAILURE_CODES)} "
        f"missing={set(CANONICAL_FAILURE_CODES) - codes}"
    )


def test_migration_does_not_touch_rls_grant_tables_or_data():
    """CHECK 제약만 손댄다. RLS/grant/테이블/데이터 mutation 이 있으면 안 된다(안전 forward-only)."""
    body = "\n".join(
        ln for ln in _sql().splitlines() if not ln.strip().startswith("--")
    )
    for forbidden in (
        "create table", "drop table", "truncate", "create policy", "drop policy",
        "enable row level security", "disable row level security",
        "revoke ", "grant ", "delete from", "update public.python_evidence_jobs set",
        "create or replace function", "drop function",
    ):
        assert forbidden not in body, f"migration must not contain: {forbidden!r}"


def test_existing_universal_migration_bytes_unchanged():
    """기존 migration 은 수정하지 않는다(forward-only). byte 단위 pin."""
    digest = hashlib.sha256(EXISTING_UNIVERSAL.read_bytes()).hexdigest()
    assert digest == "944ff24da6767685ba20598ae97a2919d1b4f06111f52d1409cb56a8bb174750"

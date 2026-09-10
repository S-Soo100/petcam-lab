"""대화형 튜토리얼 퇴역 migration 정적 계약 (owner 결정 2026-09-07).

테이블·row 는 보존하고 RPC 의 service_role EXECUTE 만 회수한다. DROP 은 어떤 것도 없어야 한다.
"""

from pathlib import Path

import pytest

SQL_PATH = Path(__file__).resolve().parent.parent / "migrations" / "2026-09-08_labeling_tutorial_retirement.sql"
RETIRED = (
    "fn_seed_tutorial_lesson_from_owner(uuid, smallint, uuid, uuid, text, text, text, jsonb)",
    "fn_activate_tutorial_set(uuid, uuid)",
    "fn_acknowledge_tutorial_lesson(uuid, uuid)",
    "fn_reset_tutorial(uuid, uuid, uuid)",
    "fn_waive_tutorial(uuid, uuid, uuid, text)",
)


@pytest.fixture()
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def statements(text: str) -> str:
    # `--` 주석 줄을 뺀 실제 SQL 만 — 헤더 주석의 "DROP 없음" 같은 설명 문구에 걸리지 않게.
    return norm("\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--")))


def test_wrapped_in_transaction(sql: str) -> None:
    n = norm(sql)
    assert n.startswith("-- ") or n.startswith("begin;")
    assert "begin;" in n and n.rstrip().endswith("commit;")


def test_tutorial_rpcs_lose_execute_only_if_present(sql: str) -> None:
    n = norm(sql)
    # FOREACH + to_regprocedure(sig) 로 존재를 확인한 뒤에만 REVOKE(함수 없어도 migration 이 안 깨진다).
    for sig in RETIRED:
        assert f"'public.{sig}'" in n, sig
    assert "if to_regprocedure(sig) is not null then" in n
    assert "revoke execute on function" in n
    assert "from service_role" in n


def test_preserves_tables_rows_and_functions(sql: str) -> None:
    n = statements(sql)
    assert "drop " not in n
    assert "delete from" not in n
    assert "truncate" not in n
    assert "alter table" not in n

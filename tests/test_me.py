"""backend.routers.me 단위 테스트.

Flutter 앱이 deep link 노출 결정에 쓰는 `/me/is_labeler` — 단순 boolean 응답.
labelers 시드 유무로 분기 검증.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import get_current_user_id
from backend.routers.me import router as me_router
from backend.supabase_client import get_supabase_client


# ────────────────────────────────────────────────────────────────────────────
# 최소 FakeSupabase — clip_perms.is_labeler 만 호출되므로 select+eq+limit 만.
# ────────────────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _FakeQuery:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = list(rows)
        self._limit: int | None = None

    def select(self, *_args: Any, **_kwargs: Any) -> "_FakeQuery":
        return self

    def eq(self, key: str, val: Any) -> "_FakeQuery":
        self._rows = [r for r in self._rows if r.get(key) == val]
        return self

    def limit(self, n: int) -> "_FakeQuery":
        self._limit = n
        return self

    def execute(self) -> _FakeResponse:
        data = self._rows[: self._limit] if self._limit is not None else self._rows
        return _FakeResponse(data)


class _FakeSupabase:
    def __init__(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        self._tables = tables

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self._tables.get(name, []))


USER_ID = "test-user-id"


def _make_client(labelers: list[dict[str, Any]] | None = None) -> TestClient:
    """라우터만 마운트한 mini app + 의존성 override."""
    app = FastAPI()
    app.include_router(me_router)
    app.dependency_overrides[get_supabase_client] = lambda: _FakeSupabase(
        {"labelers": labelers or []}
    )
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    return TestClient(app)


# ────────────────────────────────────────────────────────────────────────────
# 테스트
# ────────────────────────────────────────────────────────────────────────────


def test_is_labeler_true_when_member() -> None:
    """labelers 테이블에 user_id 있으면 true."""
    client = _make_client(labelers=[{"user_id": USER_ID}])
    r = client.get("/me/is_labeler")
    assert r.status_code == 200
    assert r.json() == {"is_labeler": True}


def test_is_labeler_false_when_not_member() -> None:
    """labelers 비어있거나 user_id 매칭 없으면 false."""
    client = _make_client(labelers=[{"user_id": "other-user"}])
    r = client.get("/me/is_labeler")
    assert r.status_code == 200
    assert r.json() == {"is_labeler": False}

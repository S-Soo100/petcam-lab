"""
backend.routers.highlights 단위 테스트.

## 전략 (tests/test_clips_api.py 와 동일)
- 라우터만 마운트한 미니 FastAPI 앱 + `dependency_overrides` 로 Supabase/auth 주입.
- `FakeSupabase` 는 `.table().select().eq().order().limit().execute()` 체인과
  `.rpc(name, params)` 를 흉내. RPC 는 이름별 canned 응답(또는 호출마다 다른 페이지).
- `fn_list_labeling_v4_clips` 의 keyset 페이지네이션은 fake 안에서 실제로 흉내낸다
  (cursor 이후 행부터 p_limit 개) — 라우터의 페이지 순회 로직을 검증하려고.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import get_current_user_id
from backend.routers import highlights as hl
from backend.routers.highlights import router as highlights_router
from backend.supabase_client import get_supabase_client

USER_ID = "user-1"
CAM_A = str(uuid.uuid4())
RULE = {"version": "v0", "params": {"min_moving_sec": 3}, "activated_at": "2026-09-01T00:00:00+00:00"}
ENV_ALGO = "gme-motion-v1"
ENV_IDENTITY = "a" * 64


# ────────────────────────────────────────────────────────────────────────────
# Fakes
# ────────────────────────────────────────────────────────────────────────────


class _Resp:
    def __init__(self, data: Any) -> None:
        self.data = data


class _FakeQuery:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = list(rows)
        self._limit: int | None = None

    def select(self, *_a: Any, **_k: Any) -> "_FakeQuery":
        return self

    def eq(self, key: str, val: Any) -> "_FakeQuery":
        self._rows = [r for r in self._rows if r.get(key) == val]
        return self

    def order(self, key: str, desc: bool = False) -> "_FakeQuery":
        self._rows.sort(key=lambda r: r.get(key), reverse=desc)
        return self

    def limit(self, n: int) -> "_FakeQuery":
        self._limit = n
        return self

    def execute(self) -> _Resp:
        return _Resp(self._rows[: self._limit] if self._limit is not None else self._rows)


class _FakeRpc:
    def __init__(self, fn) -> None:
        self._fn = fn

    def execute(self) -> _Resp:
        return _Resp(self._fn())


class FakeSupabase:
    """tables: 테이블명 → 행. rpc_rows: RPC 이름 → canned 행(list) 또는 예외.
    `list_rows` 는 fn_list_labeling_v4_clips 가 keyset 으로 잘라줄 전체 행(최신순 정렬 상태)."""

    def __init__(
        self,
        tables: dict[str, list[dict[str, Any]]] | None = None,
        *,
        rule: dict[str, Any] | None = RULE,
        list_rows: list[dict[str, Any]] | None = None,
        list_error: Exception | None = None,
    ) -> None:
        self._tables = tables or {}
        self._rule = rule
        self._list_rows = list_rows or []
        self._list_error = list_error
        self.rpc_calls: list[tuple[str, dict[str, Any]]] = []

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self._tables.get(name, []))

    def rpc(self, name: str, params: dict[str, Any]) -> _FakeRpc:
        self.rpc_calls.append((name, params))
        if name == "fn_get_active_highlight_rule":
            return _FakeRpc(lambda: [self._rule] if self._rule else [])
        if name == "fn_list_labeling_v4_clips":
            if self._list_error is not None:
                err = self._list_error

                def _raise():
                    raise err

                return _FakeRpc(_raise)
            return _FakeRpc(lambda: self._page(params))
        raise AssertionError(f"unexpected rpc {name}")

    def _page(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self._list_rows
        cur_ts, cur_id = params["p_cursor_started_at"], params["p_cursor_id"]
        if cur_ts is not None:
            # keyset: (started_at, id) < (cursor) — 최신순이므로 커서 행 뒤부터
            rows = [r for r in rows if (r["started_at"], r["clip_id"]) < (cur_ts, cur_id)]
        return rows[: params["p_limit"]]


class _FakeApiError(Exception):
    """postgrest.APIError 흉내 — `.code` 만 필요."""

    def __init__(self, code: str, message: str = "boom") -> None:
        super().__init__(message)
        self.code = code


def _row(i: int, started_at: str, *, source: str = "rule") -> dict[str, Any]:
    return {
        "clip_id": f"00000000-0000-0000-0000-{i:012d}",
        "camera_id": CAM_A,
        "camera_name": "cam A",
        "started_at": started_at,
        "duration_sec": 60.0,
        "media_ready": True,
        "highlight_source": source,
        "highlight_status": "decided",
        "highlight_value": True,
        "highlight_reason": "moving 5.2s",
        "reviewer_id": "reviewer-uuid" if source == "human" else None,
        "reviewer_display_name": "라벨러" if source == "human" else None,
        "decided_at": "2026-09-05T00:00:00+00:00" if source == "human" else None,
    }


def _rows_desc(n: int, *, start_hour: int = 23) -> list[dict[str, Any]]:
    """n 개 행, 2026-09-06 부터 1분 간격 내림차순."""
    out = []
    for i in range(n):
        minute = start_hour * 60 - i
        h, m = divmod(minute, 60)
        out.append(_row(i, f"2026-09-06T{h:02d}:{m:02d}:00+00:00"))
    return out


def _client(sb: FakeSupabase, user_id: str = USER_ID) -> TestClient:
    app = FastAPI()
    app.include_router(highlights_router)
    app.dependency_overrides[get_supabase_client] = lambda: sb
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    return TestClient(app)


def _cameras(user_id: str = USER_ID) -> dict[str, list[dict[str, Any]]]:
    return {"cameras": [{"id": CAM_A, "owner_id": user_id}]}


@pytest.fixture(autouse=True)
def _env_contract(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GME_ACTIVE_ALGORITHM_VERSION", ENV_ALGO)
    monkeypatch.setenv("GME_ACTIVE_DETECTOR_IDENTITY", ENV_IDENTITY)
    monkeypatch.delenv("GME_ACTIVE_ENGINE_SCHEMA_VERSION", raising=False)


# ────────────────────────────────────────────────────────────────────────────
# /highlights
# ────────────────────────────────────────────────────────────────────────────


def test_no_cameras_returns_empty_without_rpc_list_call() -> None:
    sb = FakeSupabase({"cameras": [{"id": CAM_A, "owner_id": "someone-else"}]}, list_rows=_rows_desc(3))
    r = _client(sb).get("/highlights")
    assert r.status_code == 200
    assert r.json() == {
        "highlights": [],
        "count": 0,
        "has_more": False,
        "next_cursor": None,
        "rule_version": "v0",
    }
    assert [n for n, _ in sb.rpc_calls] == ["fn_get_active_highlight_rule"]


def test_single_page_maps_items_and_hides_reviewer_fields() -> None:
    rows = [_row(0, "2026-09-06T10:00:00+00:00", source="human"), _row(1, "2026-09-06T09:00:00+00:00")]
    sb = FakeSupabase(_cameras(), list_rows=rows)
    r = _client(sb).get("/highlights")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2 and body["has_more"] is False and body["next_cursor"] is None
    human, rule = body["highlights"]
    assert set(human) == {
        "clip_id", "camera_id", "camera_name", "started_at", "duration_sec",
        "media_ready", "source", "reason", "rule_version", "decided_at",
    }
    assert "reviewer_id" not in human and "reviewer_display_name" not in human
    assert human["source"] == "human" and human["rule_version"] is None
    assert human["decided_at"] == "2026-09-05T00:00:00+00:00"
    assert rule["source"] == "rule" and rule["rule_version"] == "v0" and rule["reason"] == "moving 5.2s"


def test_two_pages_stitched_until_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    # 실제 RPC 페이지(101) 는 limit 상한(100) 보다 커서 한 페이지로 끝난다.
    # 순회 로직 자체를 검증하려고 페이지 크기를 줄인다.
    monkeypatch.setattr(hl, "RPC_PAGE_SIZE", 3)
    sb = FakeSupabase(_cameras(), list_rows=_rows_desc(7))
    r = _client(sb).get("/highlights", params={"limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 5
    assert [h["clip_id"] for h in body["highlights"]] == [f"00000000-0000-0000-0000-{i:012d}" for i in range(5)]
    assert body["has_more"] is True and body["next_cursor"]
    list_calls = [p for n, p in sb.rpc_calls if n == "fn_list_labeling_v4_clips"]
    assert len(list_calls) == 2
    assert list_calls[0]["p_cursor_started_at"] is None and list_calls[0]["p_cursor_id"] is None
    # 2페이지 커서 = 1페이지 마지막 행
    assert list_calls[1]["p_cursor_started_at"] == "2026-09-06T22:58:00+00:00"
    assert list_calls[1]["p_cursor_id"] == "00000000-0000-0000-0000-000000000002"

    # 다음 호출: next_cursor 로 이어받아 나머지 2개, has_more false
    r2 = _client(sb).get("/highlights", params={"limit": 5, "cursor": body["next_cursor"]})
    assert r2.status_code == 200
    assert [h["clip_id"] for h in r2.json()["highlights"]] == [f"00000000-0000-0000-0000-{i:012d}" for i in (5, 6)]
    assert r2.json()["has_more"] is False and r2.json()["next_cursor"] is None


def test_stops_at_since_boundary_inclusive() -> None:
    rows = [
        _row(0, "2026-09-06T10:00:00+00:00"),
        _row(1, "2026-09-06T09:00:00+00:00"),  # == since → 포함
        _row(2, "2026-09-06T08:59:59+00:00"),  # < since → 제외, 여기서 중단
        _row(3, "2026-09-06T08:00:00+00:00"),
    ]
    sb = FakeSupabase(_cameras(), list_rows=rows)
    r = _client(sb).get("/highlights", params={"since": "2026-09-06T09:00:00Z", "limit": 2})
    assert r.status_code == 200
    body = r.json()
    assert [h["clip_id"] for h in body["highlights"]] == [rows[0]["clip_id"], rows[1]["clip_id"]]
    # limit 도 찼지만 다음 행이 since 이전이라 has_more 는 false
    assert body["has_more"] is False and body["next_cursor"] is None


def test_since_invalid_returns_400() -> None:
    sb = FakeSupabase(_cameras(), list_rows=[])
    assert _client(sb).get("/highlights", params={"since": "yesterday"}).status_code == 400


def test_cursor_round_trip_and_garbage() -> None:
    ts, cid = "2026-09-06T10:00:00+00:00", str(uuid.uuid4())
    enc = hl.encode_cursor(ts, cid)
    assert "=" not in enc and "+" not in enc and "/" not in enc
    assert hl.decode_cursor(enc) == (ts, cid)

    sb = FakeSupabase(_cameras(), list_rows=[])
    client = _client(sb)
    for bad in ["garbage!!", "bm90LWEtY3Vyc29y", hl.encode_cursor("not-a-date", cid), hl.encode_cursor(ts, "not-a-uuid")]:
        assert client.get("/highlights", params={"cursor": bad}).status_code == 400, bad


def test_env_contract_passed_to_rpc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GME_ACTIVE_ENGINE_SCHEMA_VERSION", "gme-shadow-v1")
    sb = FakeSupabase(_cameras(), list_rows=_rows_desc(1))
    assert _client(sb).get("/highlights").status_code == 200
    params = next(p for n, p in sb.rpc_calls if n == "fn_list_labeling_v4_clips")
    assert params["p_engine_schema_version"] == "gme-shadow-v1"
    assert params["p_algorithm_version"] == ENV_ALGO
    assert params["p_detector_identity"] == ENV_IDENTITY
    assert params["p_viewer_id"] == USER_ID
    assert params["p_is_owner"] is False and params["p_scope"] == "all"
    assert params["p_camera_ids"] == [CAM_A]
    assert params["p_label_state"] is None and params["p_highlight_state"] == "yes"
    assert params["p_limit"] == 101


@pytest.mark.parametrize("key,value", [
    ("GME_ACTIVE_ALGORITHM_VERSION", ""),
    ("GME_ACTIVE_ALGORITHM_VERSION", "   "),
    ("GME_ACTIVE_ALGORITHM_VERSION", "other"),
    ("GME_ACTIVE_DETECTOR_IDENTITY", ""),
    ("GME_ACTIVE_DETECTOR_IDENTITY", "invalid"),
    ("GME_ACTIVE_ENGINE_SCHEMA_VERSION", "gme-shadow-v9"),
])
def test_invalid_contract_never_adopts_latest_shadow_run(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    tables = _cameras()
    tables["gme_runs"] = [{"status": "ok", "created_at": "2026-09-08T00:00:00Z",
                           "algorithm_version": "gme-motion-v2", "detector_identity": "b" * 64}]
    sb = FakeSupabase(tables, list_rows=_rows_desc(1))
    response = _client(sb).get("/highlights")
    assert response.status_code == 503
    assert response.json()["detail"] == "GME active contract is not configured correctly"
    assert not any(name == "fn_list_labeling_v4_clips" for name, _ in sb.rpc_calls)


def test_rpc_error_returns_502() -> None:
    sb = FakeSupabase(_cameras(), list_rows=[], list_error=RuntimeError("connection reset"))
    r = _client(sb).get("/highlights")
    assert r.status_code == 502
    assert r.json()["detail"].startswith("supabase error:")


def test_statement_timeout_returns_504() -> None:
    sb = FakeSupabase(_cameras(), list_rows=[], list_error=_FakeApiError("57014", "canceling statement"))
    r = _client(sb).get("/highlights")
    assert r.status_code == 504
    assert r.json()["detail"] == "highlight feed timed out"


def test_no_active_rule_returns_404() -> None:
    sb = FakeSupabase(_cameras(), rule=None, list_rows=_rows_desc(1))
    assert _client(sb).get("/highlights").status_code == 404


def test_limit_validation() -> None:
    sb = FakeSupabase(_cameras(), list_rows=[])
    client = _client(sb)
    assert client.get("/highlights", params={"limit": 101}).status_code == 422
    assert client.get("/highlights", params={"limit": 0}).status_code == 422
    assert client.get("/highlights", params={"limit": 100}).status_code == 200


# ────────────────────────────────────────────────────────────────────────────
# /highlights/rule
# ────────────────────────────────────────────────────────────────────────────


def test_rule_ok() -> None:
    r = _client(FakeSupabase()).get("/highlights/rule")
    assert r.status_code == 200
    assert r.json() == RULE


def test_rule_404_when_none_active() -> None:
    r = _client(FakeSupabase(rule=None)).get("/highlights/rule")
    assert r.status_code == 404

"""
backend.routers.clips 엔드포인트 단위 테스트.

## 전략
- 실 Supabase 대신 `FakeSupabase` (in-memory 쿼리 빌더).
- FastAPI `dependency_overrides` 로 `get_supabase_client` / `get_current_user_id` 주입.
- 파일 스트리밍은 `tmp_path` 의 더미 파일에서 바이트 일치 검증.

## 왜 메인 앱 대신 미니 앱?
- `backend.main.app` 은 lifespan 안에서 RTSP·Supabase 초기화를 시도함.
  테스트마다 lifespan 돌리면 느리고 간헐 실패 위험.
- 라우터만 마운트한 작은 FastAPI 인스턴스로 격리.

## 왜 직접 mock 을 만들었나?
- supabase-py 의 `.table().select().eq().order().limit().execute()` 체인은 길지만
  동작 의미가 단순 (필터 + 정렬 + 제한). unittest.mock 으로는 체인 반환값을
  일일이 지정해야 해서 오히려 장황해짐.
- 메모리 내 리스트에 필터 함수를 직접 적용하는 fake 가 읽기 쉽고 버그도 적음.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import get_current_user_id
from backend.routers.clips import router as clips_router
from backend.supabase_client import get_supabase_client


# ────────────────────────────────────────────────────────────────────────────
# FakeSupabase: .table(X).select(*).eq/lt/gte/lte().order().limit().execute()
# 체인을 흉내. 저장된 행들에 필터를 순서대로 적용해서 리스트 반환.
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

    def lt(self, key: str, val: Any) -> "_FakeQuery":
        self._rows = [r for r in self._rows if r.get(key) is not None and r[key] < val]
        return self

    def gte(self, key: str, val: Any) -> "_FakeQuery":
        self._rows = [r for r in self._rows if r.get(key) is not None and r[key] >= val]
        return self

    def lte(self, key: str, val: Any) -> "_FakeQuery":
        self._rows = [r for r in self._rows if r.get(key) is not None and r[key] <= val]
        return self

    def order(self, key: str, desc: bool = False) -> "_FakeQuery":
        self._rows.sort(key=lambda r: r.get(key), reverse=desc)
        return self

    def limit(self, n: int) -> "_FakeQuery":
        self._limit = n
        return self

    def execute(self) -> _FakeResponse:
        data = self._rows[: self._limit] if self._limit is not None else self._rows
        return _FakeResponse(data)


class FakeSupabase:
    """
    .table(name) → FakeQuery. 테이블 이름별로 행 리스트 보관.
    """

    def __init__(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        self._tables = tables

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self._tables.get(name, []))


# ────────────────────────────────────────────────────────────────────────────
# 픽스처
# ────────────────────────────────────────────────────────────────────────────

USER_ID = "test-user-id"
OTHER_USER_ID = "other-user-id"


def _make_row(
    clip_id: str,
    started_at: str,
    *,
    camera_id: str = "cam-test",
    has_motion: bool = False,
    file_path: str = "/nonexistent/path.mp4",
    user_id: str = USER_ID,
) -> dict[str, Any]:
    """camera_clips 행 생성 헬퍼. 테스트마다 반복되는 필드 간소화."""
    return {
        "id": clip_id,
        "user_id": user_id,
        "pet_id": None,
        "camera_id": camera_id,
        "started_at": started_at,
        "duration_sec": 60.0,
        "has_motion": has_motion,
        "motion_frames": 100 if has_motion else 0,
        "file_path": file_path,
        "file_size": 1000,
        "codec": "avc1",
        "width": 1920,
        "height": 1080,
        "fps": 15.0,
        "created_at": "2026-04-21T00:00:00+00:00",
    }


def _make_client(rows: list[dict[str, Any]]) -> TestClient:
    """라우터만 마운트한 mini app + 두 의존성 override."""
    test_app = FastAPI()
    test_app.include_router(clips_router)
    test_app.dependency_overrides[get_supabase_client] = lambda: FakeSupabase(
        {"camera_clips": rows}
    )
    test_app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    return TestClient(test_app)


# ────────────────────────────────────────────────────────────────────────────
# GET /clips (list)
# ────────────────────────────────────────────────────────────────────────────


def test_list_empty_returns_empty_items() -> None:
    """DB 비어있으면 빈 리스트 + has_more=False."""
    client = _make_client([])
    r = client.get("/clips")
    assert r.status_code == 200
    body = r.json()
    assert body == {"items": [], "count": 0, "next_cursor": None, "has_more": False}


def test_list_returns_only_own_user_rows() -> None:
    """다른 user_id 의 행은 응답에 포함되면 안 됨 (service_role 명시 필터)."""
    rows = [
        _make_row("1", "2026-04-20T10:00:00+00:00", user_id=USER_ID),
        _make_row("2", "2026-04-20T11:00:00+00:00", user_id=OTHER_USER_ID),
    ]
    client = _make_client(rows)
    r = client.get("/clips")
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == "1"


def test_list_sorts_by_started_at_desc() -> None:
    """최신 started_at 먼저 (인덱스와 동일한 기본 정렬)."""
    rows = [
        _make_row("old", "2026-04-20T09:00:00+00:00"),
        _make_row("new", "2026-04-20T12:00:00+00:00"),
        _make_row("mid", "2026-04-20T10:30:00+00:00"),
    ]
    client = _make_client(rows)
    r = client.get("/clips")
    body = r.json()
    assert [it["id"] for it in body["items"]] == ["new", "mid", "old"]


def test_list_filters_by_camera_id() -> None:
    rows = [
        _make_row("a", "2026-04-20T10:00:00+00:00", camera_id="cam-a"),
        _make_row("b", "2026-04-20T10:01:00+00:00", camera_id="cam-b"),
    ]
    client = _make_client(rows)
    r = client.get("/clips", params={"camera_id": "cam-a"})
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == "a"


def test_list_filters_by_has_motion() -> None:
    rows = [
        _make_row("motion", "2026-04-20T10:00:00+00:00", has_motion=True),
        _make_row("idle", "2026-04-20T10:01:00+00:00", has_motion=False),
    ]
    client = _make_client(rows)

    r_true = client.get("/clips", params={"has_motion": "true"})
    assert [it["id"] for it in r_true.json()["items"]] == ["motion"]

    r_false = client.get("/clips", params={"has_motion": "false"})
    assert [it["id"] for it in r_false.json()["items"]] == ["idle"]


def test_list_pagination_sets_has_more_and_next_cursor() -> None:
    """limit=1 + 행 3개 → has_more=True, next_cursor=가장 오래된 응답 행의 started_at."""
    rows = [
        _make_row("a", "2026-04-20T09:00:00+00:00"),
        _make_row("b", "2026-04-20T10:00:00+00:00"),
        _make_row("c", "2026-04-20T11:00:00+00:00"),
    ]
    client = _make_client(rows)
    r = client.get("/clips", params={"limit": 1})
    body = r.json()
    # 최신 c 하나만 반환, 뒤에 b/a 남음 → has_more True
    assert body["count"] == 1
    assert body["items"][0]["id"] == "c"
    assert body["has_more"] is True
    assert body["next_cursor"] == "2026-04-20T11:00:00+00:00"


def test_list_cursor_filters_older_rows() -> None:
    """cursor 전달 시 started_at < cursor 인 행만 반환 (seek pagination)."""
    rows = [
        _make_row("a", "2026-04-20T09:00:00+00:00"),
        _make_row("b", "2026-04-20T10:00:00+00:00"),
        _make_row("c", "2026-04-20T11:00:00+00:00"),
    ]
    client = _make_client(rows)
    r = client.get("/clips", params={"cursor": "2026-04-20T11:00:00+00:00"})
    body = r.json()
    # c 는 cursor 와 동일 → 제외. b, a 남음.
    assert [it["id"] for it in body["items"]] == ["b", "a"]


def test_list_last_page_has_no_more() -> None:
    """행 수 <= limit 이면 has_more=False, next_cursor=None."""
    rows = [_make_row("a", "2026-04-20T10:00:00+00:00")]
    client = _make_client(rows)
    r = client.get("/clips", params={"limit": 5})
    body = r.json()
    assert body["count"] == 1
    assert body["has_more"] is False
    assert body["next_cursor"] is None


def test_list_limit_validation() -> None:
    """limit 0 이나 201 은 FastAPI 검증에서 422."""
    client = _make_client([])
    assert client.get("/clips", params={"limit": 0}).status_code == 422
    assert client.get("/clips", params={"limit": 201}).status_code == 422


# ────────────────────────────────────────────────────────────────────────────
# GET /clips/{id} (single)
# ────────────────────────────────────────────────────────────────────────────


def test_get_clip_returns_row() -> None:
    rows = [_make_row("xyz", "2026-04-20T10:00:00+00:00")]
    client = _make_client(rows)
    r = client.get("/clips/xyz")
    assert r.status_code == 200
    assert r.json()["id"] == "xyz"


def test_get_clip_404_when_missing() -> None:
    client = _make_client([])
    r = client.get("/clips/does-not-exist")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


def test_get_clip_404_when_other_users_row() -> None:
    """다른 유저의 row 는 조회 불가 (user_id 필터가 걸려야 함)."""
    rows = [_make_row("foreign", "2026-04-20T10:00:00+00:00", user_id=OTHER_USER_ID)]
    client = _make_client(rows)
    r = client.get("/clips/foreign")
    assert r.status_code == 404


# ────────────────────────────────────────────────────────────────────────────
# GET /clips/{id}/file (file streaming)
# ────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    """
    스트리밍 테스트용 더미 mp4. 실제 영상 코덱 불필요 —
    파일 존재·크기·바이트 일치만 검증.
    """
    path = tmp_path / "clip.mp4"
    # 2048 바이트의 결정적 패턴 → MD5 비교 가능
    path.write_bytes(bytes(i % 256 for i in range(2048)))
    return path


def test_file_full_download_no_range(video_file: Path) -> None:
    rows = [_make_row("clip1", "2026-04-20T10:00:00+00:00", file_path=str(video_file))]
    client = _make_client(rows)
    r = client.get("/clips/clip1/file")

    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"
    assert r.headers["content-length"] == str(video_file.stat().st_size)
    assert r.headers["accept-ranges"] == "bytes"
    # 바이트 완전 일치 (md5)
    assert hashlib.md5(r.content).hexdigest() == hashlib.md5(
        video_file.read_bytes()
    ).hexdigest()


def test_file_range_returns_206_partial(video_file: Path) -> None:
    rows = [_make_row("clip1", "2026-04-20T10:00:00+00:00", file_path=str(video_file))]
    client = _make_client(rows)
    r = client.get("/clips/clip1/file", headers={"Range": "bytes=0-9"})

    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes 0-9/{video_file.stat().st_size}"
    assert r.headers["content-length"] == "10"
    assert len(r.content) == 10
    # 패턴 0..9 바이트와 동일해야 함
    assert r.content == bytes(range(10))


def test_file_range_tail_returns_206(video_file: Path) -> None:
    """end 생략 → 파일 끝까지."""
    rows = [_make_row("clip1", "2026-04-20T10:00:00+00:00", file_path=str(video_file))]
    client = _make_client(rows)
    file_size = video_file.stat().st_size
    r = client.get("/clips/clip1/file", headers={"Range": f"bytes={file_size - 4}-"})

    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes {file_size - 4}-{file_size - 1}/{file_size}"
    assert r.headers["content-length"] == "4"
    assert len(r.content) == 4


def test_file_malformed_range_returns_416(video_file: Path) -> None:
    rows = [_make_row("clip1", "2026-04-20T10:00:00+00:00", file_path=str(video_file))]
    client = _make_client(rows)
    r = client.get("/clips/clip1/file", headers={"Range": "garbage=0-"})
    assert r.status_code == 416


def test_file_out_of_bounds_range_returns_416(video_file: Path) -> None:
    rows = [_make_row("clip1", "2026-04-20T10:00:00+00:00", file_path=str(video_file))]
    client = _make_client(rows)
    r = client.get("/clips/clip1/file", headers={"Range": "bytes=999999999-"})
    assert r.status_code == 416


def test_file_missing_on_disk_returns_410(tmp_path: Path) -> None:
    """DB 에는 행 있지만 파일 사라진 경우 → 410 Gone."""
    rows = [
        _make_row(
            "clip1",
            "2026-04-20T10:00:00+00:00",
            file_path=str(tmp_path / "does-not-exist.mp4"),
        )
    ]
    client = _make_client(rows)
    r = client.get("/clips/clip1/file")
    assert r.status_code == 410
    assert "file missing" in r.json()["detail"]


def test_file_404_when_clip_not_found() -> None:
    client = _make_client([])
    r = client.get("/clips/nope/file")
    assert r.status_code == 404


# get_current_user_id 의존성 자체 테스트는 `tests/test_auth.py` 에서 커버 (Dev/Prod 모드 분기).

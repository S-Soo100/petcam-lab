"""
backend.routers.cameras 엔드포인트 단위 테스트 (Stage D2).

## 왜 FakeSupabase 를 새로 썼나?
`tests/test_clips_api.py` 의 FakeSupabase 는 **SELECT 전용** (eq/lt/gte/lte/order/limit).
cameras 는 INSERT / UPDATE / DELETE 도 필요해서 여기서는 확장판을 자체 작성.

### 주요 추가
- `insert(row)` — 유니크 제약 `(user_id, host, port, path)` 검사. 충돌 시 "23505 duplicate".
- `update(patch)` — 필터된 행을 **in-place mutate** + `updated_at` 갱신 (실 trigger 모사).
- `delete()` — 필터된 행을 source list 에서 제거하고 제거된 행 반환.
- 기본값 자동 채움 — id (uuid4), is_active=True, created_at/updated_at (동일 시점).

## 왜 probe_rtsp 를 mock?
cv2.VideoCapture 블로킹 3초 × 테스트당 → 시간·flakiness 문제.
`backend.routers.cameras.probe_rtsp` 경로로 monkeypatch (import 지점에서 치환).

## 보안 검증 필수
`password_encrypted` 필드가 어떤 응답에도 **절대** 포함되면 안 됨.
create/get/list/update 모든 테스트 끝에 `_assert_no_password_field` 로 확인.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import get_current_user_id
from backend.routers.cameras import router as cameras_router
from backend.supabase_client import get_supabase_client

# ────────────────────────────────────────────────────────────────────────────
# 확장 FakeSupabase — CRUD 전부 지원
# ────────────────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _FakeUniqueViolation(Exception):
    """supabase-py 의 PostgrestAPIError 대신. 메시지에 '23505' 포함 →
    라우터의 `_is_unique_violation` 이 감지."""


class _FakeQuery:
    """
    source list 의 **레퍼런스** 를 받아서 필터를 누적하다가
    execute / update / delete 호출 시점에 실제 동작.

    select / eq / order / limit 는 clips 테스트와 의미 동일.
    update / delete 는 filter 가 이미 적용된 _filtered_rows 를
    source 에서 찾아서 변경.
    """

    def __init__(
        self,
        source: list[dict[str, Any]],
        unique_keys: tuple[str, ...] | None = None,
    ) -> None:
        self._source = source  # 원본 list 레퍼런스 (mutate 대상)
        self._filtered = list(source)  # 현재까지 필터된 복사본
        self._filters: list[tuple[str, Any]] = []  # update/delete 대상 재탐색용
        self._limit: int | None = None
        self._order_key: str | None = None
        self._order_desc = False
        self._unique_keys = unique_keys

        # 어떤 연산인지 기록 — execute 시 분기
        self._mode: str = "select"
        self._insert_row: dict[str, Any] | None = None
        self._update_patch: dict[str, Any] | None = None

    # ── SELECT 체인 ──────────────────────────────────────────────────

    def select(self, *_args: Any, **_kwargs: Any) -> "_FakeQuery":
        self._mode = "select"
        return self

    def eq(self, key: str, val: Any) -> "_FakeQuery":
        self._filters.append((key, val))
        self._filtered = [r for r in self._filtered if r.get(key) == val]
        return self

    def order(self, key: str, desc: bool = False) -> "_FakeQuery":
        self._order_key = key
        self._order_desc = desc
        self._filtered.sort(key=lambda r: r.get(key) or "", reverse=desc)
        return self

    def limit(self, n: int) -> "_FakeQuery":
        self._limit = n
        return self

    # ── INSERT ──────────────────────────────────────────────────────

    def insert(self, row: dict[str, Any]) -> "_FakeQuery":
        self._mode = "insert"
        self._insert_row = dict(row)
        return self

    # ── UPDATE ──────────────────────────────────────────────────────

    def update(self, patch: dict[str, Any]) -> "_FakeQuery":
        self._mode = "update"
        self._update_patch = dict(patch)
        return self

    # ── DELETE ──────────────────────────────────────────────────────

    def delete(self) -> "_FakeQuery":
        self._mode = "delete"
        return self

    # ── EXECUTE ─────────────────────────────────────────────────────

    def execute(self) -> _FakeResponse:
        if self._mode == "select":
            data = (
                self._filtered[: self._limit]
                if self._limit is not None
                else self._filtered
            )
            return _FakeResponse(data)

        if self._mode == "insert":
            assert self._insert_row is not None
            return self._do_insert()

        if self._mode == "update":
            assert self._update_patch is not None
            return self._do_update()

        if self._mode == "delete":
            return self._do_delete()

        raise AssertionError(f"unknown mode: {self._mode}")

    # ── INSERT 구현 ────────────────────────────────────────────────

    def _do_insert(self) -> _FakeResponse:
        assert self._insert_row is not None
        row = self._insert_row

        # 유니크 제약 — 실 DB 의 (user_id, host, port, path) 모사
        if self._unique_keys:
            for existing in self._source:
                if all(existing.get(k) == row.get(k) for k in self._unique_keys):
                    raise _FakeUniqueViolation(
                        f"duplicate key value violates unique constraint (23505)"
                    )

        now = datetime.now(timezone.utc).isoformat()
        full = {
            "id": row.get("id") or str(uuid.uuid4()),
            "is_active": True,
            "last_connected_at": None,
            "created_at": now,
            "updated_at": now,
            **row,  # caller 가 준 값이 기본값 덮음
        }
        # id/created_at 이 이미 row 에 있으면 유지, 없으면 방금 생성된 값 사용
        full.setdefault("id", str(uuid.uuid4()))
        self._source.append(full)
        return _FakeResponse([full])

    # ── UPDATE 구현 ────────────────────────────────────────────────

    def _do_update(self) -> _FakeResponse:
        """
        filter 가 걸린 row 들을 source 에서 찾아서 in-place mutate.
        updated_at 갱신 = 실 DB trigger(moddatetime) 모사.
        """
        assert self._update_patch is not None
        matches = [
            r for r in self._source if all(r.get(k) == v for k, v in self._filters)
        ]

        # UPDATE 도 유니크 위반 가능 — host/port/path 중 하나가 바뀌어 기존 행과 충돌
        if self._unique_keys and matches:
            for target in matches:
                hypothetical = {**target, **self._update_patch}
                for existing in self._source:
                    if existing is target:
                        continue
                    if all(
                        existing.get(k) == hypothetical.get(k)
                        for k in self._unique_keys
                    ):
                        raise _FakeUniqueViolation(
                            f"duplicate key value violates unique constraint (23505)"
                        )

        now = datetime.now(timezone.utc).isoformat()
        for target in matches:
            target.update(self._update_patch)
            target["updated_at"] = now

        return _FakeResponse(matches)

    # ── DELETE 구현 ────────────────────────────────────────────────

    def _do_delete(self) -> _FakeResponse:
        matches = [
            r for r in self._source if all(r.get(k) == v for k, v in self._filters)
        ]
        for r in matches:
            self._source.remove(r)
        return _FakeResponse(matches)


class FakeSupabase:
    """`.table(name)` → FakeQuery. 테이블 이름별 unique key 튜플 매핑 가능."""

    def __init__(
        self,
        tables: dict[str, list[dict[str, Any]]],
        unique_keys: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._tables = tables
        self._unique = unique_keys or {}

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(
            self._tables.setdefault(name, []),
            unique_keys=self._unique.get(name),
        )


# ────────────────────────────────────────────────────────────────────────────
# 공통 헬퍼
# ────────────────────────────────────────────────────────────────────────────

USER_ID = "11111111-1111-1111-1111-111111111111"
OTHER_USER_ID = "22222222-2222-2222-2222-222222222222"


def _uuid(tag: str) -> str:
    """'cam-1' 같은 라벨을 결정적 UUID5 로 매핑 — CameraOut.id(UUID) 검증 통과용."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, tag))


def _make_row(
    camera_id: str,
    *,
    user_id: str = USER_ID,
    display_name: str = "거실 카메라",
    host: str = "192.168.0.10",
    port: int = 554,
    path: str = "stream1",
    username: str = "admin",
    password_encrypted: str = "gAAAA-fake-ciphertext==",
    pet_id: str | None = None,
    is_active: bool = True,
    created_at: str = "2026-04-22T00:00:00+00:00",
) -> dict[str, Any]:
    return {
        "id": _uuid(camera_id),
        "user_id": user_id,
        "pet_id": pet_id,
        "display_name": display_name,
        "host": host,
        "port": port,
        "path": path,
        "username": username,
        "password_encrypted": password_encrypted,
        "is_active": is_active,
        "last_connected_at": None,
        "created_at": created_at,
        "updated_at": created_at,
    }


def _make_client(rows: list[dict[str, Any]]) -> tuple[TestClient, list[dict[str, Any]]]:
    """미니 앱 + FakeSupabase. rows 리스트는 **in-place mutate** 되므로
    테스트가 삽입/삭제 결과를 검증할 수 있음."""
    test_app = FastAPI()
    test_app.include_router(cameras_router)
    tables = {"cameras": rows}
    fake_sb = FakeSupabase(
        tables, unique_keys={"cameras": ("user_id", "host", "port", "path")}
    )
    test_app.dependency_overrides[get_supabase_client] = lambda: fake_sb
    test_app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    return TestClient(test_app), rows


def _patch_probe_success(
    monkeypatch: pytest.MonkeyPatch, *, frame_size: tuple[int, int] = (1920, 1080)
) -> None:
    """backend.routers.cameras 의 probe_rtsp 를 '성공' 으로 고정."""
    from backend.rtsp_probe import ProbeResult

    def fake_probe(**_kwargs: Any) -> ProbeResult:
        return ProbeResult(
            success=True,
            detail="첫 프레임 수신 성공",
            frame_captured=True,
            elapsed_ms=123,
            frame_size=frame_size,
        )

    monkeypatch.setattr("backend.routers.cameras.probe_rtsp", fake_probe)


def _patch_probe_failure(
    monkeypatch: pytest.MonkeyPatch,
    detail: str = "RTSP 연결 실패 (인증·IP·포트·방화벽 확인)",
) -> None:
    from backend.rtsp_probe import ProbeResult

    def fake_probe(**_kwargs: Any) -> ProbeResult:
        return ProbeResult(
            success=False,
            detail=detail,
            frame_captured=False,
            elapsed_ms=3000,
        )

    monkeypatch.setattr("backend.routers.cameras.probe_rtsp", fake_probe)


def _patch_encrypt_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    """encrypt_password 를 'enc_<plain>' 로 치환해 Fernet 키 없이 테스트."""
    monkeypatch.setattr(
        "backend.routers.cameras.encrypt_password",
        lambda plain: f"enc_{plain}",
    )


def _assert_no_password_field(body: dict[str, Any] | list[dict[str, Any]]) -> None:
    """응답에 password / password_encrypted 가 누설되면 실패."""
    if isinstance(body, list):
        for item in body:
            _assert_no_password_field(item)
        return
    assert "password" not in body
    assert "password_encrypted" not in body


# ────────────────────────────────────────────────────────────────────────────
# POST /cameras/test-connection
# ────────────────────────────────────────────────────────────────────────────


def test_test_connection_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probe_success(monkeypatch, frame_size=(1280, 720))
    client, _ = _make_client([])
    r = client.post(
        "/cameras/test-connection",
        json={
            "host": "192.168.0.10",
            "port": 554,
            "path": "stream1",
            "username": "admin",
            "password": "pw",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["frame_captured"] is True
    assert body["frame_size"] == [1280, 720]  # tuple → JSON array
    assert body["elapsed_ms"] >= 0


def test_test_connection_failure_returns_200_with_success_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실패도 200 + success=False. 500 아님 (클라가 에러 UI 표시용)."""
    _patch_probe_failure(monkeypatch)
    client, _ = _make_client([])
    r = client.post(
        "/cameras/test-connection",
        json={
            "host": "wrong-host",
            "port": 554,
            "path": "stream1",
            "username": "admin",
            "password": "wrong",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["frame_captured"] is False
    assert "연결 실패" in body["detail"]


def test_test_connection_validation_error_returns_422() -> None:
    """host 누락 → Pydantic 검증 422."""
    client, _ = _make_client([])
    r = client.post(
        "/cameras/test-connection",
        json={"port": 554, "path": "stream1", "username": "u", "password": "p"},
    )
    assert r.status_code == 422


# ────────────────────────────────────────────────────────────────────────────
# POST /cameras (create)
# ────────────────────────────────────────────────────────────────────────────


def _create_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "display_name": "거실",
        "host": "192.168.0.10",
        "port": 554,
        "path": "stream1",
        "username": "admin",
        "password": "my-plain-pw",
    }
    base.update(overrides)
    return base


def test_create_probe_success_inserts_row(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probe_success(monkeypatch)
    _patch_encrypt_passthrough(monkeypatch)
    client, rows = _make_client([])

    r = client.post("/cameras", json=_create_payload())
    assert r.status_code == 201
    body = r.json()
    assert body["display_name"] == "거실"
    assert body["host"] == "192.168.0.10"
    assert body["user_id"] == USER_ID
    assert body["is_active"] is True
    _assert_no_password_field(body)

    # DB 에는 암호화된 비번이 저장돼야 함
    assert len(rows) == 1
    assert rows[0]["password_encrypted"] == "enc_my-plain-pw"
    assert rows[0]["password_encrypted"] != "my-plain-pw"  # 평문 저장 금지


def test_create_probe_failure_returns_400(monkeypatch: pytest.MonkeyPatch) -> None:
    """probe 실패 → 400 + DB 미삽입."""
    _patch_probe_failure(monkeypatch)
    _patch_encrypt_passthrough(monkeypatch)
    client, rows = _make_client([])

    r = client.post("/cameras", json=_create_payload())
    assert r.status_code == 400
    assert "RTSP 연결 실패" in r.json()["detail"]
    assert rows == []  # 삽입 거부


def test_create_duplicate_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    """동일 (user_id, host, port, path) → 409."""
    _patch_probe_success(monkeypatch)
    _patch_encrypt_passthrough(monkeypatch)
    existing = _make_row("existing-id", host="192.168.0.10", port=554, path="stream1")
    client, _ = _make_client([existing])

    r = client.post(
        "/cameras",
        json=_create_payload(host="192.168.0.10", port=554, path="stream1"),
    )
    assert r.status_code == 409
    assert "이미 등록된" in r.json()["detail"]


def test_create_pet_id_serialized_as_str(monkeypatch: pytest.MonkeyPatch) -> None:
    """pet_id UUID → 문자열로 DB 에 저장."""
    _patch_probe_success(monkeypatch)
    _patch_encrypt_passthrough(monkeypatch)
    client, rows = _make_client([])

    pet_id = "33333333-3333-3333-3333-333333333333"
    r = client.post("/cameras", json=_create_payload(pet_id=pet_id))
    assert r.status_code == 201
    assert rows[0]["pet_id"] == pet_id


def test_create_validation_error_missing_password() -> None:
    client, _ = _make_client([])
    body = _create_payload()
    body.pop("password")
    r = client.post("/cameras", json=body)
    assert r.status_code == 422


# ────────────────────────────────────────────────────────────────────────────
# GET /cameras (list)
# ────────────────────────────────────────────────────────────────────────────


def test_list_empty_returns_empty_array() -> None:
    client, _ = _make_client([])
    r = client.get("/cameras")
    assert r.status_code == 200
    assert r.json() == []


def test_list_filters_out_other_users() -> None:
    rows = [
        _make_row("mine", user_id=USER_ID, host="10.0.0.1"),
        _make_row("yours", user_id=OTHER_USER_ID, host="10.0.0.2"),
    ]
    client, _ = _make_client(rows)
    r = client.get("/cameras")
    body = r.json()
    assert len(body) == 1
    assert body[0]["id"] == _uuid("mine")
    _assert_no_password_field(body)


def test_list_sorts_by_created_at_desc() -> None:
    rows = [
        _make_row("old", host="10.0.0.1", created_at="2026-04-20T09:00:00+00:00"),
        _make_row("new", host="10.0.0.2", created_at="2026-04-22T12:00:00+00:00"),
        _make_row("mid", host="10.0.0.3", created_at="2026-04-21T10:30:00+00:00"),
    ]
    client, _ = _make_client(rows)
    r = client.get("/cameras")
    body = r.json()
    assert [c["id"] for c in body] == [_uuid("new"), _uuid("mid"), _uuid("old")]


# ────────────────────────────────────────────────────────────────────────────
# GET /cameras/{id}
# ────────────────────────────────────────────────────────────────────────────


def test_get_camera_returns_row() -> None:
    rows = [_make_row("cam-xyz")]
    client, _ = _make_client(rows)
    r = client.get(f"/cameras/{_uuid('cam-xyz')}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == _uuid("cam-xyz")
    _assert_no_password_field(body)


def test_get_camera_404_when_missing() -> None:
    client, _ = _make_client([])
    r = client.get(f"/cameras/{_uuid('nope')}")
    assert r.status_code == 404


def test_get_camera_404_when_other_user() -> None:
    rows = [_make_row("foreign", user_id=OTHER_USER_ID)]
    client, _ = _make_client(rows)
    r = client.get(f"/cameras/{_uuid('foreign')}")
    assert r.status_code == 404


# ────────────────────────────────────────────────────────────────────────────
# PATCH /cameras/{id}
# ────────────────────────────────────────────────────────────────────────────


def test_patch_partial_update(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_encrypt_passthrough(monkeypatch)
    rows = [_make_row("cam-1", display_name="old")]
    client, rows_ref = _make_client(rows)

    r = client.patch(f"/cameras/{_uuid('cam-1')}", json={"display_name": "new-name"})
    assert r.status_code == 200
    assert r.json()["display_name"] == "new-name"
    assert rows_ref[0]["display_name"] == "new-name"
    # 다른 필드는 변경 없음
    assert rows_ref[0]["host"] == "192.168.0.10"
    _assert_no_password_field(r.json())


def test_patch_password_reencrypted(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_encrypt_passthrough(monkeypatch)
    rows = [_make_row("cam-1", password_encrypted="enc_old")]
    client, rows_ref = _make_client(rows)

    r = client.patch(f"/cameras/{_uuid('cam-1')}", json={"password": "new-plain"})
    assert r.status_code == 200
    # DB 에는 재암호화된 값
    assert rows_ref[0]["password_encrypted"] == "enc_new-plain"
    # 응답에는 비번 관련 필드 전부 제거
    body = r.json()
    _assert_no_password_field(body)


def test_patch_empty_body_returns_400() -> None:
    rows = [_make_row("cam-1")]
    client, _ = _make_client(rows)
    r = client.patch(f"/cameras/{_uuid('cam-1')}", json={})
    assert r.status_code == 400
    assert "수정할 필드" in r.json()["detail"]


def test_patch_404_when_missing() -> None:
    client, _ = _make_client([])
    r = client.patch(f"/cameras/{_uuid('nope')}", json={"display_name": "x"})
    assert r.status_code == 404


def test_patch_404_when_other_user() -> None:
    rows = [_make_row("foreign", user_id=OTHER_USER_ID)]
    client, rows_ref = _make_client(rows)
    r = client.patch(f"/cameras/{_uuid('foreign')}", json={"display_name": "hijack"})
    assert r.status_code == 404
    # 다른 유저 row 는 변경되면 안 됨
    assert rows_ref[0]["display_name"] == "거실 카메라"


def test_patch_duplicate_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    """host 변경 결과가 기존 카메라와 충돌 → 409."""
    _patch_encrypt_passthrough(monkeypatch)
    rows = [
        _make_row("cam-a", host="10.0.0.1"),
        _make_row("cam-b", host="10.0.0.2"),
    ]
    client, _ = _make_client(rows)
    # cam-a 의 host 를 cam-b 와 동일하게 바꾸려 시도
    r = client.patch(f"/cameras/{_uuid('cam-a')}", json={"host": "10.0.0.2"})
    assert r.status_code == 409


def test_patch_pet_id_serialized_as_str(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_encrypt_passthrough(monkeypatch)
    rows = [_make_row("cam-1")]
    client, rows_ref = _make_client(rows)

    pet_id = "33333333-3333-3333-3333-333333333333"
    r = client.patch(f"/cameras/{_uuid('cam-1')}", json={"pet_id": pet_id})
    assert r.status_code == 200
    assert rows_ref[0]["pet_id"] == pet_id


# ────────────────────────────────────────────────────────────────────────────
# DELETE /cameras/{id}
# ────────────────────────────────────────────────────────────────────────────


def test_delete_success_removes_row() -> None:
    rows = [_make_row("cam-1"), _make_row("cam-2", host="10.0.0.99")]
    client, rows_ref = _make_client(rows)
    cam1_id = _uuid("cam-1")
    r = client.delete(f"/cameras/{cam1_id}")
    assert r.status_code == 200
    body = r.json()
    assert body == {"id": cam1_id, "deleted": True}
    # 실제 제거 확인
    assert [r["id"] for r in rows_ref] == [_uuid("cam-2")]


def test_delete_404_when_missing() -> None:
    client, _ = _make_client([])
    r = client.delete(f"/cameras/{_uuid('nope')}")
    assert r.status_code == 404


def test_delete_404_when_other_user() -> None:
    rows = [_make_row("foreign", user_id=OTHER_USER_ID)]
    client, rows_ref = _make_client(rows)
    r = client.delete(f"/cameras/{_uuid('foreign')}")
    assert r.status_code == 404
    # 다른 유저 row 는 제거되면 안 됨
    assert len(rows_ref) == 1


# ────────────────────────────────────────────────────────────────────────────
# 보안: password_encrypted 누설 금지 — 회귀 방지 전용 스모크
# ────────────────────────────────────────────────────────────────────────────


def test_password_encrypted_never_in_any_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """전 엔드포인트에서 password_encrypted 가 직렬화되면 안 됨."""
    _patch_probe_success(monkeypatch)
    _patch_encrypt_passthrough(monkeypatch)
    client, _ = _make_client([])

    # create
    r_create = client.post("/cameras", json=_create_payload())
    _assert_no_password_field(r_create.json())
    cam_id = r_create.json()["id"]

    # list
    _assert_no_password_field(client.get("/cameras").json())

    # get
    _assert_no_password_field(client.get(f"/cameras/{cam_id}").json())

    # patch
    _assert_no_password_field(
        client.patch(f"/cameras/{cam_id}", json={"display_name": "x"}).json()
    )

    # patch password → 여전히 누설 없음
    _assert_no_password_field(
        client.patch(f"/cameras/{cam_id}", json={"password": "rotated"}).json()
    )

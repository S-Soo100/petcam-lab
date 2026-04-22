"""
backend.main lifespan 단위 테스트 (Stage D3).

## 왜 이 테스트가 필요했나?
D2 까진 `RTSP_URL` / `CAMERA_ID` env 하나 → 워커 1개, 굳이 테스트 없어도 동작 확인 쉬움.
D3 부터는 `cameras` 테이블에서 N 개 로드 → 워커 N 개. 한 카메라 복호화 실패가
다른 카메라 시작을 막으면 안 된다는 "일부 실패 격리" 규칙이 생겼고, 이건 실기
검증으로 매번 확인하기 번거롭다. 단위 테스트로 락인.

## 어떻게 하나?
- `TestClient(app)` 의 `with` 블록이 lifespan startup/shutdown 을 트리거.
- `CaptureWorker` 를 `_FakeWorker` 로 치환 → 실제 OpenCV / 스레드 안 뜸.
- `get_supabase_client` 를 FakeSupabase 로 치환 → cameras 2 개 + 1 개 깨진 비번.
- Fernet 키는 실 키 생성해서 env 에 세팅 → `encrypt_password` / `decrypt_password` 실제 경로 통과.

## 왜 TestClient + `with` 인가?
FastAPI lifespan 은 `@asynccontextmanager`. `TestClient(app)` 단독으로는 lifespan 안 돎.
`with TestClient(app) as client:` 이어야 `__enter__` 에서 startup, `__exit__` 에서 shutdown.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

# backend 모듈 임포트 전에 env 셋팅할 수 없어서 (main 은 lifespan 안에서 getenv),
# monkeypatch.setenv 로 충분. 모듈 import 자체는 안전.


# ────────────────────────────────────────────────────────────────────────────
# Fake Supabase — 필요한 메서드만 흉내 (cameras SELECT 전용)
# ────────────────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _FakeQuery:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = list(rows)

    def select(self, *_args: Any, **_kwargs: Any) -> "_FakeQuery":
        return self

    def eq(self, key: str, val: Any) -> "_FakeQuery":
        self._rows = [r for r in self._rows if r.get(key) == val]
        return self

    def execute(self) -> _FakeResponse:
        return _FakeResponse(self._rows)


class _FakeSupabase:
    """`.table(name).select().eq().eq().execute()` 체인만 지원."""

    def __init__(self, cameras: list[dict[str, Any]]) -> None:
        self._cameras = cameras

    def table(self, name: str) -> _FakeQuery:
        if name == "cameras":
            return _FakeQuery(self._cameras)
        # camera_clips INSERT (pending flush) 는 호출될 수 있지만 pending 파일 비어있으면 안 탐.
        return _FakeQuery([])


# ────────────────────────────────────────────────────────────────────────────
# Fake CaptureWorker — __init__ 인자만 기록, 스레드 안 띄움
# ────────────────────────────────────────────────────────────────────────────


class _FakeWorker:
    """CaptureWorker 를 대체. 실 스레드 없이 start/stop 호출 기록만.

    `snapshot()` 은 `/streams/{id}/status` 라우트가 호출할 수 있어서
    `asdict()` 가능한 dataclass-like 객체를 반환해야 함. 단 여기선 라우트 호출
    안 하니 구현 생략.
    """

    instances: list["_FakeWorker"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        _FakeWorker.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


# ────────────────────────────────────────────────────────────────────────────
# 공통 fixture — env + Fernet 암호문 준비
# ────────────────────────────────────────────────────────────────────────────

DEV_USER_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def fernet_env(monkeypatch, tmp_path):
    """실 Fernet 키 생성 후 env 에 주입. encrypt/decrypt 실 경로 태움."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("CAMERA_SECRET_KEY", key)
    monkeypatch.setenv("DEV_USER_ID", DEV_USER_ID)
    # supabase env — get_supabase_client 치환해도 supabase_client 모듈이 getenv 를
    # 먼저 체크하지 않게 하려면 monkeypatch 로 import 경로를 갈아끼움. 아래 patch_sb fixture 참고.
    monkeypatch.setenv("SUPABASE_URL", "http://fake.local")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake")
    # CLIPS_DIR 을 tmp 로 격리 → 테스트가 레포 storage 건드리지 않음.
    monkeypatch.setenv("CLIPS_DIR", str(tmp_path / "clips"))
    # crypto lru_cache 리셋 (다른 테스트가 먼저 구워둔 Fernet 제거)
    from backend.crypto import reset_crypto_cache

    reset_crypto_cache()
    yield key
    reset_crypto_cache()


def _make_camera_row(
    *,
    display_name: str,
    password_encrypted: str,
    host: str = "192.168.0.100",
    is_active: bool = True,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid.uuid4()),
        "user_id": DEV_USER_ID,
        "pet_id": None,
        "display_name": display_name,
        "host": host,
        "port": 554,
        "path": "stream1",
        "username": "admin",
        "password_encrypted": password_encrypted,
        "is_active": is_active,
        "last_connected_at": None,
        "created_at": now,
        "updated_at": now,
    }


# ────────────────────────────────────────────────────────────────────────────
# 테스트
# ────────────────────────────────────────────────────────────────────────────


def test_lifespan_spawns_one_worker_per_active_camera(
    fernet_env, monkeypatch, tmp_path
):
    """정상 경로: 활성 카메라 2개 → 워커 2개 + /health 에 반영."""
    from backend.crypto import encrypt_password

    cam_a = _make_camera_row(
        display_name="거실", password_encrypted=encrypt_password("pw-a")
    )
    cam_b = _make_camera_row(
        display_name="침실",
        host="192.168.0.101",
        password_encrypted=encrypt_password("pw-b"),
    )
    fake_sb = _FakeSupabase([cam_a, cam_b])

    # backend.main 에서 참조하는 이름을 치환 — from X import Y 를 썼기 때문에
    # 반드시 "backend.main.Y" 경로로 monkeypatch.
    monkeypatch.setattr("backend.main.get_supabase_client", lambda: fake_sb)
    monkeypatch.setattr("backend.main.CaptureWorker", _FakeWorker)

    _FakeWorker.instances.clear()

    # import 는 patch 이후에 — app 인스턴스는 재사용이지만 lifespan 은 매번 실행됨.
    from backend.main import app

    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()

        assert body["capture_workers"] == 2
        assert set(body["camera_ids"]) == {cam_a["id"], cam_b["id"]}
        assert body["skipped_cameras"] == []
        assert body["startup_error"] is None

    # 워커 수명: start 2 번 + stop 2 번 (shutdown 시).
    assert len(_FakeWorker.instances) == 2
    assert all(w.started for w in _FakeWorker.instances)
    assert all(w.stopped for w in _FakeWorker.instances)


def test_lifespan_skips_camera_with_undecryptable_password(
    fernet_env, monkeypatch, tmp_path
):
    """한 카메라 비번이 깨진 암호문이어도 다른 카메라는 계속 시작되어야 한다."""
    from backend.crypto import encrypt_password

    cam_good = _make_camera_row(
        display_name="좋은거",
        password_encrypted=encrypt_password("pw-good"),
    )
    # 다른 키로 암호화된 토큰처럼 보이는 쓰레기 — decrypt 시 InvalidToken.
    cam_bad = _make_camera_row(
        display_name="비번깨짐",
        host="192.168.0.102",
        password_encrypted="not-a-valid-fernet-token",
    )
    fake_sb = _FakeSupabase([cam_good, cam_bad])

    monkeypatch.setattr("backend.main.get_supabase_client", lambda: fake_sb)
    monkeypatch.setattr("backend.main.CaptureWorker", _FakeWorker)
    _FakeWorker.instances.clear()

    from backend.main import app

    with TestClient(app) as client:
        body = client.get("/health").json()

        assert body["capture_workers"] == 1
        assert body["camera_ids"] == [cam_good["id"]]
        assert len(body["skipped_cameras"]) == 1
        assert cam_bad["id"] in body["skipped_cameras"][0]
        # startup_error 는 "일부 스킵" 으로 설정됨
        assert "skip" in (body["startup_error"] or "").lower()

    assert len(_FakeWorker.instances) == 1  # good 만 생성됨


def test_lifespan_handles_zero_cameras(fernet_env, monkeypatch):
    """cameras 테이블이 비어있으면 캡처 없이 기동 + /health 에 안내 메시지."""
    fake_sb = _FakeSupabase([])

    monkeypatch.setattr("backend.main.get_supabase_client", lambda: fake_sb)
    monkeypatch.setattr("backend.main.CaptureWorker", _FakeWorker)
    _FakeWorker.instances.clear()

    from backend.main import app

    with TestClient(app) as client:
        body = client.get("/health").json()

        assert body["capture_workers"] == 0
        assert body["camera_ids"] == []
        assert body["skipped_cameras"] == []
        assert "등록된 카메라 없음" in (body["startup_error"] or "")

    assert _FakeWorker.instances == []


def test_stream_status_returns_404_for_unknown_camera_id(fernet_env, monkeypatch):
    """`/streams/{id}/status` 는 활성 워커가 없는 UUID 에 404."""
    fake_sb = _FakeSupabase([])
    monkeypatch.setattr("backend.main.get_supabase_client", lambda: fake_sb)
    monkeypatch.setattr("backend.main.CaptureWorker", _FakeWorker)

    from backend.main import app

    with TestClient(app) as client:
        resp = client.get("/streams/00000000-0000-0000-0000-000000000999/status")
        assert resp.status_code == 404
        assert "not active" in resp.json()["detail"]

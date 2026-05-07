"""
backend.capture_main bootstrap / shutdown 단위 테스트.

## 왜 이 테스트가 별도 파일?
이전엔 `backend.main` 의 lifespan 안에서 캡처 워커가 떠졌고 `TestClient(app)` 의
`with` 블록으로 검증했음. cloud-migration 에서 캡처를 standalone 프로세스로 분리한 뒤
(`feature-capture-worker-extraction.md`), 검증도 standalone 함수 호출로 이전.

## 한 카메라 실패 격리
한 카메라 비번 복호화 실패가 다른 카메라 시작을 막으면 안 된다는 "일부 실패 격리"
규칙은 capture_main 으로 이전됐으니 검증도 여기서.

## TestClient 안 쓰는 이유
capture_main 은 FastAPI 가 아니라 standalone asyncio entrypoint. `bootstrap()` 을
직접 await 하고 `shutdown()` 으로 정리 → 더 단순하고 실 동작에 가까움.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from cryptography.fernet import Fernet


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
        # camera_clips INSERT (pending flush) 는 호출될 수 있지만 pending 파일이
        # 비어있으면 실 호출 안 탐.
        return _FakeQuery([])


# ────────────────────────────────────────────────────────────────────────────
# Fake CaptureWorker — start/stop 호출 기록만, 실 스레드 안 띄움
# ────────────────────────────────────────────────────────────────────────────


class _FakeWorker:
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
    """실 Fernet 키 생성 후 env 주입. encrypt/decrypt 실 경로 태움."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("CAMERA_SECRET_KEY", key)
    monkeypatch.setenv("DEV_USER_ID", DEV_USER_ID)
    monkeypatch.setenv("SUPABASE_URL", "http://fake.local")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake")
    # CLIPS_DIR / ENCODED_DIR 을 tmp 로 격리 → 테스트가 레포 storage 건드리지 않음.
    monkeypatch.setenv("CLIPS_DIR", str(tmp_path / "clips"))
    monkeypatch.setenv("ENCODED_DIR", str(tmp_path / "encoded"))

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


@pytest.mark.asyncio
async def test_bootstrap_spawns_one_worker_per_active_camera(fernet_env, monkeypatch):
    """정상 경로: 활성 카메라 2개 → 워커 2개 + runtime 에 반영."""
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

    monkeypatch.setattr("backend.capture_main.get_supabase_client", lambda: fake_sb)
    monkeypatch.setattr("backend.capture_main.CaptureWorker", _FakeWorker)
    _FakeWorker.instances.clear()

    from backend.capture_main import bootstrap, shutdown

    runtime = await bootstrap()
    try:
        assert len(runtime.capture_workers) == 2
        assert set(runtime.capture_workers.keys()) == {cam_a["id"], cam_b["id"]}
        assert runtime.skipped_cameras == []
        assert runtime.startup_error is None
    finally:
        await shutdown(runtime)

    assert len(_FakeWorker.instances) == 2
    assert all(w.started for w in _FakeWorker.instances)
    assert all(w.stopped for w in _FakeWorker.instances)


@pytest.mark.asyncio
async def test_bootstrap_skips_camera_with_undecryptable_password(
    fernet_env, monkeypatch
):
    """한 카메라 비번이 깨진 암호문이어도 다른 카메라는 계속 시작되어야 한다."""
    from backend.crypto import encrypt_password

    cam_good = _make_camera_row(
        display_name="좋은거",
        password_encrypted=encrypt_password("pw-good"),
    )
    cam_bad = _make_camera_row(
        display_name="비번깨짐",
        host="192.168.0.102",
        password_encrypted="not-a-valid-fernet-token",
    )
    fake_sb = _FakeSupabase([cam_good, cam_bad])

    monkeypatch.setattr("backend.capture_main.get_supabase_client", lambda: fake_sb)
    monkeypatch.setattr("backend.capture_main.CaptureWorker", _FakeWorker)
    _FakeWorker.instances.clear()

    from backend.capture_main import bootstrap, shutdown

    runtime = await bootstrap()
    try:
        assert len(runtime.capture_workers) == 1
        assert list(runtime.capture_workers.keys()) == [cam_good["id"]]
        assert len(runtime.skipped_cameras) == 1
        assert cam_bad["id"] in runtime.skipped_cameras[0]
        assert "skip" in (runtime.startup_error or "").lower()
    finally:
        await shutdown(runtime)

    assert len(_FakeWorker.instances) == 1  # good 만 생성됨


@pytest.mark.asyncio
async def test_bootstrap_handles_zero_cameras(fernet_env, monkeypatch):
    """cameras 테이블이 비어있으면 워커 0대 + startup_error 안내."""
    fake_sb = _FakeSupabase([])

    monkeypatch.setattr("backend.capture_main.get_supabase_client", lambda: fake_sb)
    monkeypatch.setattr("backend.capture_main.CaptureWorker", _FakeWorker)
    _FakeWorker.instances.clear()

    from backend.capture_main import bootstrap, shutdown

    runtime = await bootstrap()
    try:
        assert runtime.capture_workers == {}
        assert runtime.skipped_cameras == []
        assert "등록된 카메라 없음" in (runtime.startup_error or "")
    finally:
        await shutdown(runtime)

    assert _FakeWorker.instances == []


@pytest.mark.asyncio
async def test_bootstrap_returns_error_when_supabase_unconfigured(monkeypatch):
    """Supabase 미설정이면 startup_error 만 채우고 워커 0대로 즉시 반환."""
    from backend.supabase_client import SupabaseNotConfigured

    def _raise() -> None:
        raise SupabaseNotConfigured("env missing")

    monkeypatch.setattr("backend.capture_main.get_supabase_client", _raise)

    from backend.capture_main import bootstrap, shutdown

    runtime = await bootstrap()
    try:
        assert runtime.capture_workers == {}
        assert runtime.encode_upload_worker is None
        assert runtime.flush_task is None
        assert "Supabase" in (runtime.startup_error or "")
    finally:
        await shutdown(runtime)

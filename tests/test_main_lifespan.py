"""
backend.main lifespan 테스트 (cloud-migration 분리 후).

이전: 캡처 워커 부팅도 검증했음. 지금: 그건 `test_capture_main.py` 로 이전.
여기는 API 서버 자체의 부팅 분기만 검증.

## 무엇을 검증하나
- Supabase 정상 → /health 200, startup_error null
- Supabase 미설정 → /health 200 (서버는 떠야 함), startup_error 채워짐

`/streams/{id}/status` 는 cloud-migration 으로 삭제됨 (워커 in-memory 상태가
별도 프로세스라 API 서버는 모름). 워커 모니터링 엔드포인트는 후속 spec.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_ok_when_supabase_configured(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://fake.local")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake")

    from backend.main import app

    with TestClient(app) as client:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["startup_error"] is None
        # 워커 필드는 더 이상 노출되지 않음 — capture_main 영역으로 이전.
        assert "capture_workers" not in body
        assert "encode_upload_queue" not in body


def test_health_records_startup_error_when_supabase_unconfigured(monkeypatch):
    """Supabase env 가 없으면 startup_error 에 사유 기록, /health 는 여전히 200."""
    from backend.supabase_client import SupabaseNotConfigured

    def _raise() -> None:
        raise SupabaseNotConfigured("env missing")

    monkeypatch.setattr("backend.main.get_supabase_client", _raise)

    from backend.main import app

    with TestClient(app) as client:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert "Supabase" in (body["startup_error"] or "")

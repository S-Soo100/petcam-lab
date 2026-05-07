"""backend.health unit tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.health import make_health_app


def test_health_returns_200_without_status_check():
    app = make_health_app("vlm-worker")
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "service": "vlm-worker"}


def test_health_returns_200_when_status_check_true():
    app = make_health_app("vlm-worker", status_check=lambda: True)
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "service": "vlm-worker"}


def test_health_returns_503_when_status_check_false():
    app = make_health_app("vlm-worker", status_check=lambda: False)
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 503
        assert r.json() == {"ok": False, "service": "vlm-worker"}


def test_health_no_docs_routes():
    """/docs, /redoc, /openapi.json 비활성 — 라벨링/내부 워커는 외부 노출 X."""
    app = make_health_app("vlm-worker")
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404

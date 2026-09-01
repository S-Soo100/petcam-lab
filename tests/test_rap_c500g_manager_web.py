from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from fastapi.testclient import TestClient

from backend.rap_c500g_capture import CameraConfig
from backend.rap_c500g_manager_probe import CameraProbeStatus, VolumeStatus
from backend.rap_c500g_manager_store import (
    CameraRuntimeState,
    ManagerSnapshot,
    ManagerStore,
)
from backend.rap_c500g_manager_web import ManagerWebContext, create_manager_app


@dataclass
class FakeManager:
    active: bool = False
    diagnostic_calls: int = 0

    def is_production_active(self) -> bool:
        return self.active

    def run_diagnostic(self, *, duration_sec: float) -> dict[str, object]:
        self.diagnostic_calls += 1
        return {"duration_sec": duration_sec, "cameras": {"cam01": "captured"}}


def _client(tmp_path: Path, *, active: bool = False) -> tuple[TestClient, ManagerStore, FakeManager]:
    store = ManagerStore(tmp_path / "manager.sqlite3")
    store.write_snapshot(
        ManagerSnapshot(
            manager_state="recording",
            updated_at="2026-09-01T20:05:00+09:00",
            current_slot="2026-09-01T20:00:00+09:00",
            next_slot="2026-09-01T20:30:00+09:00",
            volume={
                "name": "RAP-C500G",
                "ready": True,
                "writable": True,
                "free_bytes": 80_000_000_000,
            },
            cameras={
                "cam01": CameraRuntimeState(
                    camera_key="cam01",
                    ip="192.168.50.23",
                    probe_state="online",
                    capture_state="recording",
                    retry_count=0,
                    file_bytes=84_200_000,
                    file_growing=True,
                    last_frame_at="2026-09-01T20:04:58+09:00",
                    error_code=None,
                )
            },
            recent_completed=(),
            incidents=(),
            sync={"pending": 0, "failed": 0},
        )
    )
    manager = FakeManager(active=active)
    configs = (
        CameraConfig("cam01", "192.168.50.23", "user", "secret"),
        CameraConfig("cam02", "192.168.50.24", "user", "secret"),
        CameraConfig("cam03", "192.168.50.25", "user", "secret"),
    )
    context = ManagerWebContext(
        manager=manager,
        store=store,
        configs=configs,
        list_volumes=lambda: [
            VolumeStatus("RAP-C500G", True, None, True, 128_000_000_000, 80_000_000_000, "/Volumes/RAP-C500G")
        ],
        camera_probe=lambda config: CameraProbeStatus(
            config.camera_key,
            config.ip,
            True,
            True,
            "2026-09-01T11:00:00+00:00",
            None,
        ),
    )
    return TestClient(create_manager_app(context)), store, manager


def test_status_and_dashboard_are_secret_free_and_responsive(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)

    status = client.get("/api/status")
    page = client.get("/")
    body = status.text + page.text

    assert status.status_code == 200
    assert page.status_code == 200
    assert "rtsp://" not in body
    assert "secret" not in body.lower()
    assert "카메라 상태" in page.text
    assert "camera-grid" in page.text
    assert "thumbnail-placeholder" in page.text
    assert "@media" in page.text
    assert page.headers["content-security-policy"].startswith("default-src 'self'")
    assert page.headers["x-frame-options"] == "DENY"


def test_settings_pending_accepts_only_allowlisted_values(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)

    response = client.put(
        "/api/settings/pending",
        json={
            "start_local": "20:00",
            "end_local": "08:00",
            "selected_cameras": ["cam01", "cam03"],
            "volume_name": "RAP-C500G",
            "max_capture_retries": 3,
        },
    )

    assert response.status_code == 200
    assert store.load_pending_plan() is not None
    assert store.load_pending_plan().selected_cameras == ("cam01", "cam03")

    bad_camera = client.put(
        "/api/settings/pending",
        json={
            "start_local": "20:00",
            "end_local": "08:00",
            "selected_cameras": ["cam99"],
            "volume_name": "RAP-C500G",
            "max_capture_retries": 3,
        },
    )
    bad_path = client.put(
        "/api/settings/pending",
        json={
            "start_local": "20:00",
            "end_local": "08:00",
            "selected_cameras": ["cam01"],
            "volume_name": "../private",
            "max_capture_retries": 3,
        },
    )
    assert bad_camera.status_code == 422
    assert bad_path.status_code == 422


def test_mutation_rejects_non_loopback_and_foreign_origin(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    payload = {
        "start_local": "20:00",
        "end_local": "08:00",
        "selected_cameras": ["cam01"],
        "volume_name": "RAP-C500G",
        "max_capture_retries": 3,
    }

    forwarded = client.put(
        "/api/settings/pending",
        headers={"x-forwarded-for": "203.0.113.10"},
        json=payload,
    )
    foreign_origin = client.put(
        "/api/settings/pending",
        headers={"origin": "https://evil.example"},
        json=payload,
    )

    assert forwarded.status_code == 403
    assert foreign_origin.status_code == 403


def test_probe_and_volume_responses_do_not_expose_mount_or_rtsp(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)

    volumes = client.get("/api/volumes")
    probes = client.post("/api/probes/cameras")

    assert volumes.status_code == 200
    assert probes.status_code == 200
    body = volumes.text + probes.text
    assert "/Volumes/" not in body
    assert "rtsp://" not in body
    assert [item["camera_key"] for item in probes.json()] == ["cam01", "cam02", "cam03"]


def test_diagnostic_is_fixed_to_sixty_seconds_and_blocked_during_production(tmp_path: Path) -> None:
    client, _, manager = _client(tmp_path)

    ok = client.post("/api/diagnostics/recording")
    assert ok.status_code == 200
    assert manager.diagnostic_calls == 1
    assert ok.json()["duration_sec"] == 60.0

    manager.active = True
    blocked = client.post("/api/diagnostics/recording")
    assert blocked.status_code == 409
    assert manager.diagnostic_calls == 1


def test_settings_and_incidents_endpoints(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    store.append_event("camera_terminal", {"camera_key": "cam02", "code": "offline"})

    settings = client.get("/api/settings")
    incidents = client.get("/api/incidents")

    assert settings.status_code == 200
    assert settings.json()["active"]["volume_name"] == "RAP-C500G"
    assert incidents.status_code == 200
    assert incidents.json()[0]["kind"] == "camera_terminal"

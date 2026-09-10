from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from backend.rap_c500g_manager_main import DEFAULT_MANAGER_PORT, main, read_status
from backend.rap_c500g_manager_store import (
    CameraRuntimeState,
    ManagerSnapshot,
    ManagerStore,
)


def _snapshot(*, state: str, incident: bool = False) -> ManagerSnapshot:
    now = datetime.now().astimezone()
    return ManagerSnapshot(
        manager_state=state,
        updated_at=now.isoformat(),
        current_slot="2026-09-01T20:00:00+09:00",
        next_slot="2026-09-01T20:30:00+09:00",
        volume={"name": "RAP-C500G", "ready": state != "blocked_storage"},
        cameras={
            "cam01": CameraRuntimeState(
                "cam01", "192.168.50.23", "online", "recording", 0, 12, True, None, None
            )
        },
        recent_completed=(),
        incidents=(
            ({"state": "open", "camera_key": "cam02", "code": "offline"},)
            if incident
            else ()
        ),
        sync={"pending": 0, "failed": 0},
    )


def test_read_status_returns_exit_zero_for_healthy_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "manager.sqlite3"
    store = ManagerStore(path)
    store.write_snapshot(_snapshot(state="recording"))

    code, payload = read_status(path)

    assert code == 0
    assert payload["manager_state"] == "recording"
    encoded = json.dumps(payload)
    assert "rtsp://" not in encoded
    assert "/Volumes/" not in encoded


def test_read_status_distinguishes_unavailable_and_owner_action(tmp_path: Path) -> None:
    missing_code, missing = read_status(tmp_path / "missing.sqlite3")
    assert missing_code == 2
    assert missing["manager_state"] == "unavailable"

    path = tmp_path / "manager.sqlite3"
    store = ManagerStore(path)
    store.write_snapshot(_snapshot(state="blocked_storage"))
    blocked_code, _ = read_status(path)
    assert blocked_code == 3

    store.write_snapshot(_snapshot(state="scheduled", incident=True))
    incident_code, _ = read_status(path)
    assert incident_code == 3


def test_stale_idle_snapshot_is_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "manager.sqlite3"
    store = ManagerStore(path)
    snapshot = _snapshot(state="idle")
    store.write_snapshot(
        ManagerSnapshot(
            manager_state=snapshot.manager_state,
            updated_at="2020-01-01T00:00:00+09:00",
            current_slot=snapshot.current_slot,
            next_slot=snapshot.next_slot,
            volume=snapshot.volume,
            cameras=snapshot.cameras,
            recent_completed=snapshot.recent_completed,
            incidents=snapshot.incidents,
            sync=snapshot.sync,
        )
    )

    code, payload = read_status(path)

    assert code == 2
    assert payload["manager_state"] == "unavailable"


def test_status_json_command_is_read_only_and_machine_readable(
    tmp_path: Path, capsys
) -> None:
    path = tmp_path / "manager.sqlite3"
    store = ManagerStore(path)
    store.write_snapshot(_snapshot(state="idle"))

    code = main(["--state-path", str(path), "status", "--json"])

    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output["manager_state"] == "idle"
    assert store.load_pending_plan() is None


def test_diagnostic_duration_is_fixed_to_sixty_seconds() -> None:
    try:
        main(["diagnostic", "--duration", "30"])
    except SystemExit as error:
        assert "60" in str(error)
    else:
        raise AssertionError("non-60 diagnostic duration must fail before runtime setup")


def test_manager_uses_dedicated_port_that_does_not_conflict_with_yolo_worker() -> None:
    assert DEFAULT_MANAGER_PORT == 8766


def test_manager_process_lifecycle_records_clean_stop(tmp_path: Path) -> None:
    store = ManagerStore(tmp_path / "process.sqlite3")
    now = datetime.now().astimezone()
    from backend.rap_c500g_capture import CameraConfig
    from backend.rap_c500g_manager_probe import VolumeStatus
    from backend.rap_c500g_manager_runtime import RapC500GManager

    configs = tuple(CameraConfig(f"cam0{i}", f"192.168.50.{22+i}", "u", "p") for i in range(1, 4))
    manager = RapC500GManager(
        configs=configs, store=store, uploader=object(), repository=object(),
        volume_validator=lambda _: VolumeStatus("RAP-C500G", False, "missing", False, 0, 0, None),
        clock=lambda: now,
    )
    manager.start()
    manager.stop()

    kinds = [item["kind"] for item in store.read_events(limit=10)]
    assert "manager_started" in kinds
    assert "manager_stopped" in kinds
    assert store.classify_restart_reason() == "clean_shutdown"

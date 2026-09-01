from __future__ import annotations

import json
from pathlib import Path

from backend.rap_c500g_manager_main import main, read_status
from backend.rap_c500g_manager_store import (
    CameraRuntimeState,
    ManagerSnapshot,
    ManagerStore,
)


def _snapshot(*, state: str, incident: bool = False) -> ManagerSnapshot:
    return ManagerSnapshot(
        manager_state=state,
        updated_at="2026-09-01T20:05:00+09:00",
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

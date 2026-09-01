from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.rap_c500g_manager_store import (
    CameraRuntimeState,
    ManagerSnapshot,
    ManagerStore,
)


def test_store_starts_with_safe_default_plan(tmp_path: Path) -> None:
    store = ManagerStore(tmp_path / "manager.sqlite3")

    plan = store.load_plan()

    assert plan.revision == 0
    assert plan.start_local == "20:00"
    assert plan.end_local == "08:00"
    assert plan.selected_cameras == ("cam01", "cam02", "cam03")
    assert plan.volume_name == "RAP-C500G"
    assert plan.max_capture_retries == 3
    assert store.load_pending_plan() is None


def test_store_applies_pending_plan_atomically(tmp_path: Path) -> None:
    store = ManagerStore(tmp_path / "manager.sqlite3")
    pending = store.save_pending_plan(
        start_local="21:00",
        end_local="07:30",
        selected_cameras=("cam01", "cam03"),
        volume_name="RAP-C500G",
        max_capture_retries=2,
    )

    assert store.load_plan().revision == 0
    assert store.load_pending_plan() == pending

    applied = store.apply_pending_plan()

    assert applied.revision == 1
    assert applied.selected_cameras == ("cam01", "cam03")
    assert applied.start_local == "21:00"
    assert store.load_pending_plan() is None
    with sqlite3.connect(store.path) as connection:
        rows = connection.execute(
            "SELECT slot, revision FROM manager_plan ORDER BY slot"
        ).fetchall()
    assert rows == [("active", 1)]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("start_local", "8pm"),
        ("end_local", "24:30"),
        ("selected_cameras", ("cam04",)),
        ("selected_cameras", ()),
        ("volume_name", "../RAP-C500G"),
        ("max_capture_retries", 6),
    ],
)
def test_store_rejects_unsafe_plan_values(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    store = ManagerStore(tmp_path / "manager.sqlite3")
    values: dict[str, object] = {
        "start_local": "20:00",
        "end_local": "08:00",
        "selected_cameras": ("cam01", "cam02", "cam03"),
        "volume_name": "RAP-C500G",
        "max_capture_retries": 3,
    }
    values[field] = value

    with pytest.raises(ValueError):
        store.save_pending_plan(**values)  # type: ignore[arg-type]


def test_snapshot_round_trip_is_secret_free(tmp_path: Path) -> None:
    store = ManagerStore(tmp_path / "manager.sqlite3")
    snapshot = ManagerSnapshot(
        manager_state="recording",
        updated_at="2026-09-01T20:01:00+09:00",
        current_slot="2026-09-01T20:00:00+09:00",
        next_slot="2026-09-01T20:30:00+09:00",
        volume={"name": "RAP-C500G", "ready": True, "free_bytes": 80_000_000_000},
        cameras={
            "cam01": CameraRuntimeState(
                camera_key="cam01",
                ip="192.168.50.23",
                probe_state="online",
                capture_state="recording",
                retry_count=0,
                file_bytes=12_345,
                file_growing=True,
                last_frame_at="2026-09-01T20:00:59+09:00",
                error_code=None,
            )
        },
        recent_completed=(),
        incidents=(),
        sync={"pending": 0, "failed": 0},
    )

    store.write_snapshot(snapshot)

    restored = store.read_snapshot()
    assert restored == snapshot
    raw = json.dumps(restored.to_public_dict(), ensure_ascii=False)
    assert "rtsp://" not in raw
    assert "password" not in raw.lower()
    assert "/Volumes/" not in raw
    assert "192.168.50.23" in raw


def test_events_are_append_only_and_bounded_on_read(tmp_path: Path) -> None:
    store = ManagerStore(tmp_path / "manager.sqlite3")
    store.append_event("camera_terminal", {"camera_key": "cam02", "code": "rtsp_offline"})
    store.append_event("camera_recovered", {"camera_key": "cam02"})

    assert [event["kind"] for event in store.read_events(limit=1)] == [
        "camera_recovered"
    ]


def test_capture_claim_is_atomic_and_survives_manager_restart(tmp_path: Path) -> None:
    path = tmp_path / "manager.sqlite3"
    first = ManagerStore(path)

    assert first.claim_capture("2026-09-01T20:00:00+09:00", "cam01") is True
    assert first.claim_capture("2026-09-01T20:00:00+09:00", "cam01") is False

    reopened = ManagerStore(path)
    assert reopened.claim_capture("2026-09-01T20:00:00+09:00", "cam01") is False
    assert reopened.read_capture_claims() == {
        ("2026-09-01T20:00:00+09:00", "cam01")
    }


def test_unfinished_capture_claims_can_be_released_after_process_preflight(tmp_path: Path) -> None:
    store = ManagerStore(tmp_path / "manager.sqlite3")
    slot = "2026-09-01T20:00:00+09:00"
    assert store.claim_capture(slot, "cam01") is True
    assert store.claim_capture(slot, "cam02") is True
    assert store.claim_capture(slot, "cam03") is True
    store.mark_capture_claim(slot, "cam01", "completed")
    store.mark_capture_claim(
        slot,
        "cam02",
        "finalizing",
        payload={"root": "/Volumes/RAP-C500G/RAP-c500g-recordings"},
    )

    assert store.release_unfinished_claims() == 1
    assert store.read_capture_claims(statuses={"completed", "terminal"}) == {
        (slot, "cam01")
    }
    assert store.claim_capture(slot, "cam02") is False
    assert store.read_finalizing_claims()[0]["camera_key"] == "cam02"

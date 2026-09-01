from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from threading import Event, Thread
from typing import Any, Callable
from zoneinfo import ZoneInfo

from backend.rap_c500g_capture import CameraConfig, RawCaptureResult
from backend.rap_c500g_manager_probe import VolumeStatus
from backend.rap_c500g_manager_runtime import RapC500GManager, manager_slot
from backend.rap_c500g_manager_store import ManagerStore


KST = ZoneInfo("Asia/Seoul")
CONFIGS = tuple(
    CameraConfig(f"cam0{index}", f"192.168.50.{22 + index}", f"u{index}", f"p{index}")
    for index in range(1, 4)
)


class ImmediateFuture:
    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        try:
            self._result = fn(*args, **kwargs)
            self._error: BaseException | None = None
        except BaseException as error:
            self._result = None
            self._error = error

    def done(self) -> bool:
        return True

    def result(self) -> Any:
        if self._error is not None:
            raise self._error
        return self._result


class ImmediateExecutor:
    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> ImmediateFuture:
        return ImmediateFuture(fn, *args, **kwargs)


class ManualFuture:
    def __init__(self) -> None:
        self.complete = False

    def done(self) -> bool:
        return self.complete

    def result(self) -> str:
        return "captured"


class ManualExecutor:
    def __init__(self) -> None:
        self.futures: list[ManualFuture] = []

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> ManualFuture:
        del fn, args, kwargs
        future = ManualFuture()
        self.futures.append(future)
        return future


def ready_volume(tmp_path: Path) -> VolumeStatus:
    return VolumeStatus(
        name="RAP-C500G",
        ready=True,
        reason=None,
        writable=True,
        total_bytes=120 * 1024**3,
        free_bytes=80 * 1024**3,
        mount_point=str(tmp_path),
    )


def test_manager_slot_uses_wall_clock_boundaries_and_crosses_midnight() -> None:
    evening = manager_slot(
        datetime(2026, 9, 1, 20, 17, tzinfo=KST), "20:00", "08:00"
    )
    morning = manager_slot(
        datetime(2026, 9, 2, 7, 45, tzinfo=KST), "20:00", "08:00"
    )

    assert evening is not None
    assert evening.scheduled_start_kst.isoformat() == "2026-09-01T20:00:00+09:00"
    assert evening.duration_sec == 13 * 60
    assert morning is not None
    assert morning.scheduled_start_kst.isoformat() == "2026-09-02T07:30:00+09:00"
    assert manager_slot(
        datetime(2026, 9, 2, 8, 0, tzinfo=KST), "20:00", "08:00"
    ) is None


def test_missing_selected_volume_blocks_every_camera(tmp_path: Path) -> None:
    captured: list[str] = []
    store = ManagerStore(tmp_path / "state/manager.sqlite3")
    now = datetime(2026, 9, 1, 20, 0, tzinfo=KST)
    manager = RapC500GManager(
        configs=CONFIGS,
        store=store,
        uploader=object(),
        repository=object(),
        volume_validator=lambda _: VolumeStatus(
            "RAP-C500G", False, "volume_missing", False, 0, 0, None
        ),
        capture_fn=lambda config, identity, paths, *, duration_sec: captured.append(
            config.camera_key
        ),
        capture_executor=ImmediateExecutor(),
        sync_executor=ImmediateExecutor(),
        clock=lambda: now,
    )

    manager.run_once(now)

    assert captured == []
    snapshot = store.read_snapshot()
    assert snapshot is not None
    assert snapshot.manager_state == "blocked_storage"
    assert snapshot.volume["reason"] == "volume_missing"


def test_same_camera_and_slot_is_started_only_once(tmp_path: Path) -> None:
    captured: list[str] = []
    store = ManagerStore(tmp_path / "state/manager.sqlite3")

    def capture(config: CameraConfig, identity: Any, paths: Any, *, duration_sec: float) -> str:
        captured.append(config.camera_key)
        return config.camera_key

    now = datetime(2026, 9, 1, 20, 0, tzinfo=KST)
    manager = RapC500GManager(
        configs=CONFIGS,
        store=store,
        uploader=object(),
        repository=object(),
        volume_validator=lambda _: ready_volume(tmp_path / "RAP-C500G"),
        capture_fn=capture,
        capture_executor=ImmediateExecutor(),
        sync_executor=ImmediateExecutor(),
        sync_fn=lambda *_: None,
        clock=lambda: now,
    )

    manager.run_once(now)
    manager.run_once(now)

    assert captured == ["cam01", "cam02", "cam03"]
    snapshot = store.read_snapshot()
    assert snapshot is not None
    assert {state.capture_state for state in snapshot.cameras.values()} == {"captured"}


def test_restart_does_not_claim_the_same_camera_slot_twice(tmp_path: Path) -> None:
    captured: list[str] = []
    store_path = tmp_path / "state/manager.sqlite3"
    now = datetime(2026, 9, 1, 20, 0, tzinfo=KST)

    def make_manager() -> RapC500GManager:
        return RapC500GManager(
            configs=CONFIGS,
            store=ManagerStore(store_path),
            uploader=object(),
            repository=object(),
            volume_validator=lambda _: ready_volume(tmp_path / "RAP-C500G"),
            capture_fn=lambda config, identity, paths, *, duration_sec: captured.append(
                config.camera_key
            ),
            capture_executor=ImmediateExecutor(),
            sync_executor=ImmediateExecutor(),
            sync_fn=lambda *_: None,
            clock=lambda: now,
        )

    make_manager().run_once(now)
    make_manager().run_once(now)

    assert captured == ["cam01", "cam02", "cam03"]


def test_completed_previous_slot_is_synced_after_boundary_crosses(tmp_path: Path) -> None:
    executor = ManualExecutor()
    synced: list[Path] = []
    store = ManagerStore(tmp_path / "state/manager.sqlite3")
    current = [datetime(2026, 9, 1, 20, 0, tzinfo=KST)]
    manager = RapC500GManager(
        configs=CONFIGS,
        store=store,
        uploader=object(),
        repository=object(),
        volume_validator=lambda _: ready_volume(tmp_path / "RAP-C500G"),
        capture_executor=executor,
        sync_executor=ImmediateExecutor(),
        sync_fn=lambda root, *_: synced.append(root),
        clock=lambda: current[0],
    )

    manager.run_once(current[0])
    assert len(executor.futures) == 3
    for future in executor.futures:
        future.complete = True
    for config in CONFIGS:
        store.mark_capture_claim(
            "2026-09-01T20:00:00+09:00", config.camera_key, "completed"
        )
    current[0] = datetime(2026, 9, 1, 20, 30, tzinfo=KST)
    manager.run_once(current[0])

    assert len(synced) == 1


def test_camera_retry_is_bounded_and_does_not_repeat_healthy_cameras(tmp_path: Path) -> None:
    attempts: defaultdict[str, int] = defaultdict(int)
    waits: list[float] = []
    store = ManagerStore(tmp_path / "state/manager.sqlite3")

    def capture(config: CameraConfig, identity: Any, paths: Any, *, duration_sec: float) -> str:
        attempts[config.camera_key] += 1
        if config.camera_key == "cam02" and attempts[config.camera_key] < 3:
            raise RuntimeError("offline")
        return config.camera_key

    now = datetime(2026, 9, 1, 20, 0, tzinfo=KST)
    manager = RapC500GManager(
        configs=CONFIGS,
        store=store,
        uploader=object(),
        repository=object(),
        volume_validator=lambda _: ready_volume(tmp_path / "RAP-C500G"),
        capture_fn=capture,
        capture_executor=ImmediateExecutor(),
        sync_executor=ImmediateExecutor(),
        sync_fn=lambda *_: None,
        retry_wait=lambda delay: waits.append(delay) or False,
        clock=lambda: now,
    )

    manager.run_once(now)

    assert dict(attempts) == {"cam01": 1, "cam02": 3, "cam03": 1}
    assert waits == [10.0, 30.0]
    snapshot = store.read_snapshot()
    assert snapshot is not None
    assert snapshot.cameras["cam02"].capture_state == "captured"
    assert snapshot.cameras["cam02"].retry_count == 2


def test_terminal_camera_failure_notifies_once_after_bounded_retries(tmp_path: Path) -> None:
    attempts: defaultdict[str, int] = defaultdict(int)
    notifications: list[tuple[str, dict[str, Any]]] = []
    now = datetime(2026, 9, 1, 20, 0, tzinfo=KST)

    def capture(config: CameraConfig, identity: Any, paths: Any, *, duration_sec: float) -> str:
        attempts[config.camera_key] += 1
        if config.camera_key == "cam02":
            raise RuntimeError("offline")
        return config.camera_key

    manager = RapC500GManager(
        configs=CONFIGS,
        store=ManagerStore(tmp_path / "state/manager.sqlite3"),
        uploader=object(),
        repository=object(),
        volume_validator=lambda _: ready_volume(tmp_path / "RAP-C500G"),
        capture_fn=capture,
        capture_executor=ImmediateExecutor(),
        sync_executor=ImmediateExecutor(),
        sync_fn=lambda *_: None,
        retry_wait=lambda _: False,
        notifier=lambda kind, payload: notifications.append((kind, dict(payload))),
        clock=lambda: now,
    )

    manager.run_once(now)
    manager.run_once(now)

    assert attempts["cam02"] == 4
    assert notifications == [
        (
            "camera_terminal",
            {
                "state": "open",
                "camera_key": "cam02",
                "slot": "2026-09-01T20:00:00+09:00",
                "code": "capture_RuntimeError",
            },
        )
    ]


def test_manager_does_not_start_new_capture_at_end_time(tmp_path: Path) -> None:
    captured: list[str] = []
    now = datetime(2026, 9, 2, 8, 0, tzinfo=KST)
    manager = RapC500GManager(
        configs=CONFIGS,
        store=ManagerStore(tmp_path / "state/manager.sqlite3"),
        uploader=object(),
        repository=object(),
        volume_validator=lambda _: ready_volume(tmp_path / "RAP-C500G"),
        capture_fn=lambda config, identity, paths, *, duration_sec: captured.append(
            config.camera_key
        ),
        capture_executor=ImmediateExecutor(),
        sync_executor=ImmediateExecutor(),
        sync_fn=lambda *_: None,
        clock=lambda: now,
    )

    manager.run_once(now)

    assert captured == []


def test_next_slot_capture_starts_while_previous_slot_is_still_finalizing(
    tmp_path: Path,
) -> None:
    verification = ManualExecutor()
    captured: list[tuple[str, str]] = []
    current = [datetime(2026, 9, 1, 20, 0, tzinfo=KST)]

    def raw_capture(config, identity, paths, *, duration_sec):
        captured.append((identity.scheduled_start_kst.isoformat(), config.camera_key))
        return RawCaptureResult(config=config, identity=identity, paths=paths)

    manager = RapC500GManager(
        configs=CONFIGS,
        store=ManagerStore(tmp_path / "state/manager.sqlite3"),
        uploader=object(),
        repository=object(),
        volume_validator=lambda _: ready_volume(tmp_path / "RAP-C500G"),
        capture_fn=raw_capture,
        finalize_fn=lambda raw: raw,  # type: ignore[return-value]
        capture_executor=ImmediateExecutor(),
        verification_executor=verification,
        sync_executor=ImmediateExecutor(),
        sync_fn=lambda *_: None,
        clock=lambda: current[0],
    )

    manager.run_once(current[0])
    assert len(verification.futures) == 3
    current[0] = datetime(2026, 9, 1, 20, 30, tzinfo=KST)
    manager.run_once(current[0])

    assert len(captured) == 6
    assert len(verification.futures) == 6


def test_failed_sync_is_retried_without_recapturing(tmp_path: Path) -> None:
    attempts = 0
    captured: list[str] = []
    now = datetime(2026, 9, 1, 20, 0, tzinfo=KST)

    def sync(*_args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("r2 unavailable")
        return None

    manager = RapC500GManager(
        configs=CONFIGS,
        store=ManagerStore(tmp_path / "state/manager.sqlite3"),
        uploader=object(),
        repository=object(),
        volume_validator=lambda _: ready_volume(tmp_path / "RAP-C500G"),
        capture_fn=lambda config, *_args, **_kwargs: captured.append(config.camera_key),
        capture_executor=ImmediateExecutor(),
        sync_executor=ImmediateExecutor(),
        sync_fn=sync,
        clock=lambda: now,
    )

    manager.run_once(now)
    manager.run_once(now)
    manager.run_once(now)

    assert attempts == 2
    assert captured == ["cam01", "cam02", "cam03"]


def test_scheduler_fatal_error_stops_loop_and_requests_process_restart(
    tmp_path: Path,
) -> None:
    restarted = Event()
    manager = RapC500GManager(
        configs=CONFIGS,
        store=ManagerStore(tmp_path / "state/manager.sqlite3"),
        uploader=object(),
        repository=object(),
        volume_validator=lambda _: (_ for _ in ()).throw(RuntimeError("boom")),
        capture_executor=ImmediateExecutor(),
        verification_executor=ImmediateExecutor(),
        sync_executor=ImmediateExecutor(),
        fatal_callback=restarted.set,
        clock=lambda: datetime(2026, 9, 1, 20, 0, tzinfo=KST),
    )

    manager.start()
    assert restarted.wait(1.0)
    manager.stop()

    assert manager.store.read_events(limit=1)[0]["kind"] == "manager_fatal"


def test_restart_resumes_durable_finalization_without_recapturing(tmp_path: Path) -> None:
    store = ManagerStore(tmp_path / "state/manager.sqlite3")
    slot = "2026-09-01T20:00:00+09:00"
    root = tmp_path / "RAP-C500G" / "RAP-c500g-recordings"
    store.claim_capture(slot, "cam01")
    store.mark_capture_claim(
        slot,
        "cam01",
        "finalizing",
        payload={
            "root": str(root),
            "actual_start": slot,
            "partial": False,
            "attempt": 0,
        },
    )
    finalized: list[str] = []

    manager = RapC500GManager(
        configs=CONFIGS,
        store=store,
        uploader=object(),
        repository=object(),
        volume_validator=lambda _: ready_volume(tmp_path / "RAP-C500G"),
        capture_fn=lambda *_args, **_kwargs: "unused",
        finalize_fn=lambda raw: finalized.append(raw.config.camera_key),  # type: ignore[return-value]
        capture_executor=ImmediateExecutor(),
        verification_executor=ImmediateExecutor(),
        sync_executor=ImmediateExecutor(),
        clock=lambda: datetime(2026, 9, 1, 20, 5, tzinfo=KST),
    )
    manager._consume_done()

    assert finalized == ["cam01"]
    assert store.read_capture_claims(statuses={"completed"}) == {(slot, "cam01")}


def test_diagnostic_holds_operation_mutex_across_next_schedule_boundary(
    tmp_path: Path,
) -> None:
    diagnostic_started = Event()
    release_diagnostic = Event()
    scheduled_finished = Event()
    now = datetime(2026, 9, 1, 19, 59, tzinfo=KST)

    def capture(*_args, **_kwargs):
        diagnostic_started.set()
        release_diagnostic.wait(1.0)
        return "captured"

    manager = RapC500GManager(
        configs=CONFIGS,
        store=ManagerStore(tmp_path / "state/manager.sqlite3"),
        uploader=object(),
        repository=object(),
        volume_validator=lambda _: ready_volume(tmp_path / "RAP-C500G"),
        capture_fn=capture,
        capture_executor=ImmediateExecutor(),
        verification_executor=ImmediateExecutor(),
        sync_executor=ImmediateExecutor(),
        sync_fn=lambda *_: None,
        clock=lambda: now,
    )
    diagnostic = Thread(target=manager.run_diagnostic)
    diagnostic.start()
    assert diagnostic_started.wait(1.0)
    scheduled = Thread(
        target=lambda: (
            manager.run_once(datetime(2026, 9, 1, 20, 0, tzinfo=KST)),
            scheduled_finished.set(),
        )
    )
    scheduled.start()

    assert not scheduled_finished.wait(0.05)
    release_diagnostic.set()
    diagnostic.join(1.0)
    scheduled.join(1.0)
    assert scheduled_finished.is_set()


def test_idle_manager_continues_pending_sync(tmp_path: Path) -> None:
    store = ManagerStore(tmp_path / "state/manager.sqlite3")
    slot = "2026-09-01T07:30:00+09:00"
    store.claim_capture(slot, "cam01")
    store.mark_capture_claim(slot, "cam01", "completed")
    synced: list[Path] = []
    now = datetime(2026, 9, 1, 8, 1, tzinfo=KST)
    manager = RapC500GManager(
        configs=CONFIGS,
        store=store,
        uploader=object(),
        repository=object(),
        volume_validator=lambda _: ready_volume(tmp_path / "RAP-C500G"),
        capture_fn=lambda *_args, **_kwargs: "unused",
        capture_executor=ImmediateExecutor(),
        verification_executor=ImmediateExecutor(),
        sync_executor=ImmediateExecutor(),
        sync_fn=lambda root, *_: synced.append(root),
        clock=lambda: now,
    )

    manager.run_once(now)
    manager.run_once(now)

    assert len(synced) == 1


def test_fatal_callback_runs_even_if_event_store_is_broken(tmp_path: Path) -> None:
    restarted = Event()
    store = ManagerStore(tmp_path / "state/manager.sqlite3")
    store.append_event = lambda *_args, **_kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        RuntimeError("sqlite unavailable")
    )
    manager = RapC500GManager(
        configs=CONFIGS,
        store=store,
        uploader=object(),
        repository=object(),
        volume_validator=lambda _: (_ for _ in ()).throw(RuntimeError("boom")),
        capture_executor=ImmediateExecutor(),
        verification_executor=ImmediateExecutor(),
        sync_executor=ImmediateExecutor(),
        fatal_callback=restarted.set,
        clock=lambda: datetime(2026, 9, 1, 20, 0, tzinfo=KST),
    )

    manager.start()
    assert restarted.wait(1.0)
    manager.stop()


def test_shutdown_cancellation_releases_running_claim_instead_of_terminal(
    tmp_path: Path,
) -> None:
    store = ManagerStore(tmp_path / "state/manager.sqlite3")
    now = datetime(2026, 9, 1, 20, 0, tzinfo=KST)
    manager = RapC500GManager(
        configs=CONFIGS,
        store=store,
        uploader=object(),
        repository=object(),
        volume_validator=lambda _: ready_volume(tmp_path / "RAP-C500G"),
        capture_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("terminated")
        ),
        capture_executor=ImmediateExecutor(),
        verification_executor=ImmediateExecutor(),
        sync_executor=ImmediateExecutor(),
        clock=lambda: now,
    )
    slot = manager_slot(now, "20:00", "08:00")
    assert slot is not None
    store.claim_capture(slot.scheduled_start_kst.isoformat(), "cam01")
    manager._stop.set()

    try:
        manager._capture_with_retries(CONFIGS[0], tmp_path / "RAP-C500G" / "RAP-c500g-recordings", slot, 3)
    except RuntimeError:
        pass

    assert store.read_capture_claims() == set()


def test_finalization_waits_for_late_usb_mount_then_resumes(tmp_path: Path) -> None:
    store = ManagerStore(tmp_path / "state/manager.sqlite3")
    slot = "2026-09-01T20:00:00+09:00"
    root = tmp_path / "RAP-C500G" / "RAP-c500g-recordings"
    store.claim_capture(slot, "cam01")
    store.mark_capture_claim(
        slot,
        "cam01",
        "finalizing",
        payload={
            "root": str(root),
            "actual_start": slot,
            "partial": False,
            "attempt": 0,
        },
    )
    mounted = [False]
    finalized: list[str] = []

    def volume(_name: str) -> VolumeStatus:
        if mounted[0]:
            return ready_volume(tmp_path / "RAP-C500G")
        return VolumeStatus("RAP-C500G", False, "volume_missing", False, 0, 0, None)

    manager = RapC500GManager(
        configs=CONFIGS,
        store=store,
        uploader=object(),
        repository=object(),
        volume_validator=volume,
        capture_fn=lambda *_args, **_kwargs: "unused",
        finalize_fn=lambda raw: finalized.append(raw.config.camera_key),  # type: ignore[return-value]
        capture_executor=ImmediateExecutor(),
        verification_executor=ImmediateExecutor(),
        sync_executor=ImmediateExecutor(),
        sync_fn=lambda *_: None,
        clock=lambda: datetime(2026, 9, 2, 9, 0, tzinfo=KST),
    )
    assert finalized == []
    assert store.read_capture_claims(statuses={"finalizing"}) == {(slot, "cam01")}

    mounted[0] = True
    manager.run_once(datetime(2026, 9, 2, 9, 0, tzinfo=KST))
    manager.run_once(datetime(2026, 9, 2, 9, 0, 1, tzinfo=KST))

    assert finalized == ["cam01"]
    assert store.read_capture_claims(statuses={"completed"}) == {(slot, "cam01")}


def test_completed_bundle_sync_uses_its_original_volume_after_plan_change(
    tmp_path: Path,
) -> None:
    store = ManagerStore(tmp_path / "state/manager.sqlite3")
    slot = "2026-09-01T20:00:00+09:00"
    old_root = tmp_path / "OLD-USB" / "RAP-c500g-recordings"
    store.claim_capture(slot, "cam01")
    store.mark_capture_claim(
        slot,
        "cam01",
        "finalizing",
        payload={"root": str(old_root)},
    )
    store.mark_capture_claim(slot, "cam01", "completed")
    synced: list[Path] = []
    now = datetime(2026, 9, 2, 9, 0, tzinfo=KST)
    manager = RapC500GManager(
        configs=CONFIGS,
        store=store,
        uploader=object(),
        repository=object(),
        volume_validator=lambda _: ready_volume(tmp_path / "RAP-C500G"),
        capture_fn=lambda *_args, **_kwargs: "unused",
        capture_executor=ImmediateExecutor(),
        verification_executor=ImmediateExecutor(),
        sync_executor=ImmediateExecutor(),
        sync_fn=lambda root, *_: synced.append(root),
        clock=lambda: now,
    )

    manager.run_once(now)

    assert synced == [old_root]

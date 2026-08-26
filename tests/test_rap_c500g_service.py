from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.rap_c500g_capture import CameraConfig
from backend.rap_c500g_manifest import atomic_write_manifest
from backend.rap_c500g_service import (
    capture_current_slot,
    make_test_run_id,
    run_production_loop,
    run_test_capture,
    scan_bundle_manifests,
    seconds_until_next_action,
    sync_bundles,
)
import backend.rap_c500g_service as service_module


KST = ZoneInfo("Asia/Seoul")
CONFIGS = tuple(
    CameraConfig(f"cam0{index}", f"192.168.50.{22 + index}", f"u{index}", f"p{index}")
    for index in range(1, 4)
)


def test_run_test_capture_starts_all_three_cameras_concurrently(tmp_path: Path) -> None:
    barrier = threading.Barrier(3, timeout=2)
    identities = []

    def fake_capture(config: CameraConfig, identity: Any, paths: Any, *, duration_sec: float) -> str:
        identities.append(identity)
        barrier.wait()
        return config.camera_key

    result = run_test_capture(
        CONFIGS,
        tmp_path,
        duration_sec=60,
        now=datetime(2026, 8, 26, 13, 42, 27, tzinfo=KST),
        test_run_id="test-20260826T134227-KST-a1b2c3d4",
        capture_fn=fake_capture,
    )

    assert result == {"cam01": "cam01", "cam02": "cam02", "cam03": "cam03"}
    assert len({item.scheduled_start_kst for item in identities}) == 1


def test_one_camera_failure_does_not_discard_other_camera_results(tmp_path: Path) -> None:
    def fake_capture(config: CameraConfig, identity: Any, paths: Any, *, duration_sec: float) -> str:
        if config.camera_key == "cam02":
            raise RuntimeError("camera offline")
        return config.camera_key

    result = run_test_capture(
        CONFIGS,
        tmp_path,
        duration_sec=60,
        now=datetime(2026, 8, 26, 13, 42, 27, tzinfo=KST),
        test_run_id="test-20260826T134227-KST-a1b2c3d4",
        capture_fn=fake_capture,
    )

    assert result["cam01"] == "cam01"
    assert isinstance(result["cam02"], RuntimeError)
    assert result["cam03"] == "cam03"


def test_capture_current_slot_uses_previous_night_and_remaining_duration(tmp_path: Path) -> None:
    seen: list[tuple[Any, float]] = []

    def fake_capture(config: CameraConfig, identity: Any, paths: Any, *, duration_sec: float) -> str:
        seen.append((identity, duration_sec))
        return config.camera_key

    capture_current_slot(
        CONFIGS,
        tmp_path,
        now=datetime(2026, 8, 27, 0, 15, tzinfo=KST),
        capture_fn=fake_capture,
    )

    assert len(seen) == 3
    assert all(identity.night_date.isoformat() == "2026-08-26" for identity, _ in seen)
    assert all(identity.partial is True for identity, _ in seen)
    assert all(duration == 900 for _, duration in seen)


def test_capture_current_slot_skips_camera_with_existing_completed_manifest(tmp_path: Path) -> None:
    now = datetime(2026, 8, 27, 0, 15, tzinfo=KST)
    captured: list[str] = []

    def fake_capture(config: CameraConfig, identity: Any, paths: Any, *, duration_sec: float) -> str:
        captured.append(config.camera_key)
        return config.camera_key

    # 첫 호출에서 cam01 위치를 알아낸 뒤 완료 marker만 선행시킨다.
    from backend.rap_c500g_naming import build_bundle_paths, current_slot
    from backend.rap_c500g_types import SegmentIdentity

    slot = current_slot(now)
    assert slot is not None
    identity = SegmentIdentity.production(
        camera_key="cam01",
        scheduled_start_kst=slot.scheduled_start_kst,
        actual_start_kst=slot.capture_start_kst,
        partial=slot.partial,
    )
    marker = build_bundle_paths(tmp_path, identity).manifest
    atomic_write_manifest(marker, {"schema": "rap-c500g-bundle/v1", "bundle_id": "existing"})

    capture_current_slot(CONFIGS, tmp_path, now=now, capture_fn=fake_capture)

    assert captured == ["cam02", "cam03"]


def test_scheduler_delay_targets_next_boundary_or_20_kst() -> None:
    assert seconds_until_next_action(datetime(2026, 8, 27, 0, 15, tzinfo=KST)) == 900
    assert seconds_until_next_action(datetime(2026, 8, 27, 8, 0, tzinfo=KST)) == 43_200
    assert seconds_until_next_action(datetime(2026, 8, 27, 19, 59, tzinfo=KST)) == 60


def test_make_test_run_id_is_path_safe_and_contains_kst_time() -> None:
    assert make_test_run_id(
        datetime(2026, 8, 26, 13, 42, 27, tzinfo=KST), token="a1b2c3d4"
    ) == "test-20260826T134227-KST-a1b2c3d4"


def test_production_loop_captures_active_slot_then_waits_for_boundary(tmp_path: Path) -> None:
    captured: list[str] = []
    waits: list[float] = []

    def fake_capture(config: CameraConfig, identity: Any, paths: Any, *, duration_sec: float) -> str:
        captured.append(config.camera_key)
        return config.camera_key

    class Uploader:
        def upload_bundle(self, bundle_dir: Path, payload: dict[str, Any]) -> object:
            return object()

    class Repository:
        def upsert_manifest(self, payload: dict[str, Any]) -> None:
            raise AssertionError("no manifest exists in this synthetic cycle")

    def stop_wait(delay: float) -> bool:
        waits.append(delay)
        return True

    run_production_loop(
        CONFIGS,
        tmp_path,
        Uploader(),
        Repository(),
        clock=lambda: datetime(2026, 8, 27, 0, 15, tzinfo=KST),
        stop_wait=stop_wait,
        capture_fn=fake_capture,
    )

    assert sorted(captured) == ["cam01", "cam02", "cam03"]
    assert waits == [900]


def test_production_loop_overlaps_previous_upload_with_next_capture(tmp_path: Path, monkeypatch) -> None:
    barrier = threading.Barrier(2, timeout=2)
    cam01_calls = 0
    wait_calls = 0

    def fake_capture(config: CameraConfig, identity: Any, paths: Any, *, duration_sec: float) -> str:
        nonlocal cam01_calls
        if config.camera_key == "cam01":
            cam01_calls += 1
            if cam01_calls == 2:
                barrier.wait()
        return config.camera_key

    def blocking_sync(root: Path, uploader: Any, repository: Any) -> object:
        barrier.wait()
        return object()

    monkeypatch.setattr(service_module, "sync_bundles", blocking_sync)

    def stop_wait(delay: float) -> bool:
        nonlocal wait_calls
        wait_calls += 1
        return wait_calls == 2

    run_production_loop(
        CONFIGS,
        tmp_path,
        object(),
        object(),
        clock=lambda: datetime(2026, 8, 27, 0, 15, tzinfo=KST),
        stop_wait=stop_wait,
        capture_fn=fake_capture,
    )

    assert cam01_calls == 2


def test_scan_bundle_manifests_returns_safe_sorted_completed_files(tmp_path: Path) -> None:
    first = tmp_path / "test/b/cam01/x/manifest.json"
    second = tmp_path / "test/a/cam01/x/manifest.json"
    legacy = tmp_path / "c500g/test/legacy/cam01/x/manifest.json"
    atomic_write_manifest(first, {"schema": "rap-c500g-bundle/v1", "bundle_id": "b"})
    atomic_write_manifest(second, {"schema": "rap-c500g-bundle/v1", "bundle_id": "a"})
    atomic_write_manifest(
        legacy, {"schema": "rap-c500g-bundle/v1", "bundle_id": "legacy"}
    )
    (tmp_path / "test/a/cam01/x/manifest.json.part").write_text("partial")

    assert scan_bundle_manifests(tmp_path) == [second, first]


def test_sync_bundles_continues_after_one_upload_failure(tmp_path: Path) -> None:
    manifests = []
    for bundle_id in ("a", "b"):
        path = tmp_path / f"test/run/cam01/{bundle_id}/manifest.json"
        payload = {"schema": "rap-c500g-bundle/v1", "bundle_id": bundle_id}
        atomic_write_manifest(path, payload)
        manifests.append(path)

    class Uploader:
        def upload_bundle(self, bundle_dir: Path, payload: dict[str, Any]) -> object:
            if payload["bundle_id"] == "a":
                raise RuntimeError("offline")
            completed = dict(payload, upload_status="uploaded", r2_verified=True)
            atomic_write_manifest(bundle_dir / "manifest.json", completed)
            return object()

    class Repository:
        def __init__(self) -> None:
            self.rows: list[str] = []

        def upsert_manifest(self, payload: dict[str, Any]) -> None:
            self.rows.append(payload["bundle_id"])

    repository = Repository()
    summary = sync_bundles(tmp_path, Uploader(), repository)

    assert summary.scanned == 2
    assert summary.uploaded == 1
    assert summary.failed == 1
    assert repository.rows == ["b"]

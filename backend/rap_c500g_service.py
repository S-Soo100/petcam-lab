"""RAP C500G 세 카메라 동시 캡처와 durable local manifest 동기화."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from backend.rap_c500g_capture import CameraConfig, CaptureResult, capture_segment
from backend.rap_c500g_manifest import read_manifest
from backend.rap_c500g_naming import build_bundle_paths, current_slot
from backend.rap_c500g_types import SegmentIdentity


CaptureFunction = Callable[..., CaptureResult | str]
KST = ZoneInfo("Asia/Seoul")


class BundleUploader(Protocol):
    def upload_bundle(self, bundle_dir: Path, manifest: dict[str, Any]) -> object: ...


class ManifestRepository(Protocol):
    def upsert_manifest(self, manifest: dict[str, Any]) -> None: ...


@dataclass(frozen=True, slots=True)
class SyncSummary:
    scanned: int
    uploaded: int
    failed: int


def _capture_three(
    configs: Sequence[CameraConfig],
    root: Path,
    identities: dict[str, SegmentIdentity],
    *,
    duration_sec: float,
    capture_fn: CaptureFunction,
) -> dict[str, CaptureResult | str | Exception]:
    results: dict[str, CaptureResult | str | Exception] = {}
    if not configs:
        return results
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="rap-capture") as pool:
        futures = {}
        for config in configs:
            identity = identities[config.camera_key]
            paths = build_bundle_paths(root, identity)
            future = pool.submit(
                capture_fn,
                config,
                identity,
                paths,
                duration_sec=duration_sec,
            )
            futures[future] = config.camera_key
        for future in as_completed(futures):
            camera_key = futures[future]
            try:
                results[camera_key] = future.result()
            except Exception as error:
                results[camera_key] = error
    return results


def run_test_capture(
    configs: Sequence[CameraConfig],
    root: Path,
    *,
    duration_sec: float,
    now: datetime,
    test_run_id: str,
    capture_fn: CaptureFunction = capture_segment,
) -> dict[str, CaptureResult | str | Exception]:
    if {config.camera_key for config in configs} != {"cam01", "cam02", "cam03"}:
        raise ValueError("exactly cam01, cam02, cam03 are required")
    identities = {
        config.camera_key: SegmentIdentity.test(
            camera_key=config.camera_key,
            scheduled_start_kst=now,
            test_run_id=test_run_id,
        )
        for config in configs
    }
    return _capture_three(
        configs,
        root,
        identities,
        duration_sec=duration_sec,
        capture_fn=capture_fn,
    )


def capture_current_slot(
    configs: Sequence[CameraConfig],
    root: Path,
    *,
    now: datetime,
    capture_fn: CaptureFunction = capture_segment,
) -> dict[str, CaptureResult | str | Exception]:
    if {config.camera_key for config in configs} != {"cam01", "cam02", "cam03"}:
        raise ValueError("exactly cam01, cam02, cam03 are required")
    slot = current_slot(now)
    if slot is None:
        return {}
    identities = {
        config.camera_key: SegmentIdentity.production(
            camera_key=config.camera_key,
            scheduled_start_kst=slot.scheduled_start_kst,
            actual_start_kst=slot.capture_start_kst,
            partial=slot.partial,
        )
        for config in configs
    }
    pending_configs = []
    for config in configs:
        paths = build_bundle_paths(root, identities[config.camera_key])
        if not paths.manifest.is_file():
            pending_configs.append(config)
    return _capture_three(
        pending_configs,
        root,
        identities,
        duration_sec=slot.duration_sec,
        capture_fn=capture_fn,
    )


def make_test_run_id(now: datetime, *, token: str | None = None) -> str:
    local = now.astimezone(KST)
    suffix = token or uuid4().hex[:8]
    if len(suffix) != 8 or any(char not in "0123456789abcdef" for char in suffix):
        raise ValueError("test run token must be 8 lowercase hex characters")
    return f"test-{local.strftime('%Y%m%dT%H%M%S')}-KST-{suffix}"


def seconds_until_next_action(now: datetime) -> int:
    local = now.astimezone(KST)
    slot = current_slot(local)
    if slot is not None:
        return max(1, int((slot.scheduled_end_kst - local).total_seconds()))
    target = datetime.combine(local.date(), time(20, 0), tzinfo=KST)
    if local >= target:
        target += timedelta(days=1)
    return max(1, int((target - local).total_seconds()))


def run_production_loop(
    configs: Sequence[CameraConfig],
    root: Path,
    uploader: BundleUploader,
    repository: ManifestRepository,
    *,
    clock: Callable[[], datetime],
    stop_wait: Callable[[float], bool],
    capture_fn: CaptureFunction = capture_segment,
) -> None:
    """SIGTERM-aware wait 함수를 주입받아 야간 slot을 계속 처리한다."""
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="rap-upload") as upload_pool:
        sync_future = None
        while True:
            started = clock()
            slot = current_slot(started)
            if slot is not None:
                capture_current_slot(
                    configs,
                    root,
                    now=started,
                    capture_fn=capture_fn,
                )

            # 이전 업로드가 길어져도 다음 30분 capture를 막지 않는다. local manifest scan이
            # durable queue라서 이번 cycle submit을 건너뛰어도 다음 cycle/restart에서 복구된다.
            if sync_future is None or sync_future.done():
                if sync_future is not None:
                    sync_future.result()
                sync_future = upload_pool.submit(sync_bundles, root, uploader, repository)

            if slot is None:
                delay = seconds_until_next_action(clock())
            else:
                delay = max(
                    1,
                    int((slot.scheduled_end_kst - clock().astimezone(KST)).total_seconds()),
                )
            if stop_wait(float(delay)):
                return


def scan_bundle_manifests(root: Path) -> list[Path]:
    manifests = []
    for mode_dir in (root / "test", root / "recordings"):
        if mode_dir.exists():
            manifests.extend(
                path for path in mode_dir.rglob("manifest.json") if path.is_file()
            )
    return sorted(manifests)


def sync_bundles(
    root: Path,
    uploader: BundleUploader,
    repository: ManifestRepository,
) -> SyncSummary:
    manifest_paths = scan_bundle_manifests(root)
    uploaded = 0
    failed = 0
    for path in manifest_paths:
        try:
            manifest = read_manifest(path)
            uploader.upload_bundle(path.parent, manifest)
            repository.upsert_manifest(read_manifest(path))
            uploaded += 1
        except Exception:
            # 다른 카메라/구간의 이중 보관을 막지 않는다. 상위 daemon이 구조화 로그를 남긴다.
            failed += 1
    return SyncSummary(scanned=len(manifest_paths), uploaded=uploaded, failed=failed)

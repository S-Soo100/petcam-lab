"""RAP C500G manager의 wall-clock scheduler와 카메라별 supervisor."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from backend.rap_c500g_capture import (
    CameraConfig,
    CaptureResult,
    RawCaptureResult,
    capture_segment,
    finalize_raw_capture,
    record_raw_segment,
    terminate_media_processes,
)
from backend.rap_c500g_manager_probe import VolumeStatus, validate_selected_volume
from backend.rap_c500g_manager_store import (
    CameraRuntimeState,
    ManagerPlan,
    ManagerSnapshot,
    ManagerStore,
)
from backend.rap_c500g_naming import SlotDecision, build_bundle_paths
from backend.rap_c500g_service import (
    make_test_run_id,
    run_test_capture,
    sync_bundles,
)
from backend.rap_c500g_types import SegmentIdentity


KST = ZoneInfo("Asia/Seoul")
RETRY_DELAYS_SEC = (10.0, 30.0, 60.0)
MANAGED_ROOT_NAME = "RAP-c500g-recordings"


class Executor(Protocol):
    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any: ...


def _parse_local_time(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour, minute)


def manager_slot(
    now: datetime,
    start_local: str,
    end_local: str,
) -> SlotDecision | None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(KST)
    start = _parse_local_time(start_local)
    end = _parse_local_time(end_local)
    current = local.time().replace(tzinfo=None)
    if start < end:
        active = start <= current < end
    else:
        active = current >= start or current < end
    if not active:
        return None

    minute = 0 if local.minute < 30 else 30
    scheduled_start = local.replace(minute=minute, second=0, microsecond=0)
    scheduled_end = scheduled_start + timedelta(minutes=30)
    if start < end or current < end:
        window_end = datetime.combine(local.date(), end, tzinfo=KST)
    else:
        window_end = datetime.combine(local.date() + timedelta(days=1), end, tzinfo=KST)
    scheduled_end = min(scheduled_end, window_end)
    night_date = local.date() - timedelta(days=1) if current < end else local.date()
    return SlotDecision(
        scheduled_start_kst=scheduled_start,
        capture_start_kst=local,
        scheduled_end_kst=scheduled_end,
        night_date=night_date,
        partial=local != scheduled_start,
    )


def _default_clock() -> datetime:
    return datetime.now(KST)


class RapC500GManager:
    def __init__(
        self,
        *,
        configs: Sequence[CameraConfig],
        store: ManagerStore,
        uploader: object,
        repository: object,
        volume_validator: Callable[[str], VolumeStatus] = validate_selected_volume,
        capture_fn: Callable[..., CaptureResult | RawCaptureResult | str] | None = None,
        finalize_fn: Callable[[RawCaptureResult], CaptureResult] | None = None,
        capture_executor: Executor | None = None,
        verification_executor: Executor | None = None,
        sync_executor: Executor | None = None,
        sync_fn: Callable[..., Any] = sync_bundles,
        notifier: Callable[[str, Mapping[str, Any]], None] | None = None,
        retry_wait: Callable[[float], bool] | None = None,
        clock: Callable[[], datetime] = _default_clock,
        fatal_callback: Callable[[], None] | None = None,
    ) -> None:
        config_map = {config.camera_key: config for config in configs}
        if set(config_map) != {"cam01", "cam02", "cam03"}:
            raise ValueError("manager registry requires cam01, cam02, cam03")
        self.configs = config_map
        self.store = store
        self.uploader = uploader
        self.repository = repository
        self.volume_validator = volume_validator
        self.capture_fn = capture_fn or record_raw_segment
        self.diagnostic_capture_fn = capture_segment if capture_fn is None else capture_fn
        self.finalize_fn = (
            (finalize_fn or finalize_raw_capture) if capture_fn is None else finalize_fn
        )
        self.clock = clock
        self._stop = threading.Event()
        self.retry_wait = retry_wait or self._stop.wait
        self._owns_capture_executor = capture_executor is None
        self._owns_verification_executor = verification_executor is None
        self._owns_sync_executor = sync_executor is None
        self.capture_executor = capture_executor or ThreadPoolExecutor(
            max_workers=3, thread_name_prefix="rap-manager-capture"
        )
        self.verification_executor = verification_executor or ThreadPoolExecutor(
            max_workers=3, thread_name_prefix="rap-manager-verify"
        )
        self.sync_executor = sync_executor or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="rap-manager-sync"
        )
        self.sync_fn = sync_fn
        self.notifier = notifier or (lambda _kind, _payload: None)
        self.fatal_callback = fatal_callback or (lambda: None)
        self._lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._active: dict[tuple[str, str], Any] = {}
        self._finalizing: dict[tuple[str, str], Any] = {}
        # SQLite claim이 service 재시작 뒤 같은 camera/slot 중복 캡처를 막아.
        self._started: set[tuple[str, str]] = store.read_capture_claims()
        self._synced_slots: set[tuple[str, str]] = set()
        self._sync_future: Any | None = None
        self._sync_slots: set[tuple[str, str]] = set()
        self._sync_failed = 0
        self._camera_states = {
            key: self._idle_camera(config) for key, config in self.configs.items()
        }
        self._recent_completed: list[Mapping[str, Any]] = []
        self._incidents: list[Mapping[str, Any]] = []
        self._last_volume = VolumeStatus(
            "RAP-C500G", False, "not_checked", False, 0, 0, None
        )
        self._resume_finalizing_claims()

    @staticmethod
    def _idle_camera(config: CameraConfig) -> CameraRuntimeState:
        return CameraRuntimeState(
            camera_key=config.camera_key,
            ip=config.ip,
            probe_state="unknown",
            capture_state="idle",
            retry_count=0,
            file_bytes=0,
            file_growing=False,
            last_frame_at=None,
            error_code=None,
        )

    def _set_camera(
        self,
        config: CameraConfig,
        *,
        capture_state: str,
        retry_count: int,
        error_code: str | None = None,
        paths: Any | None = None,
    ) -> None:
        file_bytes = 0
        if paths is not None:
            for candidate in (paths.video_part, paths.video):
                if candidate.is_file():
                    file_bytes = candidate.stat().st_size
                    break
        with self._lock:
            self._camera_states[config.camera_key] = CameraRuntimeState(
                camera_key=config.camera_key,
                ip=config.ip,
                probe_state="online" if error_code is None else "unknown",
                capture_state=capture_state,
                retry_count=retry_count,
                file_bytes=file_bytes,
                file_growing=capture_state == "recording",
                last_frame_at=(self.clock().isoformat() if capture_state == "captured" else None),
                error_code=error_code,
            )

    def _archive_failed_attempt(self, paths: Any, attempt: int) -> None:
        if not paths.bundle_dir.exists() or paths.manifest.exists():
            return
        target = paths.bundle_dir.with_name(
            f"{paths.bundle_dir.name}-failed-attempt-{attempt:02d}"
        )
        if not target.exists():
            os.replace(paths.bundle_dir, target)

    def _assert_volume_root(self, root: Path) -> None:
        status = self.volume_validator(root.parent.name)
        if (
            not status.ready
            or status.mount_point is None
            or Path(status.mount_point) != root.parent
        ):
            raise RuntimeError("selected storage volume became unavailable")

    def _mark_completed(
        self,
        config: CameraConfig,
        slot: SlotDecision,
        identity: SegmentIdentity,
        paths: Any,
        attempt: int,
    ) -> None:
        slot_key = slot.scheduled_start_kst.isoformat()
        self.store.mark_capture_claim(slot_key, config.camera_key, "completed")
        self._set_camera(
            config, capture_state="captured", retry_count=attempt, paths=paths
        )
        completed = {
            "camera_key": config.camera_key,
            "slot": slot_key,
            "partial": identity.partial,
            "retry_count": attempt,
        }
        with self._lock:
            self._recent_completed = ([completed] + self._recent_completed)[:20]
            if attempt:
                recovered = {
                    "state": "recovered",
                    "camera_key": config.camera_key,
                    "slot": slot_key,
                }
                self._incidents = ([recovered] + self._incidents)[:20]
                self.store.append_event("camera_recovered", recovered)
                try:
                    self.notifier("camera_recovered", recovered)
                except Exception:
                    pass

    def _resume_finalizing_claims(self) -> None:
        for record in self.store.read_finalizing_claims():
            camera_key = str(record["camera_key"])
            payload = dict(record["payload"])
            if camera_key not in self.configs:
                continue
            try:
                scheduled = datetime.fromisoformat(str(record["slot_start"])).astimezone(KST)
                actual = datetime.fromisoformat(str(payload["actual_start"])).astimezone(KST)
                root = Path(str(payload["root"]))
                attempt = int(payload["attempt"])
                identity = SegmentIdentity.production(
                    camera_key=camera_key,
                    scheduled_start_kst=scheduled,
                    actual_start_kst=actual,
                    partial=bool(payload["partial"]),
                )
                slot = SlotDecision(
                    scheduled_start_kst=scheduled,
                    capture_start_kst=actual,
                    scheduled_end_kst=scheduled + timedelta(minutes=30),
                    night_date=identity.night_date,
                    partial=identity.partial,
                )
                paths = build_bundle_paths(root, identity)
                raw = RawCaptureResult(
                    config=self.configs[camera_key], identity=identity, paths=paths
                )
            except (KeyError, TypeError, ValueError):
                self.store.mark_capture_claim(
                    str(record["slot_start"]), camera_key, "terminal"
                )
                self._set_camera(
                    self.configs[camera_key],
                    capture_state="failed_terminal",
                    retry_count=0,
                    error_code="finalize_invalid_claim",
                )
                continue
            key = (scheduled.isoformat(), camera_key)
            with self._lock:
                if key in self._finalizing:
                    continue
            try:
                self._assert_volume_root(root)
            except RuntimeError:
                # launchd가 USB mount보다 먼저 떠도 claim/raw를 보존하고 다음 tick에 재시도해.
                continue
            self._set_camera(
                self.configs[camera_key],
                capture_state="finalizing",
                retry_count=attempt,
                paths=paths,
            )
            self._finalizing[key] = self.verification_executor.submit(
                self._finalize_capture, raw, slot, attempt
            )

    def _finalize_capture(
        self,
        raw: RawCaptureResult,
        slot: SlotDecision,
        attempt: int,
    ) -> CaptureResult:
        self._assert_volume_root(raw.paths.root)
        if self.finalize_fn is None:
            raise RuntimeError("capture finalizer is unavailable")
        try:
            result = self.finalize_fn(raw)
        except BaseException as error:
            if self._stop.is_set():
                # raw와 finalizing payload를 그대로 남겨 다음 process가 검증을 이어가.
                raise RuntimeError("finalization cancelled for manager shutdown") from error
            self._terminal_failure(
                raw.config,
                slot,
                attempt,
                f"finalize_{type(error).__name__}",
            )
            raise
        self._mark_completed(raw.config, slot, raw.identity, raw.paths, attempt)
        return result

    def _terminal_failure(
        self,
        config: CameraConfig,
        slot: SlotDecision,
        retry_count: int,
        code: str,
    ) -> None:
        slot_key = slot.scheduled_start_kst.isoformat()
        self.store.mark_capture_claim(slot_key, config.camera_key, "terminal")
        self._set_camera(
            config,
            capture_state="failed_terminal",
            retry_count=retry_count,
            error_code=code,
        )
        incident = {
            "state": "open",
            "camera_key": config.camera_key,
            "slot": slot_key,
            "code": code,
        }
        with self._lock:
            self._incidents = ([incident] + self._incidents)[:20]
            self.store.append_event("camera_terminal", incident)
            try:
                self.notifier("camera_terminal", incident)
            except Exception:
                pass

    def _capture_with_retries(
        self,
        config: CameraConfig,
        root: Path,
        slot: SlotDecision,
        max_retries: int,
    ) -> CaptureResult | str:
        last_error: BaseException | None = None
        for attempt in range(max_retries + 1):
            self._assert_volume_root(root)
            actual_start = self.clock().astimezone(KST)
            identity = SegmentIdentity.production(
                camera_key=config.camera_key,
                scheduled_start_kst=slot.scheduled_start_kst,
                actual_start_kst=actual_start,
                partial=actual_start != slot.scheduled_start_kst,
            )
            paths = build_bundle_paths(root, identity)
            # FFmpeg worker가 다음 30분 경계 전에 반드시 반환하도록 작은 안전 여유를 둬.
            remaining = (slot.scheduled_end_kst - actual_start).total_seconds() - 3.0
            if remaining <= 0:
                break
            self._set_camera(
                config,
                capture_state="recording",
                retry_count=attempt,
                paths=paths,
            )
            try:
                result = self.capture_fn(
                    config,
                    identity,
                    paths,
                    duration_sec=remaining,
                )
            except BaseException as error:
                last_error = error
                self._archive_failed_attempt(paths, attempt + 1)
                if self._stop.is_set():
                    self.store.release_capture_claim(
                        slot.scheduled_start_kst.isoformat(), config.camera_key
                    )
                    raise RuntimeError("capture cancelled for manager shutdown") from error
                if attempt >= max_retries:
                    break
                delay = RETRY_DELAYS_SEC[min(attempt, len(RETRY_DELAYS_SEC) - 1)]
                if (slot.scheduled_end_kst - self.clock().astimezone(KST)).total_seconds() <= delay:
                    break
                self._set_camera(
                    config,
                    capture_state="retry_wait",
                    retry_count=attempt + 1,
                    error_code=f"capture_{type(error).__name__}",
                )
                if self.retry_wait(delay):
                    break
                continue

            if isinstance(result, RawCaptureResult):
                key = (slot.scheduled_start_kst.isoformat(), config.camera_key)
                self.store.mark_capture_claim(
                    key[0],
                    key[1],
                    "finalizing",
                    payload={
                        "root": str(paths.root),
                        "actual_start": identity.actual_start_kst.isoformat(),
                        "partial": identity.partial,
                        "attempt": attempt,
                    },
                )
                self._set_camera(
                    config,
                    capture_state="finalizing",
                    retry_count=attempt,
                    paths=paths,
                )
                future = self.verification_executor.submit(
                    self._finalize_capture, result, slot, attempt
                )
                with self._lock:
                    self._finalizing[key] = future
            else:
                self._mark_completed(config, slot, identity, paths, attempt)
            return result

        if self._stop.is_set():
            self.store.release_capture_claim(
                slot.scheduled_start_kst.isoformat(), config.camera_key
            )
            raise RuntimeError("capture cancelled for manager shutdown")
        code = f"capture_{type(last_error).__name__}" if last_error else "slot_expired"
        self._terminal_failure(config, slot, max_retries, code)
        if last_error is not None:
            raise last_error
        raise RuntimeError("capture slot expired")

    def _consume_done(self) -> None:
        with self._lock:
            done = [(key, future) for key, future in self._active.items() if future.done()]
        for key, future in done:
            try:
                future.result()
            except BaseException:
                pass
            with self._lock:
                self._active.pop(key, None)
        with self._lock:
            finalized = [
                (key, future)
                for key, future in self._finalizing.items()
                if future.done()
            ]
        for key, future in finalized:
            try:
                future.result()
            except BaseException:
                pass
            with self._lock:
                self._finalizing.pop(key, None)

    def _consume_sync(self) -> None:
        future = self._sync_future
        if future is None or not future.done():
            return
        try:
            summary = future.result()
            if int(getattr(summary, "failed", 0)):
                raise RuntimeError("bundle sync reported failures")
        except BaseException:
            self._sync_failed += 1
        else:
            self._synced_slots.update(self._sync_slots)
            self._sync_failed = 0
        finally:
            self._sync_future = None
            self._sync_slots = set()

    def _schedule_ready_syncs(self, root: Path) -> None:
        self._consume_sync()
        with self._lock:
            if self._sync_future is not None:
                return
            completed = self.store.read_completed_claims()
            active_slots = {slot for slot, _camera in self._active}
            finalizing_slots = {slot for slot, _camera in self._finalizing}
            ready_by_root: dict[str, set[tuple[str, str]]] = {}
            for record in completed:
                slot = str(record["slot_start"])
                payload = dict(record["payload"])
                claim_root = str(payload.get("root") or root)
                key = (claim_root, slot)
                if (
                    slot in active_slots
                    or slot in finalizing_slots
                    or key in self._synced_slots
                ):
                    continue
                ready_by_root.setdefault(claim_root, set()).add(key)
            if not ready_by_root:
                return
            # sync_bundles는 root 전체의 미완료 manifest를 스캔하므로 여러 종료 slot도
            # 한 번의 단일 worker 실행으로 함께 수렴시켜.
            selected_root = sorted(ready_by_root)[0]
            self._sync_slots = ready_by_root[selected_root]
            self._sync_future = self.sync_executor.submit(
                self.sync_fn, Path(selected_root), self.uploader, self.repository
            )

    def _snapshot(
        self,
        now: datetime,
        slot: SlotDecision | None,
        manager_state: str,
    ) -> ManagerSnapshot:
        next_slot = None
        if slot is not None:
            next_slot = slot.scheduled_end_kst.isoformat()
        return ManagerSnapshot(
            manager_state=manager_state,
            updated_at=now.astimezone(KST).isoformat(),
            current_slot=(slot.scheduled_start_kst.isoformat() if slot else None),
            next_slot=next_slot,
            volume=self._last_volume.to_public_dict(),
            cameras=dict(self._camera_states),
            recent_completed=tuple(self._recent_completed),
            incidents=tuple(self._incidents),
            sync={
                "pending": len(self._sync_slots),
                "failed": self._sync_failed,
            },
        )

    def _run_once_unlocked(self, now: datetime | None = None) -> ManagerSnapshot:
        observed = (now or self.clock()).astimezone(KST)
        self._consume_done()
        self._resume_finalizing_claims()
        plan = self.store.load_plan()
        if observed.minute in {0, 30} and observed.second < 5:
            pending = self.store.load_pending_plan()
            if pending is not None:
                plan = self.store.apply_pending_plan()
        slot = manager_slot(observed, plan.start_local, plan.end_local)
        self._last_volume = self.volume_validator(plan.volume_name)
        if not self._last_volume.ready:
            snapshot = self._snapshot(observed, slot, "blocked_storage")
            self.store.write_snapshot(snapshot)
            return snapshot
        root = Path(str(self._last_volume.mount_point)) / MANAGED_ROOT_NAME
        if slot is None:
            self._schedule_ready_syncs(root)
            snapshot = self._snapshot(observed, None, "idle")
            self.store.write_snapshot(snapshot)
            return snapshot

        slot_key = slot.scheduled_start_kst.isoformat()
        for camera_key in plan.selected_cameras:
            key = (slot_key, camera_key)
            with self._lock:
                if key in self._started or key in self._active:
                    continue
                if any(active_camera == camera_key for _, active_camera in self._active):
                    # 이전 slot child가 hard deadline 종료 중이면 다음 tick에 partial로 시작해.
                    continue
                if not self.store.claim_capture(slot_key, camera_key):
                    self._started.add(key)
                    continue
                self._started.add(key)
            config = self.configs[camera_key]
            future = self.capture_executor.submit(
                self._capture_with_retries,
                config,
                root,
                slot,
                plan.max_capture_retries,
            )
            with self._lock:
                self._active[key] = future
        self._consume_done()
        self._schedule_ready_syncs(root)
        with self._lock:
            slot_active = any(key[0] == slot_key for key in self._active)
            slot_finalizing = any(key[0] == slot_key for key in self._finalizing)
        manager_state = (
            "recording" if slot_active else "finalizing" if slot_finalizing else "scheduled"
        )
        snapshot = self._snapshot(observed, slot, manager_state)
        self.store.write_snapshot(snapshot)
        return snapshot

    def run_once(self, now: datetime | None = None) -> ManagerSnapshot:
        with self._operation_lock:
            return self._run_once_unlocked(now)

    def is_production_active(self) -> bool:
        self._consume_done()
        with self._lock:
            return bool(self._active or self._finalizing)

    def run_diagnostic(self, *, duration_sec: float = 60.0) -> dict[str, Any]:
        with self._operation_lock:
            if self.is_production_active():
                raise RuntimeError("production capture is active")
            plan = self.store.load_plan()
            volume = self.volume_validator(plan.volume_name)
            if not volume.ready or volume.mount_point is None:
                raise RuntimeError("selected volume is unavailable")
            now = self.clock().astimezone(KST)
            root = Path(volume.mount_point) / MANAGED_ROOT_NAME
            configs = tuple(self.configs[key] for key in plan.selected_cameras)
            if {config.camera_key for config in configs} != {"cam01", "cam02", "cam03"}:
                raise RuntimeError("diagnostic requires cam01, cam02, cam03")
            results = run_test_capture(
                configs,
                root,
                duration_sec=duration_sec,
                now=now,
                test_run_id=make_test_run_id(now),
                capture_fn=self.diagnostic_capture_fn,
            )
            summary = self.sync_fn(root, self.uploader, self.repository)
            return {
                "cameras": {
                    key: "failed" if isinstance(value, Exception) else "captured"
                    for key, value in results.items()
                },
                "sync": {
                    "scanned": getattr(summary, "scanned", 0),
                    "uploaded": getattr(summary, "uploaded", 0),
                    "failed": getattr(summary, "failed", 0),
                },
            }

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()

        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.run_once(self.clock())
                except BaseException as error:
                    payload = {
                        "state": "open",
                        "code": f"manager_{type(error).__name__}",
                    }
                    try:
                        try:
                            self.store.append_event("manager_fatal", payload)
                            self.notifier("manager_fatal", payload)
                        except Exception:
                            pass
                    finally:
                        self.fatal_callback()
                        self._stop.set()
                    break
                self._stop.wait(1.0)

        self._thread = threading.Thread(
            target=loop, name="rap-c500g-manager", daemon=True
        )
        self._thread.start()

    def stop(self, *, timeout: float = 10.0) -> None:
        self._stop.set()
        terminate_media_processes()
        if self._thread is not None:
            self._thread.join(timeout)
        if self._owns_capture_executor:
            cast_executor = self.capture_executor
            if hasattr(cast_executor, "shutdown"):
                cast_executor.shutdown(wait=True, cancel_futures=False)
        if self._owns_verification_executor:
            cast_executor = self.verification_executor
            if hasattr(cast_executor, "shutdown"):
                cast_executor.shutdown(wait=True, cancel_futures=False)
        if self._owns_sync_executor:
            cast_executor = self.sync_executor
            if hasattr(cast_executor, "shutdown"):
                cast_executor.shutdown(wait=True, cancel_futures=False)

"""Capture-first coordination for immediate raw backup and daytime finalization."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import Executor, Future
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Any
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.rap_c500g_capture import CameraConfig, CaptureResult, QuickVerifiedRaw, RawCaptureResult
from backend.rap_c500g_manifest import sha256_file
from backend.rap_c500g_manager_store import ManagerStore
from backend.rap_c500g_naming import build_bundle_paths
from backend.rap_c500g_pipeline_types import PipelineItem, PipelineState
from backend.rap_c500g_types import SegmentIdentity


KST = ZoneInfo("Asia/Seoul")
SLOT_CAMERAS = ("cam01", "cam02", "cam03")
RAW_UPLOAD_SUCCESS_STATES = frozenset({
    PipelineState.RAW_UPLOADED,
    PipelineState.FULL_VERIFYING,
    PipelineState.FINALIZING,
    PipelineState.VERIFIED_UPLOADED,
    PipelineState.FULL_VERIFICATION_FAILED,
    PipelineState.FINAL_ARTIFACT_FAILED,
    PipelineState.DB_SYNC_FAILED,
})


class PipelineWindow(StrEnum):
    CAPTURE = "capture"
    FINALIZE = "finalize"
    DRAIN = "drain"


def pipeline_window(now: datetime) -> PipelineWindow:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    current = now.astimezone(KST).time().replace(tzinfo=None)
    if current >= time(20, 0) or current < time(8, 0):
        return PipelineWindow.CAPTURE
    if current < time(19, 30):
        return PipelineWindow.FINALIZE
    return PipelineWindow.DRAIN


@dataclass(frozen=True, slots=True)
class PipelineSnapshot:
    mode: PipelineWindow
    raw_upload_pending: int = 0
    raw_upload_active: int = 0
    raw_upload_failed: int = 0
    raw_upload_oldest_age_sec: float | None = None
    finalize_pending: int = 0
    finalize_active: int = 0
    finalize_failed: int = 0
    finalize_completed: int = 0
    full_verification_failed: int = 0


@dataclass(frozen=True, slots=True)
class ResumeAction:
    slot_start: str
    camera_key: str
    action: str


@dataclass(frozen=True, slots=True)
class ResumeSummary:
    actions: tuple[ResumeAction, ...]
    recapture_count: int = 0

    def action_for(self, camera_key: str, slot_start: str) -> str:
        return next(
            item.action for item in self.actions
            if item.camera_key == camera_key and item.slot_start == slot_start
        )


class CaptureFirstPipeline:
    def __init__(
        self,
        *,
        store: ManagerStore,
        uploader: Any,
        repository: Any,
        quick_verify_fn: Callable[[RawCaptureResult], QuickVerifiedRaw],
        finalize_fn: Callable[[QuickVerifiedRaw], CaptureResult | Any],
        raw_upload_executor: Executor,
        finalize_executor: Executor,
        notifier: Callable[[str, Mapping[str, Any]], None] | None = None,
        configs: Mapping[str, CameraConfig] | None = None,
    ) -> None:
        self._store = store
        self._uploader = uploader
        self._repository = repository
        self._quick_verify = quick_verify_fn
        self._finalize = finalize_fn
        self._raw_pool = raw_upload_executor
        self._final_pool = finalize_executor
        self._notifier = notifier or (lambda _kind, _payload: None)
        self._configs = dict(configs or {})
        self._raw_futures: dict[Future[Any], tuple[str, str]] = {}
        self._final_futures: dict[Future[Any], tuple[str, str]] = {}
        self._verified: dict[tuple[str, str], QuickVerifiedRaw] = {}
        self._last = PipelineSnapshot(PipelineWindow.DRAIN)

    @staticmethod
    def _key(raw: RawCaptureResult | QuickVerifiedRaw) -> tuple[str, str]:
        return raw.identity.scheduled_start_kst.isoformat(), raw.identity.camera_key

    def accept_capture(self, raw: RawCaptureResult) -> None:
        key = self._key(raw)
        self._store.upsert_pipeline_item(PipelineItem(
            slot_start=key[0], camera_key=key[1], state=PipelineState.QUICK_VERIFYING,
            root=str(raw.paths.root), payload={
                "relative_dir": raw.paths.relative_dir.as_posix(),
                "actual_start": raw.identity.actual_start_kst.isoformat(),
                "partial": raw.identity.partial,
                "mode": raw.identity.mode.value,
                "test_run_id": raw.identity.test_run_id,
            },
        ))
        future = self._raw_pool.submit(self._quick_and_upload, raw)
        self._raw_futures[future] = key

    def _quick_and_upload(self, raw: RawCaptureResult) -> QuickVerifiedRaw:
        key = self._key(raw)
        verified = self._quick_verify(raw)
        self._store.upsert_pipeline_item(PipelineItem(
            slot_start=key[0], camera_key=key[1], state=PipelineState.CAPTURED,
            root=str(verified.paths.root), payload={
                "relative_dir": verified.paths.relative_dir.as_posix(),
                "actual_start": verified.identity.actual_start_kst.isoformat(),
                "partial": verified.identity.partial,
                "mode": verified.identity.mode.value,
                "test_run_id": verified.identity.test_run_id,
                "media": dict(verified.media),
                "video_sha256": verified.video_sha256,
            },
        ))
        self._store.complete_pipeline_stage(*key, PipelineState.RAW_UPLOADING)
        return self._upload_verified(verified)

    def _upload_verified(self, verified: QuickVerifiedRaw) -> QuickVerifiedRaw:
        key = self._key(verified)
        self._uploader.upload_raw_video(verified)
        self._store.complete_pipeline_stage(*key, PipelineState.RAW_UPLOADED)
        self._store.append_lifecycle_once(
            "raw_uploaded", key[0], key[1], {"bytes": verified.paths.video.stat().st_size}
        )
        return verified

    def _complete_futures(self) -> None:
        for future, key in list(self._raw_futures.items()):
            if not future.done():
                continue
            try:
                self._verified[key] = future.result()
            except Exception as error:
                self._store.fail_pipeline_stage(*key, PipelineState.RAW_UPLOAD_FAILED)
                self._record_pipeline_incident("raw_upload", key, error)
            del self._raw_futures[future]
        for future, key in list(self._final_futures.items()):
            if not future.done():
                continue
            try:
                future.result()
                self._store.complete_pipeline_stage(*key, PipelineState.VERIFIED_UPLOADED)
            except Exception as error:
                self._store.fail_pipeline_stage(*key, PipelineState.FULL_VERIFICATION_FAILED)
                self._record_pipeline_incident("finalize", key, error)
            del self._final_futures[future]

    def _record_pipeline_incident(
        self,
        stage: str,
        key: tuple[str, str],
        error: BaseException,
        *,
        notify: bool = True,
    ) -> None:
        payload = {
            "state": "open",
            "slot": key[0],
            "camera_key": key[1],
            "code": f"{stage}_{type(error).__name__}",
        }
        self._store.append_event("pipeline_incident", payload)
        if notify:
            try:
                self._notifier("pipeline_incident", payload)
            except Exception:
                pass

    def _finalize_and_sync(self, raw: QuickVerifiedRaw) -> None:
        key = self._key(raw)
        self._store.append_lifecycle_once(
            "finalize_started", key[0], key[1], {"attempt": 1}
        )
        result = self._finalize(raw)
        if not isinstance(result, CaptureResult):
            return
        self._store.complete_pipeline_stage(*key, PipelineState.FINALIZING)
        self._uploader.upload_bundle(result.paths.bundle_dir, result.manifest)
        self._store.append_lifecycle_once(
            "finalize_completed", key[0], key[1], {"state": "manifest_verified"}
        )
        from backend.rap_c500g_manifest import read_manifest
        self._repository.upsert_manifest(read_manifest(result.paths.manifest))
        self._store.append_lifecycle_once(
            "db_synced", key[0], key[1], {"state": "completed"}
        )

    def run_once(self, now: datetime, *, capture_active: bool) -> PipelineSnapshot:
        self._complete_futures()
        mode = pipeline_window(now)
        if mode is PipelineWindow.FINALIZE and not capture_active:
            active_keys = set(self._final_futures.values())
            for key, raw in sorted(self._verified.items()):
                if key in active_keys:
                    continue
                if not self._store.claim_pipeline_stage(
                    *key,
                    stage="finalize",
                    states=(PipelineState.RAW_UPLOADED, PipelineState.FULL_VERIFICATION_FAILED),
                ):
                    continue
                self._store.complete_pipeline_stage(*key, PipelineState.FULL_VERIFYING)
                future = self._final_pool.submit(self._finalize_and_sync, raw)
                self._final_futures[future] = key
        rows = self._store.list_pipeline_items()
        states = [row.state for row in rows]
        self._last = PipelineSnapshot(
            mode=mode,
            raw_upload_pending=sum(s in {PipelineState.CAPTURED, PipelineState.RAW_UPLOAD_FAILED} for s in states),
            raw_upload_active=len(self._raw_futures),
            raw_upload_failed=states.count(PipelineState.RAW_UPLOAD_FAILED),
            finalize_pending=states.count(PipelineState.RAW_UPLOADED),
            finalize_active=len(self._final_futures),
            finalize_failed=sum(s in {PipelineState.FULL_VERIFICATION_FAILED, PipelineState.FINAL_ARTIFACT_FAILED, PipelineState.DB_SYNC_FAILED} for s in states),
            finalize_completed=states.count(PipelineState.VERIFIED_UPLOADED),
            full_verification_failed=states.count(PipelineState.FULL_VERIFICATION_FAILED),
        )
        self._emit_slot_summaries(now, rows)
        self._emit_night_acceptance(now, rows)
        return self._last

    def _emit_slot_summaries(
        self, now: datetime, rows: list[PipelineItem]
    ) -> None:
        activation = self._store.read_latest_event_payload("slot_summary_activation")
        if activation is None:
            self._store.append_event_once(
                "slot_summary_activation",
                "activated_at",
                {"activated_at": now.astimezone(KST).isoformat()},
            )
            return
        activated_at = datetime.fromisoformat(str(activation["activated_at"]))
        items = {
            (item.slot_start, item.camera_key): item
            for item in rows
            if item.payload.get("mode") == "production"
        }
        claims = self._store.read_capture_claim_statuses()
        slots = sorted({slot for slot, _camera in items} | {
            slot for (slot, _camera), status in claims.items()
            if status == "terminal"
        })
        for slot in slots:
            if datetime.fromisoformat(slot) < activated_at:
                continue
            statuses: dict[str, str] = {}
            for camera in SLOT_CAMERAS:
                item = items.get((slot, camera))
                if item is not None and item.state in RAW_UPLOAD_SUCCESS_STATES:
                    statuses[camera] = "uploaded"
                elif item is not None and item.state is PipelineState.RAW_UPLOAD_FAILED:
                    statuses[camera] = "raw_upload_failed"
                elif claims.get((slot, camera)) == "terminal":
                    statuses[camera] = "capture_failed"
            if set(statuses) != set(SLOT_CAMERAS):
                continue
            payload = {"slot": slot, "cameras": statuses}
            if not self._store.append_event_once("slot_raw_summary", "slot", payload):
                continue
            try:
                self._notifier("slot_raw_summary", payload)
            except Exception:
                incident = {
                    "state": "open",
                    "slot": slot,
                    "code": "slot_summary_notify_failed",
                }
                self._store.append_event("pipeline_incident", incident)

    def _emit_night_acceptance(
        self, now: datetime, rows: list[PipelineItem]
    ) -> None:
        observed = now.astimezone(KST)
        if pipeline_window(observed) is PipelineWindow.CAPTURE:
            return
        night_date = observed.date() - timedelta(days=1)
        first_slot = datetime.combine(night_date, time(20, 0), tzinfo=KST)
        expected = {
            ((first_slot + timedelta(minutes=30 * index)).isoformat(), camera)
            for index in range(24)
            for camera in SLOT_CAMERAS
        }
        matching = {
            (item.slot_start, item.camera_key): item
            for item in rows
            if (item.slot_start, item.camera_key) in expected
            and item.payload.get("mode") == "production"
        }
        if set(matching) != expected or any(
            item.state is not PipelineState.VERIFIED_UPLOADED
            for item in matching.values()
        ):
            return
        delays = sorted(
            (
                datetime.fromisoformat(str(item.payload["actual_start"])).astimezone(KST)
                - datetime.fromisoformat(item.slot_start).astimezone(KST)
            ).total_seconds()
            for item in matching.values()
        )
        durations = [
            float(dict(item.payload["media"])["duration_sec"])
            for item in matching.values()
        ]
        p95 = delays[min(len(delays) - 1, int(0.95 * (len(delays) - 1)))]
        healthy = p95 <= 5.0 and max(delays) <= 15.0 and min(durations) >= 1760.0
        payload = {
            "night_date": night_date.isoformat(),
            "state": "healthy" if healthy else "degraded",
            "expected_slots": 72,
            "verified_slots": 72,
            "start_delay_p95_sec": round(p95, 3),
            "start_delay_max_sec": round(max(delays), 3),
            "duration_min_sec": round(min(durations), 3),
        }
        if self._store.append_event_once("night_acceptance", "night_date", payload):
            self._notifier("night_acceptance", payload)

    def drain_ready_for_test(self, *, now: datetime) -> PipelineSnapshot:
        for future in tuple(self._raw_futures):
            future.result()
        self.run_once(now, capture_active=False)
        for future in tuple(self._final_futures):
            future.result()
        return self.run_once(now, capture_active=False)

    def snapshot(self) -> PipelineSnapshot:
        return self._last

    def resume(self) -> ResumeSummary:
        action_by_state = {
            PipelineState.CAPTURED: "quick_and_upload",
            PipelineState.RAW_UPLOADING: "head_then_upload",
            PipelineState.RAW_UPLOADED: "wait_for_daytime_finalize",
            PipelineState.FULL_VERIFYING: "reclaim_finalize",
            PipelineState.FINALIZING: "reclaim_finalize",
            PipelineState.VERIFIED_UPLOADED: "none",
        }
        items = self._store.list_pipeline_items()
        actions = tuple(
            ResumeAction(item.slot_start, item.camera_key, action_by_state.get(item.state, "preserve_failed"))
            for item in items
        )
        for item in items:
            if item.camera_key not in self._configs:
                continue
            try:
                scheduled = datetime.fromisoformat(item.slot_start).astimezone(KST)
                actual = datetime.fromisoformat(str(item.payload["actual_start"])).astimezone(KST)
                test_run_id = item.payload.get("test_run_id")
                if item.payload.get("mode") == "test" and isinstance(test_run_id, str):
                    identity = SegmentIdentity.test(
                        camera_key=item.camera_key,
                        scheduled_start_kst=scheduled,
                        test_run_id=test_run_id,
                    )
                else:
                    identity = SegmentIdentity.production(
                        camera_key=item.camera_key, scheduled_start_kst=scheduled,
                        actual_start_kst=actual, partial=bool(item.payload.get("partial", False)),
                    )
                paths = build_bundle_paths(Path(item.root), identity)
                if paths.relative_dir.as_posix() != item.payload["relative_dir"]:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            if item.state is PipelineState.QUICK_VERIFYING and paths.video_part.is_file():
                raw = RawCaptureResult(self._configs[item.camera_key], identity, paths)
                future = self._raw_pool.submit(self._quick_and_upload, raw)
                self._raw_futures[future] = (item.slot_start, item.camera_key)
                continue
            if item.state in {PipelineState.CAPTURED, PipelineState.RAW_UPLOADING, PipelineState.RAW_UPLOADED, PipelineState.FULL_VERIFYING, PipelineState.FINALIZING} and paths.video.is_file():
                media = item.payload.get("media")
                digest = item.payload.get("video_sha256")
                if not isinstance(media, Mapping) or not isinstance(digest, str) or sha256_file(paths.video) != digest:
                    continue
                verified = QuickVerifiedRaw(
                    self._configs[item.camera_key], identity, paths, dict(media), digest
                )
                if item.state in {PipelineState.CAPTURED, PipelineState.RAW_UPLOADING}:
                    future = self._raw_pool.submit(self._upload_verified, verified)
                    self._raw_futures[future] = (item.slot_start, item.camera_key)
                else:
                    if item.state in {PipelineState.FULL_VERIFYING, PipelineState.FINALIZING}:
                        self._store.fail_pipeline_stage(
                            item.slot_start,
                            item.camera_key,
                            PipelineState.FULL_VERIFICATION_FAILED,
                        )
                    self._verified[(item.slot_start, item.camera_key)] = verified
        return ResumeSummary(actions=actions)

    def shutdown(self, timeout: float) -> None:
        del timeout
        self._complete_futures()

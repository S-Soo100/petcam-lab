"""Capture-first coordination for immediate raw backup and daytime finalization."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import Executor, Future
from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from backend.rap_c500g_capture import CaptureResult, QuickVerifiedRaw, RawCaptureResult
from backend.rap_c500g_manager_store import ManagerStore
from backend.rap_c500g_pipeline_types import PipelineItem, PipelineState


KST = ZoneInfo("Asia/Seoul")


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
    ) -> None:
        self._store = store
        self._uploader = uploader
        self._repository = repository
        self._quick_verify = quick_verify_fn
        self._finalize = finalize_fn
        self._raw_pool = raw_upload_executor
        self._final_pool = finalize_executor
        self._notifier = notifier or (lambda _kind, _payload: None)
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
            },
        ))
        future = self._raw_pool.submit(self._quick_and_upload, raw)
        self._raw_futures[future] = key

    def _quick_and_upload(self, raw: RawCaptureResult) -> QuickVerifiedRaw:
        key = self._key(raw)
        verified = self._quick_verify(raw)
        self._store.complete_pipeline_stage(*key, PipelineState.CAPTURED)
        self._store.complete_pipeline_stage(*key, PipelineState.RAW_UPLOADING)
        self._uploader.upload_raw_video(verified)
        self._store.complete_pipeline_stage(*key, PipelineState.RAW_UPLOADED)
        return verified

    def _complete_futures(self) -> None:
        for future, key in list(self._raw_futures.items()):
            if not future.done():
                continue
            try:
                self._verified[key] = future.result()
            except Exception:
                self._store.fail_pipeline_stage(*key, PipelineState.RAW_UPLOAD_FAILED)
            del self._raw_futures[future]
        for future, key in list(self._final_futures.items()):
            if not future.done():
                continue
            try:
                future.result()
                self._store.complete_pipeline_stage(*key, PipelineState.VERIFIED_UPLOADED)
            except Exception:
                self._store.fail_pipeline_stage(*key, PipelineState.FULL_VERIFICATION_FAILED)
            del self._final_futures[future]

    def _finalize_and_sync(self, raw: QuickVerifiedRaw) -> None:
        key = self._key(raw)
        result = self._finalize(raw)
        if not isinstance(result, CaptureResult):
            return
        self._store.complete_pipeline_stage(*key, PipelineState.FINALIZING)
        self._uploader.upload_bundle(result.paths.bundle_dir, result.manifest)
        from backend.rap_c500g_manifest import read_manifest
        self._repository.upsert_manifest(read_manifest(result.paths.manifest))

    def run_once(self, now: datetime, *, capture_active: bool) -> PipelineSnapshot:
        self._complete_futures()
        mode = pipeline_window(now)
        if mode is PipelineWindow.FINALIZE and not capture_active:
            active_keys = set(self._final_futures.values())
            for key, raw in sorted(self._verified.items()):
                if key in active_keys:
                    continue
                if not self._store.claim_pipeline_stage(
                    *key, stage="finalize", states=(PipelineState.RAW_UPLOADED,)
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
        return self._last

    def drain_ready_for_test(self, *, now: datetime) -> PipelineSnapshot:
        for future in tuple(self._raw_futures):
            future.result()
        self.run_once(now, capture_active=False)
        for future in tuple(self._final_futures):
            future.result()
        return self.run_once(now, capture_active=False)

    def snapshot(self) -> PipelineSnapshot:
        return self._last

    def shutdown(self, timeout: float) -> None:
        del timeout
        self._complete_futures()

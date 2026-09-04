from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend.rap_c500g_capture import QuickVerifiedRaw, RawCaptureResult, load_camera_configs
from backend.rap_c500g_manager_store import ManagerStore
from backend.rap_c500g_naming import build_bundle_paths
from backend.rap_c500g_pipeline import CaptureFirstPipeline, PipelineWindow, pipeline_window
from backend.rap_c500g_types import SegmentIdentity
from backend.rap_c500g_pipeline_types import PipelineItem, PipelineState


KST = ZoneInfo("Asia/Seoul")


def kst(hour: int, minute: int) -> datetime:
    return datetime(2026, 9, 3, hour, minute, tzinfo=KST)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (kst(7, 59), PipelineWindow.CAPTURE),
        (kst(8, 0), PipelineWindow.FINALIZE),
        (kst(19, 29), PipelineWindow.FINALIZE),
        (kst(19, 30), PipelineWindow.DRAIN),
        (kst(20, 0), PipelineWindow.CAPTURE),
    ],
)
def test_pipeline_window_uses_fixed_kst_boundaries(now: datetime, expected: PipelineWindow) -> None:
    assert pipeline_window(now) is expected


def raw_result(tmp_path: Path) -> RawCaptureResult:
    env = {
        "RAP_CAM_C500G_RTSP_USER": "u1", "RAP_CAM_C500G_RTSP_PASSWORD": "p1",
        "RAP_CAM_C500G_RTSP_USER_02": "u2", "RAP_CAM_C500G_RTSP_PASSWORD_02": "p2",
        "RAP_CAM_C500G_RTSP_USER_03": "u3", "RAP_CAM_C500G_RTSP_PASSWORD_03": "p3",
    }
    config = load_camera_configs(env)[0]
    identity = SegmentIdentity.production(
        camera_key="cam01", scheduled_start_kst=kst(20, 0), actual_start_kst=kst(20, 0)
    )
    paths = build_bundle_paths(tmp_path, identity)
    paths.bundle_dir.mkdir(parents=True)
    paths.video_part.write_bytes(b"raw")
    paths.log_part.write_text("", encoding="utf-8")
    return RawCaptureResult(config, identity, paths)


def test_night_capture_runs_quick_gate_and_raw_upload_but_not_full_finalize(tmp_path: Path) -> None:
    calls: list[str] = []
    raw = raw_result(tmp_path)

    def quick(value: RawCaptureResult) -> QuickVerifiedRaw:
        calls.append("quick_verify")
        value.paths.video_part.replace(value.paths.video)
        return QuickVerifiedRaw(value.config, value.identity, value.paths, {"duration_sec": 60}, "a" * 64)

    class Uploader:
        def upload_raw_video(self, _raw: QuickVerifiedRaw) -> object:
            calls.append("raw_upload")
            return object()

    with ThreadPoolExecutor(max_workers=1) as raw_pool, ThreadPoolExecutor(max_workers=1) as final_pool:
        pipeline = CaptureFirstPipeline(
            store=ManagerStore(tmp_path / "state.sqlite3"), uploader=Uploader(),
            repository=object(), quick_verify_fn=quick,
            finalize_fn=lambda _raw: calls.append("finalize"),
            raw_upload_executor=raw_pool, finalize_executor=final_pool,
        )
        pipeline.accept_capture(raw)
        pipeline.drain_ready_for_test(now=kst(20, 31))

        assert calls == ["quick_verify", "raw_upload"]
        assert pipeline.snapshot().finalize_active == 0


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (PipelineState.CAPTURED, "quick_and_upload"),
        (PipelineState.RAW_UPLOADING, "head_then_upload"),
        (PipelineState.RAW_UPLOADED, "wait_for_daytime_finalize"),
        (PipelineState.FULL_VERIFYING, "reclaim_finalize"),
        (PipelineState.VERIFIED_UPLOADED, "none"),
    ],
)
def test_resume_never_requests_recapture(tmp_path: Path, state: PipelineState, expected: str) -> None:
    store = ManagerStore(tmp_path / "resume.sqlite3")
    store.upsert_pipeline_item(PipelineItem(
        slot_start=kst(20, 0).isoformat(), camera_key="cam01", state=state,
        root=str(tmp_path), payload={"relative_dir": "recordings/2026-09-03/cam01/20-00-00"},
    ))
    with ThreadPoolExecutor(max_workers=1) as raw_pool, ThreadPoolExecutor(max_workers=1) as final_pool:
        pipeline = CaptureFirstPipeline(
            store=store, uploader=object(), repository=object(),
            quick_verify_fn=lambda raw: raw, finalize_fn=lambda raw: raw,
            raw_upload_executor=raw_pool, finalize_executor=final_pool,
        )
        summary = pipeline.resume()
    assert summary.action_for("cam01", kst(20, 0).isoformat()) == expected
    assert summary.recapture_count == 0


def test_resume_reclaims_interrupted_finalize_without_recapture(tmp_path: Path) -> None:
    raw = raw_result(tmp_path)
    raw.paths.video_part.replace(raw.paths.video)
    digest = __import__("hashlib").sha256(raw.paths.video.read_bytes()).hexdigest()
    store = ManagerStore(tmp_path / "reclaim.sqlite3")
    store.upsert_pipeline_item(PipelineItem(
        slot_start=raw.identity.scheduled_start_kst.isoformat(),
        camera_key="cam01", state=PipelineState.FULL_VERIFYING,
        root=str(raw.paths.root), payload={
            "relative_dir": raw.paths.relative_dir.as_posix(),
            "actual_start": raw.identity.actual_start_kst.isoformat(),
            "partial": False, "media": {"duration_sec": 60.0},
            "video_sha256": digest,
        },
    ))
    finalized: list[str] = []
    with ThreadPoolExecutor(max_workers=1) as raw_pool, ThreadPoolExecutor(max_workers=1) as final_pool:
        pipeline = CaptureFirstPipeline(
            store=store, uploader=object(), repository=object(),
            quick_verify_fn=lambda value: value, finalize_fn=lambda value: finalized.append(value.identity.camera_key),
            raw_upload_executor=raw_pool, finalize_executor=final_pool,
            configs={"cam01": raw.config},
        )
        pipeline.resume()
        pipeline.drain_ready_for_test(now=kst(8, 1))
    assert finalized == ["cam01"]
    assert store.list_pipeline_items()[0].state is PipelineState.VERIFIED_UPLOADED


def test_daytime_emits_exact_night_acceptance_once(tmp_path: Path) -> None:
    store = ManagerStore(tmp_path / "acceptance.sqlite3")
    for slot_index in range(24):
        slot = kst(20, 0) + timedelta(minutes=30 * slot_index)
        for camera_key in ("cam01", "cam02", "cam03"):
            store.upsert_pipeline_item(PipelineItem(
                slot_start=slot.isoformat(), camera_key=camera_key,
                state=PipelineState.VERIFIED_UPLOADED, root=str(tmp_path),
                payload={
                    "mode": "production", "relative_dir": "safe",
                    "actual_start": slot.isoformat(),
                    "media": {"duration_sec": 1783.0},
                },
            ))
    notifications: list[tuple[str, dict[str, object]]] = []
    with ThreadPoolExecutor(max_workers=1) as raw_pool, ThreadPoolExecutor(max_workers=1) as final_pool:
        pipeline = CaptureFirstPipeline(
            store=store, uploader=object(), repository=object(),
            quick_verify_fn=lambda value: value, finalize_fn=lambda value: value,
            raw_upload_executor=raw_pool, finalize_executor=final_pool,
            notifier=lambda kind, payload: notifications.append((kind, dict(payload))),
        )
        observed = datetime(2026, 9, 4, 13, 0, tzinfo=KST)
        pipeline.run_once(observed, capture_active=False)
        pipeline.run_once(observed, capture_active=False)

    assert notifications == [("night_acceptance", {
        "night_date": "2026-09-03", "state": "healthy",
        "expected_slots": 72, "verified_slots": 72,
        "start_delay_p95_sec": 0.0, "start_delay_max_sec": 0.0,
        "duration_min_sec": 1783.0,
    })]

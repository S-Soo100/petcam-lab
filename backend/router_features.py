"""Local Router feature metadata worker.

`clip_router_features` is the cheap evidence store for the local-router track.
This worker fills pending placeholder rows with OpenCV motion/event-shape
features so later routing can read metadata instead of video frames.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from supabase import Client

from backend.r2_uploader import get_r2_bucket, get_r2_client

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLL_INTERVAL_SEC = 60.0
DEFAULT_POLL_LIMIT = 10
DEFAULT_SAMPLE_FRAMES = 60
DEFAULT_STALE_PROCESSING_MINUTES = 30
DEFAULT_SLACK_INTERVAL_SEC = 1800.0
DEFAULT_SLACK_WINDOW_MINUTES = 30
ACTIVE_MOTION_THRESHOLD = 0.015
FEATURE_VERSION = "v1"
KST = timezone(timedelta(hours=9))


@dataclass(frozen=True, slots=True)
class MotionFeatureSet:
    """OpenCV-derived video features stored in clip_router_features."""

    motion_mean: float
    motion_peak: float
    motion_std: float
    active_motion_ratio: float
    center_motion_ratio: float
    late_motion_ratio: float
    motion_burst_count: int
    longest_motion_burst_sec: float
    first_motion_sec: float | None
    last_motion_sec: float | None
    motion_coverage_ratio: float
    evidence_reliability: str


@dataclass
class RouterFeatureStats:
    """One worker cycle summary."""

    polled: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0


@dataclass
class RouterFeatureWorker:
    """Poll pending feature rows, derive metadata, and update Supabase."""

    sb: Client
    poll_limit: int = DEFAULT_POLL_LIMIT
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC
    sample_frames: int = DEFAULT_SAMPLE_FRAMES
    stale_processing_minutes: int = DEFAULT_STALE_PROCESSING_MINUTES
    slack_webhook_url: str | None = None
    slack_interval_sec: float = DEFAULT_SLACK_INTERVAL_SEC
    slack_window_minutes: int = DEFAULT_SLACK_WINDOW_MINUTES
    feature_version: str = FEATURE_VERSION
    producer_name: str = "router-feature-worker"
    producer_host: str = field(default_factory=socket.gethostname)
    producer_run_id: str = field(default_factory=lambda: f"router-{_utc_now_compact()}-{uuid.uuid4().hex[:8]}")
    producer_code_ref: str = field(default_factory=lambda: _git_code_ref())
    total_stats: RouterFeatureStats = field(default_factory=RouterFeatureStats)
    _last_slack_sent_at: datetime | None = None

    async def poll_pending(self) -> list[dict[str, Any]]:
        def _pending_query(limit: int) -> list[dict[str, Any]]:
            resp = (
                self.sb.table("clip_router_features")
                .select("clip_id,camera_id,started_at")
                .eq("processing_status", "pending")
                .order("started_at", desc=False)
                .limit(limit)
                .execute()
            )
            return list(resp.data or [])

        def _stale_processing_query(limit: int) -> list[dict[str, Any]]:
            cutoff = _to_supabase_iso(
                datetime.now(timezone.utc)
                - timedelta(minutes=self.stale_processing_minutes)
            )
            resp = (
                self.sb.table("clip_router_features")
                .select("clip_id,camera_id,started_at")
                .eq("processing_status", "processing")
                .lte("updated_at", cutoff)
                .order("started_at", desc=False)
                .limit(limit)
                .execute()
            )
            return list(resp.data or [])

        pending = await asyncio.to_thread(_pending_query, self.poll_limit)
        remaining = self.poll_limit - len(pending)
        if remaining <= 0:
            return pending
        stale = await asyncio.to_thread(_stale_processing_query, remaining)
        return pending + stale

    async def process_row(self, row: dict[str, Any]) -> str:
        clip_id = row["clip_id"]
        await self._mark_processing(clip_id)
        try:
            clip = await self._fetch_clip(clip_id)
            if not clip:
                await self._mark_failed(clip_id, "camera_clips row not found")
                return "failed"

            with tempfile.TemporaryDirectory(prefix="petcam-router-features-") as tmp:
                video_path = await self._materialize_clip(clip, Path(tmp))
                features = await asyncio.to_thread(
                    extract_motion_features,
                    video_path,
                    sample_frames=self.sample_frames,
                    duration_hint=_float_or_none(clip.get("duration_sec")),
                )

            started_at = _parse_timestamptz(str(clip["started_at"]))
            camera_id = clip.get("camera_id")
            context = (
                await self._build_window_context(
                    camera_id=str(camera_id),
                    started_at=started_at,
                    active_motion_ratio=features.active_motion_ratio,
                )
                if camera_id
                else _empty_window_context()
            )
            feature_run_id = await self._insert_feature_run(clip, features, context)
            await self._mark_ready(clip_id, features, context, feature_run_id)
            return "ready"
        except Exception as exc:  # noqa: BLE001 - worker must survive bad clips.
            logger.exception("router feature processing failed: clip=%s", clip_id)
            await self._mark_failed(clip_id, f"{type(exc).__name__}: {exc}"[:1000])
            return "failed"

    async def run_once(self) -> RouterFeatureStats:
        stats = RouterFeatureStats()
        rows = await self.poll_pending()
        stats.polled = len(rows)
        for row in rows:
            outcome = await self.process_row(row)
            if outcome == "ready":
                stats.succeeded += 1
            elif outcome == "failed":
                stats.failed += 1
            else:
                stats.skipped += 1

        for field_name in ("polled", "succeeded", "failed", "skipped"):
            setattr(
                self.total_stats,
                field_name,
                getattr(self.total_stats, field_name) + getattr(stats, field_name),
            )
        return stats

    async def run(self, stop_event: asyncio.Event) -> None:
        logger.info(
            "router feature worker started — poll_interval=%.0fs limit=%d sample_frames=%d",
            self.poll_interval_sec,
            self.poll_limit,
            self.sample_frames,
        )
        while not stop_event.is_set():
            try:
                stats = await self.run_once()
                if stats.polled:
                    logger.info(
                        "cycle: polled=%d ok=%d failed=%d skipped=%d",
                        stats.polled,
                        stats.succeeded,
                        stats.failed,
                        stats.skipped,
                    )
                await self._maybe_send_slack_summary(stats)
            except Exception:  # noqa: BLE001
                logger.exception("router feature worker cycle failed")

            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self.poll_interval_sec
                )
            except asyncio.TimeoutError:
                continue

        logger.info(
            "router feature worker stopped — total: polled=%d ok=%d failed=%d skipped=%d",
            self.total_stats.polled,
            self.total_stats.succeeded,
            self.total_stats.failed,
            self.total_stats.skipped,
        )

    async def _fetch_clip(self, clip_id: str) -> dict[str, Any] | None:
        def _query() -> dict[str, Any] | None:
            resp = (
                self.sb.table("camera_clips")
                .select(
                    "id,camera_id,started_at,duration_sec,r2_key,file_path,"
                    "has_motion,motion_frames,width,height,fps"
                )
                .eq("id", clip_id)
                .single()
                .execute()
            )
            return resp.data

        return await asyncio.to_thread(_query)

    async def _mark_processing(self, clip_id: str) -> None:
        await self._update_row(clip_id, {"processing_status": "processing"})

    async def _mark_failed(self, clip_id: str, error: str) -> None:
        await self._update_row(
            clip_id,
            {
                "feature_version": self.feature_version,
                "producer_name": self.producer_name,
                "producer_host": self.producer_host,
                "producer_run_id": self.producer_run_id,
                "producer_code_ref": self.producer_code_ref,
                "feature_params": self._feature_params(),
                "processing_status": "failed",
                "processing_error": error,
                "processed_at": _utc_now_iso(),
            },
        )

    async def _mark_ready(
        self,
        clip_id: str,
        features: MotionFeatureSet,
        context: dict[str, Any],
        feature_run_id: str,
    ) -> None:
        payload = {
            "active_feature_run_id": feature_run_id,
            "feature_version": self.feature_version,
            "producer_name": self.producer_name,
            "producer_host": self.producer_host,
            "producer_run_id": self.producer_run_id,
            "producer_code_ref": self.producer_code_ref,
            "feature_params": self._feature_params(),
            "motion_mean": features.motion_mean,
            "motion_peak": features.motion_peak,
            "motion_std": features.motion_std,
            "active_motion_ratio": features.active_motion_ratio,
            "center_motion_ratio": features.center_motion_ratio,
            "late_motion_ratio": features.late_motion_ratio,
            "motion_burst_count": features.motion_burst_count,
            "longest_motion_burst_sec": features.longest_motion_burst_sec,
            "first_motion_sec": features.first_motion_sec,
            "last_motion_sec": features.last_motion_sec,
            "motion_coverage_ratio": features.motion_coverage_ratio,
            "evidence_reliability": features.evidence_reliability,
            "processing_status": "ready",
            "processing_error": None,
            "processed_at": _utc_now_iso(),
            **context,
        }
        await self._update_row(clip_id, payload)

    async def _insert_feature_run(
        self,
        clip: dict[str, Any],
        features: MotionFeatureSet,
        context: dict[str, Any],
    ) -> str:
        run_id = str(uuid.uuid4())
        output_snapshot = {
            "motion_mean": features.motion_mean,
            "motion_peak": features.motion_peak,
            "motion_std": features.motion_std,
            "active_motion_ratio": features.active_motion_ratio,
            "center_motion_ratio": features.center_motion_ratio,
            "late_motion_ratio": features.late_motion_ratio,
            "motion_burst_count": features.motion_burst_count,
            "longest_motion_burst_sec": features.longest_motion_burst_sec,
            "first_motion_sec": features.first_motion_sec,
            "last_motion_sec": features.last_motion_sec,
            "motion_coverage_ratio": features.motion_coverage_ratio,
            "evidence_reliability": features.evidence_reliability,
            **context,
        }
        payload = {
            "id": run_id,
            "clip_id": clip["id"],
            "feature_version": self.feature_version,
            "producer_name": self.producer_name,
            "producer_host": self.producer_host,
            "producer_run_id": self.producer_run_id,
            "producer_code_ref": self.producer_code_ref,
            "feature_params": self._feature_params(),
            "camera_id": clip.get("camera_id"),
            "started_at": clip.get("started_at"),
            "duration_sec": clip.get("duration_sec"),
            "has_motion": clip.get("has_motion"),
            "motion_frames": clip.get("motion_frames"),
            "width": clip.get("width"),
            "height": clip.get("height"),
            "fps": clip.get("fps"),
            "motion_mean": features.motion_mean,
            "motion_peak": features.motion_peak,
            "motion_std": features.motion_std,
            "active_motion_ratio": features.active_motion_ratio,
            "center_motion_ratio": features.center_motion_ratio,
            "late_motion_ratio": features.late_motion_ratio,
            "motion_burst_count": features.motion_burst_count,
            "longest_motion_burst_sec": features.longest_motion_burst_sec,
            "first_motion_sec": features.first_motion_sec,
            "last_motion_sec": features.last_motion_sec,
            "motion_coverage_ratio": features.motion_coverage_ratio,
            "evidence_reliability": features.evidence_reliability,
            "processing_status": "ready",
            "processing_error": None,
            "input_snapshot": {
                "r2_key_present": bool(clip.get("r2_key")),
                "file_path_present": bool(clip.get("file_path")),
                "duration_sec": clip.get("duration_sec"),
                "width": clip.get("width"),
                "height": clip.get("height"),
                "fps": clip.get("fps"),
            },
            "output_snapshot": output_snapshot,
            **context,
        }

        def _insert() -> None:
            self.sb.table("clip_router_feature_runs").insert(payload).execute()

        await asyncio.to_thread(_insert)
        return run_id

    def _feature_params(self) -> dict[str, Any]:
        return {
            "sample_frames": self.sample_frames,
            "active_motion_threshold": ACTIVE_MOTION_THRESHOLD,
            "opencv_version": cv2.__version__,
        }

    async def _update_row(self, clip_id: str, payload: dict[str, Any]) -> None:
        payload = {**payload, "updated_at": _utc_now_iso()}

        def _update() -> None:
            (
                self.sb.table("clip_router_features")
                .update(payload)
                .eq("clip_id", clip_id)
                .execute()
            )

        await asyncio.to_thread(_update)

    async def _materialize_clip(self, clip: dict[str, Any], tmp_dir: Path) -> Path:
        r2_key = clip.get("r2_key")
        if isinstance(r2_key, str) and r2_key:
            dst = tmp_dir / "clip.mp4"
            await asyncio.to_thread(download_r2_object, r2_key, dst)
            return dst

        file_path = clip.get("file_path")
        if isinstance(file_path, str):
            local_path = Path(file_path)
            if local_path.is_file():
                return local_path

        raise RuntimeError("clip has neither downloadable r2_key nor local file_path")

    async def _build_window_context(
        self,
        *,
        camera_id: str,
        started_at: datetime,
        active_motion_ratio: float,
    ) -> dict[str, Any]:
        lower = started_at - timedelta(minutes=60)
        upper = started_at + timedelta(minutes=60)

        def _query() -> list[dict[str, Any]]:
            resp = (
                self.sb.table("clip_router_features")
                .select("clip_id,started_at,active_motion_ratio")
                .eq("camera_id", camera_id)
                .gte("started_at", _to_supabase_iso(lower))
                .lte("started_at", _to_supabase_iso(upper))
                .order("started_at", desc=False)
                .limit(500)
                .execute()
            )
            return list(resp.data or [])

        rows = await asyncio.to_thread(_query)
        before: list[tuple[datetime, float | None]] = []
        after: list[datetime] = []
        for row in rows:
            row_time = _parse_timestamptz(str(row["started_at"]))
            if row_time < started_at:
                before.append((row_time, _float_or_none(row.get("active_motion_ratio"))))
            elif row_time > started_at:
                after.append(row_time)

        def _count_since(minutes: int) -> int:
            cutoff = started_at - timedelta(minutes=minutes)
            return sum(1 for row_time, _ in before if row_time >= cutoff)

        recent_values = [val for _, val in before if val is not None]
        recent_baseline = (
            float(np.mean(recent_values[-20:])) if recent_values else 0.0
        )
        prev_time = before[-1][0] if before else None
        next_time = after[0] if after else None

        return {
            "window_clip_count_10m": _count_since(10),
            "window_clip_count_30m": _count_since(30),
            "window_clip_count_60m": _count_since(60),
            "seconds_since_prev_clip": (
                (started_at - prev_time).total_seconds() if prev_time else None
            ),
            "seconds_until_next_clip": (
                (next_time - started_at).total_seconds() if next_time else None
            ),
            "recent_activity_baseline": recent_baseline,
            "activity_delta_from_baseline": active_motion_ratio - recent_baseline,
        }

    async def _maybe_send_slack_summary(self, stats: RouterFeatureStats) -> None:
        if not self.slack_webhook_url or self.slack_interval_sec <= 0:
            return

        now = datetime.now(timezone.utc)
        if (
            self._last_slack_sent_at is not None
            and (now - self._last_slack_sent_at).total_seconds()
            < self.slack_interval_sec
        ):
            return

        # no-op cycle(조회0·완료0·실패0)은 억제 — 실제 처리·실패·장기정체만 전송(30분 0건 반복 제거).
        stale_processing = 0
        if not (stats.polled or stats.succeeded or stats.failed):
            stale_processing = await asyncio.to_thread(self._count_stale_processing)
        if not router_should_send_summary(stats, stale_processing=stale_processing):
            logger.info(
                "router feature Slack suppressed (no-op cycle): polled=%d ok=%d failed=%d",
                stats.polled,
                stats.succeeded,
                stats.failed,
            )
            return

        try:
            summary = await self._build_slack_summary(stats)
            await asyncio.to_thread(send_slack_message, self.slack_webhook_url, summary)
            self._last_slack_sent_at = now
            logger.info("router feature Slack summary sent")
        except Exception:  # noqa: BLE001 - Slack 실패가 worker를 죽이면 안 됨.
            logger.exception("router feature Slack summary failed")

    def _count_stale_processing(self) -> int:
        """stale_processing_minutes 초과 processing row 수. 실패해도 0 반환(cycle 을 죽이지 않음)."""
        try:
            cutoff = _to_supabase_iso(
                datetime.now(timezone.utc) - timedelta(minutes=self.stale_processing_minutes)
            )
            resp = (
                self.sb.table("clip_router_features")
                .select("clip_id", count="exact")
                .eq("processing_status", "processing")
                .lt("updated_at", cutoff)
                .limit(1)
                .execute()
            )
            return int(resp.count or 0)
        except Exception:  # noqa: BLE001 - 관측용 count 실패가 worker 를 막으면 안 됨
            logger.exception("stale processing count failed")
            return 0

    async def _build_slack_summary(self, stats: RouterFeatureStats) -> str:
        window_start = datetime.now(timezone.utc) - timedelta(
            minutes=self.slack_window_minutes
        )

        def _count_status(status: str) -> int:
            resp = (
                self.sb.table("clip_router_features")
                .select("clip_id", count="exact")
                .eq("processing_status", status)
                .limit(1)
                .execute()
            )
            return int(resp.count or 0)

        def _count_recent_ready() -> int:
            resp = (
                self.sb.table("clip_router_features")
                .select("clip_id", count="exact")
                .eq("processing_status", "ready")
                .gte("processed_at", _to_supabase_iso(window_start))
                .limit(1)
                .execute()
            )
            return int(resp.count or 0)

        def _recent_failures() -> list[dict[str, Any]]:
            resp = (
                self.sb.table("clip_router_features")
                .select("clip_id,processing_error")
                .eq("processing_status", "failed")
                .order("updated_at", desc=True)
                .limit(3)
                .execute()
            )
            return list(resp.data or [])

        pending, processing, ready, failed, recent_ready, failures = await asyncio.gather(
            asyncio.to_thread(_count_status, "pending"),
            asyncio.to_thread(_count_status, "processing"),
            asyncio.to_thread(_count_status, "ready"),
            asyncio.to_thread(_count_status, "failed"),
            asyncio.to_thread(_count_recent_ready),
            asyncio.to_thread(_recent_failures),
        )
        return format_slack_summary(
            pending=pending,
            processing=processing,
            ready=ready,
            failed=failed,
            recent_ready=recent_ready,
            cycle_stats=stats,
            failures=failures,
            window_minutes=self.slack_window_minutes,
            now=datetime.now(timezone.utc),
        )


def download_r2_object(r2_key: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    get_r2_client().download_file(get_r2_bucket(), r2_key, str(dst))


def send_slack_message(webhook_url: str, text: str) -> None:
    payload = json.dumps({"text": text}).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status >= 300:
                raise RuntimeError(f"Slack webhook returned HTTP {response.status}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Slack webhook request failed: {exc}") from exc


def router_should_send_summary(cycle_stats: RouterFeatureStats, *, stale_processing: int = 0) -> bool:
    """no-op cycle(조회0·완료0·실패0, 정체 없음)은 Slack 억제 — 로그만. 실제 처리·실패·장기정체만 전송."""
    if cycle_stats.polled or cycle_stats.succeeded or cycle_stats.failed:
        return True
    return stale_processing > 0


def format_slack_summary(
    *,
    pending: int,
    processing: int,
    ready: int,
    failed: int,
    recent_ready: int,
    cycle_stats: RouterFeatureStats,
    failures: list[dict[str, Any]],
    window_minutes: int,
    now: datetime,
) -> str:
    kst_now = now.astimezone(KST)
    failed_sample = "없음"
    if failures:
        failed_sample = ", ".join(
            f"{str(row.get('clip_id', 'unknown'))[:8]}:{_short_error(row.get('processing_error'))}"
            for row in failures
        )
    return "\n".join(
        [
            f"🦎 라우터 메타 상황판 ({kst_now:%m/%d %H:%M KST})",
            f"· 최근 {window_minutes}분 완료 {recent_ready}건",
            f"· 전체 상태 ready {ready} / pending {pending} / processing {processing} / failed {failed}",
            (
                "· 이번 사이클 "
                f"조회 {cycle_stats.polled} · 완료 {cycle_stats.succeeded} · "
                f"실패 {cycle_stats.failed} · 스킵 {cycle_stats.skipped}"
            ),
            "· 샘플: 실패 " + failed_sample,
            "· 모드: R2+OpenCV metadata only, LLM/VLM 호출 없음",
        ]
    )


def extract_motion_features(
    video_path: Path,
    *,
    sample_frames: int = DEFAULT_SAMPLE_FRAMES,
    duration_hint: float | None = None,
) -> MotionFeatureSet:
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise RuntimeError(f"cannot open video: {video_path}")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = (
            frame_count / fps
            if fps > 0 and frame_count > 0
            else duration_hint
            if duration_hint is not None
            else 60.0
        )
        indices = _sample_indices(frame_count, sample_frames)

        grays: list[np.ndarray] = []
        brightness: list[float] = []
        for idx in indices:
            if frame_count > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            grays.append(gray)
            brightness.append(float(np.mean(gray)))

        if not grays:
            raise RuntimeError(f"no readable frames: {video_path}")

        motion_values: list[float] = []
        center_values: list[float] = []
        motion_times: list[float] = []
        for i, (prev, curr) in enumerate(zip(grays, grays[1:]), start=1):
            diff = cv2.absdiff(prev, curr)
            motion_mask = diff > 18
            motion = float(np.mean(motion_mask))
            motion_values.append(motion)
            motion_times.append((duration * i) / max(len(grays) - 1, 1))

            h, w = motion_mask.shape
            y1, y2 = h // 4, h - h // 4
            x1, x2 = w // 4, w - w // 4
            center = float(np.mean(motion_mask[y1:y2, x1:x2]))
            center_values.append(center / motion if motion > 0 else 0.0)

        if motion_values:
            motion_mean = float(np.mean(motion_values))
            late_start = max(0, (len(motion_values) * 2) // 3)
            late_mean = float(np.mean(motion_values[late_start:]))
            active_flags = [m > ACTIVE_MOTION_THRESHOLD for m in motion_values]
        else:
            motion_mean = 0.0
            late_mean = 0.0
            active_flags = []

        burst_count, longest_burst_sec = _burst_stats(active_flags, duration)
        active_times = [
            motion_times[i]
            for i, is_active in enumerate(active_flags)
            if is_active and i < len(motion_times)
        ]
        reliability = _evidence_reliability(brightness)

        return MotionFeatureSet(
            motion_mean=motion_mean,
            motion_peak=float(max(motion_values) if motion_values else 0.0),
            motion_std=float(np.std(motion_values) if motion_values else 0.0),
            active_motion_ratio=float(np.mean(active_flags)) if active_flags else 0.0,
            center_motion_ratio=float(np.mean(center_values)) if center_values else 0.0,
            late_motion_ratio=late_mean / motion_mean if motion_mean > 0 else 0.0,
            motion_burst_count=burst_count,
            longest_motion_burst_sec=longest_burst_sec,
            first_motion_sec=float(active_times[0]) if active_times else None,
            last_motion_sec=float(active_times[-1]) if active_times else None,
            motion_coverage_ratio=float(np.mean(active_flags)) if active_flags else 0.0,
            evidence_reliability=reliability,
        )
    finally:
        cap.release()


def _sample_indices(frame_count: int, sample_frames: int) -> list[int]:
    if sample_frames <= 0:
        raise ValueError("sample_frames must be positive")
    if frame_count <= 0:
        return list(range(sample_frames))
    count = min(sample_frames, frame_count)
    return np.linspace(0, max(frame_count - 1, 0), num=count, dtype=int).tolist()


def _burst_stats(active_flags: list[bool], duration: float) -> tuple[int, float]:
    if not active_flags:
        return 0, 0.0
    seconds_per_step = duration / max(len(active_flags), 1)
    burst_count = 0
    current = 0
    longest = 0
    for is_active in active_flags:
        if is_active:
            if current == 0:
                burst_count += 1
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return burst_count, float(longest * seconds_per_step)


def _empty_window_context() -> dict[str, Any]:
    return {
        "window_clip_count_10m": None,
        "window_clip_count_30m": None,
        "window_clip_count_60m": None,
        "seconds_since_prev_clip": None,
        "seconds_until_next_clip": None,
        "recent_activity_baseline": None,
        "activity_delta_from_baseline": None,
    }


def _short_error(value: Any) -> str:
    if not value:
        return "unknown"
    text = " ".join(str(value).split())
    return text[:60]


def _evidence_reliability(brightness: list[float]) -> str:
    if not brightness:
        return "low"
    mean = float(np.mean(brightness))
    std = float(np.std(brightness))
    if mean < 18.0 or std < 2.0:
        return "low"
    if std >= 8.0:
        return "high"
    return "medium"


def _parse_timestamptz(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_supabase_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_now_iso() -> str:
    return _to_supabase_iso(datetime.now(timezone.utc))


def _utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _git_code_ref() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:  # noqa: BLE001 - provenance should not block worker startup.
        return "unknown"
    return result.stdout.strip() or "unknown"


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


__all__ = [
    "DEFAULT_POLL_INTERVAL_SEC",
    "DEFAULT_POLL_LIMIT",
    "DEFAULT_SAMPLE_FRAMES",
    "DEFAULT_SLACK_INTERVAL_SEC",
    "DEFAULT_SLACK_WINDOW_MINUTES",
    "DEFAULT_STALE_PROCESSING_MINUTES",
    "MotionFeatureSet",
    "RouterFeatureStats",
    "RouterFeatureWorker",
    "download_r2_object",
    "extract_motion_features",
    "format_slack_summary",
    "send_slack_message",
]

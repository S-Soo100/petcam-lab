"""RAP C500G의 KST 관찰 구간과 안전한 bundle 경로 계산."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.rap_c500g_types import BundlePaths, RecordingMode, SegmentIdentity


KST = ZoneInfo("Asia/Seoul")
NIGHT_START = time(20, 0)
NIGHT_END = time(8, 0)
SLOT_MINUTES = 30


@dataclass(frozen=True, slots=True)
class SlotDecision:
    scheduled_start_kst: datetime
    capture_start_kst: datetime
    scheduled_end_kst: datetime
    night_date: date
    partial: bool

    @property
    def duration_sec(self) -> float:
        return (self.scheduled_end_kst - self.capture_start_kst).total_seconds()


def _as_kst(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(KST)


def observation_night(value: datetime) -> date:
    local = _as_kst(value)
    if local.time() < NIGHT_END:
        return local.date() - timedelta(days=1)
    return local.date()


def current_slot(now: datetime) -> SlotDecision | None:
    local = _as_kst(now)
    if NIGHT_END <= local.time() < NIGHT_START:
        return None

    minute = 0 if local.minute < SLOT_MINUTES else SLOT_MINUTES
    scheduled_start = local.replace(minute=minute, second=0, microsecond=0)
    scheduled_end = scheduled_start + timedelta(minutes=SLOT_MINUTES)
    return SlotDecision(
        scheduled_start_kst=scheduled_start,
        capture_start_kst=local,
        scheduled_end_kst=scheduled_end,
        night_date=observation_night(scheduled_start),
        partial=local != scheduled_start,
    )


def _segment_timestamp(value: datetime) -> str:
    return _as_kst(value).strftime("%Y%m%dT%H%M%S%z")


def build_bundle_paths(root: Path, identity: SegmentIdentity) -> BundlePaths:
    timestamp = _segment_timestamp(identity.scheduled_start_kst)
    if identity.mode is RecordingMode.TEST:
        if identity.test_run_id is None:
            raise ValueError("test_run_id is required for test recording")
        relative = Path(
            "c500g", "test", identity.test_run_id, identity.camera_key, timestamp
        )
    else:
        if identity.night_date is None:
            raise ValueError("night_date is required for production recording")
        relative = Path(
            "c500g",
            "recordings",
            identity.camera_key,
            f"night={identity.night_date.isoformat()}",
            timestamp,
        )

    bundle_dir = root / relative
    return BundlePaths(
        root=root,
        relative_dir=relative,
        bundle_dir=bundle_dir,
        video=bundle_dir / "video.mp4",
        video_part=bundle_dir / "video.part.mp4",
        thumbnail=bundle_dir / "thumbnail.jpg",
        log=bundle_dir / "ffmpeg.sanitized.log",
        log_part=bundle_dir / "ffmpeg.sanitized.log.part",
        manifest=bundle_dir / "manifest.json",
    )

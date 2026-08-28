"""RAP C500G 원본 녹화의 작은 도메인 타입."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path


CAMERA_KEYS = frozenset({"cam01", "cam02", "cam03"})
TEST_RUN_ID_PATTERN = re.compile(r"^test-\d{8}T\d{6}-KST-[0-9a-f]{8}$")


class RecordingMode(StrEnum):
    TEST = "test"
    PRODUCTION = "production"


def _validate_camera_key(camera_key: str) -> str:
    if camera_key not in CAMERA_KEYS:
        raise ValueError("camera_key must be one of cam01, cam02, cam03")
    return camera_key


def _require_aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class SegmentIdentity:
    mode: RecordingMode
    camera_key: str
    scheduled_start_kst: datetime
    actual_start_kst: datetime
    night_date: date | None
    test_run_id: str | None
    partial: bool

    @classmethod
    def production(
        cls,
        *,
        camera_key: str,
        scheduled_start_kst: datetime,
        actual_start_kst: datetime | None = None,
        partial: bool = False,
    ) -> "SegmentIdentity":
        from backend.rap_c500g_naming import observation_night

        scheduled = _require_aware(scheduled_start_kst, "scheduled_start_kst")
        actual = _require_aware(
            actual_start_kst or scheduled, "actual_start_kst"
        )
        return cls(
            mode=RecordingMode.PRODUCTION,
            camera_key=_validate_camera_key(camera_key),
            scheduled_start_kst=scheduled,
            actual_start_kst=actual,
            night_date=observation_night(scheduled),
            test_run_id=None,
            partial=partial,
        )

    @classmethod
    def test(
        cls,
        *,
        camera_key: str,
        scheduled_start_kst: datetime,
        test_run_id: str,
    ) -> "SegmentIdentity":
        scheduled = _require_aware(scheduled_start_kst, "scheduled_start_kst")
        if not TEST_RUN_ID_PATTERN.fullmatch(test_run_id):
            raise ValueError("test_run_id has an invalid format")
        return cls(
            mode=RecordingMode.TEST,
            camera_key=_validate_camera_key(camera_key),
            scheduled_start_kst=scheduled,
            actual_start_kst=scheduled,
            night_date=None,
            test_run_id=test_run_id,
            partial=False,
        )


@dataclass(frozen=True, slots=True)
class BundlePaths:
    root: Path
    relative_dir: Path
    bundle_dir: Path
    video: Path
    video_part: Path
    thumbnail: Path
    log: Path
    log_part: Path
    manifest: Path

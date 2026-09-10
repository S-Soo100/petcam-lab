from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend.rap_c500g_naming import (
    build_bundle_paths,
    current_slot,
    observation_night,
)
from backend.rap_c500g_types import SegmentIdentity


KST = ZoneInfo("Asia/Seoul")


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=KST)


def test_observation_night_keeps_after_midnight_segment_under_start_date() -> None:
    assert observation_night(dt("2026-08-27T00:15:00")) == date(2026, 8, 26)
    assert observation_night(dt("2026-08-26T20:15:00")) == date(2026, 8, 26)


def test_current_slot_rejects_daytime_and_marks_mid_slot_restart_partial() -> None:
    assert current_slot(dt("2026-08-26T19:59:00")) is None
    assert current_slot(dt("2026-08-27T08:00:00")) is None

    slot = current_slot(dt("2026-08-27T00:15:00"))
    assert slot is not None
    assert slot.scheduled_start_kst == dt("2026-08-27T00:00:00")
    assert slot.capture_start_kst == dt("2026-08-27T00:15:00")
    assert slot.scheduled_end_kst == dt("2026-08-27T00:30:00")
    assert slot.partial is True
    assert slot.night_date == date(2026, 8, 26)


def test_production_bundle_path_matches_r2_key_contract(tmp_path: Path) -> None:
    identity = SegmentIdentity.production(
        camera_key="cam02",
        scheduled_start_kst=dt("2026-08-27T00:00:00"),
        actual_start_kst=dt("2026-08-27T00:15:00"),
        partial=True,
    )

    paths = build_bundle_paths(tmp_path, identity)

    assert paths.relative_dir.as_posix() == (
        "recordings/cam02/night=2026-08-26/20260827T000000+0900"
    )
    assert paths.bundle_dir == tmp_path / paths.relative_dir
    assert paths.video.name == "video.mp4"
    assert paths.video_part.name == "video.part.mp4"


def test_test_bundle_path_includes_validated_run_id(tmp_path: Path) -> None:
    identity = SegmentIdentity.test(
        camera_key="cam01",
        scheduled_start_kst=dt("2026-08-26T13:42:27"),
        test_run_id="test-20260826T134227-KST-a1b2c3d4",
    )

    paths = build_bundle_paths(tmp_path, identity)

    assert paths.relative_dir.as_posix() == (
        "test/test-20260826T134227-KST-a1b2c3d4/"
        "cam01/20260826T134227+0900"
    )


@pytest.mark.parametrize("camera", ["cam04", "cam/01", "..", ""])
def test_segment_identity_rejects_unknown_or_path_traversal_camera(camera: str) -> None:
    with pytest.raises(ValueError, match="camera_key"):
        SegmentIdentity.test(
            camera_key=camera,
            scheduled_start_kst=dt("2026-08-26T13:42:27"),
            test_run_id="test-20260826T134227-KST-a1b2c3d4",
        )


@pytest.mark.parametrize("run_id", ["../escape", "test/run", "arbitrary", ""])
def test_segment_identity_rejects_unsafe_test_run_id(run_id: str) -> None:
    with pytest.raises(ValueError, match="test_run_id"):
        SegmentIdentity.test(
            camera_key="cam01",
            scheduled_start_kst=dt("2026-08-26T13:42:27"),
            test_run_id=run_id,
        )

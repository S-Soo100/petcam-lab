import fcntl
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.research_runtime.production_guard import (
    GuardConfig,
    evaluate_guard,
    load_guard_config,
)


KST = ZoneInfo("Asia/Seoul")


@contextmanager
def held_flock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w")
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def config_for(lock: Path) -> GuardConfig:
    return GuardConfig(
        timezone="Asia/Seoul",
        segment_max_seconds=300,
        minimum_buffer_seconds=300,
        locks=(("activity", lock),),
        windows=(),
    )


def test_guard_defers_without_holding_busy_production_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "activity.lock"
    with held_flock(lock_path):
        decision = evaluate_guard(
            now=datetime(2026, 7, 28, 10, 10, tzinfo=KST),
            config=config_for(lock_path),
            segment_seconds=300,
        )
    assert decision.allowed is False
    assert decision.reason == "activity_lock_busy"


def test_guard_defers_when_segment_crosses_backfill_window() -> None:
    config = load_guard_config(Path("config/research-runtime-quiet-windows.json"))
    decision = evaluate_guard(
        now=datetime(2026, 7, 28, 10, 21, tzinfo=KST),
        config=config,
        segment_seconds=300,
    )
    assert decision.allowed is False
    assert decision.reason == "quiet_window_insufficient"


def test_guard_allows_clear_window() -> None:
    config = load_guard_config(Path("config/research-runtime-quiet-windows.json"))
    decision = evaluate_guard(
        now=datetime(2026, 7, 28, 10, 5, tzinfo=KST),
        config=config,
        segment_seconds=300,
    )
    assert decision.allowed is True

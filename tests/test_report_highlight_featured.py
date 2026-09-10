"""report_highlight_featured.day_window — 20시 경계 하루 창(petcam-api featured_window 와 같은 정의)."""

from datetime import datetime, timezone

from scripts.report_highlight_featured import day_window


def test_window_covers_days_from_day_key_start() -> None:
    now = datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc)  # 10:00 KST → 오늘 키 = 2026-09-09
    p_from, p_to = day_window(now, 7)
    assert p_from == datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)  # 09-03 20:00 KST
    assert p_to == now


def test_window_after_20_kst_moves_key_to_today() -> None:
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)  # 21:00 KST → 오늘 키 = 2026-09-10
    p_from, _ = day_window(now, 1)
    assert p_from == datetime(2026, 9, 10, 11, 0, tzinfo=timezone.utc)

"""T0 bowl-dwell probe 순수 함수 테스트 (DB/R2/네트워크 불필요)."""
import numpy as np


def test_draw_grid_overlay():
    from scripts.t0_bowl_grid_frames import draw_grid_overlay

    frame = np.zeros((960, 1280, 3), dtype=np.uint8)
    out = draw_grid_overlay(frame)
    assert out.shape == frame.shape
    # 그리드 선이 그려졌으면 순흑이 아님
    assert out.sum() > 0
    # 원본 불변 (복사본에 그림)
    assert frame.sum() == 0

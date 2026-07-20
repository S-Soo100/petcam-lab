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


def test_bowl_dwell_sec():
    from scripts.t0_bowl_dwell_rank import bowl_dwell_sec

    dwell = {"grid_size": 4, "observed_sec": 30.0, "n_observations": 8,
             "cells": [[0.5, 0, 0, 0], [0, 0, 0, 0], [0, 0.3, 0, 0], [0, 0, 0.2, 0]]}
    # r3c2(0.2) + r2c1(0.3) 지정 → (0.2+0.3)*30 = 15.0
    assert bowl_dwell_sec(dwell, [(3, 2), (2, 1)]) == 15.0
    # 그릇 셀에 체류 없음 → 0
    assert bowl_dwell_sec(dwell, [(0, 3)]) == 0.0
    # 셀 지정 없음 → 0
    assert bowl_dwell_sec(dwell, []) == 0.0


def test_eligible_filter():
    from scripts.t0_bowl_dwell_rank import is_eligible

    ok = {"observed_sec": 10.0, "n_observations": 5, "cells": [[0.0] * 4] * 4}
    assert is_eligible({"level0_status": "ok", "level1_status": "ok", "spatial_dwell": ok})
    # no_bbox 는 dwell 무효
    assert not is_eligible({"level0_status": "ok", "level1_status": "no_bbox", "spatial_dwell": ok})
    # 관찰 시간/횟수 미달 = 노이즈 (TEST-SHEET §2)
    assert not is_eligible({"level0_status": "ok", "level1_status": "ok",
                            "spatial_dwell": {**ok, "observed_sec": 3.0}})
    assert not is_eligible({"level0_status": "ok", "level1_status": "ok",
                            "spatial_dwell": {**ok, "n_observations": 2}})
    assert not is_eligible({"level0_status": "ok", "level1_status": "ok", "spatial_dwell": None})


def test_sample_split_deterministic():
    from scripts.t0_bowl_dwell_rank import sample_split

    ranked = [{"clip_id": f"c{i}", "bowl_dwell": 100.0 - i} for i in range(100)]
    top1, rand1 = sample_split(ranked, top_n=60, random_n=20, seed=20260720)
    top2, rand2 = sample_split(ranked, top_n=60, random_n=20, seed=20260720)
    assert top1 == top2 and rand1 == rand2          # 결정론
    assert len(top1) == 60 and len(rand1) == 20
    assert {c["clip_id"] for c in top1} == {f"c{i}" for i in range(60)}  # dwell 내림차순 상위
    assert not ({c["clip_id"] for c in rand1} & {c["clip_id"] for c in top1})  # 배타

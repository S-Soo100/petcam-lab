"""분류기 arm (TEST-SHEET §5-2) — 로지스틱 회귀 + 그룹 leave-one-out. 상한 확인용, adopt 대상 아님."""
from __future__ import annotations

import math

import numpy as np

from scripts.nonvlm_behavior_v0.classifier_cv import group_loo_predict


def _separable(n_per=12, seed=1):
    rng = np.random.default_rng(seed)
    X, y, g = [], [], []
    centers = {"moving": (0.9, 1.0), "feeding": (0.1, 12.0), "hand_feeding": (0.5, 1.0)}
    for cls, (a, b) in centers.items():
        for i in range(n_per):
            X.append([a + rng.normal(0, 0.03), b + rng.normal(0, 0.3), 0.0 if cls != "hand_feeding" else 6.0])
            y.append(cls)
            g.append(f"g{i % 4}")
    return X, y, g


def test_group_loo_recovers_separable_classes():
    X, y, g = _separable()
    pred = group_loo_predict(X, y, g)
    acc = sum(p == t for p, t in zip(pred, y)) / len(y)
    assert acc >= 0.9


def test_group_loo_never_trains_on_held_out_group():
    # 그룹 "gX" 만 라벨이 뒤집혀 있으면, 그 그룹은 다른 그룹으로 학습된 모델이 예측하므로 원래(다수) 라벨로 나온다.
    X, y, g = _separable()
    y_flipped = [("feeding" if grp == "g0" and lab == "moving" else lab) for lab, grp in zip(y, g)]
    pred = group_loo_predict(X, y_flipped, g)
    g0_originally_moving = [p for p, grp, lab in zip(pred, g, y) if grp == "g0" and lab == "moving"]
    assert g0_originally_moving and all(p == "moving" for p in g0_originally_moving)


def test_handles_nan_and_constant_features_without_crashing():
    X, y, g = _separable()
    X[0][0] = math.nan
    X = [row + [1.0] for row in X]  # 상수 특징 추가 (std=0)
    pred = group_loo_predict(X, y, g)
    assert len(pred) == len(y)

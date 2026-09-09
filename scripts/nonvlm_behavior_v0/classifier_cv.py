"""분류기 arm (TEST-SHEET §5-2): 소프트맥스 로지스틱 회귀 1개 고정 + 그룹 leave-one-out. 상한 확인용.

왜 numpy 로 직접 쓰나: scikit-learn 을 pyproject 에 추가하지 않기 위해(연구 스크립트 하나 때문에 production
의존성을 늘리지 않는다). 하이퍼파라미터 탐색 없음 — 고정값 (epochs 300 · lr 0.1 · L2 1e-3), 시험지 사후 변경 금지.
"""
from __future__ import annotations

import numpy as np

EPOCHS = 300
LR = 0.1
L2 = 1e-3


def _prepare(X_train: np.ndarray, X_test: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """train 통계로만 결측 대체(중앙값)·표준화. 상수 특징은 std=1 로 두어 0 나눗셈을 피한다."""
    all_nan = np.isnan(X_train).all(axis=0)
    safe = np.where(all_nan[None, :], 0.0, X_train)  # 전부 NaN 인 열은 nanmedian 경고 없이 0 으로
    med = np.nanmedian(safe, axis=0)
    med = np.where(np.isnan(med), 0.0, med)
    Xtr = np.where(np.isnan(X_train), med, X_train)
    Xte = np.where(np.isnan(X_test), med, X_test)
    mean, std = Xtr.mean(axis=0), Xtr.std(axis=0)
    std = np.where(std < 1e-12, 1.0, std)
    return (Xtr - mean) / std, (Xte - mean) / std


def _fit_softmax(X: np.ndarray, y_idx: np.ndarray, n_classes: int) -> tuple[np.ndarray, np.ndarray]:
    n, d = X.shape
    counts = np.bincount(y_idx, minlength=n_classes).astype(float)
    weights = np.where(counts > 0, n / (n_classes * np.maximum(counts, 1)), 0.0)[y_idx]  # balanced
    W = np.zeros((d, n_classes))
    b = np.zeros(n_classes)
    Y = np.eye(n_classes)[y_idx]
    for _ in range(EPOCHS):
        logits = X @ W + b
        logits -= logits.max(axis=1, keepdims=True)
        p = np.exp(logits)
        p /= p.sum(axis=1, keepdims=True)
        grad = (p - Y) * weights[:, None] / n
        W -= LR * (X.T @ grad + L2 * W)
        b -= LR * grad.sum(axis=0)
    return W, b


def group_loo_predict(X, y, groups) -> list[str]:
    Xa = np.asarray(X, dtype=float)
    ya = np.asarray(y)
    ga = np.asarray(groups)
    classes = sorted(set(ya.tolist()))
    cls_idx = {c: i for i, c in enumerate(classes)}
    y_idx = np.array([cls_idx[v] for v in ya])
    pred = np.empty(len(ya), dtype=object)
    for g in sorted(set(ga.tolist())):
        test = ga == g
        train = ~test
        Xtr, Xte = _prepare(Xa[train], Xa[test])
        W, b = _fit_softmax(Xtr, y_idx[train], len(classes))
        pred[test] = [classes[i] for i in (Xte @ W + b).argmax(axis=1)]
    return pred.tolist()

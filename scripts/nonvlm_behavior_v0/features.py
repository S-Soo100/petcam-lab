"""GME 확장 artifact → 시험지 §4 특징 (F1~F7, F9~F11). F8(head_micro)는 head_micro.py.

입력 artifact 형식 (run_gme_local 이 쓰는 확장 JSON):
  {"gme": {"duration_sec", "intervals": [...], "track_points": [...]},
   "summary": {"candidate_moving_sec_any_gecko", "visible_sec", "unknown_sec", "camera_motion_sec",
               "max_simultaneous_geckos", ...}}

왜 순수 함수인가: 특징은 GT 를 절대 읽지 않는 결정론 계산이어야 무결성 6단계의 ②가 성립한다.
numpy 없이도 되는 계산이라 표준 라이브러리만 쓴다 (테스트가 빠르고 의존성이 0).
"""
from __future__ import annotations

import math
from collections import defaultdict

ANALYSIS_FPS = 10.0  # production GME 계약 (시험지 §3). camera_motion 초 → 프레임 환산에만 사용


def _merge_runs(intervals: list[dict], state: str) -> list[tuple[float, float]]:
    """같은 state 가 시간상 붙어 있으면 한 구간으로 합친다 (track_ids 가 달라도 합침)."""
    runs: list[tuple[float, float]] = []
    for iv in sorted(intervals, key=lambda v: v["start_sec"]):
        if iv["state"] != state:
            continue
        s, e = float(iv["start_sec"]), float(iv["end_sec"])
        if runs and abs(runs[-1][1] - s) < 1e-6:
            runs[-1] = (runs[-1][0], e)
        else:
            runs.append((s, e))
    return runs


def _longest(runs: list[tuple[float, float]]) -> tuple[float, float, float]:
    if not runs:
        return 0.0, math.nan, math.nan
    s, e = max(runs, key=lambda r: r[1] - r[0])
    return e - s, s, e


def _diag(w: float, h: float) -> float:
    return math.hypot(w, h)


def _in_runs(t: float, runs: list[tuple[float, float]]) -> bool:
    return any(s - 1e-9 <= t < e + 1e-9 for s, e in runs)


def compute_features(artifact: dict) -> dict:
    gme = artifact["gme"]
    summary = artifact["summary"]
    duration = float(gme.get("duration_sec") or summary.get("duration_sec") or 0.0)
    intervals = list(gme.get("intervals", []))
    points = sorted(gme.get("track_points", []), key=lambda p: (p["track_id"], p["timestamp_sec"]))

    visible = float(summary.get("visible_sec", 0.0))
    moving_sec = float(summary.get("candidate_moving_sec_any_gecko", 0.0))
    moving_ratio = moving_sec / visible if visible > 0 else math.nan

    static_runs = _merge_runs(intervals, "static")
    moving_runs = _merge_runs(intervals, "moving")
    longest_static, static_s, static_e = _longest(static_runs)
    longest_moving, _, _ = _longest(moving_runs)

    # F5 / F11: 같은 track 의 인접 포인트끼리만 비교 (track 이 끊기면 억지로 잇지 않는다 — GME 계약 §4.5)
    by_track: dict[str, list[dict]] = defaultdict(list)
    for p in points:
        by_track[p["track_id"]].append(p)
    disps: list[float] = []
    area_jump = 1.0
    for track_points in by_track.values():
        for prev, cur in zip(track_points, track_points[1:]):
            x0, y0, w0, h0 = prev["bbox_norm"]
            x1, y1, w1, h1 = cur["bbox_norm"]
            body = (_diag(w0, h0) + _diag(w1, h1)) / 2.0
            if body > 0:
                disps.append(math.hypot((x1 + w1 / 2) - (x0 + w0 / 2), (y1 + h1 / 2) - (y0 + h0 / 2)) / body)
            a0, a1 = w0 * h0, w1 * h1
            if a0 > 0 and a1 > 0:
                area_jump = max(area_jump, a1 / a0, a0 / a1)

    # F6: static 구간 안의 포인트만으로 w/h 표준편차 (모집단)
    ratios = [p["bbox_norm"][2] / p["bbox_norm"][3] for p in points if _in_runs(p["timestamp_sec"], static_runs)]
    if len(ratios) >= 2:
        mean = sum(ratios) / len(ratios)
        aspect_osc = math.sqrt(sum((r - mean) ** 2 for r in ratios) / len(ratios))
    else:
        aspect_osc = math.nan

    cam_runs = _merge_runs(intervals, "camera_motion")
    cam_sec = float(summary.get("camera_motion_sec", sum(e - s for s, e in cam_runs)))
    global_change_frames = int(round(cam_sec * ANALYSIS_FPS))
    first_global_change = cam_runs[0][0] if cam_runs else math.nan

    not_visible_sec = sum(e - s for s, e in _merge_runs(intervals, "not_visible"))
    unknown_sec = float(summary.get("unknown_sec", 0.0))

    return {
        "moving_ratio": moving_ratio,
        "longest_static_sec": longest_static,
        "longest_static_start_sec": static_s,
        "longest_static_end_sec": static_e,
        "longest_moving_sec": longest_moving,
        "n_moving_bouts": len(moving_runs),
        "disp_mean": (sum(disps) / len(disps)) if disps else math.nan,
        "disp_max": max(disps) if disps else math.nan,
        "aspect_osc": aspect_osc,
        "global_change_frames": global_change_frames,
        "first_global_change_sec": first_global_change,
        "unknown_ratio": unknown_sec / duration if duration > 0 else math.nan,
        "not_visible_ratio": not_visible_sec / duration if duration > 0 else math.nan,
        "max_geckos": int(summary.get("max_simultaneous_geckos", 0)),
        "bbox_area_jump": area_jump,
    }

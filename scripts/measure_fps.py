"""
RTSP 실제 프레임 수신률 측정 스크립트 (Stage A 46~47초 이슈 진단용).

## 존재의의
Stage A 구현 직후 저장된 1분 세그먼트 mp4 들이 전부 **46~47초로 재생**되는
현상을 발견했다. 원인 후보:

    (가설 1) Tapo C200 이 실제로 15fps 보다 적게 보낸다 (실 송출 ~11~12fps).
    (가설 2) OpenCV VideoCapture 가 내부 버퍼/디코딩에서 프레임을 드랍한다.
    (가설 3) 두 요인 혼재.

backend/capture.py 의 VideoWriter 는 fps=15 로 고정 기록하므로,
실제 수신 FPS 가 15 보다 작으면:
    재생 시간 = frame_count / 15  →  60초 wall-clock 기록인데 ~46초로 재생됨.

## 목적
1. 카메라가 보고하는 메타 FPS (`CAP_PROP_FPS`) 확인.
2. 실측 수신 FPS (20초간 `cap.read()` 성공 횟수 / 경과시간) 산출.
3. 프레임 간 지연 분포 (avg / p50 / p95 / p99 / max) 측정.
4. 결과로 어느 가설이 맞는지 힌트 제공 → Stage B 에서 수정 방향 결정.

## 출력 해석
- effective_fps ≈ 15 → 가설 1 기각, OpenCV 드랍(가설 2) 의심
- effective_fps < 13 → 가설 1 유력 (Tapo 가 적게 보냄)
- p95 delay >> avg*2 → 버퍼링 의심 (간헐적 큰 지연)

## 사용법
    uv run python scripts/measure_fps.py

프린트 결과를 이 스크립트 주석 혹은 specs/stage-a-streaming.md "학습 노트" 에
기록하고 Stage B 진입 전에 해결 방향을 정한다.
"""


from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

import cv2
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parent.parent

# 측정 설정
WARMUP_FRAMES = 10        # 초기 드랍할 프레임 수 (연결 직후 안정화 대기)
MEASURE_SECONDS = 20.0    # 측정 윈도우 길이 (초)
CONNECT_TIMEOUT_SEC = 30  # VideoCapture 열기 대기 한계 (초)


def mask_rtsp_url(url: str) -> str:
    """비밀번호 로그 노출 방지."""
    if "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    _, host = rest.split("@", 1)
    return f"{scheme}://***:***@{host}"


def percentile(values: list[float], p: float) -> float:
    """0~100 의 백분위값. numpy 없이 직접 계산."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    rtsp_url = os.getenv("RTSP_URL")
    if not rtsp_url:
        print("[ERROR] RTSP_URL 환경변수가 비어있어. .env 파일 확인해.")
        return 1

    print(f"[INFO] 연결 시도: {mask_rtsp_url(rtsp_url)}")

    t0 = time.perf_counter()
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        cap.release()
        print("[ERROR] VideoCapture 열기 실패.")
        return 2
    print(f"[INFO] 연결 성공 ({time.perf_counter() - t0:.2f}s)")

    # --- 메타정보 ---
    meta_fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    # BUFFERSIZE 는 백엔드에 따라 -1 또는 0 일 수 있음 (지원 안 함)
    buffer_size = cap.get(cv2.CAP_PROP_BUFFERSIZE)

    print("")
    print("=" * 60)
    print("[META] 카메라가 보고하는 값")
    print(f"  CAP_PROP_FPS         = {meta_fps:.2f}")
    print(f"  resolution           = {width}x{height}")
    print(f"  CAP_PROP_BUFFERSIZE  = {buffer_size}")
    print("=" * 60)

    # --- Warmup ---
    print(f"\n[WARMUP] 초반 {WARMUP_FRAMES} 프레임 드랍 (안정화)")
    warmup_ok = 0
    for _ in range(WARMUP_FRAMES):
        ok, _ = cap.read()
        if ok:
            warmup_ok += 1
    print(f"[WARMUP] {warmup_ok}/{WARMUP_FRAMES} 성공")

    if warmup_ok == 0:
        cap.release()
        print("[ERROR] warmup 중 단 한 프레임도 못 받음. 측정 중단.")
        return 3

    # --- 측정 ---
    print(f"\n[MEASURE] {MEASURE_SECONDS:.0f}초간 수신률 측정 시작...")
    frame_times: list[float] = []   # 각 프레임 수신 시각
    fail_count = 0

    start = time.perf_counter()
    while True:
        now = time.perf_counter()
        elapsed = now - start
        if elapsed >= MEASURE_SECONDS:
            break

        ok, _ = cap.read()
        if ok:
            frame_times.append(time.perf_counter())
        else:
            fail_count += 1

    total_elapsed = time.perf_counter() - start
    cap.release()

    frame_count = len(frame_times)
    if frame_count < 2:
        print(f"[ERROR] 수신 프레임 부족: {frame_count}. 네트워크 확인 필요.")
        return 4

    # --- 분석 ---
    effective_fps = frame_count / total_elapsed

    # 인접 프레임 간 지연 (밀리초 단위)
    deltas_ms = [
        (frame_times[i] - frame_times[i - 1]) * 1000.0
        for i in range(1, frame_count)
    ]
    avg_ms = statistics.mean(deltas_ms)
    p50_ms = percentile(deltas_ms, 50)
    p95_ms = percentile(deltas_ms, 95)
    p99_ms = percentile(deltas_ms, 99)
    max_ms = max(deltas_ms)
    min_ms = min(deltas_ms)

    print("")
    print("=" * 60)
    print("[RESULT] 측정 결과")
    print(f"  측정시간           : {total_elapsed:.2f}s")
    print(f"  수신 프레임        : {frame_count}")
    print(f"  read 실패          : {fail_count}")
    print(f"  effective FPS     : {effective_fps:.2f}")
    print("")
    print(f"  프레임 간 지연 (ms)")
    print(f"    avg  : {avg_ms:.1f}")
    print(f"    min  : {min_ms:.1f}")
    print(f"    p50  : {p50_ms:.1f}")
    print(f"    p95  : {p95_ms:.1f}")
    print(f"    p99  : {p99_ms:.1f}")
    print(f"    max  : {max_ms:.1f}")
    print("=" * 60)

    # --- 해석 ---
    print("\n[해석]")
    if effective_fps >= 14.0:
        print(f"  · effective_fps {effective_fps:.2f} ≈ 15 → 카메라는 정상 송출")
        print(f"    46~47초 문제의 원인이 프레임 드랍이 아닐 수 있음.")
        print(f"    → VideoWriter 타이밍/코덱 쪽을 더 파봐야 함.")
    elif effective_fps >= 12.0:
        print(f"  · effective_fps {effective_fps:.2f} (13~14 범위) → 약한 드랍 존재")
        print(f"    VideoWriter fps={effective_fps:.0f} 로 맞추면 재생시간 정상화됨.")
    else:
        print(f"  · effective_fps {effective_fps:.2f} < 12 → 드랍이 심함 (가설 1/2 혼재)")
        print(f"    (A) VideoWriter fps={effective_fps:.0f} 로 하향 조정")
        print(f"    (B) cap.set(CAP_PROP_BUFFERSIZE, 1) 시도")
        print(f"    (C) FFmpeg subprocess 대체 검토")

    if p95_ms > avg_ms * 2:
        print(f"  · p95 delay ({p95_ms:.1f}ms) >> avg*2 ({avg_ms*2:.1f}ms)")
        print(f"    → 간헐적 큰 지연 존재. 버퍼링/네트워크 지터 의심.")

    # 이론상 60초 wall-clock 에서 몇 초짜리 영상이 될지 시뮬레이션
    expected_playback_sec = (effective_fps * 60.0) / 15.0
    print(f"\n[예측] 60초 녹화 → fps=15 로 기록 시 예상 재생시간: {expected_playback_sec:.1f}초")
    print(f"       (실측 46~47초와 비교해서 가설 검증)")

    return 0


if __name__ == "__main__":
    sys.exit(main())

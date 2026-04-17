"""
RTSP 연결 스모크 테스트.

단 한 프레임을 읽어서 storage/ 에 JPG로 저장한다.
성공하면 카메라/네트워크/코덱이 전부 정상.

사용법:
    1) .env.example 을 .env 로 복사하고 RTSP_URL 채우기
    2) uv run python scripts/test_rtsp.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import cv2
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")

    rtsp_url = os.getenv("RTSP_URL")
    if not rtsp_url:
        print("[ERROR] RTSP_URL 환경변수가 비어있어. .env 파일 확인해.")
        return 1

    snapshot_path = REPO_ROOT / os.getenv(
        "TEST_SNAPSHOT_PATH", "storage/test_snapshot.jpg"
    )
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    # 비밀번호는 로그에 안 남기기
    masked = rtsp_url
    if "@" in rtsp_url:
        scheme, rest = rtsp_url.split("://", 1)
        _, host = rest.split("@", 1)
        masked = f"{scheme}://***:***@{host}"
    print(f"[INFO] 연결 시도: {masked}")

    t0 = time.time()
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        print("[ERROR] VideoCapture 오픈 실패. URL/네트워크/계정 확인.")
        return 2

    print(f"[INFO] 연결 성공 ({time.time() - t0:.2f}s). 첫 프레임 읽는 중...")
    ok, frame = cap.read()
    cap.release()

    if not ok or frame is None:
        print("[ERROR] 프레임 읽기 실패.")
        return 3

    h, w = frame.shape[:2]
    cv2.imwrite(str(snapshot_path), frame)
    print(f"[OK] 저장 완료: {snapshot_path} ({w}x{h})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

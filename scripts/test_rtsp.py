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

# 재시도 설정
CONNECT_MAX_RETRIES = 3        # RTSP 연결 최대 시도 횟수
CONNECT_RETRY_INTERVAL = 1.0   # 연결 실패 후 다음 시도까지 대기 (초)
FRAME_MAX_RETRIES = 10         # 프레임 읽기 최대 시도 횟수
FRAME_RETRY_INTERVAL = 0.1     # 프레임 실패 후 다음 read() 까지 대기 (초)


def open_capture_with_retry(rtsp_url: str) -> cv2.VideoCapture | None:
    """RTSP 연결을 최대 CONNECT_MAX_RETRIES 번 시도한다.
    
    성공 -> 연결된 VideoCapture 객체 반환
        전부 실패 -> None 반환
    """
    for attempt in range(1, CONNECT_MAX_RETRIES + 1):
        t0 = time.time()
        cap = cv2.VideoCapture(rtsp_url)
        if cap.isOpened():
            elapsed = time.time() - t0
            print(f"[INFO] 연결 성공 (시도 {attempt}/{CONNECT_MAX_RETRIES}, {elapsed:.2f}s)")
            return cap
        
        cap.release() # 실패한 cap도 반드시 닫기 (리소스 누수 방지)
        if attempt < CONNECT_MAX_RETRIES:
            print(f"[WARN] 연결 실패 (시도 {attempt}/{CONNECT_MAX_RETRIES}). {CONNECT_RETRY_INTERVAL:.1f}s 후 재시도...")
            time.sleep(CONNECT_RETRY_INTERVAL)
        
    print(f"[ERROR] 최대 시도 횟수 {CONNECT_MAX_RETRIES}회 재시도 모두 실패.")
    return None


def read_frame_with_retry(cap: cv2.VideoCapture):
    """열린 cap에서 유효한 프레임을 최대 FRAME_MAX_RETRIES 번 시도한다.
    
    성공 -> numpy array (프레임) 리턴
    전부 실패 -> None 리턴    
    """
    for attempt in range(1, FRAME_MAX_RETRIES + 1):
        ok, frame = cap.read()
        if ok and frame is not None:
            print(f"[INFO] 프레임 수신 성공 (시도 {attempt}/{FRAME_MAX_RETRIES})")
            return frame
        
        if attempt < FRAME_MAX_RETRIES:
            print(f"[WARN] 빈 프레임 (시도 {attempt}/{FRAME_MAX_RETRIES}). {FRAME_RETRY_INTERVAL:.1f}s 후 재시도...")
            time.sleep(FRAME_RETRY_INTERVAL)

    print(f"[ERROR] 최대 시도 횟수 {FRAME_MAX_RETRIES}회 프레임 모두 실패")
    return None


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

    cap = open_capture_with_retry(rtsp_url)
    if cap is None:
        return 2
    
    frame = read_frame_with_retry(cap)
    cap.release()
    if frame is None:
        return 3

    h, w = frame.shape[:2]
    cv2.imwrite(str(snapshot_path), frame)
    print(f"[OK] 저장 완료: {snapshot_path} ({w}x{h})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

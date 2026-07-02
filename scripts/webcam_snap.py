"""C922 라이브 프리뷰 + 키보드 셔터 스냅샷 캡처 도구.

gecko-vision-gate 테스트용 사진을 "보면서 골라 찍기" 위한 단발 도구.

사용법:
    uv run python scripts/webcam_snap.py                       # C922 자동 탐색
    uv run python scripts/webcam_snap.py --index 1             # 인덱스 수동 지정
    uv run python scripts/webcam_snap.py --camera "USB2.0 PC CAMERA"  # 다른 카메라

조작:
    SPACE   현재 프레임 저장
    Q / ESC 종료

저장: storage/webcam-test/snaps/snap_<세션시각>_<NNNN>.jpg

⚠️ macOS GUI 창은 '직접 터미널에서' 실행해야 화면에 뜬다.
   (백그라운드/원격 spawn 으로는 GUI 세션에 안 붙어 창이 안 보일 수 있음)
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import cv2

# 경로는 항상 레포 루트 기준 절대경로로 (실행 위치에 안 흔들리게)
REPO_ROOT = Path(__file__).resolve().parent.parent
SNAP_DIR = REPO_ROOT / "storage" / "webcam-test" / "snaps"

DEFAULT_CAMERA = "C922 Pro Stream Webcam"


def find_camera_index(name: str) -> int | None:
    """ffmpeg avfoundation 디바이스 목록에서 카메라 이름 → 인덱스 매핑.

    왜 이렇게 하나:
    macOS OpenCV(CAP_AVFOUNDATION)는 카메라를 '인덱스'로만 열 수 있는데,
    AVFoundation 인덱스는 디바이스 연결 상태에 따라 호출할 때마다 재정렬된다.
    그래서 인덱스를 코드에 박아두면 엉뚱한 카메라를 연다(실측 사고: [0]C922가
    다음 호출엔 [0]다이소로 바뀜). → '실행 시점에' 이름으로 다시 찾는다.

    JS 비유: 배열 인덱스로 DOM 노드 잡지 말고 querySelector(이름)로 잡는 것과 같은 결.
    """
    # ffmpeg 는 디바이스 목록을 stderr 로 출력하고 입력이 없어 exit 1 로 끝난다(정상).
    proc = subprocess.run(
        ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True,
        text=True,
    )
    # 예: "[AVFoundation indev @ 0x...] [1] C922 Pro Stream Webcam"
    pattern = re.compile(r"\[(\d+)\]\s+(.*)$")
    in_video_section = False
    for line in proc.stderr.splitlines():
        if "AVFoundation video devices" in line:
            in_video_section = True
            continue
        if "AVFoundation audio devices" in line:
            in_video_section = False  # 오디오 인덱스와 헷갈리지 않게 비디오 구간만
            continue
        if not in_video_section:
            continue
        m = pattern.search(line)
        if m and name.lower() in m.group(2).lower():
            return int(m.group(1))
    return None


def open_camera(index: int, width: int, height: int) -> cv2.VideoCapture:
    """인덱스로 카메라를 열고 원하는 해상도를 '요청'한다.

    set() 은 요청일 뿐 — 카메라가 지원 안 하면 무시되므로, 호출부에서
    get() 으로 실제 적용된 해상도를 반드시 다시 확인한다(해상도 가정 금지).
    """
    cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    if not cap.isOpened():
        raise RuntimeError(f"카메라 인덱스 {index} 열기 실패 (다른 앱이 점유 중이거나 권한 문제)")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return cap


def main() -> int:
    parser = argparse.ArgumentParser(description="C922 라이브 프리뷰 + 셔터 스냅샷")
    parser.add_argument("--camera", default=DEFAULT_CAMERA, help="카메라 이름(부분일치)")
    parser.add_argument("--index", type=int, default=None, help="인덱스 직접 지정(이름 탐색 건너뜀)")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    args = parser.parse_args()

    # 1) 카메라 인덱스 결정 (이름 탐색 우선, --index 로 오버라이드)
    if args.index is not None:
        index = args.index
        print(f"[i] 인덱스 직접 지정: {index}")
    else:
        index = find_camera_index(args.camera)
        if index is None:
            print(
                f"[!] '{args.camera}' 카메라를 못 찾음. "
                "`ffmpeg -f avfoundation -list_devices true -i ''` 로 목록 확인 후 --index 지정.",
                file=sys.stderr,
            )
            return 1
        print(f"[i] '{args.camera}' → 현재 인덱스 {index}")

    # 2) 카메라 열기 + 실제 해상도 확인
    cap = open_camera(index, args.width, args.height)
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[i] 실제 해상도: {actual_w}x{actual_h}")
    if actual_w < 1280:
        print(
            f"[!] 해상도가 낮음({actual_w}x{actual_h}) — C922가 아닐 수 있음(다이소=640x480). "
            "프리뷰로 확인하고 아니면 Q 후 --index 조정."
        )

    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    window = "C922 snap  -  SPACE=capture  Q=quit"
    count = 0
    session_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    read_fail = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                # USB 캠은 드물지만, 일시 실패를 raise 하지 않고 재시도(영상 I/O 기본기)
                read_fail += 1
                if read_fail <= 5:
                    if cv2.waitKey(30) & 0xFF in (ord("q"), 27):
                        break
                    continue
                print("[!] 프레임 읽기 연속 실패 — 카메라 연결 확인", file=sys.stderr)
                break
            read_fail = 0

            # 오버레이는 '복사본'에만 그린다 — 저장은 깨끗한 원본 frame.
            # (frame.copy() 는 비용이 있지만, 안내 텍스트가 저장 이미지에 박히면 안 되므로 필요)
            view = frame.copy()
            cv2.putText(
                view,
                f"saved: {count}   SPACE=capture  Q=quit",
                (20, 44),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.1,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
            cv2.imshow(window, view)

            key = cv2.waitKey(1) & 0xFF
            if key == ord(" "):  # SPACE → 캡처
                count += 1
                fname = f"snap_{session_stamp}_{count:04d}.jpg"
                cv2.imwrite(str(SNAP_DIR / fname), frame)  # 원본 저장
                print(f"[+] saved {fname}  ({actual_w}x{actual_h})")
            elif key in (ord("q"), 27):  # Q or ESC → 종료
                break
    finally:
        # VideoCapture 는 try/finally 로 반드시 해제 — 누락 시 다음 연결이 막힌다.
        cap.release()
        cv2.destroyAllWindows()

    print(f"\n[✓] 총 {count}장 저장 → {SNAP_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
FFmpeg 경량 인코딩 래퍼.

캡처 워커가 만든 원본 mp4 (OpenCV `cv2.VideoWriter` 출력 — `avc1` 또는 `mp4v`,
가변 비트레이트, audio 없음 가정) 를 R2 에 올리기 전에 다시 인코딩해서 용량을 줄인다.

## 왜 다시 인코딩?
OpenCV 출력은 인코더 옵션 컨트롤이 거의 없음 (preset/CRF 노출 안됨). 1분 segment 가
보통 5~20MB 로 부풀어 R2 비용·다운로드 시간·라벨링 웹 재생 지연을 키움. ffmpeg 한 번
거치면 같은 화질에 1~5MB 로 떨어진다.

## ffmpeg 옵션
```
ffmpeg -y -i <src>
       -c:v libx264 -crf 26 -preset veryfast
       -movflags +faststart
       -an
       <dst>
```

- `-c:v libx264`: 호환성 + 압축률 standard. R2 영상이 브라우저 `<video>` + Flutter 둘 다
  바로 재생되어야 함. H.264 baseline/main 프로필이 사실상 만능.
- `-crf 26`: 결정 — spec §3-2. CRF 23(시각적 거의 무손실) ~ 28(눈에 띄게 흐림) 사이의
  타협점. 라벨링은 도마뱀 행동 식별만 가능하면 OK라 26 으로 시작 (실측은 §4 표).
- `-preset veryfast`: 인코딩 속도 vs 압축률 trade-off. veryfast 대비 medium 은
  용량 ~10% 더 줄지만 시간 3~5배. 백그라운드 worker 가 1분 segment 를 ≤5초에 처리해야
  큐 backpressure 없이 흐름 → veryfast.
- `-movflags +faststart`: moov atom (메타) 을 파일 앞으로. 브라우저가 progressive
  download 로 즉시 재생 시작 (없으면 풀 다운 후 재생). R2 signed URL 재생에 필수.
- `-an`: 오디오 제거. RTSP 캡처가 audio 없거나 noise 라 의미 없음. 용량 절감 + 호환.

## 왜 subprocess 동기 호출?
이 모듈은 단순 wrapper. 호출 측 (`encode_upload_worker.py`) 이 asyncio worker 인데
ffmpeg 자체는 blocking + CPU bound 이라 `asyncio.to_thread` 로 감싸 호출. 모듈 안에서
`asyncio.create_subprocess_exec` 쓰면 worker 와 의존성 깊어져 단위 테스트 어려움.
sync 함수 + 호출 측 to_thread = donts/python.md 룰 4 ("블로킹 I/O 는 to_thread")와 일관.

## 실패 정책
spec §4 결정 2 — 단일 정책. 실패 시:
- `False` 반환 + warning 로그
- 호출 측 (worker) 이 `r2_key=NULL` 로 record 진행 (로컬 mp4 만 유지, 자동 재시도 없음)
- 부분 출력 (dst 반쯤 쓰여진 파일) 삭제
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# 결정 — spec §3-2. CRF 23/26/28 비교 후 26 채택. 변경은 spec 수정 + worker 재배포.
DEFAULT_CRF = 26
DEFAULT_PRESET = "veryfast"

# subprocess 타임아웃 (초). 1분 segment 가 veryfast 면 보통 ≤5초.
# 30초는 안전 마진 (CPU 경쟁 / 큰 파일 대비). 초과 시 강제 kill + False.
ENCODE_TIMEOUT_SEC = 30


class FFmpegNotFound(RuntimeError):
    """ffmpeg 바이너리 PATH 에 없음. brew install ffmpeg 필요."""


def _ensure_ffmpeg() -> str:
    """ffmpeg 절대 경로 반환. 없으면 raise.
    `shutil.which` 는 PATH lookup — 매 호출 비용 미미 (캐시 안함, 환경변수 변할 수 있음).
    """
    path = shutil.which("ffmpeg")
    if not path:
        raise FFmpegNotFound(
            "ffmpeg 바이너리를 PATH 에서 못 찾음. macOS: `brew install ffmpeg`"
        )
    return path


def encode_lightweight(
    src: Path,
    dst: Path,
    crf: int = DEFAULT_CRF,
    preset: str = DEFAULT_PRESET,
) -> bool:
    """
    원본 mp4 를 H.264 CRF 인코딩 + faststart + audio 제거.

    Args:
        src: 원본 mp4 절대 경로. 존재해야 함.
        dst: 출력 mp4 절대 경로. 부모 디렉토리 존재해야 함. 같은 경로면 raise.
        crf: 0(무손실) ~ 51(최저). 18~28 권장. 기본 26.
        preset: ultrafast / superfast / veryfast / faster / fast / medium / ...
            기본 veryfast.

    Returns:
        True — 성공 (dst 존재 + size > 0).
        False — ffmpeg returncode != 0 또는 timeout. dst 부분 출력은 삭제됨.

    Raises:
        FileNotFoundError: src 없거나 디렉토리.
        ValueError: src == dst (인코딩 결과로 원본 덮어쓰기 방지).
        FFmpegNotFound: ffmpeg 바이너리 미설치.
    """
    if not src.is_file():
        raise FileNotFoundError(f"encode source missing: {src}")
    if src.resolve() == dst.resolve():
        raise ValueError(f"src == dst not allowed: {src}")

    ffmpeg = _ensure_ffmpeg()

    # `-y` 자동 overwrite. dst 가 이전 실패의 부분 파일이어도 덮어씀.
    # 옵션 순서 주의: `-i` 다음에 입력, 그 뒤에 출력 옵션. ffmpeg 는 위치 의존적.
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel", "warning",  # 기본 info 는 너무 시끄러움. warning+ 만 로그.
        "-i", str(src),
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-movflags", "+faststart",
        "-an",
        str(dst),
    ]

    try:
        result = subprocess.run(  # noqa: S603 (cmd 는 우리가 조립, shell=False)
            cmd,
            capture_output=True,
            text=True,
            timeout=ENCODE_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "ffmpeg timeout (>%ds): src=%s dst=%s", ENCODE_TIMEOUT_SEC, src, dst
        )
        _cleanup_partial(dst)
        return False

    if result.returncode != 0:
        # stderr 첫 500자만 — 너무 길면 로그 쓰레기.
        logger.warning(
            "ffmpeg fail rc=%d src=%s dst=%s stderr=%s",
            result.returncode,
            src,
            dst,
            (result.stderr or "")[:500],
        )
        _cleanup_partial(dst)
        return False

    # 성공해도 출력 0바이트면 실패 취급 (ffmpeg 가 -y 로 빈 파일 만들어두는 케이스).
    if not dst.is_file() or dst.stat().st_size == 0:
        logger.warning("ffmpeg returncode=0 but dst missing/empty: %s", dst)
        _cleanup_partial(dst)
        return False

    return True


def _cleanup_partial(dst: Path) -> None:
    """실패 시 dst 부분 출력 삭제. 이미 없으면 무시."""
    try:
        dst.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("cleanup failed for %s: %s", dst, e)


__all__ = [
    "DEFAULT_CRF",
    "DEFAULT_PRESET",
    "ENCODE_TIMEOUT_SEC",
    "FFmpegNotFound",
    "encode_lightweight",
]

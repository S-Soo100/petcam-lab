"""
Cloudflare R2 (S3-compatible) 업로더.

## 왜 boto3?
R2 는 AWS S3 API 호환. boto3 가 사실상 표준 SDK + moto 로 mocking 쉬움.
대안 검토:
- `aiobotocore` (native async): 의존성 무거움, 자료 덜함. MVP 단계엔 과함.
- `httpx` + 수동 SigV4 서명: 학습 가치 있지만 보안 코드 직접 짜는 리스크.
- 결론: boto3 동기 API + 호출 측에서 `asyncio.to_thread` 로 비동기화.
  (donts/python.md 룰 4: 블로킹 I/O 는 to_thread 또는 동기 핸들러로.)

## 왜 lru_cache 싱글톤?
`boto3.client(...)` 는 HTTP 세션 + auth 객체 생성. 매 호출마다 만들면 커넥션 풀 낭비.
`supabase_client.py` 와 동일 패턴 — 프로세스 스코프 싱글톤 + 테스트 reset 헬퍼.

## R2 endpoint URL
대시보드에서 "Account ID" 를 확인 → `https://<account_id>.r2.cloudflarestorage.com`.
사용자가 직접 .env 의 `R2_ENDPOINT` 에 박아둠. region 은 R2 표준값 `auto`.

## Signed URL TTL
기본 1시간. 라벨러가 영상 재생 도중 만료될 가능성 낮음 + 재생 끝나면 페이지 이동 시
새로 발급. 너무 길면 URL 유출 시 위험.

NestJS 비유: `@Injectable()` provider + S3 SDK wrapper.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

# .env.example 에서 쓰는 더미 값. supabase_client.py 와 동일 컨벤션.
_PLACEHOLDER_PATTERNS = ("your-r2-", "PASTE_", "your-account-id")

# 기본 signed URL 만료 (초). 1시간.
DEFAULT_SIGNED_URL_TTL = 3600


class R2NotConfigured(RuntimeError):
    """R2 환경변수가 비어있거나 placeholder 일 때."""


@lru_cache(maxsize=1)
def get_r2_client() -> "S3Client":
    """
    싱글톤 boto3 S3 client (R2 endpoint 로 설정).

    필요 환경변수 (`.env`):
    - `R2_ENDPOINT` — 예: `https://<account_id>.r2.cloudflarestorage.com`
    - `R2_ACCESS_KEY_ID`
    - `R2_SECRET_ACCESS_KEY`

    `R2_BUCKET` 은 client 가 아니라 호출 측에서 사용 (`get_r2_bucket()`).
    `R2_ACCOUNT_ID` 는 endpoint 에 이미 들어있어서 client 자체는 안 씀.

    Raises:
        R2NotConfigured: 환경변수 누락 또는 placeholder 상태
    """
    load_dotenv(REPO_ROOT / ".env")

    endpoint = os.getenv("R2_ENDPOINT")
    access_key = os.getenv("R2_ACCESS_KEY_ID")
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY")

    missing = [
        name
        for name, val in (
            ("R2_ENDPOINT", endpoint),
            ("R2_ACCESS_KEY_ID", access_key),
            ("R2_SECRET_ACCESS_KEY", secret_key),
        )
        if not val
    ]
    if missing:
        raise R2NotConfigured(
            f"R2 환경변수 누락: {', '.join(missing)}. .env 확인."
        )

    for name, val in (
        ("R2_ENDPOINT", endpoint),
        ("R2_ACCESS_KEY_ID", access_key),
        ("R2_SECRET_ACCESS_KEY", secret_key),
    ):
        if any(p in val for p in _PLACEHOLDER_PATTERNS):  # type: ignore[operator]
            raise R2NotConfigured(
                f"{name} 가 placeholder 상태. Cloudflare R2 대시보드 > "
                f"Manage R2 API Tokens 에서 실제 키 발급 후 .env 기입."
            )

    # signature_version=s3v4 — R2 는 SigV4 만 지원.
    # region_name="auto" — R2 표준값. AWS 와 달리 single-region 추상화.
    # addressing_style="path" — R2 의 wildcard cert (*.r2.cloudflarestorage.com)
    #   는 한 단계만 매치. 기본 virtual-hosted style 은 bucket 을 서브도메인으로
    #   붙여 (`<bucket>.<acc>.r2.cloudflarestorage.com`) cert 매치 실패 → SSL
    #   handshake alert. path-style 강제로 endpoint 호스트명 그대로 사용.
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    )


def get_r2_bucket() -> str:
    """`R2_BUCKET` 환경변수 반환. 누락 시 raise."""
    load_dotenv(REPO_ROOT / ".env")
    bucket = os.getenv("R2_BUCKET")
    if not bucket or any(p in bucket for p in _PLACEHOLDER_PATTERNS):
        raise R2NotConfigured("R2_BUCKET 환경변수 누락 또는 placeholder.")
    return bucket


def upload_clip(
    local_path: Path,
    r2_key: str,
    content_type: str = "video/mp4",
) -> int:
    """
    로컬 파일을 R2 버킷에 업로드.

    Args:
        local_path: 업로드할 파일 절대 경로
        r2_key: R2 object key (예: `clips/{cam_id}/{date}/{name}.mp4`)
        content_type: MIME 타입 (브라우저 재생 시 정확해야 함)

    Returns:
        업로드된 바이트 수 (record 의 `encoded_file_size` 용)

    Raises:
        FileNotFoundError: local_path 가 없거나 디렉토리
        R2NotConfigured: env 미설정
        ClientError / BotoCoreError: R2 응답 실패. 호출 측 (worker) 이 try/except
            로 감싸서 `r2_key=NULL` fallback (§4 결정 2 단일 정책).
    """
    if not local_path.is_file():
        raise FileNotFoundError(f"upload source missing: {local_path}")

    client = get_r2_client()
    bucket = get_r2_bucket()
    file_size = local_path.stat().st_size

    # 왜 put_object (low-level) 인가:
    # high-level upload_file 은 ClientError 를 boto3.exceptions.S3UploadFailedError
    # 로 wrap 해버려서 호출 측 except 가 botocore ClientError 를 못 잡음.
    # 우리 파일은 인코딩 후 <20MB → 멀티파트 불필요. put_object 는 ClientError 그대로.
    # (boto3 전송 매니저 기본 multipart threshold = 8MB)
    with local_path.open("rb") as f:
        client.put_object(
            Bucket=bucket,
            Key=r2_key,
            Body=f,
            ContentType=content_type,
        )

    logger.info(
        "r2 upload ok: bucket=%s key=%s size=%d", bucket, r2_key, file_size
    )
    return file_size


def generate_signed_url(
    r2_key: str,
    ttl_sec: int = DEFAULT_SIGNED_URL_TTL,
) -> str:
    """
    R2 object 의 시간 제한 GET URL 생성.

    Args:
        r2_key: 대상 object key
        ttl_sec: 만료 (초). 기본 1시간 (§4 결정 3).

    Returns:
        브라우저/Flutter 가 직접 접근 가능한 URL.

    Raises:
        R2NotConfigured: env 미설정
        ClientError: R2 응답 실패 (드물게 — 사실상 로컬 서명이라 네트워크 무관)
    """
    client = get_r2_client()
    bucket = get_r2_bucket()

    url = client.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": bucket, "Key": r2_key},
        ExpiresIn=ttl_sec,
    )
    return url


def reset_client_cache() -> None:
    """테스트용: 싱글톤 캐시 비움. env 바꾸고 재생성할 때."""
    get_r2_client.cache_clear()


__all__ = [
    "DEFAULT_SIGNED_URL_TTL",
    "R2NotConfigured",
    "generate_signed_url",
    "get_r2_bucket",
    "get_r2_client",
    "reset_client_cache",
    "upload_clip",
    # botocore 예외는 호출 측이 잡을 수 있게 re-export
    "BotoCoreError",
    "ClientError",
]

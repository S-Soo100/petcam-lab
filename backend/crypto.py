"""
Fernet 기반 카메라 자격증명 암호화 래퍼 (Stage D1).

## 왜 Fernet 인가?
카메라 RTSP 비밀번호를 DB(`cameras.rtsp_password_enc`) 에 **양방향** 저장하기 위함.
RTSP 접속 순간에 평문 비번이 필요하므로 bcrypt/argon2 같은 일방향 해시는 쓸 수 없다.
Fernet = AES-128-CBC + HMAC-SHA256 조합의 표준 레시피(= 평문 암호화 + 변조 탐지).

## 왜 lru_cache 싱글톤?
`Fernet(key)` 인스턴스 생성은 저렴하지만 매번 `os.getenv` + 키 검증을 반복하면 낭비.
`supabase_client.py` 와 동일하게 `@lru_cache(maxsize=1)` 로 프로세스 스코프 싱글톤.

## 왜 str 입출력?
Fernet 원래 API 는 bytes 입출력이지만, 이 래퍼는 str 로 일관:
- DB 의 TEXT 컬럼에 그대로 저장·조회 (bytes 컬럼 BYTEA 대신 TEXT 선택)
- FastAPI 요청/응답 JSON 에서 자연스러움
- 호출부가 `.decode()` 를 깜빡하지 않음
Fernet 토큰은 URL-safe base64 라서 str 변환 안전.

## 키 관리
- `.env` 의 `CAMERA_SECRET_KEY` 에만 기입. `.env.example` 은 placeholder.
- 생성: `uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- 최초 1 회 생성 후 **변경 금지** (바꾸면 기존 DB 암호문 전부 복호화 불가).
- 장기적으로 HSM / Cloud KMS 이전 (MVP 엔 .env + 맥북 FileVault 로 만족).

## TS/Node 비유
`crypto.createCipheriv('aes-128-cbc', key, iv)` + HMAC 조합을 한 줄로 묶은 게 Fernet.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

# .env.example 에 쓴 placeholder 기본값을 감지하는 문자열
_PLACEHOLDER_PREFIX = "placeholder"


class CryptoNotConfigured(RuntimeError):
    """CAMERA_SECRET_KEY 가 비어있거나 placeholder 이거나 Fernet 포맷이 아닐 때."""


@lru_cache(maxsize=1)
def get_camera_fernet() -> Fernet:
    """
    싱글톤 Fernet 인스턴스.

    Raises:
        CryptoNotConfigured: 환경변수 누락 / placeholder / 잘못된 키 포맷.
    """
    # supabase_client 와 동일한 이유로 테스트·스크립트 직접 호출 대비 load_dotenv.
    load_dotenv(REPO_ROOT / ".env")

    key = os.getenv("CAMERA_SECRET_KEY", "").strip()

    if not key:
        raise CryptoNotConfigured(
            "CAMERA_SECRET_KEY 환경변수가 비어있음. .env 에 Fernet 키를 생성해 기입.\n"
            '생성 명령: uv run python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    if key.startswith(_PLACEHOLDER_PREFIX):
        raise CryptoNotConfigured(
            "CAMERA_SECRET_KEY 가 placeholder 상태. .env 에 실제 Fernet 키 기입 필요."
        )

    try:
        # Fernet 생성자가 키 길이·base64 포맷을 자체 검증. 실패 시 ValueError.
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise CryptoNotConfigured(
            f"CAMERA_SECRET_KEY 가 유효한 Fernet 키가 아님 "
            f"(32 바이트 url-safe base64 여야 함): {exc}"
        ) from exc


def encrypt_password(plaintext: str) -> str:
    """
    평문 비번 → Fernet 토큰 str. DB 에 그대로 저장 가능.

    반환 예시: 'gAAAAABk7x...==' (URL-safe base64)
    """
    if not plaintext:
        raise ValueError("plaintext must be non-empty")
    fernet = get_camera_fernet()
    token = fernet.encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_password(ciphertext: str) -> str:
    """
    Fernet 토큰 str → 평문. 변조·만료·키 불일치 시 `InvalidToken` 전파.

    `InvalidToken` 은 호출부에서 catch 해서 "카메라 비번이 복호화 불가" 상태를
    UX 에 드러내야 함 (예: 키 회전 후 재입력 요구).
    """
    if not ciphertext:
        raise ValueError("ciphertext must be non-empty")
    fernet = get_camera_fernet()
    plaintext = fernet.decrypt(ciphertext.encode("utf-8"))
    return plaintext.decode("utf-8")


def reset_crypto_cache() -> None:
    """테스트용: 싱글톤 캐시 비움. 환경변수 바꾸고 재생성할 때."""
    get_camera_fernet.cache_clear()

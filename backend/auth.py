"""
Supabase JWT 검증 + FastAPI Depends 체인 (Stage D1).

## Dev / Prod 모드
- `AUTH_MODE=dev` (기본) — Authorization 헤더 무시, `DEV_USER_ID` 반환.
  로컬 개발·pytest 에서 기존 Stage C 동작 그대로 유지.
- `AUTH_MODE=prod` — `Authorization: Bearer <JWT>` 필수. 서명 검증 후 `sub` claim 반환.

## JWT 검증 흐름
Supabase Auth 의 비대칭 서명. 공개키는 JWKS 엔드포인트에 노출:
`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`

알고리즘은 JWK 의 `alg` 필드에서 런타임 결정 (현재 Supabase 는 ES256/P-256;
과거 프로젝트는 RS256). `jwt.PyJWK` 가 `kty` 보고 알아서 RSA/EC 공개키 객체 생성.

검증 순서:
1. Authorization 헤더에서 Bearer 토큰 추출
2. 토큰 header 의 `kid` 로 JWKS 에서 매칭 공개키 찾기
3. 공개키로 `alg` 대로 서명 + `exp` + `iss` 검증
4. payload 반환 → `sub` 이 auth.users.id (UUID)

## 왜 커스텀 TTL 캐시?
Supabase 호출을 매 요청마다 하면 지연·비용. `@lru_cache` 는 TTL 이 없어서
키 로테이션 시 영구 캐시 위험. 모듈 전역 dict + `time.monotonic()` 으로 10분 TTL.
(supabase_client 의 `@lru_cache(maxsize=1)` 와는 의도적으로 다른 패턴 — 만료가 있어야 함)

## 왜 PyJWKClient 안 씀?
`jwt.PyJWKClient` 가 있긴 하지만 내부 캐시 정책이 불투명. 학습 목적으로 직접 관리.

## TS/Node 비유
- `Depends(get_current_user_id)` = NestJS `@UserId()` 커스텀 데코레이터
- JWKS TTL 캐시 = `jwks-rsa` 라이브러리의 `cache: true, cacheMaxAge: 600000`
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

import jwt
from dotenv import load_dotenv
from fastapi import Header, HTTPException, status

REPO_ROOT = Path(__file__).resolve().parent.parent

_JWKS_TTL_SEC = 600  # 10 분. Supabase 키 로테이션 빈도 고려.

# 모듈 전역 캐시. reset_jwks_cache() 로 초기화 가능 (테스트용).
_jwks_cache: dict[str, Any] = {"keys": None, "expires_at": 0.0}


class AuthError(HTTPException):
    """401 을 반환하는 인증 실패 예외. FastAPI 가 자동으로 401 응답 생성."""

    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _auth_mode() -> str:
    """현재 인증 모드 반환. 소문자로 정규화."""
    load_dotenv(REPO_ROOT / ".env")
    return os.getenv("AUTH_MODE", "dev").strip().lower()


def _dev_user_id() -> str:
    """Dev 모드용 하드코딩 user_id."""
    load_dotenv(REPO_ROOT / ".env")
    value = os.getenv("DEV_USER_ID", "").strip()
    if not value:
        raise AuthError("AUTH_MODE=dev 인데 DEV_USER_ID 가 비어있음. .env 확인.")
    return value


def get_jwks() -> list[dict[str, Any]]:
    """
    Supabase JWKS 공개키 셋 반환. 10분 TTL 캐시.

    Returns:
        `keys` 배열. 각 항목은 `{"kid", "kty", "n", "e", ...}` JWK.

    Raises:
        AuthError: JWKS URL 누락 / 네트워크 실패 / 응답 포맷 이상.
    """
    now = time.monotonic()
    cached_keys = _jwks_cache["keys"]
    if cached_keys is not None and now < _jwks_cache["expires_at"]:
        return cached_keys

    load_dotenv(REPO_ROOT / ".env")
    jwks_url = os.getenv("SUPABASE_JWKS_URL", "").strip()
    if not jwks_url:
        raise AuthError("SUPABASE_JWKS_URL 이 비어있음 (AUTH_MODE=prod 에서 필수).")

    try:
        with urllib.request.urlopen(jwks_url, timeout=5) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # urllib 의 다양한 에러 통합
        raise AuthError(f"JWKS 조회 실패: {exc}") from exc

    keys = data.get("keys")
    if not isinstance(keys, list) or not keys:
        raise AuthError("JWKS 응답에 keys 배열이 없음.")

    _jwks_cache["keys"] = keys
    _jwks_cache["expires_at"] = now + _JWKS_TTL_SEC
    return keys


def reset_jwks_cache() -> None:
    """테스트용: JWKS 캐시 초기화."""
    _jwks_cache["keys"] = None
    _jwks_cache["expires_at"] = 0.0


def verify_jwt(token: str) -> dict[str, Any]:
    """
    Supabase JWT 검증 → payload dict 반환.

    검증 항목:
    - 서명 (JWK 의 `alg` 필드 기반 — 현재 Supabase 는 ES256, 과거 RS256)
    - `exp` (pyjwt 자동)
    - `iss` (SUPABASE_JWT_ISSUER 와 일치)

    `aud` 는 Supabase 가 기본 "authenticated" 고정이라 지금은 검증 스킵.
    Stage D+ 에서 role 분기 필요하면 `verify_aud=True` 로 전환.

    Raises:
        AuthError: 어떤 검증이든 실패 시.
    """
    load_dotenv(REPO_ROOT / ".env")
    issuer = os.getenv("SUPABASE_JWT_ISSUER", "").strip()

    try:
        headers = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthError(f"JWT 헤더 파싱 실패: {exc}") from exc

    kid = headers.get("kid")
    if not kid:
        raise AuthError("JWT 헤더에 kid 가 없음.")

    # kid 매칭 실패 시 캐시가 오래됐을 가능성 → 1 회 재시도.
    keys = get_jwks()
    matching_key = next((k for k in keys if k.get("kid") == kid), None)
    if matching_key is None:
        reset_jwks_cache()
        keys = get_jwks()
        matching_key = next((k for k in keys if k.get("kid") == kid), None)
    if matching_key is None:
        raise AuthError(f"JWKS 에서 kid={kid} 매칭되는 공개키를 못 찾음.")

    # PyJWK 가 kty 보고 RSA/EC 공개키 알아서 생성. alg 는 JWK 에서 추출해 허용 목록 구성.
    try:
        pyjwk = jwt.PyJWK(matching_key)
    except Exception as exc:
        raise AuthError(f"JWK → 공개키 변환 실패: {exc}") from exc

    algorithm = matching_key.get("alg") or pyjwk.algorithm_name
    if not algorithm:
        raise AuthError("JWK 에 alg 가 없고 algorithm_name 도 추론 불가.")

    try:
        payload = jwt.decode(
            token,
            key=pyjwk.key,
            algorithms=[algorithm],
            issuer=issuer if issuer else None,
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("JWT 만료됨.") from exc
    except jwt.InvalidIssuerError as exc:
        raise AuthError("JWT issuer 불일치.") from exc
    except jwt.InvalidSignatureError as exc:
        raise AuthError("JWT 서명 불일치.") from exc
    except jwt.PyJWTError as exc:
        raise AuthError(f"JWT 검증 실패: {exc}") from exc

    return payload


def get_jwt_payload(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """
    FastAPI Depends: Authorization 헤더 → JWT 검증 → payload.

    **Prod 모드 전용.** Dev 모드에서는 `get_current_user_id` 가 이 함수를 건너뛴다.
    """
    if not authorization:
        raise AuthError("Authorization 헤더가 없음.")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError("Authorization 헤더 포맷은 'Bearer <token>' 이어야 함.")

    token = parts[1].strip()
    if not token:
        raise AuthError("Authorization 헤더에 토큰이 비어있음.")

    return verify_jwt(token)


def get_current_user_id(
    authorization: str | None = Header(default=None),
) -> str:
    """
    FastAPI Depends: 현재 요청의 user_id (UUID str).

    - `AUTH_MODE=dev` → `DEV_USER_ID` 반환 (JWT 검증 스킵, Authorization 헤더 무시)
    - `AUTH_MODE=prod` → JWT 검증 → `payload["sub"]` 반환

    Stage C 의 `get_dev_user_id` 를 이 함수로 교체하면 Dev 모드에서는 동작 동일,
    Prod 모드에서는 JWT 필수가 된다.

    Raises:
        AuthError: Prod 에서 JWT 누락/무효. Dev 에서 DEV_USER_ID 누락.
    """
    mode = _auth_mode()
    if mode == "dev":
        return _dev_user_id()
    if mode == "prod":
        payload = get_jwt_payload(authorization=authorization)
        sub = payload.get("sub")
        if not sub or not isinstance(sub, str):
            raise AuthError("JWT payload 에 sub claim (user_id) 이 없음.")
        return sub
    raise AuthError(f"AUTH_MODE 값이 이상함: '{mode}'. 'dev' 또는 'prod' 만 허용.")

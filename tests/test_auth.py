"""
backend.auth 단위 테스트 — JWT 검증 + Dev/Prod 분기 + JWKS 캐시.

## 테스트용 RSA 키쌍
실 Supabase JWKS 를 안 부르려고 세션 fixture 로 로컬 RSA 2048 키쌍 생성.
public 을 JWK 포맷으로 만들어 `get_jwks` 를 monkeypatch → `verify_jwt` 가
이 공개키로 서명 검증. 실제 Supabase 와 정확히 같은 RS256 경로.

## 왜 HTTPException 을 catch 하나?
`AuthError(HTTPException)` 상속이라 `pytest.raises(HTTPException)` 으로 다 잡힘.
status_code == 401 확인까지 하면 AuthError 한정 (다른 HTTPException 섞이지 않음).
"""

from __future__ import annotations

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from backend.auth import (
    get_current_user_id,
    get_jwks,
    reset_jwks_cache,
)

# ─────────────────────────────────────────────────────────────────────────
# 공용 fixture — RSA 키쌍 + JWK 공개키 (세션 스코프로 재사용)
# ─────────────────────────────────────────────────────────────────────────

_TEST_KID = "test-kid-1"
_TEST_ISSUER = "https://test.supabase.co/auth/v1"
_TEST_JWKS_URL = "https://test.supabase.co/auth/v1/.well-known/jwks.json"


@pytest.fixture(scope="session")
def rsa_keypair():
    """테스트 세션 동안 유지되는 RSA 2048 키쌍. 생성 비용 1회로 제한."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture(scope="session")
def jwk_public(rsa_keypair) -> dict:
    """RSA public key → JWK dict (kid 포함)."""
    _, public = rsa_keypair
    jwk_str = jwt.algorithms.RSAAlgorithm.to_jwk(public)
    jwk_dict = json.loads(jwk_str)
    jwk_dict["kid"] = _TEST_KID
    return jwk_dict


@pytest.fixture(autouse=True)
def _reset_jwks_each_test():
    """각 테스트 전/후 JWKS 캐시 초기화."""
    reset_jwks_cache()
    yield
    reset_jwks_cache()


@pytest.fixture
def patch_jwks(monkeypatch: pytest.MonkeyPatch, jwk_public: dict):
    """`get_jwks` 를 로컬 JWK 하나만 반환하도록 모킹 (HTTP 호출 차단)."""
    monkeypatch.setattr("backend.auth.get_jwks", lambda: [jwk_public])
    yield


@pytest.fixture
def prod_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_MODE", "prod")
    monkeypatch.setenv("SUPABASE_JWT_ISSUER", _TEST_ISSUER)
    monkeypatch.setenv("SUPABASE_JWKS_URL", _TEST_JWKS_URL)
    yield


@pytest.fixture
def dev_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("DEV_USER_ID", "dev-user-abc")
    yield


def _make_token(
    private_key,
    sub: str = "real-user-xyz",
    issuer: str = _TEST_ISSUER,
    exp_offset_sec: int = 300,
    kid: str = _TEST_KID,
    algorithm: str = "RS256",
) -> str:
    """기본값이 정상 유효한 토큰. 파라미터 뒤집으면 실패 케이스 생성."""
    payload = {
        "sub": sub,
        "iss": issuer,
        "exp": int(time.time()) + exp_offset_sec,
    }
    return jwt.encode(payload, private_key, algorithm=algorithm, headers={"kid": kid})


# ─────────────────────────────────────────────────────────────────────────
# Dev 모드
# ─────────────────────────────────────────────────────────────────────────


def test_dev_mode_returns_dev_user_id(dev_env) -> None:
    assert get_current_user_id(authorization=None) == "dev-user-abc"


def test_dev_mode_ignores_authorization_header(dev_env) -> None:
    """Dev 모드는 Bearer 토큰을 줘도 무시하고 DEV_USER_ID 반환."""
    assert (
        get_current_user_id(authorization="Bearer whatever-token")
        == "dev-user-abc"
    )


def test_dev_mode_missing_dev_user_id_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "dev")
    # delenv 하면 `_dev_user_id` 내부 load_dotenv 가 실제 .env 에서 다시 로드해버림.
    # 빈 문자열로 두면 override=False 덕에 그 값이 유지 → 정확한 "미설정" 시나리오.
    monkeypatch.setenv("DEV_USER_ID", "")
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(authorization=None)
    assert exc.value.status_code == 401


# ─────────────────────────────────────────────────────────────────────────
# Prod 모드 — 헤더 파싱
# ─────────────────────────────────────────────────────────────────────────


def test_prod_mode_missing_authorization_raises(prod_env) -> None:
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(authorization=None)
    assert exc.value.status_code == 401


def test_prod_mode_non_bearer_scheme_raises(prod_env) -> None:
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(authorization="Basic abc123")
    assert exc.value.status_code == 401


def test_prod_mode_empty_token_raises(prod_env) -> None:
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(authorization="Bearer ")
    assert exc.value.status_code == 401


# ─────────────────────────────────────────────────────────────────────────
# Prod 모드 — JWT 검증
# ─────────────────────────────────────────────────────────────────────────


def test_prod_mode_valid_jwt_returns_sub(prod_env, patch_jwks, rsa_keypair) -> None:
    private, _ = rsa_keypair
    token = _make_token(private, sub="real-user-xyz")
    assert get_current_user_id(authorization=f"Bearer {token}") == "real-user-xyz"


def test_prod_mode_expired_jwt_raises(prod_env, patch_jwks, rsa_keypair) -> None:
    private, _ = rsa_keypair
    token = _make_token(private, exp_offset_sec=-60)  # 1분 전 만료
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(authorization=f"Bearer {token}")
    assert exc.value.status_code == 401
    assert "만료" in exc.value.detail


def test_prod_mode_tampered_signature_raises(prod_env, patch_jwks, rsa_keypair) -> None:
    private, _ = rsa_keypair
    token = _make_token(private)
    # 서명 세그먼트(마지막) 변조
    parts = token.split(".")
    tampered = ".".join([parts[0], parts[1], parts[2][:-4] + "XXXX"])
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(authorization=f"Bearer {tampered}")
    assert exc.value.status_code == 401


def test_prod_mode_wrong_kid_raises(prod_env, patch_jwks, rsa_keypair) -> None:
    """JWKS 에 없는 kid 로 서명 → kid 매칭 실패."""
    private, _ = rsa_keypair
    token = _make_token(private, kid="unknown-kid")
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(authorization=f"Bearer {token}")
    assert exc.value.status_code == 401
    assert "kid" in exc.value.detail


def test_prod_mode_wrong_issuer_raises(prod_env, patch_jwks, rsa_keypair) -> None:
    private, _ = rsa_keypair
    token = _make_token(private, issuer="https://evil.example.com")
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(authorization=f"Bearer {token}")
    assert exc.value.status_code == 401


def test_prod_mode_missing_sub_raises(prod_env, patch_jwks, rsa_keypair) -> None:
    """sub claim 누락된 JWT → 401."""
    private, _ = rsa_keypair
    payload = {
        "iss": _TEST_ISSUER,
        "exp": int(time.time()) + 300,
        # sub 생략
    }
    token = jwt.encode(payload, private, algorithm="RS256", headers={"kid": _TEST_KID})
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(authorization=f"Bearer {token}")
    assert exc.value.status_code == 401


# ─────────────────────────────────────────────────────────────────────────
# JWKS 캐시 동작
# ─────────────────────────────────────────────────────────────────────────


class _FakeUrlopenResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self) -> bytes:
        return self._body


def test_jwks_cache_hit_avoids_second_fetch(
    monkeypatch: pytest.MonkeyPatch, prod_env
) -> None:
    """TTL 안에 두 번 호출하면 urllib 은 한 번만 실행."""
    call_count = {"n": 0}
    body = json.dumps({"keys": [{"kid": "k1", "kty": "RSA", "n": "x", "e": "AQAB"}]}).encode()

    def fake_urlopen(*args, **kwargs):
        call_count["n"] += 1
        return _FakeUrlopenResponse(body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    first = get_jwks()
    second = get_jwks()
    assert first == second
    assert call_count["n"] == 1, "두 번째 호출은 캐시에서 가져와야 함"


def test_jwks_cache_expires_triggers_refetch(
    monkeypatch: pytest.MonkeyPatch, prod_env
) -> None:
    """만료 시각 초과 시 재fetch."""
    call_count = {"n": 0}
    body = json.dumps({"keys": [{"kid": "k1", "kty": "RSA", "n": "x", "e": "AQAB"}]}).encode()

    def fake_urlopen(*args, **kwargs):
        call_count["n"] += 1
        return _FakeUrlopenResponse(body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    get_jwks()
    # 만료 시각을 0 으로 강제 → 다음 호출은 TTL 판정상 만료
    import backend.auth as auth_mod

    auth_mod._jwks_cache["expires_at"] = 0.0
    get_jwks()
    assert call_count["n"] == 2


# ─────────────────────────────────────────────────────────────────────────
# AUTH_MODE 이상값
# ─────────────────────────────────────────────────────────────────────────


def test_unknown_auth_mode_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "weird-mode")
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(authorization=None)
    assert exc.value.status_code == 401
    assert "AUTH_MODE" in exc.value.detail

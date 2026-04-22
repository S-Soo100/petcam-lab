"""
backend.crypto 단위 테스트 — Fernet 라운드트립 + placeholder 가드 + 싱글톤.

## 실 키 생성 vs 고정 키
각 테스트에서 `Fernet.generate_key()` 로 새 키 생성 (monkeypatch 로 env 주입).
고정 키 하드코딩하면 "이 키가 .env 에도 쓰이나?" 오해 여지. 매번 생성이 안전.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from backend.crypto import (
    CryptoNotConfigured,
    decrypt_password,
    encrypt_password,
    get_camera_fernet,
    reset_crypto_cache,
)


@pytest.fixture(autouse=True)
def _reset_cache_before_and_after():
    """각 테스트 전/후 싱글톤 캐시 초기화 — env 변경 반영되도록."""
    reset_crypto_cache()
    yield
    reset_crypto_cache()


def _inject_real_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """monkeypatch 로 .env 대신 새 Fernet 키를 주입. 키 문자열 반환."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("CAMERA_SECRET_KEY", key)
    return key


# ─────────────────────────────────────────────────────────────────────────
# 싱글톤 동작
# ─────────────────────────────────────────────────────────────────────────


def test_singleton_returns_same_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    _inject_real_key(monkeypatch)
    a = get_camera_fernet()
    b = get_camera_fernet()
    assert a is b, "lru_cache 로 같은 Fernet 인스턴스 반환해야 함"


def test_reset_cache_allows_new_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _inject_real_key(monkeypatch)
    first = get_camera_fernet()
    reset_crypto_cache()
    _inject_real_key(monkeypatch)  # 새 키
    second = get_camera_fernet()
    assert first is not second


# ─────────────────────────────────────────────────────────────────────────
# placeholder 가드
# ─────────────────────────────────────────────────────────────────────────


def test_placeholder_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMERA_SECRET_KEY", "placeholder-replace-with-generated-fernet-key")
    with pytest.raises(CryptoNotConfigured, match="placeholder"):
        get_camera_fernet()


def test_empty_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMERA_SECRET_KEY", "")
    with pytest.raises(CryptoNotConfigured, match="비어있음"):
        get_camera_fernet()


def test_whitespace_key_treated_as_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMERA_SECRET_KEY", "   ")
    with pytest.raises(CryptoNotConfigured, match="비어있음"):
        get_camera_fernet()


def test_invalid_format_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """32바이트 url-safe base64 가 아닌 키 → CryptoNotConfigured."""
    monkeypatch.setenv("CAMERA_SECRET_KEY", "this-is-not-a-valid-fernet-key")
    with pytest.raises(CryptoNotConfigured, match="유효한 Fernet"):
        get_camera_fernet()


# ─────────────────────────────────────────────────────────────────────────
# 라운드트립
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "plaintext",
    ["hello", "p@ssw0rd!", "한글비번테스트", "x" * 128, "!@#$%^&*()"],
)
def test_roundtrip(monkeypatch: pytest.MonkeyPatch, plaintext: str) -> None:
    _inject_real_key(monkeypatch)
    ciphertext = encrypt_password(plaintext)
    assert ciphertext != plaintext, "암호문이 평문과 같으면 안 됨"
    assert decrypt_password(ciphertext) == plaintext


def test_encrypt_returns_str(monkeypatch: pytest.MonkeyPatch) -> None:
    _inject_real_key(monkeypatch)
    ct = encrypt_password("hello")
    assert isinstance(ct, str)
    # Fernet 토큰은 'gAAAAA' 로 시작하는 url-safe base64
    assert ct.startswith("gAAAAA")


def test_same_plaintext_different_ciphertext(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fernet 은 IV/timestamp 때문에 같은 평문·같은 키라도 매번 다른 암호문."""
    _inject_real_key(monkeypatch)
    a = encrypt_password("same-pw")
    b = encrypt_password("same-pw")
    assert a != b
    # 둘 다 복호화 결과는 같아야 함
    assert decrypt_password(a) == decrypt_password(b) == "same-pw"


# ─────────────────────────────────────────────────────────────────────────
# 입력 검증
# ─────────────────────────────────────────────────────────────────────────


def test_encrypt_empty_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _inject_real_key(monkeypatch)
    with pytest.raises(ValueError, match="non-empty"):
        encrypt_password("")


def test_decrypt_empty_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _inject_real_key(monkeypatch)
    with pytest.raises(ValueError, match="non-empty"):
        decrypt_password("")


# ─────────────────────────────────────────────────────────────────────────
# 변조·키 불일치
# ─────────────────────────────────────────────────────────────────────────


def test_tampered_ciphertext_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """암호문 1문자 변조 → HMAC 검증 실패 → InvalidToken."""
    _inject_real_key(monkeypatch)
    ct = encrypt_password("hello")
    tampered = ct[:-1] + ("A" if ct[-1] != "A" else "B")
    with pytest.raises(InvalidToken):
        decrypt_password(tampered)


def test_decrypt_with_different_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """키 A 로 암호화 → 캐시 리셋 → 키 B 로 복호화 시도 → InvalidToken."""
    _inject_real_key(monkeypatch)
    ct = encrypt_password("hello")
    reset_crypto_cache()
    _inject_real_key(monkeypatch)  # 새 키
    with pytest.raises(InvalidToken):
        decrypt_password(ct)

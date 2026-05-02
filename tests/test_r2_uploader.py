"""
backend.r2_uploader 단위 테스트 (moto 로 R2/S3 mock).

## 검증 목표
- env 누락 / placeholder → R2NotConfigured 명확히 raise
- 정상 path: upload → object 존재 + 바이트 일치 + 반환 size 정확
- generate_signed_url: bucket/key 가 URL 에 포함되어야 라벨링 웹이 직접 GET 가능
- 미존재 파일 업로드 → FileNotFoundError (호출 측이 잡고 r2_key=NULL fallback)

## 왜 moto?
실제 R2 호출은 비용 + 네트워크 의존. moto 가 boto3 의 HTTP 레이어를 가로채서
in-memory S3 흉내 → 결정론적 + 빠름. R2 도 S3 호환이라 그대로 통함.

## reset_client_cache
get_r2_client 가 lru_cache 라서 테스트 사이에 env 바뀌면 stale. 매 테스트 fixture
에서 reset.
"""

from __future__ import annotations

from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from backend import r2_uploader
from backend.r2_uploader import (
    R2NotConfigured,
    generate_signed_url,
    get_r2_bucket,
    get_r2_client,
    reset_client_cache,
    upload_clip,
)

# ─── env 헬퍼 ─────────────────────────────────────────────────────────────────


_TEST_ENDPOINT = "https://test-account.r2.cloudflarestorage.com"


def _set_r2_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    """모든 R2 env 를 정상값으로 세팅 (테스트별 일부만 override 가능)."""
    defaults = {
        "R2_ENDPOINT": _TEST_ENDPOINT,
        "R2_ACCESS_KEY_ID": "test-key-id",
        "R2_SECRET_ACCESS_KEY": "test-secret",
        "R2_BUCKET": "petcam-clips-test",
        "R2_ACCOUNT_ID": "test-account",
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        monkeypatch.setenv(k, v)


@pytest.fixture(autouse=True)
def _moto_custom_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    moto 5 가 R2 custom endpoint 를 S3 로 인식하게 화이트리스트.
    이 env 가 없으면 mock_aws() 가 R2 호스트를 가로채지 못해 실제 SSL handshake 시도 → 실패.
    """
    monkeypatch.setenv("MOTO_S3_CUSTOM_ENDPOINTS", _TEST_ENDPOINT)


@pytest.fixture(autouse=True)
def _stub_load_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """`r2_uploader` 가 매 호출마다 `load_dotenv()` 로 실제 .env 를 다시 읽으면
    테스트의 `monkeypatch.delenv` 가 무력화됨 (실제 .env 의 R2_* 값이 다시 들어옴).
    테스트 동안에만 no-op 으로 교체. 운영 코드 자체는 그대로 둠.
    """
    monkeypatch.setattr(r2_uploader, "load_dotenv", lambda *a, **kw: False)


@pytest.fixture(autouse=True)
def _reset_cache_around_test() -> None:
    """매 테스트 전후로 lru_cache 비움."""
    reset_client_cache()
    yield
    reset_client_cache()


def _create_test_bucket(name: str = "petcam-clips-test") -> None:
    """
    moto 컨텍스트 안에서 테스트 버킷 생성.
    region_name="us-east-1" 로 만들어야 LocationConstraint 충돌 없음.
    (프로덕션 R2 client 의 region="auto" 와 분리.)
    """
    s3 = boto3.client(
        "s3",
        endpoint_url=_TEST_ENDPOINT,
        aws_access_key_id="test-key-id",
        aws_secret_access_key="test-secret",
        region_name="us-east-1",
    )
    s3.create_bucket(Bucket=name)


# ─── env 검증 ────────────────────────────────────────────────────────────────


def test_get_r2_client_missing_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "y")
    with pytest.raises(R2NotConfigured, match="R2_ENDPOINT"):
        get_r2_client()


def test_get_r2_client_missing_access_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R2_ENDPOINT", "https://x.r2.cloudflarestorage.com")
    monkeypatch.delenv("R2_ACCESS_KEY_ID", raising=False)
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "y")
    with pytest.raises(R2NotConfigured, match="R2_ACCESS_KEY_ID"):
        get_r2_client()


def test_get_r2_client_placeholder_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """placeholder 패턴이 들어있으면 raise (.env.example 그대로 둔 케이스)."""
    _set_r2_env(monkeypatch, R2_ACCESS_KEY_ID="your-r2-access-key")
    with pytest.raises(R2NotConfigured, match="placeholder"):
        get_r2_client()


def test_get_r2_bucket_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_r2_env(monkeypatch)
    assert get_r2_bucket() == "petcam-clips-test"


def test_get_r2_bucket_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_r2_env(monkeypatch)
    monkeypatch.delenv("R2_BUCKET")
    with pytest.raises(R2NotConfigured, match="R2_BUCKET"):
        get_r2_bucket()


def test_get_r2_bucket_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_r2_env(monkeypatch, R2_BUCKET="your-r2-bucket")
    with pytest.raises(R2NotConfigured, match="placeholder"):
        get_r2_bucket()


# ─── upload_clip ─────────────────────────────────────────────────────────────


def test_upload_clip_writes_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """업로드 성공 시 R2 에 동일 바이트 + 반환 size 일치."""
    _set_r2_env(monkeypatch)
    payload = b"\x00\x01\x02fake_mp4_bytes" * 100  # 1500 bytes
    src = tmp_path / "clip.mp4"
    src.write_bytes(payload)

    with mock_aws():
        _create_test_bucket()

        size = upload_clip(src, "clips/cam1/2026-05-02/test.mp4")
        assert size == len(payload)

        # R2 에 실제로 들어갔는지 — 같은 mock_aws 컨텍스트 안에서 GET (us-east-1 client 로 검증)
        s3 = boto3.client(
            "s3",
            endpoint_url=_TEST_ENDPOINT,
            aws_access_key_id="test-key-id",
            aws_secret_access_key="test-secret",
            region_name="us-east-1",
        )
        obj = s3.get_object(
            Bucket="petcam-clips-test", Key="clips/cam1/2026-05-02/test.mp4"
        )
        assert obj["Body"].read() == payload


def test_upload_clip_sets_content_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ContentType 이 R2 metadata 에 반영되는지."""
    _set_r2_env(monkeypatch)
    src = tmp_path / "thumb.jpg"
    src.write_bytes(b"fake_jpg")

    with mock_aws():
        _create_test_bucket()

        upload_clip(src, "thumbnails/x.jpg", content_type="image/jpeg")

        s3 = boto3.client(
            "s3",
            endpoint_url=_TEST_ENDPOINT,
            aws_access_key_id="test-key-id",
            aws_secret_access_key="test-secret",
            region_name="us-east-1",
        )
        head = s3.head_object(Bucket="petcam-clips-test", Key="thumbnails/x.jpg")
        assert head["ContentType"] == "image/jpeg"


def test_upload_clip_missing_source_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """원본 mp4 가 사라졌을 때 (디스크 정리 race) 명확한 예외."""
    _set_r2_env(monkeypatch)
    with mock_aws():
        with pytest.raises(FileNotFoundError, match="upload source missing"):
            upload_clip(tmp_path / "nonexistent.mp4", "clips/x.mp4")


def test_upload_clip_directory_not_file_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """디렉토리 경로 넘기면 raise (실수 방지)."""
    _set_r2_env(monkeypatch)
    with mock_aws():
        with pytest.raises(FileNotFoundError, match="upload source missing"):
            upload_clip(tmp_path, "clips/x.mp4")


def test_upload_clip_bucket_missing_raises_client_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """버킷 자체가 없으면 boto3 가 NoSuchBucket. 호출 측이 잡고 r2_key=NULL 처리."""
    _set_r2_env(monkeypatch, R2_BUCKET="nonexistent-bucket")
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")

    with mock_aws():
        with pytest.raises(ClientError):
            upload_clip(src, "clips/x.mp4")


# ─── generate_signed_url ─────────────────────────────────────────────────────


def test_generate_signed_url_contains_bucket_and_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_r2_env(monkeypatch)
    with mock_aws():
        _create_test_bucket()

        url = generate_signed_url("clips/cam1/2026-05-02/test.mp4")

        # SigV4 query 파라미터 포함되어야 함
        assert "petcam-clips-test" in url
        assert "clips/cam1/2026-05-02/test.mp4" in url
        assert "X-Amz-Signature=" in url or "X-Amz-Algorithm=" in url
        assert "X-Amz-Expires=3600" in url


def test_generate_signed_url_custom_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_r2_env(monkeypatch)
    with mock_aws():
        _create_test_bucket()

        url = generate_signed_url("any-key", ttl_sec=600)
        assert "X-Amz-Expires=600" in url


# ─── 회귀: lru_cache 캐시 제거 동작 ─────────────────────────────────────────


def test_reset_client_cache_picks_up_new_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env 바꾸고 reset 하면 새 client. 안 하면 옛 client (의도된 캐시 동작)."""
    _set_r2_env(monkeypatch, R2_ENDPOINT="https://first.r2.cloudflarestorage.com")
    c1 = get_r2_client()

    # cache hit — 같은 인스턴스
    assert get_r2_client() is c1

    # env 바꿔도 cache 는 유지
    monkeypatch.setenv("R2_ENDPOINT", "https://second.r2.cloudflarestorage.com")
    assert get_r2_client() is c1

    # reset 하면 새 인스턴스
    reset_client_cache()
    c2 = get_r2_client()
    assert c2 is not c1

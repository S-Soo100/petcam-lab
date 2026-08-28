"""큰 RAP 원본 bundle을 R2에 multipart + manifest-last로 올린다."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError

from backend.rap_c500g_manifest import atomic_write_manifest, read_manifest, sha256_file


MULTIPART_SIZE = 16 * 1024 * 1024
_PLACEHOLDER_PATTERNS = ("your-r2-", "PASTE_", "your-account-id")


@dataclass(frozen=True, slots=True)
class C500GR2Config:
    endpoint: str
    access_key_id: str
    secret_access_key: str
    bucket: str


def load_c500g_r2_config(env: Mapping[str, str]) -> C500GR2Config:
    names = (
        "R2_ENDPOINT",
        "R2_C500G_ACCESS_KEY_ID",
        "R2_C500G_SECRET_ACCESS_KEY",
        "R2_C500G_BUCKET",
    )
    values = {name: env.get(name, "").strip() for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"R2 C500G 환경변수 누락: {', '.join(missing)}")
    placeholders = [
        name
        for name, value in values.items()
        if any(pattern in value for pattern in _PLACEHOLDER_PATTERNS)
    ]
    if placeholders:
        raise ValueError(f"R2 C500G placeholder 환경변수: {', '.join(placeholders)}")
    if values["R2_C500G_BUCKET"] != "c500g":
        raise ValueError("R2_C500G_BUCKET must be c500g")
    return C500GR2Config(
        endpoint=values["R2_ENDPOINT"],
        access_key_id=values["R2_C500G_ACCESS_KEY_ID"],
        secret_access_key=values["R2_C500G_SECRET_ACCESS_KEY"],
        bucket=values["R2_C500G_BUCKET"],
    )


def create_c500g_r2_client(config: C500GR2Config) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=config.endpoint,
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=config.secret_access_key,
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    )


class S3TransferClient(Protocol):
    def upload_file(
        self,
        filename: str,
        bucket: str,
        key: str,
        **kwargs: Any,
    ) -> None: ...

    def head_object(self, **kwargs: Any) -> dict[str, Any]: ...


class IntegrityConflict(RuntimeError):
    """같은 key에 다른 크기 또는 해시의 object가 이미 존재한다."""


@dataclass(frozen=True, slots=True)
class UploadResult:
    uploaded: bool
    artifact_count: int
    skipped_count: int


class R2BundleUploader:
    def __init__(
        self,
        client: S3TransferClient,
        bucket: str,
        *,
        transfer_config: TransferConfig | None = None,
    ) -> None:
        if not bucket:
            raise ValueError("R2 bucket is required")
        self._client = client
        self._bucket = bucket
        self._config = transfer_config or TransferConfig(
            multipart_threshold=MULTIPART_SIZE,
            multipart_chunksize=MULTIPART_SIZE,
            max_concurrency=2,
            use_threads=True,
        )

    def _head(self, key: str) -> dict[str, Any] | None:
        try:
            return self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise

    def _ensure_object(
        self,
        *,
        path: Path,
        key: str,
        content_type: str,
        sha256: str,
        bundle_id: str,
        camera_key: str,
    ) -> bool:
        size = path.stat().st_size
        existing = self._head(key)
        if existing is not None:
            existing_sha = existing.get("Metadata", {}).get("sha256")
            if existing.get("ContentLength") == size and existing_sha == sha256:
                return False
            raise IntegrityConflict(
                f"R2 integrity conflict for {camera_key}: existing object differs"
            )

        self._client.upload_file(
            str(path),
            self._bucket,
            key,
            ExtraArgs={
                "ContentType": content_type,
                "Metadata": {
                    "sha256": sha256,
                    "bundle-id": bundle_id,
                    "camera-key": camera_key,
                },
            },
            Config=self._config,
        )
        uploaded = self._head(key)
        if uploaded is None:
            raise RuntimeError(f"R2 HEAD missing after upload for {camera_key}")
        if (
            uploaded.get("ContentLength") != size
            or uploaded.get("Metadata", {}).get("sha256") != sha256
        ):
            raise IntegrityConflict(
                f"R2 integrity verification failed for {camera_key}"
            )
        return True

    def upload_bundle(
        self,
        bundle_dir: Path,
        manifest: dict[str, Any],
    ) -> UploadResult:
        bundle_id = str(manifest["bundle_id"])
        camera_key = str(manifest["camera_key"])
        uploaded_count = 0
        skipped_count = 0

        for artifact in manifest["artifacts"]:
            name = str(artifact["name"])
            if Path(name).name != name:
                raise ValueError("artifact name must be a basename")
            changed = self._ensure_object(
                path=bundle_dir / name,
                key=str(artifact["r2_key"]),
                content_type=str(artifact["content_type"]),
                sha256=str(artifact["sha256"]),
                bundle_id=bundle_id,
                camera_key=camera_key,
            )
            uploaded_count += int(changed)
            skipped_count += int(not changed)

        manifest_path = bundle_dir / "manifest.json"
        local_manifest = read_manifest(manifest_path) if manifest_path.is_file() else None
        if local_manifest and local_manifest.get("upload_status") == "uploaded":
            completed_manifest = local_manifest
        else:
            completed_manifest = dict(manifest)
            completed_manifest["upload_status"] = "uploaded"
            completed_manifest["r2_verified"] = True
            completed_manifest["uploaded_at"] = datetime.now(UTC).isoformat()
        atomic_write_manifest(manifest_path, completed_manifest)
        manifest_sha = sha256_file(manifest_path)
        manifest_changed = self._ensure_object(
            path=manifest_path,
            key=str(manifest["manifest_r2_key"]),
            content_type="application/json",
            sha256=manifest_sha,
            bundle_id=bundle_id,
            camera_key=camera_key,
        )
        uploaded_count += int(manifest_changed)
        skipped_count += int(not manifest_changed)

        return UploadResult(
            uploaded=uploaded_count > 0,
            artifact_count=4,
            skipped_count=skipped_count,
        )

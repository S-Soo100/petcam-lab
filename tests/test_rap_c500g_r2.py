from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from backend.rap_c500g_manifest import build_local_manifest, sha256_file
from backend.rap_c500g_naming import build_bundle_paths
from backend.rap_c500g_r2 import IntegrityConflict, R2BundleUploader
from backend.rap_c500g_types import SegmentIdentity


KST = ZoneInfo("Asia/Seoul")
BUCKET = "rap-test"


class RecordingClient:
    def __init__(self, client: Any, *, fail_key_suffix: str | None = None) -> None:
        self.client = client
        self.fail_key_suffix = fail_key_suffix
        self.uploaded_keys: list[str] = []

    def upload_file(self, filename: str, bucket: str, key: str, **kwargs: Any) -> None:
        self.uploaded_keys.append(key)
        if self.fail_key_suffix and key.endswith(self.fail_key_suffix):
            raise RuntimeError("synthetic upload failure")
        self.client.upload_file(filename, bucket, key, **kwargs)

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        return self.client.head_object(**kwargs)


def make_bundle(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    identity = SegmentIdentity.test(
        camera_key="cam01",
        scheduled_start_kst=datetime(2026, 8, 26, 13, 42, 27, tzinfo=KST),
        test_run_id="test-20260826T134227-KST-a1b2c3d4",
    )
    paths = build_bundle_paths(tmp_path, identity)
    paths.bundle_dir.mkdir(parents=True)
    paths.video.write_bytes(b"v" * 1024)
    paths.thumbnail.write_bytes(b"jpeg")
    paths.log.write_text("safe\n", encoding="utf-8")
    manifest = build_local_manifest(
        identity,
        paths,
        media={"duration_sec": 60.0, "codec": "hevc", "width": 2880, "height": 1620, "fps": 20.0},
        capture={"ffmpeg_exit_code": 0, "verified": True},
    )
    return paths.bundle_dir, manifest


@mock_aws
def test_upload_bundle_verifies_artifacts_and_uploads_manifest_last(tmp_path: Path) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    recording = RecordingClient(s3)
    bundle_dir, manifest = make_bundle(tmp_path)

    result = R2BundleUploader(recording, BUCKET).upload_bundle(bundle_dir, manifest)

    assert recording.uploaded_keys[-1] == manifest["manifest_r2_key"]
    assert result.uploaded is True
    assert result.artifact_count == 4
    video = manifest["artifacts"][0]
    head = s3.head_object(Bucket=BUCKET, Key=video["r2_key"])
    assert head["ContentLength"] == video["size_bytes"]
    assert head["Metadata"]["sha256"] == video["sha256"]
    uploaded_manifest = json.loads(
        s3.get_object(Bucket=BUCKET, Key=manifest["manifest_r2_key"])["Body"].read()
    )
    assert uploaded_manifest["upload_status"] == "uploaded"
    assert uploaded_manifest["r2_verified"] is True
    assert uploaded_manifest["uploaded_at"].endswith("+00:00")


@mock_aws
def test_upload_bundle_is_idempotent_when_size_and_sha_match(tmp_path: Path) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    recording = RecordingClient(s3)
    bundle_dir, manifest = make_bundle(tmp_path)
    uploader = R2BundleUploader(recording, BUCKET)
    uploader.upload_bundle(bundle_dir, manifest)
    recording.uploaded_keys.clear()

    second = uploader.upload_bundle(bundle_dir, manifest)

    assert second.uploaded is False
    assert second.skipped_count == 4
    assert recording.uploaded_keys == []


@mock_aws
def test_upload_bundle_refuses_existing_object_with_different_hash(tmp_path: Path) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    bundle_dir, manifest = make_bundle(tmp_path)
    video = manifest["artifacts"][0]
    s3.put_object(
        Bucket=BUCKET,
        Key=video["r2_key"],
        Body=b"different",
        Metadata={"sha256": "0" * 64},
    )

    with pytest.raises(IntegrityConflict, match="cam01"):
        R2BundleUploader(RecordingClient(s3), BUCKET).upload_bundle(bundle_dir, manifest)


@mock_aws
def test_artifact_failure_never_uploads_completion_manifest(tmp_path: Path) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    bundle_dir, manifest = make_bundle(tmp_path)
    recording = RecordingClient(s3, fail_key_suffix="thumbnail.jpg")

    with pytest.raises(RuntimeError, match="synthetic"):
        R2BundleUploader(recording, BUCKET).upload_bundle(bundle_dir, manifest)

    with pytest.raises(ClientError) as error:
        s3.head_object(Bucket=BUCKET, Key=manifest["manifest_r2_key"])
    assert error.value.response["Error"]["Code"] == "404"


def test_manifest_local_file_sha_is_not_part_of_source_artifact_list(tmp_path: Path) -> None:
    bundle_dir, manifest = make_bundle(tmp_path)
    names = [item["name"] for item in manifest["artifacts"]]
    assert names == ["video.mp4", "thumbnail.jpg", "ffmpeg.sanitized.log"]
    assert not (bundle_dir / "manifest.json").exists()
    assert all(len(item["sha256"]) == 64 for item in manifest["artifacts"])
    assert sha256_file(bundle_dir / "video.mp4") == manifest["artifacts"][0]["sha256"]

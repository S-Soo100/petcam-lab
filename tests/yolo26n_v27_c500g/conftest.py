"""Shared synthetic fixtures for the v2.7 preparation pipeline."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


@dataclass
class FakeBundle:
    root: Path
    bundle_dir: Path
    video: Path
    thumbnail: Path
    log: Path
    manifest: Path


@pytest.fixture
def fake_bundle(tmp_path: Path) -> FakeBundle:
    root = tmp_path / "recordings"
    bundle_dir = root / "cam01/night=2026-08-20/20260820T200000+0900"
    bundle_dir.mkdir(parents=True)
    video = bundle_dir / "video.mp4"
    video.write_bytes(b"synthetic-c500g-video")
    thumbnail = bundle_dir / "thumbnail.jpg"
    thumbnail.write_bytes(b"synthetic-thumbnail")
    log = bundle_dir / "ffmpeg.sanitized.log"
    log.write_text("synthetic safe log\n", encoding="utf-8")
    relative = "cam01/night=2026-08-20/20260820T200000+0900"

    def artifact(path: Path, content_type: str) -> dict[str, object]:
        return {
            "name": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "content_type": content_type,
            "r2_key": f"{relative}/{path.name}",
        }

    manifest = bundle_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "rap-c500g-bundle/v1",
                "bundle_id": "rap-00000000000000000000000000000001",
                "mode": "production",
                "camera_key": "cam01",
                "test_run_id": None,
                "night_date": "2026-08-20",
                "scheduled_start_utc": "2026-08-20T11:00:00+00:00",
                "actual_start_utc": "2026-08-20T11:00:00+00:00",
                "partial": False,
                "relative_bundle_path": relative,
                "media": {
                    "duration_sec": 1800.0,
                    "codec": "hevc",
                    "width": 2880,
                    "height": 1620,
                    "fps": 15.0,
                },
                "capture": {"ffmpeg_exit_code": 0, "verified": True},
                "artifacts": [
                    artifact(video, "video/mp4"),
                    artifact(thumbnail, "image/jpeg"),
                    artifact(log, "text/plain; charset=utf-8"),
                ],
                "manifest_r2_key": f"{relative}/manifest.json",
                "upload_status": "uploaded",
                "r2_verified": True,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return FakeBundle(
        root=root,
        bundle_dir=bundle_dir,
        video=video,
        thumbnail=thumbnail,
        log=log,
        manifest=manifest,
    )


@dataclass
class FakeR2:
    video_sha256: str = ""
    objects: dict[str, dict[str, object]] = field(default_factory=dict)
    write_calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = field(
        default_factory=list
    )

    def list_objects_v2(self, **_: object) -> dict[str, object]:
        return {
            "Contents": [
                {"Key": key, "Size": metadata["ContentLength"]}
                for key, metadata in sorted(self.objects.items())
            ]
        }

    def head_object(self, **kwargs: object) -> dict[str, object]:
        key = str(kwargs["Key"])
        result = dict(self.objects[key])
        if key.endswith("/video.mp4"):
            result["Metadata"] = {"sha256": self.video_sha256}
        return result

    def __getattr__(self, name: str) -> Any:
        if name in {"put_object", "upload_file", "delete_object"}:
            def record(*args: object, **kwargs: object) -> None:
                self.write_calls.append((name, args, kwargs))

            return record
        raise AttributeError(name)


@pytest.fixture
def fake_r2(fake_bundle: FakeBundle) -> FakeR2:
    manifest = json.loads(fake_bundle.manifest.read_text(encoding="utf-8"))
    objects = {
        artifact["r2_key"]: {
            "ContentLength": artifact["size_bytes"],
            "Metadata": {"sha256": artifact["sha256"]},
        }
        for artifact in manifest["artifacts"]
    }
    return FakeR2(
        video_sha256=hashlib.sha256(fake_bundle.video.read_bytes()).hexdigest(),
        objects=objects,
    )


@dataclass
class FakeDb:
    rows: list[dict[str, object]] = field(default_factory=list)
    write_calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = field(
        default_factory=list
    )

    def select(self, _columns: str) -> "FakeDb":
        return self

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=self.rows)

    def __getattr__(self, name: str) -> Any:
        if name in {"insert", "upsert", "update", "delete"}:
            def record(*args: object, **kwargs: object) -> "FakeDb":
                self.write_calls.append((name, args, kwargs))
                return self

            return record
        raise AttributeError(name)


@pytest.fixture
def fake_db(fake_bundle: FakeBundle) -> FakeDb:
    from backend.rap_c500g_repository import manifest_to_row

    manifest = json.loads(fake_bundle.manifest.read_text(encoding="utf-8"))
    return FakeDb(rows=[manifest_to_row(manifest)])


@dataclass(frozen=True)
class CliResult:
    exit_code: int
    stdout: str
    stderr: str


@pytest.fixture
def cli_runner():
    def run(*args: str) -> CliResult:
        completed = subprocess.run(
            [sys.executable, "-m", "scripts.yolo26n_v27_c500g.cli", *args],
            check=False,
            capture_output=True,
            text=True,
        )
        return CliResult(completed.returncode, completed.stdout, completed.stderr)

    return run


@pytest.fixture
def fake_c500g_tree(tmp_path: Path, fake_bundle: FakeBundle) -> SimpleNamespace:
    attempt = tmp_path / "attempts/fake-a1"
    attempt.mkdir(parents=True)
    return SimpleNamespace(root=tmp_path, source=fake_bundle.root, attempt=attempt)

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from backend.yolo_release import v25_release_manifest
from scripts.manage_yolo_v25_owner_preview_worker import (
    LABEL,
    PORT,
    ManagerError,
    build_plist,
    validate_health_payload,
    validate_install,
)


def _git_runner(args: list[str], cwd: Path) -> str:
    assert cwd.is_absolute()
    if args == ["rev-parse", "HEAD"]:
        return "a" * 40
    if args == ["status", "--porcelain"]:
        return ""
    raise AssertionError(args)


def _write_env(path: Path, manifest_path: Path) -> None:
    path.write_text(
        f'YOLO_RELEASE_MANIFEST="{manifest_path}"\n'
        f'YOLO_EXPECTED_MODEL_VERSION="{v25_release_manifest().model_version}"\n'
        f'YOLO_WORKER_TOKEN={"t" * 43}\n'
    )
    path.chmod(0o600)


def test_v25_plist_is_parallel_localhost_runtime_with_exact_model_env(
    tmp_path: Path,
) -> None:
    plist = build_plist(
        repo=tmp_path / "repo",
        env_file=tmp_path / "worker.env",
        home=tmp_path,
    )
    encoded = plistlib.dumps(plist).decode()

    assert LABEL == "com.petcam.yolo-preview-worker-v25"
    assert PORT == 8095
    assert plist["Label"] == LABEL
    assert "127.0.0.1" in encoded and "8095" in encoded
    assert "0.0.0.0" not in encoded
    assert "YOLO_WORKER_TOKEN" not in encoded
    assert "backend.yolo_preview_worker:create_runtime_app" in encoded


def test_v25_install_requires_exact_release_and_expected_version_env(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest_path = tmp_path / "release" / "manifest.json"
    env_file = tmp_path / "worker.env"
    _write_env(env_file, manifest_path)

    validate_install(
        repo=repo,
        env_file=env_file,
        release_manifest=manifest_path,
        expected_head="a" * 40,
        hostname=lambda: "baeg-endeuui-Macmini.local",
        git_runner=_git_runner,
        release_verifier=lambda _path: v25_release_manifest(),
    )

    env_file.write_text(
        f'YOLO_RELEASE_MANIFEST="{manifest_path}"\nYOLO_WORKER_TOKEN={"t" * 43}\n'
    )
    env_file.chmod(0o600)
    with pytest.raises(ManagerError, match="expected_model_env_invalid"):
        validate_install(
            repo=repo,
            env_file=env_file,
            release_manifest=manifest_path,
            expected_head="a" * 40,
            hostname=lambda: "baeg-endeuui-Macmini.local",
            git_runner=_git_runner,
            release_verifier=lambda _path: v25_release_manifest(),
        )


def test_v25_health_payload_is_exact_owner_preview_identity() -> None:
    manifest = v25_release_manifest()
    payload = {
        "status": "ok",
        "model_version": manifest.model_version,
        "device": "mps",
        "checkpoint_sha256": manifest.checkpoint_sha256,
        "threshold": 0.20,
        "development_only": True,
        "usage_scope": "owner_preview_bbox_suggestion_only",
    }

    assert validate_health_payload(payload) == payload
    with pytest.raises(ManagerError, match="health_identity_invalid"):
        validate_health_payload({**payload, "threshold": 0.25})

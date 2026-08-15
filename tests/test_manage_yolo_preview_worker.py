from __future__ import annotations

import os
import json
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

import backend.yolo_release as yolo_release
from backend.yolo_release import (
    FixedTestMetrics,
    YoloReleaseManifest,
    create_immutable_release,
)
from scripts.manage_yolo_preview_worker import (
    LABEL,
    PORT,
    ManagerError,
    build_plist,
    install,
    status,
    uninstall,
    validate_install,
    validate_health_payload,
)


def test_direct_script_cli_can_resolve_project_imports() -> None:
    repo = Path(__file__).parents[1]

    completed = subprocess.run(
        [sys.executable, str(repo / "scripts" / "manage_yolo_preview_worker.py"), "--help"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "install" in completed.stdout

    install_help = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "manage_yolo_preview_worker.py"),
            "install",
            "--help",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "--release-manifest" in install_help.stdout
    assert "--checkpoint" not in install_help.stdout


def _git_runner(*, head: str = "a" * 40, status: str = ""):
    def run(args: list[str], cwd: Path) -> str:
        assert cwd.is_absolute()
        if args == ["rev-parse", "HEAD"]:
            return head
        if args == ["status", "--porcelain"]:
            return status
        raise AssertionError(args)

    return run


def _write_env(path: Path, manifest_path: Path) -> None:
    path.write_text(
        f'YOLO_RELEASE_MANIFEST="{manifest_path}"\nYOLO_WORKER_TOKEN={"t" * 43}\n'
    )
    path.chmod(0o600)


def test_plist_is_isolated_v23_localhost_runtime_without_secret(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    env_file = tmp_path / "worker.env"
    plist = build_plist(repo=repo, env_file=env_file, home=tmp_path)
    encoded = plistlib.dumps(plist).decode()

    assert LABEL == "com.petcam.yolo-preview-worker-v23"
    assert PORT == 8094
    assert plist["Label"] == LABEL
    assert "127.0.0.1" in encoded and "8094" in encoded
    assert "0.0.0.0" not in encoded
    assert "YOLO_WORKER_TOKEN" not in encoded
    assert LABEL in encoded
    assert str(repo) in encoded
    assert "--factory" in encoded
    assert "backend.yolo_preview_worker:create_runtime_app" in encoded


def test_validate_install_rejects_wrong_host_before_git(tmp_path: Path) -> None:
    with pytest.raises(ManagerError, match="runtime_host_mismatch"):
        validate_install(
            repo=tmp_path / "repo",
            env_file=tmp_path / "worker.env",
            release_manifest=tmp_path / "manifest.json",
            expected_head="a" * 40,
            hostname=lambda: "wrong.local",
            git_runner=lambda *_args, **_kwargs: pytest.fail("git must not run"),
            release_verifier=lambda _path: None,
        )


@pytest.mark.parametrize(
    ("head", "status", "expected"),
    [("short", "", "repo_head_invalid"), ("a" * 40, " M file", "repo_dirty")],
)
def test_validate_install_rejects_non_exact_or_dirty_repo(
    tmp_path: Path, head: str, status: str, expected: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    env_file = tmp_path / "worker.env"
    _write_env(env_file, tmp_path / "manifest.json")

    with pytest.raises(ManagerError, match=expected):
        validate_install(
            repo=repo,
            env_file=env_file,
            release_manifest=tmp_path / "manifest.json",
            expected_head="a" * 40,
            hostname=lambda: "baeg-endeuui-Macmini.local",
            git_runner=_git_runner(head=head, status=status),
            release_verifier=lambda _path: None,
        )


def test_validate_install_rejects_non_0600_env(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    env_file = tmp_path / "worker.env"
    _write_env(env_file, tmp_path / "manifest.json")
    env_file.chmod(0o644)

    with pytest.raises(ManagerError, match="env_mode_invalid"):
        validate_install(
            repo=repo,
            env_file=env_file,
            release_manifest=tmp_path / "manifest.json",
            expected_head="a" * 40,
            hostname=lambda: "baeg-endeuui-Macmini.local",
            git_runner=_git_runner(),
            release_verifier=lambda _path: None,
        )


def test_validate_install_redacts_release_failure(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    env_file = tmp_path / "worker.env"
    release_manifest = tmp_path / "secret" / "manifest.json"
    _write_env(env_file, release_manifest)

    with pytest.raises(ManagerError, match="release_identity_invalid") as caught:
        validate_install(
            repo=repo,
            env_file=env_file,
            release_manifest=release_manifest,
            expected_head="a" * 40,
            hostname=lambda: "baeg-endeuui-Macmini.local",
            git_runner=_git_runner(),
            release_verifier=lambda _path: (_ for _ in ()).throw(RuntimeError("secret")),
        )

    assert str(tmp_path) not in str(caught.value)


def test_validate_install_rejects_writable_release_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    env_file = tmp_path / "worker.env"
    source = tmp_path / "source.pt"
    source.write_bytes(b"checkpoint")
    manifest = YoloReleaseManifest(
        schema="petcam-yolo-release-v1",
        model_version="yolo26n-owner-dataset-v2.3-warm-start+dbed3a2d8018",
        checkpoint_sha256="47320987f9a49d5b00119b960f247a956773f57543982b8bfcb6da5bb3afd9ef",
        checkpoint_size=10,
        candidate="warm-start",
        threshold=0.25,
        image_size=960,
        iou=0.7,
        max_detections=20,
        evaluation_tier="development",
        future_holdout_required=True,
        allowed_use="labeling_bbox_assist_only",
        forbidden_uses=(
            "gt_auto_confirm",
            "absence_decision",
            "gme_routing",
            "r2_classification",
            "deletion",
            "vlm_skip",
            "behavior_name",
            "event_grouping",
        ),
        fixed_test=FixedTestMetrics(
            tp=53,
            fp=19,
            fn=37,
            precision=0.7361111111111112,
            recall=0.5888888888888889,
        ),
    )
    original_resolver = yolo_release.release_manifest_for_version
    monkeypatch.setattr(
        yolo_release,
        "release_manifest_for_version",
        lambda version: manifest
        if version == manifest.model_version
        else original_resolver(version),
    )
    checkpoint, manifest_path = create_immutable_release(
        source=source,
        release_root=tmp_path / "releases",
        manifest=manifest,
    )
    _write_env(env_file, manifest_path)
    checkpoint.chmod(0o644)

    with pytest.raises(ManagerError, match="release_identity_invalid"):
        validate_install(
            repo=repo,
            env_file=env_file,
            release_manifest=manifest_path,
            expected_head="a" * 40,
            hostname=lambda: "baeg-endeuui-Macmini.local",
            git_runner=_git_runner(),
        )


def test_validate_install_rejects_env_manifest_path_mismatch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    env_file = tmp_path / "worker.env"
    _write_env(env_file, tmp_path / "different" / "manifest.json")

    with pytest.raises(ManagerError, match="release_env_mismatch"):
        validate_install(
            repo=repo,
            env_file=env_file,
            release_manifest=tmp_path / "release" / "manifest.json",
            expected_head="a" * 40,
            hostname=lambda: "baeg-endeuui-Macmini.local",
            git_runner=_git_runner(),
            release_verifier=lambda _path: pytest.fail("release verification must follow env binding"),
        )


def _exact_health() -> dict[str, object]:
    return {
        "status": "ok",
        "model_version": "yolo26n-owner-dataset-v2.3-warm-start+dbed3a2d8018",
        "device": "mps",
        "checkpoint_sha256": "dbed3a2d8018a2eb6e4130de57d301414fcd6c9ba80aef8aafdaba55b19a6a34",
        "threshold": 0.25,
        "development_only": True,
        "usage_scope": "labeling_bbox_assist_only",
    }


def test_health_payload_rejects_arbitrary_model_identity() -> None:
    assert validate_health_payload(_exact_health()) == _exact_health()
    arbitrary = {**_exact_health(), "model_version": "arbitrary-model"}
    with pytest.raises(ManagerError, match="health_identity_invalid"):
        validate_health_payload(arbitrary)


def test_status_prints_only_allowlisted_verified_health(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_file = tmp_path / "worker.env"
    _write_env(env_file, tmp_path / "manifest.json")
    payload = {**_exact_health(), "private_path": "/Users/private/best.pt"}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(payload).encode()

    result = status(
        env_file=env_file,
        uid=501,
        service_runner=lambda _args: subprocess.CompletedProcess([], 0, "", ""),
        opener=lambda _request, timeout: Response(),
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "private_path" not in output
    assert "/Users/private" not in output
    assert json.dumps(_exact_health(), ensure_ascii=False) in output


def test_install_requires_replace_for_existing_plist(tmp_path: Path) -> None:
    target = tmp_path / "LaunchAgents" / f"{LABEL}.plist"
    target.parent.mkdir()
    target.write_bytes(b"existing")

    with pytest.raises(ManagerError, match="plist_exists"):
        install(
            plist=build_plist(repo=tmp_path / "repo", env_file=tmp_path / "worker.env", home=tmp_path),
            target=target,
            replace=False,
            launchctl=lambda _args: 0,
        )

    assert target.read_bytes() == b"existing"


def test_install_atomically_writes_and_bootstraps(tmp_path: Path) -> None:
    target = tmp_path / "LaunchAgents" / f"{LABEL}.plist"
    calls: list[list[str]] = []
    plist = build_plist(repo=tmp_path / "repo", env_file=tmp_path / "worker.env", home=tmp_path)

    install(
        plist=plist,
        target=target,
        replace=False,
        launchctl=lambda args: calls.append(args) or 0,
        uid=501,
    )

    assert plistlib.loads(target.read_bytes()) == plist
    assert calls == [["bootstrap", "gui/501", str(target)]]
    assert not list(target.parent.glob("*.tmp"))


def test_install_retries_transient_launchctl_bootstrap_failure(tmp_path: Path) -> None:
    target = tmp_path / "LaunchAgents" / f"{LABEL}.plist"
    target.parent.mkdir()
    target.write_bytes(b"existing")
    calls: list[list[str]] = []
    delays: list[float] = []
    bootstrap_attempts = 0

    def launchctl(args: list[str]) -> int:
        nonlocal bootstrap_attempts
        calls.append(args)
        if args[0] == "bootstrap":
            bootstrap_attempts += 1
            return 5 if bootstrap_attempts == 1 else 0
        return 0

    install(
        plist=build_plist(repo=tmp_path / "repo", env_file=tmp_path / "worker.env", home=tmp_path),
        target=target,
        replace=True,
        launchctl=launchctl,
        uid=501,
        sleeper=delays.append,
    )

    assert calls == [
        ["bootout", "gui/501/com.petcam.yolo-preview-worker-v23"],
        ["bootstrap", "gui/501", str(target)],
        ["bootstrap", "gui/501", str(target)],
    ]
    assert delays == [0.25]


def test_uninstall_is_idempotent_and_preserves_runtime_inputs(tmp_path: Path) -> None:
    target = tmp_path / "LaunchAgents" / f"{LABEL}.plist"
    env_file = tmp_path / "worker.env"
    checkpoint = tmp_path / "best.pt"
    manifest = tmp_path / "manifest.json"
    env_file.write_text("secret")
    checkpoint.write_bytes(b"checkpoint")
    manifest.write_text("{}")
    calls: list[list[str]] = []

    uninstall(target=target, launchctl=lambda args: calls.append(args) or 3, uid=501)
    target.parent.mkdir()
    target.write_bytes(b"plist")
    uninstall(target=target, launchctl=lambda args: calls.append(args) or 0, uid=501)

    assert calls == [
        ["bootout", "gui/501/com.petcam.yolo-preview-worker-v23"],
        ["bootout", "gui/501/com.petcam.yolo-preview-worker-v23"],
    ]
    assert not target.exists()
    assert env_file.exists()
    assert checkpoint.exists()
    assert manifest.exists()

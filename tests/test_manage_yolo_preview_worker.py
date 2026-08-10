from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.manage_yolo_preview_worker import (
    LABEL,
    ManagerError,
    build_plist,
    install,
    uninstall,
    validate_install,
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


def _git_runner(*, head: str = "a" * 40, status: str = ""):
    def run(args: list[str], cwd: Path) -> str:
        assert cwd.is_absolute()
        if args == ["rev-parse", "HEAD"]:
            return head
        if args == ["status", "--porcelain"]:
            return status
        raise AssertionError(args)

    return run


def test_plist_is_localhost_exact_repo_and_contains_no_secret(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    env_file = tmp_path / "worker.env"
    plist = build_plist(repo=repo, env_file=env_file, home=tmp_path)
    encoded = plistlib.dumps(plist).decode()

    assert "127.0.0.1" in encoded and "8093" in encoded
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
            checkpoint=tmp_path / "best.pt",
            expected_head="a" * 40,
            hostname=lambda: "wrong.local",
            git_runner=lambda *_args, **_kwargs: pytest.fail("git must not run"),
            checkpoint_verifier=lambda _path: None,
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
    env_file.write_text("TOKEN=value\n")
    env_file.chmod(0o600)

    with pytest.raises(ManagerError, match=expected):
        validate_install(
            repo=repo,
            env_file=env_file,
            checkpoint=tmp_path / "best.pt",
            expected_head="a" * 40,
            hostname=lambda: "baeg-endeuui-Macmini.local",
            git_runner=_git_runner(head=head, status=status),
            checkpoint_verifier=lambda _path: None,
        )


def test_validate_install_rejects_non_0600_env(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    env_file = tmp_path / "worker.env"
    env_file.write_text("TOKEN=value\n")
    env_file.chmod(0o644)

    with pytest.raises(ManagerError, match="env_mode_invalid"):
        validate_install(
            repo=repo,
            env_file=env_file,
            checkpoint=tmp_path / "best.pt",
            expected_head="a" * 40,
            hostname=lambda: "baeg-endeuui-Macmini.local",
            git_runner=_git_runner(),
            checkpoint_verifier=lambda _path: None,
        )


def test_validate_install_redacts_checkpoint_failure(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    env_file = tmp_path / "worker.env"
    env_file.write_text("TOKEN=value\n")
    env_file.chmod(0o600)

    with pytest.raises(ManagerError, match="checkpoint_identity_invalid") as caught:
        validate_install(
            repo=repo,
            env_file=env_file,
            checkpoint=tmp_path / "secret" / "best.pt",
            expected_head="a" * 40,
            hostname=lambda: "baeg-endeuui-Macmini.local",
            git_runner=_git_runner(),
            checkpoint_verifier=lambda _path: (_ for _ in ()).throw(RuntimeError("secret")),
        )

    assert str(tmp_path) not in str(caught.value)


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


def test_uninstall_is_idempotent_and_preserves_runtime_inputs(tmp_path: Path) -> None:
    target = tmp_path / "LaunchAgents" / f"{LABEL}.plist"
    env_file = tmp_path / "worker.env"
    checkpoint = tmp_path / "best.pt"
    env_file.write_text("secret")
    checkpoint.write_bytes(b"checkpoint")
    calls: list[list[str]] = []

    uninstall(target=target, launchctl=lambda args: calls.append(args) or 3, uid=501)
    target.parent.mkdir()
    target.write_bytes(b"plist")
    uninstall(target=target, launchctl=lambda args: calls.append(args) or 0, uid=501)

    assert calls == [
        ["bootout", "gui/501/com.petcam.yolo-preview-worker"],
        ["bootout", "gui/501/com.petcam.yolo-preview-worker"],
    ]
    assert not target.exists()
    assert env_file.exists()
    assert checkpoint.exists()

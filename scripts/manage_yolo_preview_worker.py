#!/usr/bin/env python3
"""Mac mini 보호 Preview YOLO LaunchAgent를 재현 가능하게 관리한다."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import socket
import stat
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from backend.yolo_preview_worker import EXPECTED_HOST, verify_checkpoint
from backend.yolo_preview_worker import CHECKPOINT_SHA256, CHECKPOINT_SIZE


LABEL = "com.petcam.yolo-preview-worker"
PORT = 8093
GitRunner = Callable[[list[str], Path], str]
LaunchctlRunner = Callable[[list[str]], int]


class ManagerError(RuntimeError):
    """경로나 secret을 포함하지 않는 운영 도구 오류."""


def _run_git(args: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _verify_pinned_checkpoint(path: Path) -> None:
    verify_checkpoint(
        path,
        expected_size=CHECKPOINT_SIZE,
        expected_sha256=CHECKPOINT_SHA256,
    )


def validate_install(
    *,
    repo: Path,
    env_file: Path,
    checkpoint: Path,
    expected_head: str,
    hostname: Callable[[], str] = socket.gethostname,
    git_runner: GitRunner = _run_git,
    checkpoint_verifier: Callable[[Path], None] = _verify_pinned_checkpoint,
) -> None:
    if hostname() != EXPECTED_HOST:
        raise ManagerError("runtime_host_mismatch")
    if not repo.is_absolute() or not repo.is_dir():
        raise ManagerError("repo_invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_head):
        raise ManagerError("repo_head_invalid")
    try:
        actual_head = git_runner(["rev-parse", "HEAD"], repo).strip()
        dirty = git_runner(["status", "--porcelain"], repo).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ManagerError("repo_invalid") from exc
    if not re.fullmatch(r"[0-9a-f]{40}", actual_head) or actual_head != expected_head:
        raise ManagerError("repo_head_invalid")
    if dirty:
        raise ManagerError("repo_dirty")
    try:
        mode = stat.S_IMODE(env_file.lstat().st_mode)
    except OSError as exc:
        raise ManagerError("env_mode_invalid") from exc
    if env_file.is_symlink() or not env_file.is_file() or mode != 0o600:
        raise ManagerError("env_mode_invalid")
    try:
        checkpoint_verifier(checkpoint)
    except Exception as exc:
        raise ManagerError("checkpoint_identity_invalid") from exc


def build_plist(*, repo: Path, env_file: Path, home: Path | None = None) -> dict[str, object]:
    runtime_home = home or Path.home()
    command = (
        'set -a; source "$1"; set +a; cd "$2"; '
        "exec /opt/homebrew/bin/uv run --group yolo-preview uvicorn --factory "
        "backend.yolo_preview_worker:create_runtime_app "
        f"--host 127.0.0.1 --port {PORT}"
    )
    log_root = runtime_home / "Library" / "Logs" / "petcam"
    return {
        "Label": LABEL,
        "ProgramArguments": [
            "/bin/zsh",
            "-lc",
            command,
            LABEL,
            str(env_file),
            str(repo),
        ],
        "WorkingDirectory": str(repo),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "StandardOutPath": str(log_root / "yolo-preview-worker.out.log"),
        "StandardErrorPath": str(log_root / "yolo-preview-worker.err.log"),
    }


def _launchctl(args: list[str]) -> int:
    return subprocess.run(["launchctl", *args], check=False).returncode


def install(
    *,
    plist: dict[str, object],
    target: Path,
    replace: bool,
    launchctl: LaunchctlRunner = _launchctl,
    uid: int | None = None,
) -> None:
    if target.exists() and not replace:
        raise ManagerError("plist_exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    log_path = Path(str(plist["StandardOutPath"])).parent
    log_path.mkdir(parents=True, exist_ok=True)
    runtime_uid = os.getuid() if uid is None else uid
    if target.exists():
        launchctl(["bootout", f"gui/{runtime_uid}/{LABEL}"])
    with tempfile.NamedTemporaryFile(
        dir=target.parent,
        prefix=f".{LABEL}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        plistlib.dump(plist, handle)
    try:
        temporary.chmod(0o644)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    if launchctl(["bootstrap", f"gui/{runtime_uid}", str(target)]) != 0:
        raise ManagerError("launchctl_bootstrap_failed")


def uninstall(
    *,
    target: Path,
    launchctl: LaunchctlRunner = _launchctl,
    uid: int | None = None,
) -> None:
    runtime_uid = os.getuid() if uid is None else uid
    launchctl(["bootout", f"gui/{runtime_uid}/{LABEL}"])
    target.unlink(missing_ok=True)


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def status(*, env_file: Path, uid: int | None = None) -> int:
    runtime_uid = os.getuid() if uid is None else uid
    service = subprocess.run(
        ["launchctl", "print", f"gui/{runtime_uid}/{LABEL}"],
        check=False,
        capture_output=True,
        text=True,
    )
    print(json.dumps({"service_loaded": service.returncode == 0}))
    try:
        token = _read_env_file(env_file)["YOLO_WORKER_TOKEN"]
        request = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/v1/health",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            health = json.loads(response.read())
        print(json.dumps({"health": health}, ensure_ascii=False))
        return 0 if service.returncode == 0 else 1
    except (KeyError, OSError, ValueError, urllib.error.URLError):
        print(json.dumps({"health": "unavailable"}))
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("--repo", type=Path, required=True)
    install_parser.add_argument("--env-file", type=Path, required=True)
    install_parser.add_argument("--checkpoint", type=Path, required=True)
    install_parser.add_argument("--expected-head", required=True)
    install_parser.add_argument("--replace", action="store_true")
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--env-file", type=Path, required=True)
    subparsers.add_parser("uninstall")
    return parser


def main() -> int:
    args = _parser().parse_args()
    target = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    try:
        if args.command == "install":
            repo = args.repo.resolve()
            env_file = args.env_file.resolve()
            checkpoint = args.checkpoint.resolve()
            validate_install(
                repo=repo,
                env_file=env_file,
                checkpoint=checkpoint,
                expected_head=args.expected_head,
            )
            install(
                plist=build_plist(repo=repo, env_file=env_file),
                target=target,
                replace=args.replace,
            )
            print(json.dumps({"installed": LABEL, "head": args.expected_head}))
            return 0
        if args.command == "status":
            return status(env_file=args.env_file.resolve())
        uninstall(target=target)
        print(json.dumps({"uninstalled": LABEL}))
        return 0
    except ManagerError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

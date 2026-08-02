"""12-frame v2 canary 전용 임시 LaunchAgent 하나만 관리해."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
from typing import Callable

from scripts.manage_local_vlm_clip_shadow_launchd import (
    LaunchConfig,
    SafetyError,
    _require_runtime_paths,
    runtime_state,
    validate_environment,
)


LABEL = "com.petcam.local-vlm-clip-shadow-canary-v2"
END_AT = "2026-08-03T07:00:00+09:00"
MODEL = "gemma3:4b"
RunCommand = Callable[..., subprocess.CompletedProcess[str]]


def exact_plist_path(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def render_plist(config: LaunchConfig) -> bytes:
    arguments = [
        str(config.python), str(config.repo_root / "scripts" / "run_local_vlm_clip_shadow_v2.py"), "run",
        "--env-file", str(config.env_file), "--salt-file", str(config.salt_file),
        "--output-dir", str(config.output_dir), "--expected-host", config.expected_host,
        "--expected-head", config.expected_head, "--expected-model", MODEL, "--end-at", END_AT,
    ]
    return plistlib.dumps({
        "Label": LABEL, "ProgramArguments": arguments,
        "WorkingDirectory": str(config.repo_root),
        "RunAtLoad": False, "KeepAlive": False,
        "StandardOutPath": str(config.output_dir / "service.stdout.log"),
        "StandardErrorPath": str(config.output_dir / "service.stderr.log"),
        "ProcessType": "Background", "Umask": 0o77,
    }, sort_keys=True)


def install(
    config: LaunchConfig,
    *,
    home: Path,
    run_command: RunCommand = subprocess.run,
) -> Path:
    host, head, clean = runtime_state(config)
    validate_environment(config, host=host, head=head, clean=clean)
    _require_runtime_paths(config)
    path = exact_plist_path(home)
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise SafetyError("launchagents_path")
    payload = render_plist(config)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise SafetyError("existing_plist_drift")
        raise SafetyError("existing_plist")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    domain = f"gui/{config.uid}"
    bootstrap = run_command(
        ["/bin/launchctl", "bootstrap", domain, str(path)],
        text=True, capture_output=True, timeout=20,
    )
    if bootstrap.returncode != 0:
        raise SafetyError("launchctl_bootstrap")
    kickstart = run_command(
        ["/bin/launchctl", "kickstart", f"{domain}/{LABEL}"],
        text=True, capture_output=True, timeout=20,
    )
    if kickstart.returncode != 0:
        raise SafetyError("launchctl_kickstart")
    return path


def status(config: LaunchConfig, *, run_command: RunCommand = subprocess.run) -> dict[str, object]:
    result = run_command(
        ["/bin/launchctl", "print", f"gui/{config.uid}/{LABEL}"],
        text=True, capture_output=True, timeout=20,
    )
    return {"label": LABEL, "loaded": result.returncode == 0, "detail": result.stdout[-2000:]}


def uninstall(
    config: LaunchConfig,
    *,
    home: Path,
    run_command: RunCommand = subprocess.run,
) -> dict[str, object]:
    path = exact_plist_path(home)
    if path.is_symlink():
        raise SafetyError("plist_symlink")
    result = run_command(
        ["/bin/launchctl", "bootout", f"gui/{config.uid}/{LABEL}"],
        text=True, capture_output=True, timeout=20,
    )
    if path.exists():
        if not path.is_file():
            raise SafetyError("plist_target")
        path.unlink()
    return {"label": LABEL, "loaded_before": result.returncode == 0, "plist_removed": not path.exists()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("render", "install", "status", "uninstall"))
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--salt-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--home", type=Path, default=Path.home())
    args = parser.parse_args()
    config = LaunchConfig(
        repo_root=args.repo_root, python=args.python, env_file=args.env_file,
        salt_file=args.salt_file, output_dir=args.output_dir,
        expected_host=args.expected_host, expected_head=args.expected_head,
    )
    if args.command == "render":
        print(render_plist(config).decode(), end="")
        return 0
    if args.command == "install":
        result: object = {"plist": str(install(config, home=args.home))}
    elif args.command == "status":
        result = status(config)
    else:
        result = uninstall(config, home=args.home)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

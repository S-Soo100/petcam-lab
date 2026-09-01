"""Mac mini용 RAP C500G manager launchd plist renderer."""

from __future__ import annotations

import argparse
import plistlib
from dataclasses import dataclass
from pathlib import Path


LABEL = "com.teraai.rap-c500g-manager"


@dataclass(frozen=True, slots=True)
class LaunchdConfig:
    repo: Path
    uv: Path
    log_dir: Path
    state_path: Path


def render_plist(config: LaunchdConfig) -> bytes:
    paths = (config.repo, config.uv, config.log_dir, config.state_path)
    if any(not path.is_absolute() for path in paths):
        raise ValueError("all launchd runtime paths must be absolute")
    payload = {
        "Label": LABEL,
        "ProgramArguments": [
            str(config.uv),
            "run",
            "python",
            "-m",
            "backend.rap_c500g_manager_main",
            "--state-path",
            str(config.state_path),
            "serve",
        ],
        "WorkingDirectory": str(config.repo),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONUNBUFFERED": "1",
        },
        "StandardOutPath": str(config.log_dir / "stdout.log"),
        "StandardErrorPath": str(config.log_dir / "stderr.log"),
    }
    return plistlib.dumps(payload, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--uv", type=Path, required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--state-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    config = LaunchdConfig(args.repo, args.uv, args.log_dir, args.state_path)
    args.log_dir.mkdir(parents=True, exist_ok=True)
    args.state_path.parent.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(render_plist(config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

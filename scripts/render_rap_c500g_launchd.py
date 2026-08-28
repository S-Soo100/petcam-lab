"""RAP C500G recorder launchd plist를 secret 없이 렌더링한다."""

from __future__ import annotations

import argparse
import plistlib
from pathlib import Path


LABEL = "com.teraai.rap-c500g-recorder"


def render_plist(*, repo: Path, log_dir: Path) -> bytes:
    payload = {
        "Label": LABEL,
        "ProgramArguments": [
            "/usr/bin/env",
            "uv",
            "run",
            "python",
            "-m",
            "backend.rap_c500g_main",
            "run",
        ],
        "WorkingDirectory": str(repo.resolve()),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        },
        "StandardOutPath": str((log_dir / "rap-c500g.stdout.log").resolve()),
        "StandardErrorPath": str((log_dir / "rap-c500g.stderr.log").resolve()),
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="RAP C500G launchd plist 렌더러")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.log_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(render_plist(repo=args.repo, log_dir=args.log_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

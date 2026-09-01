from __future__ import annotations

import plistlib
from pathlib import Path

from scripts.render_rap_c500g_manager_launchd import LaunchdConfig, render_plist


def test_render_plist_is_secret_free_and_pins_runtime_paths() -> None:
    config = LaunchdConfig(
        repo=Path("/Users/baek-end/.codex/worktrees/rap-c500g-r2/petcam-lab"),
        uv=Path("/opt/homebrew/bin/uv"),
        log_dir=Path("/Users/baek-end/Library/Logs/rap-c500g-manager"),
        state_path=Path("/Users/baek-end/Library/Application Support/rap-c500g-manager/manager.sqlite3"),
    )

    payload = render_plist(config)
    parsed = plistlib.loads(payload)
    encoded = payload.decode("utf-8")

    assert parsed["Label"] == "com.teraai.rap-c500g-manager"
    assert parsed["RunAtLoad"] is True
    assert parsed["KeepAlive"] is True
    assert parsed["WorkingDirectory"] == str(config.repo)
    args = parsed["ProgramArguments"]
    assert args[:5] == [
        str(config.uv),
        "run",
        "python",
        "-m",
        "backend.rap_c500g_manager_main",
    ]
    assert args[5] == "--state-path"
    assert args[-1] == "serve"
    assert "password" not in encoded.lower()
    assert "webhook" not in encoded.lower()
    assert "rtsp://" not in encoded


def test_render_plist_rejects_relative_paths() -> None:
    config = LaunchdConfig(
        repo=Path("relative/repo"),
        uv=Path("/opt/homebrew/bin/uv"),
        log_dir=Path("/tmp/logs"),
        state_path=Path("/tmp/state.sqlite3"),
    )
    try:
        render_plist(config)
    except ValueError as error:
        assert "absolute" in str(error)
    else:
        raise AssertionError("relative runtime path must be rejected")

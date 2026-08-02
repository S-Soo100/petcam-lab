from dataclasses import replace
from pathlib import Path
import plistlib
import subprocess

import pytest

from scripts.manage_local_vlm_clip_shadow_launchd import (
    LABEL,
    LaunchConfig,
    SafetyError,
    exact_plist_path,
    install,
    render_plist,
    validate_environment,
)


def _config(tmp_path: Path) -> LaunchConfig:
    return LaunchConfig(
        repo_root=tmp_path / "repo",
        python=tmp_path / "repo" / ".venv" / "bin" / "python",
        env_file=tmp_path / "private" / "runtime.env",
        salt_file=tmp_path / "private" / "salt.bin",
        output_dir=tmp_path / "private" / "run",
        expected_host="baeg-endeuui-Macmini.local",
        expected_head="a" * 40,
    )


def test_render_plist_is_one_shot_exact_and_contains_no_secret_value(tmp_path: Path) -> None:
    config = _config(tmp_path)
    payload = plistlib.loads(render_plist(config))
    assert payload["Label"] == LABEL
    assert payload["RunAtLoad"] is False
    assert payload["KeepAlive"] is False
    assert payload["Umask"] == 0o77
    args = payload["ProgramArguments"]
    assert args[0] == str(config.python)
    assert str(config.repo_root / "scripts" / "run_local_vlm_clip_shadow.py") in args
    assert ["--expected-model", "gemma3:4b"] == args[args.index("--expected-model"):args.index("--expected-model") + 2]
    assert "2026-08-03T07:00:00+09:00" in args
    assert "SUPABASE_SERVICE_ROLE_KEY" not in render_plist(config).decode()
    assert "KeepAlive" in payload and "StartInterval" not in payload


def test_exact_plist_path_and_environment_fail_closed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert exact_plist_path(tmp_path) == tmp_path / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    validate_environment(config, host=config.expected_host, head=config.expected_head, clean=True)
    with pytest.raises(SafetyError, match="host"):
        validate_environment(config, host="other", head=config.expected_head, clean=True)
    with pytest.raises(SafetyError, match="head"):
        validate_environment(config, host=config.expected_host, head="b" * 40, clean=True)
    with pytest.raises(SafetyError, match="dirty"):
        validate_environment(config, host=config.expected_host, head=config.expected_head, clean=False)
    with pytest.raises(SafetyError, match="absolute"):
        validate_environment(replace(config, python=Path("python")), host=config.expected_host, head=config.expected_head, clean=True)


def test_install_bootstraps_then_kickstarts_only_exact_label(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    for path in (config.repo_root, config.python.parent, config.env_file.parent, config.output_dir):
        path.mkdir(parents=True, exist_ok=True)
    config.python.write_bytes(b"")
    config.python.chmod(0o755)
    config.env_file.write_bytes(b"")
    config.salt_file.write_bytes(b"s" * 32)
    config.env_file.chmod(0o600)
    config.salt_file.chmod(0o600)
    config.output_dir.chmod(0o700)  # Gate A 통과 뒤 만들어진 private run dir야.
    (config.output_dir / "gate-a.json").write_bytes(b"{}")
    (config.output_dir / "gate-a.json").chmod(0o600)
    home = tmp_path / "home"
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    monkeypatch.setattr("scripts.manage_local_vlm_clip_shadow_launchd.runtime_state", lambda _c: (config.expected_host, config.expected_head, True))
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    path = install(config, home=home, run_command=fake_run)
    assert path == exact_plist_path(home)
    assert calls == [
        ["/bin/launchctl", "bootstrap", f"gui/{config.uid}", str(path)],
        ["/bin/launchctl", "kickstart", f"gui/{config.uid}/{LABEL}"],
    ]
    assert all("ollama" not in " ".join(call).lower() for call in calls)


def test_install_rejects_existing_different_or_symlink_plist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    config.repo_root.mkdir(parents=True)
    config.python.parent.mkdir(parents=True)
    config.python.write_bytes(b"")
    config.python.chmod(0o755)
    config.env_file.parent.mkdir(parents=True)
    config.env_file.write_bytes(b"")
    config.salt_file.write_bytes(b"s" * 32)
    config.env_file.chmod(0o600)
    config.salt_file.chmod(0o600)
    config.output_dir.mkdir(mode=0o700)
    (config.output_dir / "gate-a.json").write_bytes(b"{}")
    (config.output_dir / "gate-a.json").chmod(0o600)
    home = tmp_path / "home"
    target = exact_plist_path(home)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"different")
    monkeypatch.setattr("scripts.manage_local_vlm_clip_shadow_launchd.runtime_state", lambda _c: (config.expected_host, config.expected_head, True))
    with pytest.raises(SafetyError, match="existing"):
        install(config, home=home, run_command=lambda *_a, **_k: None)

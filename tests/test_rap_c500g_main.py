from pathlib import Path

import pytest

from backend.rap_c500g_main import _runtime, build_parser


def test_cli_exposes_test_run_and_sync_without_secret_arguments() -> None:
    parser = build_parser()

    test_args = parser.parse_args(["test", "--duration", "60"])
    manual_args = parser.parse_args(["manual-production", "--duration", "1800"])
    run_args = parser.parse_args(["run"])
    sync_args = parser.parse_args(["sync"])

    assert test_args.command == "test"
    assert test_args.duration == 60.0
    assert manual_args.command == "manual-production"
    assert manual_args.duration == 1800.0
    assert run_args.command == "run"
    assert sync_args.command == "sync"
    help_text = parser.format_help()
    assert "password" not in help_text.lower()
    assert "rtsp" not in help_text.lower()


def test_runtime_fails_closed_when_required_usb_mount_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mount = tmp_path / "RAP-C500G"
    root = mount / "RAP-c500g-recordings"
    monkeypatch.setenv("RAP_C500G_LOCAL_ROOT", str(root))
    monkeypatch.setenv("RAP_C500G_REQUIRED_MOUNT", str(mount))
    monkeypatch.setattr("backend.rap_c500g_main.load_dotenv", lambda _: None)
    monkeypatch.setattr(Path, "is_mount", lambda _: False)

    with pytest.raises(RuntimeError, match="required local mount is unavailable"):
        _runtime()


def test_runtime_rejects_local_root_outside_required_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mount = tmp_path / "RAP-C500G"
    root = tmp_path / "internal-disk-recordings"
    monkeypatch.setenv("RAP_C500G_LOCAL_ROOT", str(root))
    monkeypatch.setenv("RAP_C500G_REQUIRED_MOUNT", str(mount))
    monkeypatch.setattr("backend.rap_c500g_main.load_dotenv", lambda _: None)
    monkeypatch.setattr(Path, "is_mount", lambda _: True)

    with pytest.raises(RuntimeError, match="must be inside required local mount"):
        _runtime()

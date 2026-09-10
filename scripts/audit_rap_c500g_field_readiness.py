"""RAP C500G 현장 전원·LAN·USB·runtime을 변경 없이 aggregate 감사해."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from backend.rap_c500g_capture import CameraConfig, load_camera_configs
from backend.rap_c500g_manager_probe import (
    CameraProbeStatus,
    VolumeStatus,
    probe_camera,
    validate_selected_volume,
)


LABEL = "com.teraai.rap-c500g-manager"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE = Path.home() / "Library/Application Support/rap-c500g-manager/manager.sqlite3"
CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class FieldReadinessResult:
    ready: bool
    host_ok: bool
    power_ready: bool
    sleep_disabled: bool
    autorestart_enabled: bool
    filevault_enabled: bool
    auto_login_enabled: bool
    login_dependency_ready: bool
    ethernet_default: bool
    cameras_ready: bool
    camera_ready_count: int
    volume_ready: bool
    service_loaded: bool
    service_working_directory_ok: bool
    runtime_head_ok: bool
    lifecycle_present: bool
    storage_runway_state: str
    blockers: tuple[str, ...]

    def to_public_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        return payload


def _run(args: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), capture_output=True, text=True, timeout=timeout, check=False
    )


def _command(runner: CommandRunner, args: Sequence[str]) -> tuple[int, str]:
    try:
        result = runner(args, 10.0)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return result.returncode, result.stdout


def _power_value(output: str, key: str) -> int | None:
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s+(\d+)\s*$", output)
    return int(match.group(1)) if match else None


def collect_field_readiness(
    *,
    expected_host: str,
    expected_repo: Path,
    expected_head: str,
    configs: Sequence[CameraConfig],
    volume_status: VolumeStatus,
    lifecycle_present: bool,
    storage_runway_state: str,
    runner: CommandRunner = _run,
    camera_probe: Callable[[CameraConfig], CameraProbeStatus] = probe_camera,
) -> FieldReadinessResult:
    _, host_output = _command(runner, ["hostname"])
    host_ok = host_output.strip() == expected_host
    _, power = _command(runner, ["pmset", "-g", "custom"])
    sleep_disabled = _power_value(power, "sleep") == 0
    autorestart_enabled = _power_value(power, "autorestart") == 1
    power_ready = sleep_disabled and autorestart_enabled
    _, filevault = _command(runner, ["fdesetup", "status"])
    filevault_enabled = "is On" in filevault
    login_code, login = _command(
        runner, ["defaults", "read", "/Library/Preferences/com.apple.loginwindow", "autoLoginUser"]
    )
    auto_login_enabled = login_code == 0 and bool(login.strip())
    login_dependency_ready = auto_login_enabled and not filevault_enabled
    _, route = _command(runner, ["route", "-n", "get", "default"])
    _, hardware = _command(runner, ["networksetup", "-listallhardwareports"])
    interface_match = re.search(r"(?m)^\s*interface:\s*(\S+)", route)
    ethernet_match = re.search(
        r"Hardware Port: Ethernet\s+Device:\s*(\S+)", hardware
    )
    ethernet_default = bool(
        interface_match and ethernet_match
        and interface_match.group(1) == ethernet_match.group(1)
    )
    camera_results = [camera_probe(config) for config in configs]
    camera_ready_count = sum(item.tcp_554 and item.rtsp for item in camera_results)
    cameras_ready = camera_ready_count == len(configs) == 3
    _, runtime_head = _command(runner, ["git", "-C", str(expected_repo), "rev-parse", "HEAD"])
    runtime_head_ok = runtime_head.strip() == expected_head
    service_code, service = _command(
        runner, ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"]
    )
    service_loaded = service_code == 0 and "state = running" in service
    service_working_directory_ok = (
        service_loaded and f"working directory = {expected_repo}" in service
    )
    blockers: list[str] = []
    checks = (
        (host_ok, "host_mismatch"),
        (sleep_disabled, "sleep_enabled"),
        (autorestart_enabled, "autorestart_disabled"),
        (login_dependency_ready, "login_required_after_power_loss"),
        (ethernet_default, "ethernet_not_default"),
        (cameras_ready, "camera_probe_failed"),
        (volume_status.ready, "volume_not_ready"),
        (service_loaded, "service_not_loaded"),
        (service_working_directory_ok, "service_working_directory_mismatch"),
        (runtime_head_ok, "runtime_head_mismatch"),
        (lifecycle_present, "lifecycle_missing"),
        (storage_runway_state not in {"low", "unknown"}, "storage_runway_low"),
    )
    blockers.extend(reason for passed, reason in checks if not passed)
    return FieldReadinessResult(
        ready=not blockers,
        host_ok=host_ok,
        power_ready=power_ready,
        sleep_disabled=sleep_disabled,
        autorestart_enabled=autorestart_enabled,
        filevault_enabled=filevault_enabled,
        auto_login_enabled=auto_login_enabled,
        login_dependency_ready=login_dependency_ready,
        ethernet_default=ethernet_default,
        cameras_ready=cameras_ready,
        camera_ready_count=camera_ready_count,
        volume_ready=volume_status.ready,
        service_loaded=service_loaded,
        service_working_directory_ok=service_working_directory_ok,
        runtime_head_ok=runtime_head_ok,
        lifecycle_present=lifecycle_present,
        storage_runway_state=storage_runway_state,
        blockers=tuple(blockers),
    )


def read_state_evidence(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "unknown"
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as connection:
            lifecycle_count = connection.execute(
                "SELECT count(*) FROM manager_event WHERE kind IN "
                "('capture_scheduled','capture_started','capture_stopped','raw_uploaded',"
                "'finalize_started','finalize_completed','db_synced','manager_started','manager_stopped')"
            ).fetchone()[0]
            row = connection.execute(
                "SELECT payload FROM manager_event WHERE kind='storage_runway' ORDER BY id DESC LIMIT 1"
            ).fetchone()
    except (OSError, sqlite3.Error, TypeError):
        return False, "unknown"
    state = "unknown"
    if row is not None:
        try:
            state = str(json.loads(row[0]).get("state", "unknown"))
        except (TypeError, json.JSONDecodeError):
            state = "unknown"
    return bool(lifecycle_count), state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--volume-name", default="RAP-C500G")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    load_dotenv(REPO_ROOT / ".env")
    configs = load_camera_configs(os.environ)
    lifecycle, runway = read_state_evidence(args.state_path)
    result = collect_field_readiness(
        expected_host=args.expected_host,
        expected_repo=args.repo,
        expected_head=args.expected_head,
        configs=configs,
        volume_status=validate_selected_volume(args.volume_name),
        lifecycle_present=lifecycle,
        storage_runway_state=runway,
    )
    payload = result.to_public_dict()
    print(json.dumps(payload, sort_keys=True) if args.json else "\n".join(payload["blockers"]))
    return 0 if result.ready else 3


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from backend.rap_c500g_capture import CameraConfig
from backend.rap_c500g_manager_probe import CameraProbeStatus, VolumeStatus
from scripts.audit_rap_c500g_field_readiness import collect_field_readiness


CONFIGS = tuple(
    CameraConfig(f"cam0{i}", f"192.168.50.{22+i}", "user", "password")
    for i in range(1, 4)
)


class Runner:
    def __init__(self, *, degraded: bool = False) -> None:
        self.degraded = degraded
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args, timeout: float):
        del timeout
        key = tuple(args)
        self.calls.append(key)
        command = " ".join(args)
        if args[0] == "hostname":
            stdout = "wrong-host\n" if self.degraded else "baeg-endeuui-Macmini.local\n"
        elif "pmset" in command:
            stdout = " sleep 1\n autorestart 0\n" if self.degraded else " sleep 0\n autorestart 1\n"
        elif "fdesetup" in command:
            stdout = "FileVault is On.\n"
        elif "loginwindow" in command:
            return subprocess.CompletedProcess(args, 1, "", "password=must-not-leak")
        elif args[:4] == ["route", "-n", "get", "default"]:
            stdout = "interface: en1\n" if self.degraded else "interface: en0\n"
        elif "networksetup" in command:
            stdout = "Hardware Port: Ethernet\nDevice: en0\nHardware Port: Wi-Fi\nDevice: en1\n"
        elif args[0] == "git":
            stdout = "bad\n" if self.degraded else "a" * 40 + "\n"
        elif args[0] == "launchctl":
            if self.degraded:
                return subprocess.CompletedProcess(args, 1, "", "not loaded secret")
            stdout = "state = running\nworking directory = /safe/repo\n"
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0, stdout, "secret diagnostic")


def probe(config: CameraConfig) -> CameraProbeStatus:
    return CameraProbeStatus(config.camera_key, config.ip, True, True, "now", None)


def volume() -> VolumeStatus:
    return VolumeStatus("RAP-C500G", True, None, True, 100, 50, "/safe/mount")


def test_readiness_collects_safe_aggregate_without_mutation(tmp_path: Path) -> None:
    runner = Runner()
    result = collect_field_readiness(
        expected_host="baeg-endeuui-Macmini.local", expected_repo=Path("/safe/repo"),
        expected_head="a" * 40, configs=CONFIGS, volume_status=volume(),
        lifecycle_present=True, storage_runway_state="ok", runner=runner,
        camera_probe=probe,
    )

    public = result.to_public_dict()
    assert result.ready is False
    assert result.power_ready is True
    assert result.ethernet_default is True
    assert result.cameras_ready is True
    assert result.login_dependency_ready is False
    assert public["blockers"] == ["login_required_after_power_loss"]
    encoded = json.dumps(public)
    assert "must-not-leak" not in encoded
    assert "password" not in encoded
    assert "/safe/repo" not in encoded


def test_readiness_reports_each_actionable_runtime_blocker() -> None:
    runner = Runner(degraded=True)
    result = collect_field_readiness(
        expected_host="baeg-endeuui-Macmini.local", expected_repo=Path("/safe/repo"),
        expected_head="a" * 40, configs=CONFIGS,
        volume_status=VolumeStatus("RAP-C500G", False, "volume_missing", False, 0, 0, None),
        lifecycle_present=False, storage_runway_state="low", runner=runner,
        camera_probe=probe,
    )

    assert result.ready is False
    assert set(result.blockers) >= {
        "host_mismatch", "sleep_enabled", "autorestart_disabled",
        "login_required_after_power_loss", "ethernet_not_default",
        "volume_not_ready", "service_not_loaded", "runtime_head_mismatch",
        "lifecycle_missing", "storage_runway_low",
    }
    assert all("secret" not in value for value in result.blockers)

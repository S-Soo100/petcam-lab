from __future__ import annotations

import copy
import hashlib
import json
import plistlib
import sqlite3
from pathlib import Path
from typing import Sequence

import pytest

from scripts.verify_research_runtime_reboot import (
    RebootVerificationError,
    compare_immutable_services,
    parse_boot_sec,
    verify_production_baseline,
    verify_reboot_marker,
)


def test_parse_boot_sec_selects_sec_instead_of_usec() -> None:
    output = "{ sec = 1785233472, usec = 925537 } Tue Jul 28 19:11:12 2026"

    assert parse_boot_sec(output) == 1785233472


def test_immutable_baseline_ignores_launchd_volatile_state() -> None:
    expected = [
        {
            "label": "com.petcam.example",
            "plist_sha256": "a" * 64,
            "working_directory": "/Users/baek-end/example",
            "loaded": False,
            "runs": 0,
            "last_exit_code": None,
        }
    ]
    actual = copy.deepcopy(expected)
    actual[0].update(loaded=True, runs=3, last_exit_code="0")

    compare_immutable_services(expected, actual)


@pytest.mark.parametrize(
    ("field", "new_value"),
    [
        ("plist_sha256", "b" * 64),
        ("working_directory", "/Users/baek-end/drifted"),
    ],
)
def test_immutable_baseline_rejects_real_drift(
    field: str,
    new_value: str,
) -> None:
    expected = [
        {
            "label": "com.petcam.example",
            "plist_sha256": "a" * 64,
            "working_directory": "/Users/baek-end/example",
            "loaded": False,
            "runs": 0,
            "last_exit_code": None,
        }
    ]
    actual = copy.deepcopy(expected)
    actual[0][field] = new_value

    with pytest.raises(RebootVerificationError, match=field):
        compare_immutable_services(expected, actual)


def _write_plist(path: Path, working_directory: str) -> str:
    path.write_bytes(
        plistlib.dumps(
            {
                "Label": path.stem,
                "WorkingDirectory": working_directory,
                "ProgramArguments": ["/usr/bin/true"],
            }
        )
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_verify_production_baseline_reads_only_immutable_plist_state(
    tmp_path: Path,
) -> None:
    launch_agents = tmp_path / "LaunchAgents"
    launch_agents.mkdir()
    label = "com.petcam.example"
    working_directory = "/Users/baek-end/example"
    plist_hash = _write_plist(
        launch_agents / f"{label}.plist",
        working_directory,
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "services": [
                    {
                        "label": label,
                        "plist_sha256": plist_hash,
                        "working_directory": working_directory,
                        "loaded": False,
                        "runs": 0,
                        "last_exit_code": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert verify_production_baseline(baseline, launch_agents) == 1


def test_verify_production_baseline_rejects_plist_hash_drift(
    tmp_path: Path,
) -> None:
    launch_agents = tmp_path / "LaunchAgents"
    launch_agents.mkdir()
    label = "com.petcam.example"
    plist = launch_agents / f"{label}.plist"
    _write_plist(plist, "/Users/baek-end/example")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "services": [
                    {
                        "label": label,
                        "plist_sha256": "a" * 64,
                        "working_directory": "/Users/baek-end/example",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RebootVerificationError, match="plist_sha256"):
        verify_production_baseline(baseline, launch_agents)


def test_verify_production_baseline_rejects_expected_absent_plist_reappearance(
    tmp_path: Path,
) -> None:
    launch_agents = tmp_path / "LaunchAgents"
    launch_agents.mkdir()
    retired_label = "com.petcam.one-shot-finalizer"
    baseline = tmp_path / "production-baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "services": [],
                "expected_absent_labels": [retired_label],
            }
        ),
        encoding="utf-8",
    )

    assert verify_production_baseline(baseline, launch_agents) == 0

    _write_plist(
        launch_agents / f"{retired_label}.plist",
        "/Users/baek-end/production",
    )
    with pytest.raises(RebootVerificationError, match="expected_absent"):
        verify_production_baseline(baseline, launch_agents)


def test_verify_reboot_marker_uses_read_only_immutable_contract(
    tmp_path: Path,
) -> None:
    runtime_checkout = tmp_path / "runtime-checkout"
    runtime_checkout.mkdir()
    runtime_root = tmp_path / "runtime-root"
    for directory in ("events", "jobs", "logs"):
        (runtime_root / directory).mkdir(parents=True, exist_ok=True)
    ledger = sqlite3.connect(runtime_root / "ledger.sqlite3")
    ledger.execute(
        """
        create table jobs (
            job_id text primary key,
            state text not null,
            provider_calls integer not null,
            cost_krw integer not null
        )
        """
    )
    ledger.execute(
        "insert into jobs values ('synthetic', 'succeeded', 0, 0)"
    )
    ledger.commit()
    ledger.close()

    runtime_sha = "7" * 40
    launch_agents = tmp_path / "LaunchAgents"
    launch_agents.mkdir()
    production_label = "com.petcam.production"
    production_working_directory = "/Users/baek-end/production"
    production_hash = _write_plist(
        launch_agents / f"{production_label}.plist",
        production_working_directory,
    )
    baseline = tmp_path / "production-baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "services": [
                    {
                        "label": production_label,
                        "plist_sha256": production_hash,
                        "working_directory": production_working_directory,
                        "loaded": False,
                        "last_exit_code": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    target_label = "com.petcam.research-runtime"
    target_plist = launch_agents / f"{target_label}.plist"
    target_hash = _write_plist(target_plist, str(runtime_checkout))
    marker = tmp_path / "reboot-marker.json"
    marker.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "marker": "R1_RUNTIME_P3_REBOOT_PENDING",
                "host": "test-host.local",
                "user": "test-user",
                "runtime_sha": runtime_sha,
                "runtime_checkout": str(runtime_checkout),
                "runtime_root": str(runtime_root),
                "legacy_root": str(tmp_path / "legacy-root"),
                "runtime_label": target_label,
                "target_plist": str(target_plist),
                "target_plist_sha256": target_hash,
                "launch_agents_dir": str(launch_agents),
                "pre_reboot_boot_sec": 100,
                "production_baseline_artifact": str(baseline),
                "production_baseline_sha256": hashlib.sha256(
                    baseline.read_bytes()
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    def fake_run(args: Sequence[str]) -> str:
        command = tuple(args)
        if command == ("/bin/hostname",):
            return "test-host.local\n"
        if command == ("/usr/bin/id", "-un"):
            return "test-user\n"
        if command == ("/usr/bin/id", "-u"):
            return "501\n"
        if command == ("/usr/sbin/sysctl", "-n", "kern.boottime"):
            return "{ sec = 200, usec = 999999 } now\n"
        if command == (
            "/usr/bin/git",
            "-C",
            str(runtime_checkout),
            "rev-parse",
            "HEAD",
        ):
            return f"{runtime_sha}\n"
        if command == (
            "/usr/bin/git",
            "-C",
            str(runtime_checkout),
            "status",
            "--porcelain",
            "--untracked-files=all",
        ):
            return ""
        if command == ("/bin/launchctl", "print", f"gui/501/{target_label}"):
            return "\n".join(
                (
                    f"working directory = {runtime_checkout}",
                    f"RESEARCH_RUNTIME_ROOT => {runtime_root}",
                    f"RESEARCH_EXPECTED_HEAD => {runtime_sha}",
                    "last exit code = 0",
                )
            )
        if command == (
            str(runtime_checkout / "scripts/researchctl"),
            "--root",
            str(runtime_root),
            "status",
            "--json",
        ):
            return (
                '{"schema_version":1,"jobs":'
                '[{"job_id":"synthetic","state":"succeeded"}]}'
            )
        raise AssertionError(f"unexpected command: {command!r}")

    result = verify_reboot_marker(marker, run_command=fake_run)

    assert result == {
        "boot_sec": 200,
        "jobs": 1,
        "production_services": 1,
    }

from __future__ import annotations

import hashlib
import json
import plistlib
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.verify_research_runtime_attempt import (
    AttemptVerificationError,
    verify_attempt,
)


def _write_production_baseline(tmp_path: Path) -> tuple[Path, Path]:
    launch_agents = tmp_path / "LaunchAgents"
    launch_agents.mkdir()
    label = "com.petcam.production"
    plist = launch_agents / f"{label}.plist"
    plist.write_bytes(
        plistlib.dumps(
            {
                "Label": label,
                "WorkingDirectory": "/Users/baek-end/production",
                "ProgramArguments": ["/usr/bin/true"],
            }
        )
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "services": [
                    {
                        "label": label,
                        "plist_sha256": hashlib.sha256(
                            plist.read_bytes()
                        ).hexdigest(),
                        "working_directory": "/Users/baek-end/production",
                    }
                ],
                "expected_absent_labels": [
                    "com.petcam.one-shot-finalizer"
                ],
            }
        ),
        encoding="utf-8",
    )
    return baseline, launch_agents


def _write_runtime_attempt(tmp_path: Path) -> Path:
    root = tmp_path / "runtime"
    (root / "events").mkdir(parents=True)
    (root / "jobs/manual/attempt-1").mkdir(parents=True)
    (root / "jobs/recovery/attempt-2").mkdir(parents=True)
    (root / "logs").mkdir()
    (root / "jobs/manual/attempt-1/result.json").write_text("{}\n")
    (root / "jobs/recovery/attempt-2/result.json").write_text("{}\n")
    events = [
        {"job_id": "manual", "state": "queued"},
        {
            "attempt": 1,
            "job_id": "manual",
            "lease_epoch": 1,
            "state": "running",
        },
        {"job_id": "manual", "lease_epoch": 1, "state": "succeeded"},
        {"job_id": "recovery", "state": "queued"},
        {
            "attempt": 1,
            "job_id": "recovery",
            "lease_epoch": 1,
            "state": "running",
        },
        {
            "event": "recovery_queued",
            "job_id": "recovery",
            "previous_lease_epoch": 1,
        },
        {
            "attempt": 2,
            "job_id": "recovery",
            "lease_epoch": 3,
            "state": "running",
        },
        {"job_id": "recovery", "lease_epoch": 3, "state": "succeeded"},
    ]
    (root / "events/events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    database = sqlite3.connect(root / "ledger.sqlite3")
    database.execute(
        """
        create table jobs (
            job_id text primary key,
            state text not null,
            attempt integer not null,
            lease_epoch integer not null,
            provider_calls integer not null,
            cost_krw integer not null,
            exit_code integer,
            error_code text
        )
        """
    )
    database.executemany(
        "insert into jobs values (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("manual", "succeeded", 1, 1, 0, 0, 0, None),
            ("recovery", "succeeded", 2, 3, 0, 0, 0, None),
        ],
    )
    database.commit()
    database.close()
    return root


def test_verify_attempt_accepts_actual_runtime_event_schema(
    tmp_path: Path,
) -> None:
    root = _write_runtime_attempt(tmp_path)
    baseline, launch_agents = _write_production_baseline(tmp_path)

    assert verify_attempt(
        runtime_root=root,
        baseline_path=baseline,
        launch_agents_dir=launch_agents,
        manual_job_id="manual",
        recovery_job_id="recovery",
    ) == {
        "jobs": 2,
        "production_services": 1,
        "recovery_events": 5,
    }


def test_verify_attempt_rejects_duplicate_recovery_success(
    tmp_path: Path,
) -> None:
    root = _write_runtime_attempt(tmp_path)
    baseline, launch_agents = _write_production_baseline(tmp_path)
    events = root / "events/events.jsonl"
    with events.open("a", encoding="utf-8") as file:
        file.write(
            json.dumps(
                {
                    "job_id": "recovery",
                    "lease_epoch": 3,
                    "state": "succeeded",
                }
            )
            + "\n"
        )

    with pytest.raises(
        AttemptVerificationError,
        match="recovery_event_sequence",
    ):
        verify_attempt(
            runtime_root=root,
            baseline_path=baseline,
            launch_agents_dir=launch_agents,
            manual_job_id="manual",
            recovery_job_id="recovery",
        )


def test_attempt_verifier_supports_direct_script_entrypoint() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_research_runtime_attempt.py",
            "--help",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

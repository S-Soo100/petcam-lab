#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.verify_research_runtime_reboot import (
    RebootVerificationError,
    _verify_runtime_residue,
    verify_production_baseline,
)


class AttemptVerificationError(RuntimeError):
    pass


def _read_events(path: Path, job_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as file:
            for line in file:
                payload = json.loads(line)
                if (
                    isinstance(payload, dict)
                    and payload.get("job_id") == job_id
                ):
                    events.append(payload)
    except (OSError, json.JSONDecodeError) as exc:
        raise AttemptVerificationError("events_unreadable") from exc
    return events


def _recovery_event_tuple(event: dict[str, Any]) -> tuple[object, ...]:
    if event.get("event") == "recovery_queued":
        return ("recovery_queued", event.get("previous_lease_epoch"))
    state = event.get("state")
    if state == "queued":
        return ("queued",)
    if state == "running":
        return ("running", event.get("attempt"), event.get("lease_epoch"))
    if state == "succeeded":
        return ("succeeded", event.get("lease_epoch"))
    return ("unexpected",)


def verify_attempt(
    *,
    runtime_root: Path,
    baseline_path: Path,
    launch_agents_dir: Path,
    manual_job_id: str,
    recovery_job_id: str,
) -> dict[str, int]:
    ledger_path = runtime_root / "ledger.sqlite3"
    uri = f"{ledger_path.resolve().as_uri()}?mode=rw"
    try:
        database = sqlite3.connect(uri, uri=True)
        # Cross-runtime WAL readers may need to create sidecars before reading.
        database.execute("PRAGMA query_only=ON")
        manual = database.execute(
            """
            select state, attempt, lease_epoch, provider_calls,
                   cost_krw, exit_code, error_code
            from jobs
            where job_id = ?
            """,
            (manual_job_id,),
        ).fetchone()
        recovery = database.execute(
            """
            select state, attempt, lease_epoch, provider_calls,
                   cost_krw, exit_code, error_code
            from jobs
            where job_id = ?
            """,
            (recovery_job_id,),
        ).fetchone()
        jobs, provider_calls, cost_krw = database.execute(
            """
            select count(*), coalesce(sum(provider_calls), 0),
                   coalesce(sum(cost_krw), 0)
            from jobs
            """
        ).fetchone()
    except sqlite3.Error as exc:
        raise AttemptVerificationError("ledger_unreadable") from exc
    finally:
        if "database" in locals():
            database.close()

    if manual != ("succeeded", 1, 1, 0, 0, 0, None):
        raise AttemptVerificationError("manual_job")
    if recovery != ("succeeded", 2, 3, 0, 0, 0, None):
        raise AttemptVerificationError("recovery_job")
    if provider_calls != 0 or cost_krw != 0:
        raise AttemptVerificationError("provider_cost_nonzero")

    recovery_events = _read_events(
        runtime_root / "events/events.jsonl",
        recovery_job_id,
    )
    sequence = [_recovery_event_tuple(event) for event in recovery_events]
    expected_sequence = [
        ("queued",),
        ("running", 1, 1),
        ("recovery_queued", 1),
        ("running", 2, 3),
        ("succeeded", 3),
    ]
    if sequence != expected_sequence:
        raise AttemptVerificationError("recovery_event_sequence")

    if not (
        runtime_root
        / "jobs"
        / manual_job_id
        / "attempt-1"
        / "result.json"
    ).is_file():
        raise AttemptVerificationError("manual_result")
    if (
        runtime_root
        / "jobs"
        / recovery_job_id
        / "attempt-1"
        / "result.json"
    ).exists():
        raise AttemptVerificationError("recovery_attempt_1_result")
    if not (
        runtime_root
        / "jobs"
        / recovery_job_id
        / "attempt-2"
        / "result.json"
    ).is_file():
        raise AttemptVerificationError("recovery_attempt_2_result")

    try:
        _verify_runtime_residue(runtime_root)
        production_services = verify_production_baseline(
            baseline_path,
            launch_agents_dir,
        )
    except RebootVerificationError as exc:
        raise AttemptVerificationError(str(exc)) from exc

    return {
        "jobs": jobs,
        "production_services": production_services,
        "recovery_events": len(recovery_events),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--launch-agents-dir", type=Path, required=True)
    parser.add_argument("--manual-job-id", required=True)
    parser.add_argument("--recovery-job-id", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_attempt(
            runtime_root=args.runtime_root,
            baseline_path=args.baseline,
            launch_agents_dir=args.launch_agents_dir,
            manual_job_id=args.manual_job_id,
            recovery_job_id=args.recovery_job_id,
        )
    except AttemptVerificationError as exc:
        print(f"R1_ATTEMPT_VERIFY_FAILED reason={exc}", file=sys.stderr)
        return 1
    print(
        "R1_ATTEMPT_LEDGER_OK "
        f"jobs={result['jobs']} recovery_events={result['recovery_events']}"
    )
    print(
        "R1_ATTEMPT_PRODUCTION_BASELINE_OK "
        f"services={result['production_services']}"
    )
    print("R1_ATTEMPT_RESIDUE_ZERO")
    print("R1_ATTEMPT_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

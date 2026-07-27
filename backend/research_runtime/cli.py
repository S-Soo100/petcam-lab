from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.research_runtime.contracts import RuntimeExit
from backend.research_runtime.job_spec import JobSpecError, parse_job_spec
from backend.research_runtime.ledger import Ledger
from backend.research_runtime.paths import initialize_runtime_paths
from backend.research_runtime.redaction import redact_text


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="researchctl")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(
            os.environ.get(
                "RESEARCH_RUNTIME_ROOT",
                str(Path.home() / ".petcam-research-runtime"),
            )
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    submit = commands.add_parser("submit")
    submit.add_argument("--spec", required=True, type=Path)
    status = commands.add_parser("status")
    status.add_argument("--json", action="store_true")
    show = commands.add_parser("show")
    show.add_argument("job_id")
    show.add_argument("--json", action="store_true")
    tail = commands.add_parser("tail")
    tail.add_argument("job_id")
    tail.add_argument("--lines", type=int, default=100)
    cancel = commands.add_parser("cancel")
    cancel.add_argument("job_id")
    return parser


def _public_job(row) -> dict[str, object]:
    return {
        "attempt": row.attempt,
        "cancel_requested": row.cancel_requested_at is not None,
        "job_id": row.job_id,
        "state": row.state.value,
    }


def _json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def main(
    argv: list[str] | None = None,
    *,
    now: datetime | None = None,
) -> int:
    args = _parser().parse_args(argv)
    current = now or datetime.now(timezone.utc)
    try:
        paths = initialize_runtime_paths(args.root)
        ledger = Ledger.open(paths)
    except (OSError, sqlite3.DatabaseError, RuntimeError):
        _json({"error": "ledger_unavailable", "schema_version": 1})
        return RuntimeExit.LEDGER_FAILURE
    try:
        if args.command == "submit":
            try:
                spec = parse_job_spec(args.spec, now=current)
                inserted = ledger.enqueue(spec, now=current)
            except (JobSpecError, ValueError):
                _json({"error": "invalid_job_spec", "schema_version": 1})
                return RuntimeExit.INVALID_INPUT
            _json(
                {
                    "inserted": inserted,
                    "job_id": spec.job_id,
                    "schema_version": 1,
                }
            )
            return RuntimeExit.OK
        if args.command == "status":
            jobs = [_public_job(row) for row in ledger.list_jobs()]
            payload = {"jobs": jobs, "schema_version": 1}
            if args.json:
                _json(payload)
            else:
                for job in jobs:
                    print(f"{job['job_id']}\t{job['state']}\tattempt={job['attempt']}")
            return RuntimeExit.OK
        row = ledger.get(args.job_id)
        if row is None:
            _json({"error": "job_not_found", "schema_version": 1})
            return RuntimeExit.JOB_NOT_FOUND
        if args.command == "show":
            payload = {"job": _public_job(row), "schema_version": 1}
            if args.json:
                _json(payload)
            else:
                print(f"{row.job_id}\t{row.state.value}\tattempt={row.attempt}")
            return RuntimeExit.OK
        if args.command == "cancel":
            if not ledger.request_cancel(args.job_id, now=current):
                _json({"error": "cancel_not_allowed", "schema_version": 1})
                return RuntimeExit.INVALID_INPUT
            _json(
                {
                    "cancel_requested": True,
                    "job_id": args.job_id,
                    "schema_version": 1,
                }
            )
            return RuntimeExit.OK
        if args.command == "tail":
            if not 1 <= args.lines <= 1000:
                _json({"error": "invalid_lines", "schema_version": 1})
                return RuntimeExit.INVALID_INPUT
            log_path = (
                paths.jobs
                / args.job_id
                / f"attempt-{row.attempt}"
                / "child.log"
            )
            if not log_path.exists():
                return RuntimeExit.OK
            lines = log_path.read_text(encoding="utf-8").splitlines()[-args.lines :]
            print(redact_text("\n".join(lines), home=Path.home()))
            return RuntimeExit.OK
        return RuntimeExit.INVALID_INPUT
    except (OSError, UnicodeError):
        _json({"error": "safety_violation", "schema_version": 1})
        return RuntimeExit.SAFETY_VIOLATION
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())

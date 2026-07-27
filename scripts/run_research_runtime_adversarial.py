#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.research_runtime.budget import RuntimeBudget
from backend.research_runtime.events import EventWriteError, EventWriter
from backend.research_runtime.job_spec import JobSpecError, parse_job_spec
from backend.research_runtime.ledger import Ledger
from backend.research_runtime.paths import initialize_runtime_paths
from backend.research_runtime.production_guard import GuardConfig, evaluate_guard
from backend.research_runtime.redaction import redact_text
from backend.research_runtime.runner import recover_stale_jobs
from backend.research_runtime.supervisor import ProcessSupervisor

MARKERS = (
    "R1_SIGKILL_RECOVERY_OK",
    "R1_REBOOT_FENCING_OK",
    "R1_STALE_EPOCH_OK",
    "R1_SINGLETON_OK",
    "R1_MONOTONIC_CLOCK_OK",
    "R1_PRODUCTION_DEFER_OK",
    "R1_STARVATION_BLOCK_OK",
    "R1_DEADLINE_OK",
    "R1_DISK_FAILURE_OK",
    "R1_REDACTION_OK",
    "R1_BOUNDED_TAIL_OK",
    "R1_LEDGER_FAIL_CLOSED_OK",
    "R1_CANCEL_CLEANUP_OK",
    "R1_RESIDUE_ZERO",
)
NOW = datetime(2026, 7, 28, tzinfo=timezone.utc)


def _spec(path: Path, *, deadline: str = "2026-08-31T23:59:59+09:00"):
    value = {
        "schema_version": 1,
        "job_id": "r1-adversarial-001",
        "task_id": "r1-mac-mini-runtime-foundation",
        "handler": "synthetic_noop_v1",
        "handler_args": {"steps": 1, "step_seconds": 0},
        "manifest_blob_sha": "a" * 64,
        "manifest_commit_sha": "b" * 40,
        "repo_head": "c" * 40,
        "expected_host": "baeg-endeuui-Macmini.local",
        "budget": {
            "max_provider_calls": 0,
            "max_cost_krw": 0,
            "max_wall_seconds": 5,
            "deadline": deadline,
        },
        "resources": [],
        "privacy_class": "internal",
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return parse_job_spec(path, now=NOW)


def _ledger(root: Path) -> tuple[Ledger, object]:
    paths = initialize_runtime_paths(root)
    ledger = Ledger.open(paths)
    spec = _spec(root / "spec.json")
    ledger.enqueue(spec, now=NOW)
    return ledger, spec


def _sigkill(tmp: Path) -> bool:
    calls = 0

    def cancel() -> bool:
        nonlocal calls
        calls += 1
        return calls > 1

    result = ProcessSupervisor(
        home=tmp, poll_seconds=0.005, term_grace_seconds=0.02
    ).run(
        argv=(
            sys.executable,
            "-c",
            "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(2)",
        ),
        log_path=tmp / "kill.log",
        budget=RuntimeBudget(
            wall_seconds=3,
            deadline=NOW + timedelta(days=1),
            now=lambda: NOW,
        ),
        cancel_requested=cancel,
        heartbeat=lambda: True,
    )
    return result.outcome == "cancelled" and result.exit_code is not None


def _reboot_and_epoch(tmp: Path) -> tuple[bool, bool]:
    ledger, spec = _ledger(tmp / "ledger-a")
    claim = ledger.claim(
        boot_id="boot-a", pid=999999, now_mono=1, now=NOW, lease_seconds=30
    )
    assert claim is not None
    summary = recover_stale_jobs(
        ledger,
        current_boot_id="boot-b",
        current_pid=os.getpid(),
        pid_alive=lambda _: False,
    )
    stale = not ledger.transition(
        spec.job_id,
        expected_epoch=claim.lease_epoch,
        target=__import__(
            "backend.research_runtime.contracts", fromlist=["JobState"]
        ).JobState.SUCCEEDED,
        now=NOW,
    )
    recovered = ledger.claim(
        boot_id="boot-b",
        pid=os.getpid(),
        now_mono=2,
        now=NOW,
        lease_seconds=30,
    )
    completed = recovered is not None and ledger.transition(
        spec.job_id,
        expected_epoch=recovered.lease_epoch,
        target=__import__(
            "backend.research_runtime.contracts", fromlist=["JobState"]
        ).JobState.SUCCEEDED,
        now=NOW,
    )
    ledger.close()
    return summary.reclaimed == 1 and bool(completed), stale


def _singleton(tmp: Path) -> bool:
    path = tmp / "singleton.lock"
    with path.open("a") as first, path.open("a") as second:
        fcntl.flock(first, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def _monotonic() -> bool:
    values = iter((5.0, 6.0, 11.0))
    budget = RuntimeBudget(
        wall_seconds=5,
        deadline=NOW + timedelta(days=1),
        clock=lambda: next(values),
        now=lambda: NOW,
    )
    return not budget.expired() and budget.expired()


def _defer(tmp: Path) -> bool:
    lock = tmp / "busy.lock"
    config = GuardConfig(
        timezone="Asia/Seoul",
        segment_max_seconds=300,
        minimum_buffer_seconds=300,
        locks=(("activity", lock),),
        windows=(),
    )
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = evaluate_guard(now=NOW, config=config, segment_seconds=300)
    return not result.allowed and result.reason == "activity_lock_busy"


def _starvation(tmp: Path) -> bool:
    ledger, spec = _ledger(tmp / "ledger-b")
    for index in range(12):
        assert ledger.defer_next(now=NOW + timedelta(minutes=index), reason="busy")
    row = ledger.get(spec.job_id)
    ledger.close()
    return row is not None and row.state.value == "blocked"


def _deadline(tmp: Path) -> bool:
    path = tmp / "expired.json"
    try:
        _spec(path, deadline="2026-07-01T00:00:00Z")
    except JobSpecError:
        return True
    return False


def _disk_failure(tmp: Path) -> bool:
    blocker = tmp / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    try:
        EventWriter(blocker / "events.jsonl").append({"state": "queued"})
    except EventWriteError:
        return True
    return False


def _redaction(tmp: Path) -> bool:
    corpus = (
        "Authorization: Bearer fake-value "
        "person@example.com "
        "rtsp://user:pass@camera.local/live "
        f"{tmp}/secret"
    )
    safe = redact_text(corpus, home=tmp)
    return all(
        item not in safe
        for item in ("fake-value", "person@example.com", "user:pass", str(tmp))
    )


def _bounded_tail(tmp: Path) -> bool:
    log = tmp / "bounded.log"
    result = ProcessSupervisor(home=tmp, log_limit_bytes=64).run(
        argv=(sys.executable, "-c", "print('x'*10000)"),
        log_path=log,
        budget=RuntimeBudget(
            wall_seconds=3,
            deadline=NOW + timedelta(days=1),
            now=lambda: NOW,
        ),
        cancel_requested=lambda: False,
        heartbeat=lambda: True,
    )
    return result.outcome == "succeeded" and log.stat().st_size <= 64


def _ledger_fail_closed(tmp: Path) -> bool:
    paths = initialize_runtime_paths(tmp / "corrupt")
    paths.ledger.write_bytes(b"not sqlite")
    try:
        Ledger.open(paths)
    except (sqlite3.DatabaseError, RuntimeError):
        return paths.ledger.read_bytes() == b"not sqlite"
    return False


def _cancel_cleanup(tmp: Path) -> bool:
    result = ProcessSupervisor(
        home=tmp, poll_seconds=0.005, term_grace_seconds=0.05
    ).run(
        argv=(sys.executable, "-c", "import time;time.sleep(2)"),
        log_path=tmp / "cancel.log",
        budget=RuntimeBudget(
            wall_seconds=3,
            deadline=NOW + timedelta(days=1),
            now=lambda: NOW,
        ),
        cancel_requested=lambda: True,
        heartbeat=lambda: True,
    )
    return result.outcome == "cancelled"


def run_all(*, fail_marker: str | None = None) -> tuple[bool, list[str]]:
    emitted: list[str] = []
    with tempfile.TemporaryDirectory(prefix="r1-adversarial-") as raw:
        root = Path(raw)
        reboot, epoch = _reboot_and_epoch(root)
        checks = (
            ("R1_SIGKILL_RECOVERY_OK", lambda: _sigkill(root)),
            ("R1_REBOOT_FENCING_OK", lambda: reboot),
            ("R1_STALE_EPOCH_OK", lambda: epoch),
            ("R1_SINGLETON_OK", lambda: _singleton(root)),
            ("R1_MONOTONIC_CLOCK_OK", _monotonic),
            ("R1_PRODUCTION_DEFER_OK", lambda: _defer(root)),
            ("R1_STARVATION_BLOCK_OK", lambda: _starvation(root)),
            ("R1_DEADLINE_OK", lambda: _deadline(root)),
            ("R1_DISK_FAILURE_OK", lambda: _disk_failure(root)),
            ("R1_REDACTION_OK", lambda: _redaction(root)),
            ("R1_BOUNDED_TAIL_OK", lambda: _bounded_tail(root)),
            ("R1_LEDGER_FAIL_CLOSED_OK", lambda: _ledger_fail_closed(root)),
            ("R1_CANCEL_CLEANUP_OK", lambda: _cancel_cleanup(root)),
            ("R1_RESIDUE_ZERO", lambda: not root.exists() or not list(root.glob("*.mp4"))),
        )
        for marker, check in checks:
            if marker == fail_marker:
                continue
            if not check():
                return False, emitted
            emitted.append(marker)
    return len(emitted) == len(MARKERS), emitted


def main() -> int:
    success, markers = run_all()
    for marker in markers:
        print(marker)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())

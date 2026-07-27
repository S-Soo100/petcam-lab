from __future__ import annotations

import fcntl
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from backend.research_runtime.budget import RuntimeBudget
from backend.research_runtime.contracts import JobState, RuntimeExit
from backend.research_runtime.events import EventWriter
from backend.research_runtime.ledger import Ledger
from backend.research_runtime.paths import RuntimePaths, initialize_runtime_paths
from backend.research_runtime.production_guard import (
    GuardDecision,
    evaluate_guard,
    load_guard_config,
)
from backend.research_runtime.supervisor import ProcessSupervisor


@dataclass(frozen=True, slots=True)
class Preflight:
    expected_host: str
    expected_head: str
    hostname: Callable[[], str] = socket.gethostname
    git_state: Callable[[Path], tuple[str, bool]] | None = None


@dataclass(frozen=True, slots=True)
class RecoverySummary:
    reclaimed: int
    preserved: int
    blocked: int


def default_git_state(repo_root: Path) -> tuple[str, bool]:
    head = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=all"),
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return head, bool(status.strip())


def current_boot_id() -> str:
    result = subprocess.run(
        ("sysctl", "-n", "kern.boottime"),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def default_pid_alive(pid: int) -> bool | None:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return None


def recover_stale_jobs(
    ledger: Ledger,
    *,
    current_boot_id: str,
    current_pid: int,
    pid_alive: Callable[[int], bool | None] = default_pid_alive,
) -> RecoverySummary:
    reclaimed = preserved = blocked = 0
    for row in ledger.running_jobs():
        alive = pid_alive(row.pid) if row.pid is not None else None
        should_reclaim = row.boot_id != current_boot_id or alive is False
        if should_reclaim:
            outcome = ledger.reclaim(
                row.job_id,
                expected_epoch=row.lease_epoch,
                boot_id=current_boot_id,
                pid=current_pid,
            )
            if outcome == "reclaimed":
                reclaimed += 1
            elif outcome == "blocked":
                blocked += 1
        elif alive is True:
            preserved += 1
        else:
            blocked += 1
    return RecoverySummary(reclaimed, preserved, blocked)


def _preflight_ok(repo_root: Path, preflight: Preflight) -> bool:
    if preflight.hostname() != preflight.expected_host:
        return False
    try:
        git_state = preflight.git_state or default_git_state
        head, dirty = git_state(repo_root)
    except (OSError, subprocess.SubprocessError):
        return False
    return not dirty and head == preflight.expected_head


def run_once(
    *,
    paths: RuntimePaths,
    repo_root: Path,
    config_path: Path,
    preflight: Preflight,
    guard: Callable[..., GuardDecision] = evaluate_guard,
    boot_id: Callable[[], str] = current_boot_id,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    singleton_path: Path = Path("/tmp/petcam-research-runtime.lock"),
) -> RuntimeExit:
    # Preflight happens before opening or mutating the ledger.
    if not _preflight_ok(repo_root, preflight):
        return RuntimeExit.PREFLIGHT_MISMATCH
    singleton_path.parent.mkdir(parents=True, exist_ok=True)
    with singleton_path.open("a") as singleton:
        try:
            fcntl.flock(singleton, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return RuntimeExit.OK
        try:
            initialize_runtime_paths(paths.root)
            ledger = Ledger.open(paths, event_writer=EventWriter(paths.events))
        except Exception:
            return RuntimeExit.LEDGER_FAILURE
        try:
            active_boot = boot_id()
            recover_stale_jobs(
                ledger,
                current_boot_id=active_boot,
                current_pid=os.getpid(),
            )
            config = load_guard_config(config_path)
            decision = guard(
                now=now(),
                config=config,
                segment_seconds=config.segment_max_seconds,
            )
            if not decision.allowed:
                ledger.defer_next(now=now(), reason=decision.reason)
                return RuntimeExit.OK
            claim = ledger.claim(
                boot_id=active_boot,
                pid=os.getpid(),
                now_mono=time.monotonic(),
                now=now(),
                lease_seconds=30,
            )
            if claim is None:
                return RuntimeExit.OK
            job = ledger.execution_job(claim.job_id)
            if job is None:
                return RuntimeExit.LEDGER_FAILURE
            if (
                job.expected_host != preflight.expected_host
                or job.repo_head != preflight.expected_head
            ):
                ledger.transition(
                    job.job_id,
                    expected_epoch=job.lease_epoch,
                    target=JobState.BLOCKED,
                    now=now(),
                    error_code="job_preflight_mismatch",
                )
                return RuntimeExit.PREFLIGHT_MISMATCH
            attempt_dir = paths.jobs / job.job_id / f"attempt-{job.attempt}"
            attempt_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
            result_path = attempt_dir / "result.json"
            argv = (
                sys.executable,
                "-m",
                "backend.research_runtime.main",
                "execute-handler",
                job.handler,
                json.dumps(job.handler_args, sort_keys=True, separators=(",", ":")),
                str(result_path),
            )
            supervisor = ProcessSupervisor(home=Path.home())
            result = supervisor.run(
                argv=argv,
                log_path=attempt_dir / "child.log",
                budget=RuntimeBudget(
                    wall_seconds=job.max_wall_seconds,
                    deadline=job.deadline,
                ),
                cancel_requested=lambda: bool(
                    (ledger.get(job.job_id) or job).cancel_requested_at
                ),
                heartbeat=lambda: ledger.heartbeat(
                    job.job_id,
                    expected_epoch=job.lease_epoch,
                    now_mono=time.monotonic(),
                    now=now(),
                    lease_seconds=30,
                ),
            )
            if result.outcome == "succeeded" and result_path.exists():
                target = JobState.SUCCEEDED
                error_code = None
            elif result.outcome == "cancelled":
                target = JobState.CANCELLED
                error_code = "cancelled"
            else:
                target = JobState.FAILED
                error_code = result.outcome
            committed = ledger.transition(
                job.job_id,
                expected_epoch=job.lease_epoch,
                target=target,
                now=now(),
                exit_code=result.exit_code,
                error_code=error_code,
                result_dir=str(attempt_dir),
            )
            return RuntimeExit.OK if committed else RuntimeExit.LEDGER_FAILURE
        except Exception:
            return RuntimeExit.SAFETY_VIOLATION
        finally:
            ledger.close()
            fcntl.flock(singleton, fcntl.LOCK_UN)

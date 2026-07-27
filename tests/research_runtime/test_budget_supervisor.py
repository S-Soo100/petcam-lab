import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.research_runtime.budget import RuntimeBudget
from backend.research_runtime.supervisor import ProcessSupervisor


def test_budget_uses_monotonic_elapsed_time() -> None:
    values = iter([10.0, 12.0, 16.0])
    budget = RuntimeBudget(
        wall_seconds=5,
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        clock=lambda: next(values),
    )
    assert budget.expired() is False
    assert budget.expired() is True


def test_supervisor_redacts_output_and_reports_success(tmp_path: Path) -> None:
    supervisor = ProcessSupervisor(home=Path("/Users/baek"), log_limit_bytes=1024)
    result = supervisor.run(
        argv=(
            sys.executable,
            "-c",
            "print('Authorization: Bearer fake-token-value')",
        ),
        log_path=tmp_path / "child.log",
        budget=RuntimeBudget(
            wall_seconds=10,
            deadline=datetime.now(timezone.utc) + timedelta(minutes=1),
        ),
        cancel_requested=lambda: False,
        heartbeat=lambda: True,
    )
    assert result.outcome == "succeeded"
    text = (tmp_path / "child.log").read_text(encoding="utf-8")
    assert "fake-token-value" not in text


def test_supervisor_cancels_process_group(tmp_path: Path) -> None:
    calls = 0

    def cancel() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 2

    supervisor = ProcessSupervisor(home=tmp_path, poll_seconds=0.01, term_grace_seconds=0.05)
    result = supervisor.run(
        argv=(
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(5)",
        ),
        log_path=tmp_path / "cancel.log",
        budget=RuntimeBudget(
            wall_seconds=10,
            deadline=datetime.now(timezone.utc) + timedelta(minutes=1),
        ),
        cancel_requested=cancel,
        heartbeat=lambda: True,
    )
    assert result.outcome == "cancelled"
    assert result.termination_signal in {signal.SIGTERM, signal.SIGKILL}

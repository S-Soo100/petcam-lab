from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from backend.research_runtime.budget import RuntimeBudget
from backend.research_runtime.redaction import redact_text


@dataclass(frozen=True, slots=True)
class ProcessResult:
    outcome: str
    exit_code: int | None
    termination_signal: signal.Signals | None


class ProcessSupervisor:
    def __init__(
        self,
        *,
        home: Path,
        poll_seconds: float = 0.1,
        term_grace_seconds: float = 10.0,
        log_limit_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        self.home = home
        self.poll_seconds = poll_seconds
        self.term_grace_seconds = term_grace_seconds
        self.log_limit_bytes = log_limit_bytes

    def _terminate_group(self, process: subprocess.Popen[str]) -> signal.Signals:
        sent = signal.SIGTERM
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return sent
        try:
            process.wait(timeout=self.term_grace_seconds)
        except subprocess.TimeoutExpired:
            sent = signal.SIGKILL
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        return sent

    def run(
        self,
        *,
        argv: Sequence[str],
        log_path: Path,
        budget: RuntimeBudget,
        cancel_requested: Callable[[], bool],
        heartbeat: Callable[[], bool],
    ) -> ProcessResult:
        if not argv:
            raise ValueError("argv_required")
        log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        log_path.parent.chmod(0o700)
        process = subprocess.Popen(
            tuple(argv),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="strict",
            start_new_session=True,
            bufsize=1,
        )
        lines: queue.Queue[str | BaseException | None] = queue.Queue()

        def read_output() -> None:
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    lines.put(line)
            except BaseException as error:
                lines.put(error)
            finally:
                lines.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        written = 0
        reader_done = False
        outcome: str | None = None
        termination: signal.Signals | None = None
        with log_path.open("w", encoding="utf-8") as log:
            os.chmod(log_path, 0o600)

            def drain() -> None:
                nonlocal written, reader_done
                while True:
                    try:
                        item = lines.get_nowait()
                    except queue.Empty:
                        return
                    if item is None:
                        reader_done = True
                        continue
                    if isinstance(item, BaseException):
                        outcome = None
                        raise RuntimeError("child_output_decode_failed") from item
                    safe = redact_text(item, home=self.home)
                    encoded = safe.encode("utf-8")
                    remaining = max(0, self.log_limit_bytes - written)
                    if remaining:
                        chunk = encoded[:remaining]
                        log.write(chunk.decode("utf-8", errors="ignore"))
                        written += len(chunk)
                        log.flush()

            try:
                while process.poll() is None:
                    drain()
                    if cancel_requested():
                        outcome = "cancelled"
                        termination = self._terminate_group(process)
                        break
                    if budget.expired():
                        outcome = "budget_exceeded"
                        termination = self._terminate_group(process)
                        break
                    if not heartbeat():
                        outcome = "stale_lease"
                        termination = self._terminate_group(process)
                        break
                    time.sleep(self.poll_seconds)
                process.wait()
                reader.join(timeout=1.0)
                drain()
                os.fsync(log.fileno())
            except Exception:
                if process.poll() is None:
                    termination = self._terminate_group(process)
                raise
        if outcome is None:
            outcome = "succeeded" if process.returncode == 0 else "failed"
        return ProcessResult(
            outcome=outcome,
            exit_code=process.returncode,
            termination_signal=termination,
        )

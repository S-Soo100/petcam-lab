import json
from datetime import datetime, timezone
from pathlib import Path

from backend.research_runtime.contracts import JobState, RuntimeExit
from backend.research_runtime.events import EventWriter
from backend.research_runtime.job_spec import parse_job_spec
from backend.research_runtime.ledger import Ledger
from backend.research_runtime.paths import initialize_runtime_paths
from backend.research_runtime.production_guard import GuardDecision
from backend.research_runtime.runner import Preflight, recover_stale_jobs, run_once

from tests.research_runtime.test_job_spec import valid_spec, write_spec

NOW = datetime(2026, 7, 28, tzinfo=timezone.utc)


def setup_job(tmp_path: Path) -> tuple[object, Ledger]:
    paths = initialize_runtime_paths(tmp_path / "runtime")
    ledger = Ledger.open(paths, event_writer=EventWriter(paths.events))
    spec = parse_job_spec(write_spec(tmp_path, valid_spec()), now=NOW)
    ledger.enqueue(spec, now=NOW)
    return paths, ledger


def test_wrong_host_fails_before_ledger_mutation(tmp_path: Path) -> None:
    paths, ledger = setup_job(tmp_path)
    before = paths.ledger.read_bytes()
    result = run_once(
        paths=paths,
        repo_root=tmp_path,
        config_path=Path("config/research-runtime-quiet-windows.json"),
        preflight=Preflight(
            expected_host="mac-mini",
            expected_head="a" * 40,
            hostname=lambda: "wrong-host",
            git_state=lambda _: ("a" * 40, False),
        ),
        now=lambda: NOW,
    )
    assert result == RuntimeExit.PREFLIGHT_MISMATCH
    assert paths.ledger.read_bytes() == before
    assert ledger.get("r1-noop-001").state == JobState.QUEUED


def test_other_boot_reclaims_once(tmp_path: Path) -> None:
    _, ledger = setup_job(tmp_path)
    claim = ledger.claim(
        boot_id="boot-a",
        pid=100,
        now_mono=1.0,
        now=NOW,
        lease_seconds=30,
    )
    assert claim is not None
    summary = recover_stale_jobs(
        ledger,
        current_boot_id="boot-b",
        current_pid=101,
        pid_alive=lambda _: False,
    )
    assert summary.reclaimed == 1
    assert ledger.get(claim.job_id).attempt == 2
    assert ledger.get(claim.job_id).state == JobState.DEFERRED
    assert recover_stale_jobs(
        ledger,
        current_boot_id="boot-b",
        current_pid=101,
        pid_alive=lambda _: True,
    ).reclaimed == 0


def test_reboot_recovery_returns_job_to_execution(tmp_path: Path) -> None:
    _, ledger = setup_job(tmp_path)
    first = ledger.claim(
        boot_id="boot-a",
        pid=100,
        now_mono=1.0,
        now=NOW,
        lease_seconds=30,
    )
    assert first is not None
    assert recover_stale_jobs(
        ledger,
        current_boot_id="boot-b",
        current_pid=101,
        pid_alive=lambda _: False,
    ).reclaimed == 1
    recovered = ledger.claim(
        boot_id="boot-b",
        pid=101,
        now_mono=2.0,
        now=NOW,
        lease_seconds=30,
    )
    assert recovered is not None
    assert recovered.job_id == first.job_id
    assert recovered.attempt == 2
    assert ledger.transition(
        recovered.job_id,
        expected_epoch=recovered.lease_epoch,
        target=JobState.SUCCEEDED,
        now=NOW,
    )


def test_run_once_executes_only_registered_noop(tmp_path: Path) -> None:
    paths, ledger = setup_job(tmp_path)
    result = run_once(
        paths=paths,
        repo_root=tmp_path,
        config_path=Path("config/research-runtime-quiet-windows.json"),
        preflight=Preflight(
            expected_host="baeg-endeuui-Macmini.local",
            expected_head="c" * 40,
            hostname=lambda: "baeg-endeuui-Macmini.local",
            git_state=lambda _: ("c" * 40, False),
        ),
        guard=lambda **_: GuardDecision(True, "allowed"),
        boot_id=lambda: "boot-a",
        now=lambda: NOW,
        singleton_path=tmp_path / "runner.lock",
    )
    assert result == RuntimeExit.OK
    assert ledger.get("r1-noop-001").state == JobState.SUCCEEDED
    result_path = paths.jobs / "r1-noop-001" / "attempt-1" / "result.json"
    assert json.loads(result_path.read_text(encoding="utf-8"))["steps"] == 3

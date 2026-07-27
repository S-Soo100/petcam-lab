from datetime import datetime, timezone
from pathlib import Path

from backend.research_runtime.contracts import JobState
from backend.research_runtime.events import EventWriter
from backend.research_runtime.job_spec import parse_job_spec
from backend.research_runtime.ledger import Ledger
from backend.research_runtime.paths import initialize_runtime_paths

from tests.research_runtime.test_job_spec import valid_spec, write_spec


NOW = datetime(2026, 7, 28, tzinfo=timezone.utc)


def make_ledger(tmp_path: Path) -> tuple[Ledger, object]:
    paths = initialize_runtime_paths(tmp_path / "runtime")
    ledger = Ledger.open(paths, event_writer=EventWriter(paths.events))
    spec = parse_job_spec(write_spec(tmp_path, valid_spec()), now=NOW)
    return ledger, spec


def test_enqueue_is_idempotent_but_conflicting_spec_is_rejected(tmp_path: Path) -> None:
    ledger, spec = make_ledger(tmp_path)
    assert ledger.enqueue(spec, now=NOW) is True
    assert ledger.enqueue(spec, now=NOW) is False
    changed = valid_spec()
    changed["handler_args"]["steps"] = 4
    conflict = parse_job_spec(write_spec(tmp_path, changed), now=NOW)
    try:
        ledger.enqueue(conflict, now=NOW)
    except ValueError as error:
        assert str(error) == "job_spec_conflict"
    else:
        raise AssertionError("conflicting spec must fail")


def test_stale_epoch_cannot_commit_result(tmp_path: Path) -> None:
    ledger, spec = make_ledger(tmp_path)
    ledger.enqueue(spec, now=NOW)
    first = ledger.claim(
        boot_id="boot-a",
        pid=100,
        now_mono=1.0,
        now=NOW,
        lease_seconds=30,
    )
    assert first is not None
    assert ledger.reclaim(first.job_id, expected_epoch=first.lease_epoch, boot_id="boot-b", pid=101)
    assert (
        ledger.transition(
            first.job_id,
            expected_epoch=first.lease_epoch,
            target=JobState.SUCCEEDED,
            now=NOW,
        )
        is False
    )


def test_cancel_records_intent_without_overwriting_state(tmp_path: Path) -> None:
    ledger, spec = make_ledger(tmp_path)
    ledger.enqueue(spec, now=NOW)
    claim = ledger.claim(
        boot_id="boot-a",
        pid=100,
        now_mono=1.0,
        now=NOW,
        lease_seconds=30,
    )
    assert claim is not None
    assert ledger.request_cancel(spec.job_id, now=NOW)
    row = ledger.get(spec.job_id)
    assert row is not None
    assert row.state == JobState.RUNNING
    assert row.cancel_requested_at is not None


def test_event_log_is_append_only_and_private(tmp_path: Path) -> None:
    path = tmp_path / "events" / "events.jsonl"
    writer = EventWriter(path)
    writer.append({"job_id": "safe-id", "state": "queued"})
    writer.append({"job_id": "safe-id", "state": "running"})
    assert path.read_text(encoding="utf-8").count("\n") == 2
    assert path.stat().st_mode & 0o777 == 0o600

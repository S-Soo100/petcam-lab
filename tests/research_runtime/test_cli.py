import json
from datetime import datetime, timezone
from pathlib import Path

from backend.research_runtime.cli import main
from backend.research_runtime.job_spec import parse_job_spec
from backend.research_runtime.ledger import Ledger
from backend.research_runtime.paths import initialize_runtime_paths

from tests.research_runtime.test_job_spec import valid_spec, write_spec

NOW = datetime(2026, 7, 28, tzinfo=timezone.utc)


def test_submit_and_status_json_are_stable(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "runtime"
    spec_path = write_spec(tmp_path, valid_spec())
    assert main(["--root", str(root), "submit", "--spec", str(spec_path)], now=NOW) == 0
    capsys.readouterr()
    assert main(["--root", str(root), "status", "--json"], now=NOW) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "jobs": [
            {
                "attempt": 0,
                "cancel_requested": False,
                "job_id": "r1-noop-001",
                "state": "queued",
            }
        ],
        "schema_version": 1,
    }


def test_cancel_records_intent_without_changing_state(tmp_path: Path, capsys) -> None:
    root = tmp_path / "runtime"
    paths = initialize_runtime_paths(root)
    ledger = Ledger.open(paths)
    spec = parse_job_spec(write_spec(tmp_path, valid_spec()), now=NOW)
    ledger.enqueue(spec, now=NOW)
    claim = ledger.claim(
        boot_id="boot-a", pid=1, now_mono=1.0, now=NOW, lease_seconds=30
    )
    assert claim is not None
    ledger.close()
    assert main(["--root", str(root), "cancel", spec.job_id], now=NOW) == 0
    capsys.readouterr()
    ledger = Ledger.open(paths)
    assert ledger.get(spec.job_id).state.value == "running"
    assert ledger.get(spec.job_id).cancel_requested_at is not None
    ledger.close()


def test_missing_job_returns_exit_4(tmp_path: Path, capsys) -> None:
    assert (
        main(
            ["--root", str(tmp_path / "runtime"), "show", "missing", "--json"],
            now=NOW,
        )
        == 4
    )
    assert json.loads(capsys.readouterr().out)["error"] == "job_not_found"

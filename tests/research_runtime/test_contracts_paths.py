from pathlib import Path

from backend.research_runtime.contracts import JobState, RuntimeExit
from backend.research_runtime.paths import initialize_runtime_paths


def test_runtime_contract_is_versioned() -> None:
    assert JobState.values() == (
        "queued",
        "running",
        "deferred",
        "blocked",
        "succeeded",
        "failed",
        "cancelled",
    )
    assert RuntimeExit.OK == 0
    assert RuntimeExit.LEDGER_FAILURE == 5


def test_initialize_runtime_paths_uses_private_permissions(tmp_path: Path) -> None:
    paths = initialize_runtime_paths(tmp_path / "runtime")
    assert paths.root.stat().st_mode & 0o777 == 0o700
    assert paths.jobs.stat().st_mode & 0o777 == 0o700
    assert paths.events.parent.stat().st_mode & 0o777 == 0o700
    assert paths.ledger.parent == paths.root

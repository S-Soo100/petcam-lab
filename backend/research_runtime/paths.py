import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    root: Path
    ledger: Path
    events: Path
    jobs: Path


def initialize_runtime_paths(root: Path) -> RuntimePaths:
    os.umask(0o077)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    events_dir = root / "events"
    jobs = root / "jobs"
    for directory in (root, events_dir, jobs):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    return RuntimePaths(
        root=root,
        ledger=root / "ledger.sqlite3",
        events=events_dir / "events.jsonl",
        jobs=jobs,
    )

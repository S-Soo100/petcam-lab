from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping


class EventWriteError(OSError):
    pass


class EventWriter:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, event: Mapping[str, object]) -> None:
        line = json.dumps(
            dict(event),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.path.parent.chmod(0o700)
            with self.path.open("a", encoding="utf-8") as handle:
                os.chmod(self.path, 0o600)
                handle.write(line)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            raise EventWriteError("event_append_failed") from error

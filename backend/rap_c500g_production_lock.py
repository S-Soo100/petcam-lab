"""Legacy recorder와 manager가 공유하는 host-local production owner lock."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator


DEFAULT_PRODUCTION_LOCK = Path("/tmp/com.teraai.rap-c500g-production.lock")


class ProductionLockError(RuntimeError):
    pass


@contextmanager
def production_lock(
    path: Path = DEFAULT_PRODUCTION_LOCK,
) -> Iterator[IO[str]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ProductionLockError("another RAP production owner is active") from error
        handle.seek(0)
        handle.truncate()
        handle.write("locked\n")
        handle.flush()
        yield handle
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

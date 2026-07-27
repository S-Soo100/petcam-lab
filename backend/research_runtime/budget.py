from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable


@dataclass(slots=True)
class RuntimeBudget:
    wall_seconds: int
    deadline: datetime
    clock: Callable[[], float] = time.monotonic
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    _started: float = field(init=False)

    def __post_init__(self) -> None:
        if self.wall_seconds < 1:
            raise ValueError("invalid_wall_budget")
        if self.deadline.tzinfo is None or self.deadline.utcoffset() is None:
            raise ValueError("invalid_deadline")
        self._started = self.clock()

    def expired(self) -> bool:
        elapsed = self.clock() - self._started
        current = self.now().astimezone(timezone.utc)
        deadline = self.deadline.astimezone(timezone.utc)
        return elapsed >= self.wall_seconds or current >= deadline

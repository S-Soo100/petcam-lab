from enum import IntEnum, StrEnum


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DEFERRED = "deferred"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(item.value for item in cls)


class RuntimeExit(IntEnum):
    OK = 0
    INVALID_INPUT = 2
    PREFLIGHT_MISMATCH = 3
    JOB_NOT_FOUND = 4
    LEDGER_FAILURE = 5
    SAFETY_VIOLATION = 6

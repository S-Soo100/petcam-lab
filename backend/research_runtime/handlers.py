import time
from collections.abc import Callable, Mapping


JobHandler = Callable[[Mapping[str, int]], list[str]]


def synthetic_noop_v1(args: Mapping[str, int]) -> list[str]:
    steps = args.get("steps", 1)
    step_seconds = args.get("step_seconds", 0)
    if not isinstance(steps, int) or not 1 <= steps <= 100:
        raise ValueError("invalid_steps")
    if not isinstance(step_seconds, int) or not 0 <= step_seconds <= 60:
        raise ValueError("invalid_step_seconds")
    result: list[str] = []
    for index in range(steps):
        if step_seconds:
            time.sleep(step_seconds)
        result.append(f"step-{index + 1}")
    return result


_HANDLERS: dict[str, JobHandler] = {"synthetic_noop_v1": synthetic_noop_v1}


def handler_for(name: str) -> JobHandler:
    try:
        return _HANDLERS[name]
    except KeyError:
        raise ValueError("handler_not_allowed") from None

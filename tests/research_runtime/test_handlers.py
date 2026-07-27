from backend.research_runtime.handlers import handler_for


def test_handler_registry_contains_only_noop() -> None:
    handler = handler_for("synthetic_noop_v1")
    assert handler({"steps": 2, "step_seconds": 0}) == ["step-1", "step-2"]

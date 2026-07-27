from scripts.run_research_runtime_adversarial import MARKERS, run_all


def test_adversarial_harness_emits_all_markers() -> None:
    success, markers = run_all()
    assert success is True
    assert tuple(markers) == MARKERS


def test_failure_injection_suppresses_marker_and_fails() -> None:
    success, markers = run_all(fail_marker="R1_STALE_EPOCH_OK")
    assert success is False
    assert "R1_STALE_EPOCH_OK" not in markers

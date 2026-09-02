"""GME 관측 움직임 시간 runtime probe 실행기의 정적 계약."""

from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "run_gme_observed_moving_time_probe.py"
)


def test_runtime_probe_covers_apply_privilege_and_rollback() -> None:
    assert SCRIPT.exists(), f"runtime probe missing: {SCRIPT}"
    source = SCRIPT.read_text()
    for contract in (
        "2026-08-03_gecko_motion_engine_shadow.sql",
        "2026-09-03_gme_observed_moving_time_v1.sql",
        "GME_OBSERVED_MOVING_TIME_RUNTIME_OK",
        "GME_OBSERVED_MOVING_TIME_PRIVILEGE_OK",
        "GME_OBSERVED_MOVING_TIME_ROLLBACK_OK",
        "PROBE_RESIDUE=0",
        "drop function public.fn_get_gme_observed_moving_time_v1(uuid, text)",
    ):
        assert contract in source

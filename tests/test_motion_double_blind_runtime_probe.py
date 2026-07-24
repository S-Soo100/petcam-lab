"""동시 제출 실증 러너의 단위 테스트 — Docker 없이 명령·fail-closed·parser 만 검증.

실제 컨테이너 실증은 scripts/run_motion_double_blind_concurrency_probe.py 가 담당하고,
여기서는 순수 로직(운영 DB 접속 차단, peer_present 다중집합 판정)만 고정한다.
"""

import pytest

from scripts.run_motion_double_blind_concurrency_probe import (
    ProbeBlocked,
    parse_probe_rows,
    temp_database_name,
    validate_database_url,
    validate_temp_database_name,
)


def test_runner_refuses_non_local_database_url() -> None:
    with pytest.raises(ProbeBlocked, match="non_local_database_forbidden"):
        validate_database_url("postgresql://example.com/db")


def test_runner_allows_loopback_database_url() -> None:
    # 127.0.0.1/localhost 만 허용(운영 DB 접속 차단). 예외를 던지지 않아야 한다.
    validate_database_url("postgresql://postgres:pw@127.0.0.1:55432/postgres")
    validate_database_url("postgresql://postgres:pw@localhost:55432/postgres")


def test_runner_requires_both_concurrent_submissions() -> None:
    result = parse_probe_rows(
        [
            {"reviewer": "a", "peer_present": "f"},
            {"reviewer": "b", "peer_present": "f"},
        ]
    )
    assert result.verdict == "CONCURRENCY_FAILED"


def test_runner_accepts_exactly_one_peer_observer() -> None:
    result = parse_probe_rows(
        [
            {"reviewer": "a", "peer_present": "f"},
            {"reviewer": "b", "peer_present": "t"},
        ]
    )
    assert result.verdict == "DB_CONCURRENCY_PROBE_OK"


def test_runner_rejects_both_peers_present() -> None:
    # 둘 다 상대를 봤다면 직렬화 실패(둘 다 먼저 커밋됐다고 관측 = 경합 미직렬화).
    result = parse_probe_rows(
        [
            {"reviewer": "a", "peer_present": "t"},
            {"reviewer": "b", "peer_present": "t"},
        ]
    )
    assert result.verdict == "CONCURRENCY_FAILED"


def test_runner_rejects_wrong_row_count() -> None:
    assert parse_probe_rows([{"reviewer": "a", "peer_present": "f"}]).verdict == "CONCURRENCY_FAILED"


# ── local Homebrew postgres backend 안전 계약 ────────────────────────
def test_temp_database_name_uses_probe_prefix() -> None:
    name = temp_database_name("0a1b2c3d")
    assert name.startswith("blind_probe_")
    # 생성한 이름은 스스로 안전 검증을 통과해야 한다.
    validate_temp_database_name(name)


def test_validate_temp_database_name_rejects_non_probe_targets() -> None:
    for unsafe in (
        "postgres",
        "template1",
        "blind_probe",              # 접미사 없음
        "blindprobe_x",             # prefix 불일치
        "blind_probe_x; DROP DATABASE postgres",  # 주입 시도
        "BLIND_PROBE_ABC",          # 대문자
    ):
        with pytest.raises(ProbeBlocked, match="unsafe_temp_database_name"):
            validate_temp_database_name(unsafe)


def test_validate_temp_database_name_allows_generated() -> None:
    validate_temp_database_name("blind_probe_deadbeef0123")

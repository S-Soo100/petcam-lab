"""동시 제출 실증 러너의 단위 테스트 — Docker 없이 명령·fail-closed·parser 만 검증.

실제 컨테이너 실증은 scripts/run_motion_double_blind_concurrency_probe.py 가 담당하고,
여기서는 순수 로직(운영 DB 접속 차단, peer_present 다중집합 판정)만 고정한다.
"""

import pytest

from scripts.run_motion_double_blind_concurrency_probe import (
    ProbeBlocked,
    parse_probe_rows,
    validate_database_url,
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

"""권한별 라벨링 read RPC 실제 DB probe 러너의 단위 테스트.

빠른 순수 로직(임시 DB 이름 안전 계약·마커 판정)만 고정한다. 실제 DB 실증은
scripts/run_role_based_labeling_reads_probe.py 가 담당하며, 아래 opt-in live 테스트
(ROLE_READS_PROBE_LIVE=1)로도 돌릴 수 있다. 기본 pytest 실행은 DB 를 띄우지 않는다.
"""

import os
import shutil

import pytest

from scripts.run_role_based_labeling_reads_probe import (
    ProbeBlocked,
    main,
    missing_marker,
    role_reads_temp_database_name,
    validate_database_url,
    validate_role_reads_temp_database_name,
)


def test_temp_database_name_uses_role_reads_prefix() -> None:
    name = role_reads_temp_database_name("0a1b2c3d")
    assert name.startswith("blind_probe_role_reads_")
    # 생성한 이름은 스스로 안전 검증을 통과해야 한다.
    validate_role_reads_temp_database_name(name)


def test_validate_role_reads_temp_database_name_rejects_unsafe() -> None:
    for unsafe in (
        "postgres",
        "template1",
        "blind_probe_deadbeef",  # 다른 probe 의 prefix(role_reads 아님)
        "blind_probe_role_reads",  # 접미사 없음
        "blind_probe_role_reads_",  # 빈 hex
        "blind_probe_role_reads_ABC",  # 대문자
        "blind_probe_role_reads_xyz",  # hex 아님(x/y/z)
        "blind_probe_role_reads_x; DROP DATABASE postgres",  # 주입 시도
    ):
        with pytest.raises(ProbeBlocked, match="unsafe_temp_database_name"):
            validate_role_reads_temp_database_name(unsafe)


def test_validate_role_reads_temp_database_name_allows_generated() -> None:
    validate_role_reads_temp_database_name("blind_probe_role_reads_deadbeef0123")


def test_missing_marker_detects_absent_and_all_present() -> None:
    full = "ROLE_READS_RUNTIME_OK\nROLE_READS_BLIND_GUARD_OK\nROLE_READS_PAGINATION_OK\n"
    assert missing_marker(full) is None
    # 첫 누락 마커를 반환한다.
    assert missing_marker("ROLE_READS_RUNTIME_OK\n") == "ROLE_READS_BLIND_GUARD_OK"
    assert (
        missing_marker("ROLE_READS_RUNTIME_OK\nROLE_READS_BLIND_GUARD_OK\n")
        == "ROLE_READS_PAGINATION_OK"
    )
    assert missing_marker("") == "ROLE_READS_RUNTIME_OK"


def test_reused_local_only_contract_rejects_remote_db() -> None:
    # 기존 러너의 local-only 계약을 재사용한다(운영 DB 접속 차단).
    with pytest.raises(ProbeBlocked, match="non_local_database_forbidden"):
        validate_database_url("postgresql://prod.example.com/db")


# ── opt-in 실 DB 실증 (ROLE_READS_PROBE_LIVE=1, local postgres 필요) ──
@pytest.mark.skipif(
    os.environ.get("ROLE_READS_PROBE_LIVE") != "1",
    reason="ROLE_READS_PROBE_LIVE=1 일 때만 실제 local PostgreSQL 실증을 돈다",
)
def test_live_probe_against_local_postgres(capsys: pytest.CaptureFixture[str]) -> None:
    if shutil.which("psql") is None and not os.path.isfile(
        "/opt/homebrew/opt/postgresql@15/bin/psql"
    ):
        pytest.skip("local psql 미설치")
    rc = main(["--backend", "local-postgres"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "PROBE_RESIDUE=0" in out
    for marker in (
        "ROLE_READS_RUNTIME_OK",
        "ROLE_READS_BLIND_GUARD_OK",
        "ROLE_READS_PAGINATION_OK",
    ):
        assert marker in out

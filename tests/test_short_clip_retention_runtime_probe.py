"""짧은 영상 격리·보존 실제 DB probe 러너의 단위 테스트.

빠른 순수 로직(임시 DB 이름 안전 계약·마커 판정·local-only 계약)만 고정한다. 실제 DB 실증은
scripts/run_short_clip_retention_probe.py 가 담당하며, 아래 opt-in live 테스트
(SHORT_CLIP_PROBE_LIVE=1)로도 돌릴 수 있다. 기본 pytest 실행은 DB 를 띄우지 않는다.
"""

import os
import shutil

import pytest

from scripts.run_short_clip_retention_probe import (
    ProbeBlocked,
    main,
    missing_marker,
    short_clip_temp_database_name,
    validate_database_url,
    validate_short_clip_temp_database_name,
)


def test_temp_database_name_uses_short_clip_prefix() -> None:
    name = short_clip_temp_database_name("0a1b2c3d")
    assert name.startswith("blind_probe_short_clip_")
    validate_short_clip_temp_database_name(name)


def test_validate_short_clip_temp_database_name_rejects_unsafe() -> None:
    for unsafe in (
        "postgres",
        "template1",
        "blind_probe_deadbeef",  # 다른 probe prefix
        "blind_probe_short_clip",  # 접미사 없음
        "blind_probe_short_clip_",  # 빈 hex
        "blind_probe_short_clip_ABC",  # 대문자
        "blind_probe_short_clip_xyz",  # hex 아님
        "blind_probe_short_clip_x; DROP DATABASE postgres",  # 주입 시도
    ):
        with pytest.raises(ProbeBlocked, match="unsafe_temp_database_name"):
            validate_short_clip_temp_database_name(unsafe)


def test_validate_short_clip_temp_database_name_allows_generated() -> None:
    validate_short_clip_temp_database_name("blind_probe_short_clip_deadbeef0123")


def test_missing_marker_detects_absent_and_all_present() -> None:
    full = (
        "SHORT_CLIP_DETECT_OK\nSHORT_CLIP_RESTORE_OK\nSHORT_CLIP_DELETE_LEASE_OK\n"
        "SHORT_CLIP_APPEND_ONLY_OK\nSHORT_CLIP_NOTIFY_OK\nSHORT_CLIP_CONSUMER_GUARD_OK\n"
    )
    assert missing_marker(full) is None
    assert missing_marker("SHORT_CLIP_DETECT_OK\n") == "SHORT_CLIP_RESTORE_OK"
    assert missing_marker("") == "SHORT_CLIP_DETECT_OK"


def test_reused_local_only_contract_rejects_remote_db() -> None:
    # 기존 러너의 local-only 계약을 재사용한다(운영 DB 접속 차단).
    with pytest.raises(ProbeBlocked, match="non_local_database_forbidden"):
        validate_database_url("postgresql://prod.example.com/db")


# ── opt-in 실 DB 실증 (SHORT_CLIP_PROBE_LIVE=1, local postgres 필요) ──
@pytest.mark.skipif(
    os.environ.get("SHORT_CLIP_PROBE_LIVE") != "1",
    reason="SHORT_CLIP_PROBE_LIVE=1 일 때만 실제 local PostgreSQL 실증을 돈다",
)
def test_live_probe_against_local_postgres(capsys: pytest.CaptureFixture[str]) -> None:
    if shutil.which("psql") is None and not (
        os.path.isfile("/opt/homebrew/opt/postgresql@15/bin/psql")
        or os.path.isfile("/usr/local/opt/postgresql@15/bin/psql")
    ):
        pytest.skip("local psql 미설치")
    rc = main(["--backend", "local-postgres"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "PROBE_RESIDUE=0" in out
    for marker in (
        "SHORT_CLIP_DETECT_OK",
        "SHORT_CLIP_RESTORE_OK",
        "SHORT_CLIP_DELETE_LEASE_OK",
        "SHORT_CLIP_APPEND_ONLY_OK",
        "SHORT_CLIP_NOTIFY_OK",
        "SHORT_CLIP_CONSUMER_GUARD_OK",
    ):
        assert marker in out

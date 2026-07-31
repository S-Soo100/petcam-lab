"""Formal Blind30 v2 disposable PostgreSQL probe runner contract."""

import os
import shutil

import pytest

from scripts.run_motion_blind_formal30_v2_probe import (
    ProbeBlocked,
    apply_order,
    formal30_v2_temp_database_name,
    main,
    missing_marker,
    validate_database_url,
    validate_formal30_v2_temp_database_name,
)


def test_rejects_non_loopback_database_url() -> None:
    with pytest.raises(ProbeBlocked, match="non_local_database_forbidden"):
        validate_database_url("postgresql://prod.example.com/db")


def test_temp_database_name_is_narrow_and_generated_name_is_valid() -> None:
    name = formal30_v2_temp_database_name("deadbeef0123")
    assert name == "blind_probe_formal30_v2_deadbeef0123"
    validate_formal30_v2_temp_database_name(name)


@pytest.mark.parametrize(
    "unsafe",
    (
        "postgres",
        "template1",
        "blind_probe_deadbeef",
        "blind_probe_formal30",
        "blind_probe_formal30_v2_",
        "blind_probe_formal30_v2_XYZ",
        "blind_probe_formal30_v2_a;drop database postgres",
    ),
)
def test_rejects_unsafe_temp_database_names(unsafe: str) -> None:
    with pytest.raises(ProbeBlocked, match="unsafe_temp_database_name"):
        validate_formal30_v2_temp_database_name(unsafe)


def test_apply_order_ends_with_v1_then_v2_forward_migrations() -> None:
    paths = [path for _label, path in apply_order()]
    assert paths[-3].name == "motion_blind_formal30_prerequisites.sql"
    assert paths[-2].name == "2026-07-31_motion_blind_formal30.sql"
    assert paths[-1].name == "2026-07-31_motion_blind_formal30_v2.sql"


def test_missing_marker_detects_absent_marker() -> None:
    assert missing_marker("FORMAL30_V2_PROBE_OK\n") is None
    assert missing_marker("") == "FORMAL30_V2_PROBE_OK"


@pytest.mark.skipif(
    os.environ.get("FORMAL30_V2_PROBE_LIVE") != "1",
    reason="FORMAL30_V2_PROBE_LIVE=1 일 때만 local PostgreSQL 실증을 돈다",
)
def test_live_probe_against_local_postgres(capsys: pytest.CaptureFixture[str]) -> None:
    if shutil.which("psql") is None and not os.path.isfile(
        "/opt/homebrew/opt/postgresql@15/bin/psql"
    ):
        pytest.skip("local psql 미설치")
    rc = main(["--backend", "local-postgres"])
    output = capsys.readouterr().out
    assert rc == 0, output
    assert "FORMAL30_V2_PROBE_OK" in output
    assert "PROBE_RESIDUE=0" in output

"""GME negative audit disposable PostgreSQL probe runner tests."""

import json
from pathlib import Path
import subprocess

import pytest

import scripts.run_gme_negative_audit_probe as probe
from scripts.run_gme_negative_audit_probe import (
    HardenedLocalPostgresBackend,
    MANIFEST_PLACEHOLDER,
    ProbeBlocked,
    ProbeFailed,
    extract_fixture_sql,
    build_probe_manifest,
    missing_marker,
    negative_audit_temp_database_name,
    render_probe_sql,
    run_local_negative_audit_probe,
    validate_negative_audit_temp_database_name,
    validate_probe_database_url,
)


def test_probe_database_name_is_exact_random_prefix() -> None:
    name = negative_audit_temp_database_name("0123456789abcdef")
    assert name == "blind_probe_gme_negative_0123456789abcdef"
    validate_negative_audit_temp_database_name(name)


def test_probe_applies_close_guard_after_base_migration() -> None:
    assert probe._APPLY_ORDER == (
        ("prerequisites", "tests/sql/gme_negative_audit_prerequisites.sql"),
        ("migration", "migrations/2026-08-23_gme_negative_audit_calibration.sql"),
        (
            "close_completion_guard",
            "migrations/2026-08-25_gme_negative_audit_close_completion_guard.sql",
        ),
    )


@pytest.mark.parametrize(
    "unsafe",
    (
        "postgres",
        "template1",
        "blind_probe_deadbeef",
        "blind_probe_gme_negative_deadbeef",
        "blind_probe_gme_negative_0123456789abcdeg",
        "blind_probe_gme_negative_0123456789ABCDEF",
        "blind_probe_gme_negative_0123456789abcdef;drop database postgres",
    ),
)
def test_probe_rejects_existing_or_nonrandom_database_names(unsafe: str) -> None:
    with pytest.raises(ProbeBlocked, match="unsafe_temp_database_name"):
        validate_negative_audit_temp_database_name(unsafe)


def test_probe_database_url_requires_local_random_target() -> None:
    name = "blind_probe_gme_negative_0123456789abcdef"
    validate_probe_database_url(f"postgresql://127.0.0.1:5432/{name}")
    validate_probe_database_url(f"postgresql://localhost:5432/{name}")


@pytest.mark.parametrize(
    "unsafe_url",
    (
        "postgresql://prod.example.com:5432/blind_probe_gme_negative_0123456789abcdef",
        "postgresql://127.0.0.2:5432/blind_probe_gme_negative_0123456789abcdef",
        "postgresql://[::1]:5432/blind_probe_gme_negative_0123456789abcdef",
        "postgresql:///blind_probe_gme_negative_0123456789abcdef?host=/tmp",
        "postgresql://127.0.0.1:5432/blind_probe_gme_negative_0123456789abcdef?host=prod.example.com",
        "postgresql://user@127.0.0.1:5432/blind_probe_gme_negative_0123456789abcdef",
        "postgresql://user:secret@127.0.0.1:5432/blind_probe_gme_negative_0123456789abcdef",
        "postgresql://%31%32%37.0.0.1:5432/blind_probe_gme_negative_0123456789abcdef",
        "postgresql://127.0.0.1:5432/blind_probe_gme_negative_%30%31%32%33%34%35%36%37%38%39abcdef",
        "postgres://127.0.0.1:5432/blind_probe_gme_negative_0123456789abcdef",
        "postgresql://127.0.0.1/blind_probe_gme_negative_0123456789abcdef",
        "postgresql://127.0.0.1:5432/postgres",
        "postgresql://127.0.0.1:5432/blind_probe_gme_negative_0123456789abcdef#ignored",
    ),
)
def test_probe_database_url_rejects_authority_and_libpq_bypasses(unsafe_url: str) -> None:
    with pytest.raises(ProbeBlocked, match="unsafe_database_url"):
        validate_probe_database_url(unsafe_url)


def test_probe_requires_all_success_markers() -> None:
    assert missing_marker("GME_NEGATIVE_AUDIT_SCHEMA_OK\n") == "GME_NEGATIVE_AUDIT_BLIND_OK"
    assert (
        missing_marker(
            "GME_NEGATIVE_AUDIT_SCHEMA_OK\n"
            "GME_NEGATIVE_AUDIT_BLIND_OK\n"
            "GME_NEGATIVE_AUDIT_APPEND_ONLY_OK\n"
        )
        is None
    )


@pytest.mark.parametrize(
    ("stdout", "error"),
    (
        (
            "prefix-GME_NEGATIVE_AUDIT_SCHEMA_OK\n",
            "invalid_marker_line:GME_NEGATIVE_AUDIT_SCHEMA_OK",
        ),
        (
            "GME_NEGATIVE_AUDIT_SCHEMA_OK-suffix\n",
            "invalid_marker_line:GME_NEGATIVE_AUDIT_SCHEMA_OK",
        ),
        (
            "GME_NEGATIVE_AUDIT_SCHEMA_OK\nGME_NEGATIVE_AUDIT_SCHEMA_OK\n"
            "GME_NEGATIVE_AUDIT_BLIND_OK\nGME_NEGATIVE_AUDIT_APPEND_ONLY_OK\n",
            "duplicate_marker:GME_NEGATIVE_AUDIT_SCHEMA_OK",
        ),
        (
            "GME_NEGATIVE_AUDIT_SCHEMA_OK\nGME_NEGATIVE_AUDIT_BLIND_OK\n"
            "GME_NEGATIVE_AUDIT_APPEND_ONLY_OK\n"
            "GME_NEGATIVE_AUDIT_BLIND_OK-suffix\n",
            "invalid_marker_line:GME_NEGATIVE_AUDIT_BLIND_OK",
        ),
    ),
)
def test_probe_marker_validation_requires_exact_unique_lines(stdout: str, error: str) -> None:
    assert missing_marker(stdout) == error


def test_postgres_backend_disables_psqlrc() -> None:
    backend = HardenedLocalPostgresBackend("/tmp/psql", "postgresql://127.0.0.1:5432/db")
    assert "-X" in backend.psql_argv()
    assert backend.psql_argv().count("-X") == 1


def test_cleanup_and_residue_psql_calls_disable_psqlrc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        commands.append(command)
        stdout = "f\n" if "pg_database" in str(_kwargs.get("input_text")) else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(probe, "_run", fake_run)
    assert not probe._database_exists(
        "/tmp/psql", "127.0.0.1", 5432, "blind_probe_gme_negative_0123456789abcdef"
    )
    probe._drop_probe_roles("/tmp/psql", "127.0.0.1", 5432, ["anon"])
    assert len(commands) == 2
    assert all(command.count("-X") == 1 for command in commands)


def test_probe_manifest_comes_from_canonical_task1_producer() -> None:
    manifest = build_probe_manifest()
    assert manifest["batch_kind"] == "preview_canary"
    assert manifest["reviewer_ids"] == [
        "00000000-0000-4000-8000-000000000001",
        "00000000-0000-4000-8000-000000000002",
    ]
    assert manifest["assignment_rule"] == "stratum_round_robin_v1"
    assert [item["stratum"] for item in manifest["items"]].count("random_negative") == 4
    assert [item["stratum"] for item in manifest["items"]].count("positive_control") == 2
    assert manifest["items"][0]["duration_sec"] == str(manifest["items"][0]["duration_sec"])
    assert "게코" in json.dumps(manifest, ensure_ascii=False)
    assert len(manifest["manifest_sha256"]) == 64


def test_render_probe_sql_replaces_one_manifest_without_ascii_escaping() -> None:
    manifest = build_probe_manifest()
    rendered = render_probe_sql(f"SELECT {MANIFEST_PLACEHOLDER}::jsonb;", manifest)
    assert MANIFEST_PLACEHOLDER not in rendered
    assert "게코" in rendered
    assert "\\uac8c" not in rendered


def test_probe_template_requires_exactly_one_manifest_placeholder() -> None:
    manifest = build_probe_manifest()
    with pytest.raises(ProbeFailed, match="exactly_one"):
        render_probe_sql("SELECT 1", manifest)
    with pytest.raises(ProbeFailed, match="exactly_one"):
        render_probe_sql(MANIFEST_PLACEHOLDER + MANIFEST_PLACEHOLDER, manifest)


def test_fixture_extraction_is_bounded_by_exact_markers() -> None:
    sql = "before\n-- GME_NEGATIVE_FIXTURE_BEGIN\nSELECT 1;\n-- GME_NEGATIVE_FIXTURE_END\nafter"
    assert extract_fixture_sql(sql) == "SELECT 1;"
    with pytest.raises(ProbeFailed, match="fixture_markers"):
        extract_fixture_sql("SELECT 1")


def _completed(command: str, returncode: int, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([command], returncode, stdout="", stderr=stderr)


def test_primary_and_drop_failures_are_both_reported_and_roles_still_cleaned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_checks = iter((False, True, True))
    role_cleanup_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(probe, "_find_pg_tool", lambda name, _pg_bin: name)
    monkeypatch.setattr(probe.secrets, "token_hex", lambda _size: "0123456789abcdef")
    monkeypatch.setattr(probe, "_database_exists", lambda *_args: next(database_checks))
    monkeypatch.setattr(probe, "_existing_blind_roles", lambda _backend: set())
    monkeypatch.setattr(
        probe,
        "_run_probe_steps",
        lambda *_args: (_ for _ in ()).throw(ProbeFailed("primary failure")),
    )

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        if command[0] == "createdb":
            return _completed("createdb", 0)
        return _completed("dropdb", 1, "drop failure")

    def fake_drop_roles(
        _psql: str, _host: str, _port: int, roles: list[str]
    ) -> subprocess.CompletedProcess:
        role_cleanup_calls.append(tuple(roles))
        return _completed("drop-role", 0)

    monkeypatch.setattr(probe, "_run", fake_run)
    monkeypatch.setattr(probe, "_drop_probe_roles", fake_drop_roles)

    with pytest.raises(ProbeFailed) as caught:
        run_local_negative_audit_probe([], Path("probe.sql"))
    message = str(caught.value)
    assert "primary_failed:ProbeFailed:primary failure" in message
    assert "dropdb_failed:drop failure" in message
    assert "database_residue_nonzero" in message
    assert role_cleanup_calls == [("anon", "authenticated", "service_role")]


def test_drop_failure_does_not_skip_failed_role_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_checks = iter((False, True, True))
    role_cleanup_calls = 0
    monkeypatch.setattr(probe, "_find_pg_tool", lambda name, _pg_bin: name)
    monkeypatch.setattr(probe.secrets, "token_hex", lambda _size: "0123456789abcdef")
    monkeypatch.setattr(probe, "_database_exists", lambda *_args: next(database_checks))
    monkeypatch.setattr(probe, "_existing_blind_roles", lambda _backend: set())
    monkeypatch.setattr(probe, "_run_probe_steps", lambda *_args: None)

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        return _completed(command[0], 0 if command[0] == "createdb" else 1, "drop failure")

    def fake_drop_roles(*_args: object) -> subprocess.CompletedProcess:
        nonlocal role_cleanup_calls
        role_cleanup_calls += 1
        return _completed("drop-role", 1, "role failure")

    monkeypatch.setattr(probe, "_run", fake_run)
    monkeypatch.setattr(probe, "_drop_probe_roles", fake_drop_roles)

    with pytest.raises(ProbeFailed) as caught:
        run_local_negative_audit_probe([], Path("probe.sql"))
    assert "dropdb_failed:drop failure" in str(caught.value)
    assert "role_cleanup_failed:role failure" in str(caught.value)
    assert role_cleanup_calls == 1


def test_cleanup_keyboard_interrupt_is_reraised_after_role_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_checks = iter((False, True, False))
    role_cleanup_calls = 0
    monkeypatch.setattr(probe, "_find_pg_tool", lambda name, _pg_bin: name)
    monkeypatch.setattr(probe.secrets, "token_hex", lambda _size: "0123456789abcdef")
    monkeypatch.setattr(probe, "_database_exists", lambda *_args: next(database_checks))
    monkeypatch.setattr(probe, "_existing_blind_roles", lambda _backend: set())
    monkeypatch.setattr(probe, "_run_probe_steps", lambda *_args: None)

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        if command[0] == "createdb":
            return _completed("createdb", 0)
        raise KeyboardInterrupt

    def fake_drop_roles(*_args: object) -> subprocess.CompletedProcess:
        nonlocal role_cleanup_calls
        role_cleanup_calls += 1
        return _completed("drop-role", 0)

    monkeypatch.setattr(probe, "_run", fake_run)
    monkeypatch.setattr(probe, "_drop_probe_roles", fake_drop_roles)

    with pytest.raises(KeyboardInterrupt):
        run_local_negative_audit_probe([], Path("probe.sql"))
    assert role_cleanup_calls == 1


def test_createdb_timeout_drops_uncertain_created_database_then_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_checks = iter((False, True, False))
    drop_commands: list[list[str]] = []
    role_cleanup_calls = 0
    monkeypatch.setattr(probe, "_find_pg_tool", lambda name, _pg_bin: name)
    monkeypatch.setattr(probe.secrets, "token_hex", lambda _size: "0123456789abcdef")
    monkeypatch.setattr(probe, "_database_exists", lambda *_args: next(database_checks))

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        if command[0] == "createdb":
            raise subprocess.TimeoutExpired(command, 30)
        drop_commands.append(command)
        return _completed("dropdb", 0)

    def fake_drop_roles(*_args: object) -> None:
        nonlocal role_cleanup_calls
        role_cleanup_calls += 1
        return None

    monkeypatch.setattr(probe, "_run", fake_run)
    monkeypatch.setattr(probe, "_drop_probe_roles", fake_drop_roles)

    with pytest.raises(subprocess.TimeoutExpired):
        run_local_negative_audit_probe([], Path("probe.sql"))
    assert len(drop_commands) == 1
    assert "--force" in drop_commands[0]
    assert role_cleanup_calls == 1


def test_createdb_keyboard_interrupt_cleans_uncertain_database_then_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_checks = iter((False, True, False))
    drop_commands: list[list[str]] = []
    role_cleanup_calls = 0
    monkeypatch.setattr(probe, "_find_pg_tool", lambda name, _pg_bin: name)
    monkeypatch.setattr(probe.secrets, "token_hex", lambda _size: "0123456789abcdef")
    monkeypatch.setattr(probe, "_database_exists", lambda *_args: next(database_checks))

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        if command[0] == "createdb":
            raise KeyboardInterrupt
        drop_commands.append(command)
        return _completed("dropdb", 0)

    def fake_drop_roles(*_args: object) -> None:
        nonlocal role_cleanup_calls
        role_cleanup_calls += 1
        return None

    monkeypatch.setattr(probe, "_run", fake_run)
    monkeypatch.setattr(probe, "_drop_probe_roles", fake_drop_roles)

    with pytest.raises(KeyboardInterrupt):
        run_local_negative_audit_probe([], Path("probe.sql"))
    assert len(drop_commands) == 1
    assert role_cleanup_calls == 1


def test_createdb_timeout_records_absent_database_without_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_checks = iter((False, False))
    drop_calls = 0
    role_cleanup_calls = 0
    monkeypatch.setattr(probe, "_find_pg_tool", lambda name, _pg_bin: name)
    monkeypatch.setattr(probe.secrets, "token_hex", lambda _size: "0123456789abcdef")
    monkeypatch.setattr(probe, "_database_exists", lambda *_args: next(database_checks))

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        nonlocal drop_calls
        if command[0] == "createdb":
            raise subprocess.TimeoutExpired(command, 30)
        drop_calls += 1
        return _completed("dropdb", 0)

    def fake_drop_roles(*_args: object) -> None:
        nonlocal role_cleanup_calls
        role_cleanup_calls += 1
        return None

    monkeypatch.setattr(probe, "_run", fake_run)
    monkeypatch.setattr(probe, "_drop_probe_roles", fake_drop_roles)

    with pytest.raises(subprocess.TimeoutExpired):
        run_local_negative_audit_probe([], Path("probe.sql"))
    assert drop_calls == 0
    assert role_cleanup_calls == 1

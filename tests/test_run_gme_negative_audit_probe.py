"""GME negative audit disposable PostgreSQL probe runner tests."""

import json

import pytest

from scripts.run_gme_negative_audit_probe import (
    MANIFEST_PLACEHOLDER,
    ProbeBlocked,
    ProbeFailed,
    extract_fixture_sql,
    build_probe_manifest,
    missing_marker,
    negative_audit_temp_database_name,
    render_probe_sql,
    validate_probe_database_url,
    validate_database_url,
    validate_negative_audit_temp_database_name,
)


def test_probe_database_name_is_exact_random_prefix() -> None:
    name = negative_audit_temp_database_name("0123456789abcdef")
    assert name == "blind_probe_gme_negative_0123456789abcdef"
    validate_negative_audit_temp_database_name(name)


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


def test_probe_rejects_non_local_database() -> None:
    with pytest.raises(ProbeBlocked, match="non_local_database_forbidden"):
        validate_database_url("postgresql://prod.example.com/app")


def test_probe_database_url_requires_local_random_target() -> None:
    validate_probe_database_url(
        "postgresql://127.0.0.1:5432/blind_probe_gme_negative_0123456789abcdef"
    )
    with pytest.raises(ProbeBlocked, match="unsafe_temp_database_name"):
        validate_probe_database_url("postgresql://127.0.0.1:5432/postgres")


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


def test_probe_manifest_comes_from_canonical_task1_producer() -> None:
    manifest = build_probe_manifest()
    assert manifest["batch_kind"] == "preview_canary"
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

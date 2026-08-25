import re
from datetime import datetime, timezone
from pathlib import Path

from scripts.gme_negative_audit_sampling import (
    _canonical_duration,
    _canonical_json,
    _format_rfc3339,
)


MIGRATION = Path("migrations/2026-08-23_gme_negative_audit_calibration.sql")
SQL = MIGRATION.read_text().lower()

REQUIRED_TABLES = (
    "gme_negative_audit_batches",
    "gme_negative_audit_batch_events",
    "gme_negative_audit_items",
    "gme_negative_audit_submissions",
    "gme_negative_audit_corrections",
    "gme_negative_audit_adjudications",
    "gme_negative_audit_dataset_decisions",
)

REQUIRED_RPCS = (
    "fn_create_gme_negative_audit_batch",
    "fn_list_gme_negative_audit_queue",
    "fn_get_gme_negative_audit_item",
    "fn_submit_gme_negative_audit",
    "fn_append_gme_negative_audit_correction",
    "fn_append_gme_negative_audit_adjudication",
    "fn_append_gme_negative_audit_dataset_decision",
)

CANONICAL_DURATION_PATTERN = r"^(0|[1-9][0-9]*)([.][0-9]*[1-9])?$"
CANONICAL_RFC3339_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"([.][0-9]{6})?Z$"
)


def function_definition(name: str) -> str:
    match = re.search(
        rf"create function public\.{re.escape(name)}\b(?P<body>.*?)\$\$\s*;",
        SQL,
        re.DOTALL,
    )
    assert match is not None, f"missing function: {name}"
    return match.group(0)


def function_returns(name: str) -> str:
    definition = function_definition(name)
    return definition.split("language", 1)[0].split("returns", 1)[1]


def test_audit_tables_are_private_and_append_only() -> None:
    for table in REQUIRED_TABLES:
        assert f"create table public.{table}" in SQL
        assert f"alter table public.{table} enable row level security" in SQL
        assert f"revoke all on public.{table} from public, anon, authenticated" in SQL
        assert f"before update or delete on public.{table}" in SQL
        assert f"before truncate on public.{table}" in SQL
    assert "create policy" not in SQL


def test_batch_shape_and_state_are_frozen_in_append_only_rows() -> None:
    assert "schema_version text not null default 'gme-negative-audit-v1'" in SQL
    assert "batch_kind in ('calibration','preview_canary')" in SQL
    assert "expected_negative_count = 120" in SQL
    assert "expected_control_count = 30" in SQL
    assert "expected_total_count = 150" in SQL
    assert "expected_negative_count = 4" in SQL
    assert "expected_control_count = 2" in SQL
    assert "expected_total_count = 6" in SQL
    assert "event_type in ('prepared','opened','closed','scored','invalidated')" in SQL
    assert "update public.gme_negative_audit_batches" not in SQL
    event_guard = function_definition("fn_validate_gme_negative_audit_batch_event")
    assert "for update" in event_guard
    assert "invalid_batch_event_transition" in event_guard
    assert "batch.owner_id <> new.actor_id" in event_guard
    assert ") is not true then" in event_guard


def test_items_and_submission_preserve_frozen_identity() -> None:
    assert "unique (batch_id, ordinal)" in SQL
    assert "unique (batch_id, clip_id)" in SQL
    assert "unique (batch_id, media_sha256)" in SQL
    assert "assigned_reviewer_id uuid not null" in SQL
    assert "gme_run_id uuid not null" in SQL
    assert "media_dhash" in SQL
    assert "item_id uuid not null unique" in SQL
    assert "original_submission_id uuid not null" in SQL
    assert "effective_submission_digest text not null" in SQL
    assert "unique (item_id, expected_submission_digest)" in SQL


def test_import_is_strict_and_revalidates_source_lineage() -> None:
    definition = function_definition("fn_create_gme_negative_audit_batch")
    for contract in (
        "gme-negative-audit-v1",
        "sha256(utf8-canonical-json-v1-excluding-manifest_sha256)",
        "candidate_counts",
        "source_pools",
        "selection_sha256",
        "protected_manifest_sha256",
        "manifest_sha256",
        "detector_identity",
        "checkpoint_sha256",
        "cutoff",
        "jsonb_object_keys",
        "fn_current_gme_activity",
        "result_run_id",
        "detected is false",
        "final_decision = 'label'",
        "final_gt ->> 'visibility' in ('visible','partial')",
    ):
        assert contract in definition
    assert "schema_version' is distinct from 'gme-negative-audit-v1'" in definition
    assert "status' is distinct from 'prepared'" in definition
    assert "manifest_sha256_rule' is distinct from" in definition
    assert "assigned_reviewer_id" in definition
    assert "from auth.users" in definition
    assert "count(*) from jsonb_object_keys(v_item)) <> 14" in definition
    assert "from jsonb_array_elements(p_manifest -> 'items') as manifest_item(value)" in definition
    assert "jsonb_typeof(v_item -> 'duration_sec') <> 'string'" in definition
    assert "v_started_at < v_cutoff" in definition


def test_sql_and_producer_share_utf8_decimal_canonical_fixture() -> None:
    fixture = {"label": "게코-alpha", "duration_sec": "0.0000001"}
    assert _canonical_json(fixture) == (
        '{"duration_sec":"0.0000001","label":"게코-alpha"}'.encode()
    )

    canonical = function_definition("fn_gme_negative_audit_canonical_json")
    candidate = function_definition("fn_gme_negative_audit_manifest_candidate")
    assert "order by entry.key" in canonical
    assert "return p_value::text" in canonical
    assert "'duration_sec', p_item ->> 'duration_sec'" in candidate


def test_import_requires_canonical_duration_spelling() -> None:
    definition = function_definition("fn_create_gme_negative_audit_batch")
    assert f"duration_sec' !~ '{CANONICAL_DURATION_PATTERN}'" in definition
    assert _canonical_duration(60.0) == "60"
    assert _canonical_duration(60.25) == "60.25"

    for accepted in ("60", "60.25"):
        assert re.fullmatch(CANONICAL_DURATION_PATTERN, accepted) is not None
    for rejected in ("60.0", "60.00"):
        assert re.fullmatch(CANONICAL_DURATION_PATTERN, rejected) is None


def test_import_requires_canonical_rfc3339_spelling_for_cutoff_and_items() -> None:
    definition = function_definition("fn_create_gme_negative_audit_batch")
    sql_pattern = CANONICAL_RFC3339_PATTERN.lower()
    assert f"p_manifest ->> 'cutoff' !~ '{sql_pattern}'" in definition
    assert f"v_item ->> 'started_at' !~ '{sql_pattern}'" in definition
    assert _format_rfc3339(datetime(2026, 8, 1, tzinfo=timezone.utc)) == (
        "2026-08-01T00:00:00Z"
    )
    assert _format_rfc3339(
        datetime(2026, 8, 1, microsecond=100_000, tzinfo=timezone.utc)
    ) == "2026-08-01T00:00:00.100000Z"

    for accepted in ("2026-08-01T00:00:00Z", "2026-08-01T00:00:00.100000Z"):
        assert re.fullmatch(CANONICAL_RFC3339_PATTERN, accepted) is not None
    assert re.fullmatch(CANONICAL_RFC3339_PATTERN, "2026-08-01T00:00:00.1Z") is None


def test_import_recomputes_selection_contract_instead_of_trusting_digests() -> None:
    definition = function_definition("fn_create_gme_negative_audit_batch")
    assert "selection_provenance_mismatch" in definition
    assert "selection_sha256_mismatch" in definition
    assert "random_negative_episode_cap_exceeded" in definition
    assert "blind_order_mismatch" in definition
    assert "negative_pool_sha256" in definition
    assert "control_pool_sha256" in definition
    assert "blind-order" in definition


def test_import_derives_manifest_bound_stratum_round_robin_assignments() -> None:
    definition = function_definition("fn_create_gme_negative_audit_batch")
    assert "reviewer_ids" in definition
    assert "stratum_round_robin_v1" in definition
    assert "owner_must_be_first_reviewer" in definition
    assert "reviewer_ids_duplicate" in definition
    assert "reviewer_not_found" in definition
    assert "reviewer_not_approved" in definition
    assert "partition by manifest_item.value ->> 'stratum'" in definition
    assert "order by (manifest_item.value ->> 'ordinal')::integer" in definition
    assert "assignment_sha256:" in definition


def test_import_locks_mutable_source_tables_for_one_snapshot() -> None:
    definition = function_definition("fn_create_gme_negative_audit_batch")
    for table in ("motion_clips", "motion_clip_consensus", "gme_jobs", "gme_runs"):
        assert f"lock table public.{table} in share mode" in definition


def test_import_accepts_empty_protected_manifest_array() -> None:
    definition = function_definition("fn_create_gme_negative_audit_batch")
    assert "invalid_protected_manifest_set" in definition
    assert "jsonb_array_length(p_manifest -> 'protected_manifest_sha256') < 1" not in definition


def test_public_rpc_rows_do_not_return_blind_fields() -> None:
    public_returns = function_returns(
        "fn_list_gme_negative_audit_queue"
    ) + function_returns("fn_get_gme_negative_audit_item")
    for forbidden in (
        "stratum",
        "gme_run_id",
        "detector_identity",
        "media_sha256",
        "control",
        "source",
        "hash",
        "reviewer_id",
    ):
        assert forbidden not in public_returns


def test_submission_has_stable_errors_and_strict_present_shape() -> None:
    definition = function_definition(
        "fn_submit_gme_negative_audit"
    ) + function_definition("fn_validate_gme_negative_audit_verdict")
    assert "errcode = 'pt410'" in definition
    assert "errcode = 'pt403'" in definition
    assert "errcode = 'pt427'" in definition
    assert "jsonb_object_keys(p_bbox)" in definition
    assert "array['x','y','width','height']" in definition
    assert "p_representative_sec < 0" in definition
    assert "p_representative_sec > p_duration_sec" in definition
    assert "x + width" in definition
    assert "y + height" in definition
    assert "p_representative_sec is not null or p_bbox is not null" in definition


def test_correction_adjudication_and_dataset_decisions_are_append_only() -> None:
    correction = function_definition("fn_append_gme_negative_audit_correction")
    adjudication = function_definition("fn_append_gme_negative_audit_adjudication")
    decision = function_definition("fn_append_gme_negative_audit_dataset_decision")
    assert "expected_submission_digest" in correction
    assert "original_submission_id" in correction
    assert "expected_submission_digest" in adjudication
    assert "reviewer_id <> p_owner_id" in adjudication
    assert "gecko_absent" in adjudication
    assert "include_candidate" in decision
    assert "positive_control" in decision
    assert "effective_submission_digest" in decision
    assert "update public.gme_negative_audit_" not in correction + adjudication + decision


def test_all_append_rpcs_share_id_bound_canonical_digest_and_return_it_atomically() -> None:
    helper = function_definition("fn_gme_negative_audit_ledger_digest")
    assert "array_to_string(p_parts, '|')" in helper
    for name, result_id in (
        ("fn_submit_gme_negative_audit", "submission_id"),
        ("fn_append_gme_negative_audit_correction", "correction_id"),
        ("fn_append_gme_negative_audit_adjudication", "adjudication_id"),
        ("fn_append_gme_negative_audit_dataset_decision", "decision_id"),
    ):
        definition = function_definition(name)
        assert "fn_gme_negative_audit_ledger_digest" in definition
        assert "v_id::text" in definition
        returned = function_returns(name)
        assert result_id in returned
        assert "digest text" in returned

    event_guard = function_definition("fn_validate_gme_negative_audit_batch_event")
    assert "new.id::text" in event_guard
    assert "batch_event_digest_mismatch" in event_guard


def test_owner_append_rpcs_require_latest_batch_event_opened_and_control_never_decides() -> None:
    for name in (
        "fn_append_gme_negative_audit_adjudication",
        "fn_append_gme_negative_audit_dataset_decision",
    ):
        definition = function_definition(name)
        assert "for share" in definition
        assert "order by event.created_at desc, event.id desc limit 1" in definition
        assert "v_state is distinct from 'opened'" in definition
        assert "errcode = 'pt427'" in definition
    decision = function_definition("fn_append_gme_negative_audit_dataset_decision")
    assert "v_item.stratum = 'positive_control'" in decision
    assert "unique (item_id)" in SQL


def test_all_rpcs_are_invoker_only_and_service_role_only() -> None:
    for name in REQUIRED_RPCS:
        definition = function_definition(name)
        assert "security invoker set search_path = ''" in definition
        assert f"revoke all on function public.{name}" in SQL
        assert f"grant execute on function public.{name}" in SQL
    assert "security definer" not in SQL
    assert re.search(r"grant execute on function .* to (anon|authenticated)", SQL) is None
    assert (
        "grant execute on function public.fn_gme_negative_audit_canonical_json(jsonb) "
        "to service_role"
    ) in SQL
    assert (
        "grant execute on function public.fn_validate_gme_negative_audit_verdict"
        "(text,numeric,jsonb,numeric) to service_role"
    ) in SQL

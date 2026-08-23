import re
from pathlib import Path


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
        "sha256(canonical-json-excluding-manifest_sha256)",
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

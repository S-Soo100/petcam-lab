"""YOLO 공개 시연·팀원 bbox 기여 forward migration 안전 계약."""

from pathlib import Path
import re


SQL_PATH = Path("migrations/2026-08-10_yolo_demo_team_contribution.sql")


def sql() -> str:
    assert SQL_PATH.is_file(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8").lower()


def test_isolated_tables_are_rls_protected() -> None:
    body = sql()
    tables = (
        "yolo_model_versions",
        "yolo_model_evaluations",
        "yolo_model_approval_events",
        "yolo_model_activation_events",
        "yolo_bbox_tasks",
        "yolo_bbox_blind_submissions",
        "yolo_bbox_reveals",
        "yolo_bbox_revisions",
        "yolo_bbox_owner_decisions",
        "yolo_dataset_versions",
        "yolo_dataset_status_events",
        "yolo_dataset_memberships",
    )
    for table in tables:
        assert f"create table public.{table}" in body
        assert f"alter table public.{table} enable row level security" in body
        assert f"revoke all on table public.{table} from public, anon, authenticated" in body


def test_rpc_surface_is_service_role_only() -> None:
    body = sql()
    signatures = (
        "fn_validate_yolo_boxes(jsonb, boolean)",
        "fn_get_yolo_bbox_workspace(uuid)",
        "fn_submit_yolo_bbox_blind(uuid, uuid, jsonb, boolean)",
        "fn_reveal_yolo_bbox_prediction(uuid, uuid)",
        "fn_submit_yolo_bbox_revision(uuid, uuid, jsonb, boolean, text)",
        "fn_owner_decide_yolo_bbox_revision(uuid, uuid, text, text, uuid)",
        "fn_owner_decide_yolo_model(uuid, text, text, text)",
        "fn_freeze_yolo_dataset(uuid, uuid, text)",
        "fn_activate_yolo_model(uuid, text, text, text)",
        "fn_get_yolo_owner_overview(uuid)",
    )
    for signature in signatures:
        escaped = re.escape(f"public.{signature}")
        assert re.search(
            rf"revoke all on function {escaped}\s+from public, anon, authenticated",
            body,
        )
        assert re.search(rf"grant execute on function {escaped}\s+to service_role", body)


def test_does_not_mutate_existing_behavior_or_motion_domains() -> None:
    body = sql()
    for table in (
        "motion_clips",
        "motion_clip_review_slots",
        "motion_clip_blind_submissions",
        "motion_clip_consensus",
        "motion_clip_labeling_sessions",
        "behavior_logs",
    ):
        assert f"insert into public.{table}" not in body
        assert f"update public.{table}" not in body
        assert f"delete from public.{table}" not in body


def test_human_and_model_provenance_is_append_only() -> None:
    body = sql()
    assert "fn_reject_yolo_history_mutation" in body
    assert "yolo history is append-only" in body
    for table in (
        "yolo_bbox_blind_submissions",
        "yolo_bbox_reveals",
        "yolo_bbox_revisions",
        "yolo_bbox_owner_decisions",
        "yolo_dataset_memberships",
        "yolo_model_evaluations",
        "yolo_model_approval_events",
        "yolo_model_activation_events",
    ):
        assert f"before update or delete or truncate on public.{table}" in body


def test_dataset_membership_only_targets_immutable_draft_versions() -> None:
    body = sql()
    assert "status text not null default 'draft'" in body
    assert "status in ('draft','frozen')" in body
    assert "where id = p_dataset_version_id and status = 'draft'" in body
    assert "create table public.yolo_dataset_status_events" in body
    assert "fn_freeze_yolo_dataset" in body
    assert "not exists (select 1 from public.yolo_dataset_status_events" in body
    assert body.count("select id into locked_dataset_id") == 2
    assert len(re.findall(
        r"where id = p_dataset_version_id and status = 'draft'\s+for update",
        body,
    )) == 2


def test_task_prediction_provenance_matches_immutable_task_metadata() -> None:
    body = sql()
    assert "prediction_snapshot->>'model_version' = model_version" in body
    assert "prediction_snapshot->>'media_kind' = media_kind" in body
    assert "jsonb_array_length(frame_manifest) between 1 and 3600" in body

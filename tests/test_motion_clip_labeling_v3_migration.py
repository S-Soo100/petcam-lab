"""motion_clips 네이티브 운영 라벨링 v3 마이그레이션 정적 계약 테스트.

설계 정본: docs/superpowers/specs/2026-07-22-motion-clips-native-labeling-design.md
구현계획: docs/superpowers/plans/2026-07-22-motion-clips-native-labeling.md Task 1

이 테스트는 마이그레이션 SQL 텍스트만 정적으로 검사한다(라이브 DB 미접속).
목적: preview apply 전에 계약(정본 테이블·service-role 전용·최신순·append-only·경합/무결성)을
      약화 없이 고정하고, 회귀 시 문자열 토큰 단위로 잡아낸다.
"""

from pathlib import Path

import pytest

SQL_PATH = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "2026-07-22_motion_clip_labeling_v3.sql"
)

V3_TABLES = [
    "motion_clip_labeling_triage",
    "motion_clip_labeling_triage_events",
    "motion_clip_labeling_sessions",
    "motion_clip_labeling_session_revisions",
]

V3_RPCS = [
    "fn_list_motion_clip_labeling_queue",
    "fn_list_motion_clip_labeling_camera_options",
    "fn_decide_motion_clip_labeling",
    "fn_lock_motion_clip_gt",
    "fn_complete_motion_clip_vlm_review",
    "fn_revise_motion_clip_gt",
]


@pytest.fixture(scope="module")
def sql() -> str:
    return SQL_PATH.read_text()


@pytest.fixture(scope="module")
def lower(sql: str) -> str:
    return sql.lower()


# ── 정본 테이블: motion_clips 만, camera_clips 절대 금지 ───────────────
def test_v3_tables_reference_motion_clips_and_never_camera_clips(lower: str):
    assert "references public.motion_clips(id)" in lower
    assert "references public.camera_clips" not in lower


def test_all_four_v3_tables_are_created(lower: str):
    for table in V3_TABLES:
        assert f"create table public.{table}" in lower


# ── service-role 전용: RLS ON + anon/authenticated REVOKE ─────────────
def test_v3_tables_are_service_role_only(lower: str):
    for table in V3_TABLES:
        assert f"alter table public.{table} enable row level security" in lower
        assert f"revoke all on table public.{table} from anon" in lower
        assert f"revoke all on table public.{table} from authenticated" in lower
        assert f"grant all on table public.{table} to service_role" in lower


def test_no_client_write_policy_created(lower: str):
    # anon/authenticated 에 직접 policy/GRANT 를 열지 않는다(설계 §10). service_role 전용.
    # (row lock 의 FOR UPDATE 는 정상이므로 policy 존재 여부로만 판정한다.)
    assert "create policy" not in lower
    assert "to authenticated" not in lower
    assert "to anon" not in lower


# ── 최신순 정본 정렬 ─────────────────────────────────────────────────
def test_queue_order_is_started_at_then_id_desc(lower: str):
    assert "order by m.started_at desc, m.id desc" in lower


def test_queue_keyset_boundary_preserves_microsecond_tie_break(lower: str):
    assert "m.started_at < p_cursor_started_at" in lower
    assert "m.started_at = p_cursor_started_at and m.id < p_cursor_id" in lower


def test_queue_limit_is_clamped_1_to_100(lower: str):
    assert "least(greatest(p_limit, 1), 100)" in lower


def test_owner_branch_never_filters_by_owner_id(lower: str):
    # owner 인증 자체가 전체 접근 권한(설계 §8.1). m.owner_id 로 필터하지 않는다.
    assert "m.owner_id" not in lower


def test_labeler_branch_requires_label_and_media_and_not_completed(lower: str):
    assert "owner_decision = 'label'" in lower
    assert "m.r2_key is not null" in lower
    assert "stage = 'completed'" in lower


def test_labeler_camera_options_match_processable_queue_without_row_limit(lower: str):
    marker = (
        "create or replace function "
        "public.fn_list_motion_clip_labeling_camera_options("
    )
    assert marker in lower
    function_sql = lower.split(marker, 1)[1].split("$$;", 1)[0]
    assert "p_reviewer_id uuid" in function_sql
    assert "select distinct" in function_sql
    assert "t.owner_decision = 'label'" in function_sql
    assert "m.r2_key is not null" in function_sql
    assert "cs.reviewed_by = p_reviewer_id" in function_sql
    assert "cs.stage = 'completed'" in function_sql
    assert " limit " not in function_sql


# ── append-only 감사(events/revisions) ───────────────────────────────
def test_append_only_guards_cover_update_delete_truncate(lower: str):
    assert "tg_op in ('update', 'delete', 'truncate')" in lower
    assert "errcode = '0a000'" in lower


def test_append_only_triggers_bound_to_events_and_revisions(lower: str):
    assert "before update or delete on public.motion_clip_labeling_triage_events" in lower
    assert "before truncate on public.motion_clip_labeling_triage_events" in lower
    assert (
        "before update or delete on public.motion_clip_labeling_session_revisions"
        in lower
    )
    assert (
        "before truncate on public.motion_clip_labeling_session_revisions" in lower
    )


# ── enum CHECK 계약 ──────────────────────────────────────────────────
def test_enum_checks_are_closed(lower: str):
    assert "owner_decision in ('label','hold','skip')" in lower
    assert "stage in ('draft','gt_locked','completed')" in lower
    assert "completion_reason in ('vlm_reviewed','no_prediction')" in lower
    assert (
        "vlm_verdict in ('correct','partially_correct','incorrect','unjudgeable')"
        in lower
    )
    assert (
        "event_type in ('owner_labeled','owner_held','owner_skipped',"
        "'owner_reset','owner_started_labeling')" in lower
    )


def test_decision_note_length_is_10_to_500_when_non_null(lower: str):
    assert "char_length(decision_note) between 10 and 500" in lower


def test_revision_reason_length_is_10_to_500(lower: str):
    assert "char_length(reason) between 10 and 500" in lower


# ── 세션 GT 불변 + (clip, reviewer) 유니크 ───────────────────────────
def test_session_unique_clip_reviewer(lower: str):
    assert "unique (clip_id, reviewed_by)" in lower


def test_initial_gt_is_immutable(lower: str):
    assert "new.initial_gt is distinct from old.initial_gt" in lower
    assert "initial_gt is immutable" in lower


def test_completed_requires_completed_at(lower: str):
    assert "stage <> 'completed'" in lower
    assert "completed_at is not null" in lower


# ── 경합/무결성: row lock + stale + started-session skip ──────────────
def test_row_locks_present(lower: str):
    assert "for update" in lower
    # lock 순서: motion_clips 먼저.
    assert "from public.motion_clips where id = p_clip_id for update" in lower


def test_stale_version_rejection(lower: str):
    assert "stale_state" in lower
    assert "p_expected_updated_at" in lower


def test_started_session_skip_rejection(lower: str):
    assert "labeling_started" in lower


def test_media_unavailable_and_gt_locked_use_distinct_sqlstates(lower: str):
    assert (
        "raise exception 'media_unavailable' using errcode = 'pt422'" in lower
    )
    assert (
        "raise exception 'gt_already_locked' using errcode = 'pt423'" in lower
    )


# ── SECURITY DEFINER 고정 search_path + service_role 전용 EXECUTE ─────
def test_rpcs_have_fixed_search_path(lower: str):
    assert "security definer set search_path = public, pg_temp" in lower


def test_rpcs_execute_is_service_role_only(lower: str):
    for fn in V3_RPCS:
        assert f"function public.{fn}" in lower
    # 각 함수 REVOKE + service_role GRANT.
    assert lower.count("from public, anon, authenticated") >= len(V3_RPCS)
    assert lower.count("to service_role") >= len(V3_RPCS) + len(V3_TABLES)


def test_labeler_camera_options_rpc_execute_is_service_role_only(lower: str):
    signature = "public.fn_list_motion_clip_labeling_camera_options(uuid)"
    assert f"revoke all on function {signature}" in lower
    assert "from public, anon, authenticated" in lower
    assert f"grant execute on function {signature}" in lower
    assert "to service_role" in lower


# ── 금지 도메인 미참조(다른 정본/연구 오염 금지, 설계 §11) ───────────
def test_migration_never_touches_forbidden_domains(lower: str):
    for forbidden in (
        "behavior_labels",
        "local_vlm_evidence",
        "clip_python_evidence",
        "clip_prelabels",
        "clip_activity_assessments",
        "camera_clips",
    ):
        assert forbidden not in lower


def test_forward_only_single_transaction(lower: str):
    assert "begin;" in lower
    assert "commit;" in lower
    # 적용된 기존 마이그레이션을 수정하지 않는 forward-only 신규 파일.
    assert "drop table if exists public.motion_clip_labeling_triage" not in (
        lower.split("-- ── 롤백")[0] if "-- ── 롤백" in lower else lower
    )

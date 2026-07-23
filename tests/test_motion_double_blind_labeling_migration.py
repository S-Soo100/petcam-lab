"""그룹 이중 블라인드 라벨링 forward migration 정적 계약 테스트.

설계 정본: docs/superpowers/specs/2026-07-23-double-blind-labeling-groups-design.md
구현계획:   docs/superpowers/plans/2026-07-23-double-blind-labeling-groups.md Task 2

이 테스트는 마이그레이션 SQL 텍스트만 정적으로 검사한다(라이브 DB 미접속).
목적: preview apply 전에 group/slot/submission/consensus 경계·service-role 전용·
      append-only·blind·경합/무결성 계약을 문자열 토큰 단위로 동결한다. 실제 apply·
      rollback probe 실행은 out-of-scope(Task 8, owner 승인 경계).
"""

import re
from pathlib import Path

import pytest

SQL_PATH = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "2026-07-23_motion_double_blind_labeling.sql"
)

BLIND_TABLES = [
    "motion_labeling_review_groups",
    "motion_labeling_review_group_members",
    "motion_labeling_review_group_cameras",
    "motion_blind_review_cohorts",
    "motion_labeling_reviewer_progress",
    "motion_clip_review_slots",
    "motion_clip_blind_submissions",
    "motion_clip_consensus",
    "motion_clip_consensus_events",
]

BLIND_RPCS = [
    "fn_manage_motion_review_group",
    "fn_ensure_motion_review_slots",
    "fn_list_motion_blind_queue",
    "fn_get_motion_blind_workspace",
    "fn_claim_motion_review_slot",
    "fn_submit_motion_blind_review",
    "fn_finalize_motion_blind_consensus",
    "fn_list_motion_blind_conflicts",
    "fn_resolve_motion_blind_consensus",
    "fn_reassign_motion_review_slot",
    "fn_manage_motion_blind_canary",
]


@pytest.fixture(scope="module")
def sql() -> str:
    return SQL_PATH.read_text()


@pytest.fixture(scope="module")
def lower(sql: str) -> str:
    return sql.lower()


# ── 필수 CREATE TABLE 마커 (계획 Step 1) ─────────────────────────────
def test_required_create_table_markers(sql: str):
    assert "CREATE TABLE public.motion_labeling_review_groups" in sql
    assert "CREATE TABLE public.motion_labeling_reviewer_progress" in sql
    assert "CREATE TABLE public.motion_clip_review_slots" in sql
    assert "CREATE TABLE public.motion_blind_review_cohorts" in sql
    assert "CREATE TABLE public.motion_clip_blind_submissions" in sql
    assert "CREATE TABLE public.motion_clip_consensus" in sql


def test_all_nine_tables_created(lower: str):
    for table in BLIND_TABLES:
        assert f"create table public.{table}" in lower


# ── 정본 FK: motion_clips / cameras / auth.users, camera_clips 금지 ──
def test_references_canonical_sources(lower: str):
    assert "references public.motion_clips(id)" in lower
    assert "references public.cameras(id)" in lower
    assert "references auth.users(id)" in lower
    assert "references public.camera_clips" not in lower


# ── 활성 유일성(멤버·카메라) 부분 유니크 인덱스 ──────────────────────
def test_unique_index_present(sql: str):
    assert "CREATE UNIQUE INDEX" in sql


def test_active_member_and_camera_uniqueness(lower: str):
    assert "where ended_at is null" in lower
    # 활성 멤버는 user 당 하나, 활성 카메라는 카메라 당 하나의 그룹.
    assert "uq_motion_review_member_active" in lower
    assert "uq_motion_review_camera_active" in lower


def test_slot_reviewer_uniqueness(lower: str):
    # clip×reviewer×scope 로 slot 유일. 같은 reviewer 두 slot 금지.
    assert "uq_motion_review_slot_live" in lower
    assert "uq_motion_review_slot_canary" in lower


def test_single_submission_per_slot(lower: str):
    # slot 당 immutable 최초 제출 정확히 1개.
    assert "unique (slot_id)" in lower


# ── cohort 격리(live/canary) ─────────────────────────────────────────
def test_cohort_kind_check_and_live_filter(lower: str):
    assert "cohort_kind in ('live','canary')" in lower
    # 일반 queue/progress/export RPC 는 live 만 읽는다.
    assert "cohort_kind = 'live'" in lower


def test_cohort_status_open_closed_no_delete(lower: str):
    assert "status in ('open','closed')" in lower
    # canary 종료 = status closed 로 UPDATE, row 삭제 아님(설계 §6.3).


# ── comparator 버전 고정 ─────────────────────────────────────────────
def test_comparator_version_literal(sql: str):
    assert "motion-blind-v1" in sql


# ── SECURITY INVOKER + 고정 빈 search_path ───────────────────────────
def test_rpcs_use_security_invoker_empty_search_path(sql: str):
    assert "SET search_path = ''" in sql
    assert "SECURITY INVOKER" in sql
    # SECURITY DEFINER 를 쓰지 않는다(설계 §7).
    assert "SECURITY DEFINER" not in sql


# ── row lock ─────────────────────────────────────────────────────────
def test_row_locks_present(lower: str):
    assert "for update" in lower


# ── service-role 전용: RLS + REVOKE + GRANT ──────────────────────────
def test_submissions_rls_enabled_marker(sql: str):
    assert (
        "ALTER TABLE public.motion_clip_blind_submissions ENABLE ROW LEVEL SECURITY"
        in sql
    )


def test_all_tables_service_role_only(lower: str):
    for table in BLIND_TABLES:
        assert f"alter table public.{table} enable row level security" in lower
        assert f"revoke all on table public.{table} from anon" in lower
        assert f"revoke all on table public.{table} from authenticated" in lower
        assert f"grant all on table public.{table} to service_role" in lower


def test_no_client_policy_or_grant(lower: str):
    assert "create policy" not in lower
    assert "to authenticated" not in lower
    assert "to anon" not in lower


def test_rpcs_execute_service_role_only(lower: str):
    for fn in BLIND_RPCS:
        assert f"function public.{fn}" in lower
    assert "grant execute" in lower
    assert lower.count("to service_role") >= len(BLIND_RPCS) + len(BLIND_TABLES)
    assert lower.count("from public, anon, authenticated") >= len(BLIND_RPCS)


# ── append-only 감사(submissions + consensus events) ─────────────────
def test_append_only_guard_covers_update_delete_truncate(lower: str):
    assert "tg_op in ('update', 'delete', 'truncate')" in lower
    assert "errcode = '0a000'" in lower


def test_append_only_triggers_bound_to_submissions_and_events(lower: str):
    assert (
        "before update or delete on public.motion_clip_blind_submissions" in lower
    )
    assert "before truncate on public.motion_clip_blind_submissions" in lower
    assert (
        "before update or delete on public.motion_clip_consensus_events" in lower
    )
    assert "before truncate on public.motion_clip_consensus_events" in lower


# ── decision / GT shape 계약 ─────────────────────────────────────────
def test_decision_enum_closed(lower: str):
    assert "decision in ('label','hold','exclude')" in lower


def test_reason_code_enum_closed(lower: str):
    assert (
        "reason_code in ('behavior_data','ambiguous','gecko_absent',"
        "'capture_error','media_error')" in lower
    )


def test_label_requires_gt_non_label_forbids_gt(lower: str):
    # label 은 jsonb object GT 필수, 비-label 은 GT NULL(설계 §5.2).
    assert "decision = 'label' and initial_gt is not null" in lower
    assert "jsonb_typeof(initial_gt) = 'object'" in lower
    assert "decision <> 'label' and initial_gt is null" in lower


def test_consensus_status_enum_closed(lower: str):
    assert (
        "status in ('awaiting','agreed','conflict','owner_resolved')" in lower
    )


# ── note 길이 ≤ 2000 (plain text) ────────────────────────────────────
def test_note_length_capped_2000(lower: str):
    assert "char_length(note) <= 2000" in lower


# ── 안정 SQLSTATE 마커 ───────────────────────────────────────────────
def test_stable_sqlstates_present(lower: str):
    # invalid input, not found, forbidden, stale, duplicate submission, append-only
    assert "errcode = '22023'" in lower  # invalid input
    assert "errcode = 'p0002'" in lower  # not found
    assert "errcode = 'pt403'" in lower  # forbidden
    assert "errcode = 'pt409'" in lower  # stale
    assert "errcode = 'pt410'" in lower  # duplicate submission
    assert "errcode = '0a000'" in lower  # append-only


def test_lease_and_group_and_canary_sqlstates(lower: str):
    assert "errcode = 'pt423'" in lower  # slot_in_use (다른 탭 lease)
    assert "errcode = 'pt424'" in lower  # stale/expired lease
    assert "errcode = 'pt425'" in lower  # group invariant (정확히 2인/카메라 중복)
    assert "errcode = 'pt426'" in lower  # owner resolve on non-conflict
    assert "errcode = 'pt427'" in lower  # cohort closed/unknown


# ── 입력 검증: cursor / limit / array-length / uuid ──────────────────
def test_queue_cursor_pairing_validation(lower: str):
    assert "(p_cursor_started_at is null) <> (p_cursor_id is null)" in lower


def test_queue_limit_clamped_1_to_100(lower: str):
    assert "least(greatest(p_limit, 1), 100)" in lower


def test_queue_order_newest_first(lower: str):
    assert "order by m.started_at desc, m.id desc" in lower


def test_array_length_validation(lower: str):
    # canary clip 목록은 1..20, reviewer 목록은 정확히 2(설계 §10.2·계획 Task 6).
    assert "array_length" in lower
    assert "between 1 and 20" in lower


def test_two_active_approved_members_enforced(lower: str):
    # 활성 그룹은 정확히 2인(설계 §2). 관리 RPC 가 approved labeler 인지 확인.
    assert "labeler_applications" in lower
    assert "'approved'" in lower


# ── 결정론 비교 입력은 initial_gt 뿐: current_gt/prediction/evidence 금지 ─
def test_no_prediction_or_evidence_columns(lower: str):
    for forbidden in ("current_gt", "prediction_snapshot", "evidence", "r2_key,"):
        assert forbidden not in lower


# ── 이메일/비밀값 하드코딩 금지 ──────────────────────────────────────
def test_no_email_or_secret_literals(lower: str):
    for forbidden in ("@gmail.com", "@naver.com", "encrypted_password", "service_role_key"):
        assert forbidden not in lower


# ── 금지 도메인 미참조 (legacy v3·VLM·Gate·Evidence 불변) ────────────
def test_never_touches_forbidden_domains(lower: str):
    for forbidden in (
        "behavior_labels",
        "local_vlm_evidence",
        "clip_python_evidence",
        "clip_prelabels",
        "clip_activity_assessments",
        "camera_clips",
        "clip_vlm_jobs",
    ):
        assert forbidden not in lower


# ── 동적 SQL / 사용자 입력 문자열 결합 금지 ──────────────────────────
def test_no_dynamic_sql(lower: str):
    assert "execute format(" not in lower
    assert "execute '" not in lower
    assert "execute e'" not in lower


# ── forward-only 단일 트랜잭션, 기존 migration 미수정 ────────────────
def test_forward_only_single_transaction(lower: str):
    assert "begin;" in lower
    assert "commit;" in lower
    body = lower.split("-- ── 롤백")[0] if "-- ── 롤백" in lower else lower
    for table in BLIND_TABLES:
        assert f"drop table if exists public.{table}" not in body


def test_does_not_recreate_or_edit_v3_tables(lower: str):
    # 기존 v3 정본 테이블/함수를 다시 만들거나 지우지 않는다(계획 Global Constraints).
    assert "create table public.motion_clip_labeling_triage" not in lower
    assert "drop function if exists public.fn_lock_motion_clip_gt" not in lower
    assert "create or replace function public.fn_lock_motion_clip_gt" not in lower


# ── rollback probe 주석 존재 (계획 Step 7) ───────────────────────────
def test_rollback_probe_comments_present(lower: str):
    assert "probe" in lower
    # 활성 2인·중복 카메라·wrong reviewer·중복 submit·stale digest·단일 consensus·
    # canary 격리·append-only·owner resolve on conflict.
    assert "rollback" in lower


# ══════════════════════════════════════════════════════════════════
# 하드닝 (2026-07-24) — 함수 본문 정적 계약 (계획 Task 1·2·5)
# ══════════════════════════════════════════════════════════════════
def function_body(sql: str, name: str) -> str:
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\.{re.escape(name)}\b.*?AS \$\$(.*?)\$\$;",
        sql,
        re.S | re.I,
    )
    assert match is not None, f"missing function: {name}"
    return match.group(1)


# ── Task 1: aggregate 잠금 오류 제거 + live clip ownership 고정 ───────
def test_ensure_does_not_apply_for_update_to_aggregate(sql: str) -> None:
    body = function_body(sql, "fn_ensure_motion_review_slots")
    # aggregate 문장에 FOR UPDATE 를 붙이지 않는다(Postgres 런타임 오류).
    assert not re.search(r"array_agg\([^;]+FOR UPDATE", body, re.S | re.I)
    # 멤버 행 잠금은 별도 문장으로 분리한다.
    assert "PERFORM 1" in body
    assert "ORDER BY user_id" in body
    assert "FOR UPDATE" in body


def test_live_ownership_is_claimed_once_and_slots_never_expand(sql: str) -> None:
    body = function_body(sql, "fn_ensure_motion_review_slots")
    assert "v_owned_group_id" in body
    assert "v_live_slot_count" in body
    assert "live clip must have zero or two slots" in body
    assert "consensus group mismatch" in body


# ── Task 2: 동시 제출 직렬화 + finalize identity ─────────────────────
def test_submit_locks_shared_consensus_before_slot(sql: str) -> None:
    body = function_body(sql, "fn_submit_motion_blind_review")
    # 공통 잠금 순서: consensus row 를 slot 보다 먼저 잠근다(둘째 제출이 첫째 커밋을 보게).
    assert body.index("FROM public.motion_clip_consensus") < body.index(
        "FROM public.motion_clip_review_slots"
    )


def test_finalize_checks_pair_identity_and_distinct_reviewers(sql: str) -> None:
    body = function_body(sql, "fn_finalize_motion_blind_consensus")
    for marker in (
        "v_a.clip_id <> p_clip_id",
        "v_b.clip_id <> p_clip_id",
        "v_a.group_id <> v_b.group_id",
        "v_a.reviewer_id = v_b.reviewer_id",
        "v_a.cohort_kind <> p_cohort_kind",
        "v_b.cohort_kind <> p_cohort_kind",
    ):
        assert marker in body


def test_auto_compared_event_is_transition_only(sql: str) -> None:
    body = function_body(sql, "fn_finalize_motion_blind_consensus")
    assert "v_did_transition boolean := false" in body
    assert "IF v_did_transition THEN" in body

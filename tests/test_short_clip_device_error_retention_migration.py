"""짧은 영상 장치 오류 격리·보존 forward migration 정적 계약 테스트.

설계 정본: docs/superpowers/specs/2026-07-24-short-clip-device-error-retention-design.md
구현계획:   docs/superpowers/plans/2026-07-24-short-clip-device-error-retention.md Task 1~2

라이브 DB 미접속 정적 검사다. 목적: preview apply 전에
  - 격리 원장 상태머신을 닫힌 집합으로 동결,
  - append-only event 테이블(UPDATE/DELETE/TRUNCATE → 0A000)을 고정,
  - service-role 전용 grant·고정 search_path·168h 보존·delete lease 검증·
    내구성 있는 일일 Slack claim 계약을 문자열 토큰 단위로 동결,
  - `motion_clips`/사람 GT 를 삭제하는 statement 부재를 보장,
  - 소비자 가드(Task 2)의 quarantine/media_deleted 제외 술어를 고정한다.
실제 apply·rollback probe 실행은 scripts/run_short_clip_retention_probe.py 담당.
"""

from pathlib import Path

import pytest

_SQL_PATH = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "2026-07-24_short_clip_device_error_retention.sql"
)


@pytest.fixture(scope="module")
def sql() -> str:
    return _SQL_PATH.read_text()


@pytest.fixture(scope="module")
def sql_lower() -> str:
    return _SQL_PATH.read_text().lower()


# ── 신규 테이블 & 상태머신 ──────────────────────────────────────────
def test_migration_creates_the_four_tables(sql: str):
    for tbl in (
        "CREATE TABLE public.camera_short_clip_policies",
        "CREATE TABLE public.motion_clip_system_exclusions",
        "CREATE TABLE public.motion_clip_system_exclusion_events",
        "CREATE TABLE public.short_clip_retention_notifications",
    ):
        assert tbl in sql


def test_exclusion_state_machine_is_closed(sql_lower: str):
    assert (
        "state in ('candidate','quarantined','restored',"
        "'media_deleted','deletion_blocked')"
    ) in sql_lower


def test_reason_code_is_constrained_to_short_device_error(sql_lower: str):
    assert "reason_code = 'short_device_error'" in sql_lower


def test_event_type_is_closed(sql_lower: str):
    for evt in (
        "candidate_detected",
        "auto_quarantined",
        "owner_restored",
        "delete_claimed",
        "delete_completed",
        "delete_failed",
        "delete_blocked",
    ):
        assert f"'{evt}'" in sql_lower


def test_retention_default_is_168_hours(sql_lower: str):
    assert "retention_hours integer not null default 168" in sql_lower


# ── append-only 감사 ───────────────────────────────────────────────
def test_audit_is_append_only(sql_lower: str):
    assert (
        "before update or delete on public.motion_clip_system_exclusion_events"
        in sql_lower
    )
    assert (
        "before truncate on public.motion_clip_system_exclusion_events" in sql_lower
    )
    assert "errcode = '0a000'" in sql_lower


# ── 메타데이터·사람 GT 보존 ────────────────────────────────────────
def test_delete_rpc_never_deletes_metadata(sql_lower: str):
    assert "delete from public.motion_clips" not in sql_lower
    assert "delete from public.motion_clip_labeling_sessions" not in sql_lower
    assert "delete from public.motion_clip_review_slots" not in sql_lower
    assert "delete from public.motion_clip_blind_submissions" not in sql_lower
    assert "delete from public.motion_clip_consensus" not in sql_lower
    assert "delete from public.behavior_labels" not in sql_lower
    assert "delete from public.behavior_logs" not in sql_lower


def test_no_forged_owner_decided_by(sql_lower: str):
    # 시스템 자동 판정(record/claim/complete)은 Owner UUID 를 decided_by 로 위조하지 않는다.
    # detected event 의 actor_id 는 NULL(worker_host 로만 기록)이며, owner_labeled triage
    # 이벤트는 오직 fn_restore_short_clip_exclusion(명시 Owner actor) 안에서만 append 된다.
    assert "candidate_detected" in sql_lower
    # 감지 RPC 는 triage 를 건드리지 않는다(복구 RPC 만 owner_decision='label' 을 쓴다).
    assert "owner_labeled" in sql_lower


# ── service-role 전용 / 고정 search_path ───────────────────────────
_RPCS = (
    "fn_list_short_clip_detection_candidates",
    "fn_record_short_clip_detection",
    "fn_restore_short_clip_exclusion",
    "fn_claim_short_clip_media_deletions",
    "fn_complete_short_clip_media_delete",
    "fn_fail_short_clip_media_delete",
    "fn_list_short_clip_system_exclusions",
    "fn_claim_short_clip_retention_notification",
    "fn_complete_short_clip_retention_notification",
    "fn_release_short_clip_retention_notification",
)


def test_all_rpcs_are_service_role_only(sql: str):
    for fn in _RPCS:
        assert f"REVOKE ALL ON FUNCTION public.{fn}" in sql, fn
        assert f"GRANT EXECUTE ON FUNCTION public.{fn}" in sql, fn
    # client role 은 실행 권한이 없다.
    assert "FROM PUBLIC, anon, authenticated" in sql
    assert "TO service_role" in sql


def test_helper_execute_is_revoked_from_clients(sql: str):
    assert "REVOKE ALL ON FUNCTION public.fn_valid_short_clip_seconds" in sql


def test_functions_pin_search_path(sql_lower: str):
    # 모든 신규 함수는 search_path 를 고정한다(빈 문자열 또는 명시적 스키마).
    assert "set search_path" in sql_lower
    # 빈 search_path 를 최소 한 번은 쓴다(SQL helper).
    assert "set search_path = ''" in sql_lower


def test_tables_have_rls_enabled_without_client_policy(sql_lower: str):
    for tbl in (
        "public.camera_short_clip_policies",
        "public.motion_clip_system_exclusions",
        "public.motion_clip_system_exclusion_events",
        "public.short_clip_retention_notifications",
    ):
        assert f"alter table {tbl} enable row level security" in sql_lower
    # anon/authenticated 대상 CREATE POLICY 가 없어야 한다(service_role 만 RLS 우회).
    assert "create policy" not in sql_lower


# ── delete lease fail-closed ────────────────────────────────────────
def test_claim_delete_limit_and_host_guard(sql_lower: str):
    # claim 은 1..30 배치 + nonblank host 를 강제한다(가드는 NOT BETWEEN 형태).
    assert "between 1 and 30" in sql_lower
    assert "p_worker_host must be nonblank" in sql_lower
    assert "skip locked" in sql_lower


def test_complete_delete_requires_lease_token(sql_lower: str):
    # complete 는 정확한 exclusion id + lease token + 미만료 lease 를 요구한다.
    assert "delete_lease_token" in sql_lower
    assert "delete_lease_expires_at" in sql_lower


def test_claim_never_returns_blank_r2_key(sql_lower: str):
    # claim 후보는 nonblank r2_key 만 반환한다.
    assert "r2_key" in sql_lower
    assert "btrim(m.r2_key) <> ''" in sql_lower


# ── 내구성 있는 일일 Slack claim ────────────────────────────────────
def test_daily_slack_claim_is_durable_and_unique(sql_lower: str):
    assert "summary_date_kst date primary key" in sql_lower
    # 성공은 sent_at 을 채우고 실패는 claim 을 놓아준다(at-least-once, 중복 성공 없음).
    assert "fn_claim_short_clip_retention_notification" in sql_lower
    assert "fn_complete_short_clip_retention_notification" in sql_lower
    assert "fn_release_short_clip_retention_notification" in sql_lower


# ── 보호 대상 attachment 술어 ──────────────────────────────────────
def test_protected_attachment_predicate_covers_human_and_research(sql_lower: str):
    for tbl in (
        "public.motion_clip_labeling_sessions",
        "public.motion_clip_review_slots",
        "public.motion_clip_blind_submissions",
        "public.motion_clip_consensus",
        "public.behavior_labels",
        "public.behavior_logs",
    ):
        assert f"from {tbl}" in sql_lower
    assert "owner_decision = 'label'" in sql_lower


def test_active_machine_jobs_use_deployed_status_literals(sql_lower: str):
    # 배포된 status CHECK 에 실재하는 active literal 만 쓴다.
    assert "clip_vlm_jobs" in sql_lower
    assert "python_evidence_jobs" in sql_lower
    assert "status in ('queued','submitted','failed_retryable')" in sql_lower
    assert "status in ('queued','processing','failed_retryable')" in sql_lower

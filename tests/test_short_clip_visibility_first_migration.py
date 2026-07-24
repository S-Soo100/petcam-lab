"""짧은 오류 영상 visibility-first forward migration 정적 계약 테스트.

설계 정본: docs/superpowers/specs/2026-07-25-short-clip-visibility-first-design.md
구현계획:   docs/superpowers/plans/2026-07-25-short-clip-visibility-first.md Task 1

라이브 DB 미접속 정적 검사다. 목적:
  - 복구 RPC(fn_restore_short_clip_exclusion)가 사람 판정(triage/triage_events/owner_decision)을
    절대 쓰지 않도록 문자열 단위로 동결,
  - 앱 가시성 helper(fn_motion_clip_visible_to_owner)가 terminal 시스템 격리
    (quarantined/media_deleted)만 숨기고 owner+exclusion 만 판정하도록 고정,
  - `own clips select` policy 를 helper 호출로 forward 교체하는지 확인,
  - 물리 삭제 statement 신규 추가 부재를 보장한다.
실제 apply·rollback probe 실행은 scripts/run_short_clip_visibility_first_probe.py 담당.
"""

from pathlib import Path

import pytest

_SQL_PATH = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "2026-07-25_short_clip_visibility_first.sql"
)


@pytest.fixture(scope="module")
def sql() -> str:
    return _SQL_PATH.read_text()


@pytest.fixture(scope="module")
def sql_lower() -> str:
    return _SQL_PATH.read_text().lower()


def _extract_function(sql: str, name: str) -> str:
    """`CREATE OR REPLACE FUNCTION public.<name>` 부터 그 함수의 종료 `$$;` 까지 슬라이스."""
    marker = f"CREATE OR REPLACE FUNCTION public.{name}"
    start = sql.index(marker)
    end = sql.index("$$;", start)
    return sql[start:end]


@pytest.fixture(scope="module")
def function_body(sql: str) -> str:
    return _extract_function(sql, "fn_restore_short_clip_exclusion")


# ── 계획 Task 1 필수 계약 ───────────────────────────────────────────
def test_restore_never_writes_human_triage(function_body: str):
    # 복구 RPC 는 사람 triage 원장/이벤트/owner_decision 을 절대 lock/읽기/쓰기 하지 않는다.
    assert "motion_clip_labeling_triage " not in function_body
    assert "motion_clip_labeling_triage_events" not in function_body
    assert "owner_decision" not in function_body


def test_app_visibility_hides_only_terminal_system_exclusions(sql_lower: str):
    assert "fn_motion_clip_visible_to_owner" in sql_lower
    assert "state in ('quarantined','media_deleted')" in sql_lower
    assert 'alter policy "own clips select"' in sql_lower


def test_physical_delete_not_added(sql_lower: str):
    assert "delete from public.motion_clips" not in sql_lower
    assert "delete from public.motion_clip_system_exclusions" not in sql_lower


# ── forward-only + 함수 계약 추가 동결 ──────────────────────────────
def test_migration_is_forward_only_create_or_replace(sql: str):
    # 07-24 원본 함수 이름을 유지하되 forward CREATE OR REPLACE 로만 교체한다(DROP 금지).
    assert "CREATE OR REPLACE FUNCTION public.fn_restore_short_clip_exclusion" in sql
    assert "CREATE OR REPLACE FUNCTION public.fn_motion_clip_visible_to_owner" in sql
    assert "DROP FUNCTION" not in sql.upper()
    # 07-24 에 이미 적용된 테이블/트리거를 재정의하지 않는다.
    assert "CREATE TABLE" not in sql.upper()


def test_restore_preserves_state_guards(function_body: str):
    # media_deleted PT428, non-quarantined PT409, lease PT409, 없음 PT409 를 보존한다.
    assert "PT428" in function_body
    assert function_body.count("PT409") >= 3
    assert "delete lease active" in function_body
    # 시스템 원장만 restored 로 전환하고 owner_restored 감사 1건을 남긴다.
    assert "SET state = 'restored'" in function_body
    assert "'owner_restored'" in function_body


def test_visibility_helper_is_security_definer_stable_pinned(sql_lower: str):
    # helper 는 SECURITY DEFINER · STABLE · 고정 빈 search_path 이며 auth.uid() 로 owner 를 판정한다.
    body = sql_lower[sql_lower.index("fn_motion_clip_visible_to_owner"):]
    body = body[: body.index("$$;")]
    assert "security definer" in body
    assert "stable" in body
    assert "set search_path = ''" in body
    assert "auth.uid()" in body
    # boolean 만 반환하고 raw exclusion 컬럼(rule/actor/r2)을 노출하지 않는다.
    assert "returns boolean" in body
    for leak in ("rule_version", "delete_lease_token", "r2_key", "actor_id"):
        assert leak not in body, leak


def test_visibility_helper_execute_grant_is_client_scoped(sql: str):
    assert (
        "REVOKE ALL ON FUNCTION public.fn_motion_clip_visible_to_owner(uuid,uuid)"
        in sql
    )
    assert (
        "GRANT EXECUTE ON FUNCTION public.fn_motion_clip_visible_to_owner(uuid,uuid)"
        in sql
    )
    # RLS USING 식은 querying role 로 실행되므로 authenticated 가 helper 실행권을 가져야 한다.
    assert "TO authenticated, service_role" in sql


def test_delete_policy_and_delete_pipeline_untouched(sql_lower: str):
    # SELECT policy 만 교체하고 DELETE policy·삭제 lease RPC 는 이 migration 에서 건드리지 않는다.
    assert "alter policy \"own clips delete\"" not in sql_lower
    assert "fn_claim_short_clip_media_deletions" not in sql_lower
    assert "short_clip_retention_delete_enabled" not in sql_lower

"""권한별 라벨링 웹 읽기 모델 forward migration 정적 계약 테스트.

설계 정본: docs/superpowers/specs/2026-07-24-role-based-labeling-web-design.md
구현계획:   docs/superpowers/plans/2026-07-24-role-based-labeling-web.md Task 2

이 테스트는 마이그레이션 SQL 텍스트만 정적으로 검사한다(라이브 DB 미접속).
목적: preview apply 전에 읽기 전용 RPC 세 개의 service-role 전용·write 부재·
      확정 전 라벨 은닉(blind) 계약을 문자열 토큰 단위로 동결한다. 실제 apply·
      rollback probe 실행은 out-of-scope(Preview Deployment Gate, owner 승인 경계).
"""

from pathlib import Path

SQL = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "2026-07-24_role_based_labeling_reads.sql"
).read_text()

READ_FUNCTIONS = (
    "fn_list_motion_blind_history",
    "fn_list_motion_labeling_library",
    "fn_get_motion_blind_owner_overview",
)


def test_read_functions_are_service_role_only():
    for fn in READ_FUNCTIONS:
        assert f"REVOKE ALL ON FUNCTION public.{fn}" in SQL
        assert "FROM PUBLIC, anon, authenticated" in SQL
        assert f"GRANT EXECUTE ON FUNCTION public.{fn}" in SQL
        assert "TO service_role" in SQL


def test_no_write_statements_inside_read_functions():
    bodies = SQL.split("-- READ FUNCTION BODY")
    assert len(bodies) == 4
    for body in bodies[1:]:
        upper = body.split("-- END READ FUNCTION BODY", 1)[0].upper()
        for forbidden in ("INSERT INTO", "UPDATE PUBLIC.", "DELETE FROM", "TRUNCATE"):
            assert forbidden not in upper


def test_library_hides_pending_labels():
    assert "WHEN consensus_status IN ('agreed','owner_resolved')" in SQL
    assert "WHEN consensus_status = 'conflict' THEN 'owner_review'" in SQL
    assert "WHEN consensus_status = 'awaiting' THEN 'awaiting'" in SQL
    assert "ELSE NULL::jsonb" in SQL

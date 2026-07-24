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


def test_library_canary_scope_precedence_and_re_review():
    # review-fix P0-1: 과거 clip 이 open canary 에 편입되면 canary consensus 를 먼저 보고
    # legacy 정답을 숨긴다. clip 이 여러 canary 에 들어갈 수 있으므로 open 우선 + 최신 순으로
    # 결정론적 scope 하나를 고른다.
    assert "public.motion_blind_review_cohorts co ON co.id=cc.cohort_id" in SQL
    assert "WHERE cc.clip_id=m.id AND cc.cohort_kind='canary'" in SQL
    assert "ORDER BY (co.status='open') DESC, co.created_at DESC, cc.id DESC" in SQL
    # canary awaiting/conflict → re_review(과거 GT 은닉), agreed/owner_resolved → canary final 공개.
    assert "WHEN canary_status IN ('agreed','owner_resolved') THEN 'final'" in SQL
    assert "WHEN canary_status IN ('awaiting','conflict') THEN 're_review'" in SQL
    # live consensus 는 canary scope 가 없을 때만 본다.
    assert "WHEN live_status IN ('agreed','owner_resolved') THEN 'final'" in SQL
    assert "WHEN live_status = 'conflict' THEN 'owner_review'" in SQL
    assert "WHEN live_status = 'awaiting' THEN 'awaiting'" in SQL


def test_library_final_fields_null_unless_publishing_state():
    # final_decision/final_gt 는 canary/live agreed·owner_resolved 또는 legacy 일 때만 non-null.
    # 확정 전(re_review/awaiting/owner_review) blind scope 는 항상 null.
    assert "WHEN canary_status IS NOT NULL THEN NULL::text" in SQL
    assert "WHEN live_status IS NOT NULL THEN NULL::text" in SQL
    assert "WHEN canary_status IS NOT NULL THEN NULL::jsonb" in SQL
    assert "WHEN live_status IS NOT NULL THEN NULL::jsonb" in SQL
    assert "ELSE NULL::jsonb" in SQL


def test_library_server_side_final_decision_filter():
    # review-fix P1-2: final_decision 을 classified 뒤·keyset/limit 전에 서버에서 적용한다.
    assert "p_final_decision text DEFAULT NULL" in SQL
    assert "p_final_decision NOT IN ('label','hold','exclude')" in SQL
    assert "p_final_decision IS NULL OR c.public_decision=p_final_decision" in SQL


def test_library_re_review_state_allowlisted():
    assert "NOT IN ('final','awaiting','owner_review','unlabeled','re_review')" in SQL


def test_ambiguous_column_qualified_with_classified_alias():
    # review-fix P1-1: outer SELECT/WHERE/ORDER BY 를 classified c 로 한정해
    # RETURNS TABLE 출력 변수(camera_id 등)와의 이름 충돌(ambiguous)을 제거한다.
    assert "FROM classified c" in SQL
    assert "ORDER BY c.started_at DESC, c.id DESC" in SQL


def test_page_fetch_cap_allows_lookahead_101():
    # review-fix P1-2: API 는 최대 100 을 노출하고 has_more 판정용 lookahead 1 을 더해
    # p_limit=101 을 요청한다. RPC 가 100 으로 자르면 has_more 가 영원히 false 가 되므로
    # history·library 두 함수의 fetch cap 을 101 로 올린다.
    assert SQL.count("LIMIT LEAST(GREATEST(p_limit,1),101)") >= 2
    assert "LIMIT LEAST(GREATEST(p_limit,1),100)" not in SQL


def test_owner_overview_canary_has_slot_total_denominator():
    # review-fix P1-3: open canary 진행률 분모는 slot_total(= 2×clip_total when 2 reviewers)이라야
    # submitted_total/slot_total ≤ 1 이 된다. clip_total 분모는 최대 2× 를 넘겨 잘못된 진행률이다.
    assert "'slot_total', (SELECT count(*) FROM public.motion_clip_review_slots s" in SQL


def test_library_grants_updated_for_new_signature():
    # review-fix: p_final_decision 추가로 함수 signature 가 바뀌었으므로 REVOKE/GRANT 도 갱신한다.
    sig = (
        "uuid, uuid, text, uuid[], timestamptz, timestamptz, "
        "text, text, text, text, timestamptz, uuid, integer"
    )
    assert sig in SQL

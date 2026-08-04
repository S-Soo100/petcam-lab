"""진행 중 교차검수 변화와 완료 source 불변 digest를 분리하는 후속 migration 계약."""

from pathlib import Path

SQL_PATH = Path(
    "migrations/2026-08-04_motion_clip_canonical_gt_audit_digest_scope.sql"
)


def test_audit_digest_scope_migration_is_additive_and_final_only() -> None:
    sql = SQL_PATH.read_text(encoding="utf-8").lower()
    assert "create or replace function public.fn_audit_motion_clip_canonical_gt()" in sql
    assert "c.cohort_kind = 'live'" in sql
    assert "c.status in ('agreed', 'owner_resolved')" in sql
    assert "(c.final_decision <> 'label' or c.final_gt is not null)" in sql
    assert "s.stage = 'completed'" in sql
    assert "coalesce(s.current_gt, s.initial_gt) is not null" in sql
    assert "'source_mutation_digest'" in sql
    assert "'workflow_observation_digest'" in sql
    for forbidden in (
        "update public.motion_clip_consensus",
        "delete from public.motion_clip_consensus",
        "update public.motion_clip_labeling_sessions",
        "delete from public.motion_clip_labeling_sessions",
    ):
        assert forbidden not in sql

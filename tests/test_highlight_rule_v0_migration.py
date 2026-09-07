"""highlight rule v0 migration 정적 계약. SQL 텍스트만 검사한다(PG 불필요)."""

import re
from pathlib import Path

import pytest

SQL_PATH = Path(__file__).resolve().parent.parent / "migrations" / "2026-09-08_highlight_rule_v0.sql"

TABLES = (
    "highlight_rule_versions",
    "highlight_rule_activation_events",
    "motion_clip_highlight_verdicts",
)
FUNCTIONS = {
    "fn_highlight_rule_eval": "(public.gme_runs, jsonb)",
    "fn_get_active_highlight_rule": "()",
    "fn_highlight_initial": "(uuid, text, text, text)",
    "fn_highlight_current": "(uuid, text, text, text)",
    "fn_submit_highlight_verdict": "(uuid, uuid, boolean, boolean, text, text, text, text, text)",
    "fn_create_highlight_rule_version": "(text, jsonb, text, uuid)",
    "fn_activate_highlight_rule_version": "(text, uuid)",
    "fn_highlight_rule_stats": "(timestamptz, timestamptz)",
}


@pytest.fixture()
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def test_tables_are_private_and_append_only(sql: str) -> None:
    n = norm(sql)
    for table in TABLES:
        assert f"create table public.{table}" in n
        assert f"alter table public.{table} enable row level security" in n
        assert f"revoke all on public.{table} from public, anon, authenticated, service_role" in n
        assert f"before update or delete on public.{table}" in n
        assert f"before truncate on public.{table}" in n
    assert "create policy" not in n


def test_verdict_shape_locks_one_initial_per_clip(sql: str) -> None:
    n = norm(sql)
    assert "kind text not null check (kind in ('initial','correction'))" in n
    assert "create unique index uq_motion_clip_highlight_verdict_initial on public.motion_clip_highlight_verdicts (clip_id) where kind = 'initial'" in n
    assert "check ((initial is null and changed is null) or (changed = (initial <> verdict)))" in n
    assert "change_reason is null or change_reason in ('false_detection','gecko_not_visible','camera_shake','too_short','interesting_low_numbers','other')" in n
    assert "rule_version text not null references public.highlight_rule_versions(version)" in n


def test_rule_versions_are_versioned_and_seeded_v0(sql: str) -> None:
    n = norm(sql)
    assert "version text primary key check (version ~ '^hl-rule-v[0-9]+$')" in n
    assert "jsonb_typeof(params->'triggers') = 'array'" in n
    assert "'hl-rule-v0'" in n
    assert '"name": "long_activity", "on": true, "activity_sec_gte": 10' in sql
    assert '"name": "sustained_move", "on": true, "longest_sec_gte": 5' in sql
    assert '"name": "frequent_bursts", "on": false' in sql
    assert '"name": "early_action", "on": false' in sql
    assert "insert into public.highlight_rule_activation_events" in n


def test_eval_reads_exact_features_and_fails_closed_on_unknown_trigger(sql: str) -> None:
    n = norm(sql)
    assert "i->>'state' = 'moving'" in n
    assert "when 'long_activity' then" in n
    assert "when 'sustained_move' then" in n
    assert "when 'frequent_bursts' then" in n
    assert "when 'early_action' then" in n
    assert "unknown highlight trigger" in n and "errcode = '22023'" in n
    assert "'게코 미관측'" in sql


def test_eval_validates_required_numeric_keys_by_name(sql: str) -> None:
    # AND 단락 때문에 frequent_bursts 의 bursts_gte 누락이 통과하던 구멍 — 키를 이름으로 명시 검사한다.
    n = norm(sql)
    assert "when 'long_activity' then array['activity_sec_gte']" in n
    assert "when 'sustained_move' then array['longest_sec_gte']" in n
    assert "when 'frequent_bursts' then array['activity_sec_gte', 'bursts_gte']" in n
    assert "when 'early_action' then array['first_move_sec_lte']" in n
    assert "jsonb_typeof(v_trigger->v_key) is distinct from 'number'" in n
    assert "requires numeric parameter" in n


def test_activate_existing_version_appends_event_only(sql: str) -> None:
    n = norm(sql)
    body = n.split("create function public.fn_activate_highlight_rule_version(")[1].split("$$;")[0]
    assert "unknown highlight rule version" in body and "errcode = 'p0002'" in body
    assert "insert into public.highlight_rule_activation_events" in body
    assert "insert into public.highlight_rule_versions" not in body
    assert "security definer set search_path = ''" in body


def test_initial_uses_exact_identity_rpc_without_fallback(sql: str) -> None:
    n = norm(sql)
    assert "public.fn_get_gme_observed_moving_time_v2(p_clip_id, p_engine_schema_version, p_algorithm_version, p_detector_identity)" in n
    assert "errcode = 'pt428'" in n  # active rule 없음
    for status in ("'decided'", "'pending'", "'failed'"):
        assert status in sql


def test_submit_enforces_reviewer_and_lock(sql: str) -> None:
    n = norm(sql)
    # 운영 적격 가드(2026-08-06)로 test/격리/삭제 clip 확정을 막고, 미존재와 같은 P0002 로 접는다.
    assert "if to_regprocedure('public.fn_is_motion_clip_production_labeling_eligible(uuid)') is null" in n
    body = n.split("create function public.fn_submit_highlight_verdict(")[1].split("$$;")[0]
    assert "if not public.fn_is_motion_clip_production_labeling_eligible(p_clip_id) then" in body
    assert "select 1 from public.motion_clips c where c.id = p_clip_id" not in body
    assert "from public.labelers l where l.user_id = p_reviewer_id" in n
    assert "errcode = 'pt403'" in n
    assert "when unique_violation then" in n and "errcode = 'pt409'" in n
    assert "p_kind = 'correction' and not p_is_owner" in n


def test_stats_expose_decided_count_as_kept_ratio_denominator(sql: str) -> None:
    n = norm(sql)
    body = n.split("create function public.fn_highlight_rule_stats(")[1].split("$$;")[0]
    assert "decided_count bigint" in body
    assert "count(*) filter (where v.initial is not null)::bigint" in body


def test_functions_have_expected_signatures_and_privileges(sql: str) -> None:
    n = norm(sql)
    for name, sig in FUNCTIONS.items():
        # CREATE FUNCTION 은 파라미터 이름을 포함하므로(plpgsql 본문이 이름을 씀) 존재만 확인하고,
        # 정확한 시그니처는 이름 없는 REVOKE/GRANT 줄로 잠근다.
        assert f"create function public.{name}(" in n, name
        assert f"revoke all on function public.{name}{sig} from public, anon, authenticated".replace(" ", "") in n.replace(" ", ""), name
        assert f"grant execute on function public.{name}{sig} to service_role".replace(" ", "") in n.replace(" ", ""), name
    assert re.search(r"security definer set search_path\s*=\s*''", n)


def test_migration_never_mutates_existing_ledgers(sql: str) -> None:
    n = norm(sql)
    for table in ("gme_runs", "gme_jobs", "motion_clips", "motion_clip_consensus", "motion_clip_blind_submissions"):
        assert f"update public.{table}" not in n
        assert f"delete from public.{table}" not in n
        assert f"alter table public.{table}" not in n

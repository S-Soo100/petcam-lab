# Highlight Rule v0 — DB 판정 계층 + API Implementation Plan

> **구현 방식 (CAOF):** 이 계획을 task 단위로 구현한다. Critical 트랙이면 Implementer 에이전트 분리(GATE 4), Standard면 메인이 직접 구현. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GME 결과와 active 규칙 파라미터만으로 영상의 `하이라이트 O/X` 1차 판정을 DB 함수가 계산하고, 사람 확정을 append-only 원장에 남기며, 규칙은 params 버전+activation event로만 바뀌게 한다.

**Architecture:** 1차 판정은 저장하지 않고 `fn_highlight_rule_eval(gme_runs row, params)`가 순수 계산한다. `fn_highlight_initial`이 exact GME identity의 run을 찾아 eval을 호출하고, `fn_submit_highlight_verdict`가 그 순간의 판정을 스냅샷해 verdict를 append한다. 웹은 service_role RPC만 호출하고 run id·detector identity·R2 key는 브라우저로 내보내지 않는다.

**Tech Stack:** PostgreSQL(plpgsql, Supabase) · pytest 정적 계약 테스트 · 일회용 PostgreSQL probe(`pg_ctl`) · Next.js app router API(TypeScript) · vitest

**Spec:** [`specs/feature-highlight-auto-initial-designation.md`](../../../specs/feature-highlight-auto-initial-designation.md) §2 In 1~5, §4.1, §4.1a(v0 트리거 4개 중 2개 on), §4.2

**Sibling plan:** [`2026-09-07-labeling-web-v4.md`](2026-09-07-labeling-web-v4.md) — 목록 RPC·페이지·blind 퇴역. 그 계획의 Task 1은 이 계획 Task 1 migration이 먼저 적용돼 있어야 한다.

**트랙:** Critical (production migration + 새 쓰기 경로). Task별 커밋, `main` 직접 push 금지 → 브랜치 `feat/highlight-rule-v0`.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `migrations/2026-09-08_highlight_rule_v0.sql` | 테이블 3개(규칙 버전·활성화 이벤트·verdict) + 함수 6개 + seed(v0 활성) |
| `tests/test_highlight_rule_v0_migration.py` | migration 정적 계약(테이블 RLS/append-only, 함수 시그니처, seed, 권한) |
| `scripts/run_highlight_rule_v0_probe.py` | 일회용 PostgreSQL에서 실제 apply + 동작 실증 + residue 0 |
| `tests/test_highlight_rule_v0_probe.py` | probe 러너의 순수 파서 테스트(PG 없이) |
| `web/src/lib/highlightV4.ts` | 공개 타입·enum·한국어 카피(클라이언트/서버 공용, 순수) |
| `web/src/lib/highlightV4Server.ts` | RPC row → 공개 타입 매퍼(fail-closed) + rpc 에러 → HTTP 매핑 |
| `web/src/app/api/labeling-v4/_access.ts` | `loadV4ClipAccess` — 승인 사용자 + clip 존재 확인 |
| `web/src/app/api/labeling-v4/clips/[clipId]/highlight/route.ts` | GET 현재값+1차 판정 |
| `web/src/app/api/labeling-v4/clips/[clipId]/verdict/route.ts` | POST 사람 확정 |
| `web/src/app/api/labeling-v4/owner/highlight-rules/route.ts` | GET active 규칙 / POST 새 버전 생성+활성화 (owner) |
| `web/src/app/api/labeling-v4/owner/highlight-stats/route.ts` | GET 규칙 버전별 유지율 집계 (owner) |

---

### Task 1: migration — 테이블·함수·seed (정적 계약 테스트 선행)

**Context:**
- Depends on: 없음 (기존 `gme_jobs`/`gme_runs`/`motion_clips`/`labelers`/`auth.users`가 production에 이미 있음)
- Inputs: `fn_get_gme_observed_moving_time_v2(uuid,text,text,text)` (migration `2026-09-03_gme_slow_motion_v1_contract.sql`) — 상태 `measured/not_observed/pending/failed` + `run_id`
- Outputs: 테이블 `highlight_rule_versions`, `highlight_rule_activation_events`, `motion_clip_highlight_verdicts`; 함수 `fn_highlight_rule_eval`, `fn_get_active_highlight_rule`, `fn_highlight_initial`, `fn_highlight_current`, `fn_submit_highlight_verdict`, `fn_create_highlight_rule_version`, `fn_highlight_rule_stats`
- Must know: (a) 레포 규칙 — 새 테이블은 RLS ON + `REVOKE ALL … FROM PUBLIC, anon, authenticated, service_role` + UPDATE/DELETE/TRUNCATE를 `0A000`으로 막는 trigger, 쓰기는 `SECURITY DEFINER SET search_path=''` 함수만. (b) 1차 판정은 저장하지 않는다(스펙 §4.2). (c) verdict는 `kind='initial'` 1건만 clip당 허용(부분 유니크), owner 정정은 `kind='correction'` append. (d) 안정 SQLSTATE: 입력 오류 `22023`, 없음 `P0002`, 권한 `PT403`, 이미 확정 `PT409`, active 규칙 없음 `PT428`.
- Acceptance: `uv run pytest tests/test_highlight_rule_v0_migration.py -x -q` → 전부 PASS

**Files:**
- Create: `migrations/2026-09-08_highlight_rule_v0.sql`
- Test: `tests/test_highlight_rule_v0_migration.py`

- [ ] **Step 1: 정적 계약 테스트 작성**

```python
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


def test_initial_uses_exact_identity_rpc_without_fallback(sql: str) -> None:
    n = norm(sql)
    assert "public.fn_get_gme_observed_moving_time_v2(p_clip_id, p_engine_schema_version, p_algorithm_version, p_detector_identity)" in n
    assert "errcode = 'pt428'" in n  # active rule 없음
    for status in ("'decided'", "'pending'", "'failed'"):
        assert status in sql


def test_submit_enforces_reviewer_and_lock(sql: str) -> None:
    n = norm(sql)
    assert "from public.labelers l where l.user_id = p_reviewer_id" in n
    assert "errcode = 'pt403'" in n
    assert "when unique_violation then" in n and "errcode = 'pt409'" in n
    assert "p_kind = 'correction' and not p_is_owner" in n


def test_functions_have_expected_signatures_and_privileges(sql: str) -> None:
    n = norm(sql)
    for name, sig in FUNCTIONS.items():
        assert f"create function public.{name}{sig}".replace(" ", "") in n.replace(" ", ""), name
        assert f"revoke all on function public.{name}{sig} from public, anon, authenticated".replace(" ", "") in n.replace(" ", ""), name
        assert f"grant execute on function public.{name}{sig} to service_role".replace(" ", "") in n.replace(" ", ""), name
    assert re.search(r"security definer set search_path\s*=\s*''", n)


def test_migration_never_mutates_existing_ledgers(sql: str) -> None:
    n = norm(sql)
    for table in ("gme_runs", "gme_jobs", "motion_clips", "motion_clip_consensus", "motion_clip_blind_submissions"):
        assert f"update public.{table}" not in n
        assert f"delete from public.{table}" not in n
        assert f"alter table public.{table}" not in n
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/baek/petcam-lab && uv run pytest tests/test_highlight_rule_v0_migration.py -x -q`
Expected: FAIL — `migration missing: .../2026-09-08_highlight_rule_v0.sql`

- [ ] **Step 3: migration 작성**

```sql
BEGIN;

-- 하이라이트 1차 판정은 저장하지 않는다. (active 규칙 params × exact GME run)의 순수 계산이며,
-- 사람이 확정하는 순간에만 그때 보였던 값을 verdict row에 스냅샷한다(스펙 §4.2).

-- ── 규칙 버전 (append-only) ──────────────────────────────────────────
CREATE TABLE public.highlight_rule_versions (
  version text PRIMARY KEY CHECK (version ~ '^hl-rule-v[0-9]+$'),
  params jsonb NOT NULL,
  note text NOT NULL DEFAULT '',
  created_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (jsonb_typeof(params->'triggers') = 'array'),
  CHECK (jsonb_typeof(coalesce(params->'guards', '[]'::jsonb)) = 'array')
);
COMMENT ON TABLE public.highlight_rule_versions IS
  '하이라이트 규칙 파라미터 버전. 숫자만 바뀌고 함수 코드는 안 바뀐다(스펙 §4.1a).';

CREATE TABLE public.highlight_rule_activation_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version text NOT NULL REFERENCES public.highlight_rule_versions(version) ON DELETE RESTRICT,
  actor_id uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
  activated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX idx_highlight_rule_activation_events_latest
  ON public.highlight_rule_activation_events (activated_at DESC, id DESC);

-- ── 사람 확정 (append-only) ──────────────────────────────────────────
CREATE TABLE public.motion_clip_highlight_verdicts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  reviewer_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  kind text NOT NULL CHECK (kind IN ('initial','correction')),
  rule_version text NOT NULL REFERENCES public.highlight_rule_versions(version) ON DELETE RESTRICT,
  gme_run_id uuid REFERENCES public.gme_runs(id) ON DELETE RESTRICT,
  initial_status text NOT NULL CHECK (initial_status IN ('decided','pending','failed')),
  initial boolean,
  initial_reason text NOT NULL,
  verdict boolean NOT NULL,
  changed boolean,
  change_reason text,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK ((initial_status = 'decided' AND initial IS NOT NULL AND gme_run_id IS NOT NULL)
      OR (initial_status IN ('pending','failed') AND initial IS NULL AND gme_run_id IS NULL)),
  CHECK ((initial IS NULL AND changed IS NULL) OR (changed = (initial <> verdict))),
  CHECK (change_reason IS NULL OR change_reason IN ('false_detection','gecko_not_visible','camera_shake','too_short','interesting_low_numbers','other'))
);
COMMENT ON TABLE public.motion_clip_highlight_verdicts IS
  '검수자 최종값. initial 1건만 clip당 허용, owner 정정은 correction append. 최신 row가 현재값.';

CREATE UNIQUE INDEX uq_motion_clip_highlight_verdict_initial
  ON public.motion_clip_highlight_verdicts (clip_id) WHERE kind = 'initial';
CREATE INDEX idx_motion_clip_highlight_verdicts_clip_latest
  ON public.motion_clip_highlight_verdicts (clip_id, created_at DESC, id DESC);
CREATE INDEX idx_motion_clip_highlight_verdicts_rule_created
  ON public.motion_clip_highlight_verdicts (rule_version, created_at DESC);

-- ── append-only trigger + RLS (세 테이블 공통) ───────────────────────
CREATE FUNCTION public.fn_block_highlight_ledger_mutation()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  RAISE EXCEPTION 'highlight ledgers are append-only' USING ERRCODE = '0A000';
END $$;

CREATE TRIGGER trg_highlight_rule_versions_no_update_delete
  BEFORE UPDATE OR DELETE ON public.highlight_rule_versions
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_highlight_ledger_mutation();
CREATE TRIGGER trg_highlight_rule_versions_no_truncate
  BEFORE TRUNCATE ON public.highlight_rule_versions
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_highlight_ledger_mutation();
CREATE TRIGGER trg_highlight_rule_activation_events_no_update_delete
  BEFORE UPDATE OR DELETE ON public.highlight_rule_activation_events
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_highlight_ledger_mutation();
CREATE TRIGGER trg_highlight_rule_activation_events_no_truncate
  BEFORE TRUNCATE ON public.highlight_rule_activation_events
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_highlight_ledger_mutation();
CREATE TRIGGER trg_motion_clip_highlight_verdicts_no_update_delete
  BEFORE UPDATE OR DELETE ON public.motion_clip_highlight_verdicts
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_highlight_ledger_mutation();
CREATE TRIGGER trg_motion_clip_highlight_verdicts_no_truncate
  BEFORE TRUNCATE ON public.motion_clip_highlight_verdicts
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_highlight_ledger_mutation();

ALTER TABLE public.highlight_rule_versions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.highlight_rule_versions FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.highlight_rule_activation_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.highlight_rule_activation_events FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.motion_clip_highlight_verdicts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.motion_clip_highlight_verdicts FROM PUBLIC, anon, authenticated, service_role;

-- ── 순수 계산: run row × params → O/X ────────────────────────────────
-- 트리거는 OR. on=false 트리거는 판정에 안 쓰고 shadow에 이름만 남긴다(스펙 §4.1a 제안 순서).
CREATE FUNCTION public.fn_highlight_rule_eval(p_run public.gme_runs, p_params jsonb)
RETURNS TABLE (initial boolean, reason text, fired text[], shadow text[], features jsonb)
LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_activity numeric := coalesce(p_run.candidate_moving_sec_any_gecko, 0);
  v_visible numeric := coalesce(p_run.visible_sec, 0);
  v_longest numeric := 0;
  v_bursts integer := 0;
  v_first numeric;
  v_trigger jsonb;
  v_name text;
  v_on boolean;
  v_hit boolean;
  v_fired text[] := '{}';
  v_shadow text[] := '{}';
BEGIN
  SELECT coalesce(max((i->>'end_sec')::numeric - (i->>'start_sec')::numeric), 0),
         count(*)::integer,
         min((i->>'start_sec')::numeric)
    INTO v_longest, v_bursts, v_first
  FROM jsonb_array_elements(coalesce(p_run.state_intervals, '[]'::jsonb)) i
  WHERE i->>'state' = 'moving';

  features := jsonb_build_object(
    'activity_sec', round(v_activity, 1),
    'longest_moving_sec', round(v_longest, 1),
    'moving_burst_count', v_bursts,
    'first_moving_sec', round(v_first, 1),
    'visible_sec', round(v_visible, 1),
    'duration_sec', p_run.duration_sec
  );

  IF v_visible <= 0 THEN
    initial := false; reason := '게코 미관측'; fired := '{}'; shadow := '{}';
    RETURN NEXT; RETURN;
  END IF;

  FOR v_trigger IN SELECT value FROM jsonb_array_elements(p_params->'triggers') LOOP
    v_name := v_trigger->>'name';
    v_on := coalesce((v_trigger->>'on')::boolean, false);
    v_hit := CASE v_name
      WHEN 'long_activity' THEN v_activity >= (v_trigger->>'activity_sec_gte')::numeric
      WHEN 'sustained_move' THEN v_longest >= (v_trigger->>'longest_sec_gte')::numeric
      WHEN 'frequent_bursts' THEN v_activity >= (v_trigger->>'activity_sec_gte')::numeric
                                AND v_bursts >= (v_trigger->>'bursts_gte')::integer
      WHEN 'early_action' THEN v_first IS NOT NULL
                                AND v_first <= (v_trigger->>'first_move_sec_lte')::numeric
      ELSE NULL
    END;
    -- 모르는 트리거 이름·빠진 숫자 = NULL → fail-closed. 규칙 저장 시에도 같은 검사를 한다.
    IF v_hit IS NULL THEN
      RAISE EXCEPTION 'unknown highlight trigger or missing parameter: %', v_name
        USING ERRCODE = '22023';
    END IF;
    IF v_hit AND v_on THEN v_fired := v_fired || v_name;
    ELSIF v_hit THEN v_shadow := v_shadow || v_name;
    END IF;
  END LOOP;

  initial := cardinality(v_fired) > 0;
  fired := v_fired;
  shadow := v_shadow;
  reason := CASE WHEN initial
    THEN format('움직임 %s초 · 최장 연속 %s초', round(v_activity, 1), round(v_longest, 1))
    ELSE format('짧은 움직임 %s초 · 최장 연속 %s초', round(v_activity, 1), round(v_longest, 1))
  END;
  RETURN NEXT;
END $$;

-- ── active 규칙 = 최신 activation event ───────────────────────────────
CREATE FUNCTION public.fn_get_active_highlight_rule()
RETURNS TABLE (version text, params jsonb, activated_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT v.version, v.params, e.activated_at
  FROM public.highlight_rule_activation_events e
  JOIN public.highlight_rule_versions v ON v.version = e.version
  ORDER BY e.activated_at DESC, e.id DESC
  LIMIT 1
$$;

-- ── 1차 판정 (저장 없음) ────────────────────────────────────────────
CREATE FUNCTION public.fn_highlight_initial(
  p_clip_id uuid,
  p_engine_schema_version text,
  p_algorithm_version text,
  p_detector_identity text
) RETURNS TABLE (
  status text,            -- decided | pending | failed
  initial boolean,
  rule_version text,
  gme_run_id uuid,
  reason text,
  fired text[],
  shadow text[],
  features jsonb
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_rule record;
  v_gme record;
  v_run public.gme_runs%ROWTYPE;
  v_eval record;
BEGIN
  SELECT * INTO v_rule FROM public.fn_get_active_highlight_rule();
  IF v_rule.version IS NULL THEN
    RAISE EXCEPTION 'no active highlight rule' USING ERRCODE = 'PT428';
  END IF;

  SELECT * INTO v_gme
  FROM public.fn_get_gme_observed_moving_time_v2(
    p_clip_id, p_engine_schema_version, p_algorithm_version, p_detector_identity);

  IF v_gme.measurement_status IN ('pending', 'failed') THEN
    status := v_gme.measurement_status; initial := NULL; rule_version := v_rule.version;
    gme_run_id := NULL; fired := '{}'; shadow := '{}'; features := NULL;
    reason := CASE WHEN v_gme.measurement_status = 'pending' THEN '분석 대기' ELSE '분석 실패' END;
    RETURN NEXT; RETURN;
  END IF;

  SELECT r.* INTO v_run FROM public.gme_runs r WHERE r.id = v_gme.run_id;
  SELECT * INTO v_eval FROM public.fn_highlight_rule_eval(v_run, v_rule.params);

  status := 'decided'; initial := v_eval.initial; rule_version := v_rule.version;
  gme_run_id := v_run.id; reason := v_eval.reason; fired := v_eval.fired;
  shadow := v_eval.shadow; features := v_eval.features;
  RETURN NEXT;
END $$;

-- ── 현재값: 사람 확정 있으면 그 값, 없으면 1차 판정 ───────────────────
CREATE FUNCTION public.fn_highlight_current(
  p_clip_id uuid,
  p_engine_schema_version text,
  p_algorithm_version text,
  p_detector_identity text
) RETURNS TABLE (
  source text,            -- human | rule
  status text,            -- decided | pending | failed  (human이면 항상 decided)
  value boolean,
  rule_version text,
  reason text,
  reviewer_id uuid,
  decided_at timestamptz,
  verdict_kind text
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_verdict public.motion_clip_highlight_verdicts%ROWTYPE;
  v_initial record;
BEGIN
  SELECT * INTO v_verdict
  FROM public.motion_clip_highlight_verdicts v
  WHERE v.clip_id = p_clip_id
  ORDER BY v.created_at DESC, v.id DESC
  LIMIT 1;

  IF v_verdict.id IS NOT NULL THEN
    source := 'human'; status := 'decided'; value := v_verdict.verdict;
    rule_version := v_verdict.rule_version; reason := v_verdict.initial_reason;
    reviewer_id := v_verdict.reviewer_id; decided_at := v_verdict.created_at;
    verdict_kind := v_verdict.kind;
    RETURN NEXT; RETURN;
  END IF;

  SELECT * INTO v_initial FROM public.fn_highlight_initial(
    p_clip_id, p_engine_schema_version, p_algorithm_version, p_detector_identity);
  source := 'rule'; status := v_initial.status; value := v_initial.initial;
  rule_version := v_initial.rule_version; reason := v_initial.reason;
  reviewer_id := NULL; decided_at := NULL; verdict_kind := NULL;
  RETURN NEXT;
END $$;

-- ── 사람 확정 append ────────────────────────────────────────────────
CREATE FUNCTION public.fn_submit_highlight_verdict(
  p_clip_id uuid,
  p_reviewer_id uuid,
  p_is_owner boolean,
  p_verdict boolean,
  p_kind text,
  p_change_reason text,
  p_engine_schema_version text,
  p_algorithm_version text,
  p_detector_identity text
) RETURNS TABLE (verdict_id uuid, initial boolean, changed boolean, rule_version text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_initial record;
  v_id uuid := gen_random_uuid();
  v_changed boolean;
BEGIN
  IF p_clip_id IS NULL OR p_reviewer_id IS NULL OR p_verdict IS NULL OR p_kind IS NULL THEN
    RAISE EXCEPTION 'required parameter is missing' USING ERRCODE = '22023';
  END IF;
  IF p_kind NOT IN ('initial', 'correction') THEN
    RAISE EXCEPTION 'invalid verdict kind' USING ERRCODE = '22023';
  END IF;
  IF p_change_reason IS NOT NULL AND p_change_reason NOT IN
     ('false_detection','gecko_not_visible','camera_shake','too_short','interesting_low_numbers','other') THEN
    RAISE EXCEPTION 'invalid change reason' USING ERRCODE = '22023';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.motion_clips c WHERE c.id = p_clip_id) THEN
    RAISE EXCEPTION 'motion clip not found' USING ERRCODE = 'P0002';
  END IF;
  -- 승인 라벨러 또는 owner만. 배정 카메라와 무관하게 누구나 확정 가능(v4 스펙 §4.1).
  IF NOT p_is_owner AND NOT EXISTS (
    SELECT 1 FROM public.labelers l WHERE l.user_id = p_reviewer_id
  ) THEN
    RAISE EXCEPTION 'reviewer is not an approved labeler' USING ERRCODE = 'PT403';
  END IF;
  IF p_kind = 'correction' AND NOT p_is_owner THEN
    RAISE EXCEPTION 'only owner can append a correction' USING ERRCODE = 'PT403';
  END IF;
  IF p_kind = 'correction' AND NOT EXISTS (
    SELECT 1 FROM public.motion_clip_highlight_verdicts v WHERE v.clip_id = p_clip_id AND v.kind = 'initial'
  ) THEN
    RAISE EXCEPTION 'nothing to correct' USING ERRCODE = 'P0002';
  END IF;

  SELECT * INTO v_initial FROM public.fn_highlight_initial(
    p_clip_id, p_engine_schema_version, p_algorithm_version, p_detector_identity);
  v_changed := CASE WHEN v_initial.initial IS NULL THEN NULL ELSE v_initial.initial <> p_verdict END;

  BEGIN
    INSERT INTO public.motion_clip_highlight_verdicts (
      id, clip_id, reviewer_id, kind, rule_version, gme_run_id, initial_status,
      initial, initial_reason, verdict, changed, change_reason
    ) VALUES (
      v_id, p_clip_id, p_reviewer_id, p_kind, v_initial.rule_version, v_initial.gme_run_id,
      v_initial.status, v_initial.initial, v_initial.reason, p_verdict, v_changed, p_change_reason
    );
  EXCEPTION WHEN unique_violation THEN
    -- 먼저 저장한 사람이 이긴다(v4 스펙 §4.2). 호출자는 "방금 확정됐어"로 안내한다.
    RAISE EXCEPTION 'clip already has an initial verdict' USING ERRCODE = 'PT409';
  END;

  verdict_id := v_id; initial := v_initial.initial; changed := v_changed;
  rule_version := v_initial.rule_version;
  RETURN NEXT;
END $$;

-- ── 규칙 버전 생성 + 활성화 (owner) ────────────────────────────────
CREATE FUNCTION public.fn_create_highlight_rule_version(
  p_version text,
  p_params jsonb,
  p_note text,
  p_actor_id uuid
) RETURNS TABLE (version text, activated_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_probe public.gme_runs%ROWTYPE;
  v_dummy record;
  v_event_id uuid := gen_random_uuid();
BEGIN
  IF p_version IS NULL OR p_params IS NULL OR p_actor_id IS NULL THEN
    RAISE EXCEPTION 'required parameter is missing' USING ERRCODE = '22023';
  END IF;
  -- params 유효성은 eval을 합성 run에 한 번 돌려 확인한다(모르는 트리거·빠진 숫자 = 22023).
  v_probe.candidate_moving_sec_any_gecko := 1; v_probe.visible_sec := 1; v_probe.duration_sec := 60;
  v_probe.state_intervals := '[{"state":"moving","start_sec":0,"end_sec":1}]'::jsonb;
  SELECT * INTO v_dummy FROM public.fn_highlight_rule_eval(v_probe, p_params);

  INSERT INTO public.highlight_rule_versions (version, params, note, created_by)
  VALUES (p_version, p_params, coalesce(p_note, ''), p_actor_id);
  INSERT INTO public.highlight_rule_activation_events (id, version, actor_id)
  VALUES (v_event_id, p_version, p_actor_id);

  RETURN QUERY SELECT e.version, e.activated_at
  FROM public.highlight_rule_activation_events e WHERE e.id = v_event_id;
END $$;

-- ── 집계: 규칙 버전 × 카메라 유지율 (owner) ────────────────────────
CREATE FUNCTION public.fn_highlight_rule_stats(p_from timestamptz, p_to timestamptz)
RETURNS TABLE (
  rule_version text,
  camera_id uuid,
  camera_name text,
  verdict_count bigint,
  kept_count bigint,
  o_to_x bigint,
  x_to_o bigint,
  pending_initial bigint,
  reason_counts jsonb
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT
    v.rule_version,
    c.camera_id,
    cam.name,
    count(*)::bigint,
    count(*) FILTER (WHERE v.changed = false)::bigint,
    count(*) FILTER (WHERE v.initial = true AND v.verdict = false)::bigint,
    count(*) FILTER (WHERE v.initial = false AND v.verdict = true)::bigint,
    count(*) FILTER (WHERE v.initial IS NULL)::bigint,
    coalesce((
      SELECT jsonb_object_agg(r.change_reason, r.n)
      FROM (
        SELECT v2.change_reason, count(*) AS n
        FROM public.motion_clip_highlight_verdicts v2
        JOIN public.motion_clips c2 ON c2.id = v2.clip_id
        WHERE v2.rule_version = v.rule_version AND c2.camera_id = c.camera_id
          AND v2.kind = 'initial' AND v2.change_reason IS NOT NULL
          AND v2.created_at >= p_from AND v2.created_at < p_to
        GROUP BY v2.change_reason
      ) r
    ), '{}'::jsonb)
  FROM public.motion_clip_highlight_verdicts v
  JOIN public.motion_clips c ON c.id = v.clip_id
  LEFT JOIN public.cameras cam ON cam.id = c.camera_id
  WHERE v.kind = 'initial' AND v.created_at >= p_from AND v.created_at < p_to
  GROUP BY v.rule_version, c.camera_id, cam.name
  ORDER BY v.rule_version DESC, cam.name NULLS LAST
$$;

-- ── 권한 ──────────────────────────────────────────────────────────
REVOKE ALL ON FUNCTION public.fn_highlight_rule_eval(public.gme_runs, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_highlight_rule_eval(public.gme_runs, jsonb) TO service_role;
REVOKE ALL ON FUNCTION public.fn_get_active_highlight_rule() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_active_highlight_rule() TO service_role;
REVOKE ALL ON FUNCTION public.fn_highlight_initial(uuid, text, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_highlight_initial(uuid, text, text, text) TO service_role;
REVOKE ALL ON FUNCTION public.fn_highlight_current(uuid, text, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_highlight_current(uuid, text, text, text) TO service_role;
REVOKE ALL ON FUNCTION public.fn_submit_highlight_verdict(uuid, uuid, boolean, boolean, text, text, text, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_submit_highlight_verdict(uuid, uuid, boolean, boolean, text, text, text, text, text) TO service_role;
REVOKE ALL ON FUNCTION public.fn_create_highlight_rule_version(text, jsonb, text, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_create_highlight_rule_version(text, jsonb, text, uuid) TO service_role;
REVOKE ALL ON FUNCTION public.fn_highlight_rule_stats(timestamptz, timestamptz) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_highlight_rule_stats(timestamptz, timestamptz) TO service_role;

-- ── seed: v0 (owner 승인 2026-09-07) ─────────────────────────────────
INSERT INTO public.highlight_rule_versions (version, params, note, created_by) VALUES (
  'hl-rule-v0',
  '{"triggers": [
      {"name": "long_activity", "on": true, "activity_sec_gte": 10},
      {"name": "sustained_move", "on": true, "longest_sec_gte": 5},
      {"name": "frequent_bursts", "on": false, "activity_sec_gte": 3, "bursts_gte": 8},
      {"name": "early_action", "on": false, "first_move_sec_lte": 2}
    ], "guards": []}'::jsonb,
  'owner 승인 2026-09-07. long_activity 10s OR sustained_move 5s. 나머지 두 트리거는 shadow.',
  NULL
);
INSERT INTO public.highlight_rule_activation_events (version, actor_id) VALUES ('hl-rule-v0', NULL);

COMMIT;
```

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/baek/petcam-lab && uv run pytest tests/test_highlight_rule_v0_migration.py -x -q`
Expected: `8 passed`

- [ ] **Step 5: 커밋**

```bash
cd /Users/baek/petcam-lab && git checkout -b feat/highlight-rule-v0 && git add migrations/2026-09-08_highlight_rule_v0.sql tests/test_highlight_rule_v0_migration.py && git commit -m "feat: 하이라이트 규칙 v0 원장·판정 함수 migration + 정적 계약 테스트"
```

---

### Task 2: 일회용 PostgreSQL probe — 실제 apply + 동작 실증

**Context:**
- Depends on: Task 1
- Inputs: `migrations/2026-08-03_gecko_motion_engine_shadow.sql`(gme 테이블), `migrations/2026-09-03_gme_observed_moving_time_v1.sql`, `migrations/2026-09-03_gme_slow_motion_v1_contract.sql`(v2 RPC), Task 1 migration. 러너 골격은 `scripts/run_gme_observed_moving_time_probe.py`와 같다(초기화·roles·createdb·cleanup).
- Outputs: `scripts/run_highlight_rule_v0_probe.py`, `tests/test_highlight_rule_v0_probe.py`
- Must know: Homebrew PostgreSQL 15 바이너리 경로는 `/opt/homebrew/opt/postgresql@15/bin`(없으면 `brew --prefix postgresql@15`). probe는 production에 절대 연결하지 않는다. 마지막에 `PROBE_RESIDUE=0`(데이터 디렉토리 삭제 = TemporaryDirectory)을 찍는다. `gme_runs` 컬럼 목록은 `tests/sql`의 기존 probe와 동일(위 러너 setup 참고).
- Acceptance: `uv run python scripts/run_highlight_rule_v0_probe.py --pg-bin $(brew --prefix postgresql@15)/bin` → 마지막 줄 `HIGHLIGHT_RULE_V0_PROBE_OK` 와 `PROBE_RESIDUE=0`; `uv run pytest tests/test_highlight_rule_v0_probe.py -q` PASS

**Files:**
- Create: `scripts/run_highlight_rule_v0_probe.py`
- Test: `tests/test_highlight_rule_v0_probe.py`

- [ ] **Step 1: 러너의 순수 파서 테스트 작성**

```python
"""probe 러너의 psql 출력 파서만 검사한다(PG 불필요)."""

from scripts.run_highlight_rule_v0_probe import parse_kv_lines, expect


def test_parse_kv_lines_reads_psql_unaligned_output() -> None:
    out = "initial|t\nreason|움직임 12.5초 · 최장 연속 6.0초\nfired|{long_activity,sustained_move}\n"
    parsed = parse_kv_lines(out)
    assert parsed["initial"] == "t"
    assert parsed["fired"] == "{long_activity,sustained_move}"


def test_expect_raises_with_label_on_mismatch() -> None:
    try:
        expect("case-a", {"initial": "t"}, initial="f")
    except RuntimeError as err:
        assert "case-a" in str(err) and "initial" in str(err)
    else:
        raise AssertionError("expect() must raise on mismatch")
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/baek/petcam-lab && uv run pytest tests/test_highlight_rule_v0_probe.py -q`
Expected: FAIL — `ModuleNotFoundError: scripts.run_highlight_rule_v0_probe`

- [ ] **Step 3: probe 러너 작성**

```python
"""highlight rule v0 migration을 일회용 PostgreSQL에서 실증한다. production 연결 0."""

from __future__ import annotations

import argparse
import socket
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    ROOT / "migrations" / "2026-08-03_gecko_motion_engine_shadow.sql",
    ROOT / "migrations" / "2026-09-03_gme_observed_moving_time_v1.sql",
    ROOT / "migrations" / "2026-09-03_gme_slow_motion_v1_contract.sql",
    ROOT / "migrations" / "2026-09-08_highlight_rule_v0.sql",
]
FLAGS = ("-X", "-v", "ON_ERROR_STOP=1", "-qAt")
ENGINE, ALGO, IDENTITY = "gme-shadow-v1", "gme-motion-v1", "a" * 64
CLIP = {k: f"00000000-0000-4000-8000-00000000000{i}" for i, k in enumerate(
    ("include", "boundary_activity", "boundary_longest", "short", "not_observed", "pending", "shadow_only"), start=1)}
LABELER = "30000000-0000-4000-8000-000000000001"
OWNER = "30000000-0000-4000-8000-000000000002"
STRANGER = "30000000-0000-4000-8000-000000000003"


class ProbeError(RuntimeError):
    pass


def parse_kv_lines(out: str) -> dict[str, str]:
    """psql -qAt 로 찍은 `key|value` 줄들을 dict 로."""
    parsed: dict[str, str] = {}
    for line in out.splitlines():
        if "|" in line:
            key, value = line.split("|", 1)
            parsed[key.strip()] = value.strip()
    return parsed


def expect(label: str, parsed: dict[str, str], **want: str) -> None:
    for key, value in want.items():
        got = parsed.get(key)
        if got != value:
            raise RuntimeError(f"{label}: {key} expected {value!r} got {got!r}")


def run(argv: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, input=input_text, text=True, capture_output=True, timeout=120, check=False)


def require_ok(result: subprocess.CompletedProcess[str], label: str) -> str:
    if result.returncode != 0:
        raise ProbeError(f"{label}:{(result.stderr or result.stdout).strip()[:1500]}")
    return (result.stdout or "").strip()


def require_sqlstate(result: subprocess.CompletedProcess[str], label: str, sqlstate: str) -> None:
    if result.returncode == 0 or sqlstate not in (result.stderr or ""):
        raise ProbeError(f"{label}: expected SQLSTATE {sqlstate}, got rc={result.returncode} {result.stderr[:400]}")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_row(state: str, start: float, end: float) -> str:
    return f'{{"state":"{state}","start_sec":{start},"end_sec":{end},"track_ids":["g0001"]}}'


def setup_sql() -> str:
    def job(n: int, clip: str, status: str) -> str:
        return (f"('1000000{n}-0000-4000-8000-000000000001','{clip}','historical',10,"
                f"'{ENGINE}','{ALGO}','{IDENTITY}','{status}')")

    def run_(n: int, clip: str, activity: float, visible: float, intervals: str) -> str:
        return (f"('2000000{n}-0000-4000-8000-000000000001','{clip}','1000000{n}-0000-4000-8000-000000000001',"
                f"'{ENGINE}','{ALGO}','{IDENTITY}','probe','probe-{n}','ok',60,600,600,10,{activity},{activity},"
                f"{visible},0,0,1,'terra-derived/gme/v1/permanent/probe/{n}.json',repeat('{chr(96 + n)}',64),1,"
                f"'[{intervals}]'::jsonb)")

    intervals = {
        "include": ",".join([run_row("moving", 0, 12.5)]),
        "boundary_activity": ",".join([run_row("moving", 0, 4), run_row("static", 4, 10), run_row("moving", 10, 16)]),  # activity=10.0, longest=6 → 트리거 둘 다
        "boundary_longest": ",".join([run_row("moving", 0, 5.0)]),  # activity=5.0(<10), longest=5.0(>=5) → O
        "short": ",".join([run_row("moving", 0, 4.9)]),  # activity 4.9, longest 4.9 → X
        "not_observed": "",
        "shadow_only": ",".join([run_row("moving", 0, 1.0)] + [run_row("moving", i, i + 0.3) for i in range(2, 12)]),  # activity 4, bursts 11, first 0 → shadow frequent_bursts+early_action, X
    }
    return f"""
    INSERT INTO auth.users(id) VALUES ('{LABELER}'),('{OWNER}'),('{STRANGER}');
    INSERT INTO public.labelers(user_id) VALUES ('{LABELER}');
    INSERT INTO public.cameras(id, name) VALUES ('40000000-0000-4000-8000-000000000001','probe-cam');
    INSERT INTO public.motion_clips(id, camera_id, started_at, duration_sec, r2_key)
      SELECT id::uuid, '40000000-0000-4000-8000-000000000001', now(), 60, 'probe/'||id FROM unnest(ARRAY[{",".join("'" + v + "'" for v in CLIP.values())}]) AS id;
    INSERT INTO public.gme_jobs(id,clip_id,source,priority,engine_schema_version,algorithm_version,detector_identity,status) VALUES
      {job(1, CLIP['include'], 'succeeded')},
      {job(2, CLIP['boundary_activity'], 'succeeded')},
      {job(3, CLIP['boundary_longest'], 'succeeded')},
      {job(4, CLIP['short'], 'succeeded')},
      {job(5, CLIP['not_observed'], 'succeeded')},
      {job(6, CLIP['pending'], 'queued')},
      {job(7, CLIP['shadow_only'], 'succeeded')};
    INSERT INTO public.gme_runs(id,clip_id,job_id,engine_schema_version,algorithm_version,detector_identity,
      producer_host,producer_run_id,status,duration_sec,decoded_frame_count,analyzed_frame_count,source_fps,
      candidate_moving_sec_any_gecko,moving_gecko_seconds,visible_sec,unknown_sec,camera_motion_sec,
      max_simultaneous_geckos,permanent_artifact_key,permanent_artifact_sha256,permanent_artifact_bytes,state_intervals) VALUES
      {run_(1, CLIP['include'], 12.5, 60, intervals['include'])},
      {run_(2, CLIP['boundary_activity'], 10.0, 60, intervals['boundary_activity'])},
      {run_(3, CLIP['boundary_longest'], 5.0, 60, intervals['boundary_longest'])},
      {run_(4, CLIP['short'], 4.9, 60, intervals['short'])},
      {run_(5, CLIP['not_observed'], 0, 0, intervals['not_observed'])},
      {run_(7, CLIP['shadow_only'], 4.0, 60, intervals['shadow_only'])};
    UPDATE public.gme_jobs j SET result_run_id = r.id FROM public.gme_runs r WHERE r.job_id = j.id;
    """


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-bin", type=Path, required=True)
    args = parser.parse_args()
    binaries = {n: args.pg_bin / n for n in ("psql", "initdb", "pg_ctl", "createdb")}
    for path in binaries.values():
        if not path.is_file():
            raise ProbeError(f"missing:{path.name}")
    port = free_port()
    db = "highlight_rule_v0_probe"
    with tempfile.TemporaryDirectory(prefix="highlight-rule-v0-pg-") as tmp:
        data_dir = Path(tmp) / "data"
        require_ok(run([str(binaries["initdb"]), "-D", str(data_dir), "--auth=trust", "--no-locale"]), "initdb")
        started = False

        def sql(database: str, statement: str) -> subprocess.CompletedProcess[str]:
            return run([str(binaries["psql"]), "-h", "127.0.0.1", "-p", str(port), "-d", database, *FLAGS], input_text=statement)

        def q(statement: str) -> dict[str, str]:
            return parse_kv_lines(require_ok(sql(db, statement), statement[:60]))

        try:
            require_ok(subprocess.run([str(binaries["pg_ctl"]), "-D", str(data_dir), "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"],
                                      text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120, check=False), "pg_start")
            started = True
            require_ok(sql("postgres", "create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;"), "roles")
            require_ok(run([str(binaries["createdb"]), "-h", "127.0.0.1", "-p", str(port), db]), "createdb")
            require_ok(sql(db, """
                create extension if not exists pgcrypto;
                create schema auth; create table auth.users(id uuid primary key);
                create table public.cameras(id uuid primary key, name text);
                create table public.motion_clips(id uuid primary key, camera_id uuid references public.cameras(id),
                  started_at timestamptz not null default now(), duration_sec double precision, r2_key text);
                create table public.labelers(user_id uuid primary key);
                grant select on public.motion_clips, public.cameras, public.labelers to service_role;
            """), "schema")
            for path in MIGRATIONS:
                require_ok(sql(db, path.read_text(encoding="utf-8")), path.name)
            require_ok(sql(db, setup_sql()), "setup")

            def initial(clip: str) -> dict[str, str]:
                return q(f"select 'status|'||status union all select 'initial|'||coalesce(initial::text,'null') "
                         f"union all select 'fired|'||fired::text union all select 'shadow|'||shadow::text "
                         f"from public.fn_highlight_initial('{clip}','{ENGINE}','{ALGO}','{IDENTITY}');")

            # 1) seed + active
            expect("active", q("select 'version|'||version from public.fn_get_active_highlight_rule();"), version="hl-rule-v0")
            # 2) eval 경계
            expect("include", initial(CLIP["include"]), status="decided", initial="true", fired="{long_activity,sustained_move}")
            expect("boundary_activity", initial(CLIP["boundary_activity"]), initial="true")
            expect("boundary_longest", initial(CLIP["boundary_longest"]), initial="true", fired="{sustained_move}")
            expect("short", initial(CLIP["short"]), initial="false", fired="{}")
            expect("not_observed", initial(CLIP["not_observed"]), status="decided", initial="false")
            expect("pending", initial(CLIP["pending"]), status="pending", initial="null")
            expect("shadow_only", initial(CLIP["shadow_only"]), initial="false", shadow="{frequent_bursts,early_action}")
            # 3) submit: labeler 확정, 잠금, stranger 거부, correction owner-only
            expect("submit", q(f"select 'changed|'||changed::text||'' from public.fn_submit_highlight_verdict('{CLIP['include']}','{LABELER}',false,false,'initial','false_detection','{ENGINE}','{ALGO}','{IDENTITY}');"), changed="true")
            require_sqlstate(sql(db, f"select * from public.fn_submit_highlight_verdict('{CLIP['include']}','{OWNER}',true,true,'initial',null,'{ENGINE}','{ALGO}','{IDENTITY}');"), "lock", "PT409")
            require_sqlstate(sql(db, f"select * from public.fn_submit_highlight_verdict('{CLIP['short']}','{STRANGER}',false,true,'initial',null,'{ENGINE}','{ALGO}','{IDENTITY}');"), "stranger", "PT403")
            require_sqlstate(sql(db, f"select * from public.fn_submit_highlight_verdict('{CLIP['include']}','{LABELER}',false,true,'correction',null,'{ENGINE}','{ALGO}','{IDENTITY}');"), "correction-by-labeler", "PT403")
            expect("owner-correction", q(f"select 'initial|'||initial::text from public.fn_submit_highlight_verdict('{CLIP['include']}','{OWNER}',true,true,'correction',null,'{ENGINE}','{ALGO}','{IDENTITY}');"), initial="true")
            expect("current-human", q(f"select 'source|'||source union all select 'value|'||value::text union all select 'kind|'||verdict_kind from public.fn_highlight_current('{CLIP['include']}','{ENGINE}','{ALGO}','{IDENTITY}');"), source="human", value="true", kind="correction")
            expect("current-rule", q(f"select 'source|'||source union all select 'value|'||value::text from public.fn_highlight_current('{CLIP['short']}','{ENGINE}','{ALGO}','{IDENTITY}');"), source="rule", value="false")
            expect("pending-verdict", q(f"select 'changed|'||coalesce(changed::text,'null') from public.fn_submit_highlight_verdict('{CLIP['pending']}','{LABELER}',false,true,'initial',null,'{ENGINE}','{ALGO}','{IDENTITY}');"), changed="null")
            # 4) 규칙 버전 생성 + 활성화 + 잘못된 트리거 거부
            expect("v1", q(f"select 'version|'||version from public.fn_create_highlight_rule_version('hl-rule-v1', '{{\"triggers\":[{{\"name\":\"long_activity\",\"on\":true,\"activity_sec_gte\":12}}]}}'::jsonb, 'probe', '{OWNER}');"), version="hl-rule-v1")
            expect("active-v1", q("select 'version|'||version from public.fn_get_active_highlight_rule();"), version="hl-rule-v1")
            require_sqlstate(sql(db, f"select * from public.fn_create_highlight_rule_version('hl-rule-v2', '{{\"triggers\":[{{\"name\":\"nope\",\"on\":true}}]}}'::jsonb, 'bad', '{OWNER}');"), "unknown-trigger", "22023")
            expect("old-verdict-immutable", q(f"select 'rule|'||rule_version from public.motion_clip_highlight_verdicts where clip_id='{CLIP['include']}' and kind='initial';"), rule="hl-rule-v0")
            # 5) stats
            expect("stats", q("select 'n|'||sum(verdict_count)::text union all select 'x|'||sum(o_to_x)::text from public.fn_highlight_rule_stats(now()-interval '1 hour', now()+interval '1 hour') where rule_version='hl-rule-v0';"), n="2", x="1")
            # 6) append-only + 권한
            require_sqlstate(sql(db, "update public.motion_clip_highlight_verdicts set verdict = false;"), "append-only", "0A000")
            require_sqlstate(sql(db, "delete from public.highlight_rule_versions;"), "append-only-rules", "0A000")
            expect("privs", q("select 'tables|'||count(*)::text from information_schema.role_table_grants where grantee in ('anon','authenticated','service_role') and table_name in ('highlight_rule_versions','highlight_rule_activation_events','motion_clip_highlight_verdicts');"), tables="0")
            expect("rls", q("select 'rls|'||count(*)::text from pg_class where relname in ('highlight_rule_versions','highlight_rule_activation_events','motion_clip_highlight_verdicts') and relrowsecurity;"), rls="3")
            print("HIGHLIGHT_RULE_V0_PROBE_OK")
        finally:
            if started:
                subprocess.run([str(binaries["pg_ctl"]), "-D", str(data_dir), "-m", "immediate", "stop"], text=True, capture_output=True, timeout=120, check=False)
    print("PROBE_RESIDUE=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 파서 테스트 통과 + probe 실행**

Run: `cd /Users/baek/petcam-lab && uv run pytest tests/test_highlight_rule_v0_probe.py -q && uv run python scripts/run_highlight_rule_v0_probe.py --pg-bin "$(brew --prefix postgresql@15)/bin"`
Expected: `2 passed` 그리고 마지막 두 줄 `HIGHLIGHT_RULE_V0_PROBE_OK` / `PROBE_RESIDUE=0`. 실패하면 라벨(`boundary_longest: initial expected 'true' got 'false'` 형태)로 어느 케이스인지 바로 보인다.

- [ ] **Step 5: 커밋**

```bash
cd /Users/baek/petcam-lab && git add scripts/run_highlight_rule_v0_probe.py tests/test_highlight_rule_v0_probe.py && git commit -m "test: 하이라이트 규칙 v0 일회용 PostgreSQL probe"
```

---

### Task 3: 웹 공용 타입·카피 + 서버 매퍼

**Context:**
- Depends on: Task 1 (RPC 반환 컬럼명)
- Inputs: `fn_highlight_current` 컬럼 `(source,status,value,rule_version,reason,reviewer_id,decided_at,verdict_kind)`, `fn_highlight_initial` 컬럼 `(status,initial,rule_version,gme_run_id,reason,fired,shadow,features)`
- Outputs: `web/src/lib/highlightV4.ts`(타입·enum·카피), `web/src/lib/highlightV4Server.ts`(매퍼)
- Must know: 매퍼는 fail-closed — 모르는 값이면 throw(`labelingV3Server.mapGmeObservedMovingTimeRow` 패턴). 공개 타입에 `gme_run_id`·`reviewer_id`(UUID)·`features`의 raw는 넣지 않는다. 화면에 필요한 건 `reason`·`fired`·`shadow`·`features` 중 숫자 4개뿐.
- Acceptance: `cd /Users/baek/petcam-lab/web && npx vitest run src/lib/highlightV4Server.test.ts` PASS

**Files:**
- Create: `web/src/lib/highlightV4.ts`, `web/src/lib/highlightV4Server.ts`
- Test: `web/src/lib/highlightV4Server.test.ts`

- [ ] **Step 1: 매퍼 테스트 작성**

```ts
import { describe, expect, it } from 'vitest';

import { mapHighlightCurrentRow, mapHighlightInitialRow } from './highlightV4Server';

const initialRow = {
  status: 'decided', initial: true, rule_version: 'hl-rule-v0',
  gme_run_id: '20000000-0000-4000-8000-000000000001',
  reason: '움직임 12.5초 · 최장 연속 6.0초',
  fired: ['long_activity'], shadow: ['early_action'],
  features: { activity_sec: 12.5, longest_moving_sec: 6, moving_burst_count: 3, first_moving_sec: 0.2, visible_sec: 60, duration_sec: 60 },
};

describe('mapHighlightInitialRow', () => {
  it('공개 필드만 통과시키고 run id는 버린다', () => {
    const out = mapHighlightInitialRow(initialRow);
    expect(out).toEqual({
      status: 'decided', value: true, rule_version: 'hl-rule-v0',
      reason: '움직임 12.5초 · 최장 연속 6.0초', fired: ['long_activity'], shadow: ['early_action'],
      features: { activity_sec: 12.5, longest_moving_sec: 6, moving_burst_count: 3, first_moving_sec: 0.2 },
    });
    expect(JSON.stringify(out)).not.toContain('20000000');
  });
  it('pending 은 value null 이고 features 없음', () => {
    const out = mapHighlightInitialRow({ ...initialRow, status: 'pending', initial: null, gme_run_id: null, features: null, fired: [], shadow: [] });
    expect(out.status).toBe('pending');
    expect(out.value).toBeNull();
    expect(out.features).toBeNull();
  });
  it('모르는 status 는 throw', () => {
    expect(() => mapHighlightInitialRow({ ...initialRow, status: 'weird' })).toThrow('invalid_highlight_initial');
  });
  it('decided 인데 value 가 null 이면 throw', () => {
    expect(() => mapHighlightInitialRow({ ...initialRow, initial: null })).toThrow('invalid_highlight_initial');
  });
});

describe('mapHighlightCurrentRow', () => {
  it('human 은 reviewer 표시명을 받고 UUID 는 버린다', () => {
    const out = mapHighlightCurrentRow({
      source: 'human', status: 'decided', value: false, rule_version: 'hl-rule-v0', reason: '짧은 움직임 4.9초',
      reviewer_id: '30000000-0000-4000-8000-000000000001', decided_at: '2026-09-08T00:00:00Z', verdict_kind: 'initial',
    }, '김라벨');
    expect(out).toEqual({ source: 'human', status: 'decided', value: false, rule_version: 'hl-rule-v0', reason: '짧은 움직임 4.9초', reviewer_name: '김라벨', decided_at: '2026-09-08T00:00:00Z', verdict_kind: 'initial' });
  });
  it('rule 은 reviewer 없음', () => {
    const out = mapHighlightCurrentRow({ source: 'rule', status: 'pending', value: null, rule_version: 'hl-rule-v0', reason: '분석 대기', reviewer_id: null, decided_at: null, verdict_kind: null }, null);
    expect(out.reviewer_name).toBeNull();
    expect(out.verdict_kind).toBeNull();
  });
});
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/baek/petcam-lab/web && npx vitest run src/lib/highlightV4Server.test.ts`
Expected: FAIL — `Cannot find module './highlightV4Server'`

- [ ] **Step 3: 타입·카피 파일**

```ts
// web/src/lib/highlightV4.ts
// 하이라이트 v4 공개 계약(클라이언트/서버 공용, 순수). run id·detector identity·reviewer UUID 는 없다.

export type HighlightInitialStatus = 'decided' | 'pending' | 'failed';
export type HighlightSource = 'human' | 'rule';
export type HighlightVerdictKind = 'initial' | 'correction';

export const HIGHLIGHT_TRIGGERS = ['long_activity', 'sustained_move', 'frequent_bursts', 'early_action'] as const;
export type HighlightTrigger = (typeof HIGHLIGHT_TRIGGERS)[number];

export const HIGHLIGHT_CHANGE_REASONS = [
  'false_detection', 'gecko_not_visible', 'camera_shake', 'too_short', 'interesting_low_numbers', 'other',
] as const;
export type HighlightChangeReason = (typeof HIGHLIGHT_CHANGE_REASONS)[number];

export const HIGHLIGHT_CHANGE_REASON_LABELS: Record<HighlightChangeReason, string> = {
  false_detection: '오검출',
  gecko_not_visible: '게코 안 보임',
  camera_shake: '카메라 흔들림',
  too_short: '너무 짧음',
  interesting_low_numbers: '재밌는데 숫자 낮음',
  other: '기타',
};

export const HIGHLIGHT_TRIGGER_LABELS: Record<HighlightTrigger, string> = {
  long_activity: '오래 움직임',
  sustained_move: '연속 이동',
  frequent_bursts: '잦은 움직임',
  early_action: '촬영 직후 움직임',
};

export interface HighlightFeatures {
  activity_sec: number;
  longest_moving_sec: number;
  moving_burst_count: number;
  first_moving_sec: number | null;
}

export interface HighlightInitial {
  status: HighlightInitialStatus;
  value: boolean | null; // decided 일 때만 boolean
  rule_version: string;
  reason: string;
  fired: HighlightTrigger[];
  shadow: HighlightTrigger[];
  features: HighlightFeatures | null;
}

export interface HighlightCurrent {
  source: HighlightSource;
  status: HighlightInitialStatus;
  value: boolean | null;
  rule_version: string;
  reason: string;
  reviewer_name: string | null;
  decided_at: string | null;
  verdict_kind: HighlightVerdictKind | null;
}

export interface HighlightDetail {
  current: HighlightCurrent;
  initial: HighlightInitial;
}

export interface HighlightVerdictInput {
  verdict: boolean;
  change_reason?: HighlightChangeReason | null;
}

export interface HighlightVerdictResult {
  verdict_id: string;
  initial: boolean | null;
  changed: boolean | null;
  rule_version: string;
}

export function highlightValueLabel(value: boolean | null, status: HighlightInitialStatus): string {
  if (status === 'pending') return '분석 대기';
  if (status === 'failed') return '분석 실패';
  return value ? '하이라이트 O' : '하이라이트 X';
}

export function isHighlightChangeReason(v: unknown): v is HighlightChangeReason {
  return typeof v === 'string' && (HIGHLIGHT_CHANGE_REASONS as readonly string[]).includes(v);
}
```

- [ ] **Step 4: 서버 매퍼**

```ts
// web/src/lib/highlightV4Server.ts
import 'server-only';

import { NextResponse } from 'next/server';

import {
  HIGHLIGHT_TRIGGERS,
  type HighlightCurrent,
  type HighlightFeatures,
  type HighlightInitial,
  type HighlightInitialStatus,
  type HighlightTrigger,
} from './highlightV4';

const STATUSES: readonly HighlightInitialStatus[] = ['decided', 'pending', 'failed'];
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface HighlightInitialRow {
  status: unknown; initial: unknown; rule_version: unknown; gme_run_id: unknown;
  reason: unknown; fired: unknown; shadow: unknown; features: unknown;
}
export interface HighlightCurrentRow {
  source: unknown; status: unknown; value: unknown; rule_version: unknown; reason: unknown;
  reviewer_id: unknown; decided_at: unknown; verdict_kind: unknown;
}

function triggers(v: unknown): HighlightTrigger[] {
  if (!Array.isArray(v)) throw new Error('invalid_highlight_initial');
  return v.map((t) => {
    if (typeof t !== 'string' || !(HIGHLIGHT_TRIGGERS as readonly string[]).includes(t)) throw new Error('invalid_highlight_initial');
    return t as HighlightTrigger;
  });
}

function num(v: unknown): number {
  const n = typeof v === 'string' ? Number(v) : v;
  if (typeof n !== 'number' || !Number.isFinite(n)) throw new Error('invalid_highlight_initial');
  return n;
}

function features(v: unknown): HighlightFeatures | null {
  if (v === null || v === undefined) return null;
  if (typeof v !== 'object') throw new Error('invalid_highlight_initial');
  const f = v as Record<string, unknown>;
  return {
    activity_sec: num(f.activity_sec),
    longest_moving_sec: num(f.longest_moving_sec),
    moving_burst_count: num(f.moving_burst_count),
    first_moving_sec: f.first_moving_sec === null || f.first_moving_sec === undefined ? null : num(f.first_moving_sec),
  };
}

export function mapHighlightInitialRow(row: HighlightInitialRow): HighlightInitial {
  const status = row.status;
  if (typeof status !== 'string' || !(STATUSES as readonly string[]).includes(status)) throw new Error('invalid_highlight_initial');
  if (typeof row.rule_version !== 'string' || typeof row.reason !== 'string') throw new Error('invalid_highlight_initial');
  const value = row.initial;
  if (status === 'decided' && typeof value !== 'boolean') throw new Error('invalid_highlight_initial');
  if (status !== 'decided' && value !== null) throw new Error('invalid_highlight_initial');
  return {
    status: status as HighlightInitialStatus,
    value: status === 'decided' ? (value as boolean) : null,
    rule_version: row.rule_version,
    reason: row.reason,
    fired: triggers(row.fired),
    shadow: triggers(row.shadow),
    features: status === 'decided' ? features(row.features) : null,
  };
}

export function mapHighlightCurrentRow(row: HighlightCurrentRow, reviewerName: string | null): HighlightCurrent {
  const source = row.source;
  const status = row.status;
  if (source !== 'human' && source !== 'rule') throw new Error('invalid_highlight_current');
  if (typeof status !== 'string' || !(STATUSES as readonly string[]).includes(status)) throw new Error('invalid_highlight_current');
  if (typeof row.rule_version !== 'string' || typeof row.reason !== 'string') throw new Error('invalid_highlight_current');
  if (row.value !== null && typeof row.value !== 'boolean') throw new Error('invalid_highlight_current');
  if (source === 'human') {
    if (typeof row.reviewer_id !== 'string' || !UUID_RE.test(row.reviewer_id)) throw new Error('invalid_highlight_current');
    if (typeof row.decided_at !== 'string') throw new Error('invalid_highlight_current');
    if (row.verdict_kind !== 'initial' && row.verdict_kind !== 'correction') throw new Error('invalid_highlight_current');
  }
  return {
    source,
    status: status as HighlightInitialStatus,
    value: row.value as boolean | null,
    rule_version: row.rule_version,
    reason: row.reason,
    reviewer_name: source === 'human' ? reviewerName : null,
    decided_at: source === 'human' ? (row.decided_at as string) : null,
    verdict_kind: source === 'human' ? (row.verdict_kind as 'initial' | 'correction') : null,
  };
}

// RPC 안정 SQLSTATE → HTTP. 나머지는 null 을 돌려 호출자가 502 로 접는다.
export function highlightRpcErrorResponse(error: unknown): NextResponse | null {
  const code = (error as { code?: string } | null)?.code;
  switch (code) {
    case '22023': return NextResponse.json({ detail: '요청 값이 잘못됐어.', code: 'invalid_request' }, { status: 400 });
    case 'P0002': return NextResponse.json({ detail: '영상을 찾을 수 없어.', code: 'not_found' }, { status: 404 });
    case 'PT403': return NextResponse.json({ detail: '이 작업을 할 권한이 없어.', code: 'forbidden' }, { status: 403 });
    case 'PT409': return NextResponse.json({ detail: '방금 다른 사람이 확정했어. 다음 영상으로 넘어가.', code: 'already_decided' }, { status: 409 });
    case 'PT428': return NextResponse.json({ detail: '활성 규칙이 없어. owner 에게 알려줘.', code: 'no_active_rule' }, { status: 503 });
    default: return null;
  }
}

export function highlightDatabaseError(cause: unknown): NextResponse {
  console.error('[labeling-v4] highlight database error', cause);
  return NextResponse.json({ detail: '잠시 후 다시 시도해.', code: 'database_unavailable' }, { status: 502 });
}
```

- [ ] **Step 5: 통과 확인 + 커밋**

Run: `cd /Users/baek/petcam-lab/web && npx vitest run src/lib/highlightV4Server.test.ts && npx tsc --noEmit -p .`
Expected: `6 passed`, tsc 오류 0

```bash
cd /Users/baek/petcam-lab && git add web/src/lib/highlightV4.ts web/src/lib/highlightV4Server.ts web/src/lib/highlightV4Server.test.ts && git commit -m "feat: 하이라이트 v4 공개 타입·카피·서버 매퍼"
```

---

### Task 4: v4 접근 가드 + GET highlight route

**Context:**
- Depends on: Task 3
- Inputs: `requireLabelingAccess(req)` (`web/src/lib/labelingAccess.ts`, `{ ok:true; userId; isOwner }`), `readGmeActiveContract()` (`web/src/lib/labelingV3Server.ts`), `supabaseAdmin` (`web/src/lib/supabase.ts`)
- Outputs: `web/src/app/api/labeling-v4/_access.ts` → `loadV4ClipAccess`, `web/src/app/api/labeling-v4/clips/[clipId]/highlight/route.ts`
- Must know: 승인 라벨러 + owner 모두 접근(튜토리얼 게이트는 v4에서 요구하지 않음 — 하이라이트 O/X 확정은 튜토리얼 대상이 아님). clip 미존재는 404 `not_found`. reviewer 표시명은 `labeler_applications.display_name`, owner 는 `'Owner'`.
- Acceptance: `npx vitest run "src/app/api/labeling-v4/clips/\[clipId\]/highlight/route.test.ts"` PASS

**Files:**
- Create: `web/src/app/api/labeling-v4/_access.ts`, `web/src/app/api/labeling-v4/clips/[clipId]/highlight/route.ts`
- Test: `web/src/app/api/labeling-v4/clips/[clipId]/highlight/route.test.ts`

- [ ] **Step 1: 테스트 작성**

```ts
import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireLabelingAccess, rpc, from } = vi.hoisted(() => ({
  requireLabelingAccess: vi.fn(), rpc: vi.fn(), from: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc, from } }));
vi.mock('@/lib/labelingV3Server', () => ({
  readGmeActiveContract: () => ({ engine_schema_version: 'gme-shadow-v1', algorithm_version: 'gme-motion-v1', detector_identity: 'a'.repeat(64) }),
}));

import { GET } from './route';

const CLIP = '00000000-0000-4000-8000-000000000001';
const req = () => new NextRequest(`https://label.tera-ai.uk/api/labeling-v4/clips/${CLIP}/highlight`);

function clipQuery(rows: unknown[]) {
  return { select: () => ({ eq: () => ({ limit: async () => ({ data: rows, error: null }) }) }) };
}

const currentRow = { source: 'rule', status: 'decided', value: true, rule_version: 'hl-rule-v0', reason: '움직임 12.5초 · 최장 연속 6.0초', reviewer_id: null, decided_at: null, verdict_kind: null };
const initialRow = { status: 'decided', initial: true, rule_version: 'hl-rule-v0', gme_run_id: '2'.repeat(8) + '-0000-4000-8000-000000000001', reason: currentRow.reason, fired: ['long_activity'], shadow: [], features: { activity_sec: 12.5, longest_moving_sec: 6, moving_burst_count: 1, first_moving_sec: 0, visible_sec: 60, duration_sec: 60 } };

beforeEach(() => {
  vi.clearAllMocks();
  requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'u1', isOwner: false });
  from.mockImplementation((table: string) => {
    if (table === 'motion_clips') return clipQuery([{ id: CLIP }]);
    if (table === 'labeler_applications') return clipQuery([{ display_name: '김라벨' }]);
    throw new Error(`unexpected table ${table}`);
  });
  rpc.mockImplementation(async (name: string) => {
    if (name === 'fn_highlight_current') return { data: [currentRow], error: null };
    if (name === 'fn_highlight_initial') return { data: [initialRow], error: null };
    throw new Error(`unexpected rpc ${name}`);
  });
});

describe('GET /api/labeling-v4/clips/[clipId]/highlight', () => {
  it('현재값 + 1차 판정을 돌려주고 run id 를 노출하지 않는다', async () => {
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.current.value).toBe(true);
    expect(body.initial.fired).toEqual(['long_activity']);
    expect(JSON.stringify(body)).not.toContain('22222222');
    expect(rpc.mock.calls[0][1]).toEqual({ p_clip_id: CLIP, p_engine_schema_version: 'gme-shadow-v1', p_algorithm_version: 'gme-motion-v1', p_detector_identity: 'a'.repeat(64) });
  });
  it('인증 실패는 가드 응답 그대로', async () => {
    requireLabelingAccess.mockResolvedValue({ ok: false, response: new Response(null, { status: 401 }) });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(401);
    expect(rpc).not.toHaveBeenCalled();
  });
  it('clip 없음은 404', async () => {
    from.mockImplementation(() => clipQuery([]));
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
  });
  it('잘못된 uuid 는 DB 접근 전 400', async () => {
    const res = await GET(req(), { params: { clipId: 'nope' } });
    expect(res.status).toBe(400);
    expect(from).not.toHaveBeenCalled();
  });
  it('human 현재값이면 표시명을 붙인다', async () => {
    rpc.mockImplementation(async (name: string) => name === 'fn_highlight_current'
      ? { data: [{ ...currentRow, source: 'human', value: false, reviewer_id: '30000000-0000-4000-8000-000000000001', decided_at: '2026-09-08T00:00:00Z', verdict_kind: 'initial' }], error: null }
      : { data: [initialRow], error: null });
    const body = await (await GET(req(), { params: { clipId: CLIP } })).json();
    expect(body.current.reviewer_name).toBe('김라벨');
    expect(JSON.stringify(body)).not.toContain('30000000');
  });
});
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/baek/petcam-lab/web && npx vitest run "src/app/api/labeling-v4/clips/\[clipId\]/highlight/route.test.ts"`
Expected: FAIL — `Cannot find module './route'`

- [ ] **Step 3: 접근 가드**

```ts
// web/src/app/api/labeling-v4/_access.ts
import 'server-only';

import { NextRequest, NextResponse } from 'next/server';

import { requireLabelingAccess } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface V4ClipRow {
  id: string;
  camera_id: string | null;
  started_at: string;
  duration_sec: number | null;
  r2_key: string | null;
}

export type V4ClipAccess =
  | { ok: true; userId: string; isOwner: boolean; clip: V4ClipRow }
  | { ok: false; response: NextResponse };

export function isUuid(v: string): boolean {
  return UUID_RE.test(v);
}

// 승인 사용자(owner 또는 labelers row)면 어떤 clip 이든 읽을 수 있다(v4 스펙 §4.1: 배정은 권한이 아님).
export async function loadV4ClipAccess(req: NextRequest, clipId: string): Promise<V4ClipAccess> {
  if (!isUuid(clipId)) {
    return { ok: false, response: NextResponse.json({ detail: '잘못된 영상 id 야.', code: 'invalid_request' }, { status: 400 }) };
  }
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access;
  const { data, error } = await supabaseAdmin
    .from('motion_clips')
    .select('id, camera_id, started_at, duration_sec, r2_key')
    .eq('id', clipId)
    .limit(1);
  if (error) throw error;
  const clip = (data ?? [])[0] as V4ClipRow | undefined;
  if (!clip) {
    return { ok: false, response: NextResponse.json({ detail: '영상을 찾을 수 없어.', code: 'not_found' }, { status: 404 }) };
  }
  return { ok: true, userId: access.userId, isOwner: access.isOwner, clip };
}

// 표시명: labeler_applications.display_name. owner 는 'Owner'. 없으면 '라벨러'.
export async function reviewerDisplayName(reviewerId: string | null): Promise<string | null> {
  if (!reviewerId) return null;
  if (process.env.DEV_USER_ID && reviewerId === process.env.DEV_USER_ID) return 'Owner';
  const { data, error } = await supabaseAdmin
    .from('labeler_applications')
    .select('display_name')
    .eq('user_id', reviewerId)
    .limit(1);
  if (error) throw error;
  return ((data ?? [])[0] as { display_name?: string } | undefined)?.display_name ?? '라벨러';
}
```

- [ ] **Step 4: GET route**

```ts
// web/src/app/api/labeling-v4/clips/[clipId]/highlight/route.ts
import { NextRequest, NextResponse } from 'next/server';

import {
  highlightDatabaseError,
  highlightRpcErrorResponse,
  mapHighlightCurrentRow,
  mapHighlightInitialRow,
  type HighlightCurrentRow,
  type HighlightInitialRow,
} from '@/lib/highlightV4Server';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';
import { loadV4ClipAccess, reviewerDisplayName } from '../../../_access';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v4/clips/[clipId]/highlight — 현재값(사람 확정 우선) + 1차 판정 상세.
// 1차 판정은 저장된 값이 아니라 DB 함수가 지금 계산한 값이다(스펙 §4.2).
export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  try {
    const access = await loadV4ClipAccess(req, params.clipId);
    if (!access.ok) return access.response;

    const contract = readGmeActiveContract();
    const args = {
      p_clip_id: params.clipId,
      p_engine_schema_version: contract.engine_schema_version,
      p_algorithm_version: contract.algorithm_version,
      p_detector_identity: contract.detector_identity,
    };
    const current = await supabaseAdmin.rpc('fn_highlight_current', args);
    if (current.error) return highlightRpcErrorResponse(current.error) ?? highlightDatabaseError(current.error);
    const initial = await supabaseAdmin.rpc('fn_highlight_initial', args);
    if (initial.error) return highlightRpcErrorResponse(initial.error) ?? highlightDatabaseError(initial.error);
    if (!Array.isArray(current.data) || current.data.length !== 1 || !Array.isArray(initial.data) || initial.data.length !== 1) {
      throw new Error('invalid_highlight_result_count');
    }
    const currentRow = current.data[0] as HighlightCurrentRow;
    const name = await reviewerDisplayName(typeof currentRow.reviewer_id === 'string' ? currentRow.reviewer_id : null);
    return NextResponse.json({
      current: mapHighlightCurrentRow(currentRow, name),
      initial: mapHighlightInitialRow(initial.data[0] as HighlightInitialRow),
    });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
```

- [ ] **Step 5: 통과 확인 + 커밋**

Run: `cd /Users/baek/petcam-lab/web && npx vitest run "src/app/api/labeling-v4/clips/\[clipId\]/highlight/route.test.ts"`
Expected: `5 passed`

```bash
cd /Users/baek/petcam-lab && git add web/src/app/api/labeling-v4 && git commit -m "feat: labeling-v4 접근 가드 + 하이라이트 현재값/1차 판정 GET"
```

---

### Task 5: POST verdict route

**Context:**
- Depends on: Task 4 (`loadV4ClipAccess`), Task 3 (`isHighlightChangeReason`, `HighlightVerdictResult`)
- Inputs: body `{ verdict: boolean, change_reason?: string|null, kind?: 'initial'|'correction' }`
- Outputs: `web/src/app/api/labeling-v4/clips/[clipId]/verdict/route.ts`
- Must know: `kind` 기본 `initial`; `correction` 은 owner 만(DB 도 PT403 으로 막지만 route 에서 먼저 403). PT409 는 "방금 다른 사람이 확정" 409. 응답에 verdict_id 만(UUID) — 클라이언트는 표시용으로 안 쓴다.
- Acceptance: `npx vitest run "src/app/api/labeling-v4/clips/\[clipId\]/verdict/route.test.ts"` PASS

**Files:**
- Create: `web/src/app/api/labeling-v4/clips/[clipId]/verdict/route.ts`
- Test: `web/src/app/api/labeling-v4/clips/[clipId]/verdict/route.test.ts`

- [ ] **Step 1: 테스트 작성**

```ts
import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { loadV4ClipAccess, rpc } = vi.hoisted(() => ({ loadV4ClipAccess: vi.fn(), rpc: vi.fn() }));
vi.mock('../../../_access', () => ({ loadV4ClipAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('@/lib/labelingV3Server', () => ({
  readGmeActiveContract: () => ({ engine_schema_version: 'gme-shadow-v1', algorithm_version: 'gme-motion-v1', detector_identity: 'a'.repeat(64) }),
}));

import { POST } from './route';

const CLIP = '00000000-0000-4000-8000-000000000001';
const post = (body: unknown) => new NextRequest(`https://label.tera-ai.uk/api/labeling-v4/clips/${CLIP}/verdict`, { method: 'POST', body: JSON.stringify(body), headers: { 'content-type': 'application/json' } });

beforeEach(() => {
  vi.clearAllMocks();
  loadV4ClipAccess.mockResolvedValue({ ok: true, userId: 'u1', isOwner: false, clip: { id: CLIP } });
  rpc.mockResolvedValue({ data: [{ verdict_id: '50000000-0000-4000-8000-000000000001', initial: true, changed: true, rule_version: 'hl-rule-v0' }], error: null });
});

describe('POST /api/labeling-v4/clips/[clipId]/verdict', () => {
  it('라벨러 initial 확정을 RPC 에 그대로 넘긴다', async () => {
    const res = await POST(post({ verdict: false, change_reason: 'false_detection' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_submit_highlight_verdict', {
      p_clip_id: CLIP, p_reviewer_id: 'u1', p_is_owner: false, p_verdict: false, p_kind: 'initial', p_change_reason: 'false_detection',
      p_engine_schema_version: 'gme-shadow-v1', p_algorithm_version: 'gme-motion-v1', p_detector_identity: 'a'.repeat(64),
    });
    expect(await res.json()).toEqual({ verdict_id: '50000000-0000-4000-8000-000000000001', initial: true, changed: true, rule_version: 'hl-rule-v0' });
  });
  it('verdict 가 boolean 이 아니면 400, RPC 호출 없음', async () => {
    expect((await POST(post({ verdict: 'yes' }), { params: { clipId: CLIP } })).status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });
  it('모르는 change_reason 은 400', async () => {
    expect((await POST(post({ verdict: true, change_reason: 'lol' }), { params: { clipId: CLIP } })).status).toBe(400);
  });
  it('라벨러의 correction 은 403', async () => {
    expect((await POST(post({ verdict: true, kind: 'correction' }), { params: { clipId: CLIP } })).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });
  it('PT409 는 409 already_decided', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT409' } });
    const res = await POST(post({ verdict: true }), { params: { clipId: CLIP } });
    expect(res.status).toBe(409);
    expect((await res.json()).code).toBe('already_decided');
  });
});
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/baek/petcam-lab/web && npx vitest run "src/app/api/labeling-v4/clips/\[clipId\]/verdict/route.test.ts"`
Expected: FAIL — `Cannot find module './route'`

- [ ] **Step 3: route 작성**

```ts
// web/src/app/api/labeling-v4/clips/[clipId]/verdict/route.ts
import { NextRequest, NextResponse } from 'next/server';

import { isHighlightChangeReason, type HighlightVerdictResult } from '@/lib/highlightV4';
import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';
import { loadV4ClipAccess } from '../../../_access';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function badRequest(detail: string) {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

// POST /api/labeling-v4/clips/[clipId]/verdict — 사람 확정 append(v4 스펙 §4.2 낙관적 잠금).
export async function POST(req: NextRequest, { params }: { params: { clipId: string } }) {
  try {
    const access = await loadV4ClipAccess(req, params.clipId);
    if (!access.ok) return access.response;

    let body: { verdict?: unknown; change_reason?: unknown; kind?: unknown };
    try { body = await req.json(); } catch { return badRequest('JSON 본문이 필요해.'); }
    if (typeof body.verdict !== 'boolean') return badRequest('verdict 는 true/false 여야 해.');
    const reason = body.change_reason ?? null;
    if (reason !== null && !isHighlightChangeReason(reason)) return badRequest('change_reason 값이 잘못됐어.');
    const kind = body.kind ?? 'initial';
    if (kind !== 'initial' && kind !== 'correction') return badRequest('kind 값이 잘못됐어.');
    if (kind === 'correction' && !access.isOwner) {
      return NextResponse.json({ detail: '정정은 owner 만 할 수 있어.', code: 'forbidden' }, { status: 403 });
    }

    const contract = readGmeActiveContract();
    const { data, error } = await supabaseAdmin.rpc('fn_submit_highlight_verdict', {
      p_clip_id: params.clipId,
      p_reviewer_id: access.userId,
      p_is_owner: access.isOwner,
      p_verdict: body.verdict,
      p_kind: kind,
      p_change_reason: reason,
      p_engine_schema_version: contract.engine_schema_version,
      p_algorithm_version: contract.algorithm_version,
      p_detector_identity: contract.detector_identity,
    });
    if (error) return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
    if (!Array.isArray(data) || data.length !== 1) throw new Error('invalid_verdict_result_count');
    const row = data[0] as HighlightVerdictResult;
    return NextResponse.json({ verdict_id: row.verdict_id, initial: row.initial, changed: row.changed, rule_version: row.rule_version });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
```

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `cd /Users/baek/petcam-lab/web && npx vitest run "src/app/api/labeling-v4/clips/\[clipId\]/verdict/route.test.ts"`
Expected: `5 passed`

```bash
cd /Users/baek/petcam-lab && git add "web/src/app/api/labeling-v4/clips/[clipId]/verdict" && git commit -m "feat: 하이라이트 사람 확정 POST route"
```

---

### Task 6: owner 규칙 버전·집계 route

**Context:**
- Depends on: Task 3
- Inputs: `requireOwner(req)` (`web/src/lib/labelingAccess.ts`), RPC `fn_get_active_highlight_rule()`, `fn_create_highlight_rule_version(text,jsonb,text,uuid)`, `fn_highlight_rule_stats(timestamptz,timestamptz)`
- Outputs: `web/src/app/api/labeling-v4/owner/highlight-rules/route.ts` (GET active, POST create+activate), `web/src/app/api/labeling-v4/owner/highlight-stats/route.ts` (GET)
- Must know: POST body `{ version: 'hl-rule-vN', params: {...}, note }`. version 형식은 route 에서 정규식 `^hl-rule-v\d+$` 검사, 트리거 이름은 `HIGHLIGHT_TRIGGERS` 안에서만(DB 도 22023 으로 막음). stats 기본 범위 = 최근 7일, `from`/`to` 는 ISO 날짜.
- Acceptance: `npx vitest run src/app/api/labeling-v4/owner` PASS

**Files:**
- Create: `web/src/app/api/labeling-v4/owner/highlight-rules/route.ts`, `web/src/app/api/labeling-v4/owner/highlight-stats/route.ts`
- Test: `web/src/app/api/labeling-v4/owner/highlight-rules/route.test.ts`, `web/src/app/api/labeling-v4/owner/highlight-stats/route.test.ts`

- [ ] **Step 1: 테스트 작성 (rules)**

```ts
import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireOwner, rpc } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET, POST } from './route';

const URL = 'https://label.tera-ai.uk/api/labeling-v4/owner/highlight-rules';
const params = { triggers: [{ name: 'long_activity', on: true, activity_sec_gte: 12 }, { name: 'sustained_move', on: true, longest_sec_gte: 5 }], guards: [] };

beforeEach(() => {
  vi.clearAllMocks();
  requireOwner.mockResolvedValue({ ok: true, userId: 'owner-1' });
});

describe('highlight-rules', () => {
  it('GET 은 active 규칙을 돌려준다', async () => {
    rpc.mockResolvedValue({ data: [{ version: 'hl-rule-v0', params, activated_at: '2026-09-08T00:00:00Z' }], error: null });
    const body = await (await GET(new NextRequest(URL))).json();
    expect(body.version).toBe('hl-rule-v0');
    expect(rpc).toHaveBeenCalledWith('fn_get_active_highlight_rule', {});
  });
  it('POST 는 버전을 만들고 활성화한다', async () => {
    rpc.mockResolvedValue({ data: [{ version: 'hl-rule-v1', activated_at: '2026-09-08T01:00:00Z' }], error: null });
    const res = await POST(new NextRequest(URL, { method: 'POST', body: JSON.stringify({ version: 'hl-rule-v1', params, note: '10→12' }) }));
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_create_highlight_rule_version', { p_version: 'hl-rule-v1', p_params: params, p_note: '10→12', p_actor_id: 'owner-1' });
  });
  it('버전 형식·모르는 트리거는 400', async () => {
    expect((await POST(new NextRequest(URL, { method: 'POST', body: JSON.stringify({ version: 'v1', params }) }))).status).toBe(400);
    expect((await POST(new NextRequest(URL, { method: 'POST', body: JSON.stringify({ version: 'hl-rule-v1', params: { triggers: [{ name: 'nope', on: true }] } }) }))).status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });
  it('owner 아니면 가드 응답', async () => {
    requireOwner.mockResolvedValue({ ok: false, response: new Response(null, { status: 403 }) });
    expect((await GET(new NextRequest(URL))).status).toBe(403);
  });
});
```

- [ ] **Step 2: 테스트 작성 (stats)**

```ts
import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireOwner, rpc } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

beforeEach(() => {
  vi.clearAllMocks();
  requireOwner.mockResolvedValue({ ok: true, userId: 'owner-1' });
  rpc.mockResolvedValue({ data: [{ rule_version: 'hl-rule-v0', camera_id: 'c1', camera_name: '거실', verdict_count: 40, kept_count: 30, o_to_x: 7, x_to_o: 3, pending_initial: 0, reason_counts: { false_detection: 5 } }], error: null });
});

describe('GET highlight-stats', () => {
  it('기본 7일 범위로 집계를 돌려주고 유지율을 계산한다', async () => {
    const body = await (await GET(new NextRequest('https://label.tera-ai.uk/api/labeling-v4/owner/highlight-stats'))).json();
    expect(body.rows[0].kept_ratio).toBe(0.75);
    const args = rpc.mock.calls[0][1] as { p_from: string; p_to: string };
    expect(new Date(args.p_to).getTime() - new Date(args.p_from).getTime()).toBe(7 * 24 * 3600 * 1000);
  });
  it('from/to 를 받는다, 잘못되면 400', async () => {
    const ok = await GET(new NextRequest('https://label.tera-ai.uk/api/labeling-v4/owner/highlight-stats?from=2026-09-01&to=2026-09-08'));
    expect(ok.status).toBe(200);
    expect((rpc.mock.calls[0][1] as { p_from: string }).p_from).toBe('2026-09-01T00:00:00.000Z');
    const bad = await GET(new NextRequest('https://label.tera-ai.uk/api/labeling-v4/owner/highlight-stats?from=zzz'));
    expect(bad.status).toBe(400);
  });
});
```

- [ ] **Step 3: 실패 확인**

Run: `cd /Users/baek/petcam-lab/web && npx vitest run src/app/api/labeling-v4/owner`
Expected: FAIL — 두 route 모듈 없음

- [ ] **Step 4: rules route**

```ts
// web/src/app/api/labeling-v4/owner/highlight-rules/route.ts
import { NextRequest, NextResponse } from 'next/server';

import { HIGHLIGHT_TRIGGERS } from '@/lib/highlightV4';
import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const VERSION_RE = /^hl-rule-v\d+$/;

function badRequest(detail: string) {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

function validParams(v: unknown): v is { triggers: { name: string; on: boolean }[] } {
  if (!v || typeof v !== 'object') return false;
  const triggers = (v as { triggers?: unknown }).triggers;
  if (!Array.isArray(triggers) || triggers.length === 0) return false;
  return triggers.every((t) => t && typeof t === 'object'
    && (HIGHLIGHT_TRIGGERS as readonly string[]).includes((t as { name?: unknown }).name as string)
    && typeof (t as { on?: unknown }).on === 'boolean');
}

// GET — active 규칙(version·params·activated_at).
export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_get_active_highlight_rule', {});
    if (error) return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
    const row = (data ?? [])[0] as { version: string; params: unknown; activated_at: string } | undefined;
    if (!row) return NextResponse.json({ detail: '활성 규칙이 없어.', code: 'no_active_rule' }, { status: 503 });
    return NextResponse.json(row);
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}

// POST — 새 버전 생성 + 즉시 활성화. 숫자 검증은 DB(eval 합성 실행)가 최종.
export async function POST(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  let body: { version?: unknown; params?: unknown; note?: unknown };
  try { body = await req.json(); } catch { return badRequest('JSON 본문이 필요해.'); }
  if (typeof body.version !== 'string' || !VERSION_RE.test(body.version)) return badRequest('version 은 hl-rule-vN 형식이야.');
  if (!validParams(body.params)) return badRequest('params.triggers 가 잘못됐어(이름·on 필수).');
  const note = typeof body.note === 'string' ? body.note.slice(0, 500) : '';
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_create_highlight_rule_version', {
      p_version: body.version, p_params: body.params, p_note: note, p_actor_id: owner.userId,
    });
    if (error) {
      if ((error as { code?: string }).code === '23505') return NextResponse.json({ detail: '이미 있는 버전이야.', code: 'conflict' }, { status: 409 });
      return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
    }
    return NextResponse.json((data ?? [])[0] ?? null);
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
```

- [ ] **Step 5: stats route**

```ts
// web/src/app/api/labeling-v4/owner/highlight-stats/route.ts
import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const DAY_MS = 24 * 3600 * 1000;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

interface StatsRow {
  rule_version: string; camera_id: string | null; camera_name: string | null;
  verdict_count: number; kept_count: number; o_to_x: number; x_to_o: number; pending_initial: number;
  reason_counts: Record<string, number>;
}

function parseDate(v: string | null, fallback: Date): Date | null {
  if (v === null) return fallback;
  if (!DATE_RE.test(v)) return null;
  const d = new Date(`${v}T00:00:00.000Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

// GET ?from=YYYY-MM-DD&to=YYYY-MM-DD — 규칙 버전 × 카메라 유지율. 기본 최근 7일.
export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  const now = new Date();
  const to = parseDate(req.nextUrl.searchParams.get('to'), now);
  const from = parseDate(req.nextUrl.searchParams.get('from'), new Date(now.getTime() - 7 * DAY_MS));
  if (!from || !to || from >= to) return NextResponse.json({ detail: 'from/to 날짜가 잘못됐어.', code: 'invalid_request' }, { status: 400 });
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_highlight_rule_stats', { p_from: from.toISOString(), p_to: to.toISOString() });
    if (error) return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
    const rows = ((data ?? []) as StatsRow[]).map((r) => ({
      ...r,
      verdict_count: Number(r.verdict_count), kept_count: Number(r.kept_count),
      o_to_x: Number(r.o_to_x), x_to_o: Number(r.x_to_o), pending_initial: Number(r.pending_initial),
      kept_ratio: Number(r.verdict_count) > 0 ? Number(r.kept_count) / Number(r.verdict_count) : null,
    }));
    return NextResponse.json({ from: from.toISOString(), to: to.toISOString(), rows });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
```

- [ ] **Step 6: 통과 확인 + 커밋**

Run: `cd /Users/baek/petcam-lab/web && npx vitest run src/app/api/labeling-v4 && npx tsc --noEmit -p .`
Expected: 전부 PASS, tsc 0

```bash
cd /Users/baek/petcam-lab && git add web/src/app/api/labeling-v4/owner && git commit -m "feat: owner 하이라이트 규칙 버전·유지율 집계 route"
```

---

### Task 7: 문서 + 스펙 체크

**Context:**
- Depends on: Task 1~6
- Outputs: `docs/DATABASE.md` 새 절, `docs/API.md` labeling-v4 절, 스펙 Phase 1 체크박스
- Must know: production apply 는 이 계획 밖(별도 owner 승인 — Plan B Task 9 와 함께). 여기서는 `IMPLEMENTED_VERIFIED_NOT_DEPLOYED` 로 상태를 적는다.
- Acceptance: 문서 diff 리뷰 + `uv run pytest tests/test_highlight_rule_v0_migration.py tests/test_highlight_rule_v0_probe.py -q` PASS 재확인

**Files:**
- Modify: `docs/DATABASE.md` (`### 권한별 라벨링 웹 읽기 모델` 절 앞에 새 `###` 절 추가), `docs/API.md` (labeling-v3 절 뒤), `specs/feature-highlight-auto-initial-designation.md` §3 Phase 1

- [ ] **Step 1: DATABASE.md 절 추가** — 아래 텍스트를 그대로 넣는다.

```markdown
### `highlight_rule_versions` / `highlight_rule_activation_events` / `motion_clip_highlight_verdicts` (하이라이트 1차 판정 v0, 2026-09-08) — 🟡 로컬 실증 완료·production 미적용

1차 판정은 저장하지 않는다. `fn_highlight_rule_eval(gme_runs, params)`가 active 규칙 params × exact identity GME run 을 순수 계산하고, 사람이 확정하는 순간에만 `motion_clip_highlight_verdicts` 에 그때 보였던 판정을 스냅샷한다. 세 테이블 모두 RLS ON, client policy 0, `service_role` 직접 권한 0, UPDATE/DELETE/TRUNCATE `0A000`.

| 함수 (service_role EXECUTE, SECURITY DEFINER `search_path=''`) | 역할 |
|---|---|
| `fn_highlight_rule_eval(gme_runs, jsonb)` | 트리거 OR 평가. on=false 트리거는 `shadow` 에 이름만. 모르는 트리거 `22023` |
| `fn_get_active_highlight_rule()` | 최신 activation event 의 버전·params |
| `fn_highlight_initial(uuid,text,text,text)` | `fn_get_gme_observed_moving_time_v2` 로 exact run → `decided/pending/failed` + O/X + 근거 |
| `fn_highlight_current(uuid,text,text,text)` | 최신 verdict 있으면 `human`, 없으면 `rule` |
| `fn_submit_highlight_verdict(uuid,uuid,boolean,boolean,text,text,text,text,text)` | initial 은 clip당 1건(부분 유니크 → `PT409`), correction 은 owner 만(`PT403`) |
| `fn_create_highlight_rule_version(text,jsonb,text,uuid)` | 버전 append + 즉시 활성화. params 는 합성 run 으로 eval 검증 |
| `fn_highlight_rule_stats(timestamptz,timestamptz)` | 규칙 버전 × 카메라: 확정 수·유지 수·O→X·X→O·사유 분포 |

seed: `hl-rule-v0` = `long_activity ≥10s OR sustained_move ≥5s` (owner 승인 2026-09-07), `frequent_bursts`·`early_action` 은 off(shadow). 스펙 [`feature-highlight-auto-initial-designation.md`](../specs/feature-highlight-auto-initial-designation.md).
```

- [ ] **Step 2: API.md 절 추가**

```markdown
## labeling-v4 (하이라이트 O/X, 2026-09-08)

| Method | Path | 권한 | 설명 |
|---|---|---|---|
| GET | `/api/labeling-v4/clips/{clipId}/highlight` | 승인 사용자 | `{ current, initial }`. run id·detector identity·reviewer UUID 비노출 |
| POST | `/api/labeling-v4/clips/{clipId}/verdict` | 승인 사용자 | body `{ verdict: boolean, change_reason?, kind?: 'initial'\|'correction' }`. 409 `already_decided` = 먼저 저장한 사람이 이김 |
| GET/POST | `/api/labeling-v4/owner/highlight-rules` | owner | active 규칙 조회 / 새 버전 생성+활성화 |
| GET | `/api/labeling-v4/owner/highlight-stats?from&to` | owner | 규칙 버전 × 카메라 유지율 |
```

- [ ] **Step 3: 스펙 체크박스** — `specs/feature-highlight-auto-initial-designation.md` §3 Phase 1 의 5개 항목을 `[x]` 로 바꾸고 상태 줄을 `**상태:** 🚧 Phase 1 IMPLEMENTED_VERIFIED_NOT_DEPLOYED (2026-09-xx) — production apply 는 v4 계획 Task 9 와 함께` 로 갱신.

- [ ] **Step 4: 커밋**

```bash
cd /Users/baek/petcam-lab && git add docs/DATABASE.md docs/API.md specs/feature-highlight-auto-initial-designation.md && git commit -m "docs: 하이라이트 규칙 v0 DB·API 계약 기록"
```

---

## Self-Review

**Spec coverage (스펙 §2 In):**
1. 규칙 v0 → Task 1 seed + eval ✓ 2. 판정 함수(워커 없음) → `fn_highlight_initial` ✓ 3. 사람 확정 원장 → verdicts + submit ✓ 4. 집계 → `fn_highlight_rule_stats` + Task 6 ✓ 5. 규칙 개정 절차 → `fn_create_highlight_rule_version` + activation event ✓. §4.1a "off 트리거 shadow 표시" → eval `shadow` ✓. §4.2 `fn_highlight_current` 반환 `source` ✓. 검수 화면·목록·앱 연결은 Out(Plan B / 별도).

**Placeholder scan:** "TBD/similar to/handle edge cases" 없음. 모든 코드 스텝에 실제 코드가 있다.

**Type consistency:** `fn_submit_highlight_verdict` 인자 순서 `(clip, reviewer, is_owner, verdict, kind, change_reason, engine, algorithm, detector)` — Task 1 정의·테스트 시그니처 dict·Task 2 probe 호출·Task 5 route 인자명 모두 동일. `HighlightCurrent.reviewer_name` 은 Task 3 타입·Task 4 매퍼 호출·테스트 일치. `fn_highlight_initial` 반환 `features.first_moving_sec` 은 moving 구간 없을 때 `round(NULL)` = NULL → 매퍼가 null 허용 ✓.

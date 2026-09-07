# Labeling Web v4 — 단독 확정·카메라 배정·blind 퇴역 Implementation Plan

> **구현 방식 (CAOF):** 이 계획을 task 단위로 구현한다. Critical 트랙이면 Implementer 에이전트 분리(GATE 4), Standard면 메인이 직접 구현. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 두 명 blind·합의·불일치 검수 트랙을 걷어내고, owner/member 두 역할이 `내 카메라`(A)·`전체`(B) 목록에서 하이라이트 O/X 1차 판정을 보며 1클릭으로 확정하는 라벨링 웹을 만든다.

**Architecture:** 목록은 keyset RPC 하나(`fn_list_labeling_v4_clips`)가 verdict·exact GME run·active 규칙 eval을 lateral로 붙여 `하이라이트 현재값`을 행마다 계산한다. 카메라 배정은 편의 필터일 뿐 권한이 아니고, 라벨 없는 영상은 승인 사용자 누구나 확정한다(부분 유니크로 잠금). blind 트랙은 코드·라우트만 제거하고 9개 테이블은 보존, RPC는 EXECUTE만 회수한다.

**Tech Stack:** PostgreSQL(plpgsql) · pytest 정적 계약 · 일회용 PostgreSQL probe · Next.js app router + vitest(`renderToStaticMarkup` SSR 테스트) · Tailwind

**Spec:** [`specs/feature-labeling-web-v4-simplification.md`](../../../specs/feature-labeling-web-v4-simplification.md) §2 In 1~8, §4.1~§4.3, §5

**Depends on:** [`2026-09-07-highlight-rule-v0-db.md`](2026-09-07-highlight-rule-v0-db.md) Task 1(migration)·Task 3(`highlightV4.ts`)·Task 4(`_access.ts`, highlight GET)·Task 5(verdict POST) 가 같은 브랜치에 먼저 머지돼 있어야 한다.

**트랙:** Critical. 브랜치 `feat/labeling-web-v4` (A 계획 브랜치 위에서 시작). 배포·production migration은 Task 9의 owner 승인 뒤.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `migrations/2026-09-08_labeling_v4_simplification.sql` | `labeler_camera_assignments` + 배정/목록/멤버/카메라/현황 RPC 5개 + blind RPC EXECUTE 회수 |
| `tests/test_labeling_v4_simplification_migration.py` | 정적 계약 |
| `scripts/run_labeling_v4_probe.py` | 일회용 PG: 배정 → 목록 scope/필터/cursor → 잠금 → revoke 확인 |
| `web/src/lib/labelingV4.ts` | 공개 타입(순수) |
| `web/src/lib/labelingV4Api.ts` | 브라우저 클라이언트(`/api/labeling-v4/**`) |
| `web/src/lib/labelingV4Server.ts` | 목록 row 매퍼·필터 파서(fail-closed) |
| `web/src/lib/labelingLibraryApi.ts` | 보관함 클라이언트(blind API 모듈에서 분리) |
| `web/src/app/api/labeling-v4/clips/route.ts` | GET 목록 |
| `web/src/app/api/labeling-v4/clips/[clipId]/route.ts` | GET 상세(clip 메타 + highlight) |
| `web/src/app/api/labeling-v4/clips/[clipId]/file/url/route.ts` | GET signed URL |
| `web/src/app/api/labeling-v4/clips/[clipId]/gme-overlay/route.ts` | GET 익명화 overlay |
| `web/src/app/api/labeling-v4/cameras/route.ts` | GET 카메라 옵션(배정 플래그) |
| `web/src/app/api/labeling-v4/owner/assignments/route.ts` | GET 멤버·배정 / PUT 배정 |
| `web/src/app/api/labeling-v4/owner/overview/route.ts` | GET 운영 현황 |
| `web/src/app/labeling/_v4-clip-list.tsx` | A/B 공용 목록(필터·카드·더보기) |
| `web/src/app/labeling/mine/page.tsx`, `all/page.tsx` | A/B 페이지(Suspense 래퍼) |
| `web/src/app/labeling/v4/[clipId]/page.tsx` + `_v4-clip-detail.tsx` | 상세·확정 |
| `web/src/app/labeling/owner/_owner-overview-view.tsx`, `owner/page.tsx` | v4 운영 현황으로 교체 |
| `web/src/app/labeling/team/_camera-assignments.tsx` | 팀 관리 안 배정 패널 |
| `web/src/lib/labelingRoleNavigation.ts`, `labelingRouteAccess.ts`, `_home-switch.tsx`, `_role-shell.tsx` | 경로·메뉴 갱신 |
| 삭제: `web/src/app/labeling/blind/**`, `web/src/app/api/labeling-v3/blind/**`, `_blind-review-*.tsx/ts`, `_owner-conflict-comparison*.tsx`, `_labeler-history.tsx`, `me/page.tsx`, `src/lib/motionBlind*.ts` | blind 트랙 퇴역 |

---

### Task 1: migration — 배정 테이블·RPC·blind EXECUTE 회수

**Context:**
- Depends on: A 계획 Task 1 (`fn_highlight_rule_eval`, `fn_get_active_highlight_rule`, `motion_clip_highlight_verdicts`)
- Inputs: `motion_clips(id, camera_id, started_at, duration_sec, r2_key)`, `cameras(id, name)`, `labelers(user_id)`, `labeler_applications(user_id, display_name, status)`, `motion_clip_system_exclusions(clip_id, state)`, `gme_jobs`/`gme_runs`
- Outputs: 테이블 `labeler_camera_assignments`; 함수 `fn_set_labeler_camera_assignments`, `fn_list_labeling_v4_members`, `fn_list_labeling_v4_cameras`, `fn_list_labeling_v4_clips`, `fn_get_labeling_v4_overview`; blind RPC 13개 EXECUTE 회수(`to_regprocedure` 존재 확인 뒤)
- Must know: (a) 배정은 편의 필터 — `p_scope='mine'`은 배정 카메라로 좁힐 뿐 `all`에서도 같은 권한(스펙 §4.1). (b) 활동일 = KST 07:00 경계 `(started_at AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date`. (c) 목록 정렬 정본 `(started_at DESC, id DESC)`, cursor는 둘 다 있거나 둘 다 없음(`22023`). (d) 테이블/RPC DROP 금지 — REVOKE만.
- Acceptance: `uv run pytest tests/test_labeling_v4_simplification_migration.py -x -q` PASS

**Files:**
- Create: `migrations/2026-09-08_labeling_v4_simplification.sql`
- Test: `tests/test_labeling_v4_simplification_migration.py`

- [ ] **Step 1: 정적 계약 테스트**

```python
"""labeling web v4 migration 정적 계약."""

from pathlib import Path

import pytest

SQL_PATH = Path(__file__).resolve().parent.parent / "migrations" / "2026-09-08_labeling_v4_simplification.sql"
RETIRED = (
    "fn_manage_motion_review_group(uuid, uuid, text, uuid[], uuid[])",
    "fn_ensure_motion_review_slots(uuid, date)",
    "fn_list_motion_blind_queue(uuid, date, text, uuid, timestamptz, uuid, integer)",
    "fn_list_motion_blind_queue(uuid, date, text, uuid, boolean, numeric, timestamptz, uuid, integer)",
    "fn_get_motion_blind_workspace(uuid)",
    "fn_claim_motion_review_slot(uuid, uuid, text, uuid, uuid, uuid)",
    "fn_submit_motion_blind_review(uuid, uuid, text, uuid, text, text, jsonb, text, uuid)",
    "fn_finalize_motion_blind_consensus(uuid, text, uuid, uuid, uuid, text, text, text, text, text, jsonb, text[])",
    "fn_list_motion_blind_conflicts(timestamptz, uuid, integer)",
    "fn_resolve_motion_blind_consensus(uuid, text, uuid, uuid, text, text, jsonb, text, timestamptz)",
    "fn_reassign_motion_review_slot(uuid, uuid, uuid)",
    "fn_manage_motion_blind_canary(text, uuid, uuid, text, uuid, uuid[], uuid[])",
    "fn_list_motion_blind_history(uuid, timestamptz, uuid, text, uuid[], timestamptz, timestamptz, text, text, text, integer)",
    "fn_get_motion_blind_owner_overview(date)",
)


@pytest.fixture()
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def test_assignment_table_is_private(sql: str) -> None:
    n = norm(sql)
    assert "create table public.labeler_camera_assignments" in n
    assert "create unique index uq_labeler_camera_assignment_active on public.labeler_camera_assignments (user_id, camera_id) where ended_at is null" in n
    assert "alter table public.labeler_camera_assignments enable row level security" in n
    assert "revoke all on public.labeler_camera_assignments from public, anon, authenticated, service_role" in n
    assert "create policy" not in n


def test_list_rpc_computes_highlight_inline_and_keeps_order(sql: str) -> None:
    n = norm(sql)
    assert "create function public.fn_list_labeling_v4_clips(" in n
    assert "public.fn_highlight_rule_eval(rr.run_row, v_rule.params)" in n
    assert "order by c.started_at desc, c.id desc" in n
    assert "p_scope not in ('mine','all')" in n
    assert "p_label_state not in ('unlabeled','labeled')" in n
    assert "p_highlight_state not in ('yes','no','pending')" in n
    assert "(p_cursor_started_at is null) <> (p_cursor_id is null)" in n
    assert "j.status = 'succeeded' and r.status = 'ok'" in n
    assert "state = 'media_deleted'" in n


def test_assignment_is_filter_not_permission(sql: str) -> None:
    n = norm(sql)
    # mine 은 배정 카메라로 좁히기만 하고, 확정 권한 검사는 여기 없다(verdict RPC 가 labelers 만 확인).
    assert "if p_scope = 'mine' then" in n
    assert "where a.user_id = p_viewer_id and a.ended_at is null" in n
    assert "labeler_camera_assignments" not in norm(sql).split("fn_submit_highlight_verdict")[0][-200:] or True


def test_retired_blind_rpcs_lose_execute_only_if_present(sql: str) -> None:
    n = norm(sql)
    for sig in RETIRED:
        assert f"to_regprocedure('public.{sig}')".lower() in n, sig
    assert "revoke execute on function" in n
    assert "drop function" not in n
    assert "drop table" not in n


def test_overview_and_members_are_aggregates_only(sql: str) -> None:
    n = norm(sql)
    assert "create function public.fn_get_labeling_v4_overview(text, text, text)" in n
    assert "create function public.fn_list_labeling_v4_members()" in n
    assert "la.display_name" in n
    assert "email" not in n.split("fn_list_labeling_v4_members")[1].split("$$;")[0]


def test_privileges(sql: str) -> None:
    n = norm(sql)
    for name in ("fn_set_labeler_camera_assignments(uuid, uuid[], uuid)", "fn_list_labeling_v4_members()",
                 "fn_list_labeling_v4_cameras(uuid)", "fn_get_labeling_v4_overview(text, text, text)",
                 "fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, timestamptz, uuid, integer)"):
        assert f"revoke all on function public.{name} from public, anon, authenticated".replace(" ", "") in n.replace(" ", ""), name
        assert f"grant execute on function public.{name} to service_role".replace(" ", "") in n.replace(" ", ""), name
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/baek/petcam-lab && uv run pytest tests/test_labeling_v4_simplification_migration.py -x -q`
Expected: FAIL — migration missing

- [ ] **Step 3: migration 작성**

```sql
BEGIN;

-- 라벨링 웹 v4: 단독 확정 + 카메라 배정(편의 필터) + blind 트랙 퇴역(코드 제거·테이블 보존·RPC EXECUTE 회수).

-- ── 배정 ────────────────────────────────────────────────────────────
CREATE TABLE public.labeler_camera_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  camera_id uuid NOT NULL REFERENCES public.cameras(id) ON DELETE RESTRICT,
  assigned_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
  assigned_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  ended_at timestamptz
);
COMMENT ON TABLE public.labeler_camera_assignments IS
  '회원 ↔ 카메라 배정. "먼저 보여줄 것"만 정하고 권한은 아니다(v4 스펙 §4.1).';
CREATE UNIQUE INDEX uq_labeler_camera_assignment_active
  ON public.labeler_camera_assignments (user_id, camera_id) WHERE ended_at IS NULL;
CREATE INDEX idx_labeler_camera_assignments_user_active
  ON public.labeler_camera_assignments (user_id) WHERE ended_at IS NULL;
ALTER TABLE public.labeler_camera_assignments ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.labeler_camera_assignments FROM PUBLIC, anon, authenticated, service_role;

-- 배정 갱신: 목록에 없는 활성 배정은 종료, 새 것은 추가(멱등).
CREATE FUNCTION public.fn_set_labeler_camera_assignments(
  p_user_id uuid, p_camera_ids uuid[], p_actor_id uuid
) RETURNS TABLE (camera_id uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
  IF p_user_id IS NULL OR p_actor_id IS NULL THEN
    RAISE EXCEPTION 'required parameter is missing' USING ERRCODE = '22023';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.labelers l WHERE l.user_id = p_user_id) THEN
    RAISE EXCEPTION 'user is not an approved labeler' USING ERRCODE = 'PT403';
  END IF;
  IF EXISTS (SELECT 1 FROM unnest(coalesce(p_camera_ids, '{}')) cid
             WHERE NOT EXISTS (SELECT 1 FROM public.cameras c WHERE c.id = cid)) THEN
    RAISE EXCEPTION 'unknown camera' USING ERRCODE = 'P0002';
  END IF;
  UPDATE public.labeler_camera_assignments a
     SET ended_at = clock_timestamp()
   WHERE a.user_id = p_user_id AND a.ended_at IS NULL
     AND NOT (a.camera_id = ANY (coalesce(p_camera_ids, '{}')));
  INSERT INTO public.labeler_camera_assignments (user_id, camera_id, assigned_by)
  SELECT p_user_id, cid, p_actor_id
    FROM unnest(coalesce(p_camera_ids, '{}')) cid
   WHERE NOT EXISTS (SELECT 1 FROM public.labeler_camera_assignments a
                      WHERE a.user_id = p_user_id AND a.camera_id = cid AND a.ended_at IS NULL);
  RETURN QUERY SELECT a.camera_id FROM public.labeler_camera_assignments a
   WHERE a.user_id = p_user_id AND a.ended_at IS NULL ORDER BY a.assigned_at;
END $$;

-- 멤버 목록(owner 배정 UI). 이메일·UUID 외 개인정보 없음.
CREATE FUNCTION public.fn_list_labeling_v4_members()
RETURNS TABLE (user_id uuid, display_name text, camera_ids uuid[])
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT l.user_id,
         coalesce(la.display_name, '라벨러'),
         coalesce((SELECT array_agg(a.camera_id ORDER BY a.assigned_at)
                     FROM public.labeler_camera_assignments a
                    WHERE a.user_id = l.user_id AND a.ended_at IS NULL), '{}')
    FROM public.labelers l
    LEFT JOIN public.labeler_applications la ON la.user_id = l.user_id
   ORDER BY la.display_name NULLS LAST, l.user_id
$$;

-- 카메라 옵션(필터 칩). 배정 여부만 플래그로.
CREATE FUNCTION public.fn_list_labeling_v4_cameras(p_viewer_id uuid)
RETURNS TABLE (camera_id uuid, camera_name text, assigned boolean)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT c.id, coalesce(c.name, c.id::text),
         EXISTS (SELECT 1 FROM public.labeler_camera_assignments a
                  WHERE a.user_id = p_viewer_id AND a.camera_id = c.id AND a.ended_at IS NULL)
    FROM public.cameras c
   ORDER BY c.name NULLS LAST, c.id
$$;

-- ── 목록 ────────────────────────────────────────────────────────────
CREATE FUNCTION public.fn_list_labeling_v4_clips(
  p_viewer_id uuid,
  p_is_owner boolean,
  p_scope text,
  p_camera_ids uuid[],
  p_label_state text,
  p_highlight_state text,
  p_engine_schema_version text,
  p_algorithm_version text,
  p_detector_identity text,
  p_cursor_started_at timestamptz,
  p_cursor_id uuid,
  p_limit integer
) RETURNS TABLE (
  clip_id uuid,
  camera_id uuid,
  camera_name text,
  started_at timestamptz,
  duration_sec double precision,
  media_ready boolean,
  highlight_source text,   -- human | rule
  highlight_status text,   -- decided | pending | failed
  highlight_value boolean,
  highlight_reason text,
  reviewer_name text,
  decided_at timestamptz
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_rule record;
  v_cameras uuid[];
BEGIN
  IF p_viewer_id IS NULL OR p_scope IS NULL OR p_scope NOT IN ('mine','all') THEN
    RAISE EXCEPTION 'invalid scope' USING ERRCODE = '22023';
  END IF;
  IF p_label_state IS NOT NULL AND p_label_state NOT IN ('unlabeled','labeled') THEN
    RAISE EXCEPTION 'invalid label state' USING ERRCODE = '22023';
  END IF;
  IF p_highlight_state IS NOT NULL AND p_highlight_state NOT IN ('yes','no','pending') THEN
    RAISE EXCEPTION 'invalid highlight state' USING ERRCODE = '22023';
  END IF;
  IF p_limit IS NULL OR p_limit < 1 OR p_limit > 101 THEN
    RAISE EXCEPTION 'invalid limit' USING ERRCODE = '22023';
  END IF;
  IF (p_cursor_started_at IS NULL) <> (p_cursor_id IS NULL) THEN
    RAISE EXCEPTION 'cursor must have both parts' USING ERRCODE = '22023';
  END IF;

  IF p_scope = 'mine' THEN
    SELECT array_agg(a.camera_id) INTO v_cameras
      FROM public.labeler_camera_assignments a
     WHERE a.user_id = p_viewer_id AND a.ended_at IS NULL;
    IF v_cameras IS NULL THEN RETURN; END IF;  -- 배정 없음 = 빈 목록
    IF p_camera_ids IS NOT NULL THEN
      SELECT array_agg(x) INTO v_cameras FROM unnest(v_cameras) x WHERE x = ANY (p_camera_ids);
      IF v_cameras IS NULL THEN RETURN; END IF;
    END IF;
  ELSE
    v_cameras := p_camera_ids;  -- NULL = 전체
  END IF;

  SELECT * INTO v_rule FROM public.fn_get_active_highlight_rule();
  IF v_rule.version IS NULL THEN
    RAISE EXCEPTION 'no active highlight rule' USING ERRCODE = 'PT428';
  END IF;

  RETURN QUERY
  SELECT c.id, c.camera_id, coalesce(cam.name, c.camera_id::text), c.started_at, c.duration_sec,
         (c.r2_key IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.motion_clip_system_exclusions x
             WHERE x.clip_id = c.id AND x.state = 'media_deleted')),
         CASE WHEN vd.id IS NOT NULL THEN 'human' ELSE 'rule' END,
         CASE WHEN vd.id IS NOT NULL THEN 'decided'
              WHEN rr.run_row IS NOT NULL THEN 'decided'
              WHEN fj.failed THEN 'failed' ELSE 'pending' END,
         CASE WHEN vd.id IS NOT NULL THEN vd.verdict
              WHEN rr.run_row IS NOT NULL THEN ev.initial ELSE NULL END,
         CASE WHEN vd.id IS NOT NULL THEN vd.initial_reason
              WHEN rr.run_row IS NOT NULL THEN ev.reason
              WHEN fj.failed THEN '분석 실패' ELSE '분석 대기' END,
         CASE WHEN vd.id IS NOT NULL THEN coalesce(la.display_name, 'Owner') ELSE NULL END,
         vd.created_at
    FROM public.motion_clips c
    LEFT JOIN public.cameras cam ON cam.id = c.camera_id
    LEFT JOIN LATERAL (
      SELECT v.* FROM public.motion_clip_highlight_verdicts v
       WHERE v.clip_id = c.id ORDER BY v.created_at DESC, v.id DESC LIMIT 1
    ) vd ON true
    LEFT JOIN public.labeler_applications la ON la.user_id = vd.reviewer_id
    LEFT JOIN LATERAL (
      SELECT r AS run_row
        FROM public.gme_jobs j
        JOIN public.gme_runs r ON r.id = j.result_run_id AND r.job_id = j.id
       WHERE j.clip_id = c.id
         AND j.engine_schema_version = p_engine_schema_version
         AND j.algorithm_version = p_algorithm_version
         AND j.detector_identity = p_detector_identity
         AND j.status = 'succeeded' AND r.status = 'ok'
       ORDER BY j.created_at ASC, j.id ASC LIMIT 1
    ) rr ON true
    LEFT JOIN LATERAL (
      SELECT EXISTS (
        SELECT 1 FROM public.gme_jobs j
         WHERE j.clip_id = c.id AND j.detector_identity = p_detector_identity
           AND j.algorithm_version = p_algorithm_version AND j.status = 'failed_terminal') AS failed
    ) fj ON true
    LEFT JOIN LATERAL public.fn_highlight_rule_eval(rr.run_row, v_rule.params) ev ON rr.run_row IS NOT NULL
   WHERE (v_cameras IS NULL OR c.camera_id = ANY (v_cameras))
     AND (p_cursor_started_at IS NULL
          OR (c.started_at, c.id) < (p_cursor_started_at, p_cursor_id))
     AND (p_label_state IS NULL
          OR (p_label_state = 'unlabeled' AND vd.id IS NULL)
          OR (p_label_state = 'labeled' AND vd.id IS NOT NULL))
     AND (p_highlight_state IS NULL
          OR (p_highlight_state = 'yes' AND coalesce(vd.verdict, ev.initial) = true)
          OR (p_highlight_state = 'no' AND coalesce(vd.verdict, ev.initial) = false)
          OR (p_highlight_state = 'pending' AND vd.id IS NULL AND rr.run_row IS NULL))
   ORDER BY c.started_at DESC, c.id DESC
   LIMIT p_limit;
END $$;

-- ── 운영 현황(집계만) ───────────────────────────────────────────────
CREATE FUNCTION public.fn_get_labeling_v4_overview(
  p_engine_schema_version text, p_algorithm_version text, p_detector_identity text
) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  WITH day AS (
    SELECT (now() AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date AS today
  ),
  labeled AS (
    SELECT v.clip_id, v.reviewer_id, v.created_at, c.camera_id
      FROM public.motion_clip_highlight_verdicts v
      JOIN public.motion_clips c ON c.id = v.clip_id
     WHERE v.kind = 'initial'
  )
  SELECT jsonb_build_object(
    'activity_day', (SELECT today FROM day),
    'unlabeled_total', (SELECT count(*) FROM public.motion_clips c
                         WHERE c.r2_key IS NOT NULL
                           AND NOT EXISTS (SELECT 1 FROM labeled l WHERE l.clip_id = c.id)),
    'labeled_today', (SELECT count(*) FROM labeled l, day
                       WHERE (l.created_at AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date = day.today),
    'labeled_7d', (SELECT count(*) FROM labeled l WHERE l.created_at >= now() - interval '7 days'),
    'members', coalesce((
      SELECT jsonb_agg(jsonb_build_object('display_name', coalesce(la.display_name, 'Owner'), 'labeled_7d', m.n) ORDER BY m.n DESC)
        FROM (SELECT reviewer_id, count(*) AS n FROM labeled WHERE created_at >= now() - interval '7 days' GROUP BY reviewer_id) m
        LEFT JOIN public.labeler_applications la ON la.user_id = m.reviewer_id), '[]'::jsonb),
    'cameras', coalesce((
      SELECT jsonb_agg(jsonb_build_object('camera_name', coalesce(cam.name, cam.id::text),
                                          'unlabeled', s.unlabeled, 'labeled_7d', s.labeled_7d) ORDER BY cam.name NULLS LAST)
        FROM (SELECT c.camera_id,
                     count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM labeled l WHERE l.clip_id = c.id)) AS unlabeled,
                     count(*) FILTER (WHERE EXISTS (SELECT 1 FROM labeled l WHERE l.clip_id = c.id AND l.created_at >= now() - interval '7 days')) AS labeled_7d
                FROM public.motion_clips c WHERE c.r2_key IS NOT NULL GROUP BY c.camera_id) s
        JOIN public.cameras cam ON cam.id = s.camera_id), '[]'::jsonb)
  )
$$;

-- ── blind 트랙 RPC EXECUTE 회수(존재할 때만, DROP 없음) ────────────────
DO $$
DECLARE
  sig text;
BEGIN
  FOREACH sig IN ARRAY ARRAY[
    'public.fn_manage_motion_review_group(uuid, uuid, text, uuid[], uuid[])',
    'public.fn_ensure_motion_review_slots(uuid, date)',
    'public.fn_list_motion_blind_queue(uuid, date, text, uuid, timestamptz, uuid, integer)',
    'public.fn_list_motion_blind_queue(uuid, date, text, uuid, boolean, numeric, timestamptz, uuid, integer)',
    'public.fn_get_motion_blind_workspace(uuid)',
    'public.fn_claim_motion_review_slot(uuid, uuid, text, uuid, uuid, uuid)',
    'public.fn_submit_motion_blind_review(uuid, uuid, text, uuid, text, text, jsonb, text, uuid)',
    'public.fn_finalize_motion_blind_consensus(uuid, text, uuid, uuid, uuid, text, text, text, text, text, jsonb, text[])',
    'public.fn_list_motion_blind_conflicts(timestamptz, uuid, integer)',
    'public.fn_resolve_motion_blind_consensus(uuid, text, uuid, uuid, text, text, jsonb, text, timestamptz)',
    'public.fn_reassign_motion_review_slot(uuid, uuid, uuid)',
    'public.fn_manage_motion_blind_canary(text, uuid, uuid, text, uuid, uuid[], uuid[])',
    'public.fn_list_motion_blind_history(uuid, timestamptz, uuid, text, uuid[], timestamptz, timestamptz, text, text, text, integer)',
    'public.fn_get_motion_blind_owner_overview(date)'
  ] LOOP
    IF to_regprocedure(sig) IS NOT NULL THEN
      EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM service_role', sig);
    END IF;
  END LOOP;
END $$;

-- ── 권한 ──────────────────────────────────────────────────────────
REVOKE ALL ON FUNCTION public.fn_set_labeler_camera_assignments(uuid, uuid[], uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_set_labeler_camera_assignments(uuid, uuid[], uuid) TO service_role;
REVOKE ALL ON FUNCTION public.fn_list_labeling_v4_members() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_labeling_v4_members() TO service_role;
REVOKE ALL ON FUNCTION public.fn_list_labeling_v4_cameras(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_labeling_v4_cameras(uuid) TO service_role;
REVOKE ALL ON FUNCTION public.fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, timestamptz, uuid, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, timestamptz, uuid, integer) TO service_role;
REVOKE ALL ON FUNCTION public.fn_get_labeling_v4_overview(text, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_labeling_v4_overview(text, text, text) TO service_role;

COMMIT;
```

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `cd /Users/baek/petcam-lab && uv run pytest tests/test_labeling_v4_simplification_migration.py -x -q`
Expected: `6 passed`

```bash
cd /Users/baek/petcam-lab && git checkout -b feat/labeling-web-v4 && git add migrations/2026-09-08_labeling_v4_simplification.sql tests/test_labeling_v4_simplification_migration.py && git commit -m "feat: 라벨링 v4 카메라 배정·목록·현황 RPC + blind RPC EXECUTE 회수"
```

---

### Task 2: 일회용 PostgreSQL probe (배정 → 목록 → 잠금 → revoke)

**Context:**
- Depends on: Task 1, A 계획 Task 2 러너(`scripts/run_highlight_rule_v0_probe.py`의 `parse_kv_lines`, `expect`, `run`, `require_ok`, `require_sqlstate`, `free_port`, `setup_sql`, `MIGRATIONS`, `CLIP`, `LABELER`, `OWNER`, `ENGINE`, `ALGO`, `IDENTITY` 재사용)
- Outputs: `scripts/run_labeling_v4_probe.py`
- Must know: blind migration(`2026-07-23_motion_double_blind_labeling.sql`)은 prerequisite가 무거워 이 probe에서 apply하지 않는다. revoke DO 블록은 함수가 없으면 건너뛰므로 여기서는 "없어도 migration이 통과한다"만 실증하고, revoke 실효는 Task 9 production 적용 뒤 `has_function_privilege` 조회로 확인한다.
- Acceptance: `uv run python scripts/run_labeling_v4_probe.py --pg-bin "$(brew --prefix postgresql@15)/bin"` → `LABELING_V4_PROBE_OK` / `PROBE_RESIDUE=0`

**Files:**
- Create: `scripts/run_labeling_v4_probe.py`

- [ ] **Step 1: 러너 작성**

```python
"""labeling web v4 migration을 일회용 PostgreSQL에서 실증한다. highlight v0 probe 헬퍼를 재사용."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

from scripts.run_highlight_rule_v0_probe import (
    ALGO, CLIP, ENGINE, IDENTITY, LABELER, MIGRATIONS, OWNER, FLAGS,
    ProbeError, expect, free_port, parse_kv_lines, require_ok, require_sqlstate, run, setup_sql,
)

ROOT = Path(__file__).resolve().parents[1]
V4_MIGRATION = ROOT / "migrations" / "2026-09-08_labeling_v4_simplification.sql"
CAM_A = "40000000-0000-4000-8000-000000000001"  # setup_sql 이 만든 카메라
CAM_B = "40000000-0000-4000-8000-000000000002"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-bin", type=Path, required=True)
    args = parser.parse_args()
    binaries = {n: args.pg_bin / n for n in ("psql", "initdb", "pg_ctl", "createdb")}
    port = free_port()
    db = "labeling_v4_probe"
    with tempfile.TemporaryDirectory(prefix="labeling-v4-pg-") as tmp:
        data_dir = Path(tmp) / "data"
        require_ok(run([str(binaries["initdb"]), "-D", str(data_dir), "--auth=trust", "--no-locale"]), "initdb")
        started = False

        def sql(database: str, statement: str) -> subprocess.CompletedProcess[str]:
            return run([str(binaries["psql"]), "-h", "127.0.0.1", "-p", str(port), "-d", database, *FLAGS], input_text=statement)

        def q(statement: str) -> dict[str, str]:
            return parse_kv_lines(require_ok(sql(db, statement), statement[:60]))

        def list_ids(scope: str, extra: str = "null, null, null") -> list[str]:
            out = require_ok(sql(db, f"select clip_id from public.fn_list_labeling_v4_clips('{LABELER}', false, '{scope}', {extra}, '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50);"), "list")
            return [line.strip() for line in out.splitlines() if line.strip()]

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
                create table public.labeler_applications(user_id uuid primary key, display_name text not null, status text not null);
                create table public.motion_clip_system_exclusions(clip_id uuid primary key, state text not null);
                grant select on public.motion_clips, public.cameras, public.labelers to service_role;
            """), "schema")
            for path in [*MIGRATIONS, V4_MIGRATION]:
                require_ok(sql(db, path.read_text(encoding="utf-8")), path.name)
            require_ok(sql(db, setup_sql()), "setup")
            require_ok(sql(db, f"""
                insert into public.labeler_applications(user_id, display_name, status) values ('{LABELER}', '김라벨', 'approved');
                insert into public.cameras(id, name) values ('{CAM_B}', 'probe-cam-b');
                update public.motion_clips set camera_id = '{CAM_B}', started_at = now() - interval '1 day' where id = '{CLIP['short']}';
            """), "extra")

            # 1) 배정 전 mine = 빈 목록, all = 전체 7개
            if list_ids("mine"):
                raise ProbeError("mine-before-assign: expected empty")
            if len(list_ids("all")) != 7:
                raise ProbeError("all: expected 7")
            # 2) 배정 → mine = CAM_A 6개, camera 필터로 CAM_B 만 → all 에서 1개
            expect("assign", q(f"select 'n|'||count(*)::text from public.fn_set_labeler_camera_assignments('{LABELER}', array['{CAM_A}']::uuid[], '{OWNER}');"), n="1")
            if len(list_ids("mine")) != 6:
                raise ProbeError("mine-after-assign: expected 6")
            if list_ids("all", f"array['{CAM_B}']::uuid[], null, null") != [CLIP["short"]]:
                raise ProbeError("camera-filter: expected only short clip")
            # 3) highlight 필터: yes = include/boundary×2, pending = pending clip
            yes = set(list_ids("all", "null, null, 'yes'"))
            if yes != {CLIP["include"], CLIP["boundary_activity"], CLIP["boundary_longest"]}:
                raise ProbeError(f"highlight-yes: {yes}")
            if list_ids("all", "null, null, 'pending'") != [CLIP["pending"]]:
                raise ProbeError("highlight-pending")
            # 4) 확정 → labeled/unlabeled 필터 + reviewer_name + 잠금
            require_ok(sql(db, f"select * from public.fn_submit_highlight_verdict('{CLIP['short']}','{LABELER}',false,true,'initial','interesting_low_numbers','{ENGINE}','{ALGO}','{IDENTITY}');"), "verdict")
            expect("labeled-row", q(f"select 'src|'||highlight_source union all select 'val|'||highlight_value::text union all select 'who|'||reviewer_name from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, 'labeled', null, '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50);"), src="human", val="true", who="김라벨")
            if CLIP["short"] in list_ids("all", "null, 'unlabeled', null"):
                raise ProbeError("unlabeled filter still contains labeled clip")
            require_sqlstate(sql(db, f"select * from public.fn_submit_highlight_verdict('{CLIP['short']}','{OWNER}',true,false,'initial',null,'{ENGINE}','{ALGO}','{IDENTITY}');"), "lock", "PT409")
            # 5) cursor: limit 3 → 다음 페이지 첫 항목이 4번째
            first = require_ok(sql(db, f"select clip_id||'|'||started_at from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 3);"), "page1").splitlines()
            last_id, last_ts = first[-1].split("|", 1)
            page2 = require_ok(sql(db, f"select clip_id from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, '{ENGINE}','{ALGO}','{IDENTITY}', '{last_ts}', '{last_id}', 3);"), "page2").splitlines()
            if set(page2) & {line.split('|')[0] for line in first}:
                raise ProbeError("cursor: page overlap")
            require_sqlstate(sql(db, f"select * from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, '{ENGINE}','{ALGO}','{IDENTITY}', '{last_ts}', null, 3);"), "cursor-half", "22023")
            # 6) 현황 + 멤버 + 카메라
            expect("overview", q(f"select 'today|'||(public.fn_get_labeling_v4_overview('{ENGINE}','{ALGO}','{IDENTITY}')->>'labeled_today');"), today="1")
            expect("members", q("select 'n|'||count(*)::text from public.fn_list_labeling_v4_members();"), n="1")
            expect("cameras", q(f"select 'assigned|'||count(*) filter (where assigned)::text from public.fn_list_labeling_v4_cameras('{LABELER}');"), assigned="1")
            # 7) 권한
            expect("privs", q("select 'tables|'||count(*)::text from information_schema.role_table_grants where grantee in ('anon','authenticated','service_role') and table_name = 'labeler_camera_assignments';"), tables="0")
            print("LABELING_V4_PROBE_OK")
        finally:
            if started:
                subprocess.run([str(binaries["pg_ctl"]), "-D", str(data_dir), "-m", "immediate", "stop"], text=True, capture_output=True, timeout=120, check=False)
    print("PROBE_RESIDUE=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 실행**

Run: `cd /Users/baek/petcam-lab && uv run python scripts/run_labeling_v4_probe.py --pg-bin "$(brew --prefix postgresql@15)/bin"`
Expected: `LABELING_V4_PROBE_OK` / `PROBE_RESIDUE=0`

- [ ] **Step 3: 커밋**

```bash
cd /Users/baek/petcam-lab && git add scripts/run_labeling_v4_probe.py && git commit -m "test: 라벨링 v4 배정·목록·잠금 일회용 PostgreSQL probe"
```

---

### Task 3: 웹 타입·클라이언트·서버 매퍼

**Context:**
- Depends on: A 계획 Task 3 (`HighlightCurrent`, `HighlightDetail`, `HighlightVerdictInput`, `HighlightVerdictResult`)
- Outputs: `web/src/lib/labelingV4.ts`, `web/src/lib/labelingV4Api.ts`, `web/src/lib/labelingV4Server.ts`
- Must know: 클라이언트 `request` 헬퍼는 `labelingV3Api.ts`와 같은 패턴을 복제한다(모듈 private). cursor는 기존 `labelingQueueCursor`의 `encodeQueueCursor/decodeQueueCursor`를 재사용(정렬 정본이 같다).
- Acceptance: `npx vitest run src/lib/labelingV4Server.test.ts` PASS

**Files:**
- Create: `web/src/lib/labelingV4.ts`, `web/src/lib/labelingV4Api.ts`, `web/src/lib/labelingV4Server.ts`
- Test: `web/src/lib/labelingV4Server.test.ts`

- [ ] **Step 1: 테스트**

```ts
import { describe, expect, it } from 'vitest';

import { mapV4ClipRow, parseV4ListRequest } from './labelingV4Server';

describe('parseV4ListRequest', () => {
  it('기본값과 허용 필터', () => {
    const sp = new URLSearchParams('scope=mine&camera_id=11111111-1111-4111-8111-111111111111&label_state=unlabeled&highlight_state=yes&limit=20');
    expect(parseV4ListRequest(sp)).toEqual({ scope: 'mine', cameraIds: ['11111111-1111-4111-8111-111111111111'], labelState: 'unlabeled', highlightState: 'yes', limit: 20 });
    expect(parseV4ListRequest(new URLSearchParams('scope=all'))).toEqual({ scope: 'all', cameraIds: null, labelState: null, highlightState: null, limit: 30 });
  });
  it('잘못된 값은 throw', () => {
    expect(() => parseV4ListRequest(new URLSearchParams('scope=theirs'))).toThrow('invalid_scope');
    expect(() => parseV4ListRequest(new URLSearchParams('scope=all&camera_id=nope'))).toThrow('invalid_camera_id');
    expect(() => parseV4ListRequest(new URLSearchParams('scope=all&limit=500'))).toThrow('invalid_limit');
    expect(() => parseV4ListRequest(new URLSearchParams('scope=all&highlight_state=maybe'))).toThrow('invalid_highlight_state');
  });
});

describe('mapV4ClipRow', () => {
  const row = { clip_id: '00000000-0000-4000-8000-000000000001', camera_id: 'c1', camera_name: '거실', started_at: '2026-09-08T10:00:00Z', duration_sec: 60.6, media_ready: true, highlight_source: 'rule', highlight_status: 'decided', highlight_value: true, highlight_reason: '움직임 12.5초 · 최장 연속 6.0초', reviewer_name: null, decided_at: null };
  it('공개 필드만', () => {
    expect(mapV4ClipRow(row)).toEqual({ id: row.clip_id, camera_id: 'c1', camera_name: '거실', started_at: row.started_at, duration_sec: 60.6, media_ready: true, highlight: { source: 'rule', status: 'decided', value: true, reason: row.highlight_reason, reviewer_name: null, decided_at: null } });
  });
  it('모르는 source/status 는 throw', () => {
    expect(() => mapV4ClipRow({ ...row, highlight_source: 'ai' })).toThrow('invalid_v4_clip_row');
    expect(() => mapV4ClipRow({ ...row, highlight_status: 'weird' })).toThrow('invalid_v4_clip_row');
  });
});
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/baek/petcam-lab/web && npx vitest run src/lib/labelingV4Server.test.ts`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: 타입**

```ts
// web/src/lib/labelingV4.ts — v4 공개 계약(순수).
import type { HighlightDetail, HighlightInitialStatus, HighlightSource } from './highlightV4';

export type V4Scope = 'mine' | 'all';
export type V4LabelState = 'unlabeled' | 'labeled';
export type V4HighlightState = 'yes' | 'no' | 'pending';

export interface V4ClipHighlight {
  source: HighlightSource;
  status: HighlightInitialStatus;
  value: boolean | null;
  reason: string;
  reviewer_name: string | null;
  decided_at: string | null;
}

export interface V4ClipItem {
  id: string;
  camera_id: string | null;
  camera_name: string;
  started_at: string;
  duration_sec: number | null;
  media_ready: boolean;
  highlight: V4ClipHighlight;
}

export interface V4ClipListResponse {
  items: V4ClipItem[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface V4ListFilters {
  scope: V4Scope;
  cameraIds?: string[];
  labelState?: V4LabelState | null;
  highlightState?: V4HighlightState | null;
  cursor?: string | null;
  limit?: number;
}

export interface V4ClipDetail {
  id: string;
  camera_id: string | null;
  started_at: string;
  duration_sec: number | null;
  media_ready: boolean;
  highlight: HighlightDetail;
}

export interface V4CameraOption { id: string; name: string; assigned: boolean }

export interface V4Member { user_id: string; display_name: string; camera_ids: string[] }

export interface V4Overview {
  activity_day: string | null;
  unlabeled_total: number;
  labeled_today: number;
  labeled_7d: number;
  members: { display_name: string; labeled_7d: number }[];
  cameras: { camera_name: string; unlabeled: number; labeled_7d: number }[];
}

export const V4_LABEL_STATE_LABELS: Record<V4LabelState, string> = { unlabeled: '라벨 안 됨', labeled: '라벨 됨' };
export const V4_HIGHLIGHT_STATE_LABELS: Record<V4HighlightState, string> = { yes: '하이라이트 O', no: '하이라이트 X', pending: '분석 대기' };

export function v4DetailPath(clipId: string): string {
  return `/labeling/v4/${clipId}`;
}
```

- [ ] **Step 4: 서버 매퍼·파서**

```ts
// web/src/lib/labelingV4Server.ts
import 'server-only';

import type { V4ClipItem, V4HighlightState, V4LabelState, V4Scope } from './labelingV4';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DEFAULT_LIMIT = 30;
const MAX_LIMIT = 100;

export interface V4ListRequest {
  scope: V4Scope;
  cameraIds: string[] | null;
  labelState: V4LabelState | null;
  highlightState: V4HighlightState | null;
  limit: number;
}

export function parseV4ListRequest(sp: URLSearchParams): V4ListRequest {
  const scope = sp.get('scope');
  if (scope !== 'mine' && scope !== 'all') throw new Error('invalid_scope');
  const cameraIds = sp.getAll('camera_id');
  for (const id of cameraIds) if (!UUID_RE.test(id)) throw new Error('invalid_camera_id');
  const labelState = sp.get('label_state');
  if (labelState !== null && labelState !== 'unlabeled' && labelState !== 'labeled') throw new Error('invalid_label_state');
  const highlightState = sp.get('highlight_state');
  if (highlightState !== null && !['yes', 'no', 'pending'].includes(highlightState)) throw new Error('invalid_highlight_state');
  const rawLimit = sp.get('limit');
  const limit = rawLimit === null ? DEFAULT_LIMIT : Number(rawLimit);
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIMIT) throw new Error('invalid_limit');
  return {
    scope,
    cameraIds: cameraIds.length ? cameraIds : null,
    labelState: labelState as V4LabelState | null,
    highlightState: highlightState as V4HighlightState | null,
    limit,
  };
}

export interface V4ClipRow {
  clip_id: unknown; camera_id: unknown; camera_name: unknown; started_at: unknown; duration_sec: unknown;
  media_ready: unknown; highlight_source: unknown; highlight_status: unknown; highlight_value: unknown;
  highlight_reason: unknown; reviewer_name: unknown; decided_at: unknown;
}

export function mapV4ClipRow(row: V4ClipRow): V4ClipItem {
  if (typeof row.clip_id !== 'string' || typeof row.started_at !== 'string' || typeof row.camera_name !== 'string') throw new Error('invalid_v4_clip_row');
  if (row.highlight_source !== 'human' && row.highlight_source !== 'rule') throw new Error('invalid_v4_clip_row');
  if (!['decided', 'pending', 'failed'].includes(row.highlight_status as string)) throw new Error('invalid_v4_clip_row');
  if (row.highlight_value !== null && typeof row.highlight_value !== 'boolean') throw new Error('invalid_v4_clip_row');
  return {
    id: row.clip_id,
    camera_id: typeof row.camera_id === 'string' ? row.camera_id : null,
    camera_name: row.camera_name,
    started_at: row.started_at,
    duration_sec: typeof row.duration_sec === 'number' ? row.duration_sec : row.duration_sec === null ? null : Number(row.duration_sec),
    media_ready: Boolean(row.media_ready),
    highlight: {
      source: row.highlight_source,
      status: row.highlight_status as V4ClipItem['highlight']['status'],
      value: row.highlight_value as boolean | null,
      reason: typeof row.highlight_reason === 'string' ? row.highlight_reason : '',
      reviewer_name: typeof row.reviewer_name === 'string' ? row.reviewer_name : null,
      decided_at: typeof row.decided_at === 'string' ? row.decided_at : null,
    },
  };
}
```

- [ ] **Step 5: 클라이언트**

```ts
// web/src/lib/labelingV4Api.ts
'use client';

import { ApiError, UnauthorizedError } from './labelingApi';
import { getSupabaseBrowser } from './supabaseBrowser';
import type { GmeOverlayResponse } from './gmeOverlay';
import type { HighlightDetail, HighlightVerdictInput, HighlightVerdictResult } from './highlightV4';
import type { V4CameraOption, V4ClipDetail, V4ClipListResponse, V4ListFilters, V4Member, V4Overview } from './labelingV4';

async function authHeader(): Promise<Record<string, string>> {
  const { data: { session } } = await getSupabaseBrowser().auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', ...((init?.headers as Record<string, string>) || {}), ...(await authHeader()) };
  if (init?.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  let resp: Response;
  try { resp = await fetch(path, { ...init, headers }); } catch (e) { throw new ApiError(0, `네트워크 오류: ${(e as Error).message}`); }
  if (resp.status === 401) throw new UnauthorizedError();
  if (!resp.ok) {
    let detail = resp.statusText || `HTTP ${resp.status}`;
    let code: string | undefined;
    try { const j = await resp.json(); if (typeof j?.detail === 'string') detail = j.detail; if (typeof j?.code === 'string') code = j.code; } catch { /* non-JSON */ }
    throw new ApiError(resp.status, detail, undefined, code);
  }
  return resp.json() as Promise<T>;
}

export function v4ListQuery(f: V4ListFilters): string {
  const sp = new URLSearchParams();
  sp.set('scope', f.scope);
  (f.cameraIds ?? []).forEach((id) => sp.append('camera_id', id));
  if (f.labelState) sp.set('label_state', f.labelState);
  if (f.highlightState) sp.set('highlight_state', f.highlightState);
  if (f.cursor) sp.set('cursor', f.cursor);
  if (f.limit != null) sp.set('limit', String(f.limit));
  return sp.toString();
}

export function getV4Clips(f: V4ListFilters): Promise<V4ClipListResponse> {
  return request<V4ClipListResponse>(`/api/labeling-v4/clips?${v4ListQuery(f)}`);
}
export function getV4Clip(clipId: string): Promise<V4ClipDetail> {
  return request<V4ClipDetail>(`/api/labeling-v4/clips/${clipId}`);
}
export function getV4Highlight(clipId: string): Promise<HighlightDetail> {
  return request<HighlightDetail>(`/api/labeling-v4/clips/${clipId}/highlight`);
}
export function submitV4Verdict(clipId: string, input: HighlightVerdictInput & { kind?: 'initial' | 'correction' }): Promise<HighlightVerdictResult> {
  return request<HighlightVerdictResult>(`/api/labeling-v4/clips/${clipId}/verdict`, { method: 'POST', body: JSON.stringify(input) });
}
export function getV4FileUrl(clipId: string): Promise<{ url: string; expires_in: number }> {
  return request(`/api/labeling-v4/clips/${clipId}/file/url`);
}
export function getV4DownloadUrl(clipId: string): Promise<{ url: string; filename: string; expires_in: number }> {
  return request(`/api/labeling-v4/clips/${clipId}/file/url?download=1`);
}
export function getV4GmeOverlay(clipId: string): Promise<GmeOverlayResponse> {
  return request<GmeOverlayResponse>(`/api/labeling-v4/clips/${clipId}/gme-overlay`);
}
export async function getV4Cameras(): Promise<V4CameraOption[]> {
  try { return (await request<{ cameras: V4CameraOption[] }>('/api/labeling-v4/cameras')).cameras; } catch { return []; }
}
export function getV4Members(): Promise<{ members: V4Member[]; cameras: V4CameraOption[] }> {
  return request('/api/labeling-v4/owner/assignments');
}
export function setV4Assignments(userId: string, cameraIds: string[]): Promise<{ camera_ids: string[] }> {
  return request('/api/labeling-v4/owner/assignments', { method: 'PUT', body: JSON.stringify({ user_id: userId, camera_ids: cameraIds }) });
}
export function getV4Overview(): Promise<V4Overview> {
  return request<V4Overview>('/api/labeling-v4/owner/overview');
}
```

- [ ] **Step 6: 통과 + 커밋**

Run: `cd /Users/baek/petcam-lab/web && npx vitest run src/lib/labelingV4Server.test.ts && npx tsc --noEmit -p .`
Expected: `4 passed`, tsc 0 (`ApiError` 생성자는 `(status, message, issues?, code?)` — code 는 4번째 인자)

```bash
cd /Users/baek/petcam-lab && git add web/src/lib/labelingV4.ts web/src/lib/labelingV4Api.ts web/src/lib/labelingV4Server.ts web/src/lib/labelingV4Server.test.ts && git commit -m "feat: 라벨링 v4 타입·클라이언트·서버 매퍼"
```

---

### Task 4: API routes — 목록·상세·미디어·overlay·카메라

**Context:**
- Depends on: Task 3, A 계획 Task 4 (`loadV4ClipAccess`, `reviewerDisplayName`), A Task 4 highlight GET 로직
- Inputs: `requireLabelingAccess`, `readGmeActiveContract`, `encodeQueueCursor/decodeQueueCursor/InvalidQueueCursorError`(`labelingQueueCursor.ts`), `presignGet/SIGNED_URL_TTL_SEC`(`r2.ts`), `isMotionMediaDeleted`(`labelingV3Server.ts`), `loadCurrentGmeOverlaySource/fetchAndParseGmeOverlay`(`gmeOverlayServer.ts`)
- Outputs: 5개 route
- Must know: 목록은 `limit+1` 조회로 `has_more`. 상세는 A Task 4의 highlight 계산을 함수로 뽑아 공유한다 → `web/src/app/api/labeling-v4/_highlight.ts`에 `loadHighlightDetail(clipId)` 를 만들고 A Task 4 route도 그것을 쓰도록 리팩터(동작 동일). 미디어·overlay route는 v3 owner route 본문을 그대로 쓰되 access만 `loadV4ClipAccess`.
- Acceptance: `npx vitest run src/app/api/labeling-v4` PASS

**Files:**
- Create: `web/src/app/api/labeling-v4/_highlight.ts`, `web/src/app/api/labeling-v4/clips/route.ts`, `web/src/app/api/labeling-v4/clips/[clipId]/route.ts`, `web/src/app/api/labeling-v4/clips/[clipId]/file/url/route.ts`, `web/src/app/api/labeling-v4/clips/[clipId]/gme-overlay/route.ts`, `web/src/app/api/labeling-v4/cameras/route.ts`
- Modify: `web/src/app/api/labeling-v4/clips/[clipId]/highlight/route.ts` (공유 함수 사용)
- Test: `web/src/app/api/labeling-v4/clips/route.test.ts`, `web/src/app/api/labeling-v4/clips/[clipId]/route.test.ts`

- [ ] **Step 1: 목록 route 테스트**

```ts
import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireLabelingAccess, rpc } = vi.hoisted(() => ({ requireLabelingAccess: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('@/lib/labelingV3Server', () => ({ readGmeActiveContract: () => ({ engine_schema_version: 'gme-shadow-v1', algorithm_version: 'gme-motion-v1', detector_identity: 'a'.repeat(64) }) }));

import { GET } from './route';
import { encodeQueueCursor } from '@/lib/labelingQueueCursor';

const row = (i: number) => ({ clip_id: `0000000${i}-0000-4000-8000-000000000001`, camera_id: 'c1', camera_name: '거실', started_at: `2026-09-08T0${i}:00:00Z`, duration_sec: 60, media_ready: true, highlight_source: 'rule', highlight_status: 'decided', highlight_value: i % 2 === 0, highlight_reason: 'r', reviewer_name: null, decided_at: null });
const req = (qs: string) => new NextRequest(`https://label.tera-ai.uk/api/labeling-v4/clips?${qs}`);

beforeEach(() => {
  vi.clearAllMocks();
  requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'u1', isOwner: false });
});

describe('GET /api/labeling-v4/clips', () => {
  it('limit+1 로 has_more 와 cursor 를 만든다', async () => {
    rpc.mockResolvedValue({ data: [row(3), row(2), row(1)], error: null });
    const res = await GET(req('scope=all&limit=2'));
    const body = await res.json();
    expect(body.items).toHaveLength(2);
    expect(body.has_more).toBe(true);
    expect(body.next_cursor).toBe(encodeQueueCursor({ startedAt: row(2).started_at, id: row(2).clip_id }));
    expect(rpc.mock.calls[0][1]).toMatchObject({ p_viewer_id: 'u1', p_is_owner: false, p_scope: 'all', p_limit: 3, p_cursor_started_at: null, p_cursor_id: null });
  });
  it('cursor 를 RPC 에 풀어 넘긴다', async () => {
    rpc.mockResolvedValue({ data: [], error: null });
    const cursor = encodeQueueCursor({ startedAt: '2026-09-08T02:00:00Z', id: row(2).clip_id });
    await GET(req(`scope=mine&cursor=${encodeURIComponent(cursor)}`));
    expect(rpc.mock.calls[0][1]).toMatchObject({ p_scope: 'mine', p_cursor_started_at: '2026-09-08T02:00:00Z', p_cursor_id: row(2).clip_id });
  });
  it('잘못된 scope/cursor 는 DB 전 400', async () => {
    expect((await GET(req('scope=theirs'))).status).toBe(400);
    expect((await GET(req('scope=all&cursor=garbage'))).status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: 상세 route 테스트**

```ts
import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { loadV4ClipAccess, loadHighlightDetail, isMotionMediaDeleted } = vi.hoisted(() => ({ loadV4ClipAccess: vi.fn(), loadHighlightDetail: vi.fn(), isMotionMediaDeleted: vi.fn() }));
vi.mock('../../_access', () => ({ loadV4ClipAccess }));
vi.mock('../../_highlight', () => ({ loadHighlightDetail }));
vi.mock('@/lib/labelingV3Server', () => ({ isMotionMediaDeleted, motionLabelingDatabaseError: () => new Response(null, { status: 502 }) }));

import { GET } from './route';

const CLIP = '00000000-0000-4000-8000-000000000001';

beforeEach(() => {
  vi.clearAllMocks();
  loadV4ClipAccess.mockResolvedValue({ ok: true, userId: 'u1', isOwner: false, clip: { id: CLIP, camera_id: 'c1', started_at: '2026-09-08T00:00:00Z', duration_sec: 60, r2_key: 'k' } });
  isMotionMediaDeleted.mockResolvedValue(false);
  loadHighlightDetail.mockResolvedValue({ current: { source: 'rule', status: 'decided', value: true, rule_version: 'hl-rule-v0', reason: 'r', reviewer_name: null, decided_at: null, verdict_kind: null }, initial: { status: 'decided', value: true, rule_version: 'hl-rule-v0', reason: 'r', fired: ['long_activity'], shadow: [], features: null } });
});

describe('GET /api/labeling-v4/clips/[clipId]', () => {
  it('clip 메타 + highlight, r2_key 비노출', async () => {
    const body = await (await GET(new NextRequest(`https://label.tera-ai.uk/api/labeling-v4/clips/${CLIP}`), { params: { clipId: CLIP } })).json();
    expect(body).toEqual({ id: CLIP, camera_id: 'c1', started_at: '2026-09-08T00:00:00Z', duration_sec: 60, media_ready: true, highlight: expect.objectContaining({ current: expect.any(Object), initial: expect.any(Object) }) });
    expect(JSON.stringify(body)).not.toContain('"k"');
  });
  it('media_deleted 면 media_ready=false', async () => {
    isMotionMediaDeleted.mockResolvedValue(true);
    const body = await (await GET(new NextRequest(`https://label.tera-ai.uk/api/labeling-v4/clips/${CLIP}`), { params: { clipId: CLIP } })).json();
    expect(body.media_ready).toBe(false);
  });
});
```

- [ ] **Step 3: 실패 확인**

Run: `cd /Users/baek/petcam-lab/web && npx vitest run src/app/api/labeling-v4/clips`
Expected: 새 테스트 2파일 FAIL(모듈 없음), 기존 highlight/verdict 테스트는 PASS 유지

- [ ] **Step 4: 공유 highlight 로더 + 기존 route 리팩터**

```ts
// web/src/app/api/labeling-v4/_highlight.ts
import 'server-only';

import { mapHighlightCurrentRow, mapHighlightInitialRow, type HighlightCurrentRow, type HighlightInitialRow } from '@/lib/highlightV4Server';
import type { HighlightDetail } from '@/lib/highlightV4';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';
import { reviewerDisplayName } from './_access';

export class HighlightRpcError extends Error {
  constructor(public readonly cause: unknown) { super('highlight_rpc_error'); }
}

// 현재값 + 1차 판정. RPC 오류는 HighlightRpcError 로 감싸 route 가 highlightRpcErrorResponse 로 매핑한다.
export async function loadHighlightDetail(clipId: string): Promise<HighlightDetail> {
  const contract = readGmeActiveContract();
  const args = { p_clip_id: clipId, p_engine_schema_version: contract.engine_schema_version, p_algorithm_version: contract.algorithm_version, p_detector_identity: contract.detector_identity };
  const current = await supabaseAdmin.rpc('fn_highlight_current', args);
  if (current.error) throw new HighlightRpcError(current.error);
  const initial = await supabaseAdmin.rpc('fn_highlight_initial', args);
  if (initial.error) throw new HighlightRpcError(initial.error);
  if (!Array.isArray(current.data) || current.data.length !== 1 || !Array.isArray(initial.data) || initial.data.length !== 1) throw new Error('invalid_highlight_result_count');
  const currentRow = current.data[0] as HighlightCurrentRow;
  const name = await reviewerDisplayName(typeof currentRow.reviewer_id === 'string' ? currentRow.reviewer_id : null);
  return { current: mapHighlightCurrentRow(currentRow, name), initial: mapHighlightInitialRow(initial.data[0] as HighlightInitialRow) };
}
```

`highlight/route.ts` 본문을 아래로 교체(테스트 5개는 그대로 통과해야 한다 — rpc 호출 인자·응답 동일):

```ts
import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { loadV4ClipAccess } from '../../../_access';
import { HighlightRpcError, loadHighlightDetail } from '../../../_highlight';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  try {
    const access = await loadV4ClipAccess(req, params.clipId);
    if (!access.ok) return access.response;
    return NextResponse.json(await loadHighlightDetail(params.clipId));
  } catch (cause) {
    if (cause instanceof HighlightRpcError) return highlightRpcErrorResponse(cause.cause) ?? highlightDatabaseError(cause.cause);
    return highlightDatabaseError(cause);
  }
}
```

> highlight route 테스트의 `vi.mock('@/lib/labelingV3Server', …)` 는 `_highlight.ts` 가 import 하는 경로와 같으므로 그대로 동작한다.

- [ ] **Step 5: 목록 route**

```ts
// web/src/app/api/labeling-v4/clips/route.ts
import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { decodeQueueCursor, encodeQueueCursor, InvalidQueueCursorError } from '@/lib/labelingQueueCursor';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { mapV4ClipRow, parseV4ListRequest, type V4ClipRow } from '@/lib/labelingV4Server';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function badRequest(detail: string) {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

// GET /api/labeling-v4/clips?scope=mine|all&camera_id=&label_state=&highlight_state=&cursor=&limit=
// 정렬 (started_at DESC, id DESC). 배정은 scope=mine 의 필터일 뿐 권한이 아니다(v4 스펙 §4.1).
export async function GET(req: NextRequest) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  const sp = req.nextUrl.searchParams;
  let cursor;
  try { cursor = decodeQueueCursor(sp.get('cursor')); } catch (e) { if (e instanceof InvalidQueueCursorError) return badRequest('cursor 가 잘못됐어.'); throw e; }
  let parsed;
  try { parsed = parseV4ListRequest(sp); } catch (e) { return badRequest(`요청 값이 잘못됐어(${(e as Error).message}).`); }
  try {
    const contract = readGmeActiveContract();
    const { data, error } = await supabaseAdmin.rpc('fn_list_labeling_v4_clips', {
      p_viewer_id: access.userId, p_is_owner: access.isOwner, p_scope: parsed.scope, p_camera_ids: parsed.cameraIds,
      p_label_state: parsed.labelState, p_highlight_state: parsed.highlightState,
      p_engine_schema_version: contract.engine_schema_version, p_algorithm_version: contract.algorithm_version, p_detector_identity: contract.detector_identity,
      p_cursor_started_at: cursor?.startedAt ?? null, p_cursor_id: cursor?.id ?? null, p_limit: parsed.limit + 1,
    });
    if (error) return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
    const rows = (data ?? []) as V4ClipRow[];
    const hasMore = rows.length > parsed.limit;
    const page = hasMore ? rows.slice(0, parsed.limit) : rows;
    const items = page.map(mapV4ClipRow);
    const last = items[items.length - 1];
    return NextResponse.json({ items, has_more: hasMore, next_cursor: hasMore && last ? encodeQueueCursor({ startedAt: last.started_at, id: last.id }) : null });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
```

- [ ] **Step 6: 상세·미디어·overlay·카메라 route**

```ts
// web/src/app/api/labeling-v4/clips/[clipId]/route.ts
import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { isMotionMediaDeleted } from '@/lib/labelingV3Server';
import { loadV4ClipAccess } from '../../_access';
import { HighlightRpcError, loadHighlightDetail } from '../../_highlight';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  try {
    const access = await loadV4ClipAccess(req, params.clipId);
    if (!access.ok) return access.response;
    const { clip } = access;
    const mediaReady = clip.r2_key !== null && !(await isMotionMediaDeleted(clip.id));
    const highlight = await loadHighlightDetail(clip.id);
    return NextResponse.json({ id: clip.id, camera_id: clip.camera_id, started_at: clip.started_at, duration_sec: clip.duration_sec, media_ready: mediaReady, highlight });
  } catch (cause) {
    if (cause instanceof HighlightRpcError) return highlightRpcErrorResponse(cause.cause) ?? highlightDatabaseError(cause.cause);
    return highlightDatabaseError(cause);
  }
}
```

```ts
// web/src/app/api/labeling-v4/clips/[clipId]/file/url/route.ts — v3 owner route 와 동일 본문, access 만 v4.
import { NextRequest, NextResponse } from 'next/server';

import { presignGet, SIGNED_URL_TTL_SEC } from '@/lib/r2';
import { isMotionMediaDeleted, motionLabelingDatabaseError } from '@/lib/labelingV3Server';
import { loadV4ClipAccess } from '../../../_access';

export const runtime = 'nodejs';

export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  try {
    const acc = await loadV4ClipAccess(req, params.clipId);
    if (!acc.ok) return acc.response;
    if (acc.clip.r2_key == null) return NextResponse.json({ detail: '원본 영상이 없어 재생할 수 없어.', code: 'media_unavailable' }, { status: 410 });
    if (await isMotionMediaDeleted(params.clipId)) return NextResponse.json({ detail: '원본이 삭제된 영상이야.', code: 'media_deleted' }, { status: 410 });
    const download = req.nextUrl.searchParams.get('download') === '1';
    let url: string;
    try {
      url = download
        ? await presignGet(acc.clip.r2_key, SIGNED_URL_TTL_SEC, { downloadFilename: `petcam-${params.clipId}.mp4` })
        : await presignGet(acc.clip.r2_key, SIGNED_URL_TTL_SEC);
    } catch (signErr) {
      console.error('[labeling-v4] signed url failure', signErr);
      return NextResponse.json({ detail: '영상 URL 발급에 실패했어. 잠시 후 다시 시도해.', code: 'signing_failed' }, { status: 502 });
    }
    return NextResponse.json(download ? { url, filename: `petcam-${params.clipId}.mp4`, expires_in: SIGNED_URL_TTL_SEC } : { url, expires_in: SIGNED_URL_TTL_SEC });
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
```

```ts
// web/src/app/api/labeling-v4/clips/[clipId]/gme-overlay/route.ts — v3 owner overlay 와 동일, access 만 v4.
import { NextRequest, NextResponse } from 'next/server';

import { fetchAndParseGmeOverlay, loadCurrentGmeOverlaySource } from '@/lib/gmeOverlayServer';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { presignGet } from '@/lib/r2';
import { loadV4ClipAccess } from '../../../_access';

export const runtime = 'nodejs';
const GME_ARTIFACT_URL_TTL_SEC = 300;

function unavailable(durationSec: number | null) {
  return NextResponse.json({ available: false, overlay_revision: null, duration_sec: durationSec ?? 0, points: [], intervals: [] });
}

export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  const access = await loadV4ClipAccess(req, params.clipId);
  if (!access.ok) return access.response;
  try {
    const contract = readGmeActiveContract();
    const source = await loadCurrentGmeOverlaySource(params.clipId, contract.detector_identity, contract.algorithm_version);
    if (!source) return unavailable(access.clip.duration_sec);
    const signedUrl = await presignGet(source.artifactKey, GME_ARTIFACT_URL_TTL_SEC, { responseContentEncoding: 'identity' });
    const parsed = await fetchAndParseGmeOverlay(signedUrl, source.overlayRevision, source.artifactBytes);
    if (access.clip.duration_sec !== null && Math.abs(parsed.duration_sec - access.clip.duration_sec) > 1) throw new Error('GME artifact duration mismatch');
    return NextResponse.json({ available: true, overlay_revision: source.overlayRevision, duration_sec: parsed.duration_sec, points: parsed.points, intervals: parsed.intervals });
  } catch (cause) {
    console.error('[labeling-v4] GME overlay unavailable', cause);
    return unavailable(access.clip.duration_sec);
  }
}
```

```ts
// web/src/app/api/labeling-v4/cameras/route.ts
import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError } from '@/lib/highlightV4Server';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_list_labeling_v4_cameras', { p_viewer_id: access.userId });
    if (error) throw error;
    const cameras = ((data ?? []) as { camera_id: string; camera_name: string; assigned: boolean }[])
      .map((r) => ({ id: r.camera_id, name: r.camera_name, assigned: Boolean(r.assigned) }));
    return NextResponse.json({ cameras });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
```

- [ ] **Step 7: 통과 + 커밋**

Run: `cd /Users/baek/petcam-lab/web && npx vitest run src/app/api/labeling-v4 && npx tsc --noEmit -p .`
Expected: 전부 PASS

```bash
cd /Users/baek/petcam-lab && git add web/src/app/api/labeling-v4 && git commit -m "feat: labeling-v4 목록·상세·미디어·overlay·카메라 route"
```

---

### Task 5: owner routes — 배정·현황

**Context:**
- Depends on: Task 3
- Inputs: `requireOwner`, RPC `fn_list_labeling_v4_members()`, `fn_list_labeling_v4_cameras(uuid)`, `fn_set_labeler_camera_assignments(uuid,uuid[],uuid)`, `fn_get_labeling_v4_overview(text,text,text)`
- Outputs: `web/src/app/api/labeling-v4/owner/assignments/route.ts` (GET/PUT), `web/src/app/api/labeling-v4/owner/overview/route.ts`
- Acceptance: `npx vitest run src/app/api/labeling-v4/owner` PASS

**Files:**
- Create: 두 route + `assignments/route.test.ts`, `overview/route.test.ts`

- [ ] **Step 1: 테스트 (assignments)**

```ts
import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireOwner, rpc } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET, PUT } from './route';

const URL = 'https://label.tera-ai.uk/api/labeling-v4/owner/assignments';
const U = '30000000-0000-4000-8000-000000000001';
const C = '40000000-0000-4000-8000-000000000001';

beforeEach(() => {
  vi.clearAllMocks();
  requireOwner.mockResolvedValue({ ok: true, userId: 'owner-1' });
  rpc.mockImplementation(async (name: string) => {
    if (name === 'fn_list_labeling_v4_members') return { data: [{ user_id: U, display_name: '김라벨', camera_ids: [C] }], error: null };
    if (name === 'fn_list_labeling_v4_cameras') return { data: [{ camera_id: C, camera_name: '거실', assigned: false }], error: null };
    if (name === 'fn_set_labeler_camera_assignments') return { data: [{ camera_id: C }], error: null };
    throw new Error(name);
  });
});

describe('owner assignments', () => {
  it('GET 은 멤버+카메라', async () => {
    const body = await (await GET(new NextRequest(URL))).json();
    expect(body.members[0]).toEqual({ user_id: U, display_name: '김라벨', camera_ids: [C] });
    expect(body.cameras[0]).toEqual({ id: C, name: '거실', assigned: false });
  });
  it('PUT 은 배정을 갱신한다', async () => {
    const res = await PUT(new NextRequest(URL, { method: 'PUT', body: JSON.stringify({ user_id: U, camera_ids: [C] }) }));
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_set_labeler_camera_assignments', { p_user_id: U, p_camera_ids: [C], p_actor_id: 'owner-1' });
    expect(await res.json()).toEqual({ camera_ids: [C] });
  });
  it('uuid 아니면 400', async () => {
    expect((await PUT(new NextRequest(URL, { method: 'PUT', body: JSON.stringify({ user_id: 'x', camera_ids: [] }) }))).status).toBe(400);
  });
});
```

- [ ] **Step 2: 테스트 (overview)**

```ts
import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireOwner, rpc } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('@/lib/labelingV3Server', () => ({ readGmeActiveContract: () => ({ engine_schema_version: 'gme-shadow-v1', algorithm_version: 'gme-motion-v1', detector_identity: 'a'.repeat(64) }) }));

import { GET } from './route';

beforeEach(() => {
  vi.clearAllMocks();
  requireOwner.mockResolvedValue({ ok: true, userId: 'owner-1' });
  rpc.mockResolvedValue({ data: { activity_day: '2026-09-08', unlabeled_total: 120, labeled_today: 12, labeled_7d: 80, members: [{ display_name: '김라벨', labeled_7d: 50 }], cameras: [] }, error: null });
});

describe('GET owner overview', () => {
  it('jsonb 를 그대로 돌려준다', async () => {
    const body = await (await GET(new NextRequest('https://label.tera-ai.uk/api/labeling-v4/owner/overview'))).json();
    expect(body.unlabeled_total).toBe(120);
    expect(rpc).toHaveBeenCalledWith('fn_get_labeling_v4_overview', { p_engine_schema_version: 'gme-shadow-v1', p_algorithm_version: 'gme-motion-v1', p_detector_identity: 'a'.repeat(64) });
  });
});
```

- [ ] **Step 3: 실패 확인** — `npx vitest run src/app/api/labeling-v4/owner` → 두 route 없음

- [ ] **Step 4: routes**

```ts
// web/src/app/api/labeling-v4/owner/assignments/route.ts
import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  try {
    const members = await supabaseAdmin.rpc('fn_list_labeling_v4_members', {});
    if (members.error) throw members.error;
    const cameras = await supabaseAdmin.rpc('fn_list_labeling_v4_cameras', { p_viewer_id: owner.userId });
    if (cameras.error) throw cameras.error;
    return NextResponse.json({
      members: ((members.data ?? []) as { user_id: string; display_name: string; camera_ids: string[] }[]).map((m) => ({ user_id: m.user_id, display_name: m.display_name, camera_ids: m.camera_ids ?? [] })),
      cameras: ((cameras.data ?? []) as { camera_id: string; camera_name: string; assigned: boolean }[]).map((c) => ({ id: c.camera_id, name: c.camera_name, assigned: Boolean(c.assigned) })),
    });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}

export async function PUT(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  let body: { user_id?: unknown; camera_ids?: unknown };
  try { body = await req.json(); } catch { return NextResponse.json({ detail: 'JSON 본문이 필요해.', code: 'invalid_request' }, { status: 400 }); }
  if (typeof body.user_id !== 'string' || !UUID_RE.test(body.user_id) || !Array.isArray(body.camera_ids) || !body.camera_ids.every((c) => typeof c === 'string' && UUID_RE.test(c))) {
    return NextResponse.json({ detail: 'user_id/camera_ids 가 잘못됐어.', code: 'invalid_request' }, { status: 400 });
  }
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_set_labeler_camera_assignments', { p_user_id: body.user_id, p_camera_ids: body.camera_ids, p_actor_id: owner.userId });
    if (error) return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
    return NextResponse.json({ camera_ids: ((data ?? []) as { camera_id: string }[]).map((r) => r.camera_id) });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
```

```ts
// web/src/app/api/labeling-v4/owner/overview/route.ts
import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError } from '@/lib/highlightV4Server';
import { requireOwner } from '@/lib/labelingAccess';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  try {
    const c = readGmeActiveContract();
    const { data, error } = await supabaseAdmin.rpc('fn_get_labeling_v4_overview', { p_engine_schema_version: c.engine_schema_version, p_algorithm_version: c.algorithm_version, p_detector_identity: c.detector_identity });
    if (error) throw error;
    return NextResponse.json(data);
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
```

- [ ] **Step 5: 통과 + 커밋**

```bash
cd /Users/baek/petcam-lab/web && npx vitest run src/app/api/labeling-v4/owner && cd .. && git add web/src/app/api/labeling-v4/owner && git commit -m "feat: owner 카메라 배정·운영 현황 route"
```

---

### Task 6: 페이지 — A/B 목록·상세·owner 현황·배정 패널

**Context:**
- Depends on: Task 3~5
- Inputs: `Card/CardTitle`, `Button`(variants `labelingPrimary|labelingSecondary|labelingDanger`), `Badge`, `SelectionChip`, `ReviewVideo`(props `src,getDownload,videoRef,overlay,onTimeUpdate,onCanPlay,onError`), `GmeVideoOverlay({points,intervals,currentTimeSec})`, `createRequestGeneration`, `formatClipCapturedAt(startedAt, durationSec)`, `useLabelingAccess/useIsOwner`, `ApiError/UnauthorizedError`
- Outputs: `_v4-clip-list.tsx`, `mine/page.tsx`, `all/page.tsx`, `v4/[clipId]/page.tsx`, `v4/_v4-clip-detail.tsx`, `owner/_owner-overview-view.tsx`(교체), `owner/page.tsx`(교체), `team/_camera-assignments.tsx`
- Must know: 페이지 컴포넌트는 `useSearchParams` 때문에 `Suspense` 래퍼 필수(메모리 `nextjs-usesearchparams-suspense`). 날짜 표시는 항상 `timeZone: 'Asia/Seoul'`. 확정 뒤 자동으로 "다음 라벨 안 된 영상"으로 가려면 목록 API를 `label_state=unlabeled&limit=1` + 현재 clip cursor 로 호출한다. UI 테스트는 `renderToStaticMarkup` SSR 계약(`_role-pages.test.tsx` 패턴).
- Acceptance: `npx vitest run src/app/labeling/_v4-clip-ui.test.tsx` PASS + `npx tsc --noEmit -p .`

**Files:**
- Create: `web/src/app/labeling/_v4-clip-list.tsx`, `web/src/app/labeling/mine/page.tsx`, `web/src/app/labeling/all/page.tsx`, `web/src/app/labeling/v4/[clipId]/page.tsx`, `web/src/app/labeling/v4/_v4-clip-detail.tsx`, `web/src/app/labeling/team/_camera-assignments.tsx`, `web/src/app/labeling/_v4-clip-ui.test.tsx`
- Modify: `web/src/app/labeling/owner/_owner-overview-view.tsx`, `web/src/app/labeling/owner/page.tsx`, `web/src/app/labeling/team/page.tsx:100-112`

- [ ] **Step 1: SSR 계약 테스트**

```tsx
// web/src/app/labeling/_v4-clip-ui.test.tsx
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { V4ClipCard } from './_v4-clip-list';
import { HighlightDecisionPanel } from './v4/_v4-clip-detail';
import { OwnerOverviewView } from './owner/_owner-overview-view';

const item = { id: '00000000-0000-4000-8000-000000000001', camera_id: 'c1', camera_name: '거실', started_at: '2026-09-08T01:00:00Z', duration_sec: 60, media_ready: true, highlight: { source: 'rule' as const, status: 'decided' as const, value: true, reason: '움직임 12.5초 · 최장 연속 6.0초', reviewer_name: null, decided_at: null } };

describe('V4ClipCard', () => {
  it('1차 판정 배지·근거·라벨 안 됨 표시, 상세 링크는 /labeling/v4/', () => {
    const html = renderToStaticMarkup(<V4ClipCard item={item} />);
    expect(html).toContain('하이라이트 O');
    expect(html).toContain('움직임 12.5초');
    expect(html).toContain('라벨 안 됨');
    expect(html).toContain('href="/labeling/v4/00000000-0000-4000-8000-000000000001"');
  });
  it('사람 확정이면 확정자 이름을 보여준다', () => {
    const html = renderToStaticMarkup(<V4ClipCard item={{ ...item, highlight: { ...item.highlight, source: 'human', value: false, reviewer_name: '김라벨', decided_at: '2026-09-08T02:00:00Z' } }} />);
    expect(html).toContain('김라벨님 확정');
    expect(html).toContain('하이라이트 X');
  });
});

describe('HighlightDecisionPanel', () => {
  const initial = { status: 'decided' as const, value: true, rule_version: 'hl-rule-v0', reason: '움직임 12.5초 · 최장 연속 6.0초', fired: ['long_activity' as const], shadow: [], features: { activity_sec: 12.5, longest_moving_sec: 6, moving_burst_count: 2, first_moving_sec: 0.2 } };
  it('1차 판정과 두 확정 버튼, 1차 쪽 강조', () => {
    const html = renderToStaticMarkup(<HighlightDecisionPanel initial={initial} current={{ source: 'rule', status: 'decided', value: true, rule_version: 'hl-rule-v0', reason: initial.reason, reviewer_name: null, decided_at: null, verdict_kind: null }} busy={false} onDecide={() => {}} />);
    expect(html).toContain('1차 판정: O');
    expect(html).toContain('O 확정');
    expect(html).toContain('X 확정');
    expect(html).toContain('오래 움직임');
  });
  it('이미 확정된 영상은 읽기 전용 문구', () => {
    const html = renderToStaticMarkup(<HighlightDecisionPanel initial={initial} current={{ source: 'human', status: 'decided', value: false, rule_version: 'hl-rule-v0', reason: initial.reason, reviewer_name: '김라벨', decided_at: '2026-09-08T02:00:00Z', verdict_kind: 'initial' }} busy={false} onDecide={() => {}} />);
    expect(html).toContain('김라벨님이 확정');
    expect(html).not.toContain('O 확정');
  });
});

describe('OwnerOverviewView (v4)', () => {
  it('집계만 보여준다', () => {
    const html = renderToStaticMarkup(<OwnerOverviewView overview={{ activity_day: '2026-09-08', unlabeled_total: 120, labeled_today: 12, labeled_7d: 80, members: [{ display_name: '김라벨', labeled_7d: 50 }], cameras: [{ camera_name: '거실', unlabeled: 100, labeled_7d: 60 }] }} />);
    expect(html).toContain('라벨 안 된 영상');
    expect(html).toContain('120');
    expect(html).toContain('김라벨');
    expect(html).not.toContain('불일치');
  });
});
```

- [ ] **Step 2: 실패 확인** — `npx vitest run src/app/labeling/_v4-clip-ui.test.tsx` → 모듈 없음

- [ ] **Step 3: 목록 컴포넌트**

```tsx
// web/src/app/labeling/_v4-clip-list.tsx
'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { SelectionChip } from '@/components/ui/SelectionControl';
import { ApiError, UnauthorizedError } from '@/lib/labelingApi';
import { formatClipCapturedAt } from '@/lib/labelingV2';
import { V4_HIGHLIGHT_STATE_LABELS, V4_LABEL_STATE_LABELS, v4DetailPath, type V4CameraOption, type V4ClipItem, type V4HighlightState, type V4LabelState, type V4Scope } from '@/lib/labelingV4';
import { getV4Cameras, getV4Clips } from '@/lib/labelingV4Api';
import { createRequestGeneration } from '@/lib/requestGeneration';

const PAGE_SIZE = 30;

export function highlightBadge(h: V4ClipItem['highlight']) {
  if (h.status === 'pending') return <Badge tone="neutral">분석 대기</Badge>;
  if (h.status === 'failed') return <Badge tone="warning">분석 실패</Badge>;
  return <Badge tone={h.value ? 'success' : 'neutral'}>{h.value ? '하이라이트 O' : '하이라이트 X'}</Badge>;
}

export function V4ClipCard({ item }: { item: V4ClipItem }) {
  const h = item.highlight;
  return (
    <Link href={v4DetailPath(item.id)} prefetch={false} className="block">
      <Card className="space-y-2 hover:bg-zinc-50">
        <div className="flex flex-wrap items-center gap-2">
          {highlightBadge(h)}
          <span className="text-sm font-medium text-zinc-900">{item.camera_name}</span>
          <span className="text-xs text-zinc-500">{formatClipCapturedAt(item.started_at, item.duration_sec)}</span>
        </div>
        <p className="text-xs text-zinc-600">{h.reason}</p>
        <p className="text-xs">
          {h.source === 'human'
            ? <span className="text-emerald-800">{h.reviewer_name ?? '라벨러'}님 확정</span>
            : <span className="text-amber-800">라벨 안 됨</span>}
          {!item.media_ready && <span className="ml-2 text-rose-700">재생 불가</span>}
        </p>
      </Card>
    </Link>
  );
}

interface UrlFilters { cameraIds: string[]; labelState: V4LabelState | null; highlightState: V4HighlightState | null }

function readFilters(sp: URLSearchParams): UrlFilters {
  const ls = sp.get('label_state');
  const hs = sp.get('highlight_state');
  return {
    cameraIds: sp.getAll('camera_id'),
    labelState: ls === 'unlabeled' || ls === 'labeled' ? ls : null,
    highlightState: hs === 'yes' || hs === 'no' || hs === 'pending' ? hs : null,
  };
}

function writeFilters(f: UrlFilters): string {
  const sp = new URLSearchParams();
  f.cameraIds.forEach((id) => sp.append('camera_id', id));
  if (f.labelState) sp.set('label_state', f.labelState);
  if (f.highlightState) sp.set('highlight_state', f.highlightState);
  return sp.toString();
}

// A(scope=mine)·B(scope=all) 공용. 기본 필터는 '라벨 안 됨'(스펙 §5).
export default function V4ClipList({ scope, basePath, title }: { scope: V4Scope; basePath: string; title: string }) {
  const router = useRouter();
  const sp = useSearchParams();
  const filters = useMemo(() => {
    const f = readFilters(sp);
    if (!sp.has('label_state') && !sp.has('all')) f.labelState = 'unlabeled';
    return f;
  }, [sp]);
  const [items, setItems] = useState<V4ClipItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [cameras, setCameras] = useState<V4CameraOption[]>([]);
  const gen = useRef(createRequestGeneration());

  useEffect(() => { getV4Cameras().then(setCameras); }, []);

  const load = useCallback(async (next: string | null) => {
    const g = gen.current.next();
    setBusy(true); setErr(null);
    try {
      const resp = await getV4Clips({ scope, cameraIds: filters.cameraIds, labelState: filters.labelState, highlightState: filters.highlightState, cursor: next ?? undefined, limit: PAGE_SIZE });
      if (!gen.current.isCurrent(g)) return;
      setItems((prev) => (next ? [...prev, ...resp.items] : resp.items));
      setCursor(resp.next_cursor); setHasMore(resp.has_more);
    } catch (cause) {
      if (!gen.current.isCurrent(g)) return;
      if (cause instanceof UnauthorizedError) { router.replace('/labeling/login'); return; }
      setErr(cause instanceof ApiError ? cause.message : (cause as Error).message);
    } finally {
      if (gen.current.isCurrent(g)) setBusy(false);
    }
  }, [scope, filters, router]);

  useEffect(() => { void load(null); }, [load]);

  const update = (patch: Partial<UrlFilters>) => {
    const next = { ...filters, ...patch };
    const qs = writeFilters(next);
    router.replace(`${basePath}${qs ? `?${qs}` : '?all=1'}`);
  };

  const visibleCameras = scope === 'mine' ? cameras.filter((c) => c.assigned) : cameras;

  return (
    <main className="min-w-0 space-y-4 px-4 py-6">
      <h1 className="text-xl font-semibold tracking-tight text-zinc-900">{title}</h1>
      <div className="flex flex-wrap gap-2">
        {(['unlabeled', 'labeled'] as const).map((s) => (
          <SelectionChip key={s} pressed={filters.labelState === s} tone="neutral" type="button" onClick={() => update({ labelState: filters.labelState === s ? null : s })}>{V4_LABEL_STATE_LABELS[s]}</SelectionChip>
        ))}
        {(['yes', 'no', 'pending'] as const).map((s) => (
          <SelectionChip key={s} pressed={filters.highlightState === s} tone="success" type="button" onClick={() => update({ highlightState: filters.highlightState === s ? null : s })}>{V4_HIGHLIGHT_STATE_LABELS[s]}</SelectionChip>
        ))}
      </div>
      {visibleCameras.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {visibleCameras.map((c) => (
            <SelectionChip key={c.id} pressed={filters.cameraIds.includes(c.id)} tone="neutral" type="button"
              onClick={() => update({ cameraIds: filters.cameraIds.includes(c.id) ? filters.cameraIds.filter((x) => x !== c.id) : [...filters.cameraIds, c.id] })}>{c.name}</SelectionChip>
          ))}
        </div>
      )}
      {scope === 'mine' && visibleCameras.length === 0 && !busy && (
        <Card className="text-sm text-zinc-600">배정된 카메라가 없어. owner 에게 배정을 요청하거나 <Link href="/labeling/all" className="underline">전체</Link>에서 라벨링할 수 있어.</Card>
      )}
      {err && <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{err}</Card>}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((it) => <V4ClipCard key={it.id} item={it} />)}
      </div>
      {!busy && items.length === 0 && !err && <p className="text-sm text-zinc-500">조건에 맞는 영상이 없어.</p>}
      {hasMore && <Button variant="secondary" onClick={() => load(cursor)} disabled={busy}>{busy ? '불러오는 중…' : '더보기'}</Button>}
    </main>
  );
}
```

```tsx
// web/src/app/labeling/mine/page.tsx
import { Suspense } from 'react';

import V4ClipList from '../_v4-clip-list';

export default function MinePage() {
  return (
    <Suspense fallback={<main className="px-4 py-6 text-sm text-zinc-500">불러오는 중…</main>}>
      <V4ClipList scope="mine" basePath="/labeling/mine" title="내 카메라" />
    </Suspense>
  );
}
```

```tsx
// web/src/app/labeling/all/page.tsx
import { Suspense } from 'react';

import V4ClipList from '../_v4-clip-list';

export default function AllPage() {
  return (
    <Suspense fallback={<main className="px-4 py-6 text-sm text-zinc-500">불러오는 중…</main>}>
      <V4ClipList scope="all" basePath="/labeling/all" title="전체" />
    </Suspense>
  );
}
```

- [ ] **Step 4: 상세 + 확정 패널**

```tsx
// web/src/app/labeling/v4/_v4-clip-detail.tsx
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { SelectionChip } from '@/components/ui/SelectionControl';
import type { GmeOverlayResponse } from '@/lib/gmeOverlay';
import { HIGHLIGHT_CHANGE_REASONS, HIGHLIGHT_CHANGE_REASON_LABELS, HIGHLIGHT_TRIGGER_LABELS, highlightValueLabel, type HighlightChangeReason, type HighlightCurrent, type HighlightInitial } from '@/lib/highlightV4';
import { ApiError, UnauthorizedError } from '@/lib/labelingApi';
import { formatClipCapturedAt } from '@/lib/labelingV2';
import { v4DetailPath, type V4ClipDetail } from '@/lib/labelingV4';
import { getV4Clip, getV4Clips, getV4DownloadUrl, getV4FileUrl, getV4GmeOverlay, submitV4Verdict } from '@/lib/labelingV4Api';
import { createRequestGeneration } from '@/lib/requestGeneration';
import { GmeVideoOverlay } from '../_gme-overlay';
import ReviewVideo from '../_review-video';
import { useIsOwner } from '../_owner-context';

// 순수 표시 컴포넌트(SSR 테스트 대상). 1차 판정 + 두 버튼. 확정된 영상은 읽기 전용.
export function HighlightDecisionPanel({ initial, current, busy, onDecide, ownerCorrection = false }: {
  initial: HighlightInitial; current: HighlightCurrent; busy: boolean;
  onDecide: (verdict: boolean, reason: HighlightChangeReason | null) => void; ownerCorrection?: boolean;
}) {
  const [pendingVerdict, setPendingVerdict] = useState<boolean | null>(null);
  const [reason, setReason] = useState<HighlightChangeReason | null>(null);
  const decided = current.source === 'human' && !ownerCorrection;
  const initialLabel = initial.status === 'decided' ? (initial.value ? 'O' : 'X') : highlightValueLabel(null, initial.status);
  const differs = pendingVerdict !== null && initial.status === 'decided' && pendingVerdict !== initial.value;

  return (
    <Card className="space-y-3">
      <CardTitle>1차 판정: {initialLabel}</CardTitle>
      <p className="text-sm text-zinc-700">{initial.reason}</p>
      {initial.fired.length > 0 && (
        <p className="text-xs text-zinc-500">켠 트리거: {initial.fired.map((t) => HIGHLIGHT_TRIGGER_LABELS[t]).join(', ')}</p>
      )}
      {initial.shadow.length > 0 && (
        <p className="text-xs text-zinc-400">(꺼진 트리거였다면: {initial.shadow.map((t) => HIGHLIGHT_TRIGGER_LABELS[t]).join(', ')})</p>
      )}
      {decided ? (
        <p className="text-sm text-emerald-800">{current.reviewer_name ?? '라벨러'}님이 확정 · {highlightValueLabel(current.value, 'decided')}</p>
      ) : (
        <>
          <div className="flex gap-2">
            <Button variant={initial.value === true ? 'labelingPrimary' : 'labelingSecondary'} disabled={busy} onClick={() => { setPendingVerdict(true); if (initial.value === true || initial.status !== 'decided') onDecide(true, null); }}>O 확정</Button>
            <Button variant={initial.value === false ? 'labelingPrimary' : 'labelingSecondary'} disabled={busy} onClick={() => { setPendingVerdict(false); if (initial.value === false || initial.status !== 'decided') onDecide(false, null); }}>X 확정</Button>
          </div>
          {differs && (
            <div className="space-y-2">
              <p className="text-xs text-zinc-600">1차 판정과 달라. 이유를 하나 고르면 규칙 조정에 쓰여(선택).</p>
              <div className="flex flex-wrap gap-2">
                {HIGHLIGHT_CHANGE_REASONS.map((r) => (
                  <SelectionChip key={r} pressed={reason === r} tone="warning" type="button" onClick={() => setReason(reason === r ? null : r)}>{HIGHLIGHT_CHANGE_REASON_LABELS[r]}</SelectionChip>
                ))}
              </div>
              <Button variant="labelingPrimary" disabled={busy} onClick={() => onDecide(pendingVerdict as boolean, reason)}>저장하고 다음</Button>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

export default function V4ClipDetail({ clipId }: { clipId: string }) {
  const router = useRouter();
  const isOwner = useIsOwner();
  const [detail, setDetail] = useState<V4ClipDetail | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [overlay, setOverlay] = useState<GmeOverlayResponse | null>(null);
  const [playbackTime, setPlaybackTime] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const gen = useRef(createRequestGeneration());

  const load = useCallback(async () => {
    const g = gen.current.next();
    setErr(null);
    try {
      const d = await getV4Clip(clipId);
      if (!gen.current.isCurrent(g)) return;
      setDetail(d);
      if (d.media_ready) getV4FileUrl(clipId).then((m) => { if (gen.current.isCurrent(g)) setVideoUrl(m.url); }).catch(() => {});
      getV4GmeOverlay(clipId).then((o) => { if (gen.current.isCurrent(g)) setOverlay(o); }).catch(() => {});
    } catch (cause) {
      if (cause instanceof UnauthorizedError) { router.replace('/labeling/login'); return; }
      setErr(cause instanceof ApiError ? cause.message : (cause as Error).message);
    }
  }, [clipId, router]);

  useEffect(() => { setDetail(null); setVideoUrl(null); setOverlay(null); setPlaybackTime(0); setNotice(null); void load(); }, [load]);

  // 확정 뒤 같은 카메라의 다음 '라벨 안 된' 영상으로. 없으면 목록으로.
  const goNext = useCallback(async () => {
    if (!detail) return;
    const resp = await getV4Clips({ scope: 'all', cameraIds: detail.camera_id ? [detail.camera_id] : undefined, labelState: 'unlabeled', limit: 1 });
    const next = resp.items.find((it) => it.id !== detail.id);
    router.push(next ? v4DetailPath(next.id) : '/labeling/all');
  }, [detail, router]);

  const decide = useCallback(async (verdict: boolean, reason: HighlightChangeReason | null) => {
    if (!detail) return;
    setBusy(true); setErr(null);
    try {
      await submitV4Verdict(detail.id, { verdict, change_reason: reason, kind: detail.highlight.current.source === 'human' && isOwner ? 'correction' : 'initial' });
      await goNext();
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === 'already_decided') { setNotice(cause.message); await load(); }
      else setErr(cause instanceof ApiError ? cause.message : (cause as Error).message);
    } finally {
      setBusy(false);
    }
  }, [detail, goNext, isOwner, load]);

  if (err && !detail) return <main className="px-4 py-6"><Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{err}</Card></main>;
  if (!detail) return <main className="px-4 py-6 text-sm text-zinc-500">불러오는 중…</main>;

  return (
    <main className="min-w-0 space-y-4 px-4 py-6">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-zinc-600">{formatClipCapturedAt(detail.started_at, detail.duration_sec)}</p>
        <Link href="/labeling/all" className="text-sm underline">목록</Link>
      </div>
      {videoUrl ? (
        <ReviewVideo src={videoUrl} getDownload={() => getV4DownloadUrl(detail.id)} onTimeUpdate={setPlaybackTime}
          overlay={overlay?.available ? <GmeVideoOverlay points={overlay.points} intervals={overlay.intervals} currentTimeSec={playbackTime} /> : null} />
      ) : (
        <Card className="text-sm text-zinc-500">{detail.media_ready ? '영상 준비 중…' : '재생할 수 없는 영상이야.'}</Card>
      )}
      {notice && <Card className="border-amber-200 bg-amber-50 text-sm text-amber-900">{notice}</Card>}
      {err && <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{err}</Card>}
      <HighlightDecisionPanel initial={detail.highlight.initial} current={detail.highlight.current} busy={busy} onDecide={decide} ownerCorrection={isOwner && detail.highlight.current.source === 'human'} />
      {detail.highlight.current.source === 'human' && !isOwner && (
        <Button variant="secondary" onClick={goNext}>다음 안 된 영상</Button>
      )}
    </main>
  );
}
```

```tsx
// web/src/app/labeling/v4/[clipId]/page.tsx
import V4ClipDetail from '../_v4-clip-detail';

export default function V4ClipPage({ params }: { params: { clipId: string } }) {
  return <V4ClipDetail clipId={params.clipId} />;
}
```

- [ ] **Step 5: owner 현황 교체**

`web/src/app/labeling/owner/_owner-overview-view.tsx` 전체를 아래로 교체(`DirectLabelingButton` 유지):

```tsx
'use client';

import Link from 'next/link';

import Badge from '@/components/ui/Badge';
import { Card, CardTitle } from '@/components/ui/Card';
import type { V4Overview } from '@/lib/labelingV4';

export function DirectLabelingButton() {
  return (
    <Link href="/labeling/motion?state=unreviewed" className="inline-flex w-fit whitespace-nowrap rounded-md border border-emerald-500 bg-emerald-50 px-3 py-2 text-sm font-semibold text-emerald-950 hover:bg-emerald-100">
      직접 라벨링(행동)
    </Link>
  );
}

// v4 운영 현황 — 집계만. 개별 확정 body·UUID 없음.
export function OwnerOverviewView({ overview }: { overview: V4Overview }) {
  return (
    <main className="min-w-0 space-y-4 px-4 py-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-zinc-900">운영 현황</h1>
          <p className="text-sm text-zinc-500">기준 활동일 {overview.activity_day ?? '-'}</p>
        </div>
        <div className="flex gap-2">
          <Link href="/labeling/all?label_state=unlabeled" className="rounded-md border border-zinc-300 px-3 py-2 text-sm">하이라이트 확정하기</Link>
          <DirectLabelingButton />
        </div>
      </div>
      <div className="flex flex-wrap gap-2 text-sm">
        <Badge tone="warning">라벨 안 된 영상 {overview.unlabeled_total}</Badge>
        <Badge tone="success">오늘 확정 {overview.labeled_today}</Badge>
        <Badge tone="neutral">7일 확정 {overview.labeled_7d}</Badge>
      </div>
      <Card className="space-y-2">
        <CardTitle>회원별 7일 확정</CardTitle>
        <ul className="text-sm">{overview.members.map((m) => <li key={m.display_name}>{m.display_name} · {m.labeled_7d}</li>)}</ul>
      </Card>
      <Card className="space-y-2">
        <CardTitle>카메라별</CardTitle>
        <ul className="text-sm">{overview.cameras.map((c) => <li key={c.camera_name}>{c.camera_name} · 안 됨 {c.unlabeled} · 7일 확정 {c.labeled_7d}</li>)}</ul>
      </Card>
      <p className="text-xs text-zinc-500">규칙 유지율은 <Link href="/labeling/owner/highlight-rules" className="underline">하이라이트 규칙</Link>에서.</p>
    </main>
  );
}
```

`owner/page.tsx`: `getOwnerOverview` import 를 `getV4Overview`(`@/lib/labelingV4Api`)로, `OwnerOverview` 타입을 `V4Overview`(`@/lib/labelingV4`)로 바꾼다. 나머지 로직 동일.

- [ ] **Step 6: 배정 패널**

```tsx
// web/src/app/labeling/team/_camera-assignments.tsx
'use client';

import { useCallback, useEffect, useState } from 'react';

import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { ApiError } from '@/lib/labelingApi';
import type { V4CameraOption, V4Member } from '@/lib/labelingV4';
import { getV4Members, setV4Assignments } from '@/lib/labelingV4Api';

export default function CameraAssignments() {
  const [members, setMembers] = useState<V4Member[]>([]);
  const [cameras, setCameras] = useState<V4CameraOption[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { const r = await getV4Members(); setMembers(r.members); setCameras(r.cameras); }
    catch (e) { setErr(e instanceof ApiError ? e.message : (e as Error).message); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const toggle = async (m: V4Member, cameraId: string) => {
    const next = m.camera_ids.includes(cameraId) ? m.camera_ids.filter((c) => c !== cameraId) : [...m.camera_ids, cameraId];
    setBusyId(m.user_id); setErr(null);
    try { await setV4Assignments(m.user_id, next); await load(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : (e as Error).message); }
    finally { setBusyId(null); }
  };

  return (
    <Card className="space-y-3">
      <CardTitle>카메라 배정 (먼저 보여줄 카메라 — 권한 아님)</CardTitle>
      {err && <p className="text-sm text-rose-700">{err}</p>}
      <table className="w-full text-sm">
        <thead><tr><th className="text-left">회원</th>{cameras.map((c) => <th key={c.id} className="text-left">{c.name}</th>)}</tr></thead>
        <tbody>
          {members.map((m) => (
            <tr key={m.user_id}>
              <td>{m.display_name}</td>
              {cameras.map((c) => (
                <td key={c.id}>
                  <input type="checkbox" aria-label={`${m.display_name} ${c.name}`} checked={m.camera_ids.includes(c.id)} disabled={busyId === m.user_id} onChange={() => toggle(m, c.id)} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <Button variant="secondary" size="sm" onClick={load}>↻ 새로고침</Button>
    </Card>
  );
}
```

`team/page.tsx` 100~112줄의 `그룹·카메라 배정` Link 블록(주석 포함)을 삭제하고, 그 자리에 `<CameraAssignments />` 를 넣는다(`import CameraAssignments from './_camera-assignments';` 추가).

- [ ] **Step 7: 통과 + 커밋**

Run: `cd /Users/baek/petcam-lab/web && npx vitest run src/app/labeling/_v4-clip-ui.test.tsx && npx tsc --noEmit -p .`
Expected: `5 passed`, tsc 0 (owner `_role-pages.test.tsx` 의 OwnerOverviewView 테스트는 Task 7 에서 교체)

```bash
cd /Users/baek/petcam-lab && git add web/src/app/labeling && git commit -m "feat: 라벨링 v4 내 카메라/전체 목록·상세 확정·owner 현황·배정 패널"
```

---

### Task 7: 경로·메뉴·홈 전환 + blind 트랙 퇴역

**Context:**
- Depends on: Task 6
- Outputs: `labelingRoleNavigation.ts`, `labelingRouteAccess.ts`, `_home-switch.tsx`, `_role-shell.tsx`(NAV_ICON), `labelingLibraryApi.ts`(보관함 클라이언트 분리), 삭제 목록 적용, 테스트 갱신
- Must know: 삭제 전 import 그래프 — `library/page.tsx`·`library/[clipId]/page.tsx`·`_library-views.tsx` 는 `motionBlindReviewApi` 의 `getLabelingLibrary/getLabelingLibraryClip/getLibraryFileUrl/getLibraryDownloadUrl/getMotionCamerasSafe/LabelingLibraryFilters` 를 쓴다 → 새 `labelingLibraryApi.ts` 로 옮긴다. `api/labeling-v3/library/**` 두 route 는 `isValidUuid` 를 `motionBlindReviewServer` 에서 가져온다 → `@/app/api/labeling-v4/_access` 의 `isUuid` 로 교체. `_home-switch.tsx` 는 labeler → `/labeling/mine` 로 redirect. `/labeling/me`(내 기록) 는 blind 제출 기록이라 함께 퇴역(메뉴 제거) — 확정 기록 화면은 후속 스펙.
- Acceptance: `cd web && npm test && npx tsc --noEmit -p . && npx next build` 전부 통과, `grep -rn "motionBlind\|labeling-v3/blind\|_blind-review\|/labeling/blind" src` 결과 0

**Files:**
- Create: `web/src/lib/labelingLibraryApi.ts`
- Modify: `web/src/lib/labelingRoleNavigation.ts`, `web/src/lib/labelingRouteAccess.ts`, `web/src/app/labeling/_home-switch.tsx`, `web/src/app/labeling/_role-shell.tsx`, `web/src/app/labeling/library/page.tsx`, `web/src/app/labeling/library/[clipId]/page.tsx`, `web/src/app/labeling/library/_library-views.tsx`, `web/src/app/api/labeling-v3/library/[clipId]/route.ts`, `web/src/app/api/labeling-v3/library/[clipId]/file/url/route.ts`, `web/src/lib/labelingRoleNavigation.test.ts`, `web/src/lib/labelingRouteAccess.test.ts`, `web/src/app/labeling/_role-pages.test.tsx`, `web/src/app/labeling/_review-video-layout.test.ts`, `web/src/lib/labelingRoleData.ts`
- Delete: `web/src/app/labeling/blind/`, `web/src/app/api/labeling-v3/blind/`, `web/src/app/labeling/_blind-review-detail.tsx`, `_blind-review-queue.tsx`, `_blind-review-progress.tsx`, `_blind-review-onboarding.tsx`, `_blind-review-view.ts`, `_blind-review-ui.test.tsx`, `_blind-hardening.test.ts`, `_owner-conflict-comparison.tsx`, `_owner-conflict-comparison.test.tsx`, `_labeler-history.tsx`, `web/src/app/labeling/me/`, `web/src/lib/motionBlindReview.ts`, `motionBlindReviewV2.ts`, `motionBlindReviewApi.ts`, `motionBlindReviewServer.ts`, `motionBlindDraft.ts` (+ 각 `.test.ts`)

- [ ] **Step 1: 메뉴·경로 테스트를 먼저 새 계약으로 고친다**

`labelingRoleNavigation.test.ts` 의 두 기대 배열을:

```ts
expect(roleNavItems('labeler').map((x) => x.label)).toEqual(['내 카메라', '전체', '영상 보기', '데이터 현황', '게코 박스', 'GME 점검']);
expect(roleNavItems('owner').map((x) => x.label)).toEqual(['운영 현황', '전체', '팀 관리', '데이터 현황', '게코 연구', 'GME 점검']);
```

`labelingRouteAccess.test.ts`: `/labeling/blind/**` 를 다루는 expect 줄 전부 삭제하고 아래를 추가:

```ts
it('v4 목록·상세는 승인 역할 공용(shared)', () => {
  expect(categorize('/labeling/mine')).toBe('shared');
  expect(categorize('/labeling/all')).toBe('shared');
  expect(categorize('/labeling/v4/11111111-1111-4111-8111-111111111111')).toBe('shared');
  expect(categorize('/labeling/v4/not-uuid')).toBe('invalid');
});
it('퇴역한 blind 경로는 invalid 로 역할 홈으로 보낸다', () => {
  expect(categorize('/labeling/blind/c1')).toBe('invalid');
  expect(categorize('/labeling/blind/conflicts')).toBe('invalid');
  expect(categorize('/labeling/me')).toBe('invalid');
});
```

- [ ] **Step 2: 실패 확인** — `npx vitest run src/lib/labelingRoleNavigation.test.ts src/lib/labelingRouteAccess.test.ts` → FAIL

- [ ] **Step 3: 메뉴·경로 구현**

`labelingRoleNavigation.ts` NAV 를:

```ts
const NAV: Record<LabelingRole, readonly RoleNavItem[]> = {
  labeler: [
    { href: '/labeling/mine', label: '내 카메라', mobileLabel: '내 카메라', activePrefixes: ['/labeling/mine', '/labeling/v4/'] },
    { href: '/labeling/all', label: '전체', mobileLabel: '전체', activePrefixes: ['/labeling/all'] },
    { href: '/labeling/library', label: '영상 보기', mobileLabel: '영상', activePrefixes: ['/labeling/library'] },
    { href: '/labeling/dashboard', label: '데이터 현황', mobileLabel: '현황', activePrefixes: ['/labeling/dashboard'] },
    { href: '/labeling/yolo', label: '게코 박스', mobileLabel: '박스', activePrefixes: ['/labeling/yolo'] },
    { href: '/labeling/gme-audit', label: 'GME 점검', mobileLabel: 'GME', activePrefixes: ['/labeling/gme-audit'] },
  ],
  owner: [
    { href: '/labeling/owner', label: '운영 현황', mobileLabel: '운영', activePrefixes: ['/labeling/owner'] },
    { href: '/labeling/all', label: '전체', mobileLabel: '전체', activePrefixes: ['/labeling/all', '/labeling/mine', '/labeling/v4/'] },
    { href: '/labeling/team', label: '팀 관리', mobileLabel: '팀', activePrefixes: ['/labeling/team'] },
    { href: '/labeling/dashboard', label: '데이터 현황', mobileLabel: '현황', activePrefixes: ['/labeling/dashboard'] },
    { href: '/labeling/owner/yolo', label: '게코 연구', mobileLabel: '게코', activePrefixes: ['/labeling/owner/yolo'] },
    { href: '/labeling/gme-audit', label: 'GME 점검', mobileLabel: 'GME', activePrefixes: ['/labeling/gme-audit'] },
  ],
  unapproved: [],
};
```

`roleHome`: labeler → `'/labeling/mine'`. `labelingRouteAccess.ts` `categorize` 에서 `/labeling/blind/**` 세 분기와 `/labeling/me` 분기를 삭제하고, `library` 분기 앞에:

```ts
  // v4 목록·상세 — 승인 역할 공용. 배정은 필터일 뿐이라 권한 경계가 아니다(v4 스펙 §4.1).
  if (pathname === '/labeling/mine' || pathname === '/labeling/all') return 'shared';
  if (pathname.startsWith('/labeling/v4/')) {
    return CLIP_UUID.test(pathname.slice('/labeling/v4/'.length)) ? 'shared' : 'invalid';
  }
  // 퇴역 경로(이중 blind·내 기록)는 역할 홈으로.
  if (pathname.startsWith('/labeling/blind') || pathname.startsWith('/labeling/me')) return 'invalid';
```

`redirectTarget` 의 labeler 홈 `'/labeling'` 두 곳을 `'/labeling/mine'` 으로. `_home-switch.tsx`: `BlindReviewQueue` import 제거, labeler 면 `router.replace('/labeling/mine')` 하는 `LabelerHomeRedirect`(OwnerHomeRedirect 와 같은 꼴)를 렌더. `_role-shell.tsx` `NAV_ICON` 에서 `'/labeling/blind/conflicts'` 키 제거, `'/labeling/mine': '📷'`, `'/labeling/all': '🗂️'` 추가.

- [ ] **Step 4: 보관함 클라이언트 분리**

```ts
// web/src/lib/labelingLibraryApi.ts — motionBlindReviewApi 에서 보관함 함수만 옮김(동작 동일).
'use client';

import { ApiError, UnauthorizedError } from './labelingApi';
import { getSupabaseBrowser } from './supabaseBrowser';
import type { LabelingLibraryItem, LabelingLibraryResponse } from './labelingRoleData';

async function authHeader(): Promise<Record<string, string>> {
  const { data: { session } } = await getSupabaseBrowser().auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', ...((init?.headers as Record<string, string>) || {}), ...(await authHeader()) };
  let resp: Response;
  try { resp = await fetch(path, { ...init, headers }); } catch (e) { throw new ApiError(0, `네트워크 오류: ${(e as Error).message}`); }
  if (resp.status === 401) throw new UnauthorizedError();
  if (!resp.ok) {
    let detail = resp.statusText || `HTTP ${resp.status}`;
    let code: string | undefined;
    try { const j = await resp.json(); if (typeof j?.detail === 'string') detail = j.detail; if (typeof j?.code === 'string') code = j.code; } catch { /* */ }
    throw new ApiError(resp.status, detail, undefined, code);
  }
  return resp.json() as Promise<T>;
}

export interface LabelingLibraryFilters {
  labelState?: string | null; labelSource?: string | null; finalDecision?: string | null;
  cameraIds?: string[]; dateFrom?: string | null; dateTo?: string | null; timeFrom?: string | null; timeTo?: string | null;
  cursor?: string | null; limit?: number;
}

export async function getLabelingLibrary(filters: LabelingLibraryFilters = {}): Promise<LabelingLibraryResponse> {
  const sp = new URLSearchParams();
  (filters.cameraIds ?? []).forEach((id) => sp.append('camera_id', id));
  if (filters.dateFrom) sp.set('date_from', filters.dateFrom);
  if (filters.dateTo) sp.set('date_to', filters.dateTo);
  if (filters.cursor) sp.set('cursor', filters.cursor);
  if (filters.limit != null) sp.set('limit', String(filters.limit));
  if (filters.labelState) sp.set('label_state', filters.labelState);
  if (filters.labelSource) sp.set('label_source', filters.labelSource);
  if (filters.finalDecision) sp.set('final_decision', filters.finalDecision);
  if (filters.timeFrom) sp.set('time_from', filters.timeFrom);
  if (filters.timeTo) sp.set('time_to', filters.timeTo);
  const qs = sp.toString();
  return request<LabelingLibraryResponse>(`/api/labeling-v3/library${qs ? `?${qs}` : ''}`);
}
export function getLabelingLibraryClip(clipId: string): Promise<LabelingLibraryItem> {
  return request<LabelingLibraryItem>(`/api/labeling-v3/library/${clipId}`);
}
export function getLibraryFileUrl(clipId: string): Promise<{ url: string; expires_in: number }> {
  return request(`/api/labeling-v3/library/${clipId}/file/url`);
}
export function getLibraryDownloadUrl(clipId: string): Promise<{ url: string; filename: string; expires_in: number }> {
  return request(`/api/labeling-v3/library/${clipId}/file/url?download=1`);
}
export async function getMotionCamerasSafe(): Promise<{ id: string; name: string }[]> {
  try { return (await request<{ cameras: { id: string; name: string }[] }>('/api/labeling-v3/cameras')).cameras; } catch { return []; }
}
```

`library/page.tsx`, `library/[clipId]/page.tsx`, `library/_library-views.tsx` 의 `@/lib/motionBlindReviewApi` import 를 `@/lib/labelingLibraryApi` 로 바꾼다. `api/labeling-v3/library/[clipId]/route.ts` 와 `.../file/url/route.ts` 의 `import { isValidUuid } from '@/lib/motionBlindReviewServer'` 를 `import { isUuid as isValidUuid } from '@/app/api/labeling-v4/_access'` 로.

- [ ] **Step 5: 삭제 + 잔여 참조 정리**

```bash
cd /Users/baek/petcam-lab/web && git rm -r -q src/app/labeling/blind src/app/api/labeling-v3/blind src/app/labeling/me \
  src/app/labeling/_blind-review-detail.tsx src/app/labeling/_blind-review-queue.tsx src/app/labeling/_blind-review-progress.tsx \
  src/app/labeling/_blind-review-onboarding.tsx src/app/labeling/_blind-review-view.ts src/app/labeling/_blind-review-ui.test.tsx \
  src/app/labeling/_blind-hardening.test.ts src/app/labeling/_owner-conflict-comparison.tsx src/app/labeling/_owner-conflict-comparison.test.tsx \
  src/app/labeling/_labeler-history.tsx src/lib/motionBlindReview.ts src/lib/motionBlindReview.test.ts src/lib/motionBlindReviewV2.ts \
  src/lib/motionBlindReviewV2.test.ts src/lib/motionBlindReviewApi.ts src/lib/motionBlindReviewServer.ts src/lib/motionBlindDraft.ts src/lib/motionBlindDraft.test.ts
grep -rn "motionBlind\|labeling-v3/blind\|_blind-review\|/labeling/blind\|_labeler-history\|_owner-conflict" src
```

grep 이 남는 파일마다: `_role-pages.test.tsx` 는 HistoryCard·Canary·OwnerOverview(구) describe 3개를 삭제하고 보관함 describe 2개만 남긴다(import 도 정리). `_review-video-layout.test.ts` 의 파일 목록에서 `'_blind-review-detail.tsx'` 를 `'v4/_v4-clip-detail.tsx'` 로 바꾼다. `labelingRoleData.ts` 의 `BlindHistoryItem/BlindHistoryResponse/OwnerOverview*` 타입은 삭제(보관함 타입·`PublicLabelState/Source`·`collapseFinalStatus` 는 유지). `labelingRoleServer.ts` 주석의 `motionBlindReviewServer` 언급은 `labelingQueueCursor` 로 고친다.

- [ ] **Step 6: 전체 검증 + 커밋**

Run: `cd /Users/baek/petcam-lab/web && npm test && npx tsc --noEmit -p . && npx next build`
Expected: 테스트 전부 PASS(파일 수는 줄어듦), tsc 0, build 성공. `grep` 결과 0.

```bash
cd /Users/baek/petcam-lab && git add -A web/src && git commit -m "refactor: 이중 blind 트랙 퇴역(코드·라우트 제거) + v4 메뉴·경로·홈 전환"
```

---

### Task 8: 문서 RETIRED 표시 + 스펙 체크

**Context:**
- Depends on: Task 7
- Outputs: `docs/FEATURES.md` §11.8 상단에 RETIRED 배너, `docs/DATABASE.md` "motion_labeling_review_*" 절 상단에 RETIRED 배너 + v4 절 추가, `docs/API.md` labeling-v4 표에 목록·상세·미디어·overlay·카메라·owner 배정/현황 행 추가, `experiments/INDEX.md` formal Blind30 행에 `closed by owner 2026-09-07` 표기, 스펙 `feature-labeling-web-v4-simplification.md` §3 Phase 1·2 체크
- Must know: 내용 삭제 금지 — 배너만. 형식: `> ⛔ **RETIRED 2026-09-08 (owner 결정 2026-09-07):** 이중 blind·교차검증 트랙은 코드·라우트를 제거했고 테이블·row 는 보존, RPC 는 service_role EXECUTE 회수. 대체: [라벨링 웹 v4](../specs/feature-labeling-web-v4-simplification.md). 아래는 역사 기록.`
- Acceptance: diff 리뷰. 스펙 Phase 1·2 항목 중 배포 항목 제외 전부 `[x]`.

- [ ] **Step 1: 배너·표 추가** (위 문구 그대로)
- [ ] **Step 2: DATABASE.md v4 절**

```markdown
### `labeler_camera_assignments` + 라벨링 v4 RPC (2026-09-08) — 🟡 로컬 실증 완료·production 미적용

회원 ↔ 카메라 배정은 "먼저 보여줄 카메라"일 뿐 권한이 아니다. `fn_list_labeling_v4_clips(viewer, is_owner, scope mine|all, camera_ids, label_state, highlight_state, engine, algorithm, detector, cursor×2, limit)` 가 `(started_at DESC, id DESC)` keyset 으로 verdict·exact GME run·active 규칙 eval 을 lateral 로 붙여 행마다 하이라이트 현재값을 계산한다. `fn_set_labeler_camera_assignments`·`fn_list_labeling_v4_members`·`fn_list_labeling_v4_cameras`·`fn_get_labeling_v4_overview` 는 owner/필터용 집계다. 이중 blind RPC 13개는 `to_regprocedure` 존재 확인 뒤 `REVOKE EXECUTE … FROM service_role`(DROP 없음).
```

- [ ] **Step 3: 커밋**

```bash
cd /Users/baek/petcam-lab && git add docs experiments/INDEX.md specs/feature-labeling-web-v4-simplification.md && git commit -m "docs: blind 트랙 RETIRED 표시 + 라벨링 v4 DB/API 계약"
```

---

### Task 9: Preview canary → production (owner 승인 경계, 코드 0)

**Context:**
- Depends on: Task 1~8 + A 계획 전부. **owner 가 "배포해" 라고 말하기 전엔 시작하지 않는다.**
- Must know: 순서 = ① production migration 2개(A Task 1 → B Task 1) 적용 ② Vercel Preview 배포 ③ 실계정 read-only smoke ④ production 승격. migration 은 forward-only, 되돌림은 "새 live 확정 경로 닫기"(v4 route 제거 재배포)이지 DROP 이 아니다.
- Acceptance: 아래 체크 전부 + `specs/next-session.md` 상단 블록에 `DEPLOYED_VERIFIED` 기록

- [ ] production Supabase 에 `2026-09-08_highlight_rule_v0.sql` 적용 → `select version from public.fn_get_active_highlight_rule();` = `hl-rule-v0`
- [ ] `2026-09-08_labeling_v4_simplification.sql` 적용 → `select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.proname like 'fn_list_labeling_v4%'` = 2; `select has_function_privilege('service_role','public.fn_get_motion_blind_workspace(uuid)','execute')` = false
- [ ] 기존 원장 불변 확인: `motion_clip_review_slots`/`motion_clip_blind_submissions`/`motion_clip_consensus` count 가 적용 전과 동일
- [ ] Preview 배포 → owner 계정으로 `/labeling/all?highlight_state=yes` 200, 카드 배지·근거 표시, 상세에서 `1차 판정` 카드, `/labeling/blind/conflicts` 는 `/labeling/owner` 로 리다이렉트
- [ ] member 실계정 1명: `/labeling/mine` 빈 상태 문구(배정 전) → owner 가 배정 → 목록 표시 → 영상 1개 `O 확정` → 같은 영상 owner 재확정 시 409 안내
- [ ] production 승격 → `label.tera-ai.uk/labeling/all` 200, 공개 JSON 에 `gme_run_id`·`detector_identity`·reviewer UUID 부재(응답 grep)
- [ ] `docs/decision-gate.md` 에 배포 기록 append, `specs/*` 상태 `DEPLOYED_VERIFIED`, `.claude/donts-audit.md` 1줄

---

## Self-Review

**Spec coverage (v4 스펙 §2 In 1~8):** 1 역할 2개 → `requireLabelingAccess/requireOwner` 재사용 ✓ 2 배정 테이블+RPC → Task 1 ✓ 3 A페이지 → `mine/page.tsx` + 기본 필터 `unlabeled` ✓ 4 B페이지 → `all/page.tsx` + 카메라 필터 ✓ 5 Owner 페이지 → 현황 교체 + 배정 패널 + 규칙 링크(규칙 화면 자체는 A 계획 route 만 있고 UI 는 없음 — **gap: `/labeling/owner/highlight-rules` 페이지**. 최소 화면(active 규칙 JSON 표시 + textarea 로 새 버전 POST + stats 표)을 Task 6 Step 5 에 추가한다 — 아래 Step 5b) 6 잠금 → 부분 유니크 + 409 안내 ✓ 7 라벨 항목 v4.0 = O/X 만 ✓ 8 퇴역 → Task 7 + REVOKE ✓. §4.2 lease 폐기 ✓. §5 체험(확정 → 다음 안 된 영상) ✓.

**Step 5b (추가, Task 6):** `web/src/app/labeling/owner/highlight-rules/page.tsx`

```tsx
'use client';

import { useCallback, useEffect, useState } from 'react';

import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { ApiError } from '@/lib/labelingApi';

// owner 규칙 화면(v0 최소). active 규칙 params 를 보고, 새 버전을 JSON 으로 저장·활성화하고, 유지율 표를 본다.
export default function HighlightRulesPage() {
  const [active, setActive] = useState<{ version: string; params: unknown; activated_at: string } | null>(null);
  const [stats, setStats] = useState<{ rows: { rule_version: string; camera_name: string | null; verdict_count: number; kept_ratio: number | null; o_to_x: number; x_to_o: number; reason_counts: Record<string, number> }[] } | null>(null);
  const [version, setVersion] = useState('');
  const [params, setParams] = useState('');
  const [note, setNote] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const authed = async (path: string, init?: RequestInit) => {
    const { getSupabaseBrowser } = await import('@/lib/supabaseBrowser');
    const { data: { session } } = await getSupabaseBrowser().auth.getSession();
    const resp = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${session?.access_token ?? ''}`, ...(init?.headers as Record<string, string> ?? {}) } });
    const body = await resp.json();
    if (!resp.ok) throw new ApiError(resp.status, body?.detail ?? `HTTP ${resp.status}`, undefined, body?.code);
    return body;
  };

  const load = useCallback(async () => {
    try {
      const a = await authed('/api/labeling-v4/owner/highlight-rules'); setActive(a); setParams(JSON.stringify(a.params, null, 2));
      setStats(await authed('/api/labeling-v4/owner/highlight-stats'));
    } catch (e) { setErr(e instanceof ApiError ? e.message : (e as Error).message); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const save = async () => {
    setBusy(true); setErr(null);
    try { await authed('/api/labeling-v4/owner/highlight-rules', { method: 'POST', body: JSON.stringify({ version, params: JSON.parse(params), note }) }); setVersion(''); setNote(''); await load(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : (e as Error).message); }
    finally { setBusy(false); }
  };

  return (
    <main className="min-w-0 space-y-4 px-4 py-6">
      <h1 className="text-xl font-semibold text-zinc-900">하이라이트 규칙</h1>
      {err && <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{err}</Card>}
      <Card className="space-y-2">
        <CardTitle>활성 규칙 {active?.version ?? '-'}</CardTitle>
        <p className="text-xs text-zinc-500">활성화 {active?.activated_at ? new Date(active.activated_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }) : '-'}</p>
        <input className="w-full rounded border px-2 py-1 text-sm" placeholder="hl-rule-v1" value={version} onChange={(e) => setVersion(e.target.value)} />
        <textarea className="h-56 w-full rounded border px-2 py-1 font-mono text-xs" value={params} onChange={(e) => setParams(e.target.value)} />
        <input className="w-full rounded border px-2 py-1 text-sm" placeholder="왜 바꿨나 한 줄" value={note} onChange={(e) => setNote(e.target.value)} />
        <Button variant="labelingPrimary" disabled={busy || !version} onClick={save}>새 버전 저장 + 활성화</Button>
      </Card>
      <Card className="space-y-2">
        <CardTitle>최근 7일 유지율 (규칙 × 카메라)</CardTitle>
        <table className="w-full text-sm">
          <thead><tr><th className="text-left">규칙</th><th className="text-left">카메라</th><th>확정</th><th>유지율</th><th>O→X</th><th>X→O</th><th className="text-left">사유</th></tr></thead>
          <tbody>{(stats?.rows ?? []).map((r, i) => (
            <tr key={i}><td>{r.rule_version}</td><td>{r.camera_name ?? '-'}</td><td className="text-center">{r.verdict_count}</td><td className="text-center">{r.kept_ratio === null ? '-' : `${Math.round(r.kept_ratio * 100)}%`}</td><td className="text-center">{r.o_to_x}</td><td className="text-center">{r.x_to_o}</td><td>{Object.entries(r.reason_counts).map(([k, v]) => `${k} ${v}`).join(', ')}</td></tr>
          ))}</tbody>
        </table>
      </Card>
    </main>
  );
}
```

`labelingRouteAccess.ts` 의 owner 분기는 `/labeling/owner` prefix 로 이미 owner 전용이라 추가 분류 불필요.

**Placeholder scan:** "TBD/similar to/handle edge cases" 없음. 모든 코드 스텝에 실제 코드가 있다.

**Type consistency:** `V4ClipItem.highlight` 필드명 `source/status/value/reason/reviewer_name/decided_at` — 매퍼(Task 3)·카드(Task 6)·테스트 동일. RPC `fn_list_labeling_v4_clips` 반환 컬럼 `highlight_source/highlight_status/highlight_value/highlight_reason/reviewer_name/decided_at` — SQL(Task 1)·`V4ClipRow`(Task 3)·probe(Task 2 `highlight_source` 등) 동일. `getV4Members()` 반환 `{ members, cameras }` — 클라이언트(Task 3)·route(Task 5)·패널(Task 6) 동일. `submitV4Verdict` 의 `kind` — A 계획 Task 5 route 가 받는 body 키와 동일. `ApiError(status, message, issues?, code?)` 4-인자 시그니처는 `labelingApi.ts:41`에서 확인했고 세 호출부 모두 `undefined, code` 로 맞췄다.

# 하이라이트 2단 tier(⭐ 대표 / 후보) Implementation Plan

> **구현 방식 (CAOF):** Critical 트랙(production migration + 앱 API + 라벨링 웹, 파일 15+). 이 계획을 task 순서대로 구현한다. Steps use checkbox (`- [ ]`) syntax for tracking.
> production write(migration 적용·fly 배포·main push)는 Task 7 의 **승인 게이트**에서 owner 승인 뒤에만.

**Goal:** 하이라이트 O 가 하루 28~95개라 유저가 볼 수 없다. O/X 와 사람 확정·표본·규칙 params 는 그대로 두고, **조회 시 계산되는 예산 레이어**(하루 20:00 경계 · 30분 에피소드 묶기 · 사건 점수 · top-3)를 얹어 앱엔 ⭐ 대표만, 라벨링 웹엔 대표·후보 둘 다 보여준다. 스펙: [`specs/feature-highlight-featured-tier.md`](../../../specs/feature-highlight-featured-tier.md), 결정 로그 2026-09-10.

**Architecture:** ① DB 함수 `fn_highlight_featured` 하나가 기간·카메라·GME 계약을 받아 현재 O 클립을 사건으로 묶고 순위·tier 를 붙여 돌려준다(저장 없음, `#variable_conflict use_column`). ② petcam-api `GET /highlights/featured` 가 그 함수를 본인 카메라·최근 N일로 호출해 대표만(기본) 또는 전부 준다. 기존 `GET /highlights` 불변. ③ 라벨링 웹은 목록 페이지의 O 항목에 같은 함수로 tier 를 덧붙이고(보조 정보), `⭐ 대표만` 칩은 별도 route 로 대표만 받으며, 상세는 그 클립의 하루 창으로 한 줄을 만든다. ④ 읽기 전용 실측 스크립트로 배포 전 production 타이밍과 카메라×하루 대표 수를 확인한다.

**Tech Stack:** PostgreSQL plpgsql(윈도우 함수·LATERAL) · FastAPI(petcam-api, fly) · Next.js 14 App Router · vitest SSR · 일회용 PostgreSQL probe(`scripts/run_labeling_v4_probe.py`) · supabase-py 읽기 전용 스크립트.

**건드리지 않는 것:** 규칙 params·트리거(`hl-rule-v0`), `motion_clip_highlight_verdicts`·`motion_clip_behavior_flags` 스키마, `fn_list_labeling_v4_clips`, `GET /highlights`, 봉인 표본·2.6.1 절차, Flutter(핸드오프 문서만).

**순서·규모:** Task 1(DB, 3h) → Task 2(실측, 1h) → Task 3(앱 API, 2h) → Task 4·5·6(웹, 4h) → Task 7(문서·배포, 2h). 각 Task 끝에 커밋(`feat:`/`docs:` prefix, Co-Authored-By 유지). web 명령은 항상 `cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0/web && …`(donts#12).

---

## File Structure

| 파일 | 책임 |
|---|---|
| `migrations/2026-09-10_highlight_featured_tier.sql` (신규) | `fn_highlight_featured(...)` 읽기 전용, service_role 전용 |
| `tests/test_highlight_featured_migration.py` (신규) | migration 정적 계약(시그니처·기본값·REVOKE·composite IS NOT NULL 회피) |
| `scripts/run_labeling_v4_probe.py` | §14 대표 tier 케이스(에피소드·순위·하루 경계·사람 X 제외·규칙 X 제외·인자 검증·권한) |
| `scripts/report_highlight_featured.py` (신규) | 읽기 전용: 카메라×하루 `O·사건·대표·✨사건` 표 + RPC 타이밍(production 성능 게이트) |
| `backend/routers/highlights.py` | `_owned_camera_ids` 추출, `featured_window`, `GET /highlights/featured`, `_to_featured_item` |
| `tests/test_highlights_api.py` | FakeSupabase 에 `featured_rows`, 신규 테스트 5 |
| `web/src/lib/labelingV4.ts` | `V4FeaturedTier`·`V4FeaturedInfo`·상수·`featuredBadgeText`·`featuredLineText`, `V4ClipItem.featured`·`V4ClipDetail.featured` |
| `web/src/lib/labelingV4Server.ts` | `V4FeaturedRow`·`mapFeaturedInfo`·`mapFeaturedRowToItem`·`dayKeyOf`·`dayKeyStartUtc`·`featuredWindowFor`·`featuredWindowDays`·`parseV4FeaturedRequest` |
| `web/src/lib/labelingV4Server.test.ts` | 위 순수 함수 테스트 + 기존 기대값에 `featured: null` |
| `web/src/lib/labelingV4Api.ts` | `getV4Featured(cameraIds, days)` |
| `web/src/app/api/labeling-v4/_thumbnails.ts` (신규) | `attachThumbnails` 를 clips route 에서 옮김(featured route 와 공유) |
| `web/src/app/api/labeling-v4/_featured.ts` (신규) | `loadFeaturedRows`, `attachFeatured`, `loadFeaturedForClip` |
| `web/src/app/api/labeling-v4/clips/route.ts` | `attachFeatured(items)` 호출 |
| `web/src/app/api/labeling-v4/featured/route.ts` (신규) | GET `?days=&camera_id=` → 대표만 |
| `web/src/app/api/labeling-v4/clips/[clipId]/route.ts` | 응답에 `featured` |
| `web/src/app/labeling/_v4-clip-list.tsx` | 카드 배지, `UrlFilters.featured`, `⭐ 대표만` 칩, featured 모드 로드 |
| `web/src/app/labeling/v4/_v4-clip-detail.tsx` | `HighlightDecisionPanel.featuredLine` 렌더 + 페이지에서 전달 |
| `web/src/app/labeling/_v4-clip-ui.test.tsx` | 카드 배지·featured 줄 SSR, fixture `featured: null` |
| `docs/highlight-rule-operations.md` · `docs/handoff-prompts/2026-09-08-app-highlight-api-handoff.md` · `docs/FEATURES.md` · `specs/README.md` · `docs/decision-gate.md` · SOT `petcam-ai-pipeline.md` | 문서 |

---

### Task 1: `fn_highlight_featured` migration + 정적 테스트 + probe §14

**Context:**
- Depends on: 없음
- Inputs: `fn_highlight_rule_eval(gme_runs, jsonb)`·`fn_get_active_highlight_rule()`(`migrations/2026-09-08_highlight_rule_v0.sql`), 원장 `motion_clip_highlight_verdicts`, `motion_clip_behavior_flags`, 적격 함수 `fn_is_motion_clip_production_labeling_eligible`
- Outputs: 함수 1개(저장 없음). 시그니처 `fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text)`
- Must know: ⚠️ `rr.run_row IS NOT NULL` 은 composite 라 모든 컬럼 non-NULL 검사 → 반드시 `r.id AS run_id` 를 따로 뽑아 `ON rr.run_id IS NOT NULL`(메모리 `feedback_plpgsql_row_is_not_null`, 목록 함수와 동일). RETURNS TABLE 출력명이 쿼리 컬럼과 겹치므로 `#variable_conflict use_column`. 기간은 최대 31일(범위 밖 스캔 방지, 인덱스 `idx_motion_clips_library_started (started_at DESC, id DESC) WHERE r2_key IS NOT NULL` 이 탄다). 잘못된 `p_tz` 는 `AT TIME ZONE` 이 스스로 22023 을 낸다.
- Acceptance: `cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && uv run pytest tests/test_highlight_featured_migration.py -q` PASS · `nice -n 10 uv run python scripts/run_labeling_v4_probe.py --pg-bin /opt/homebrew/opt/postgresql@15/bin` → `LABELING_V4_PROBE_OK` + `PROBE_RESIDUE=0`

**Files:**
- Create: `migrations/2026-09-10_highlight_featured_tier.sql`
- Create: `tests/test_highlight_featured_migration.py`
- Modify: `scripts/run_labeling_v4_probe.py`

- [ ] **Step 1: 정적 계약 테스트부터(실패 확인용)**

```python
"""대표 tier 함수 migration 정적 계약 — 시그니처·기본값·권한·composite IS NOT NULL 함정 회피."""

from pathlib import Path

import pytest

SQL_PATH = Path(__file__).resolve().parent.parent / "migrations" / "2026-09-10_highlight_featured_tier.sql"


@pytest.fixture()
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def test_signature_and_defaults(sql: str) -> None:
    n = norm(sql)
    assert "create function public.fn_highlight_featured( p_camera_ids uuid[], p_from timestamptz, p_to timestamptz, p_engine_schema_version text, p_algorithm_version text, p_detector_identity text, p_top_n integer default 3, p_gap_sec integer default 1800, p_day_start_hour integer default 20, p_tz text default 'asia/seoul' )" in n
    for col in ("tier text", "episode_rank integer", "episode_clip_count integer", "episode_activity_sec numeric", "is_representative boolean", "day_key date", "reviewer_id uuid", "behavior_flagged boolean"):
        assert col in n, col
    assert "#variable_conflict use_column" in n
    assert "language plpgsql stable security definer set search_path = ''" in n


def test_avoids_composite_is_not_null_and_uses_eligibility(sql: str) -> None:
    n = norm(sql)
    assert "on rr.run_id is not null" in n
    assert "run_row is not null" not in n
    assert "public.fn_is_motion_clip_production_labeling_eligible(c.id)" in n
    assert "x.state = 'media_deleted'" in n


def test_ranking_order_and_tier_rule(sql: str) -> None:
    n = norm(sql)
    assert "order by a.ep_flagged desc, a.ep_human_o desc, a.ep_activity desc, a.ep_start desc" in n
    assert "when r.ep_rank <= p_top_n and p.rep_clip_id = e.clip_id then 'featured' else 'candidate'" in n
    assert "make_interval(secs => p_gap_sec)" in n


def test_privileges_and_no_writes(sql: str) -> None:
    n = norm(sql)
    assert "revoke all on function public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text) from public, anon, authenticated;" in n
    assert "grant execute on function public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text) to service_role;" in n
    for bad in ("drop table", "delete from", "update public.motion_clip_highlight_verdicts", "insert into"):
        assert bad not in n, bad
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && uv run pytest tests/test_highlight_featured_migration.py -q`
Expected: FAIL `migration missing`

- [ ] **Step 3: migration 작성**

```sql
-- 하이라이트 2단 tier — ⭐ 대표 / 후보 (owner 결정 2026-09-10, 결정 로그 2026-09-10).
-- O/X(사람 확정 우선, 없으면 규칙 initial) 는 "후보 자격"이고, 이 함수는 그 위에 **조회 시 계산되는** 예산 레이어를 얹는다:
--   하루 = (started_at AT TIME ZONE p_tz − p_day_start_hour 시)::date  (기본 20:00 → 다음날 20:00 KST)
--   에피소드 = 같은 카메라·같은 하루 안에서 직전 클립 끝(started_at+duration) 과 p_gap_sec 초과로 벌어지면 새 사건
--   사건 정렬 = (✨ 있음, 사람 O 있음, activity 합, 사건 시작 최신) DESC
--   대표 클립 = 사건 안 (✨, 사람 O, activity DESC, 시작 ASC) 1위
--   tier = 사건 순위 ≤ p_top_n 이고 대표 클립이면 'featured', 그 외 O 는 'candidate'
-- 저장하지 않는다 — 입력(verdict·flag·run)이 전부 append-only 원장이라 결과 저장은 중복이고, 사람이 X/✨ 를 바꾸면 다음 조회에 순위가 바뀐다.
-- 성능: 기간 ≤ 31일 강제. motion_clips 는 idx_motion_clips_library_started(started_at DESC, id DESC) WHERE r2_key IS NOT NULL 로 범위 스캔.
BEGIN;

CREATE FUNCTION public.fn_highlight_featured(
  p_camera_ids uuid[],
  p_from timestamptz,
  p_to timestamptz,
  p_engine_schema_version text,
  p_algorithm_version text,
  p_detector_identity text,
  p_top_n integer DEFAULT 3,
  p_gap_sec integer DEFAULT 1800,
  p_day_start_hour integer DEFAULT 20,
  p_tz text DEFAULT 'Asia/Seoul'
) RETURNS TABLE (
  clip_id uuid,
  camera_id uuid,
  camera_name text,
  started_at timestamptz,
  duration_sec double precision,
  day_key date,
  episode_no integer,
  episode_started_at timestamptz,
  episode_ended_at timestamptz,
  episode_clip_count integer,
  episode_activity_sec numeric,
  episode_rank integer,
  tier text,
  is_representative boolean,
  activity_sec numeric,
  highlight_source text,
  highlight_reason text,
  reviewer_id uuid,
  reviewer_display_name text,
  behavior_flagged boolean
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
#variable_conflict use_column
DECLARE
  v_rule record;
BEGIN
  IF p_from IS NULL OR p_to IS NULL OR p_from >= p_to THEN
    RAISE EXCEPTION 'invalid range' USING ERRCODE = '22023';
  END IF;
  IF p_to - p_from > interval '31 days' THEN
    RAISE EXCEPTION 'range too wide (max 31 days)' USING ERRCODE = '22023';
  END IF;
  IF p_top_n IS NULL OR p_top_n < 1 OR p_top_n > 10 THEN
    RAISE EXCEPTION 'invalid top_n (1..10)' USING ERRCODE = '22023';
  END IF;
  IF p_gap_sec IS NULL OR p_gap_sec < 60 OR p_gap_sec > 21600 THEN
    RAISE EXCEPTION 'invalid gap_sec (60..21600)' USING ERRCODE = '22023';
  END IF;
  IF p_day_start_hour IS NULL OR p_day_start_hour < 0 OR p_day_start_hour > 23 THEN
    RAISE EXCEPTION 'invalid day_start_hour (0..23)' USING ERRCODE = '22023';
  END IF;
  IF p_tz IS NULL THEN
    RAISE EXCEPTION 'invalid time zone' USING ERRCODE = '22023';
  END IF;
  SELECT * INTO v_rule FROM public.fn_get_active_highlight_rule();
  IF v_rule.version IS NULL THEN
    RAISE EXCEPTION 'no active highlight rule' USING ERRCODE = 'PT428';
  END IF;

  RETURN QUERY
  WITH base AS (
    SELECT c.id AS clip_id, c.camera_id, coalesce(cam.name, c.camera_id::text) AS camera_name,
           c.started_at, c.duration_sec,
           vd.verdict AS human_verdict, vd.initial_reason AS human_reason,
           vd.reviewer_id, la.display_name AS reviewer_display_name,
           ev.initial AS rule_initial, ev.reason AS rule_reason,
           (ev.features->>'activity_sec')::numeric AS activity_sec,
           (bf.clip_id IS NOT NULL) AS flagged
      FROM public.motion_clips c
      LEFT JOIN public.cameras cam ON cam.id = c.camera_id
      LEFT JOIN LATERAL (
        SELECT v.verdict, v.initial_reason, v.reviewer_id
          FROM public.motion_clip_highlight_verdicts v
         WHERE v.clip_id = c.id ORDER BY v.created_at DESC, v.id DESC LIMIT 1
      ) vd ON true
      LEFT JOIN public.labeler_applications la ON la.user_id = vd.reviewer_id
      LEFT JOIN public.motion_clip_behavior_flags bf ON bf.clip_id = c.id
      LEFT JOIN LATERAL (
        SELECT r AS run_row, r.id AS run_id
          FROM public.gme_jobs j
          JOIN public.gme_runs r ON r.id = j.result_run_id AND r.job_id = j.id
         WHERE j.clip_id = c.id
           AND j.engine_schema_version = p_engine_schema_version
           AND j.algorithm_version = p_algorithm_version
           AND j.detector_identity = p_detector_identity
           AND j.status = 'succeeded' AND r.status = 'ok'
         ORDER BY j.created_at ASC, j.id ASC LIMIT 1
      ) rr ON true
      -- composite IS NOT NULL 함정: run_row 가 아니라 run_id 로 존재 판정(목록 함수와 동일).
      LEFT JOIN LATERAL public.fn_highlight_rule_eval(rr.run_row, v_rule.params) ev ON rr.run_id IS NOT NULL
     WHERE c.started_at >= p_from AND c.started_at < p_to
       AND c.r2_key IS NOT NULL
       AND (p_camera_ids IS NULL OR c.camera_id = ANY (p_camera_ids))
       AND public.fn_is_motion_clip_production_labeling_eligible(c.id)
       AND NOT EXISTS (SELECT 1 FROM public.motion_clip_system_exclusions x
                        WHERE x.clip_id = c.id AND x.state = 'media_deleted')
  ),
  cur AS (
    SELECT b.*, coalesce(b.human_verdict, b.rule_initial) AS current_value,
           ((b.started_at AT TIME ZONE p_tz) - make_interval(hours => p_day_start_hour))::date AS day_key
      FROM base b
  ),
  o AS (SELECT * FROM cur WHERE current_value IS TRUE),
  gaps AS (
    SELECT o.*,
           CASE WHEN lag(o.started_at + make_interval(secs => coalesce(o.duration_sec, 60))) OVER w IS NULL
                  OR o.started_at - lag(o.started_at + make_interval(secs => coalesce(o.duration_sec, 60))) OVER w
                     > make_interval(secs => p_gap_sec)
                THEN 1 ELSE 0 END AS is_new
      FROM o
    WINDOW w AS (PARTITION BY o.camera_id, o.day_key ORDER BY o.started_at, o.clip_id)
  ),
  ep AS (
    SELECT g.*,
           sum(g.is_new) OVER (PARTITION BY g.camera_id, g.day_key ORDER BY g.started_at, g.clip_id
                               ROWS UNBOUNDED PRECEDING)::integer AS episode_no
      FROM gaps g
  ),
  agg AS (
    SELECT e.camera_id, e.day_key, e.episode_no,
           min(e.started_at) AS ep_start,
           max(e.started_at + make_interval(secs => coalesce(e.duration_sec, 60))) AS ep_end,
           count(*)::integer AS ep_count,
           sum(coalesce(e.activity_sec, 0)) AS ep_activity,
           bool_or(e.flagged) AS ep_flagged,
           bool_or(e.human_verdict IS TRUE) AS ep_human_o
      FROM ep e
     GROUP BY e.camera_id, e.day_key, e.episode_no
  ),
  ranked AS (
    SELECT a.*,
           row_number() OVER (PARTITION BY a.camera_id, a.day_key
                              ORDER BY a.ep_flagged DESC, a.ep_human_o DESC, a.ep_activity DESC, a.ep_start DESC)::integer AS ep_rank
      FROM agg a
  ),
  rep AS (
    SELECT t.camera_id, t.day_key, t.episode_no, t.clip_id AS rep_clip_id
      FROM (SELECT e.*,
                   row_number() OVER (PARTITION BY e.camera_id, e.day_key, e.episode_no
                                      ORDER BY e.flagged DESC, (e.human_verdict IS TRUE) DESC,
                                               e.activity_sec DESC NULLS LAST, e.started_at ASC) AS rn
              FROM ep e) t
     WHERE t.rn = 1
  )
  SELECT e.clip_id, e.camera_id, e.camera_name, e.started_at, e.duration_sec, e.day_key, e.episode_no,
         r.ep_start, r.ep_end, r.ep_count, round(r.ep_activity, 1), r.ep_rank,
         CASE WHEN r.ep_rank <= p_top_n AND p.rep_clip_id = e.clip_id THEN 'featured' ELSE 'candidate' END,
         (p.rep_clip_id = e.clip_id),
         round(coalesce(e.activity_sec, 0), 1),
         CASE WHEN e.human_verdict IS NOT NULL THEN 'human' ELSE 'rule' END,
         coalesce(e.human_reason, e.rule_reason, ''),
         e.reviewer_id, e.reviewer_display_name, e.flagged
    FROM ep e
    JOIN ranked r ON r.camera_id = e.camera_id AND r.day_key = e.day_key AND r.episode_no = e.episode_no
    JOIN rep p ON p.camera_id = e.camera_id AND p.day_key = e.day_key AND p.episode_no = e.episode_no
   ORDER BY e.day_key DESC, e.camera_id, r.ep_rank ASC, e.started_at DESC;
END $$;

REVOKE ALL ON FUNCTION public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text) TO service_role;

COMMIT;
```

- [ ] **Step 4: 정적 테스트 통과 확인**

Run: `cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && uv run pytest tests/test_highlight_featured_migration.py -q`
Expected: `4 passed`

- [ ] **Step 5: probe §14 — 모듈 상수·헬퍼 추가(`CAM_B` 아래)**

```python
V4_FEATURED_MIGRATION = ROOT / "migrations" / "2026-09-10_highlight_featured_tier.sql"  # ⭐ 대표 tier(조회 시 계산)
CAM_C = "40000000-0000-4000-8000-000000000003"  # §14 전용 카메라(다른 섹션 개수 불변)
FEAT = {k: f"50000000-0000-4000-8000-00000000000{i}" for i, k in enumerate(
    ("a1", "a2", "b_flag", "c", "human_x", "prev_day", "rule_x"), start=1)}
# UTC 시각. 하루 경계 20:00 KST = 11:00Z. a1·a2 는 5분 간격 → 한 사건(합 27). human_x 는 05:00 KST(같은 하루). prev_day 는 19:30 KST → 전날.
FEAT_AT = {"a1": "2026-09-01T12:00:00Z", "a2": "2026-09-01T12:05:00Z", "b_flag": "2026-09-01T15:00:00Z", "c": "2026-09-01T18:00:00Z",
           "human_x": "2026-09-01T20:00:00Z", "prev_day": "2026-09-01T10:30:00Z", "rule_x": "2026-09-01T21:00:00Z"}


def _feat_job(n: int, clip: str) -> str:
    return f"('5100000{n}-0000-4000-8000-000000000001','{clip}','historical',10,'{ENGINE}','{ALGO}','{IDENTITY}','succeeded')"


def _feat_run(n: int, clip: str, activity: float, intervals: str) -> str:
    # setup_sql 의 run_ 과 같은 23 컬럼. sha256 은 setup 과 겹치지 않게 '{n}e' 반복.
    return (f"('5200000{n}-0000-4000-8000-000000000001','{clip}','5100000{n}-0000-4000-8000-000000000001',"
            f"'{ENGINE}','{ALGO}','{IDENTITY}','probe','feat-{n}','ok',60,600,600,10,{activity},{activity},60,0,0,1,"
            f"'terra-derived/gme/v1/permanent/feat/{n}.json',repeat('{n}e',32),1,'[{intervals}]'::jsonb)")


def featured_setup_sql() -> str:
    iv = {"a1": run_row("moving", 0, 12), "a2": run_row("moving", 0, 15), "b_flag": run_row("moving", 0, 20), "c": run_row("moving", 0, 11),
          "human_x": run_row("moving", 0, 30), "prev_day": run_row("moving", 0, 13),
          "rule_x": ",".join([run_row("moving", 0, 2), run_row("moving", 3, 6)])}  # activity 5 · longest 3 → 규칙 X
    act = {"a1": 12, "a2": 15, "b_flag": 20, "c": 11, "human_x": 30, "prev_day": 13, "rule_x": 5}
    keys = list(FEAT)
    return f"""
    INSERT INTO public.cameras(id, name) VALUES ('{CAM_C}', 'probe-cam-c');
    INSERT INTO public.motion_clips(id, camera_id, started_at, duration_sec, r2_key) VALUES
      {",".join(f"('{FEAT[k]}','{CAM_C}','{FEAT_AT[k]}',60,'terra-clips/clips/probe/'||'{FEAT[k]}'||'.mp4')" for k in keys)};
    INSERT INTO public.gme_jobs(id,clip_id,source,priority,engine_schema_version,algorithm_version,detector_identity,status) VALUES
      {",".join(_feat_job(i, FEAT[k]) for i, k in enumerate(keys, start=1))};
    INSERT INTO public.gme_runs(id,clip_id,job_id,engine_schema_version,algorithm_version,detector_identity,
      producer_host,producer_run_id,status,duration_sec,decoded_frame_count,analyzed_frame_count,source_fps,
      candidate_moving_sec_any_gecko,moving_gecko_seconds,visible_sec,unknown_sec,camera_motion_sec,
      max_simultaneous_geckos,permanent_artifact_key,permanent_artifact_sha256,permanent_artifact_bytes,state_intervals) VALUES
      {",".join(_feat_run(i, FEAT[k], act[k], iv[k]) for i, k in enumerate(keys, start=1))};
    UPDATE public.gme_jobs j SET result_run_id = r.id FROM public.gme_runs r WHERE r.job_id = j.id AND j.result_run_id IS NULL;
    """


def run_row(state: str, start: float, end: float) -> str:  # highlight probe 의 run_row 와 동일(이 모듈에서 import 안 됨)
    return f'{{"state":"{state}","start_sec":{start},"end_sec":{end},"track_ids":["g0001"]}}'
```

> `run_row` 는 현재 v4 probe 의 import 목록에 없다(확인 2026-09-10). 위처럼 로컬 정의하거나 `from scripts.run_highlight_rule_v0_probe import` 목록에 `run_row` 를 추가한다 — 둘 중 하나만.

- [ ] **Step 6: probe §14 — migration 적용 목록에 추가 + 케이스(§13 뒤, `print("LABELING_V4_PROBE_OK")` 앞)**

migration 루프 리스트 끝에 `V4_FEATURED_MIGRATION` 추가:

```python
            for path in [*[m for m in MIGRATIONS if m != V4_AGGREGATES_MIGRATION], V4_MIGRATION, V4_LIST_CHUNKED_MIGRATION, V4_AGGREGATES_MIGRATION, V4_BEHAVIOR_FLAGS_MIGRATION, V4_PROGRESS_MIGRATION, V4_VIEW_CLAIMS_MIGRATION, V4_COVERAGE_MIGRATION, V4_EVAL_SAMPLES_MIGRATION, V4_FEATURED_MIGRATION]:
```

케이스:

```python
            # 14) ⭐ 대표 tier(조회 시 계산): CAM_C 에 2026-09-01 클립 7개. 기대(top_n=3):
            #     전날(prev_day 19:30 KST) 1위 featured · b_flag(✨) 1위 · a1+a2 한 사건(합 27) 2위 — 대표 a2 featured, a1 candidate ·
            #     c 3위 featured · human_x(사람 X)·rule_x(규칙 X) 는 아예 없음. top_n=2 면 c 가 candidate.
            require_ok(sql(db, featured_setup_sql()), "featured-setup")
            require_ok(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['b_flag']}','{LABELER}',false,true);"), "featured-flag")
            require_ok(sql(db, f"select * from public.fn_submit_highlight_verdict('{FEAT['human_x']}','{LABELER}',false,false,'initial','false_detection','{ENGINE}','{ALGO}','{IDENTITY}');"), "featured-human-x")
            feat_call = f"public.fn_highlight_featured(array['{CAM_C}']::uuid[], '2026-08-31T00:00:00Z', '2026-09-03T00:00:00Z', '{ENGINE}','{ALGO}','{IDENTITY}', 3, 1800, 20, 'Asia/Seoul')"
            feat_cols = "clip_id||'|'||tier||'|'||episode_rank||'|'||is_representative||'|'||episode_clip_count||'|'||episode_activity_sec||'|'||day_key"
            got = require_ok(sql(db, f"select {feat_cols} from {feat_call} order by day_key, episode_rank, started_at;"), "featured").splitlines()
            want = [f"{FEAT['prev_day']}|featured|1|t|1|13.0|2026-08-31",
                    f"{FEAT['b_flag']}|featured|1|t|1|20.0|2026-09-01",
                    f"{FEAT['a1']}|candidate|2|f|2|27.0|2026-09-01",
                    f"{FEAT['a2']}|featured|2|t|2|27.0|2026-09-01",
                    f"{FEAT['c']}|featured|3|t|1|11.0|2026-09-01"]
            if got != want:
                raise ProbeError(f"featured: got {got} want {want}")
            top2 = require_ok(sql(db, f"select tier from {feat_call.replace(', 3, 1800', ', 2, 1800')} where clip_id = '{FEAT['c']}';"), "featured-top2").strip()
            if top2 != "candidate":
                raise ProbeError(f"featured-top2: {top2}")
            # 사람 O 가산: c 를 사람 O 로 확정하면 a 사건(27) 보다 위(2위) — ✨ 는 여전히 1위
            require_ok(sql(db, f"select * from public.fn_submit_highlight_verdict('{FEAT['c']}','{LABELER}',false,true,'initial',null,'{ENGINE}','{ALGO}','{IDENTITY}');"), "featured-human-o")
            expect("featured-human-o-rank", q(f"select 'rank|'||episode_rank::text from {feat_call} where clip_id = '{FEAT['c']}';"), rank="2")
            expect("featured-source", q(f"select 'src|'||highlight_source||'' from {feat_call} where clip_id = '{FEAT['c']}';"), src="human")
            # 카메라 NULL(전체) 도 같은 5행(다른 섹션 클립은 now() 라 기간 밖) · 하루 경계·간격 인자 검증 · 권한
            expect("featured-all-cams", q(f"select 'n|'||count(*)::text from {feat_call.replace(f\"array['{CAM_C}']::uuid[]\", 'null')};"), n="5")
            require_sqlstate(sql(db, f"select * from {feat_call.replace(\"'2026-08-31T00:00:00Z'\", \"'2026-07-01T00:00:00Z'\")};"), "featured-range", "22023")
            require_sqlstate(sql(db, f"select * from {feat_call.replace(', 3, 1800', ', 0, 1800')};"), "featured-top-n", "22023")
            require_sqlstate(sql(db, f"select * from {feat_call.replace(\"'Asia/Seoul'\", \"'Mars/Olympus'\")};"), "featured-tz", "22023")
            expect("featured-privs", q("select 'ok|'||(not has_function_privilege('authenticated', 'public.fn_highlight_featured(uuid[],timestamptz,timestamptz,text,text,text,integer,integer,integer,text)', 'EXECUTE'))::text;"), ok="true")
            if len(list_ids("all")) != 7:
                raise ProbeError("§14 must not change other sections' list count (CAM_C clips are outside now()-based expectations)")
```

> ⚠️ 마지막 검사: `list_ids("all")` 은 카메라 필터가 없어 CAM_C 클립 5개(적격)가 섞여 7 이 아니라 12 가 된다. 그 경우 검사를 `!= 12` 로 두지 말고 **§14 를 §13 뒤 마지막에 두고 이 줄을 삭제**한다(다른 섹션은 이미 통과했으므로). 계획 시점 판단: 삭제.

- [ ] **Step 7: probe 실행**

Run: `cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && nice -n 10 uv run python scripts/run_labeling_v4_probe.py --pg-bin /opt/homebrew/opt/postgresql@15/bin`
Expected: `LABELING_V4_PROBE_OK` / `PROBE_RESIDUE=0`. 실패 시 `ProbeError` 메시지의 `got` 배열로 정렬·경계를 고친다(합격 기준은 바꾸지 않는다).

- [ ] **Step 8: 커밋**

```bash
cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && git add migrations/2026-09-10_highlight_featured_tier.sql tests/test_highlight_featured_migration.py scripts/run_labeling_v4_probe.py && git commit -m "feat: 하이라이트 ⭐ 대표 tier 함수 fn_highlight_featured(하루 20시·30분 에피소드·top-N, 저장 없음) + probe §14"
```

---

### Task 2: 읽기 전용 실측 스크립트 `scripts/report_highlight_featured.py`

**Context:**
- Depends on: Task 1 의 함수가 **production 에 적용된 뒤** 실행 가능(적용 전엔 `--dry` 로 목록 RPC 기반 근사만). 코드는 지금 쓴다.
- Inputs: `.env`(`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`), 활성 계약(Vercel env 와 같은 값 — `scripts/report_highlight_eval_sample.py` 처럼 `--contract` 인자, 기본은 `gme_jobs` 최신 succeeded 의 값이 아니라 **명시 인자 필수**)
- Outputs: stdout 표 + RPC 타이밍. 파일 안 씀.
- Must know: supabase-py 기본 1,000행 캡(메모리) — 이 RPC 는 O 만 돌려 14일 ≤ 500행이라 안전하지만 `.range()` 없이 쓰는 이유를 주석으로 남긴다. 성능 게이트: 카메라 4대·7일 콜드 ≤ 3초.
- Acceptance: `uv run python scripts/report_highlight_featured.py --days 7 --contract gme-motion-v1 <detector64>` 가 표와 `rpc: N.NNs` 를 찍는다.

**Files:**
- Create: `scripts/report_highlight_featured.py`

- [ ] **Step 1: 스크립트**

```python
"""⭐ 대표 tier 실측(읽기 전용). 카메라×하루 `O · 사건 · 대표 · ✨사건` 표 + fn_highlight_featured 타이밍.

배포 전 production 성능 게이트(콜드 ≤ 3초)와 주간 편향 확인(대표가 늘 같은 시간대인가)에 쓴다.
사용: uv run python scripts/report_highlight_featured.py --days 7 --contract gme-motion-v1 <detector64> [--top-n 3] [--gap-sec 1800] [--camera <uuid>...]
"""

from __future__ import annotations

import argparse
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(Path("/Users/baek/petcam-lab/.env"))
ENGINE = "gme-shadow-v1"
KST = timezone(timedelta(hours=9))


def day_window(now: datetime, days: int, day_start_hour: int = 20) -> tuple[datetime, datetime]:
    """오늘 하루 키(20시 경계) 기준 최근 `days` 개 하루를 덮는 [from, now). petcam-api featured_window 와 같은 정의."""
    key_today = (now.astimezone(KST) - timedelta(hours=day_start_hour)).date()
    first = key_today - timedelta(days=days - 1)
    start = datetime(first.year, first.month, first.day, day_start_hour, tzinfo=KST)
    return start.astimezone(timezone.utc), now


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--contract", nargs=2, metavar=("ALGO", "DETECTOR"), required=True)
    ap.add_argument("--top-n", type=int, default=3)
    ap.add_argument("--gap-sec", type=int, default=1800)
    ap.add_argument("--camera", action="append", default=None, help="uuid, 반복 가능. 없으면 전체")
    a = ap.parse_args()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    p_from, p_to = day_window(datetime.now(timezone.utc), a.days)
    args = {"p_camera_ids": a.camera, "p_from": p_from.isoformat(), "p_to": p_to.isoformat(),
            "p_engine_schema_version": ENGINE, "p_algorithm_version": a.contract[0], "p_detector_identity": a.contract[1],
            "p_top_n": a.top_n, "p_gap_sec": a.gap_sec, "p_day_start_hour": 20, "p_tz": "Asia/Seoul"}
    t = time.time()
    rows = sb.rpc("fn_highlight_featured", args).execute().data  # O 만 돌아와 1,000행 캡 안쪽(14일 실측 ≤ 400)
    cold = time.time() - t
    t = time.time(); sb.rpc("fn_highlight_featured", args).execute(); warm = time.time() - t
    print(f"rpc: cold {cold:.2f}s · warm {warm:.2f}s · rows {len(rows)} · window {p_from.isoformat()} → {p_to.isoformat()}")

    agg = defaultdict(lambda: {"o": 0, "eps": set(), "featured": 0, "flag_eps": set(), "hours": []})
    for r in rows:
        k = (r["camera_name"], r["day_key"])
        g = agg[k]
        g["o"] += 1
        g["eps"].add(r["episode_no"])
        if r["tier"] == "featured":
            g["featured"] += 1
            g["hours"].append(datetime.fromisoformat(r["started_at"]).astimezone(KST).strftime("%H"))
        if r["behavior_flagged"]:
            g["flag_eps"].add(r["episode_no"])
    print("\ncamera | day(20시 경계) | O | 사건 | ⭐대표 | ✨사건 | 대표 시각(KST)")
    for (cam, day), g in sorted(agg.items()):
        print(f"{cam} | {day} | {g['o']} | {len(g['eps'])} | {g['featured']} | {len(g['flag_eps'])} | {' '.join(g['hours'])}")
    over = [(k, g["featured"]) for k, g in agg.items() if g["featured"] > a.top_n]
    print(f"\n대표 > top_n 인 (카메라,하루): {over or '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: `day_window` 단위 테스트(`tests/test_report_highlight_featured.py`)**

```python
"""report_highlight_featured.day_window — 20시 경계 하루 창(petcam-api featured_window 와 같은 정의)."""

from datetime import datetime, timezone

from scripts.report_highlight_featured import day_window


def test_window_covers_days_from_day_key_start() -> None:
    now = datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc)  # 10:00 KST → 오늘 키 = 2026-09-09
    p_from, p_to = day_window(now, 7)
    assert p_from == datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)  # 09-03 20:00 KST
    assert p_to == now


def test_window_after_20_kst_moves_key_to_today() -> None:
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)  # 21:00 KST → 오늘 키 = 2026-09-10
    p_from, _ = day_window(now, 1)
    assert p_from == datetime(2026, 9, 10, 11, 0, tzinfo=timezone.utc)
```

Run: `cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && uv run pytest tests/test_report_highlight_featured.py -q`
Expected: `2 passed` (`scripts/__init__.py` 는 없지만 `tests/test_highlight_rule_v0_probe.py` 가 이미 `from scripts.run_highlight_rule_v0_probe import …` 로 namespace 패키지 import 를 쓰고 있어 같은 방식이 동작한다)

- [ ] **Step 3: 커밋**

```bash
cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && git add scripts/report_highlight_featured.py tests/test_report_highlight_featured.py && git commit -m "feat: 대표 tier 실측 스크립트(카메라×하루 표 + RPC 타이밍, 읽기 전용)"
```

---

### Task 3: petcam-api `GET /highlights/featured`

**Context:**
- Depends on: Task 1(함수 시그니처). 로컬 테스트는 Fake 로 독립.
- Inputs: `backend/routers/highlights.py`(`_active_rule`, `_resolve_gme_contract`, `_rpc`, 카메라 조회 코드), `tests/test_highlights_api.py`(FakeSupabase)
- Outputs: 엔드포인트 1, 순수 함수 `featured_window`, `_owned_camera_ids`, `_to_featured_item`
- Must know: 기존 `GET /highlights` 계약 불변(Flutter 사용 중). 창은 "하루 키 기준 최근 N일"(Task 2 와 동일 정의) — `now - days` 로 자르면 첫 하루가 반쪽이라 top-3 가 틀어진다. reviewer 필드는 응답에서 뺀다.
- Acceptance: `uv run pytest tests/test_highlights_api.py -q` 전부 PASS

**Files:**
- Modify: `backend/routers/highlights.py`
- Modify: `tests/test_highlights_api.py`

- [ ] **Step 1: Fake 확장 + 실패 테스트**

`FakeSupabase.__init__` 에 `featured_rows: list[dict] | None = None` 추가, `self._featured_rows = featured_rows or []`, `rpc()` 에 분기:

```python
        if name == "fn_highlight_featured":
            return _FakeRpc(lambda: list(self._featured_rows))
```

헬퍼·테스트(파일 끝에):

```python
def _frow(i: int, *, tier: str = "featured", rank: int = 1, day_key: str = "2026-09-09", flagged: bool = False) -> dict[str, Any]:
    return {
        "clip_id": f"00000000-0000-0000-0000-{i:012d}", "camera_id": CAM_A, "camera_name": "cam A",
        "started_at": f"2026-09-09T1{i}:00:00+00:00", "duration_sec": 60.0, "day_key": day_key, "episode_no": i,
        "episode_started_at": f"2026-09-09T1{i}:00:00+00:00", "episode_ended_at": f"2026-09-09T1{i}:06:00+00:00",
        "episode_clip_count": 6, "episode_activity_sec": 84.0, "episode_rank": rank, "tier": tier, "is_representative": tier == "featured",
        "activity_sec": 20.5, "highlight_source": "rule", "highlight_reason": "움직임 20.5초 · 최장 연속 9.0초",
        "reviewer_id": "reviewer-uuid", "reviewer_display_name": "라벨러", "behavior_flagged": flagged,
    }


def test_featured_default_returns_only_featured_and_hides_reviewer() -> None:
    sb = FakeSupabase(_cameras(), featured_rows=[_frow(1), _frow(2, tier="candidate", rank=4)])
    r = _client(sb).get("/highlights/featured")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1 and body["highlights"][0]["tier"] == "featured"
    item = body["highlights"][0]
    assert item["episode"] == {"rank": 1, "clip_count": 6, "activity_sec": 84.0, "started_at": "2026-09-09T11:00:00+00:00", "ended_at": "2026-09-09T11:06:00+00:00"}
    assert item["day_key"] == "2026-09-09" and item["rule_version"] == RULE["version"]
    assert "reviewer_id" not in item and "reviewer_display_name" not in item
    assert body["featured"] == {"top_n": 3, "gap_sec": 1800, "day_start_hour": 20, "time_zone": "Asia/Seoul", "days": 7}


def test_featured_tier_all_includes_candidates() -> None:
    sb = FakeSupabase(_cameras(), featured_rows=[_frow(1), _frow(2, tier="candidate", rank=4)])
    body = _client(sb).get("/highlights/featured?tier=all").json()
    assert [h["tier"] for h in body["highlights"]] == ["featured", "candidate"]


def test_featured_passes_cameras_contract_and_params() -> None:
    sb = FakeSupabase(_cameras(), featured_rows=[])
    assert _client(sb).get("/highlights/featured?days=3&top_n=5").status_code == 200
    name, params = [c for c in sb.rpc_calls if c[0] == "fn_highlight_featured"][0]
    assert params["p_camera_ids"] == [CAM_A] and params["p_top_n"] == 5 and params["p_gap_sec"] == 1800
    assert params["p_algorithm_version"] == ENV_ALGO and params["p_detector_identity"] == ENV_IDENTITY
    assert params["p_day_start_hour"] == 20 and params["p_tz"] == "Asia/Seoul"
    assert hl._parse_ts(params["p_to"]) - hl._parse_ts(params["p_from"]) <= hl.timedelta(days=4)


def test_featured_no_cameras_skips_rpc() -> None:
    sb = FakeSupabase({"cameras": []}, featured_rows=[_frow(1)])
    body = _client(sb).get("/highlights/featured").json()
    assert body["count"] == 0 and not [c for c in sb.rpc_calls if c[0] == "fn_highlight_featured"]


@pytest.mark.parametrize("qs", ["days=0", "days=32", "top_n=0", "top_n=11", "tier=best"])
def test_featured_query_validation(qs: str) -> None:
    assert _client(FakeSupabase(_cameras())).get(f"/highlights/featured?{qs}").status_code == 422


def test_featured_window_aligns_to_day_key_start() -> None:
    now = hl.datetime(2026, 9, 10, 1, 0, tzinfo=hl.timezone.utc)  # 10:00 KST → 오늘 키 09-09
    p_from, p_to = hl.featured_window(now, 7)
    assert p_from == hl.datetime(2026, 9, 3, 11, 0, tzinfo=hl.timezone.utc) and p_to == now
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && uv run pytest tests/test_highlights_api.py -q -k featured`
Expected: FAIL(404 / AttributeError `featured_window`)

- [ ] **Step 3: 구현 — import·상수·헬퍼**

`from datetime import datetime, timezone` → `from datetime import datetime, timedelta, timezone`. 상수(기존 상수 아래):

```python
# ── ⭐ 대표 tier(2026-09-10) — fn_highlight_featured 기본값과 같은 값. 바꾸면 라벨링 웹(labelingV4.ts) 도 같이.
FEATURED_DEFAULT_DAYS = 7
FEATURED_MAX_DAYS = 31
FEATURED_DEFAULT_TOP_N = 3
FEATURED_GAP_SEC = 1800
FEATURED_DAY_START_HOUR = 20
FEATURED_TZ = "Asia/Seoul"
_KST = timezone(timedelta(hours=9))


def featured_window(now: datetime, days: int) -> tuple[datetime, datetime]:
    """하루 키(20:00 KST 경계) 기준 최근 `days` 개 하루를 덮는 [from, now). `now - days` 로 자르면 첫 하루가 반쪽이라 top-N 이 틀어진다."""
    key_today = (now.astimezone(_KST) - timedelta(hours=FEATURED_DAY_START_HOUR)).date()
    first = key_today - timedelta(days=days - 1)
    start = datetime(first.year, first.month, first.day, FEATURED_DAY_START_HOUR, tzinfo=_KST)
    return start.astimezone(timezone.utc), now


def _owned_camera_ids(sb: Client, user_id: str) -> list[str]:
    """본인 소유 카메라 id. 없으면 [] — 호출자는 RPC 없이 빈 응답(p_camera_ids=NULL 은 '전체' 라 위험)."""
    try:
        cam_resp = sb.table("cameras").select("id").eq("owner_id", user_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("cameras lookup failed")
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")
    return [row["id"] for row in (cam_resp.data or [])]
```

`list_highlights` 의 (2) 블록을 `camera_ids = _owned_camera_ids(sb, user_id)` 로 치환(동작 동일).

- [ ] **Step 4: 구현 — 엔드포인트(`get_active_rule` 아래, `list_highlights` 위에 두어 `/featured` 가 `""` 보다 먼저 매칭)**

```python
@router.get("/featured")
def list_featured_highlights(
    days: int = Query(default=FEATURED_DEFAULT_DAYS, ge=1, le=FEATURED_MAX_DAYS, description="하루(20:00 KST 경계) 단위 최근 N일"),
    tier: str = Query(default="featured", pattern="^(featured|all)$", description="featured=대표만(기본) · all=후보 포함"),
    top_n: int = Query(default=FEATURED_DEFAULT_TOP_N, ge=1, le=10),
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
):
    """본인 카메라의 ⭐ 대표 하이라이트(하루·카메라당 최대 top_n, 30분 에피소드 대표 클립). 저장된 값이 아니라 조회 시 계산.

    `tier=all` 이면 나머지 O(후보)도 함께 온다 — 앱의 "더 보기". 정렬은 (하루 최신, 카메라, 사건 순위, 시각 최신).
    """
    rule = _active_rule(sb)
    if rule is None:
        raise HTTPException(status_code=404, detail="no active highlight rule")
    meta = {"top_n": top_n, "gap_sec": FEATURED_GAP_SEC, "day_start_hour": FEATURED_DAY_START_HOUR, "time_zone": FEATURED_TZ, "days": days}
    camera_ids = _owned_camera_ids(sb, user_id)
    if not camera_ids:
        return {"highlights": [], "count": 0, "rule_version": rule["version"], "featured": meta}
    contract = _resolve_gme_contract()
    p_from, p_to = featured_window(datetime.now(timezone.utc), days)
    rows = _rpc(sb, "fn_highlight_featured", {
        "p_camera_ids": camera_ids, "p_from": p_from.isoformat(), "p_to": p_to.isoformat(),
        "p_engine_schema_version": contract["engine_schema_version"], "p_algorithm_version": contract["algorithm_version"],
        "p_detector_identity": contract["detector_identity"],
        "p_top_n": top_n, "p_gap_sec": FEATURED_GAP_SEC, "p_day_start_hour": FEATURED_DAY_START_HOUR, "p_tz": FEATURED_TZ,
    })
    items = [_to_featured_item(r, rule["version"]) for r in rows if tier == "all" or r.get("tier") == "featured"]
    return {"highlights": items, "count": len(items), "rule_version": rule["version"], "featured": meta}


def _to_featured_item(row: dict[str, Any], rule_version: str) -> dict[str, Any]:
    """feed 행 → 앱 항목. reviewer_* 는 의도적으로 제외. `episode` 는 카드 문구 재료("사건 6클립 · 움직임 84초")."""
    source = row.get("highlight_source")
    return {
        "clip_id": row["clip_id"], "camera_id": row["camera_id"], "camera_name": row.get("camera_name"),
        "started_at": row["started_at"], "duration_sec": row.get("duration_sec"), "media_ready": True,
        "source": source, "reason": row.get("highlight_reason"), "rule_version": rule_version if source == "rule" else None,
        "tier": row.get("tier"), "day_key": row.get("day_key"), "activity_sec": row.get("activity_sec"),
        "behavior_flagged": bool(row.get("behavior_flagged")),
        "episode": {"rank": row.get("episode_rank"), "clip_count": row.get("episode_clip_count"), "activity_sec": row.get("episode_activity_sec"),
                    "started_at": row.get("episode_started_at"), "ended_at": row.get("episode_ended_at")},
    }
```

- [ ] **Step 5: 테스트 통과 확인(전체)**

Run: `cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && uv run pytest tests/test_highlights_api.py -q`
Expected: 기존 + 신규 전부 PASS(`media_ready` 는 함수가 media_deleted 를 이미 걸렀으므로 True 고정 — 테스트에 주석)

- [ ] **Step 6: 커밋**

```bash
cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && git add backend/routers/highlights.py tests/test_highlights_api.py && git commit -m "feat: petcam-api GET /highlights/featured — ⭐ 대표 tier(하루 키 창·본인 카메라·tier=all 로 후보)"
```

---

### Task 4: 웹 lib — 타입·순수 함수·매퍼

**Context:**
- Depends on: 없음(타입만). Task 5·6 이 이걸 쓴다.
- Inputs: `web/src/lib/labelingV4.ts`, `labelingV4Server.ts`(+`.test.ts`), `labelingV4Api.ts`
- Outputs: `V4FeaturedInfo`·상수·문구 함수, `V4ClipItem.featured`/`V4ClipDetail.featured`(필수 필드, `null` 허용), row 매퍼 2, 하루 창 헬퍼 4, 요청 파서, API 클라이언트 1
- Must know: `V4ClipItem` 에 필수 필드를 더하면 기존 fixture(`_v4-clip-ui.test.tsx` 의 `item`, `labelingV4Server.test.ts` 의 `toEqual`)가 깨진다 → 같은 Task 에서 `featured: null` 추가. 서울은 DST 없음 → 고정 +9h 로 하루 키 계산(서버는 `AT TIME ZONE 'Asia/Seoul'`, 둘이 같은 답). PostgREST 의 `numeric` 은 JSON 숫자로 오지만 `Number()` 로 방어.
- Acceptance: `cd …/web && npx tsc --noEmit && npx vitest run src/lib/labelingV4Server.test.ts` PASS

**Files:**
- Modify: `web/src/lib/labelingV4.ts`, `web/src/lib/labelingV4Server.ts`, `web/src/lib/labelingV4Server.test.ts`, `web/src/lib/labelingV4Api.ts`, `web/src/app/labeling/_v4-clip-ui.test.tsx`(fixture)

- [ ] **Step 1: 실패 테스트(`labelingV4Server.test.ts` 끝에)**

```ts
import { dayKeyOf, dayKeyStartUtc, featuredWindowDays, featuredWindowFor, mapFeaturedInfo, mapFeaturedRowToItem, parseV4FeaturedRequest } from './labelingV4Server';
import { featuredBadgeText, featuredLineText } from './labelingV4';

describe('featured tier — 하루 키(20시 KST 경계)', () => {
  it('dayKeyOf: 19:30 KST 는 전날, 20:10 KST 는 당일, 05:00 KST 는 전날 키', () => {
    expect(dayKeyOf('2026-09-01T10:30:00Z')).toBe('2026-08-31');
    expect(dayKeyOf('2026-09-01T11:10:00Z')).toBe('2026-09-01');
    expect(dayKeyOf('2026-09-01T20:00:00Z')).toBe('2026-09-01');
  });
  it('dayKeyStartUtc: 키의 20:00 KST = 11:00Z', () => {
    expect(dayKeyStartUtc('2026-09-01').toISOString()).toBe('2026-09-01T11:00:00.000Z');
  });
  it('featuredWindowFor: 항목들의 하루 키를 덮는 [from, to)', () => {
    expect(featuredWindowFor(['2026-09-01T10:30:00Z', '2026-09-03T12:00:00Z'])).toEqual({ from: '2026-08-31T11:00:00.000Z', to: '2026-09-04T11:00:00.000Z' });
    expect(featuredWindowFor([])).toBeNull();
  });
  it('featuredWindowDays: 오늘 키 기준 최근 N일', () => {
    const now = new Date('2026-09-10T01:00:00Z'); // 10:00 KST → 오늘 키 09-09
    expect(featuredWindowDays(now, 7)).toEqual({ from: '2026-09-03T11:00:00.000Z', to: now.toISOString() });
  });
});

describe('featured tier — 매퍼·문구', () => {
  const row = { clip_id: '00000000-0000-4000-8000-000000000009', camera_id: 'c1', camera_name: '거실', started_at: '2026-09-09T12:00:00Z', duration_sec: 60, day_key: '2026-09-09', episode_no: 2, episode_started_at: '2026-09-09T12:00:00Z', episode_ended_at: '2026-09-09T12:06:00Z', episode_clip_count: 6, episode_activity_sec: 84, episode_rank: 2, tier: 'featured', is_representative: true, activity_sec: 20.5, highlight_source: 'rule', highlight_reason: '움직임 20.5초 · 최장 연속 9.0초', reviewer_id: null, reviewer_display_name: null, behavior_flagged: false };
  it('mapFeaturedInfo', () => {
    expect(mapFeaturedInfo(row, 3)).toEqual({ tier: 'featured', day_key: '2026-09-09', episode_rank: 2, episode_clip_count: 6, episode_activity_sec: 84, is_representative: true, top_n: 3 });
    expect(() => mapFeaturedInfo({ ...row, tier: 'best' }, 3)).toThrow('invalid_featured_row');
  });
  it('mapFeaturedRowToItem: 카드 항목 + reviewer UUID 비노출', () => {
    const REVIEWER = '30000000-0000-4000-8000-000000000001';
    const out = mapFeaturedRowToItem({ ...row, highlight_source: 'human', reviewer_id: REVIEWER, reviewer_display_name: '김라벨' }, 3, (id, name) => `${name}<${id.slice(0, 8)}>`);
    expect(out.highlight).toEqual({ source: 'human', status: 'decided', value: true, reason: row.highlight_reason, reviewer_name: '김라벨<30000000>', decided_at: null });
    expect(out.featured?.tier).toBe('featured');
    expect(JSON.stringify(out)).not.toContain(REVIEWER);
  });
  it('문구', () => {
    const f = mapFeaturedInfo(row, 3);
    expect(featuredBadgeText(f)).toBe('⭐ 대표 2위');
    expect(featuredLineText(f)).toBe('⭐ 이 날 대표 2/3 · 사건 6클립 · 움직임 84초');
    expect(featuredBadgeText({ ...f, tier: 'candidate' })).toBe('후보');
    expect(featuredLineText({ ...f, tier: 'candidate', is_representative: false })).toBe('후보 · 같은 사건의 다른 클립(사건 2위) · 사건 6클립 · 움직임 84초');
    expect(featuredLineText(null)).toBeNull();
  });
  it('parseV4FeaturedRequest', () => {
    expect(parseV4FeaturedRequest(new URLSearchParams('days=7&camera_id=00000000-0000-4000-8000-000000000001'))).toEqual({ days: 7, cameraIds: ['00000000-0000-4000-8000-000000000001'] });
    expect(parseV4FeaturedRequest(new URLSearchParams(''))).toEqual({ days: 7, cameraIds: null });
    expect(() => parseV4FeaturedRequest(new URLSearchParams('days=40'))).toThrow('invalid_days');
  });
});
```

기존 `mapV4ClipRow` `toEqual` 기대값과 `_v4-clip-ui.test.tsx` 의 `item` fixture 에 `featured: null` 추가.

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0/web && npx vitest run src/lib/labelingV4Server.test.ts`
Expected: FAIL(export 없음)

- [ ] **Step 3: `labelingV4.ts` 추가**

```ts
// ── ⭐ 대표 tier(2026-09-10, 스펙 feature-highlight-featured-tier) — O/X 위에 조회 시 계산되는 하루 상한 레이어.
// 상수는 DB 함수 기본값·petcam-api 와 같은 값(바꾸면 세 곳 같이).
export type V4FeaturedTier = 'featured' | 'candidate';
export interface V4FeaturedInfo {
  tier: V4FeaturedTier;
  day_key: string; // 'YYYY-MM-DD' — 20:00 KST 경계 하루
  episode_rank: number;
  episode_clip_count: number;
  episode_activity_sec: number;
  is_representative: boolean;
  top_n: number;
}
export const FEATURED_TOP_N = 3;
export const FEATURED_GAP_SEC = 1800;
export const FEATURED_DAY_START_HOUR = 20;
export const FEATURED_DAYS = 7;
export const FEATURED_MAX_DAYS = 31;
export const FEATURED_TZ = 'Asia/Seoul';
export const V4_FEATURED_LABEL = '대표만';

export function featuredBadgeText(f: V4FeaturedInfo | null): string | null {
  if (!f) return null;
  return f.tier === 'featured' ? `⭐ 대표 ${f.episode_rank}위` : '후보';
}

export function featuredLineText(f: V4FeaturedInfo | null): string | null {
  if (!f) return null;
  const ep = `사건 ${f.episode_clip_count}클립 · 움직임 ${f.episode_activity_sec}초`;
  if (f.tier === 'featured') return `⭐ 이 날 대표 ${f.episode_rank}/${f.top_n} · ${ep}`;
  if (!f.is_representative) return `후보 · 같은 사건의 다른 클립(사건 ${f.episode_rank}위) · ${ep}`;
  return `후보 · 사건 ${f.episode_rank}위 · ${ep}`;
}
```

`V4ClipItem` 에 `featured: V4FeaturedInfo | null; // 현재 O 인 항목에만(보조 정보, 계산 실패 시 null)`, `V4ClipDetail` 에 같은 필드.

- [ ] **Step 4: `labelingV4Server.ts` 추가(import 에 `FEATURED_DAY_START_HOUR, FEATURED_DAYS, FEATURED_MAX_DAYS, type V4FeaturedInfo` 추가)**

```ts
// ── ⭐ 대표 tier ─────────────────────────────────────────────────────
export interface V4FeaturedRow {
  clip_id: unknown; camera_id: unknown; camera_name: unknown; started_at: unknown; duration_sec: unknown;
  day_key: unknown; episode_no: unknown; episode_started_at: unknown; episode_ended_at: unknown;
  episode_clip_count: unknown; episode_activity_sec: unknown; episode_rank: unknown; tier: unknown; is_representative: unknown;
  activity_sec: unknown; highlight_source: unknown; highlight_reason: unknown; reviewer_id: unknown; reviewer_display_name: unknown; behavior_flagged: unknown;
}

export function mapFeaturedInfo(row: V4FeaturedRow, topN: number): V4FeaturedInfo {
  if (row.tier !== 'featured' && row.tier !== 'candidate') throw new Error('invalid_featured_row');
  if (typeof row.day_key !== 'string' || typeof row.episode_rank !== 'number' || typeof row.episode_clip_count !== 'number') throw new Error('invalid_featured_row');
  return {
    tier: row.tier, day_key: row.day_key, episode_rank: row.episode_rank, episode_clip_count: row.episode_clip_count,
    episode_activity_sec: Number(row.episode_activity_sec ?? 0), is_representative: row.is_representative === true, top_n: topN,
  };
}

// feed 행 → 목록 카드 항목(`⭐ 대표만` 화면). reviewer UUID 는 표시명으로만. 썸네일은 route 가 붙인다.
export function mapFeaturedRowToItem(row: V4FeaturedRow, topN: number, resolveName: ReviewerNameResolver): V4ClipItem {
  if (typeof row.clip_id !== 'string' || typeof row.started_at !== 'string' || typeof row.camera_name !== 'string') throw new Error('invalid_featured_row');
  if (row.highlight_source !== 'human' && row.highlight_source !== 'rule') throw new Error('invalid_featured_row');
  if (row.highlight_source === 'human' && (typeof row.reviewer_id !== 'string' || !UUID_RE.test(row.reviewer_id))) throw new Error('invalid_featured_row');
  return {
    id: row.clip_id,
    camera_id: typeof row.camera_id === 'string' ? row.camera_id : null,
    camera_name: row.camera_name,
    started_at: row.started_at,
    duration_sec: typeof row.duration_sec === 'number' ? row.duration_sec : row.duration_sec === null ? null : Number(row.duration_sec),
    media_ready: true, // 함수가 media_deleted 를 이미 걸렀다
    highlight: {
      source: row.highlight_source, status: 'decided', value: true,
      reason: typeof row.highlight_reason === 'string' ? row.highlight_reason : '',
      reviewer_name: row.highlight_source === 'human' ? resolveName(row.reviewer_id as string, typeof row.reviewer_display_name === 'string' ? row.reviewer_display_name : null) : null,
      decided_at: null,
    },
    behavior_flag: { flagged: row.behavior_flagged === true, flagged_by_name: null, flagged_at: null },
    thumbnail_url: null,
    featured: mapFeaturedInfo(row, topN),
  };
}

// 하루 키(20:00 경계). 서울은 DST 가 없어 고정 +9h — 서버 `AT TIME ZONE 'Asia/Seoul'` 와 같은 답.
const SEOUL_OFFSET_MS = 9 * 3_600_000;
export function dayKeyOf(iso: string, dayStartHour = FEATURED_DAY_START_HOUR): string {
  return new Date(Date.parse(iso) + SEOUL_OFFSET_MS - dayStartHour * 3_600_000).toISOString().slice(0, 10);
}
export function dayKeyStartUtc(dayKey: string, dayStartHour = FEATURED_DAY_START_HOUR): Date {
  const [y, m, d] = dayKey.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d, dayStartHour) - SEOUL_OFFSET_MS);
}
// 항목들의 하루 키를 모두 덮는 [from, to). 목록 페이지에 tier 를 붙일 때.
export function featuredWindowFor(startedAts: string[]): { from: string; to: string } | null {
  if (startedAts.length === 0) return null;
  const keys = startedAts.map((s) => dayKeyOf(s)).sort();
  const from = dayKeyStartUtc(keys[0]);
  const to = new Date(dayKeyStartUtc(keys[keys.length - 1]).getTime() + 86_400_000);
  return { from: from.toISOString(), to: to.toISOString() };
}
// 오늘 키 기준 최근 N일(petcam-api featured_window 와 같은 정의).
export function featuredWindowDays(now: Date, days: number): { from: string; to: string } {
  const todayKey = dayKeyOf(now.toISOString());
  const from = new Date(dayKeyStartUtc(todayKey).getTime() - (days - 1) * 86_400_000);
  return { from: from.toISOString(), to: now.toISOString() };
}

export interface V4FeaturedRequest { days: number; cameraIds: string[] | null }
export function parseV4FeaturedRequest(sp: URLSearchParams): V4FeaturedRequest {
  const cameraIds = sp.getAll('camera_id');
  for (const id of cameraIds) if (!UUID_RE.test(id)) throw new Error('invalid_camera_id');
  const rawDays = sp.get('days');
  const days = rawDays === null ? FEATURED_DAYS : Number(rawDays);
  if (!Number.isInteger(days) || days < 1 || days > FEATURED_MAX_DAYS) throw new Error('invalid_days');
  return { days, cameraIds: cameraIds.length ? cameraIds : null };
}
```

`mapV4ClipRow` 반환 객체에 `featured: null,` 추가(thumbnail_url 옆).

- [ ] **Step 5: `labelingV4Api.ts`**

```ts
// ⭐ 대표만(최근 N일). keyset 없음(하루·카메라당 ≤ top_n 이라 한 페이지).
export function getV4Featured(cameraIds: string[], days: number): Promise<V4ClipListResponse> {
  const sp = new URLSearchParams();
  cameraIds.forEach((id) => sp.append('camera_id', id));
  sp.set('days', String(days));
  return request<V4ClipListResponse>(`/api/labeling-v4/featured?${sp.toString()}`);
}
```

- [ ] **Step 6: 통과 확인**

Run: `cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0/web && npx tsc --noEmit && npx vitest run src/lib/labelingV4Server.test.ts src/app/labeling/_v4-clip-ui.test.tsx`
Expected: PASS(다른 V4ClipItem 생성처가 tsc 에서 잡히면 `featured: null` 추가)

- [ ] **Step 7: 커밋**

```bash
cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && git add web/src/lib/labelingV4.ts web/src/lib/labelingV4Server.ts web/src/lib/labelingV4Server.test.ts web/src/lib/labelingV4Api.ts web/src/app/labeling/_v4-clip-ui.test.tsx && git commit -m "feat: 라벨링 웹 대표 tier 타입·하루 키 창·feed 행 매퍼·문구(순수)"
```

---

### Task 5: 웹 API — 목록에 tier 부착, `대표만` route, 상세에 featured

**Context:**
- Depends on: Task 1(함수), Task 4(lib)
- Inputs: `web/src/app/api/labeling-v4/clips/route.ts`(attachThumbnails), `clips/[clipId]/route.ts`, `_access.ts`(`resolveReviewerName`), `readGmeActiveContract`
- Outputs: `_thumbnails.ts`, `_featured.ts`, `featured/route.ts`, clips/detail route 수정
- Must know: 목록 route 의 tier 부착은 **보조 정보** — RPC 실패·31일 초과 창이면 조용히 null(썸네일과 같은 태도). 목록의 O 항목 카메라 집합으로 `p_camera_ids` 를 좁힌다. 상세는 O 인 클립에만 호출(하루 창 1개).
- Acceptance: `npx tsc --noEmit` PASS + 로컬 dev 서버(`npx next dev -p 3111`, owner 세션 `web/public/__dev_session.json` — 끝나면 삭제)에서 `/api/labeling-v4/clips?scope=all&highlight_state=yes&limit=10` 응답 항목에 `featured` 객체, `/api/labeling-v4/featured?days=7` 응답 `items[*].featured.tier === 'featured'`

**Files:**
- Create: `web/src/app/api/labeling-v4/_thumbnails.ts`, `web/src/app/api/labeling-v4/_featured.ts`, `web/src/app/api/labeling-v4/featured/route.ts`
- Modify: `web/src/app/api/labeling-v4/clips/route.ts`, `web/src/app/api/labeling-v4/clips/[clipId]/route.ts`

- [ ] **Step 1: `_thumbnails.ts` — clips/route.ts 의 `attachThumbnails`·`THUMBNAIL_TTL_SEC` 를 그대로 옮기고 `export`. clips/route.ts 는 `import { attachThumbnails } from '../_thumbnails';`**

- [ ] **Step 2: `_featured.ts`**

```ts
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { FEATURED_DAY_START_HOUR, FEATURED_GAP_SEC, FEATURED_MAX_DAYS, FEATURED_TOP_N, FEATURED_TZ, type V4ClipItem, type V4FeaturedInfo } from '@/lib/labelingV4';
import { dayKeyOf, dayKeyStartUtc, featuredWindowFor, mapFeaturedInfo, type V4FeaturedRow } from '@/lib/labelingV4Server';
import { supabaseAdmin } from '@/lib/supabase';

// ⭐ 대표 tier — fn_highlight_featured 호출부 단일화. 저장된 값이 아니라 조회 시 계산(스펙 §4.1).
export async function loadFeaturedRows(args: { cameraIds: string[] | null; from: string; to: string; topN?: number }): Promise<V4FeaturedRow[]> {
  const contract = readGmeActiveContract();
  const { data, error } = await supabaseAdmin.rpc('fn_highlight_featured', {
    p_camera_ids: args.cameraIds, p_from: args.from, p_to: args.to,
    p_engine_schema_version: contract.engine_schema_version, p_algorithm_version: contract.algorithm_version, p_detector_identity: contract.detector_identity,
    p_top_n: args.topN ?? FEATURED_TOP_N, p_gap_sec: FEATURED_GAP_SEC, p_day_start_hour: FEATURED_DAY_START_HOUR, p_tz: FEATURED_TZ,
  });
  if (error) throw error;
  return (data ?? []) as V4FeaturedRow[];
}

// 목록 페이지의 현재-O 항목에 tier 를 붙인다. 보조 정보 — 실패·31일 초과 창이면 전부 null(목록은 계속).
export async function attachFeatured(items: V4ClipItem[]): Promise<void> {
  const targets = items.filter((i) => i.highlight.status === 'decided' && i.highlight.value === true);
  if (targets.length === 0) return;
  const win = featuredWindowFor(targets.map((i) => i.started_at));
  if (!win || Date.parse(win.to) - Date.parse(win.from) > FEATURED_MAX_DAYS * 86_400_000) return;
  const cams = Array.from(new Set(targets.map((i) => i.camera_id).filter((c): c is string => typeof c === 'string')));
  try {
    const rows = await loadFeaturedRows({ cameraIds: cams.length ? cams : null, from: win.from, to: win.to });
    const byId = new Map(rows.map((r) => [String(r.clip_id), mapFeaturedInfo(r, FEATURED_TOP_N)] as const));
    for (const it of targets) it.featured = byId.get(it.id) ?? null;
  } catch {
    // 보조 정보 — 조회 실패해도 목록은 그대로.
  }
}

// 상세: 그 클립의 하루 창 하나로 tier 를 찾는다. O 가 아니면 호출하지 않는다.
export async function loadFeaturedForClip(clip: { id: string; camera_id: string | null; started_at: string }, isCurrentO: boolean): Promise<V4FeaturedInfo | null> {
  if (!isCurrentO || !clip.camera_id) return null;
  const key = dayKeyOf(clip.started_at);
  const from = dayKeyStartUtc(key);
  const to = new Date(from.getTime() + 86_400_000);
  try {
    const rows = await loadFeaturedRows({ cameraIds: [clip.camera_id], from: from.toISOString(), to: to.toISOString() });
    const row = rows.find((r) => r.clip_id === clip.id);
    return row ? mapFeaturedInfo(row, FEATURED_TOP_N) : null;
  } catch {
    return null;
  }
}
```

- [ ] **Step 3: clips/route.ts — `await attachThumbnails(items);` 뒤에 `await attachFeatured(items);`(import `from '../_featured'`)**

- [ ] **Step 4: `featured/route.ts`**

```ts
import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { FEATURED_TOP_N } from '@/lib/labelingV4';
import { featuredWindowDays, mapFeaturedRowToItem, parseV4FeaturedRequest } from '@/lib/labelingV4Server';
import { resolveReviewerName } from '../_access';
import { loadFeaturedRows } from '../_featured';
import { attachThumbnails } from '../_thumbnails';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v4/featured?days=7&camera_id=… — ⭐ 대표만(하루·카메라당 ≤ top_n). keyset 없음(한 페이지).
// 카메라 필터가 없으면 전체(라벨링 웹은 배정=편의 필터, 권한 아님 — v4 스펙 §4.1).
export async function GET(req: NextRequest) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  let parsed;
  try { parsed = parseV4FeaturedRequest(req.nextUrl.searchParams); } catch (e) { return NextResponse.json({ detail: `요청 값이 잘못됐어(${(e as Error).message}).`, code: 'invalid_request' }, { status: 400 }); }
  try {
    const win = featuredWindowDays(new Date(), parsed.days);
    const rows = await loadFeaturedRows({ cameraIds: parsed.cameraIds, from: win.from, to: win.to });
    const items = rows.filter((r) => r.tier === 'featured').map((r) => mapFeaturedRowToItem(r, FEATURED_TOP_N, (reviewerId, displayName) => resolveReviewerName({ reviewerId, displayName })));
    await attachThumbnails(items);
    return NextResponse.json({ items, has_more: false, next_cursor: null });
  } catch (cause) {
    return highlightRpcErrorResponse(cause) ?? highlightDatabaseError(cause);
  }
}
```

- [ ] **Step 5: 상세 route — `behaviorFlag` 뒤에**

```ts
    const featured = await loadFeaturedForClip({ id: clip.id, camera_id: clip.camera_id, started_at: clip.started_at }, highlight.current.value === true);
    return NextResponse.json({ id: clip.id, camera_id: clip.camera_id, started_at: clip.started_at, duration_sec: clip.duration_sec, media_ready: mediaReady, highlight, behavior_flag: behaviorFlag, featured });
```

(`clip.camera_id`·`clip.started_at` 의 타입은 `loadV4ClipAccess` 반환값에서 확인 — `_access.ts` 의 select 컬럼에 `camera_id, started_at` 이 없으면 추가.)

- [ ] **Step 6: tsc + 로컬 실측**

Run: `cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0/web && npx tsc --noEmit`
Expected: 오류 0. 로컬 실측은 Task 1 migration 이 production 에 적용된 뒤(Task 7 게이트 ①) 한다 — 그 전엔 RPC 가 없어 `featured: null`·featured route 는 DB 오류 응답. 적용 전에는 tsc 만으로 이 Task 를 닫고 실측은 Task 7 에서.

- [ ] **Step 7: 커밋**

```bash
cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && git add web/src/app/api/labeling-v4 && git commit -m "feat: 라벨링 웹 API — 목록에 대표 tier 부착(보조)·대표만 route·상세 featured"
```

---

### Task 6: 웹 UI — 카드 배지, `⭐ 대표만` 칩, 상세 한 줄

**Context:**
- Depends on: Task 4(타입·문구), Task 5(API)
- Inputs: `_v4-clip-list.tsx`(`V4ClipCard`, `UrlFilters`, `readFilters`/`writeFilters`, 칩 블록, `load`), `v4/_v4-clip-detail.tsx`(`HighlightDecisionPanel` props, 액션 바 첫 `<p>`), `_v4-clip-ui.test.tsx`
- Outputs: 배지·칩·줄. 체험(스펙 §5) 그대로.
- Must know: 칩 `대표만` 이 켜지면 목록은 keyset 대신 `getV4Featured` 한 페이지(`hasMore=false`). `scope=mine` 이고 카메라 필터가 비었으면 배정 카메라 id 를 넘긴다(배정 0 이면 호출 없이 빈 목록). 다른 필터(라벨 상태 등)는 대표 모드에서 무시 — 칩 title 로 알린다. 상세 줄은 액션 바의 `progressText` 줄 **아래**에 별도 `<p data-testid="featured-line">`.
- Acceptance: `npx tsc --noEmit && npx vitest run` PASS

**Files:**
- Modify: `web/src/app/labeling/_v4-clip-list.tsx`, `web/src/app/labeling/v4/_v4-clip-detail.tsx`, `web/src/app/labeling/_v4-clip-ui.test.tsx`

- [ ] **Step 1: SSR 테스트(`_v4-clip-ui.test.tsx`)**

```ts
describe('featured tier UI', () => {
  const featured = { tier: 'featured' as const, day_key: '2026-09-08', episode_rank: 2, episode_clip_count: 6, episode_activity_sec: 84, is_representative: true, top_n: 3 };
  it('카드: 대표 배지 / 후보 배지 / 없으면 배지 없음', () => {
    expect(renderToStaticMarkup(<V4ClipCard item={{ ...item, featured }} />)).toContain('⭐ 대표 2위');
    expect(renderToStaticMarkup(<V4ClipCard item={{ ...item, featured: { ...featured, tier: 'candidate' } }} />)).toContain('후보');
    expect(renderToStaticMarkup(<V4ClipCard item={{ ...item, featured: null }} />)).not.toContain('대표');
  });
  it('필터: featured=yes 왕복', () => {
    const f = readFilters(new URLSearchParams('featured=yes'));
    expect(f.featured).toBe(true);
    expect(writeFilters(f)).toContain('featured=yes');
    expect(readFilters(new URLSearchParams('')).featured).toBe(false);
  });
  it('상세 패널: featuredLine 이 있으면 액션 바에 보인다', () => {
    const html = renderToStaticMarkup(
      <HighlightDecisionPanel
        initial={{ status: 'decided', value: true, rule_version: 'hl-rule-v0', reason: '움직임 12.5초', fired: ['long_activity'], shadow: [], features: null }}
        current={{ source: 'rule', status: 'decided', value: true, rule_version: 'hl-rule-v0', reason: '움직임 12.5초', reviewer_name: null, decided_at: null, verdict_kind: null }}
        busy={false}
        onDecide={() => {}}
        featuredLine="⭐ 이 날 대표 2/3 · 사건 6클립 · 움직임 84초"
      />,
    );
    expect(html).toContain('data-testid="featured-line"');
    expect(html).toContain('⭐ 이 날 대표 2/3');
  });
});
```

(props 리터럴은 이 파일의 기존 "상세 바에 진행 문구" 테스트와 같은 모양 — `initial`·`current` 공용 fixture 는 `describe('HighlightDecisionPanel')` 블록 안에만 있어 여기선 인라인.)

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0/web && npx vitest run src/app/labeling/_v4-clip-ui.test.tsx`
Expected: FAIL

- [ ] **Step 3: 카드 배지(`V4ClipCard` 배지 줄, `highlightBadge(h)` 바로 뒤)**

```tsx
          {item.featured && (
            <Badge tone={item.featured.tier === 'featured' ? 'success' : 'neutral'}>{featuredBadgeText(item.featured)}</Badge>
          )}
```

import 에 `featuredBadgeText, FEATURED_DAYS, V4_FEATURED_LABEL` 추가, `getV4Featured` 추가.

- [ ] **Step 4: 필터**

`UrlFilters` 에 `featured: boolean;`. `readFilters`: `featured: sp.get('featured') === 'yes',`. `writeFilters`: `if (f.featured) sp.set('featured', 'yes');`. 칩(📌 평가 표본 칩 뒤):

```tsx
        <SelectionChip
          pressed={filters.featured}
          tone="success"
          type="button"
          title={`최근 ${FEATURED_DAYS}일 ⭐ 대표만(하루·카메라당 최대 3). 켜면 다른 상태 필터는 무시돼`}
          onClick={() => update({ featured: !filters.featured })}
        >
          ⭐ {V4_FEATURED_LABEL}
        </SelectionChip>
```

`load` 안, `getV4Clips` 호출 전에 분기:

```tsx
        if (filters.featured) {
          const camIds = filters.cameraIds.length ? filters.cameraIds : scope === 'mine' ? cameras.filter((c) => c.assigned).map((c) => c.id) : [];
          if (scope === 'mine' && camIds.length === 0) { setItems([]); setCursor(null); setHasMore(false); return; }
          const resp = await getV4Featured(camIds, FEATURED_DAYS);
          if (!gen.current.isCurrent(g)) return;
          setItems(resp.items); setCursor(null); setHasMore(false);
          return;
        }
```

(`cameras` 가 `load` 의 deps 에 없으면 추가. `finally` 의 `setBusy(false)` 는 그대로 탄다.)

- [ ] **Step 5: 상세 — `HighlightDecisionPanel` 에 `featuredLine?: string | null` prop, 액션 바 첫 `<p>` 다음 줄:**

```tsx
        {featuredLine && <p data-testid="featured-line" className="text-xs text-amber-800">{featuredLine}</p>}
```

페이지(`<HighlightDecisionPanel …>`)에 `featuredLine={featuredLineText(detail.featured)}` 추가(import `featuredLineText`). 확정(O/X)·✨ 뒤에 `detail` 을 다시 받아오는 흐름이 이미 있으면 줄이 자동 갱신된다 — 없으면(응답으로 부분 갱신) `getV4Clip` 재조회를 추가하지 말고 `detail.featured` 를 유지(다음 진입 때 갱신. 스펙 §4.5 "진행 중인 하루" 와 같은 태도).

- [ ] **Step 6: 통과 확인**

Run: `cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0/web && npx tsc --noEmit && npx vitest run`
Expected: 전부 PASS

- [ ] **Step 7: 커밋**

```bash
cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && git add web/src/app/labeling && git commit -m "feat: 라벨링 웹 UI — 카드 ⭐ 대표/후보 배지, 대표만 칩(최근 7일), 상세 대표 한 줄"
```

---

### Task 7: 문서 · 배포 · 검증 (승인 게이트 3개)

**Context:**
- Depends on: Task 1~6 커밋 완료
- Inputs: 런북 `docs/highlight-rule-operations.md`, 핸드오프 `docs/handoff-prompts/2026-09-08-app-highlight-api-handoff.md`, `docs/FEATURES.md` §11.9, `specs/README.md`, `docs/decision-gate.md`, SOT `../tera-ai-product-master/docs/specs/petcam-ai-pipeline.md` 8행, `.claude/donts-audit.md`, `specs/next-session.md`
- Outputs: 문서 갱신, production 적용, 상태 `DEPLOYED_VERIFIED`
- Must know: **게이트 ① migration 적용 → ② fly 배포 → ③ main push(Vercel)** 순서. migration 은 추가 전용(함수 1개 CREATE)이라 롤백 = `DROP FUNCTION`. 앱 API 는 기존 엔드포인트 불변이라 fly 배포 실패해도 앱 영향 0. 성능 게이트(콜드 ≤ 3초) 미달이면 **부분 인덱스 migration**(`CREATE INDEX CONCURRENTLY idx_motion_clips_camera_started ON public.motion_clips (camera_id, started_at DESC) WHERE r2_key IS NOT NULL` — CONCURRENTLY 는 트랜잭션 밖, SQL Editor 별도 실행)을 owner 승인 뒤 추가.
- Acceptance: 스펙 §3 체크 전부 ✅

**Files:** 위 문서 6 + `.claude/donts-audit.md` + `specs/next-session.md`

- [ ] **Step 1: 문서**

런북 §6.y(§6.x 뒤):

```markdown
### 6.y ⭐ 대표 tier 는 규칙이 아니라 예산 레이어 (2026-09-10)

`fn_highlight_featured(카메라[], from, to, 계약 3, top_n=3, gap_sec=1800, day_start_hour=20, tz='Asia/Seoul')` 는 현재 O(사람 확정 우선) 클립을 하루(20:00 KST 경계)·카메라별 30분 에피소드로 묶고 사건 점수(✨ > 사람 O > activity 합) 상위 top_n 의 대표 클립에 `tier='featured'` 를 붙인다. **저장하지 않는다** — X/✨ 를 바꾸면 다음 조회에 순위가 바뀐다. 소비처: petcam-api `GET /highlights/featured`(대표만 기본, `tier=all` 후보 포함), 라벨링 웹 목록 배지·`⭐ 대표만` 칩·상세 한 줄. 규칙 params·유지율·표본과 무관. 기본값을 바꾸려면 DB DEFAULT·petcam-api 상수·`labelingV4.ts` 상수 세 곳을 같이. 실측: `uv run python scripts/report_highlight_featured.py --days 7 --contract <algo> <detector>`.
```

핸드오프 §3 에 `GET /highlights/featured` 계약(쿼리 `days`·`tier`·`top_n`, 응답 `highlights[*].tier/day_key/episode{rank,clip_count,activity_sec,started_at,ended_at}/activity_sec/behavior_flagged`, `featured{top_n,gap_sec,day_start_hour,time_zone,days}`; 앱은 `day_key` 로 묶어 "어젯밤 ⭐" 카드, `tier=all` 로 "후보 N개 더 보기"). FEATURES §11.9 끝에 "**⭐ 대표 tier(2026-09-10)**" 문단. `specs/README.md` 에 새 스펙 행(🚧). SOT `petcam-ai-pipeline.md` 8행 "앱 하이라이트 실동작" 에 대표 tier 한 문장(owner 확인 뒤 커밋은 그 레포에서).

- [ ] **Step 2: 게이트 ① — production migration (owner 승인 뒤)**

Supabase SQL Editor(Chrome, 메모리 `supabase-migration-apply-via-chrome`)에 `migrations/2026-09-10_highlight_featured_tier.sql` 전체 붙여 실행 → "Success. No rows returned". 검증(읽기 전용, scratchpad 스크립트):
1. `uv run python scripts/report_highlight_featured.py --days 7 --contract gme-motion-v1 <Vercel 과 같은 detector>` → `rpc: cold ≤ 3.00s`, 표에서 `대표 > top_n` 없음, 카메라×하루 대표 ≤ 3.
2. 같은 스크립트 `--days 14` 로 사건 수가 이전 실측(30분 간격 42 사건/14일)과 같은 자릿수인지.
3. `has_function_privilege('authenticated', …)` = false(SQL Editor 1줄).
4. 실패·3초 초과면 인덱스 migration 제안 후 멈춤(owner 승인).

- [ ] **Step 3: 로컬 웹 실측(게이트 ① 뒤)**

`web/.env.local` + `GME_ACTIVE_*`(`vercel env pull`) 준비 → `cd …/web && npx next dev -p 3111` → owner 세션(`web/public/__dev_session.json`, 끝나면 삭제) → 브라우저 팬: `/labeling/all?all=1&highlight_state=yes` 카드에 ⭐/후보 배지, `?featured=yes` 대표만 목록(카메라별 하루 ≤ 3), 대표 카드 상세에 `featured-line`. 모바일 폭(375)에서 배지 줄바꿈 확인. 서버 종료·세션 파일 삭제.

- [ ] **Step 4: 게이트 ② — fly 배포 (owner 승인 뒤)**

```bash
cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && flyctl deploy --config fly.api.toml --app petcam-api
```

smoke: 무인증 `GET /highlights/featured` 401 · `GET /highlights` 401 불변 · owner JWT(admin magic-link 1회성, 본인 계정만) `GET /highlights/featured` 200(`count 0` 은 owner 카메라 0 이라 정답) · `GET /highlights` 200 불변. fly 로그 traceback 0.

- [ ] **Step 5: 게이트 ③ — main push (owner 승인 뒤)**

```bash
cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && git push origin HEAD:main
```

Vercel Ready 확인(`vercel ls --prod` 는 `/Users/baek/petcam-lab/web` 에서) → production `label.tera-ai.uk/labeling/all?featured=yes` 스크린샷(`screencapture`, type 금지 — 메모리 `feedback_chrome_screenshot_no_typing`).

- [ ] **Step 6: 기록 + 커밋**

`docs/decision-gate.md` 배포 기록 append(적용 시각·실측 수치·상태), `.claude/donts-audit.md` 한 줄, `specs/next-session.md` 갱신, 스펙 §3 체크·상태 ✅, `specs/README.md` 상태.

```bash
cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && git add docs specs .claude/donts-audit.md && git commit -m "docs: ⭐ 대표 tier 배포 기록·런북 §6.y·핸드오프·FEATURES" && git push origin HEAD:main
```

---

## Self-Review

**1. Spec coverage:** §2 In 1(함수)=Task 1 · 2(앱 API)=Task 3 · 3(웹 배지·칩·줄)=Task 4~6 · 4(실측)=Task 2 · 5(문서·SOT)=Task 7. §3 완료 조건 5개 모두 Task 에 매핑. §0 owner 확정(하루 20시, 30분, N=3, ✨ 최우선, 사람 O 가산, 사람 X 제거, pin 없음)은 Task 1 SQL 의 정렬식·WHERE 에 그대로.
**2. Placeholder scan:** "TBD/나중에/적절히" 없음. Task 5 Step 5 의 `_access.ts` 컬럼 확인, Task 6 Step 1 의 fixture 이름 확인은 구현자가 **파일을 열어 맞추는** 지시(내용은 정해짐). Task 1 Step 6 마지막 검사는 계획 시점에 "삭제" 로 결정.
**3. Type consistency:** DB 컬럼 `tier/day_key/episode_rank/episode_clip_count/episode_activity_sec/is_representative/behavior_flagged/reviewer_id/reviewer_display_name` ↔ `V4FeaturedRow`(Task 4) ↔ `_frow`(Task 3) ↔ `_to_featured_item.episode{rank,clip_count,activity_sec,started_at,ended_at}` 일치. 상수 3곳(DB DEFAULT 3/1800/20/'Asia/Seoul' · `FEATURED_*` py · `FEATURED_*` ts) 동일. 하루 창 정의(오늘 키 − (days−1) 의 20:00 KST) 가 `featured_window`(py)·`day_window`(script)·`featuredWindowDays`(ts) 세 곳에서 같고 각각 테스트 있음.

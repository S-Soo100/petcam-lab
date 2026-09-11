# 라벨링 웹 행동 표시 3종(의미있는 행동·쳇바퀴·추락) Implementation Plan

> **구현 방식 (CAOF):** Critical 트랙(production migration 2개 함수 교체 + 앱 API + 라벨링 웹). 이 계획을 task 순서대로 구현한다. Steps use checkbox (`- [ ]`) syntax for tracking.
> production write(migration 적용·fly·main push)는 Task 6 게이트 ①②③에서 owner 승인 뒤에만.

**Goal:** ✨ 버튼 하나(종류 없음)를 **의미있는 행동 · 쳇바퀴 · 추락** 세 개로 넓힌다. 쳇바퀴는 앱 대표에 밤·카메라당 1개만, 추락은 수집용(대표 무관), 앱 화면은 무변경. 스펙 [`specs/feature-behavior-marks.md`](../../../specs/feature-behavior-marks.md) §0 owner 확정(2026-09-11).

**Architecture:** ① 기존 테이블에 `kind` 컬럼을 붙이고 PK 를 `(clip_id, kind)` 로 넓힌다(옛 ✨ 데이터 = `meaningful`). ② RPC get/set 은 종류별 3행을 돌려주고, 옛 4-인자 set·단일 get 은 `meaningful` 위임으로 남긴다(배포 순서 무관). ③ 목록 함수는 **행 중복 방지**(bf 조인 → LATERAL 집계)와 종류 필터만 바꾸고 반환 타입은 유지(CREATE OR REPLACE, wrapper 무변경). 종류 배열은 별도 배치 RPC 로 웹이 붙인다. ④ 대표 함수는 bf 집계 + `p_wheel_cap`(기본 1) + `behavior_kinds` 출력(DROP+CREATE). ⑤ 웹: 버튼 3·단축키 W/D·칩 3·배지. ⑥ API: `behavior_kinds`.

**Tech Stack:** PostgreSQL plpgsql · FastAPI · Next.js 14 · vitest · 일회용 PostgreSQL probe.

**건드리지 않는 것:** 하이라이트 O/X·규칙 params·유지율·표본, 앱(Flutter) 코드, `GET /highlights`.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `migrations/2026-09-11_behavior_marks.sql` (신규) | kind 컬럼·PK·인덱스, `fn_get_motion_clip_behavior_flags`(3행)·`fn_set_motion_clip_behavior_flag`(5-인자)·옛 4-인자/단일 get 위임·`fn_get_motion_clip_behavior_kinds(uuid[])`·목록 14-인자 본문 교체(CREATE OR REPLACE)·`fn_highlight_featured` 교체(`p_wheel_cap`·`behavior_kinds`) |
| `tests/test_behavior_marks_migration.py` (신규) | 정적 계약 |
| `scripts/run_labeling_v4_probe.py` | §15 케이스 |
| `backend/routers/highlights.py` · `tests/test_highlights_api.py` | `behavior_kinds`, `p_wheel_cap` |
| `web/src/lib/labelingV4.ts` | `V4BehaviorKind`·라벨/아이콘·`V4BehaviorMarks`·`V4ClipItem.behavior_kinds`·`V4ClipDetail.behavior_marks`·필터 타입 확장 |
| `web/src/lib/labelingV4Server.ts` (+test) | `mapBehaviorMarks`, 필터 파서 확장, `mapV4ClipRow` 에 `behavior_kinds: []` |
| `web/src/lib/labelingHotkeys.ts` (+test) | `toggle_wheel`(W/ㅈ)·`toggle_fall`(D/ㅇ), 범례 |
| `web/src/lib/labelingV4Api.ts` | `setV4BehaviorMark(clipId, kind, flagged)` |
| `web/src/app/api/labeling-v4/_behavior-flag.ts` | `loadBehaviorMarks`, `setBehaviorMark`, `attachBehaviorKinds` |
| `web/src/app/api/labeling-v4/clips/[clipId]/behavior-flag/route.ts` (+test) | body `{kind?, flagged}` → marks 3종 |
| `web/src/app/api/labeling-v4/clips/route.ts` · `featured/route.ts` · `clips/[clipId]/route.ts` | kinds 부착 / 상세 `behavior_marks` |
| `web/src/app/labeling/v4/_v4-clip-detail.tsx` | `BehaviorMarkButtons`(3), 토글 3, 단축키 |
| `web/src/app/labeling/_v4-clip-list.tsx` (+test) | 칩 3, 배지 3 |
| 문서 | 런북 §6.x, 슬랙 문구, 핸드오프 한 줄, 결정 로그 |

---

### Task 1: migration + 정적 테스트 + probe §15

**Context:**
- Depends on: 없음
- Inputs: `migrations/2026-09-09_labeling_v4_behavior_flags.sql`(테이블·RPC), `2026-09-09_labeling_v4_eval_samples.sql`(14-인자 목록 본문), `2026-09-11_highlight_featured_hour_cap.sql`(대표 함수 v0.1)
- Outputs: migration 1개
- Must know: ⚠️ 표시가 영상당 여러 행이 되면 `LEFT JOIN motion_clip_behavior_flags bf ON bf.clip_id = c.id` 가 **행을 중복**시킨다 → 목록·대표 둘 다 LATERAL 집계로. 목록 14-인자는 반환 타입을 안 바꾸므로 CREATE OR REPLACE(13·12-인자 wrapper 무변경). 대표 함수는 반환 컬럼 추가라 DROP+CREATE. 추락은 정렬·상한 어디에도 안 들어간다(Q2).
- Acceptance: `uv run pytest tests/test_behavior_marks_migration.py -q` PASS · probe `LABELING_V4_PROBE_OK`

**Files:** Create `migrations/2026-09-11_behavior_marks.sql`, `tests/test_behavior_marks_migration.py`; Modify `scripts/run_labeling_v4_probe.py`

- [ ] **Step 1: 정적 테스트**

```python
"""행동 표시 3종 migration 정적 계약."""
from pathlib import Path
import pytest

SQL_PATH = Path(__file__).resolve().parent.parent / "migrations" / "2026-09-11_behavior_marks.sql"
FEAT_SIG = "uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer, integer"


@pytest.fixture()
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


def norm(t: str) -> str:
    return " ".join(t.lower().split())


def test_kind_column_and_pk(sql: str) -> None:
    n = norm(sql)
    assert "add column kind text not null default 'meaningful' check (kind in ('meaningful','wheel','fall'))" in n
    assert "drop constraint motion_clip_behavior_flags_pkey" in n and "add primary key (clip_id, kind)" in n
    assert "create index idx_motion_clip_behavior_flags_kind on public.motion_clip_behavior_flags (kind, flagged_at desc)" in n


def test_rpcs(sql: str) -> None:
    n = norm(sql)
    assert "create function public.fn_get_motion_clip_behavior_flags(p_clip_id uuid) returns table (kind text, flagged boolean, flagged_by uuid, flagged_by_display_name text, flagged_at timestamptz)" in n
    assert "create function public.fn_set_motion_clip_behavior_flag( p_clip_id uuid, p_user_id uuid, p_is_owner boolean, p_kind text, p_flagged boolean )" in n
    assert "create or replace function public.fn_set_motion_clip_behavior_flag( p_clip_id uuid, p_user_id uuid, p_is_owner boolean, p_flagged boolean )" in n  # 옛 4-인자 위임
    assert "and f.kind = 'meaningful'" in n  # 옛 단일 get
    assert "create function public.fn_get_motion_clip_behavior_kinds(p_clip_ids uuid[]) returns table (clip_id uuid, kinds text[])" in n
    assert "p_kind not in ('meaningful','wheel','fall')" in n


def test_list_no_dup_and_kind_filter(sql: str) -> None:
    n = norm(sql)
    assert "create or replace function public.fn_list_labeling_v4_clips( p_viewer_id uuid, p_is_owner boolean, p_scope text, p_camera_ids uuid[], p_label_state text, p_highlight_state text, p_behavior_flag text, p_sample_id text," in n
    assert "p_behavior_flag not in ('yes','meaningful','wheel','fall')" in n
    assert "and (p_behavior_flag = 'yes' or f.kind = p_behavior_flag)" in n
    assert "left join public.motion_clip_behavior_flags bf on bf.clip_id = c.id" not in n
    assert "select (array_agg(f.flagged_by order by f.flagged_at, f.kind))[1] as flagged_by" in n


def test_featured_wheel_cap_and_kinds(sql: str) -> None:
    n = norm(sql)
    assert "drop function public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer);" in n
    assert "p_wheel_cap integer default 1" in n and "behavior_kinds text[]" in n
    assert "bool_or(e.flagged) as ep_flagged" in n and "bool_or(e.wheel) as ep_wheel" in n
    assert "and (not h.ep_wheel or p_wheel_cap is null or h.wheel_rank <= p_wheel_cap)" in n
    assert "'fall'" not in n.split("create function public.fn_highlight_featured")[1].split("order by a.ep_flagged")[0]  # 추락은 점수에 없음
    assert f"grant execute on function public.fn_highlight_featured({FEAT_SIG}) to service_role;" in n
```

- [ ] **Step 2: 실패 확인** — `cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && uv run pytest tests/test_behavior_marks_migration.py -q` → FAIL(파일 없음)

- [ ] **Step 3: migration — 테이블·RPC 부분(파일 앞부분, 손으로)**

```sql
-- 행동 표시 3종 — 의미있는 행동(meaningful) · 쳇바퀴(wheel) · 추락(fall). owner 확정 2026-09-11(스펙 feature-behavior-marks §0).
-- ✨ 하나(종류 없음)를 종류 있는 표시로 넓힌다. 옛 행은 전부 meaningful. 영상당 종류별 1개, 종류끼리 독립.
-- 쳇바퀴 = GME 가 못 잡는 "제자리 활동" 정답 세트, 추락 = 수집용(대표 선정 무관). 하이라이트 O/X·유지율과 무관(런북 §6.x).
-- ⚠️ 영상당 여러 행이 되므로 목록·대표 함수의 bf 조인을 LATERAL 집계로 바꿔 행 중복을 막는다.
BEGIN;

ALTER TABLE public.motion_clip_behavior_flags
  ADD COLUMN kind text NOT NULL DEFAULT 'meaningful' CHECK (kind IN ('meaningful','wheel','fall'));
ALTER TABLE public.motion_clip_behavior_flags DROP CONSTRAINT motion_clip_behavior_flags_pkey;
ALTER TABLE public.motion_clip_behavior_flags ADD PRIMARY KEY (clip_id, kind);
CREATE INDEX idx_motion_clip_behavior_flags_kind ON public.motion_clip_behavior_flags (kind, flagged_at DESC);

-- 종류별 3행(항상). 없는 종류는 flagged=false.
CREATE FUNCTION public.fn_get_motion_clip_behavior_flags(p_clip_id uuid)
RETURNS TABLE (kind text, flagged boolean, flagged_by uuid, flagged_by_display_name text, flagged_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT k.kind, (f.clip_id IS NOT NULL) AS flagged, f.flagged_by, la.display_name, f.flagged_at
    FROM (VALUES ('meaningful'), ('wheel'), ('fall')) AS k(kind)
    LEFT JOIN public.motion_clip_behavior_flags f ON f.clip_id = p_clip_id AND f.kind = k.kind
    LEFT JOIN public.labeler_applications la ON la.user_id = f.flagged_by
   ORDER BY array_position(ARRAY['meaningful','wheel','fall'], k.kind);
$$;

-- 옛 단일 get = meaningful 만(웹 구버전·테스트 호환).
CREATE OR REPLACE FUNCTION public.fn_get_motion_clip_behavior_flag(p_clip_id uuid)
RETURNS TABLE (flagged boolean, flagged_by uuid, flagged_by_display_name text, flagged_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT (f.clip_id IS NOT NULL) AS flagged, f.flagged_by, la.display_name, f.flagged_at
    FROM (SELECT p_clip_id AS id) x
    LEFT JOIN public.motion_clip_behavior_flags f ON f.clip_id = x.id AND f.kind = 'meaningful'
    LEFT JOIN public.labeler_applications la ON la.user_id = f.flagged_by;
$$;

CREATE FUNCTION public.fn_set_motion_clip_behavior_flag(
  p_clip_id uuid, p_user_id uuid, p_is_owner boolean, p_kind text, p_flagged boolean
) RETURNS TABLE (kind text, flagged boolean, flagged_by uuid, flagged_by_display_name text, flagged_at timestamptz)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_existing_by uuid;
BEGIN
  IF p_clip_id IS NULL OR p_user_id IS NULL OR p_flagged IS NULL THEN
    RAISE EXCEPTION 'invalid arguments' USING ERRCODE = '22023';
  END IF;
  IF p_kind IS NULL OR p_kind NOT IN ('meaningful','wheel','fall') THEN
    RAISE EXCEPTION 'invalid kind' USING ERRCODE = '22023';
  END IF;
  IF NOT public.fn_is_motion_clip_production_labeling_eligible(p_clip_id) THEN
    RAISE EXCEPTION 'motion clip not found' USING ERRCODE = 'P0002';
  END IF;
  IF p_flagged THEN
    INSERT INTO public.motion_clip_behavior_flags (clip_id, kind, flagged_by)
    VALUES (p_clip_id, p_kind, p_user_id)
    ON CONFLICT (clip_id, kind) DO NOTHING;  -- 첫 체크한 사람 유지(멱등)
  ELSE
    SELECT f.flagged_by INTO v_existing_by FROM public.motion_clip_behavior_flags f WHERE f.clip_id = p_clip_id AND f.kind = p_kind;
    IF v_existing_by IS NOT NULL AND v_existing_by <> p_user_id AND NOT coalesce(p_is_owner, false) THEN
      RAISE EXCEPTION 'only the flagger or owner can unflag' USING ERRCODE = 'PT403';
    END IF;
    DELETE FROM public.motion_clip_behavior_flags f WHERE f.clip_id = p_clip_id AND f.kind = p_kind;
  END IF;
  RETURN QUERY SELECT * FROM public.fn_get_motion_clip_behavior_flags(p_clip_id);
END $$;

-- 옛 4-인자 set = meaningful 위임(반환 모양은 옛 그대로 1행).
CREATE OR REPLACE FUNCTION public.fn_set_motion_clip_behavior_flag(
  p_clip_id uuid, p_user_id uuid, p_is_owner boolean, p_flagged boolean
) RETURNS TABLE (flagged boolean, flagged_by uuid, flagged_by_display_name text, flagged_at timestamptz)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
  SELECT r.flagged, r.flagged_by, r.flagged_by_display_name, r.flagged_at
    FROM public.fn_set_motion_clip_behavior_flag(p_clip_id, p_user_id, p_is_owner, 'meaningful', p_flagged) r
   WHERE r.kind = 'meaningful';
$$;

-- 목록 카드 배지용 배치 조회(웹이 페이지 항목 id 로 한 번).
CREATE FUNCTION public.fn_get_motion_clip_behavior_kinds(p_clip_ids uuid[])
RETURNS TABLE (clip_id uuid, kinds text[])
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT f.clip_id, array_agg(f.kind ORDER BY array_position(ARRAY['meaningful','wheel','fall'], f.kind)) AS kinds
    FROM public.motion_clip_behavior_flags f
   WHERE f.clip_id = ANY (p_clip_ids)
   GROUP BY f.clip_id;
$$;

REVOKE ALL ON FUNCTION public.fn_get_motion_clip_behavior_flags(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_motion_clip_behavior_flags(uuid) TO service_role;
REVOKE ALL ON FUNCTION public.fn_set_motion_clip_behavior_flag(uuid, uuid, boolean, text, boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_set_motion_clip_behavior_flag(uuid, uuid, boolean, text, boolean) TO service_role;
REVOKE ALL ON FUNCTION public.fn_get_motion_clip_behavior_kinds(uuid[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_motion_clip_behavior_kinds(uuid[]) TO service_role;
```

- [ ] **Step 4: migration — 목록 14-인자 본문 교체(프로그램 변환, 이전 eval_samples 때와 같은 수법)**

scratchpad 생성기 `gen_behavior_marks_list.py`: `2026-09-09_labeling_v4_eval_samples.sql` 에서 `CREATE FUNCTION public.fn_list_labeling_v4_clips(` ~ 그 함수의 `END $$;` 까지 잘라 아래 4곳을 치환(각 치환은 정확히 1회 매칭이어야 함 — `assert src.count(old) == 1`), `CREATE FUNCTION` → `CREATE OR REPLACE FUNCTION` 으로 바꿔 migration 파일에 이어 붙인다.

```python
REPL = [
    ("  IF p_behavior_flag IS NOT NULL AND p_behavior_flag NOT IN ('yes') THEN",
     "  IF p_behavior_flag IS NOT NULL AND p_behavior_flag NOT IN ('yes','meaningful','wheel','fall') THEN"),
    ("                OR EXISTS (SELECT 1 FROM public.motion_clip_behavior_flags f WHERE f.clip_id = c.id))",
     "                OR EXISTS (SELECT 1 FROM public.motion_clip_behavior_flags f WHERE f.clip_id = c.id\n                             AND (p_behavior_flag = 'yes' OR f.kind = p_behavior_flag)))"),
    ("        LEFT JOIN public.motion_clip_behavior_flags bf ON bf.clip_id = c.id\n        LEFT JOIN public.labeler_applications bla ON bla.user_id = bf.flagged_by\n",
     "        -- 표시가 영상당 여러 행(종류별)이라 집계로 1행 — 첫 표시(가장 이른 flagged_at)의 사람·시각.\n"
     "        LEFT JOIN LATERAL (\n"
     "          SELECT (array_agg(f.flagged_by ORDER BY f.flagged_at, f.kind))[1] AS flagged_by,\n"
     "                 min(f.flagged_at) AS flagged_at\n"
     "            FROM public.motion_clip_behavior_flags f WHERE f.clip_id = c.id\n"
     "        ) bf ON true\n"
     "        LEFT JOIN public.labeler_applications bla ON bla.user_id = bf.flagged_by\n"),
    ("CREATE FUNCTION public.fn_list_labeling_v4_clips(", "CREATE OR REPLACE FUNCTION public.fn_list_labeling_v4_clips("),
]
```

(`behavior_flagged := v_row.bf_by IS NOT NULL` 등 출력 줄은 그대로 — 집계 결과의 첫 사람으로 동작.)

- [ ] **Step 5: migration — 대표 함수 교체(v0.1 파일을 베이스로 아래만 다름)**

```sql
DROP FUNCTION public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer);

CREATE FUNCTION public.fn_highlight_featured(
  p_camera_ids uuid[], p_from timestamptz, p_to timestamptz,
  p_engine_schema_version text, p_algorithm_version text, p_detector_identity text,
  p_top_n integer DEFAULT NULL, p_gap_sec integer DEFAULT 600, p_day_start_hour integer DEFAULT 20,
  p_tz text DEFAULT 'Asia/Seoul', p_hour_cap integer DEFAULT 3,
  p_wheel_cap integer DEFAULT 1            -- 쳇바퀴 사건 밤·카메라당 대표 상한(NULL=없음). owner Q1
) RETURNS TABLE (
  … v0.1 과 동일 21컬럼 …,
  behavior_kinds text[]                    -- 마지막에 추가
)
…
  IF p_wheel_cap IS NOT NULL AND (p_wheel_cap < 1 OR p_wheel_cap > 10) THEN
    RAISE EXCEPTION 'invalid wheel_cap (1..10 or null)' USING ERRCODE = '22023';
  END IF;
…
  -- base: bf 조인을 집계로. flagged = 의미있는 행동 또는 쳇바퀴(정렬용). wheel = 쳇바퀴. 추락(fall)은 정렬·상한 어디에도 안 들어감(수집용, Q2).
           (bf.kinds && ARRAY['meaningful','wheel']) AS flagged,
           ('wheel' = ANY (bf.kinds)) AS wheel,
           coalesce(bf.kinds, '{}'::text[]) AS kinds
      …
      LEFT JOIN LATERAL (
        SELECT array_agg(f.kind ORDER BY array_position(ARRAY['meaningful','wheel','fall'], f.kind)) AS kinds
          FROM public.motion_clip_behavior_flags f WHERE f.clip_id = c.id
      ) bf ON true
…
  agg: … bool_or(e.flagged) AS ep_flagged, bool_or(e.wheel) AS ep_wheel, bool_or(e.human_verdict IS TRUE) AS ep_human_o
  ranked: (정렬 v0.1 그대로: ep_flagged DESC, ep_human_o DESC, ep_activity DESC, ep_start DESC)
  hour_ranked: v0.1 그대로 + 쳇바퀴 순위
           row_number() OVER (PARTITION BY r.camera_id, r.day_key, r.ep_wheel ORDER BY r.ep_rank)::integer AS wheel_rank
  최종 SELECT: tier 조건에 한 줄 추가
         CASE WHEN h.rep_clip_id = e.clip_id
                   AND (p_top_n IS NULL OR h.ep_rank <= p_top_n)
                   AND (p_hour_cap IS NULL OR h.hour_rank <= p_hour_cap)
                   AND (NOT h.ep_wheel OR p_wheel_cap IS NULL OR h.wheel_rank <= p_wheel_cap)
              THEN 'featured' ELSE 'candidate' END,
         …, e.flagged, e.kinds
REVOKE/GRANT 는 12-타입 시그니처로.
COMMIT;
```

> 주의: `wheel_rank` 는 `PARTITION BY … r.ep_wheel` 이라 쳇바퀴 아닌 사건도 번호가 붙지만 tier 조건이 `NOT h.ep_wheel OR …` 로 무시한다.

- [ ] **Step 6: probe §15 (§14 뒤, 마지막)**

```python
            # 15) 행동 표시 3종: get 3행 · set(kind) · 옛 4-인자 위임 · 목록 중복 없음·종류 필터 · 대표 쳇바퀴 상한 1 · 추락은 정렬 무관 · 권한
            expect("marks-get-3", q(f"select 'n|'||count(*)::text from public.fn_get_motion_clip_behavior_flags('{FEAT['h1']}');"), n="3")
            require_ok(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['h1']}','{LABELER}',false,'wheel',true);"), "mark-wheel-h1")
            require_ok(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['h2']}','{LABELER}',false,'wheel',true);"), "mark-wheel-h2")
            require_ok(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['h2']}','{LABELER}',false,'fall',true);"), "mark-fall-h2")
            require_ok(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['h3']}','{LABELER}',false,'fall',true);"), "mark-fall-h3")
            require_sqlstate(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['h1']}','{LABELER}',false,'jump',true);"), "mark-bad-kind", "22023")
            expect("marks-kinds-h2", q(f"select 'k|'||array_to_string(kinds, ',') from public.fn_get_motion_clip_behavior_kinds(array['{FEAT['h2']}']::uuid[]);"), k="wheel,fall")
            # 옛 4-인자 set·단일 get 은 meaningful 만 본다(b_flag 는 §14 에서 meaningful)
            expect("legacy-get", q(f"select 'f|'||flagged::text from public.fn_get_motion_clip_behavior_flag('{FEAT['h2']}');"), f="false")
            expect("legacy-get-b", q(f"select 'f|'||flagged::text from public.fn_get_motion_clip_behavior_flag('{FEAT['b_flag']}');"), f="true")
            # 목록: h2 는 표시 2개지만 1행 · 종류 필터
            wheel_ids = require_ok(sql(db, f"select clip_id from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, 'wheel', null, '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50);"), "list-wheel").splitlines()
            if sorted(wheel_ids) != sorted([FEAT['h1'], FEAT['h2']]):
                raise ProbeError(f"list-wheel: {wheel_ids}")
            any_ids = require_ok(sql(db, f"select clip_id from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, 'yes', null, '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50);"), "list-any").splitlines()
            if len(any_ids) != len(set(any_ids)) or set(any_ids) != {FEAT['b_flag'], FEAT['h1'], FEAT['h2'], FEAT['h3']}:
                raise ProbeError(f"list-any dup/set: {any_ids}")
            require_sqlstate(sql(db, f"select * from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, 'jump', null, '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50);"), "list-bad-kind", "22023")
            # 대표: 쳇바퀴 h1·h2 는 flagged 라 b_flag 다음 순위(2·3위, 둘 다 activity 로 정렬 h1 14 > h2 13) → wheel_cap 1 이라 h1 featured, h2 candidate.
            #       추락 h3 는 정렬에 안 들어가 §14 그대로(21시 4번째 → candidate). 출력 kinds.
            feat2 = feat_call.replace(chr(39) + 'Asia/Seoul' + chr(39) + ', 3', chr(39) + 'Asia/Seoul' + chr(39) + ', 3, 1')
            got2 = require_ok(sql(db, f"select clip_id||'|'||tier||'|'||episode_rank||'|'||coalesce(array_to_string(behavior_kinds, '+'), '-') from {feat2} where clip_id in ('{FEAT['h1']}','{FEAT['h2']}','{FEAT['h3']}') order by episode_rank;"), "featured-marks").splitlines()
            want2 = [f"{FEAT['h1']}|featured|2|wheel", f"{FEAT['h2']}|candidate|3|wheel+fall", f"{FEAT['h3']}|candidate|6|fall"]
            if got2 != want2:
                raise ProbeError(f"featured-marks: got {got2} want {want2}")
            expect("featured-wheel-cap-null", q(f"select 'tier|'||tier from {feat2.replace(', 3, 1)', ', 3, null)')} where clip_id = '{FEAT['h2']}';"), tier="featured")
            expect("marks-privs", q("select 'ok|'||(not has_function_privilege('authenticated', 'public.fn_set_motion_clip_behavior_flag(uuid,uuid,boolean,text,boolean)', 'EXECUTE'))::text;"), ok="true")
```

(§14 의 `c` 사람 O 확정이 먼저 있으므로 h1·h2 순위: b_flag 1 · c(사람 O) 2 · h1 3 · h2 4 — 실행해 보고 `want2` 의 순위 숫자를 실제 정렬에 맞춘다. 합격 기준(쳇바퀴 2개 중 1개만 featured·추락은 tier 무변화·kinds 문자열)은 바꾸지 않는다.)

- [ ] **Step 7: 실행·커밋** — 정적 테스트 PASS, probe OK → `git commit -m "feat: 행동 표시 3종 migration(kind·PK·RPC·목록 집계·대표 쳇바퀴 상한) + probe §15"`

---

### Task 2: petcam-api `behavior_kinds` + `p_wheel_cap`

- [ ] `FEATURED_WHEEL_CAP = 1` 상수, RPC 인자 `p_wheel_cap`, meta `wheel_cap`, `_to_featured_item` 에 `"behavior_kinds": list(row.get("behavior_kinds") or [])`.
- [ ] 테스트: `_frow` 에 `behavior_kinds: ["wheel"]`, `test_featured_default…` 에 `item["behavior_kinds"] == ["wheel"]`, meta 에 `wheel_cap: 1`, params 에 `p_wheel_cap == 1`.
- [ ] `uv run pytest tests/test_highlights_api.py -q` PASS → 커밋.

---

### Task 3: 웹 lib·API

- [ ] `labelingV4.ts`

```ts
export type V4BehaviorKind = 'meaningful' | 'wheel' | 'fall';
export const V4_BEHAVIOR_KINDS: V4BehaviorKind[] = ['meaningful', 'wheel', 'fall'];
export const V4_BEHAVIOR_KIND_LABELS: Record<V4BehaviorKind, string> = { meaningful: '의미있는 행동', wheel: '쳇바퀴', fall: '추락' };
export const V4_BEHAVIOR_KIND_ICONS: Record<V4BehaviorKind, string> = { meaningful: '✨', wheel: '🎡', fall: '⚠️' };
export const V4_BEHAVIOR_KIND_HINTS: Record<V4BehaviorKind, string> = {
  meaningful: '물·허물·밥 등 (쳇바퀴·추락이면 그쪽 버튼)', wheel: '쳇바퀴 탐 — 앱 대표는 밤당 1개', fall: '떨어짐 — 수집용, 앱 대표엔 안 감',
};
export type V4BehaviorMarks = Record<V4BehaviorKind, V4BehaviorFlag>;
export type V4BehaviorFlagFilter = 'yes' | V4BehaviorKind;
// V4ClipItem: behavior_kinds: V4BehaviorKind[];   V4ClipDetail: behavior_marks: V4BehaviorMarks (behavior_flag 는 meaningful 로 유지)
```

- [ ] `labelingV4Server.ts`: `mapBehaviorMarks(rows: BehaviorMarkRow[], resolveName)` (3행 → Record, 빠진 종류는 flagged:false), `parseV4ListRequest` 의 behavior_flag 허용값 확장, `mapV4ClipRow` 에 `behavior_kinds: []`, `mapFeaturedRowToItem` 에 `behavior_kinds: Array.isArray(row.behavior_kinds) ? row.behavior_kinds.filter(isKind) : []`.
- [ ] `labelingHotkeys.ts`: `toggle_wheel`(w/W/ㅈ)·`toggle_fall`(d/D/ㅇ), 범례 `… F 의미있는 행동 · W 쳇바퀴 · D 추락`.
- [ ] `labelingV4Api.ts`: `setV4BehaviorMark(clipId, kind, flagged): Promise<V4BehaviorMarks>` (POST `{kind, flagged}`).
- [ ] `_behavior-flag.ts`: `loadBehaviorMarks(clipId)`(RPC `fn_get_motion_clip_behavior_flags`), `setBehaviorMark(clipId, userId, isOwner, kind, flagged)`(5-인자 RPC), `attachBehaviorKinds(items)`(RPC `fn_get_motion_clip_behavior_kinds`, 실패 시 빈 배열). `loadBehaviorFlag` 는 `loadBehaviorMarks(...).meaningful` 로 위임.
- [ ] route `behavior-flag`: body `{ kind?: V4BehaviorKind = 'meaningful', flagged }` → `setBehaviorMark` → marks 3종 응답. 테스트: kind 미지정=meaningful, `wheel`, 잘못된 kind 400, RPC 호출 인자 `p_kind`.
- [ ] `clips/route.ts` · `featured/route.ts`: `await attachBehaviorKinds(items)`. 상세 route: `behavior_marks: await loadBehaviorMarks(clip.id)` + `behavior_flag: marks.meaningful`.
- [ ] tests(`labelingV4Server.test.ts`, `labelingHotkeys.test.ts`, route test) → `npx tsc --noEmit && npx vitest run` PASS → 커밋.

---

### Task 4: 웹 UI

- [ ] `_v4-clip-detail.tsx`: `BehaviorMarkButtons({ marks, busyKind, onToggle(kind, next), gtHref })` — 버튼 3개(PC 한 줄, 모바일 3열, 각 `data-testid="behavior-mark-<kind>"`, `aria-pressed`), 체크되면 `🎡 쳇바퀴 · 김라벨 — 눌러서 해제`, 아니면 `🎡 쳇바퀴` + 작은 힌트. `행동 라벨링 열기 →` 는 어느 종류든 체크됐을 때. 페이지: `busyKind` 상태, `toggleMark(kind, next)` → `setV4BehaviorMark` → `detail.behavior_marks` 갱신. 단축키 `toggle_flag`→meaningful, `toggle_wheel`, `toggle_fall`.
- [ ] `_v4-clip-list.tsx`: 칩 `✨ 의미있는 행동`(behavior_flag=meaningful) `🎡 쳇바퀴`(wheel) `⚠️ 추락`(fall) — 기존 `yes` 칩은 제거(종류 칩 3개로 대체; URL `behavior_flag=yes` 는 여전히 동작). 카드 배지: `item.behavior_kinds.map(k => <Badge tone={k==='fall'?'danger':'warning'}>{icon} {label}</Badge>)`. `behavior_flag.flagged` 기반 옛 배지 제거(중복 방지).
- [ ] `_v4-clip-ui.test.tsx`: 카드 배지 3종·없음, 버튼 3개 렌더·pressed·busy, 칩 3개 URL 왕복. → `npx tsc --noEmit && npx vitest run` PASS → 커밋.

---

### Task 5: 문서

- [ ] 런북 §6.x: 3종·`kind`·쳇바퀴 상한·추락 수집용·`fn_get_motion_clip_behavior_kinds`. 핸드오프 §3: `behavior_kinds` 필드 한 줄(앱 무변경). 슬랙 문구(`docs/handoff-prompts/…` 아님 — 답변으로). 결정 로그 append. → 커밋.

---

### Task 6: 배포 게이트 (owner 승인 각각)

- [ ] **① migration**: SQL Editor(DROP 확인 다이얼로그) → "Success" → 검증: `fn_get_motion_clip_behavior_flags(<기존 ✨ clip>)` 3행에 meaningful=true, `report_highlight_featured.py --days 7` 대표 수 v0.1 과 동일(쳇바퀴 표시 0 이므로), 목록 RPC 행 수 불변(중복 없음), 권한 false/false/true.
- [ ] **② fly** → smoke(무인증 401·owner JWT 200·`behavior_kinds` 키 존재·`featured.wheel_cap 1`).
- [ ] **③ main push** → Vercel Ready → production 상세에서 버튼 3개·W/D 단축키·목록 칩·배지(스크린샷, type 금지). 결정 로그 배포 기록.

---

## Self-Review

**Spec coverage:** In 1(종류)=Task 1 · 2(DB)=Task 1 · 3(대표 선정: 쳇바퀴 1·추락 무관·집계)=Task 1 Step 5 · 4(API)=Task 2 · 5(웹)=Task 3·4 · 6(문서)=Task 5. Q1~Q5 반영: wheel_cap 1(Step 5), fall 정렬 제외(Step 5 `flagged = kinds && ['meaningful','wheel']`), 앱 무변경(Task 2 는 필드 추가만), W/D(Task 3).
**Placeholder scan:** Step 5 는 v0.1 파일 대비 차이만 적었고 "…" 는 v0.1 과 동일 부분 지시(구현자는 v0.1 파일을 복사해 차이만 적용). Step 6 의 순위 숫자는 실행 후 맞추되 합격 기준은 고정. 나머지 TBD 없음.
**Type consistency:** DB `kind`/`kinds text[]`/`behavior_kinds text[]` ↔ API `behavior_kinds: list` ↔ TS `V4BehaviorKind[]`. RPC 이름 `fn_get_motion_clip_behavior_flags`(복수, 3행)·`fn_get_motion_clip_behavior_kinds`(배치)·`fn_set_motion_clip_behavior_flag`(5-인자 신규 + 4-인자 위임) 일관.

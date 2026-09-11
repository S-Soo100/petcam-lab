# 행동 표시 4종 + 대표 선정 슬롯(움직임·격함·클로즈업·쳇바퀴) Implementation Plan (v2)

> **구현 방식 (CAOF):** Critical 트랙(production migration 2개 + 파생 지표 백필 + 앱 API + 라벨링 웹). task 순서대로 구현. Steps use checkbox (`- [ ]`) syntax.
> production write(migration·백필·fly·main push)는 Task 8 게이트에서 owner 승인 뒤에만.
> v1(3버튼·쳇바퀴 상한) 계획은 이 v2 로 대체. 스펙 [`specs/feature-behavior-marks.md`](../../../specs/feature-behavior-marks.md) §0·§0b owner 확정(2026-09-11).

**Goal:** ✨ 하나를 **의미있는 행동·쳇바퀴·추락·📸 예쁘게 나옴** 4개로 넓히고, 앱 대표를 **시간대(KST 시)마다 움직임 2 · 격함 2 · 클로즈업 1** + **쳇바퀴 밤당 1** 슬롯으로 뽑는다. 격함·클로즈업은 GME 영구 아티팩트의 프레임별 박스에서 계산한 파생 지표(엔진 수정 없음). 앱 화면은 무변경.

**Architecture:** ① migration A — 표시 테이블에 `kind`(4종)·PK `(clip_id, kind)`, RPC get(4행)/set(kind)/옛 wrapper/배치 kinds, 목록 함수는 행 중복 방지·종류 필터만(CREATE OR REPLACE). ② 파생 지표 — `backend/gme_run_features.py` 순수 함수(track_points → 지표) + `scripts/compute_gme_run_features.py`(아티팩트 → `gme_run_features` 테이블 upsert, 14일 백필). ③ migration B — `gme_run_features` 테이블 + `fn_highlight_featured` v0.2(슬롯, DROP+CREATE). ④ API `slot`·`behavior_kinds`. ⑤ 웹 버튼 4·단축키·칩 4·배지(종류+슬롯)·상세 지표 줄.

**Tech Stack:** PostgreSQL plpgsql · Python(boto3 R2 read, supabase-py) · FastAPI · Next.js 14 · vitest · 일회용 PostgreSQL probe.

**건드리지 않는 것:** 하이라이트 O/X 규칙·유지율·표본, Flutter, `GET /highlights`.

**순서·규모:** Task 1(표시 migration, 3h) → 2(파생 지표 함수·스크립트, 3h) → 3(슬롯 migration, 4h) → 4(API, 1h) → 5·6(웹, 5h) → 7(문서, 1h) → 8(게이트). 이틀.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `migrations/2026-09-11_behavior_marks.sql` (신규) | kind 4종·PK·인덱스·RPC(get 4행·set 5-인자·옛 4-인자/단일 get 위임·`fn_get_motion_clip_behavior_kinds`)·목록 14-인자 본문 교체 |
| `migrations/2026-09-12_gme_run_features_and_slots.sql` (신규) | `gme_run_features` 테이블 + `fn_highlight_featured` v0.2 |
| `tests/test_behavior_marks_migration.py` · `tests/test_featured_slots_migration.py` (신규) | 정적 계약 |
| `backend/gme_run_features.py` (신규) · `tests/test_gme_run_features.py` (신규) | 순수 지표 계산 + 합성 궤적 테스트 |
| `scripts/compute_gme_run_features.py` (신규) | 아티팩트 → 테이블 upsert(백필·증분) |
| `scripts/run_labeling_v4_probe.py` | §15(표시)·§16(슬롯) |
| `scripts/report_highlight_featured.py` | 슬롯별 개수 표 |
| `backend/routers/highlights.py` · `tests/test_highlights_api.py` | `slot`·`behavior_kinds`·슬롯 메타 |
| `web/src/lib/labelingV4.ts`·`labelingV4Server.ts`(+test)·`labelingHotkeys.ts`(+test)·`labelingV4Api.ts` | 타입·라벨·필터·단축키 P·API |
| `web/src/app/api/labeling-v4/_behavior-flag.ts`·`clips/[clipId]/behavior-flag/route.ts`(+test)·`clips/route.ts`·`featured/route.ts`·`_featured.ts`·`clips/[clipId]/route.ts` | marks 4종·kinds 부착·slot |
| `web/src/app/labeling/v4/_v4-clip-detail.tsx`·`_v4-clip-list.tsx`·`_v4-clip-ui.test.tsx` | 버튼 4·칩 4·배지·지표 줄 |
| 문서 | 런북 §6.x/§6.y, 핸드오프 §3, 결정 로그 |

---

### Task 1: 표시 4종 migration A + 정적 테스트 + probe §15

**Context:**
- Depends on: 없음
- Inputs: `migrations/2026-09-09_labeling_v4_behavior_flags.sql`, `2026-09-09_labeling_v4_eval_samples.sql`(14-인자 목록 본문)
- Outputs: migration A
- Must know: ⚠️ 표시가 영상당 여러 행 → `LEFT JOIN … bf ON bf.clip_id = c.id` 가 목록 행을 **중복**시킨다 → LATERAL 집계. 목록 반환 타입은 그대로(CREATE OR REPLACE, 13/12-인자 wrapper 무변경). 대표 함수는 Task 3 에서 교체하므로 여기선 안 건드리되 **이 migration 만 적용된 사이에도 대표 함수가 중복 행을 내지 않도록** Task 3 migration 을 같은 배포 창에 적용한다(게이트 ①에서 A→B 연속).
- Acceptance: `uv run pytest tests/test_behavior_marks_migration.py -q` PASS · probe `LABELING_V4_PROBE_OK`

**Files:** Create `migrations/2026-09-11_behavior_marks.sql`, `tests/test_behavior_marks_migration.py`; Modify `scripts/run_labeling_v4_probe.py`

- [ ] **Step 1: 정적 테스트**

```python
"""행동 표시 4종 migration A 정적 계약."""
from pathlib import Path
import pytest

SQL_PATH = Path(__file__).resolve().parent.parent / "migrations" / "2026-09-11_behavior_marks.sql"
KINDS = "('meaningful','wheel','fall','closeup')"


@pytest.fixture()
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


def norm(t: str) -> str:
    return " ".join(t.lower().split())


def test_kind_column_and_pk(sql: str) -> None:
    n = norm(sql)
    assert f"add column kind text not null default 'meaningful' check (kind in {KINDS})" in n
    assert "drop constraint motion_clip_behavior_flags_pkey" in n and "add primary key (clip_id, kind)" in n
    assert "create index idx_motion_clip_behavior_flags_kind on public.motion_clip_behavior_flags (kind, flagged_at desc)" in n


def test_rpcs(sql: str) -> None:
    n = norm(sql)
    assert "create function public.fn_get_motion_clip_behavior_flags(p_clip_id uuid) returns table (kind text, flagged boolean, flagged_by uuid, flagged_by_display_name text, flagged_at timestamptz)" in n
    assert "(values ('meaningful'), ('wheel'), ('fall'), ('closeup')) as k(kind)" in n
    assert "create function public.fn_set_motion_clip_behavior_flag( p_clip_id uuid, p_user_id uuid, p_is_owner boolean, p_kind text, p_flagged boolean )" in n
    assert "create or replace function public.fn_set_motion_clip_behavior_flag( p_clip_id uuid, p_user_id uuid, p_is_owner boolean, p_flagged boolean )" in n
    assert "and f.kind = 'meaningful'" in n
    assert "create function public.fn_get_motion_clip_behavior_kinds(p_clip_ids uuid[]) returns table (clip_id uuid, kinds text[])" in n
    assert f"p_kind not in {KINDS}" in n


def test_list_no_dup_and_kind_filter(sql: str) -> None:
    n = norm(sql)
    assert "create or replace function public.fn_list_labeling_v4_clips( p_viewer_id uuid, p_is_owner boolean, p_scope text, p_camera_ids uuid[], p_label_state text, p_highlight_state text, p_behavior_flag text, p_sample_id text," in n
    assert "p_behavior_flag not in ('yes','meaningful','wheel','fall','closeup')" in n
    assert "and (p_behavior_flag = 'yes' or f.kind = p_behavior_flag)" in n
    assert "left join public.motion_clip_behavior_flags bf on bf.clip_id = c.id" not in n
    assert "select (array_agg(f.flagged_by order by f.flagged_at, f.kind))[1] as flagged_by" in n
    for bad in ("drop table", "delete from", "drop function"):
        assert bad not in n, bad
```

- [ ] **Step 2: 실패 확인** — `cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && uv run pytest tests/test_behavior_marks_migration.py -q` → FAIL

- [ ] **Step 3: migration A — 테이블·RPC**

```sql
-- 행동 표시 4종 — 의미있는 행동(meaningful) · 쳇바퀴(wheel) · 추락(fall) · 예쁘게 나옴(closeup). owner 확정 2026-09-11(스펙 feature-behavior-marks §0·§0b).
-- ✨ 하나(종류 없음)를 종류 있는 표시로 넓힌다. 옛 행은 전부 meaningful. 영상당 종류별 1개, 종류끼리 독립.
-- 쳇바퀴 = "제자리 활동" 정답 세트, 추락 = 수집용, closeup = 자동 클로즈업(파생 지표) 정답 세트이자 슬롯 1순위. O/X·유지율과 무관(런북 §6.x).
-- ⚠️ 영상당 여러 행이 되므로 목록 함수의 bf 조인을 LATERAL 집계로 바꿔 행 중복을 막는다(대표 함수는 2026-09-12 migration 에서 교체 — 같은 배포 창에 적용).
BEGIN;

ALTER TABLE public.motion_clip_behavior_flags
  ADD COLUMN kind text NOT NULL DEFAULT 'meaningful' CHECK (kind IN ('meaningful','wheel','fall','closeup'));
ALTER TABLE public.motion_clip_behavior_flags DROP CONSTRAINT motion_clip_behavior_flags_pkey;
ALTER TABLE public.motion_clip_behavior_flags ADD PRIMARY KEY (clip_id, kind);
CREATE INDEX idx_motion_clip_behavior_flags_kind ON public.motion_clip_behavior_flags (kind, flagged_at DESC);

CREATE FUNCTION public.fn_get_motion_clip_behavior_flags(p_clip_id uuid)
RETURNS TABLE (kind text, flagged boolean, flagged_by uuid, flagged_by_display_name text, flagged_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT k.kind, (f.clip_id IS NOT NULL) AS flagged, f.flagged_by, la.display_name, f.flagged_at
    FROM (VALUES ('meaningful'), ('wheel'), ('fall'), ('closeup')) AS k(kind)
    LEFT JOIN public.motion_clip_behavior_flags f ON f.clip_id = p_clip_id AND f.kind = k.kind
    LEFT JOIN public.labeler_applications la ON la.user_id = f.flagged_by
   ORDER BY array_position(ARRAY['meaningful','wheel','fall','closeup'], k.kind);
$$;

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
  IF p_kind IS NULL OR p_kind NOT IN ('meaningful','wheel','fall','closeup') THEN
    RAISE EXCEPTION 'invalid kind' USING ERRCODE = '22023';
  END IF;
  IF NOT public.fn_is_motion_clip_production_labeling_eligible(p_clip_id) THEN
    RAISE EXCEPTION 'motion clip not found' USING ERRCODE = 'P0002';
  END IF;
  IF p_flagged THEN
    INSERT INTO public.motion_clip_behavior_flags (clip_id, kind, flagged_by)
    VALUES (p_clip_id, p_kind, p_user_id)
    ON CONFLICT (clip_id, kind) DO NOTHING;
  ELSE
    SELECT f.flagged_by INTO v_existing_by FROM public.motion_clip_behavior_flags f WHERE f.clip_id = p_clip_id AND f.kind = p_kind;
    IF v_existing_by IS NOT NULL AND v_existing_by <> p_user_id AND NOT coalesce(p_is_owner, false) THEN
      RAISE EXCEPTION 'only the flagger or owner can unflag' USING ERRCODE = 'PT403';
    END IF;
    DELETE FROM public.motion_clip_behavior_flags f WHERE f.clip_id = p_clip_id AND f.kind = p_kind;
  END IF;
  RETURN QUERY SELECT * FROM public.fn_get_motion_clip_behavior_flags(p_clip_id);
END $$;

CREATE OR REPLACE FUNCTION public.fn_set_motion_clip_behavior_flag(
  p_clip_id uuid, p_user_id uuid, p_is_owner boolean, p_flagged boolean
) RETURNS TABLE (flagged boolean, flagged_by uuid, flagged_by_display_name text, flagged_at timestamptz)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
  SELECT r.flagged, r.flagged_by, r.flagged_by_display_name, r.flagged_at
    FROM public.fn_set_motion_clip_behavior_flag(p_clip_id, p_user_id, p_is_owner, 'meaningful', p_flagged) r
   WHERE r.kind = 'meaningful';
$$;

CREATE FUNCTION public.fn_get_motion_clip_behavior_kinds(p_clip_ids uuid[])
RETURNS TABLE (clip_id uuid, kinds text[])
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT f.clip_id, array_agg(f.kind ORDER BY array_position(ARRAY['meaningful','wheel','fall','closeup'], f.kind)) AS kinds
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

- [ ] **Step 4: migration A — 목록 14-인자 본문 교체(프로그램 변환)**

scratchpad `gen_behavior_marks_list.py`: `2026-09-09_labeling_v4_eval_samples.sql` 의 `CREATE FUNCTION public.fn_list_labeling_v4_clips(` 부터 그 함수 `END $$;` 까지 잘라 아래 4개를 치환(각 `assert src.count(old) == 1`)해 Step 3 뒤에 이어 붙이고 `COMMIT;` 으로 닫는다.

```python
REPL = [
    ("  IF p_behavior_flag IS NOT NULL AND p_behavior_flag NOT IN ('yes') THEN",
     "  IF p_behavior_flag IS NOT NULL AND p_behavior_flag NOT IN ('yes','meaningful','wheel','fall','closeup') THEN"),
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

- [ ] **Step 5: probe §15** (§14 뒤; 대표 관련 검증은 §16 에서)

```python
            # 15) 행동 표시 4종: get 4행 · set(kind) · 옛 4-인자/단일 get 은 meaningful 만 · 목록 중복 없음·종류 필터 · 잘못된 kind 22023 · 권한
            expect("marks-get-4", q(f"select 'n|'||count(*)::text from public.fn_get_motion_clip_behavior_flags('{FEAT['h1']}');"), n="4")
            require_ok(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['h1']}','{LABELER}',false,'wheel',true);"), "mark-wheel-h1")
            require_ok(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['h2']}','{LABELER}',false,'wheel',true);"), "mark-wheel-h2")
            require_ok(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['h2']}','{LABELER}',false,'fall',true);"), "mark-fall-h2")
            require_ok(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['rule_x']}','{LABELER}',false,'closeup',true);"), "mark-closeup-rule-x")  # X 영상에 📸
            require_sqlstate(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['h1']}','{LABELER}',false,'jump',true);"), "mark-bad-kind", "22023")
            expect("marks-kinds-h2", q(f"select 'k|'||array_to_string(kinds, ',') from public.fn_get_motion_clip_behavior_kinds(array['{FEAT['h2']}']::uuid[]);"), k="wheel,fall")
            expect("legacy-get", q(f"select 'f|'||flagged::text from public.fn_get_motion_clip_behavior_flag('{FEAT['h2']}');"), f="false")
            expect("legacy-get-b", q(f"select 'f|'||flagged::text from public.fn_get_motion_clip_behavior_flag('{FEAT['b_flag']}');"), f="true")
            require_sqlstate(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['h2']}','{STRANGER}',false,'wheel',false);"), "unflag-stranger", "PT403")
            wheel_ids = require_ok(sql(db, f"select clip_id from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, 'wheel', null, '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50);"), "list-wheel").splitlines()
            if sorted(wheel_ids) != sorted([FEAT['h1'], FEAT['h2']]):
                raise ProbeError(f"list-wheel: {wheel_ids}")
            any_ids = require_ok(sql(db, f"select clip_id from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, 'yes', null, '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50);"), "list-any").splitlines()
            if len(any_ids) != len(set(any_ids)) or set(any_ids) != {FEAT['b_flag'], FEAT['h1'], FEAT['h2'], FEAT['rule_x']}:
                raise ProbeError(f"list-any dup/set: {any_ids}")
            require_sqlstate(sql(db, f"select * from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, 'jump', null, '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50);"), "list-bad-kind", "22023")
            expect("marks-privs", q("select 'ok|'||(not has_function_privilege('authenticated', 'public.fn_set_motion_clip_behavior_flag(uuid,uuid,boolean,text,boolean)', 'EXECUTE'))::text;"), ok="true")
```

`STRANGER` 는 이미 import 돼 있다. migration 목록에 `V4_BEHAVIOR_MARKS_MIGRATION` 추가(§14 대표 검증은 Task 3 migration 도 함께 적용된 상태에서 돌므로 Task 3 에서 §14 기대값을 슬롯 기준으로 고친다 — Task 1 시점엔 §14 가 옛 함수 기준으로 그대로 통과해야 한다: 표시 migration A 는 대표 함수를 안 건드리므로 통과).

- [ ] **Step 6: 실행·커밋** — 정적 PASS · probe OK → `git commit -m "feat: 행동 표시 4종 migration A(kind·PK·RPC·목록 집계/필터) + probe §15"`

---

### Task 2: 파생 지표 — 순수 함수 + 스크립트

**Context:**
- Depends on: 없음(테이블은 Task 3 migration; 스크립트는 그 뒤 실행)
- Inputs: 영구 아티팩트 `gme-artifact-v1`(`track_points[]: {timestamp_sec, bbox_norm[x,y,w,h], confidence, provenance, track_id}`), 실측 스크립트 `scratchpad/measure_intensity_closeup.py`(같은 정의)
- Outputs: `backend/gme_run_features.py` `compute_features(track_points) -> RunFeatures | None`, `scripts/compute_gme_run_features.py`
- Must know: `provenance == 'observed'` 만 쓴다(추정치 제외). 같은 track_id 인접 점만 속도 계산(0 < dt ≤ 2s). 속도 단위 = 몸길이(두 박스 폭 평균)/초 — 카메라 거리 무관. **최댓값이 아니라 p90** 을 격함으로(ID 스위치 스파이크 방어). 클로즈업 = 면적 비율 ≥ 0.08 인 점에서 다음 점까지 시간 합. `feature_version = 'gme-feat-v1'` 을 행에 박는다(정의가 바뀌면 v2 로 재계산).
- Acceptance: `uv run pytest tests/test_gme_run_features.py -q` PASS

**Files:** Create `backend/gme_run_features.py`, `tests/test_gme_run_features.py`, `scripts/compute_gme_run_features.py`

- [ ] **Step 1: 테스트**

```python
"""gme_run_features.compute_features — 합성 궤적: 정지·직진·클로즈업·ID 스위치 스파이크."""
from backend.gme_run_features import CLOSEUP_AREA, FEATURE_VERSION, compute_features


def pt(t, x, y, w=0.1, h=0.1, track="g1", prov="observed"):
    return {"timestamp_sec": t, "bbox_norm": [x, y, w, h], "confidence": 0.9, "provenance": prov, "track_id": track}


def test_static_gecko_has_zero_speed_and_no_closeup():
    f = compute_features([pt(i * 0.5, 0.4, 0.4) for i in range(20)])
    assert f.p90_speed == 0 and f.max_speed == 0 and f.path_diag == 0 and f.closeup_sec == 0 and f.observed_points == 20


def test_straight_run_speed_in_body_lengths_per_sec():
    # 0.5초마다 x 가 0.05(=박스 폭 0.1 의 절반) 이동 → 0.5 몸길이 / 0.5s = 1.0 몸길이/초
    f = compute_features([pt(i * 0.5, 0.1 + 0.05 * i, 0.5) for i in range(10)])
    assert abs(f.p90_speed - 1.0) < 1e-6 and abs(f.max_speed - 1.0) < 1e-6
    assert abs(f.path_diag - (0.45 / 2 ** 0.5)) < 1e-6


def test_closeup_seconds_counts_big_boxes():
    pts = [pt(i * 1.0, 0.3, 0.3, w=0.4, h=0.3) for i in range(12)] + [pt(12 + i, 0.3, 0.3) for i in range(5)]  # 0.12 면적 11초 + 작은 박스
    f = compute_features(pts)
    assert f.max_area == 0.12 and abs(f.closeup_sec - 11.0) < 1e-6 and CLOSEUP_AREA == 0.08


def test_id_switch_spike_is_not_p90():
    pts = [pt(i * 0.5, 0.1 + 0.005 * i, 0.5) for i in range(40)]  # 느린 이동
    pts[20] = pt(10.0, 0.9, 0.5)  # 한 점만 튐(스파이크)
    f = compute_features(pts)
    assert f.max_speed > 5 and f.p90_speed < 0.5


def test_ignores_non_observed_and_short_tracks():
    assert compute_features([pt(0, 0.1, 0.1, prov="tracked")] * 10) is None
    assert compute_features([pt(0, 0.1, 0.1), pt(1, 0.2, 0.1)]) is None  # 5점 미만
    assert FEATURE_VERSION == "gme-feat-v1"
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_gme_run_features.py -q` → ImportError

- [ ] **Step 3: 순수 함수**

```python
"""GME 영구 아티팩트(track_points)에서 파생 지표를 계산한다 — 격함(속도)·클로즈업(박스 면적). 엔진 수정 없이 사후 계산.

- 속도 단위 = 몸길이/초(두 박스 폭 평균으로 나눔) → 카메라 거리와 무관.
- 격함은 p90(상위 10% 값). 최댓값은 ID 스위치 스파이크에 취약해 참고용.
- 클로즈업 초 = 면적 비율(w*h) ≥ CLOSEUP_AREA 인 점에서 다음 점까지의 시간 합(같은 프레임 간격 ≤ 2s 만).
정의를 바꾸면 FEATURE_VERSION 을 올리고 전량 재계산한다(스펙 feature-behavior-marks §2).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

FEATURE_VERSION = "gme-feat-v1"
CLOSEUP_AREA = 0.08
MAX_GAP_SEC = 2.0
MIN_POINTS = 5


@dataclass(frozen=True, slots=True)
class RunFeatures:
    p90_speed: float
    max_speed: float
    path_diag: float
    max_area: float
    mean_area: float
    closeup_sec: float
    observed_points: int


def compute_features(track_points: list[dict]) -> RunFeatures | None:
    pts = sorted((p for p in track_points if p.get("provenance") == "observed"), key=lambda p: p["timestamp_sec"])
    if len(pts) < MIN_POINTS:
        return None
    speeds: list[float] = []
    path = 0.0
    for a, b in zip(pts, pts[1:]):
        dt = b["timestamp_sec"] - a["timestamp_sec"]
        if dt <= 0 or dt > MAX_GAP_SEC or a["track_id"] != b["track_id"]:
            continue
        ax, ay, aw, ah = a["bbox_norm"]
        bx, by, bw, bh = b["bbox_norm"]
        dist = math.hypot((bx + bw / 2) - (ax + aw / 2), (by + bh / 2) - (ay + ah / 2))
        body = max(1e-3, (aw + bw) / 2)
        speeds.append(dist / body / dt)
        path += dist
    if not speeds:
        return None
    speeds.sort()
    areas = [(p["timestamp_sec"], p["bbox_norm"][2] * p["bbox_norm"][3]) for p in pts]
    closeup = 0.0
    for (t0, a0), (t1, _) in zip(areas, areas[1:]):
        if a0 >= CLOSEUP_AREA and 0 < t1 - t0 <= MAX_GAP_SEC:
            closeup += t1 - t0
    return RunFeatures(
        p90_speed=speeds[min(len(speeds) - 1, int(len(speeds) * 0.9))],
        max_speed=speeds[-1],
        path_diag=path / math.sqrt(2),
        max_area=max(a for _, a in areas),
        mean_area=sum(a for _, a in areas) / len(areas),
        closeup_sec=closeup,
        observed_points=len(pts),
    )
```

> `test_straight_run_speed`: 9구간 × 0.05 = 0.45 → `path_diag = 0.45/√2`. `test_id_switch_spike`: 튄 점 앞뒤 두 구간이 최대 속도, p90 은 나머지 느린 구간(0.005/0.1/0.5 = 0.1 몸길이/초).

- [ ] **Step 4: 스크립트**

```python
"""GME 영구 아티팩트 → gme_run_features 테이블(파생 지표 gme-feat-v1). 백필·증분 공용.

사용: uv run python scripts/compute_gme_run_features.py --days 14 --contract gme-motion-v1 <detector64> [--limit 500] [--dry-run]
- 대상: 기간 내 status='ok' run 중 활성 계약이고 features 행이 없거나 feature_version 이 다른 것.
- 쓰기: service_role upsert(run_id PK). 읽기 전용 확인은 --dry-run.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
from dotenv import load_dotenv
from supabase import create_client

from backend.gme_run_features import FEATURE_VERSION, compute_features

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(Path("/Users/baek/petcam-lab/.env"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--contract", nargs=2, metavar=("ALGO", "DETECTOR"), required=True)
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    s3 = boto3.client("s3", endpoint_url=os.environ.get("R2_ENDPOINT") or os.environ.get("R2_ENDPOINT_URL"),
                      aws_access_key_id=os.environ.get("R2_ACCESS_KEY_ID"), aws_secret_access_key=os.environ.get("R2_SECRET_ACCESS_KEY"), region_name="auto")
    bucket = os.environ.get("R2_BUCKET") or os.environ.get("R2_BUCKET_NAME")
    since = (datetime.now(timezone.utc) - timedelta(days=a.days)).isoformat()
    runs = []
    offset = 0
    while True:  # supabase-py 1,000행 캡 → range 페이징
        page = (sb.table("gme_runs").select("id,clip_id,permanent_artifact_key,created_at").eq("status", "ok")
                .eq("algorithm_version", a.contract[0]).eq("detector_identity", a.contract[1]).gte("created_at", since)
                .order("created_at", desc=True).range(offset, offset + 999).execute().data)
        runs += page
        if len(page) < 1000 or len(runs) >= a.limit:
            break
        offset += 1000
    runs = runs[: a.limit]
    have = {}
    ids = [r["id"] for r in runs]
    for i in range(0, len(ids), 500):
        for row in sb.table("gme_run_features").select("run_id,feature_version").in_("run_id", ids[i:i + 500]).execute().data:
            have[row["run_id"]] = row["feature_version"]
    todo = [r for r in runs if have.get(r["id"]) != FEATURE_VERSION]
    print(f"runs {len(runs)} · todo {len(todo)} · version {FEATURE_VERSION}")
    batch, done, skipped = [], 0, 0
    for r in todo:
        key = r["permanent_artifact_key"]
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        d = json.loads(gzip.decompress(body) if key.endswith(".gz") else body)
        f = compute_features(d.get("track_points", []))
        if f is None:
            skipped += 1
            continue
        batch.append({"run_id": r["id"], "clip_id": r["clip_id"], "feature_version": FEATURE_VERSION, **asdict(f)})
        if len(batch) >= 100:
            if not a.dry_run:
                sb.table("gme_run_features").upsert(batch, on_conflict="run_id").execute()
            done += len(batch); batch = []
    if batch and not a.dry_run:
        sb.table("gme_run_features").upsert(batch, on_conflict="run_id").execute()
    done += len(batch)
    print(f"{'would write' if a.dry_run else 'wrote'} {done} · skipped(<5 observed points) {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: 테스트 PASS → 커밋** `feat: GME 파생 지표(격함·클로즈업) 순수 함수 + 백필 스크립트`

---

### Task 3: migration B — `gme_run_features` 테이블 + `fn_highlight_featured` v0.2(슬롯) + probe §16

**Context:**
- Depends on: Task 1(kind), Task 2(지표 정의)
- Inputs: v0.1 함수(`2026-09-11_highlight_featured_hour_cap.sql`)
- Outputs: 테이블 1 + 함수 교체(DROP+CREATE, 14-인자)
- Must know: 슬롯 우선순위는 고정 순서로 계산해 한 사건이 두 슬롯을 먹지 않게 한다: **쳇바퀴(밤당) → 움직임(시간대) → 격함(시간대, 앞 슬롯 제외) → 클로즈업(시간대, 앞 슬롯 사건 소속 영상 제외, X 영상 포함)**. 파생 지표가 없는 run(백필 전)은 격함·클로즈업 후보에서 빠질 뿐 움직임 슬롯은 동작. `p_hour_cap`·`p_top_n` 제거(슬롯이 대체). 출력에 `slot`·`hour_key`·`intensity`·`closeup_sec`·`highlight_value` 추가.
- Acceptance: `uv run pytest tests/test_featured_slots_migration.py -q` PASS · probe `LABELING_V4_PROBE_OK`

**Files:** Create `migrations/2026-09-12_gme_run_features_and_slots.sql`, `tests/test_featured_slots_migration.py`; Modify `scripts/run_labeling_v4_probe.py`

- [ ] **Step 1: 정적 테스트**

```python
"""대표 tier v0.2(슬롯) migration B 정적 계약."""
from pathlib import Path
import pytest

SQL_PATH = Path(__file__).resolve().parent.parent / "migrations" / "2026-09-12_gme_run_features_and_slots.sql"
OLD_SIG = "uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer"
NEW_SIG = "uuid[], timestamptz, timestamptz, text, text, text, integer, integer, text, integer, integer, integer, integer, numeric"


@pytest.fixture()
def sql() -> str:
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


def norm(t: str) -> str:
    return " ".join(t.lower().split())


def test_features_table(sql: str) -> None:
    n = norm(sql)
    assert "create table public.gme_run_features ( run_id uuid primary key references public.gme_runs(id) on delete cascade," in n
    for col in ("feature_version text not null", "p90_speed numeric", "max_speed numeric", "path_diag numeric", "max_area numeric", "mean_area numeric", "closeup_sec numeric", "observed_points integer not null"):
        assert col in n, col
    assert "alter table public.gme_run_features enable row level security" in n
    assert "grant select, insert, update on public.gme_run_features to service_role" in n


def test_featured_signature_and_slots(sql: str) -> None:
    n = norm(sql)
    assert f"drop function public.fn_highlight_featured({OLD_SIG});" in n
    for p in ("p_activity_slots integer default 2", "p_intensity_slots integer default 2", "p_closeup_slots integer default 1", "p_wheel_cap integer default 1", "p_closeup_min_sec numeric default 10"):
        assert p in n, p
    assert "p_hour_cap" not in n.split("create function")[1] and "p_top_n" not in n.split("create function")[1]
    for col in ("slot text", "hour_key integer", "intensity numeric", "closeup_sec numeric", "highlight_value boolean", "behavior_kinds text[]", "episode_intensity numeric"):
        assert col in n, col
    assert "'closeup' = any (b.kinds) or coalesce(b.closeup_sec, 0) >= p_closeup_min_sec" in n
    assert "on rr.run_id is not null" in n and "run_row is not null" not in n
    assert f"grant execute on function public.fn_highlight_featured({NEW_SIG}) to service_role;" in n
```

- [ ] **Step 2: migration B**

```sql
-- 대표 tier v0.2 — 시간대 슬롯(움직임 2·격함 2·클로즈업 1) + 쳇바퀴 밤당 1 (owner 확정 2026-09-11, 스펙 feature-behavior-marks §0b).
-- 파생 지표 gme_run_features(격함 p90_speed·클로즈업 closeup_sec, 영구 아티팩트에서 스크립트가 채움) 를 읽는다. 없으면 그 후보에서만 빠진다.
-- 슬롯 순서(한 사건이 두 슬롯을 못 먹게): 쳇바퀴(밤) → 움직임(시) → 격함(시, 앞 제외) → 클로즈업(시, 앞 슬롯 사건의 영상 제외, X 영상 포함).
-- 추락(fall)은 어디에도 안 들어감(수집용). 저장 없음·조회 시 계산·O/X 규칙 불변은 그대로.
BEGIN;

CREATE TABLE public.gme_run_features (
  run_id uuid PRIMARY KEY REFERENCES public.gme_runs(id) ON DELETE CASCADE,
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE CASCADE,
  feature_version text NOT NULL,
  p90_speed numeric,
  max_speed numeric,
  path_diag numeric,
  max_area numeric,
  mean_area numeric,
  closeup_sec numeric,
  observed_points integer NOT NULL,
  computed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_gme_run_features_clip ON public.gme_run_features (clip_id);
ALTER TABLE public.gme_run_features ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.gme_run_features FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.gme_run_features TO service_role;  -- 백필 스크립트(service_role) 가 upsert

DROP FUNCTION public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer);

CREATE FUNCTION public.fn_highlight_featured(
  p_camera_ids uuid[],
  p_from timestamptz,
  p_to timestamptz,
  p_engine_schema_version text,
  p_algorithm_version text,
  p_detector_identity text,
  p_gap_sec integer DEFAULT 600,
  p_day_start_hour integer DEFAULT 20,
  p_tz text DEFAULT 'Asia/Seoul',
  p_activity_slots integer DEFAULT 2,
  p_intensity_slots integer DEFAULT 2,
  p_closeup_slots integer DEFAULT 1,
  p_wheel_cap integer DEFAULT 1,
  p_closeup_min_sec numeric DEFAULT 10
) RETURNS TABLE (
  clip_id uuid,
  camera_id uuid,
  camera_name text,
  started_at timestamptz,
  duration_sec double precision,
  day_key date,
  hour_key integer,
  episode_no integer,
  episode_started_at timestamptz,
  episode_ended_at timestamptz,
  episode_clip_count integer,
  episode_activity_sec numeric,
  episode_intensity numeric,
  episode_rank integer,
  tier text,
  slot text,
  is_representative boolean,
  activity_sec numeric,
  intensity numeric,
  closeup_sec numeric,
  highlight_value boolean,
  highlight_source text,
  highlight_reason text,
  reviewer_id uuid,
  reviewer_display_name text,
  behavior_flagged boolean,
  behavior_kinds text[]
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
#variable_conflict use_column
DECLARE
  v_rule record;
BEGIN
  IF p_from IS NULL OR p_to IS NULL OR p_from >= p_to THEN RAISE EXCEPTION 'invalid range' USING ERRCODE = '22023'; END IF;
  IF p_to - p_from > interval '31 days' THEN RAISE EXCEPTION 'range too wide (max 31 days)' USING ERRCODE = '22023'; END IF;
  IF p_gap_sec IS NULL OR p_gap_sec < 60 OR p_gap_sec > 21600 THEN RAISE EXCEPTION 'invalid gap_sec (60..21600)' USING ERRCODE = '22023'; END IF;
  IF p_day_start_hour IS NULL OR p_day_start_hour < 0 OR p_day_start_hour > 23 THEN RAISE EXCEPTION 'invalid day_start_hour (0..23)' USING ERRCODE = '22023'; END IF;
  IF p_tz IS NULL THEN RAISE EXCEPTION 'invalid time zone' USING ERRCODE = '22023'; END IF;
  IF p_activity_slots IS NULL OR p_activity_slots < 0 OR p_activity_slots > 10
     OR p_intensity_slots IS NULL OR p_intensity_slots < 0 OR p_intensity_slots > 10
     OR p_closeup_slots IS NULL OR p_closeup_slots < 0 OR p_closeup_slots > 10 THEN
    RAISE EXCEPTION 'invalid slots (0..10)' USING ERRCODE = '22023';
  END IF;
  IF p_wheel_cap IS NOT NULL AND (p_wheel_cap < 1 OR p_wheel_cap > 10) THEN RAISE EXCEPTION 'invalid wheel_cap (1..10 or null)' USING ERRCODE = '22023'; END IF;
  IF p_closeup_min_sec IS NULL OR p_closeup_min_sec < 0 THEN RAISE EXCEPTION 'invalid closeup_min_sec' USING ERRCODE = '22023'; END IF;
  SELECT * INTO v_rule FROM public.fn_get_active_highlight_rule();
  IF v_rule.version IS NULL THEN RAISE EXCEPTION 'no active highlight rule' USING ERRCODE = 'PT428'; END IF;

  RETURN QUERY
  WITH base AS (
    SELECT c.id AS clip_id, c.camera_id, coalesce(cam.name, c.camera_id::text) AS camera_name,
           c.started_at, c.duration_sec,
           ((c.started_at AT TIME ZONE p_tz) - make_interval(hours => p_day_start_hour))::date AS day_key,
           extract(hour FROM (c.started_at AT TIME ZONE p_tz))::integer AS hour_key,
           vd.verdict AS human_verdict, vd.initial_reason AS human_reason,
           vd.reviewer_id, la.display_name AS reviewer_display_name,
           ev.initial AS rule_initial, ev.reason AS rule_reason,
           (ev.features->>'activity_sec')::numeric AS activity_sec,
           coalesce(bf.kinds, '{}'::text[]) AS kinds,
           gf.p90_speed AS intensity, gf.closeup_sec
      FROM public.motion_clips c
      LEFT JOIN public.cameras cam ON cam.id = c.camera_id
      LEFT JOIN LATERAL (
        SELECT v.verdict, v.initial_reason, v.reviewer_id FROM public.motion_clip_highlight_verdicts v
         WHERE v.clip_id = c.id ORDER BY v.created_at DESC, v.id DESC LIMIT 1
      ) vd ON true
      LEFT JOIN public.labeler_applications la ON la.user_id = vd.reviewer_id
      LEFT JOIN LATERAL (
        SELECT array_agg(f.kind ORDER BY array_position(ARRAY['meaningful','wheel','fall','closeup'], f.kind)) AS kinds
          FROM public.motion_clip_behavior_flags f WHERE f.clip_id = c.id
      ) bf ON true
      LEFT JOIN LATERAL (
        SELECT r AS run_row, r.id AS run_id FROM public.gme_jobs j
          JOIN public.gme_runs r ON r.id = j.result_run_id AND r.job_id = j.id
         WHERE j.clip_id = c.id AND j.engine_schema_version = p_engine_schema_version
           AND j.algorithm_version = p_algorithm_version AND j.detector_identity = p_detector_identity
           AND j.status = 'succeeded' AND r.status = 'ok'
         ORDER BY j.created_at ASC, j.id ASC LIMIT 1
      ) rr ON true
      -- composite IS NOT NULL 함정: run_id 로 존재 판정.
      LEFT JOIN LATERAL public.fn_highlight_rule_eval(rr.run_row, v_rule.params) ev ON rr.run_id IS NOT NULL
      LEFT JOIN public.gme_run_features gf ON gf.run_id = rr.run_id
     WHERE c.started_at >= p_from AND c.started_at < p_to
       AND c.r2_key IS NOT NULL
       AND (p_camera_ids IS NULL OR c.camera_id = ANY (p_camera_ids))
       AND public.fn_is_motion_clip_production_labeling_eligible(c.id)
       AND NOT EXISTS (SELECT 1 FROM public.motion_clip_system_exclusions x WHERE x.clip_id = c.id AND x.state = 'media_deleted')
  ),
  cur AS (SELECT b.*, coalesce(b.human_verdict, b.rule_initial) AS current_value FROM base b),
  o AS (SELECT * FROM cur WHERE current_value IS TRUE),
  gaps AS (
    SELECT o.*,
           CASE WHEN lag(o.started_at + make_interval(secs => coalesce(o.duration_sec, 60))) OVER w IS NULL
                  OR o.started_at - lag(o.started_at + make_interval(secs => coalesce(o.duration_sec, 60))) OVER w > make_interval(secs => p_gap_sec)
                THEN 1 ELSE 0 END AS is_new
      FROM o WINDOW w AS (PARTITION BY o.camera_id, o.day_key ORDER BY o.started_at, o.clip_id)
  ),
  ep AS (
    SELECT g.*, sum(g.is_new) OVER (PARTITION BY g.camera_id, g.day_key ORDER BY g.started_at, g.clip_id ROWS UNBOUNDED PRECEDING)::integer AS episode_no
      FROM gaps g
  ),
  agg AS (
    SELECT e.camera_id, e.day_key, e.episode_no,
           min(e.started_at) AS ep_start, max(e.started_at + make_interval(secs => coalesce(e.duration_sec, 60))) AS ep_end,
           count(*)::integer AS ep_count, sum(coalesce(e.activity_sec, 0)) AS ep_activity,
           max(e.intensity) AS ep_intensity,
           bool_or('meaningful' = ANY (e.kinds)) AS ep_meaningful,
           bool_or('wheel' = ANY (e.kinds)) AS ep_wheel,
           bool_or(e.human_verdict IS TRUE) AS ep_human_o
      FROM ep e GROUP BY e.camera_id, e.day_key, e.episode_no
  ),
  rep AS (
    SELECT t.camera_id, t.day_key, t.episode_no, t.clip_id AS rep_clip_id, t.hour_key AS rep_hour
      FROM (SELECT e.*, row_number() OVER (PARTITION BY e.camera_id, e.day_key, e.episode_no
                                           ORDER BY ('meaningful' = ANY (e.kinds)) DESC, (e.human_verdict IS TRUE) DESC, e.activity_sec DESC NULLS LAST, e.started_at ASC) AS rn
              FROM ep e) t WHERE t.rn = 1
  ),
  epx AS (SELECT a.*, p.rep_clip_id, p.rep_hour FROM agg a JOIN rep p USING (camera_id, day_key, episode_no)),
  -- ④ 쳇바퀴: 밤·카메라당 p_wheel_cap (activity 합 순). 슬롯 밖.
  wheel_ranked AS (
    SELECT x.*, CASE WHEN x.ep_wheel THEN row_number() OVER (PARTITION BY x.camera_id, x.day_key, x.ep_wheel ORDER BY x.ep_activity DESC, x.ep_start DESC)::integer END AS wheel_rank
      FROM epx x
  ),
  s1 AS (
    SELECT w.*, (w.ep_wheel AND (p_wheel_cap IS NULL OR w.wheel_rank <= p_wheel_cap)) AS in_wheel FROM wheel_ranked w
  ),
  -- ① 움직임: 시간대(대표 클립의 KST 시)당 p_activity_slots. ✨ > 사람 O > activity 합. 쳇바퀴 슬롯 사건 제외.
  s2 AS (
    SELECT s.*, CASE WHEN NOT s.in_wheel THEN row_number() OVER (PARTITION BY s.camera_id, s.day_key, s.rep_hour, s.in_wheel
                                                                  ORDER BY s.ep_meaningful DESC, s.ep_human_o DESC, s.ep_activity DESC, s.ep_start DESC)::integer END AS act_rank
      FROM s1 s
  ),
  s3 AS (SELECT s.*, (NOT s.in_wheel AND s.act_rank <= p_activity_slots) AS in_activity FROM s2 s),
  -- ② 격함: 앞 슬롯에 안 든 사건 중 사람 O > 사건 격함(클립 p90 최대). 지표 없는 사건은 뒤로.
  s4 AS (
    SELECT s.*, CASE WHEN NOT s.in_wheel AND NOT s.in_activity AND s.ep_intensity IS NOT NULL
                     THEN row_number() OVER (PARTITION BY s.camera_id, s.day_key, s.rep_hour, (s.in_wheel OR s.in_activity OR s.ep_intensity IS NULL)
                                             ORDER BY s.ep_human_o DESC, s.ep_intensity DESC, s.ep_activity DESC)::integer END AS int_rank
      FROM s3 s
  ),
  slotted AS (
    SELECT s.camera_id, s.day_key, s.episode_no, s.rep_clip_id, s.ep_start, s.ep_end, s.ep_count, s.ep_activity, s.ep_intensity,
           s.act_rank AS ep_rank,
           CASE WHEN s.in_wheel THEN 'wheel' WHEN s.in_activity THEN 'activity'
                WHEN s.int_rank IS NOT NULL AND s.int_rank <= p_intensity_slots THEN 'intensity' END AS ep_slot
      FROM s4 s
  ),
  -- ③ 클로즈업: 모든 영상(O/X 무관) 중 📸 또는 closeup_sec ≥ 기준. 앞 슬롯 사건에 속한 영상은 제외. 시간대당 p_closeup_slots.
  close_cand AS (
    SELECT b.*, e.episode_no AS o_episode_no
      FROM cur b
      LEFT JOIN ep e ON e.clip_id = b.clip_id
      LEFT JOIN slotted sl ON sl.camera_id = b.camera_id AND sl.day_key = b.day_key AND sl.episode_no = e.episode_no
     WHERE ('closeup' = ANY (b.kinds) OR coalesce(b.closeup_sec, 0) >= p_closeup_min_sec)
       AND (sl.ep_slot IS NULL)
  ),
  close_ranked AS (
    SELECT cc.clip_id, row_number() OVER (PARTITION BY cc.camera_id, cc.day_key, cc.hour_key
                                          ORDER BY ('closeup' = ANY (cc.kinds)) DESC, cc.closeup_sec DESC NULLS LAST, cc.started_at DESC)::integer AS close_rank
      FROM close_cand cc
  ),
  -- O 영상 행
  o_rows AS (
    SELECT e.clip_id, e.camera_id, e.camera_name, e.started_at, e.duration_sec, e.day_key, e.hour_key, e.episode_no,
           sl.ep_start, sl.ep_end, sl.ep_count, round(sl.ep_activity, 1) AS ep_activity, round(sl.ep_intensity, 2) AS ep_intensity, sl.ep_rank,
           CASE WHEN sl.rep_clip_id = e.clip_id AND sl.ep_slot IS NOT NULL THEN sl.ep_slot
                WHEN cr.close_rank IS NOT NULL AND cr.close_rank <= p_closeup_slots THEN 'closeup' END AS slot,
           (sl.rep_clip_id = e.clip_id) AS is_rep, e.activity_sec, e.intensity, e.closeup_sec, true AS highlight_value,
           e.human_verdict, e.human_reason, e.rule_reason, e.reviewer_id, e.reviewer_display_name, e.kinds
      FROM ep e
      JOIN slotted sl ON sl.camera_id = e.camera_id AND sl.day_key = e.day_key AND sl.episode_no = e.episode_no
      LEFT JOIN close_ranked cr ON cr.clip_id = e.clip_id
  ),
  -- X 영상인데 클로즈업 슬롯에 든 행
  x_rows AS (
    SELECT b.clip_id, b.camera_id, b.camera_name, b.started_at, b.duration_sec, b.day_key, b.hour_key, NULL::integer AS episode_no,
           NULL::timestamptz AS ep_start, NULL::timestamptz AS ep_end, NULL::integer AS ep_count, NULL::numeric AS ep_activity, NULL::numeric AS ep_intensity, NULL::integer AS ep_rank,
           'closeup'::text AS slot, true AS is_rep, b.activity_sec, b.intensity, b.closeup_sec, false AS highlight_value,
           b.human_verdict, b.human_reason, b.rule_reason, b.reviewer_id, b.reviewer_display_name, b.kinds
      FROM cur b JOIN close_ranked cr ON cr.clip_id = b.clip_id
     WHERE b.current_value IS NOT TRUE AND cr.close_rank <= p_closeup_slots
  ),
  all_rows AS (SELECT * FROM o_rows UNION ALL SELECT * FROM x_rows)
  SELECT r.clip_id, r.camera_id, r.camera_name, r.started_at, r.duration_sec, r.day_key, r.hour_key, r.episode_no,
         r.ep_start, r.ep_end, r.ep_count, r.ep_activity, r.ep_intensity, r.ep_rank,
         CASE WHEN r.slot IS NOT NULL THEN 'featured' ELSE 'candidate' END, r.slot, r.is_rep,
         round(coalesce(r.activity_sec, 0), 1), round(r.intensity, 2), round(r.closeup_sec, 1), r.highlight_value,
         CASE WHEN r.human_verdict IS NOT NULL THEN 'human' ELSE 'rule' END, coalesce(r.human_reason, r.rule_reason, ''),
         r.reviewer_id, r.reviewer_display_name, (r.kinds && ARRAY['meaningful','wheel','fall','closeup']), r.kinds
    FROM all_rows r
   ORDER BY r.day_key DESC, r.camera_id, r.hour_key DESC, (r.slot IS NULL), r.started_at DESC;
END $$;

REVOKE ALL ON FUNCTION public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, text, integer, integer, integer, integer, numeric) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, text, integer, integer, integer, integer, numeric) TO service_role;

COMMIT;
```

> `ep_rank` 는 이제 "움직임 순위(시간대 안)" 다. 정렬은 (하루 최신, 카메라, 시 최신, 대표 먼저, 시각 최신).

- [ ] **Step 3: probe §16 + §14 기대값 갱신**

§14 는 v0.1 인자(`null, 600, 20, 'Asia/Seoul', 3`)로 호출하던 검사라 새 시그니처에 맞춰 **§14 를 §16 으로 대체**한다(옛 검사는 migration 파일과 정적 테스트가 보존). §16 fixture(§14 것 재사용, CAM_C 2026-09-01):

```python
            # 16) 대표 v0.2 슬롯. 파생 지표: a2 격함 2.5, h1 1.0, h2 0.5, c 3.0(사람 O), rule_x 클로즈업 12초(📸 는 §15 에서 표시됨), b_flag 클로즈업 0.
            require_ok(sql(db, f"""
              insert into public.gme_run_features(run_id, clip_id, feature_version, p90_speed, max_speed, path_diag, max_area, mean_area, closeup_sec, observed_points) values
                ('52000002-0000-4000-8000-000000000001','{FEAT['a2']}','gme-feat-v1',2.5,3,1,0.05,0.03,0,50),
                ('52000008-0000-4000-8000-000000000001','{FEAT['h1']}','gme-feat-v1',1.0,1,1,0.05,0.03,0,50),
                ('52000009-0000-4000-8000-000000000001','{FEAT['h2']}','gme-feat-v1',0.5,1,1,0.05,0.03,0,50),
                ('52000004-0000-4000-8000-000000000001','{FEAT['c']}','gme-feat-v1',3.0,3,1,0.05,0.03,0,50),
                ('52000007-0000-4000-8000-000000000001','{FEAT['rule_x']}','gme-feat-v1',0.1,0.2,0.1,0.20,0.15,12,50);
            """), "features-seed")
            feat3 = f"public.fn_highlight_featured(array['{CAM_C}']::uuid[], '2026-08-31T00:00:00Z', '2026-09-03T00:00:00Z', '{ENGINE}','{ALGO}','{IDENTITY}', 600, 20, 'Asia/Seoul', 2, 2, 1, 1, 10)"
            got3 = require_ok(sql(db, f"select clip_id||'|'||tier||'|'||coalesce(slot,'-')||'|'||highlight_value::text from {feat3} order by day_key, hour_key, started_at;"), "slots").splitlines()
            # 21시(KST): 사건 a(a1+a2, ✨없음·activity 27·격함 2.5), h1(14, 🎡 wheel), h2(13, 🎡+⚠️), h3(11). 쳇바퀴 밤당 1 → h1(activity 14 > h2 13) wheel 슬롯.
            #   움직임 2: a(27), h3(11)  [h2 는 wheel 이지만 상한 초과 → 일반 경쟁: activity 13 > h3 11 이므로 h2 가 2위, h3 3위] → 정정: 움직임 = a, h2. 격함 2: 남은 사건 중 지표 있는 것 = 없음(h3 지표 없음) → 0개.
            # 00시: b_flag(✨) 움직임 1위. 03시: c(사람 O, 격함 3.0) 움직임 1위. 05시: human_x 는 사람 X 라 후보 아님. 06시(21Z): rule_x 는 X 인데 📸+클로즈업 12초 → 클로즈업 슬롯(highlight_value false).
            # 전날 19시: prev_day 움직임 1위.
            want3 = [f"{FEAT['prev_day']}|featured|activity|true",
                     f"{FEAT['a1']}|candidate|-|true", f"{FEAT['a2']}|featured|activity|true",
                     f"{FEAT['h1']}|featured|wheel|true", f"{FEAT['h2']}|featured|activity|true", f"{FEAT['h3']}|candidate|-|true",
                     f"{FEAT['b_flag']}|featured|activity|true",
                     f"{FEAT['c']}|featured|activity|true",
                     f"{FEAT['rule_x']}|featured|closeup|false"]
            if got3 != want3:
                raise ProbeError(f"slots: got {got3} want {want3}")
            # 격함 슬롯 확인: 움직임 슬롯을 0 으로 두면 21시에서 격함 2 = a(2.5), h1 은 wheel, h2(0.5) → a·h2 intensity
            got4 = require_ok(sql(db, f"select clip_id||'|'||coalesce(slot,'-') from {feat3.replace(', 2, 2, 1, 1, 10)', ', 0, 2, 1, 1, 10)')} where hour_key = 21 order by started_at;"), "slots-intensity").splitlines()
            want4 = [f"{FEAT['a1']}|-", f"{FEAT['a2']}|intensity", f"{FEAT['h1']}|wheel", f"{FEAT['h2']}|intensity", f"{FEAT['h3']}|-"]
            if got4 != want4:
                raise ProbeError(f"slots-intensity: got {got4} want {want4}")
            expect("slots-no-closeup", q(f"select 'n|'||count(*)::text from {feat3.replace(', 2, 2, 1, 1, 10)', ', 2, 2, 0, 1, 10)')} where slot = 'closeup';"), n="0")
            require_sqlstate(sql(db, f"select * from {feat3.replace(', 2, 2, 1, 1, 10)', ', 11, 2, 1, 1, 10)')};"), "slots-bad", "22023")
            expect("features-privs", q("select 'ok|'||(not has_table_privilege('authenticated', 'public.gme_run_features', 'SELECT'))::text;"), ok="true")
```

> 순서·순위는 실행해 보고 `want3/want4` 를 실제 정렬(`ORDER BY day_key, hour_key, started_at`)에 맞춘다. **합격 기준(고정):** 쳇바퀴 2개 중 1개만 wheel · 21시 움직임 슬롯 2개 · 격함 슬롯은 지표 있는 사건만 · X 영상이 📸+클로즈업으로 featured(highlight_value false) · 추락 h2 는 슬롯에 영향 없음 · 슬롯 0 이면 그 종류 0개.

- [ ] **Step 4: 정적 PASS · probe OK → 커밋** `feat: 대표 tier v0.2 — 시간대 슬롯(움직임2·격함2·클로즈업1)+쳇바퀴 밤당1, gme_run_features 테이블 + probe §15·§16`

---

### Task 4: petcam-api

- [ ] 상수: `FEATURED_ACTIVITY_SLOTS=2 / INTENSITY_SLOTS=2 / CLOSEUP_SLOTS=1 / WHEEL_CAP=1 / CLOSEUP_MIN_SEC=10`, `FEATURED_GAP_SEC=600` 유지, `FEATURED_HOUR_CAP`·`FEATURED_DEFAULT_TOP_N`·`top_n` 쿼리 제거. RPC 인자 이름 새 시그니처대로. meta `featured{slots:{activity,intensity,closeup}, wheel_cap, closeup_min_sec, gap_sec, day_start_hour, time_zone, days}`.
- [ ] `_to_featured_item`: `slot`, `behavior_kinds`, `highlight_value`, `intensity`, `closeup_sec`, `episode.intensity`; `rule_version` 은 `source=='rule'` 일 때만(그대로). `hour_key` 는 앱 불필요 → 제외.
- [ ] 테스트: `_frow` 갱신(slot·kinds·hour_key…), 기본 응답 `slot=='activity'`, `tier=all` 후보 포함, params 에 `p_activity_slots==2 … p_closeup_min_sec==10`, `top_n` 쿼리는 이제 무시가 아니라 **422**(제거) → parametrize 갱신. `uv run pytest tests/test_highlights_api.py -q` PASS → 커밋.

---

### Task 5: 웹 lib·API

- [ ] `labelingV4.ts`

```ts
export type V4BehaviorKind = 'meaningful' | 'wheel' | 'fall' | 'closeup';
export const V4_BEHAVIOR_KINDS: V4BehaviorKind[] = ['meaningful', 'wheel', 'fall', 'closeup'];
export const V4_BEHAVIOR_KIND_LABELS: Record<V4BehaviorKind, string> = { meaningful: '의미있는 행동', wheel: '쳇바퀴', fall: '추락', closeup: '예쁘게 나옴' };
export const V4_BEHAVIOR_KIND_ICONS: Record<V4BehaviorKind, string> = { meaningful: '✨', wheel: '🎡', fall: '⚠️', closeup: '📸' };
export const V4_BEHAVIOR_KIND_HINTS: Record<V4BehaviorKind, string> = {
  meaningful: '물·허물·밥 등 — 앱 움직임 슬롯 1순위', wheel: '쳇바퀴 — 앱 밤당 1개', fall: '떨어짐 — 수집용, 앱엔 안 감', closeup: '크고 예쁘게 나옴 — 앱 클로즈업 슬롯 1순위',
};
export type V4BehaviorMarks = Record<V4BehaviorKind, V4BehaviorFlag>;
export type V4BehaviorFlagFilter = 'yes' | V4BehaviorKind;
export type V4FeaturedSlot = 'activity' | 'intensity' | 'closeup' | 'wheel';
export const V4_FEATURED_SLOT_LABELS: Record<V4FeaturedSlot, string> = { activity: '움직임', intensity: '격함', closeup: '클로즈업', wheel: '쳇바퀴' };
export const FEATURED_SLOTS = { activity: 2, intensity: 2, closeup: 1 } as const;
export const FEATURED_WHEEL_CAP = 1;
export const FEATURED_CLOSEUP_MIN_SEC = 10;
// V4FeaturedInfo: { tier, day_key, hour_key, slot: V4FeaturedSlot | null, episode_rank: number | null, episode_clip_count: number | null,
//                   episode_activity_sec: number | null, episode_intensity: number | null, intensity: number | null, closeup_sec: number | null, is_representative }
// featuredBadgeText: featured → `⭐ 대표 · ${SLOT_LABEL}` / candidate → '후보'
// featuredLineText: featured → `⭐ 이 날 대표 · ${SLOT_LABEL} 슬롯 · 사건 N클립 · 움직임 N초` + (intensity != null ? ` · 격함 ${intensity}` : '') + (closeup_sec ? ` · 클로즈업 ${closeup_sec}초` : '')
//                   candidate(rep) → `후보 · 사건 …`, candidate(not rep) → `후보 · 같은 사건의 다른 클립 · …`
// V4ClipItem.behavior_kinds: V4BehaviorKind[]; V4ClipDetail.behavior_marks: V4BehaviorMarks
```

(FEATURED_TOP_N·FEATURED_HOUR_CAP 제거.)

- [ ] `labelingV4Server.ts`: `mapBehaviorMarks(rows, resolveName)`(4행→Record), `parseV4ListRequest` 허용값 4종+yes, `mapFeaturedInfo` 새 컬럼(slot 검증: 4값|null), `mapV4ClipRow` 에 `behavior_kinds: []`, `mapFeaturedRowToItem` 에 `highlight.value = row.highlight_value === true`(X 클로즈업 영상은 value false 로 카드에 `하이라이트 X` + `⭐ 대표 · 클로즈업` 이 같이 보임 — 의도).
- [ ] `labelingHotkeys.ts`: `toggle_wheel`(w/W/ㅈ)·`toggle_fall`(d/D/ㅇ)·`toggle_closeup`(p/P/ㅔ), 범례 갱신.
- [ ] `labelingV4Api.ts`: `setV4BehaviorMark(clipId, kind, flagged): Promise<V4BehaviorMarks>`.
- [ ] `_behavior-flag.ts`: `loadBehaviorMarks`, `setBehaviorMark`, `attachBehaviorKinds(items)`; `loadBehaviorFlag` 는 marks.meaningful 위임. `_featured.ts`: 새 RPC 인자(`p_activity_slots…`), `loadFeaturedForClip` 은 O 아닌 클립도 호출(클로즈업 슬롯 가능) → `isCurrentO` 인자 제거.
- [ ] route `behavior-flag`: `{ kind?: V4BehaviorKind = 'meaningful', flagged }` → marks. `clips/route.ts`·`featured/route.ts`: `attachBehaviorKinds`. 상세: `behavior_marks` + `behavior_flag = marks.meaningful`.
- [ ] tests → `npx tsc --noEmit && npx vitest run` PASS → 커밋.

---

### Task 6: 웹 UI

- [ ] `_v4-clip-detail.tsx`: `BehaviorMarkButtons({ marks, busyKind, onToggle, gtHref })` 4개(PC 한 줄·모바일 `grid-cols-2`), `data-testid="behavior-mark-<kind>"`, 체크되면 `🎡 쳇바퀴 · 김라벨 — 눌러서 해제`, 아니면 `🎡 쳇바퀴` + 힌트 한 줄(PC 만). 단축키 F/W/D/P. 상세 `featuredLine` 에 격함·클로즈업 숫자.
- [ ] `_v4-clip-list.tsx`: 칩 4개(`behavior_flag=meaningful|wheel|fall|closeup`), 옛 `yes` 칩 제거(URL 은 계속 동작). 카드: 종류 배지 4종(`item.behavior_kinds`), 대표 배지 `⭐ 대표 · 움직임` 등. `⭐ 대표만` 칩 목록은 slot 순.
- [ ] `_v4-clip-ui.test.tsx`: 배지 4종·슬롯 문구·버튼 4·pressed/busy·칩 4 왕복. PASS → 커밋.

---

### Task 7: 문서

- [ ] 런북 §6.x(4종·kind·배치 RPC), §6.y(v0.2 슬롯·파생 지표·백필 명령·주기 미정), 핸드오프 §3(`slot`·`behavior_kinds`·`highlight_value` 가 false 인 클로즈업 항목 — 앱은 그대로 재생만), `docs/highlight-motion-gaps-options.md` §4 갱신, 결정 로그. `report_highlight_featured.py` 를 슬롯별 개수 표로(`움직임/격함/클로즈업/쳇바퀴`). → 커밋.

---

### Task 8: 배포 게이트 (owner 승인 각각)

- [ ] **① migration A + B 연속 적용**(둘 다 SQL Editor, B 는 DROP 다이얼로그) → 검증: `fn_get_motion_clip_behavior_flags(<✨ clip>)` 4행, 목록 RPC 행 수 불변, `fn_highlight_featured` 새 시그니처 200(지표 없으니 격함·클로즈업 0), 권한.
- [ ] **① 백필**: `uv run python scripts/compute_gme_run_features.py --days 14 --contract gme-motion-v1 <detector> --dry-run` → 건수 확인 → 실제 실행 → `report_highlight_featured.py --days 7` 슬롯별 표(시간대당 ≤5, 격함·클로즈업 채워짐, 쳇바퀴 0).
- [ ] **② fly** → smoke(401·owner JWT 200·`slot`/`behavior_kinds` 키·`featured.slots`).
- [ ] **③ main push** → Vercel Ready → production: 상세 버튼 4·P 단축키·목록 칩 4·배지·`대표만` 슬롯 문구(스크린샷). 결정 로그 배포 기록.
- [ ] 후속 등록(next-session): 새 run 파생 지표 계산 주기(Mac mini launchd 또는 Vercel cron) 결정 · 2.6.1 전환 시 새 계약 run 백필 · 📸 세트 30건 모이면 자동 클로즈업 정답률 측정.

---

## Self-Review

**Spec coverage:** §2 In 0(파생 테이블)=Task 2·3 · 1(4종)=Task 1 · 2(DB)=Task 1 · 3(슬롯)=Task 3 · 4(API)=Task 4 · 5(웹)=Task 5·6 · 6(문서)=Task 7. §0·§0b 확정 전부 반영: wheel_cap 1(Task 3 ④), 추락 무관(정렬·슬롯 어디에도 fall 없음), 앱 무표시(Task 4 필드만), F/W/D/P, 슬롯 2·2·1, X 클로즈업 포함(`x_rows`), 📸 1순위(`close_ranked` 정렬), 항목별 0 허용(다른 슬롯으로 안 채움 — 각 슬롯이 독립 row_number).
**Placeholder scan:** Task 3 Step 3 의 `want3/want4` 는 실행 후 정렬에 맞추되 합격 기준 고정. Task 4·5·6 은 v0.1 코드 대비 차이를 적었고 타입·상수 이름을 명시. TBD 없음.
**Type consistency:** DB 컬럼(`slot text`, `hour_key integer`, `intensity`, `closeup_sec`, `highlight_value`, `behavior_kinds text[]`, `episode_intensity`) ↔ API item(`slot`, `behavior_kinds`, `highlight_value`, `intensity`, `closeup_sec`, `episode.intensity`) ↔ TS `V4FeaturedInfo`. RPC 인자 14개 이름이 Task 3·4·5 에서 동일. `gme_run_features` 컬럼 ↔ `RunFeatures` 필드 ↔ 스크립트 upsert dict 동일.

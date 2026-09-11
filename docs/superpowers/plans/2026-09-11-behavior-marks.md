# 행동 표시 4종 + 대표 예산·다양성 Implementation Plan (v3, 2026-09-11)

> **구현 방식 (CAOF):** Critical 트랙. 3단계로 나눈다 — **1단계(지금)** 표시 4종·하루 예산 15·의심 서명 검수·회귀 세트, **2단계(병행)** 파생 지표 계산 + 블라인드 평가(시험지), **3단계(블라인드 통과 뒤)** 예산 안 다양성 배분 + 정책 버전·노출 로그. 3단계 코드는 2단계 결과를 보고 별도 계획서로 쓴다(지금 쓰면 검증 안 된 기준을 코드로 고정하는 셈).
> v2(시간당 5 슬롯) 는 ChatGPT 검토(2026-09-11)로 폐기 — 총량 증가·검증 안 된 지표 선정 반영·사람 X 의미 미정. 결정 로그 2026-09-11 참조.
> production write 는 게이트에서 owner 승인 뒤에만.

**Goal:** ✨ 하나를 **의미있는 행동·쳇바퀴·추락·📸 예쁘게 나옴** 4개로 넓혀 정답 세트를 모으고, 앱 대표는 **하루·카메라당 15개 예산**(owner 2026-09-11) + 시간당 3 안에서 뽑는다. 격함·클로즈업 지표는 계산만 하고 **블라인드 평가를 통과한 뒤** 선정에 넣는다.

**owner 확정:** 예산 15(임시, 일주일 뒤 조정) · 쳇바퀴 밤당 1 · 추락은 수집용 · 앱 무표시 · 단축키 F/W/D/P. **확인 대기(3단계 전):** 사람 X 영상은 📸 를 직접 찍은 경우에만 클로즈업 후보 재진입(제안).

**건드리지 않는 것:** 하이라이트 O/X 규칙·유지율·표본 `eval-2026-09`, Flutter, `GET /highlights`.

---

## 1단계 — 표시 4종 · 예산 15 · 의심 서명 검수 · 회귀 세트 (하루)

### Task 1: migration A — 표시 4종 + 대표 함수 v0.1.1(집계·예산) + probe

**Context:**
- Depends on: 없음
- Inputs: `2026-09-09_labeling_v4_behavior_flags.sql`, `2026-09-09_labeling_v4_eval_samples.sql`(14-인자 목록), `2026-09-11_highlight_featured_hour_cap.sql`(v0.1)
- Outputs: `migrations/2026-09-11_behavior_marks.sql` = kind 4종·PK·RPC·옛 wrapper·배치 kinds + 목록 14-인자 본문 교체(집계·종류 필터, CREATE OR REPLACE) + **대표 함수 v0.1.1**(DROP+CREATE 12-인자: v0.1 + bf 집계 + `p_day_cap` 15, 반환 컬럼에 `behavior_kinds text[]`)
- Must know: ⚠️ 표시가 영상당 여러 행 → 목록·대표 함수의 `LEFT JOIN … bf` 가 행을 **중복**시키므로 둘 다 LATERAL 집계로(같은 migration 안에서). v0.1.1 의 `flagged`(1위 승격) = `meaningful|wheel|closeup` 중 하나라도(추락 제외). 하루 예산 = 시간당 3 통과한 대표를 사건 순위(ep_rank)로 카메라·하루당 `p_day_cap` 까지. 선정 논리는 그 외 v0.1 과 동일(격함·클로즈업 미반영).
- Acceptance: `uv run pytest tests/test_behavior_marks_migration.py -q` PASS · probe `LABELING_V4_PROBE_OK`

**Files:** Create `migrations/2026-09-11_behavior_marks.sql`, `tests/test_behavior_marks_migration.py`; Modify `scripts/run_labeling_v4_probe.py`

- [ ] **Step 1: 정적 테스트**

```python
"""행동 표시 4종 + 대표 v0.1.1(집계·하루 예산) migration 정적 계약."""
from pathlib import Path
import pytest

SQL_PATH = Path(__file__).resolve().parent.parent / "migrations" / "2026-09-11_behavior_marks.sql"
KINDS = "('meaningful','wheel','fall','closeup')"
OLD_FEAT = "uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer"
NEW_FEAT = "uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer, integer"


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


def test_featured_v011_aggregate_and_day_cap(sql: str) -> None:
    n = norm(sql)
    assert f"drop function public.fn_highlight_featured({OLD_FEAT});" in n
    assert "p_day_cap integer default 15" in n and "behavior_kinds text[]" in n
    assert "(bf.kinds && array['meaningful','wheel','closeup']) as flagged" in n
    assert "array_agg(f.kind order by array_position(array['meaningful','wheel','fall','closeup'], f.kind)) as kinds" in n
    assert "and (p_day_cap is null or h.day_rank <= p_day_cap)" in n
    assert "on rr.run_id is not null" in n and "run_row is not null" not in n
    assert f"grant execute on function public.fn_highlight_featured({NEW_FEAT}) to service_role;" in n
```

- [ ] **Step 2: 실패 확인** — `cd /Users/baek/petcam-lab/.claude/worktrees/highlight-rule-v0 && uv run pytest tests/test_behavior_marks_migration.py -q` → FAIL

- [ ] **Step 3: migration — 테이블·RPC** (v2 Task 1 Step 3 과 동일 SQL: ALTER kind/PK/index, `fn_get_motion_clip_behavior_flags` 4행, 옛 단일 get `kind='meaningful'`, 5-인자 set, 옛 4-인자 위임, `fn_get_motion_clip_behavior_kinds`, REVOKE/GRANT 3쌍 — 그대로 복사)

- [ ] **Step 4: migration — 목록 14-인자 본문 교체(프로그램 변환)** (v2 Task 1 Step 4 의 `REPL` 4개 그대로: 허용값 4종+yes, EXISTS 에 kind 조건, bf LATERAL 집계, CREATE OR REPLACE)

- [ ] **Step 5: migration — 대표 함수 v0.1.1** — `2026-09-11_highlight_featured_hour_cap.sql` 의 CREATE 를 베이스로 아래만 다르게:

```sql
DROP FUNCTION public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer);

CREATE FUNCTION public.fn_highlight_featured(
  p_camera_ids uuid[], p_from timestamptz, p_to timestamptz,
  p_engine_schema_version text, p_algorithm_version text, p_detector_identity text,
  p_top_n integer DEFAULT NULL, p_gap_sec integer DEFAULT 600, p_day_start_hour integer DEFAULT 20,
  p_tz text DEFAULT 'Asia/Seoul', p_hour_cap integer DEFAULT 3,
  p_day_cap integer DEFAULT 15               -- 하루·카메라당 대표 예산(owner 2026-09-11, 임시). NULL = 없음
) RETURNS TABLE ( … v0.1 의 21컬럼 그대로 …, behavior_kinds text[] )
…
  IF p_day_cap IS NOT NULL AND (p_day_cap < 1 OR p_day_cap > 100) THEN
    RAISE EXCEPTION 'invalid day_cap (1..100 or null)' USING ERRCODE = '22023';
  END IF;
…
  -- base: bf 조인을 집계로. flagged = 의미있는 행동·쳇바퀴·📸 중 하나라도(1위 승격, 추락 제외).
           (bf.kinds && ARRAY['meaningful','wheel','closeup']) AS flagged,
           coalesce(bf.kinds, '{}'::text[]) AS kinds
      …
      LEFT JOIN LATERAL (
        SELECT array_agg(f.kind ORDER BY array_position(ARRAY['meaningful','wheel','fall','closeup'], f.kind)) AS kinds
          FROM public.motion_clip_behavior_flags f WHERE f.clip_id = c.id
      ) bf ON true
…
  hour_ranked AS ( … v0.1 그대로 … ),
  -- 하루 예산: 시간당 상한을 통과한 사건을 사건 순위로 다시 세어 p_day_cap 까지.
  day_ranked AS (
    SELECT h.*,
           row_number() OVER (PARTITION BY h.camera_id, h.day_key, (p_hour_cap IS NULL OR h.hour_rank <= p_hour_cap)
                              ORDER BY h.ep_rank)::integer AS day_rank
      FROM hour_ranked h
  )
  SELECT … , h.ep_rank, h.hour_rank,
         CASE WHEN h.rep_clip_id = e.clip_id
                   AND (p_top_n IS NULL OR h.ep_rank <= p_top_n)
                   AND (p_hour_cap IS NULL OR h.hour_rank <= p_hour_cap)
                   AND (p_day_cap IS NULL OR h.day_rank <= p_day_cap)
              THEN 'featured' ELSE 'candidate' END,
         …, e.flagged, e.kinds
    FROM ep e JOIN day_ranked h ON …
REVOKE/GRANT 12-타입.
```

> `day_rank` 의 PARTITION 에 `(hour_rank <= p_hour_cap)` 를 넣어 시간당 상한에 걸린 사건은 예산을 안 먹게 한다.

- [ ] **Step 6: probe** — §15(표시: v2 Task 1 Step 5 그대로 + `closeup` on `rule_x`) + §14 갱신: `feat_call` 을 12-인자(`…, 3, 15)`)로, 기대 열에 `behavior_kinds` 추가, **예산 검사** `p_day_cap=2` 면 21시 사건 중 순위 3 이후가 candidate(21시 4개 + 00시·03시 각 1 = 6 사건 중 2개만 featured), `p_day_cap=null` 이면 §14 원래 기대. 표시 후 순위: h1(🎡)·h2(🎡+⚠️)는 flagged 라 b_flag(✨) 다음(activity 순 h1 14 > h2 13), 추락만 있는 영상은 flagged 아님 — 기대값을 실행 결과에 맞추되 합격 기준(집계 후 행 중복 0·추락 단독은 승격 안 됨·예산 컷) 고정.

- [ ] **Step 7: 실행·커밋** — `feat: 행동 표시 4종 migration + 대표 v0.1.1(표시 집계·하루 예산 15) + probe §14/§15`

### Task 2: jitter 의심 20건 회귀 세트 등록 + "🔎 의심 서명" 칩

**Context:**
- Depends on: 없음(기존 `fn_register_eval_sample`·📌 칩 메커니즘 재사용)
- Inputs: `scratchpad/measure_jitter_share.py` 의 서명(최장 연속 <2s & 구간 ≥30), `motion_clip_eval_samples`, `web/src/lib/labelingV4.ts` `isEvalSampleId`
- Outputs: 표본 `jitter-2026-09`(서명 해당 현재-O 20건, stratum `cam8:jitter`), `experiments/highlight-eval-sample/jitter-2026-09.json`, 목록 칩 `🔎 의심 서명`(`?sample=jitter-2026-09`)
- Must know: 목적은 ① 팀원이 먼저 검수(정지 오탐이면 X+오검출) ② 2.6.1 전후 회귀 비교. `eval-2026-09` 와 **분리**(그건 O/X 재보정용). 등록은 owner 승인 게이트. 칩은 `ACTIVE_EVAL_SAMPLE_ID` 처럼 상수 `JITTER_SAMPLE_ID`.
- Acceptance: `scripts/build_jitter_regression_sample.py --contract … ` 가 JSON 20건 생성(`--register` 는 승인 뒤), vitest 칩 왕복 테스트 PASS

- [ ] `scripts/build_jitter_regression_sample.py`(신규, `build_highlight_eval_sample.py` 골격 재사용: 최근 14일 현재-O 중 서명 해당 → JSON, `--register` 로 `fn_register_eval_sample('jitter-2026-09', items, DEV_USER, true)`).
- [ ] `_v4-clip-list.tsx` 칩 `🔎 의심 서명`(tone neutral, title "정지 게코 bbox 흔들림 의심 — 먼저 검수해 줘. 오탐이면 X + 오검출"), `readFilters/writeFilters` 는 기존 `sampleId` 재사용(값만 다름). 상세 바의 `📌 표본 n/m` 문구는 sampleId 가 jitter 면 `🔎 의심 n/m`.
- [ ] 커밋 `feat: jitter 의심 회귀 세트 스크립트 + 라벨링 웹 의심 서명 칩`

### Task 3: petcam-api — `behavior_kinds` · `p_day_cap`

- [ ] 상수 `FEATURED_DAY_CAP = 15`, RPC 인자 `p_day_cap`, meta `day_cap`, `_to_featured_item` 에 `"behavior_kinds": list(row.get("behavior_kinds") or [])`.
- [ ] 테스트: `_frow` 에 `behavior_kinds`, meta·params·item 검증. PASS → 커밋.

### Task 4: 웹 lib·API·UI — 버튼 4·칩 4·배지·단축키

(v2 Task 5·6 에서 **슬롯 관련만 제외**: `V4FeaturedInfo` 에 `behavior_kinds` 만 추가, `featuredBadgeText` 는 그대로 `⭐ 대표 n위`.)

- [ ] `labelingV4.ts`: `V4BehaviorKind`(4)·라벨·아이콘·힌트(`meaningful: '물·허물·밥 등 — 쳇바퀴·추락·예쁘게는 그쪽 버튼'`, `wheel: '쳇바퀴 탐 — 앱 밤당 1개'`, `fall: '떨어짐 — 수집용, 앱엔 안 감'`, `closeup: '크고 예쁘게 나옴 — 자동 클로즈업 검증용'`)·`V4BehaviorMarks`·`V4BehaviorFlagFilter = 'yes' | V4BehaviorKind`·`FEATURED_DAY_CAP = 15`·`JITTER_SAMPLE_ID = 'jitter-2026-09'`·`V4ClipItem.behavior_kinds`·`V4ClipDetail.behavior_marks`. **미표시 = 미확인**(주석).
- [ ] `labelingV4Server.ts`: `mapBehaviorMarks`(4행→Record), 필터 파서, `mapV4ClipRow.behavior_kinds: []`, `mapFeaturedRowToItem.behavior_kinds`. `labelingHotkeys.ts`: W/D/P. `labelingV4Api.ts`: `setV4BehaviorMark`. `_behavior-flag.ts`: `loadBehaviorMarks`/`setBehaviorMark`/`attachBehaviorKinds`. route body `{kind?, flagged}`. `_featured.ts`: `p_day_cap`. clips/featured route `attachBehaviorKinds`. 상세 `behavior_marks`.
- [ ] `_v4-clip-detail.tsx`: `BehaviorMarkButtons` 4개(PC 한 줄, 모바일 2×2), 단축키, `행동 라벨링 열기 →` 는 어느 종류든. `_v4-clip-list.tsx`: 칩 4(옛 `yes` 칩 제거), 카드 배지 4종, `🔎 의심 서명` 칩(Task 2).
- [ ] tests → `tsc`·`vitest` PASS → 커밋.

### Task 5: 문서 + 게이트 ①②③

- [ ] 런북 §6.x(4종·kind·배치 RPC·미표시=미확인)·§6.y(v0.1.1 예산 15·의심 서명 칩), 핸드오프 §3(`behavior_kinds`·`day_cap`; 앱 무변경), `docs/highlight-motion-gaps-options.md` §4, 결정 로그(ChatGPT 검토 반영·v2 폐기·v3 채택), 슬랙 문구(4버튼·의심 칩).
- [ ] **①** migration 적용 → 검증(4행 get·목록 행 수 불변·`fn_highlight_featured` 12-인자 200·`report_highlight_featured.py --days 7` 하룻밤 ≤15·권한) → jitter 세트 `--register`(owner 승인) → **②** fly → **③** main push·Vercel → production 버튼 4·칩·배지 실측(스크린샷). 결정 로그.

---

## 2단계 — 파생 지표 계산 + 블라인드 평가 (1단계와 병행, 선정 미반영)

### Task 6: 파생 지표 순수 함수·테이블·백필 (v2 Task 2 + 테이블만)

- [ ] `backend/gme_run_features.py` — v2 Task 2 Step 3 정의를 **보강**(ChatGPT 2번): 같은 트랙 연속 관측만·`dt ≤ 1.5s`·화면 종횡비 보정(`dx *= aspect`, aspect 는 아티팩트/run 의 프레임 크기 — 없으면 16:9 가정하고 `feature_version` 에 표기)·박스 크기 평활(폭의 5점 이동중앙값)·유효 구간 < 10 이면 `None`(미정). 지표 이름: `norm_speed_p90`·`norm_speed_top10_mean`·`path_diag`·`visible_big_sec`(면적 ≥ 8% **연속** 최장 구간 초)·`max_area`. 테스트: 정지·직진·클로즈업·스파이크·검출 누락 구간 제외·유효 구간 부족.
- [ ] `migrations/2026-09-12_gme_run_features.sql` — 테이블만(v2 Task 3 의 CREATE TABLE + RLS/GRANT, 컬럼명은 위 이름). 대표 함수 변경 없음.
- [ ] `scripts/compute_gme_run_features.py` — v2 Task 2 Step 4(컬럼명 갱신). `--dry-run` 먼저.
- [ ] 커밋. 게이트: 테이블 migration 적용(owner) → 14일 백필.

### Task 7: 블라인드 평가 시험지 + 실행 (`.claude/rules/research-testing.md` 의무)

- [ ] `experiments/highlight-feature-blind-2026-09/TEST-SHEET.md`(🔒 실행 전): H0 "지표 상위군과 하위군의 사람 평가가 같다". 표본 60건 = 층: 규칙 O/X × `norm_speed_p90` 상/하위 × `visible_big_sec` 상/하위 × 카메라(P4 Cam (dev)/3) + jitter 서명 6건. 점수·배지·대표 여부 **숨김**. 평가자 = owner + 팀원 2. 문항 3(각 1~5): "격하게 움직였다" · "크고 잘 보인다" · "앱에서 보고 싶다". 합격: 각 지표에 대해 상위군 평균 − 하위군 평균 ≥ 1.0 이고 Spearman ≥ 0.5. 평가 화면 = 라벨링 웹에 표본 칩(`blind-2026-09`) + 상세에 3문항 폼(표시·대표 배지 숨김 모드) — 또는 스프레드시트 링크(구현 비용 판단 뒤 결정, 시험지에 명시).
- [ ] 실행 → `REPORT.md`(adopt/hold/reject 지표별) → `experiments/INDEX.md`.
- [ ] 결과에 따라 **3단계 계획서**(예산 15 안 다양성 배분: 시간대 1개씩 먼저 → 점수순 → 종류 상한 격함 ≤4·클로즈업 ≤2·쳇바퀴 ≤1 → 사람 추천 종류 우선, `policy_version`, 노출 로그 `highlight_feed_exposures`, 사건 최대 60분, 사람 X 재진입 규칙 owner 확인) 를 별도로 쓴다.

---

## Self-Review

**Spec coverage:** 스펙 §2 In 0(파생 테이블)=Task 6 · 1·2(표시 4종·DB)=Task 1 · 3(대표 선정)=1단계는 v0.1.1(집계·예산)까지만, 다양성 배분은 3단계 계획서 · 4(API)=Task 3 · 5(웹)=Task 4 · 6(문서)=Task 5. owner 확정: 예산 15(Task 1 Step 5·Task 3·Task 4 상수), 쳇바퀴 밤당 1·격함/클로즈업 슬롯은 3단계로 이월(스펙 §0b 에 "3단계" 표기 필요 → Task 5 문서에서 갱신).
**Placeholder scan:** Task 1 Step 3·4 는 v2 계획서의 완전한 SQL/코드를 참조("그대로 복사") — 그 v2 본문은 git 이력(`01b79ce`)에 있으므로 구현자는 `git show 01b79ce:docs/superpowers/plans/2026-09-11-behavior-marks.md` 로 꺼낸다. 3단계는 의도적으로 미작성(검증 전 고정 금지).
**Type consistency:** `behavior_kinds text[]`(DB) ↔ `behavior_kinds: list`(API) ↔ `V4BehaviorKind[]`(TS). `p_day_cap`/`FEATURED_DAY_CAP`/`day_cap` 15 세 곳. 지표 컬럼명(`norm_speed_p90`, `norm_speed_top10_mean`, `path_diag`, `visible_big_sec`, `max_area`) 은 함수·테이블·스크립트 동일.

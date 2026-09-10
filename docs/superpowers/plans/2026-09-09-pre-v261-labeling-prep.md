# 2.6.1 전 라벨링 준비 3종 Implementation Plan

> **구현 방식 (CAOF):** Standard 트랙 — 메인이 task 순서대로 직접 구현한다. Steps use checkbox (`- [ ]`) syntax for tracking.
> production write(migration 적용·표본 등록)는 각 Task 의 **승인 게이트**에서 owner 승인 뒤에만.

**Goal:** GME 2.6.1 은 학습이 끝나면 **무조건 전체 적용**한다(owner 결정 2026-09-08). 그 전환을 숫자로 운영할 도구(활성 계약 커버리지)와 팀 가동 첫 주 마찰 제거(영상 503 재시도)를 먼저 갖추고, 전환 당일 규칙 숫자(10초/5초)를 바로 재보정할 수 있게 사람 O/X 가 붙은 봉인 표본을 만든다. 표본은 검출기 채택 판정용이 아니라 **규칙 재보정 기준선**이다.

**Architecture:** ① 표본은 DB 테이블(`motion_clip_eval_samples`) + 목록 RPC 14-인자 오버로드(`p_sample_id`) + 목록/이어서/다음 필터로 흐른다. 층화 무작위 추출은 읽기 전용 스크립트가 후보를 뽑아 JSON 으로 남기고, 등록 RPC 는 owner 승인 뒤 한 번만 호출한다. ② 503 재시도는 `ReviewVideo` 안에서 지수 백오프 3회 → 실패 시 "다시 시도" 버튼이 서명 URL 을 새로 받는다. ③ 커버리지는 읽기 전용 RPC 한 개를 owner 현황 JSON 에 붙인다.

**Tech Stack:** PostgreSQL(plpgsql, RPC 전용 테이블 패턴) · Next.js 14 App Router · vitest SSR 테스트 · 일회용 PostgreSQL probe(`scripts/run_labeling_v4_probe.py`) · supabase-py 읽기 전용 스크립트.

**순서·규모 (2026-09-08 owner 확정):** Task 7(커버리지, 2h) → Task 6(503 재시도, 2~3h) → Task 1~5(표본, 반나절). 각 Task 끝에 커밋. migration 은 Task 7·1 두 개. Task 4 보고에 임계값 후보별(예 8/4·10/5·12/6) 수용률·놓침률 표를 넣어 전환 당일 규칙 v1 근거로 쓴다. Task 6 에 영상 오류 서버 로그 한 줄(clip·시각·몇 번째 재시도에 성공)을 포함한다.

**건드리지 않는 것:** 규칙 파라미터·트리거 on/off(`hl-rule-v0` 불변), 확정 원장 스키마, 앱 API(`/highlights`), 2.6.1 계약 전환(env).

---

## File Structure

| 파일 | 책임 |
|---|---|
| `migrations/2026-09-09_labeling_v4_eval_samples.sql` (신규) | `motion_clip_eval_samples` 테이블, `fn_register_eval_sample`, `fn_eval_sample_progress`, `fn_eval_sample_report`, 14-인자 `fn_list_labeling_v4_clips` + 13-인자 위임 wrapper |
| `migrations/2026-09-09_gme_contract_coverage.sql` (신규) | `fn_gme_contract_coverage` 읽기 전용 |
| `scripts/run_labeling_v4_probe.py` | §11 표본 케이스, §12 커버리지 케이스 추가 |
| `scripts/build_highlight_eval_sample.py` (신규) | 층화 무작위 후보 추출 → `experiments/highlight-eval-sample/<id>.json` (읽기 전용, 등록은 `--register` 플래그 + 승인) |
| `scripts/report_highlight_eval_sample.py` (신규) | 표본 O/X 확정 현황·층별 수용/놓침 표 |
| `web/src/lib/labelingV4.ts` | `V4ListFilters.sampleId`, `V4EvalSampleProgress` 타입, `V4Overview.coverage` |
| `web/src/lib/labelingV4Server.ts` | `parseV4ListRequest` 에 `sample` 파라미터 |
| `web/src/lib/labelingV4Api.ts` | `getV4Clips` 쿼리 `sample`, `getV4Continue(scope, cams, sampleId)`, `getV4NextClip(id, sampleId)`, `getV4EvalSampleProgress(id)` |
| `web/src/app/api/labeling-v4/clips/route.ts` · `continue/route.ts` · `clips/[clipId]/next/route.ts` | `p_sample_id` 전달 |
| `web/src/app/api/labeling-v4/eval-sample/[sampleId]/route.ts` (신규) | GET progress |
| `web/src/app/api/labeling-v4/owner/overview/route.ts` | coverage RPC 합류 |
| `web/src/app/labeling/_v4-clip-list.tsx` | `평가 표본` 칩(`?sample=`), ProgressRow 에 표본 진행 |
| `web/src/app/labeling/v4/_v4-clip-detail.tsx` | sessionStorage `labeling.v4.sample` 로 next/continue 표본 유지, 바에 `표본 57/200` |
| `web/src/app/labeling/_review-video.tsx` | 재시도(백오프 3회) + `onRetryExhausted` |
| `web/src/lib/videoRetry.ts` (신규) | `nextRetryDelayMs(attempt)` 순수 |
| `web/src/app/labeling/owner/_owner-overview-view.tsx` | 커버리지 한 줄 |
| `specs/feature-highlight-auto-initial-designation.md` · `docs/highlight-rule-operations.md` | 표본 절차·커버리지 읽는 법 |

---

### Task 1: 표본 테이블·RPC migration + probe

**Context:**
- Depends on: 없음
- Inputs: 기존 13-인자 `fn_list_labeling_v4_clips`(`migrations/2026-09-09_labeling_v4_behavior_flags.sql`), 검수 원장 `motion_clip_highlight_verdicts`
- Outputs: 테이블 1, RPC 3, 목록 함수 14-인자 오버로드 + 13-인자 wrapper
- Must know: 테이블은 RPC 전용(service_role 직접 권한 없음, RLS on). 목록 함수는 13-인자를 wrapper 로 남겨 migration→웹 배포 사이 무중단(behavior_flags migration 과 같은 수법). `p_sample_id` 는 chunk WHERE 에서 EXISTS 로 걸러야 전체 스캔이 안 된다.
- Acceptance: `nice -n 10 uv run python scripts/run_labeling_v4_probe.py --pg-bin /opt/homebrew/opt/postgresql@15/bin` → `LABELING_V4_PROBE_OK`

**Files:**
- Create: `migrations/2026-09-09_labeling_v4_eval_samples.sql`
- Modify: `scripts/run_labeling_v4_probe.py`

- [ ] **Step 1: migration 작성**

```sql
BEGIN;
CREATE TABLE public.motion_clip_eval_samples (
  sample_id text NOT NULL,
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  stratum text NOT NULL,                 -- 예: '5b3ea7aa:O' (camera8:규칙 initial)
  registered_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  registered_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (sample_id, clip_id)
);
CREATE INDEX idx_motion_clip_eval_samples_clip ON public.motion_clip_eval_samples (clip_id);
ALTER TABLE public.motion_clip_eval_samples ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.motion_clip_eval_samples FROM PUBLIC, anon, authenticated, service_role;

-- 등록: owner 만(p_is_owner), 운영 적격 clip 만, 이미 있는 (sample, clip) 은 무시. 등록 수 반환.
CREATE FUNCTION public.fn_register_eval_sample(p_sample_id text, p_items jsonb, p_actor uuid, p_is_owner boolean)
RETURNS integer LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_n integer := 0; v_item jsonb;
BEGIN
  IF NOT coalesce(p_is_owner,false) THEN RAISE EXCEPTION 'owner only' USING ERRCODE='PT403'; END IF;
  IF p_sample_id IS NULL OR p_sample_id !~ '^[a-z0-9-]{3,40}$' THEN RAISE EXCEPTION 'invalid sample id' USING ERRCODE='22023'; END IF;
  IF jsonb_typeof(p_items) <> 'array' THEN RAISE EXCEPTION 'items must be array' USING ERRCODE='22023'; END IF;
  FOR v_item IN SELECT * FROM jsonb_array_elements(p_items) LOOP
    IF NOT public.fn_is_motion_clip_production_labeling_eligible((v_item->>'clip_id')::uuid) THEN CONTINUE; END IF;
    INSERT INTO public.motion_clip_eval_samples (sample_id, clip_id, stratum, registered_by)
    VALUES (p_sample_id, (v_item->>'clip_id')::uuid, coalesce(v_item->>'stratum','?'), p_actor)
    ON CONFLICT DO NOTHING;
    IF FOUND THEN v_n := v_n + 1; END IF;
  END LOOP;
  RETURN v_n;
END $$;

-- 진행: 표본 전체 / 사람 확정 수.
CREATE FUNCTION public.fn_eval_sample_progress(p_sample_id text)
RETURNS TABLE (total bigint, labeled bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT count(*), count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM public.motion_clip_highlight_verdicts v WHERE v.clip_id = s.clip_id AND v.kind='initial'))
    FROM public.motion_clip_eval_samples s WHERE s.sample_id = p_sample_id;
$$;

-- 보고: 층별 n · 규칙 initial · 사람 O 수 (최초 initial verdict 기준, 정정은 별도 열).
CREATE FUNCTION public.fn_eval_sample_report(p_sample_id text)
RETURNS TABLE (stratum text, total bigint, labeled bigint, rule_o bigint, human_o bigint, o_to_o bigint, o_to_x bigint, x_to_o bigint, x_to_x bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT s.stratum, count(*), count(v.id),
         count(*) FILTER (WHERE v.initial = true), count(*) FILTER (WHERE v.verdict = true),
         count(*) FILTER (WHERE v.initial = true AND v.verdict = true),
         count(*) FILTER (WHERE v.initial = true AND v.verdict = false),
         count(*) FILTER (WHERE v.initial = false AND v.verdict = true),
         count(*) FILTER (WHERE v.initial = false AND v.verdict = false)
    FROM public.motion_clip_eval_samples s
    LEFT JOIN public.motion_clip_highlight_verdicts v ON v.clip_id = s.clip_id AND v.kind = 'initial'
   WHERE s.sample_id = p_sample_id
   GROUP BY s.stratum ORDER BY s.stratum;
$$;
```

이어서 14-인자 `fn_list_labeling_v4_clips`: behavior_flags migration 의 13-인자 본문을 그대로 복사하고 시그니처에 `p_sample_id text` 를 `p_behavior_flag` 뒤에 추가, 검증 `IF p_sample_id IS NOT NULL AND p_sample_id !~ '^[a-z0-9-]{3,40}$' THEN RAISE ... '22023'`, chunk WHERE 에 한 줄:

```sql
           AND (p_sample_id IS NULL
                OR EXISTS (SELECT 1 FROM public.motion_clip_eval_samples s WHERE s.sample_id = p_sample_id AND s.clip_id = c.id))
```

13-인자 시그니처는 `CREATE OR REPLACE ... LANGUAGE sql` wrapper 로 14-인자에 `NULL::text` 를 넘긴다(반환 컬럼 동일). GRANT/REVOKE 는 새 함수 4개 + 14-인자 목록에 service_role 전용. `COMMIT;`

- [ ] **Step 2: probe §11 추가** (`scripts/run_labeling_v4_probe.py`, `LABELING_V4_PROBE_OK` 직전)

```python
            # 11) 평가 표본: owner 등록(비적격 clip 은 건너뜀) → 14-인자 목록 p_sample_id 필터 → 진행/보고 → 라벨러 등록 PT403
            items = f"[{{\"clip_id\":\"{CLIP['include']}\",\"stratum\":\"a:O\"}},{{\"clip_id\":\"{CLIP['short']}\",\"stratum\":\"b:X\"}},{{\"clip_id\":\"{CLIP['test_purpose']}\",\"stratum\":\"z\"}}]"
            expect("sample-register", q(f"select 'n|'||public.fn_register_eval_sample('eval-probe', '{items}'::jsonb, '{OWNER}', true)::text;"), n="2")
            require_sqlstate(sql(db, f"select public.fn_register_eval_sample('eval-probe', '[]'::jsonb, '{LABELER}', false);"), "sample-labeler", "PT403")
            sample_ids = require_ok(sql(db, f"select clip_id from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, null, 'eval-probe', '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50);"), "list-sample").splitlines()
            if set(sample_ids) != {CLIP['include'], CLIP['short']}:
                raise ProbeError(f"list-sample: {sample_ids}")
            expect("sample-progress", q("select 'total|'||total::text||'' from public.fn_eval_sample_progress('eval-probe');"), total="2")
            expect("sample-report", q("select 'labeled|'||sum(labeled)::text from public.fn_eval_sample_report('eval-probe');"), labeled="1")  # short 는 §4 에서 확정됨
```

MIGRATIONS 목록에 `V4_EVAL_SAMPLES_MIGRATION` 추가(`V4_VIEW_CLAIMS_MIGRATION` 뒤).

- [ ] **Step 3: probe 실행** — `nice -n 10 uv run python scripts/run_labeling_v4_probe.py --pg-bin /opt/homebrew/opt/postgresql@15/bin` → `LABELING_V4_PROBE_OK`. 실패면 kv 파싱(`|` 첫 분리)·CLIP 상태 순서를 먼저 의심.

- [ ] **Step 4: 커밋** — `git add migrations/2026-09-09_labeling_v4_eval_samples.sql scripts/run_labeling_v4_probe.py && git commit -m "feat: 하이라이트 평가 표본 테이블·RPC + 목록 표본 필터 (migration·probe)"`

---

### Task 2: 웹 표본 필터 (목록·이어서·다음·상세 진행)

**Context:**
- Depends on: Task 1 (시그니처 확정)
- Inputs: `?sample=<id>` URL 필터, `labelingV4Prefetch`·`labelingV4Progress` 기존 구조
- Outputs: 목록 칩, ProgressRow 표본 진행, continue/next 가 표본 안에서만, 상세 바 `표본 57/200`
- Must know: 목록 필터의 SOT 는 URL(`readFilters/writeFilters`). 상세는 URL 에 표본이 없으므로 sessionStorage `labeling.v4.sample` 로 넘긴다(목록에서 칩을 끄면 지운다). `sample` 값 검증은 서버 `parseV4ListRequest` 에서 `^[a-z0-9-]{3,40}$` fail-closed.
- Acceptance: `cd web && npx vitest run src/app/labeling/_v4-clip-ui.test.tsx src/app/api/labeling-v4/clips/route.test.ts src/lib/labelingV4Server.test.ts` 통과, `npx tsc --noEmit -p tsconfig.json` 0

**Files:**
- Modify: `web/src/lib/labelingV4.ts`, `web/src/lib/labelingV4Server.ts`(+test), `web/src/lib/labelingV4Api.ts`, `web/src/app/api/labeling-v4/clips/route.ts`(+test), `web/src/app/api/labeling-v4/continue/route.ts`, `web/src/app/api/labeling-v4/clips/[clipId]/next/route.ts`(+test), `web/src/app/labeling/_v4-clip-list.tsx`, `web/src/app/labeling/v4/_v4-clip-detail.tsx`, `web/src/app/labeling/_v4-clip-ui.test.tsx`
- Create: `web/src/app/api/labeling-v4/eval-sample/[sampleId]/route.ts`(+test)

- [ ] **Step 1: 실패 테스트** — `labelingV4Server.test.ts` 에 `parseV4ListRequest(new URLSearchParams('scope=all&sample=eval-2026-09'))` → `sampleId: 'eval-2026-09'`, `sample=BAD!` → throw. `_v4-clip-ui.test.tsx` 에 `writeFilters({..., sampleId: 'eval-2026-09'})` → `sample=eval-2026-09` 왕복. 실행해 FAIL 확인.

- [ ] **Step 2: 타입·파서·API 클라이언트**

```ts
// labelingV4.ts
export const EVAL_SAMPLE_ID_RE = /^[a-z0-9-]{3,40}$/;
export interface V4EvalSampleProgress { sample_id: string; total: number; labeled: number }
// V4ListFilters: sampleId?: string | null;
// labelingV4Server.ts parseV4ListRequest:
const sample = sp.get('sample');
if (sample !== null && !EVAL_SAMPLE_ID_RE.test(sample)) throw new Error('invalid_sample');
// return 에 sampleId: sample,
// labelingV4Api.ts: v4ListQuery 에 if (f.sampleId) sp.set('sample', f.sampleId);
export async function getV4Continue(scope: V4Scope, cameraIds: string[], sampleId: string | null = null) { /* sp.set('sample', sampleId) */ }
export async function getV4NextClip(clipId: string, sampleId: string | null = null) { /* `/next?sample=` */ }
export function getV4EvalSampleProgress(id: string): Promise<V4EvalSampleProgress> { return request(`/api/labeling-v4/eval-sample/${id}`); }
```

- [ ] **Step 3: 라우트 3개에 `p_sample_id`** — clips/continue: `parsed.sampleId`. next: `req.nextUrl.searchParams.get('sample')` 를 같은 정규식으로 검증(잘못되면 400), RPC 호출에 `p_sample_id`. 테스트의 `toHaveBeenCalledWith` 객체에 `p_sample_id: null` 추가.

- [ ] **Step 4: 진행 라우트** — `eval-sample/[sampleId]/route.ts`: `requireLabelingAccess` → id 정규식 → `rpc('fn_eval_sample_progress', { p_sample_id })` → `{ sample_id, total, labeled }`. 테스트 2건(정상·잘못된 id 400).

- [ ] **Step 5: 목록 UI** — `UrlFilters.sampleId`, 칩 `📌 평가 표본` (`filters.sampleId ? 끄기 : ?sample=<현재 활성 표본>`). 활성 표본 id 는 env `NEXT_PUBLIC_LABELING_EVAL_SAMPLE_ID`(없으면 칩 숨김). 칩 켜면 `sessionStorage.setItem('labeling.v4.sample', id)`, 끄면 remove. ProgressRow 에 `sampleProgress?: V4EvalSampleProgress | null` → `표본 57/200 확정`. `continueLabeling` 은 `getV4Continue(scope, cams, filters.sampleId)`.

- [ ] **Step 6: 상세** — `const sampleId = sessionStorage.getItem('labeling.v4.sample')`(effect). `goNext`·프리페치의 `getV4NextClip(detail.id, sampleId)`. 확정 성공 시 `setSampleProgress(p => p && {...p, labeled: p.labeled+1})`. 바 요약 오른쪽 `progressText` 에 ` · 표본 58/200` 이어붙임.

- [ ] **Step 7: 테스트 통과 확인 → 커밋** — `git commit -m "feat: 평가 표본 필터 — 목록 칩·이어서·다음·상세 진행"`

---

### Task 3: 층화 무작위 추출 스크립트 (읽기 전용) + 등록 게이트

**Context:**
- Depends on: Task 1 (등록 RPC)
- Inputs: production 읽기(service role): 최근 14일 `motion_clips`(r2_key, thumbnail 무관), 활성 계약 run 존재, 사람 확정 없음, 규칙 initial(O/X)
- Outputs: `experiments/highlight-eval-sample/eval-2026-09.json`(clip_id, camera, initial, started_at, stratum, seed) + `--register` 시 등록 수 출력
- Must know: 규칙 initial 은 목록 RPC(`highlight_state` yes/no, limit 101 페이징)로 읽으면 clip 별 RPC 호출이 없다. 층화: 카메라 × initial(O/X). 카메라별 목표 = min(후보, 60)(O 30·X 30), 후보가 적은 카메라는 있는 만큼(보고서에 실제 n). seed 고정(`--seed 20260909`). **등록(`--register`)은 production write — owner 승인 문구 뒤에만 실행.** 표본 id 는 `eval-2026-09`.
- Acceptance: `uv run python scripts/build_highlight_eval_sample.py --sample-id eval-2026-09 --days 14 --seed 20260909` → JSON 생성, 표준출력에 층별 n 표. `--register` 없이 write 0.

**Files:**
- Create: `scripts/build_highlight_eval_sample.py`, `experiments/highlight-eval-sample/README.md`(표본 정의·seed·층화 규칙·"기존 확정 재작성 금지")

- [ ] **Step 1: 스크립트**

```python
"""하이라이트 평가 표본 층화 무작위 추출(읽기 전용). --register 만 write(owner 승인 뒤)."""
import argparse, json, os, random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
DEV = os.environ["DEV_USER_ID"]

def active_contract():
    j = sb.table("gme_jobs").select("algorithm_version,detector_identity").eq("status","succeeded").order("created_at", desc=True).limit(1).execute().data[0]
    env_a, env_d = os.environ.get("GME_ACTIVE_ALGORITHM_VERSION"), os.environ.get("GME_ACTIVE_DETECTOR_IDENTITY")
    return (env_a or j["algorithm_version"]), (env_d or j["detector_identity"])

def list_page(state, cam, cursor, algo, det):
    return sb.rpc("fn_list_labeling_v4_clips", {"p_viewer_id": DEV, "p_is_owner": True, "p_scope": "all", "p_camera_ids": [cam],
        "p_label_state": "unlabeled", "p_highlight_state": state, "p_behavior_flag": None,
        "p_engine_schema_version": "gme-shadow-v1", "p_algorithm_version": algo, "p_detector_identity": det,
        "p_cursor_started_at": cursor[0] if cursor else None, "p_cursor_id": cursor[1] if cursor else None, "p_limit": 101}).execute().data

def candidates(days, algo, det):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cams = [c["id"] for c in sb.table("cameras").select("id").execute().data]
    out = defaultdict(list)  # (cam8, 'O'|'X') -> rows
    for cam in cams:
        for state, tag in (("yes","O"),("no","X")):
            cursor = None
            while True:
                rows = list_page(state, cam, cursor, algo, det)
                keep = [r for r in rows if r["started_at"] >= since and r["highlight_source"] == "rule"]
                out[(cam[:8], tag)].extend(keep)
                if len(rows) < 101 or (rows and rows[-1]["started_at"] < since): break
                cursor = (rows[-1]["started_at"], rows[-1]["clip_id"])
    return out

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--sample-id", required=True); ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--seed", type=int, default=20260909); ap.add_argument("--per-stratum", type=int, default=30); ap.add_argument("--register", action="store_true")
    a = ap.parse_args(); rnd = random.Random(a.seed); algo, det = active_contract()
    picked = []
    for (cam8, tag), rows in sorted(candidates(a.days, algo, det).items()):
        chosen = rnd.sample(rows, min(len(rows), a.per_stratum))
        print(f"{cam8}:{tag} 후보 {len(rows)} → 표본 {len(chosen)}")
        picked += [{"clip_id": r["clip_id"], "stratum": f"{cam8}:{tag}", "camera_id": r["camera_id"], "started_at": r["started_at"], "initial": tag} for r in chosen]
    out = ROOT / "experiments" / "highlight-eval-sample" / f"{a.sample_id}.json"; out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"sample_id": a.sample_id, "seed": a.seed, "days": a.days, "contract": {"algorithm_version": algo, "detector_identity": det}, "items": picked}, ensure_ascii=False, indent=1))
    print("wrote", out, "n=", len(picked))
    if a.register:
        n = sb.rpc("fn_register_eval_sample", {"p_sample_id": a.sample_id, "p_items": [{"clip_id": p["clip_id"], "stratum": p["stratum"]} for p in picked], "p_actor": DEV, "p_is_owner": True}).execute().data
        print("registered", n)

if __name__ == "__main__": main()
```

- [ ] **Step 2: dry-run** — `--register` 없이 실행해 층별 n 표 확인. 카메라 `5b3ea7aa`(P4 Cam (dev)) 외 3대는 최근 14일 후보가 적을 것(09-05 이후 12·14건) — 그대로 보고, 표본 크기를 억지로 맞추지 않는다.
- [ ] **Step 3: 커밋(JSON 포함)** — `git commit -m "feat: 하이라이트 평가 표본 층화 추출 스크립트 + eval-2026-09 후보"`
- [ ] **Step 4: 🚦 승인 게이트** — owner 에게 층별 n 표와 JSON 경로를 보이고 "등록 승인" 뒤에만 `--register`. 등록 수를 `docs/decision-gate.md` 에 append.

---

### Task 4: 표본 보고 스크립트

**Context:**
- Depends on: Task 1 (`fn_eval_sample_report`)
- Inputs: `--sample-id`
- Outputs: 층별 `n · 확정 · 규칙O · 사람O · O→O/O→X/X→O/X→X` 표 + 합계 + 모집단 가중 수용률/놓침률(층 비중 = 후보 수 비율, JSON 의 후보 수 사용)
- Must know: 단순 합산 회수율은 보고하지 않는다(그쪽 문서 §4.2). 표본 밖 확정과 섞지 않는다.
- Acceptance: `uv run python scripts/report_highlight_eval_sample.py --sample-id eval-2026-09` 가 표 출력, write 0.

- [ ] **Step 1: 스크립트** — RPC 호출 → 표 출력 → `experiments/highlight-eval-sample/<id>-report-<date>.md` 저장. 2.6.1 비교 때 같은 표본에 새 계약 run 의 initial 을 붙여 `rule_o(v2.6) vs rule_o(v2.6.1) vs human_o` 3열 표를 만드는 `--compare-contract <algo> <detector>` 옵션은 **이번 범위 밖**(2.6.1 run 이 생긴 뒤 별 Task).
- [ ] **Step 2: 커밋**

---

### Task 5: 문서·Slack 문구

- [ ] `specs/feature-highlight-auto-initial-designation.md` §운영에 "봉인 표본 eval-2026-09: 층화 규칙·seed·등록일·재작성 금지·2.6.1 비교 절차" 추가
- [ ] `docs/highlight-rule-operations.md` §3 앞에 "표본 확정이 끝나기 전엔 유지율로 규칙을 바꾸지 않는다" 한 줄, §5 에 `fn_eval_sample_report` SQL
- [ ] Slack 초안에 "목록 위 `📌 평가 표본` 칩을 켜고 그것부터 확정해 주세요(약 N개)" 한 줄
- [ ] 커밋 → push → Vercel Ready 확인 → production 에서 칩·진행 수 실측(owner 계정)

---

### Task 6: 영상 503 재시도

**Context:**
- Depends on: 없음
- Inputs: `ReviewVideo` 의 `onError`, `_v4-clip-detail` 의 `getV4FileUrl`
- Outputs: 오류 시 1s·2s·4s 백오프로 `video.load()` 3회 → 그래도 실패면 영상 자리에 `영상을 못 불러왔어 · 다시 시도` 버튼 → 서명 URL 재발급 후 재생
- Must know: R2 가 같은 서명 URL 에 503 을 간헐적으로 준다(2026-09-08 실측, 재요청은 206 성공). 재시도는 같은 URL 로, 마지막 수동 버튼만 URL 을 새로 받는다(만료 대비). ReviewVideo 는 motion/library 등 공용이라 기본값이 기존 동작(재시도 0)이어야 한다 — `retry?: { attempts: number }` 옵션이 있을 때만 켠다.
- Acceptance: `npx vitest run src/lib/videoRetry.test.ts src/app/labeling/_review-video.test.tsx` 통과. 로컬에서 `video.dispatchEvent(new Event('error'))` 3회 뒤 버튼 노출 실측.

**Files:**
- Create: `web/src/lib/videoRetry.ts`, `web/src/lib/videoRetry.test.ts`
- Modify: `web/src/app/labeling/_review-video.tsx`, `web/src/app/labeling/v4/_v4-clip-detail.tsx`, `web/src/app/labeling/_review-video.test.tsx`

- [ ] **Step 1: 순수 함수 + 테스트**

```ts
// videoRetry.ts
export const VIDEO_RETRY_MAX = 3;
export function nextRetryDelayMs(attempt: number): number | null {  // attempt: 0-based 실패 횟수
  return attempt >= VIDEO_RETRY_MAX ? null : 1000 * 2 ** attempt;  // 1s, 2s, 4s
}
```
테스트: `[0,1,2,3] → [1000,2000,4000,null]`.

- [ ] **Step 2: ReviewVideo** — props `retry?: { onExhausted: () => void }`. 내부 `attemptRef`; `onError` 핸들러에서 `retry` 있으면 `const d = nextRetryDelayMs(attemptRef.current++)`; `d !== null` 이면 `setTimeout(() => video.load(), d)` 아니면 `retry.onExhausted()`. 성공(`onCanPlay`)하면 `attemptRef.current = 0`. 기존 `onError` prop 은 그대로 호출. 언마운트 시 타이머 정리.

- [ ] **Step 3: 상세** — `const [videoBroken, setVideoBroken] = useState(false)`; `retry={{ onExhausted: () => setVideoBroken(true) }}`. `videoBroken` 이면 영상 자리 Card: `영상을 못 불러왔어(저장소 일시 오류일 수 있어)` + `Button 다시 시도` → `getV4FileUrl(id)` 로 `setVideoUrl(새 url)`, `setVideoBroken(false)`. 확정 버튼은 그대로 활성(영상 없이도 판정 가능 정책 유지).

- [ ] **Step 4: 테스트·실측·커밋** — `git commit -m "feat: 영상 로드 실패 자동 재시도(1·2·4s) + 다시 시도 버튼"`

---

### Task 7: 활성 계약 커버리지 한 줄

**Context:**
- Depends on: 없음
- Inputs: 활성 계약(env), `gme_jobs(status='succeeded', identity)`, `motion_clips(r2_key not null)`
- Outputs: owner 현황 `활성 GME 계약 커버리지: 최근 7일 100% (1,006/1,006) · 전체 47% (12,530/26,761)`
- Must know: 2026-09-08 실측으로 8/27 이후 100%, 이전 43%. 계약 전환 뒤 이 줄이 "최근 7일 0%" 로 떨어지는 게 정상이며, 백필이 채워질수록 오른다 — 전환 타이밍 판단용. count 는 jobs.succeeded 와 clips 를 identity 로 join(전체 26k, 1초 안팎; overview 와 같은 빈도로만 호출).
- Acceptance: probe §12 통과, `npx vitest run src/app/api/labeling-v4/owner/overview/route.test.ts src/app/labeling/_v4-clip-ui.test.tsx` 통과, production RPC 실측 값이 2026-09-08 수치와 정합.

**Files:**
- Create: `migrations/2026-09-09_gme_contract_coverage.sql`
- Modify: `scripts/run_labeling_v4_probe.py`, `web/src/lib/labelingV4.ts`(`V4Overview.coverage`), `web/src/app/api/labeling-v4/owner/overview/route.ts`(+test), `web/src/app/labeling/owner/_owner-overview-view.tsx`, `web/src/app/labeling/_v4-clip-ui.test.tsx`

- [ ] **Step 1: migration**

```sql
BEGIN;
CREATE FUNCTION public.fn_gme_contract_coverage(p_engine_schema_version text, p_algorithm_version text, p_detector_identity text)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  WITH c AS (
    SELECT c.id, c.started_at,
           EXISTS (SELECT 1 FROM public.gme_jobs j WHERE j.clip_id = c.id AND j.status = 'succeeded'
                     AND j.engine_schema_version = p_engine_schema_version
                     AND j.algorithm_version = p_algorithm_version AND j.detector_identity = p_detector_identity) AS has_run
      FROM public.motion_clips c WHERE c.r2_key IS NOT NULL)
  SELECT jsonb_build_object(
    'last7d_total', count(*) FILTER (WHERE started_at >= now() - interval '7 days'),
    'last7d_with_run', count(*) FILTER (WHERE started_at >= now() - interval '7 days' AND has_run),
    'all_total', count(*), 'all_with_run', count(*) FILTER (WHERE has_run)) FROM c;
$$;
REVOKE ALL ON FUNCTION public.fn_gme_contract_coverage(text,text,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_gme_contract_coverage(text,text,text) TO service_role;
COMMIT;
```

- [ ] **Step 2: probe §12** — setup 의 job/run 구성상 활성 identity run 있는 clip 수를 기대값으로(`all_with_run`), `pending` clip 은 제외됨을 확인.
- [ ] **Step 3: overview 라우트** — `Promise.all([overview rpc, coverage rpc])`; 응답에 `coverage: { last7d_total, last7d_with_run, all_total, all_with_run }`(숫자 정규화). 테스트: rpc 두 번 호출·정규화.
- [ ] **Step 4: 뷰** — `OwnerOverviewView` 첫 카드 아래 한 줄: `활성 GME 계약 커버리지 · 최근 7일 {pct}% ({n}/{d}) · 전체 {pct}% ({n}/{d})` + 회색 설명 `계약(algorithm/detector) 전환 직후엔 최근 7일이 0% 로 떨어지는 게 정상 — 백필이 찰수록 오른다`. 테스트 1건.
- [ ] **Step 5: 🚦 migration 승인 → SQL Editor 적용 → RPC 실측(값이 100%/47% 근처) → 커밋·push·배포 → owner 화면 확인**

---

## Self-Review

- **Spec coverage:** 표본(테이블·RPC·목록/이어서/다음 필터·상세 진행·추출·보고·문서) / 503 재시도(순수 함수·ReviewVideo·상세 버튼) / 커버리지(RPC·overview·뷰) — 추천 3종 전부 Task 로 있음. "나중에" 로 뺀 규칙 튜닝·2.6.1 비교(`--compare-contract`)는 범위 밖으로 명시.
- **Placeholder scan:** 코드 없는 단계 없음. 14-인자 목록 함수 본문은 기존 13-인자 파일 복사 지시로 대체(동일 본문 반복 회피, 파일 경로 명시).
- **Type consistency:** `V4ListFilters.sampleId` ↔ `parseV4ListRequest().sampleId` ↔ RPC `p_sample_id`; `V4EvalSampleProgress{ sample_id,total,labeled }` ↔ `fn_eval_sample_progress(total,labeled)`; `V4Overview.coverage` 4개 키 ↔ `fn_gme_contract_coverage` 4개 키; `retry.onExhausted` ↔ 상세 `setVideoBroken`.
- **승인 게이트 2곳:** Task 3 Step 4(표본 등록 write), Task 7 Step 5(migration). Task 1 migration 도 production 적용은 Task 5 배포 직전 승인.

# GME 탐지 영상 휴먼 라벨링·활동량 활용 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GME에서 게코가 탐지된 영상을 기존 이중 블라인드 휴먼 라벨링에서 우선 처리하고, GME 활동 구간과 활동량을 OpenAI VLM 입력 준비와 하이라이트 후보 순위에 재사용한다.

**Architecture:** `gme_jobs.result_run_id → gme_runs`의 최신 성공 결과를 한 개의 내부 SQL 계약으로 정규화한다. 기존 eligible 영상 전량 보존 정책은 유지하고, live blind 큐에서 탐지 여부와 활동량을 날짜 안의 정렬키로만 사용한다. OpenAI VLM 연구 경로는 같은 GME run의 `moving` 구간을 dense frame 입력으로 사용하고, clip aggregate에 카메라·활동일 내부 활동량 순위를 남긴다.

**Tech Stack:** PostgreSQL/Supabase SQL RPC, Next.js 14 Route Handlers, TypeScript/Vitest, Python 3.12, OpenCV, pytest, uv

**Spec:** `docs/superpowers/specs/2026-08-22-gme-detected-human-labeling-activity-use-design.md`

## Global Constraints

- GME 활동량은 정렬·입력 준비·후보 순위에만 사용하고 행동 GT나 자동 제외 근거로 쓰지 않는다.
- GME 미탐지·실패 영상은 기존 eligible 큐에서 제거하지 않는다. 탐지 영상 우선 뒤에 그대로 남긴다.
- live blind 큐는 날짜를 먼저 고르고, 같은 날짜 안에서 `detected DESC, activity DESC, started_at DESC, id DESC`로 정렬한다.
- 최초 사람 제출 전 API와 화면에 GME 활동량, VLM 결과, 선택 사유를 노출하지 않는다.
- canary 큐의 동결 순서와 기존 제출·slot·consensus는 변경하거나 재생성하지 않는다.
- 현재 GME 결과는 `gme_jobs.status='succeeded'`와 `result_run_id`가 가리키는 `gme_runs.status='ok'`만 인정한다.
- GME 탐지는 `visible_sec > 0 AND max_simultaneous_geckos > 0`일 때만 true다. 불일치는 false로 접되 run은 삭제하지 않는다.
- 같은 clip에 여러 GME identity가 있으면 `gme_jobs.completed_at DESC, gme_jobs.id DESC`의 최신 성공 job 한 건만 사용한다.
- 종료된 local VLM/Claude 경로는 수정하지 않는다. VLM 변경은 현재 OpenAI API 연구 경로에만 적용한다.
- production DB/R2/service/model 배포는 migration rollback probe, web/Python 회귀, owner canary 승인 뒤에만 수행한다.
- 현재 worktree의 기존 `M 13 + ?? 67`은 사용자 소유다. 이 계획의 파일만 명시적으로 stage하고 다른 변경을 섞지 않는다.
- 실행은 `superpowers:using-git-worktrees`로 만든 clean isolated worktree에서 시작한다. GME v2.5 runtime 커밋 계보와 이 설계 커밋 `afe6a03`을 모두 포함한 새 `codex/` 브랜치를 사용한다.

---

### Task 1: 최신 GME 활동 컨텍스트 SQL 계약

**Files:**
- Create: `migrations/2026-08-22_gme_activity_blind_queue.sql`
- Create: `tests/test_gme_activity_context_migration.py`

**Interfaces:**
- Consumes: `public.gme_jobs.result_run_id`, `public.gme_runs`의 성공 run과 append-only provenance.
- Produces: `public.fn_current_gme_activity(uuid)` → `run_id uuid, detected boolean, activity_sec numeric, visible_sec numeric, state_intervals jsonb` 한 행 또는 0행.

- [ ] **Step 1: 정적 계약 실패 테스트를 작성한다**

```python
from pathlib import Path

SQL = Path("migrations/2026-08-22_gme_activity_blind_queue.sql").read_text().lower()


def test_current_gme_activity_uses_only_completed_success_result_pointer() -> None:
    assert "create function public.fn_current_gme_activity" in SQL
    assert "j.status = 'succeeded'" in SQL
    assert "r.id = j.result_run_id" in SQL
    assert "r.status = 'ok'" in SQL
    assert "order by j.completed_at desc nulls last, j.id desc" in SQL


def test_detection_requires_visibility_and_gecko_count() -> None:
    assert "r.visible_sec > 0 and r.max_simultaneous_geckos > 0" in SQL
    assert "security invoker" in SQL
    assert "to service_role" in SQL
    assert "to authenticated" not in SQL
```

- [ ] **Step 2: 테스트를 실행해 RED를 확인한다**

Run: `uv run pytest -q tests/test_gme_activity_context_migration.py`

Expected: migration 파일 부재로 collection 또는 read 단계에서 FAIL.

- [ ] **Step 3: 최소 SQL 함수를 구현한다**

`migrations/2026-08-22_gme_activity_blind_queue.sql`에 아래 구조를 구현한다. Task 2가 같은
migration에 queue RPC 교체를 추가하며, 두 Task가 끝나기 전에는 DB에 적용하지 않는다.

```sql
BEGIN;

CREATE FUNCTION public.fn_current_gme_activity(p_clip_id uuid)
RETURNS TABLE (
  run_id uuid,
  detected boolean,
  activity_sec numeric,
  visible_sec numeric,
  state_intervals jsonb
)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  SELECT
    r.id,
    (r.visible_sec > 0 AND r.max_simultaneous_geckos > 0),
    r.candidate_moving_sec_any_gecko,
    r.visible_sec,
    r.state_intervals
  FROM public.gme_jobs j
  JOIN public.gme_runs r ON r.id = j.result_run_id
  WHERE j.clip_id = p_clip_id
    AND j.status = 'succeeded'
    AND r.status = 'ok'
  ORDER BY j.completed_at DESC NULLS LAST, j.id DESC
  LIMIT 1;
$$;

REVOKE ALL ON FUNCTION public.fn_current_gme_activity(uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_current_gme_activity(uuid) TO service_role;

COMMIT;
```

- [ ] **Step 4: 정적 테스트를 GREEN으로 만든다**

Run:

```bash
uv run pytest -q tests/test_gme_activity_context_migration.py tests/test_gecko_motion_engine_migration.py
```

Expected: PASS. 실제 SQL runtime은 queue RPC까지 같은 migration에 들어간 Task 2에서 함께 검증한다.

- [ ] **Step 5: Task 1만 커밋한다**

```bash
git add migrations/2026-08-22_gme_activity_blind_queue.sql \
  tests/test_gme_activity_context_migration.py
git commit -m "feat: 최신 GME 활동 컨텍스트 계약 추가"
```

---

### Task 2: 탐지 영상 우선 이중 블라인드 큐

**Files:**
- Modify: `migrations/2026-08-22_gme_activity_blind_queue.sql`
- Create: `tests/test_gme_activity_blind_queue_migration.py`
- Create: `tests/sql/gme_activity_blind_queue_prerequisites.sql`
- Create: `tests/sql/gme_activity_blind_queue_probe.sql`
- Modify: `web/src/lib/motionBlindReviewServer.ts`
- Modify: `web/src/lib/motionBlindReviewServer.test.ts`
- Modify: `web/src/app/api/labeling-v3/blind/queue/route.ts`
- Modify: `web/src/app/api/labeling-v3/blind/queue/route.test.ts`
- Modify: `web/src/app/api/labeling-v3/blind/canary/[cohortId]/route.ts`
- Test: `web/src/app/api/labeling-v3/blind/canary/[cohortId]/route.test.ts`

**Interfaces:**
- Consumes: Task 1의 `fn_current_gme_activity(uuid)`.
- Produces: live queue 내부 rank 필드 `rank_detected boolean`, `rank_activity_sec numeric`; cursor v2 `{v:2,d,k,c,g,a,t,id}`.

- [ ] **Step 1: SQL RED 테스트를 작성한다**

다음 조건을 정적으로 고정한다.

```python
def test_live_queue_orders_gme_detected_then_activity_without_filtering_absent() -> None:
    sql = Path("migrations/2026-08-22_gme_activity_blind_queue.sql").read_text().lower()
    assert "left join lateral public.fn_current_gme_activity(m.id)" in sql
    assert "order by rank_detected desc, rank_activity_sec desc" in sql
    assert "where gme.detected" not in sql
    assert "rank_detected boolean" in sql
    assert "rank_activity_sec numeric" in sql


def test_canary_keeps_frozen_time_order() -> None:
    assert "case when p_cohort_kind = 'live'" in sql
```

- [ ] **Step 2: SQL 테스트가 파일 부재로 실패하는지 확인한다**

Run: `uv run pytest -q tests/test_gme_activity_blind_queue_migration.py`

Expected: FAIL.

- [ ] **Step 3: live 큐 RPC를 forward-only로 교체한다**

새 migration에서 기존 `fn_list_motion_blind_queue`의 인자에 다음 cursor 필드를 추가한다.

```sql
p_cursor_detected boolean DEFAULT NULL,
p_cursor_activity_sec numeric DEFAULT NULL
```

반환 컬럼 끝에는 아래 두 값을 추가한다.

```sql
rank_detected boolean,
rank_activity_sec numeric
```

live 행의 rank는 다음처럼 계산한다. canary는 `false, 0`으로 고정해 기존 시간순을 유지한다.

```sql
CASE WHEN p_cohort_kind = 'live' THEN COALESCE(gme.detected, false) ELSE false END,
CASE WHEN p_cohort_kind = 'live' AND COALESCE(gme.detected, false)
     THEN COALESCE(gme.activity_sec, 0) ELSE 0 END
```

keyset 조건과 정렬은 rank 두 필드 뒤에 기존 `(started_at,id)`를 둔다. rank는 정렬·cursor에만 쓰고 공개 item에는 넣지 않는다. `fn_ensure_motion_review_slots`의 eligible 집합은 바꾸지 않으며, 실행 뒤 “현재 GME detected eligible clip에는 reviewer slot 두 개”라는 invariant만 추가 검증한다.

- [ ] **Step 4: runtime probe로 전량 보존과 우선순위를 함께 검증한다**

`tests/sql/gme_activity_blind_queue_prerequisites.sql`는 tracked
`tests/sql/motion_double_blind_prerequisites.sql`을 exact 복사한 뒤 `gme_jobs`, `gme_runs`의 Task 1
함수 소비 컬럼과 FK만 추가한다. probe fixture는 한 clip의 old/new 성공 run과 실패 job을 먼저 만들고
Task 1 함수가 최신 성공 run을 고르는지 assert한다. 이어 같은 activity day에
`detected activity=9`, `detected activity=2`, `not-detected` 세 clip을 만들어 다음을 검증한다.

```sql
ASSERT v_order = ARRAY[v_detected_9, v_detected_2, v_not_detected];
ASSERT (SELECT count(*) FROM public.motion_clip_review_slots
        WHERE clip_id = v_detected_9) = 2;
ASSERT (SELECT count(*) FROM public.motion_clip_review_slots
        WHERE clip_id = v_not_detected) = 2;
ASSERT (SELECT run_id FROM public.fn_current_gme_activity(v_detected_9)) = v_new_run;
```

페이지 크기 2로 첫 페이지와 cursor 다음 페이지를 합쳤을 때 누락·중복 0도 assert한다.

- [ ] **Step 5: TypeScript cursor v2 RED 테스트를 작성한다**

```ts
const cursor = encodeBlindCursor(liveScope, {
  gmeDetected: true,
  activitySec: '9.5',
  startedAt: '2026-08-21T21:00:00.000000+09:00',
  id: CLIP,
});
expect(decodeBlindCursor(cursor, liveScope)).toEqual({
  gmeDetected: true,
  activitySec: '9.5',
  startedAt: '2026-08-21T21:00:00.000000+09:00',
  id: CLIP,
});
expect(() => decodeBlindCursor(legacyV1Cursor, liveScope)).toThrow(InvalidBlindCursorError);
```

또 `mapBlindQueueRow` 결과 JSON에 `rank_detected`, `rank_activity_sec`, `gme`, `activity` 문자열이 없음을 검사한다.

- [ ] **Step 6: web 테스트를 RED로 확인한다**

Run:

```bash
cd web
npm test -- --run src/lib/motionBlindReviewServer.test.ts \
  src/app/api/labeling-v3/blind/queue/route.test.ts \
  'src/app/api/labeling-v3/blind/canary/[cohortId]/route.test.ts'
```

Expected: cursor position 필드와 새 RPC 인자 assertion에서 FAIL.

- [ ] **Step 7: cursor·route를 최소 수정한다**

`BlindQueuePosition`은 다음 exact 타입을 쓴다.

```ts
export interface BlindQueuePosition {
  gmeDetected: boolean;
  activitySec: string;
  startedAt: string;
  id: string;
}
```

cursor는 `v:2`, `g:boolean`, `a:/^(0|[1-9]\d*)(\.\d+)?$/`를 검증한다. live route는 row의 내부 rank를 next cursor에 넣고 RPC에 네 cursor 필드를 모두 전달한다. canary route는 새 cursor 인자 둘을 `null`로 넘긴다. `mapBlindQueueRow`와 공개 `BlindQueueItem`은 변경하지 않는다.

- [ ] **Step 8: SQL·web 테스트를 GREEN으로 만든다**

Run:

```bash
uv run pytest -q tests/test_gme_activity_blind_queue_migration.py
uv run python scripts/run_motion_double_blind_concurrency_probe.py \
  --migration migrations/2026-08-22_gme_activity_blind_queue.sql \
  --prerequisites tests/sql/gme_activity_blind_queue_prerequisites.sql \
  --probe tests/sql/gme_activity_blind_queue_probe.sql \
  --backend local
cd web
npm test -- --run src/lib/motionBlindReviewServer.test.ts \
  src/app/api/labeling-v3/blind/queue/route.test.ts \
  'src/app/api/labeling-v3/blind/canary/[cohortId]/route.test.ts'
npx tsc --noEmit
```

Expected: 정적/web 테스트 PASS와 runtime marker
`GME_ACTIVITY_CONTEXT_OK`, `GME_ACTIVITY_BLIND_QUEUE_OK`,
`DB_RUNTIME_PROBE_OK`, `DB_CONCURRENCY_PROBE_OK`, `PROBE_RESIDUE=0`.

- [ ] **Step 9: Task 2만 커밋한다**

```bash
git add migrations/2026-08-22_gme_activity_blind_queue.sql \
  tests/test_gme_activity_blind_queue_migration.py \
  tests/sql/gme_activity_blind_queue_prerequisites.sql \
  tests/sql/gme_activity_blind_queue_probe.sql \
  web/src/lib/motionBlindReviewServer.ts \
  web/src/lib/motionBlindReviewServer.test.ts \
  web/src/app/api/labeling-v3/blind/queue/route.ts \
  web/src/app/api/labeling-v3/blind/queue/route.test.ts \
  'web/src/app/api/labeling-v3/blind/canary/[cohortId]/route.ts' \
  'web/src/app/api/labeling-v3/blind/canary/[cohortId]/route.test.ts'
git commit -m "feat: GME 탐지와 활동량으로 라벨링 순서 지정"
```

---

### Task 3: GME 활동 구간을 OpenAI VLM 입력에 연결

**Files:**
- Create: `scripts/rba_gme_activity.py`
- Create: `tests/test_rba_gme_activity.py`
- Modify: `scripts/rba_openai_frame_policy.py`
- Modify: `tests/test_rba_openai_frame_policy.py`
- Modify: `scripts/run_rba_openai_smoke.py`
- Modify: `tests/test_run_rba_openai_smoke.py`

**Interfaces:**
- Consumes: Task 1과 같은 GME run schema의 private JSON mapping.
- Produces: `parse_gme_activity(run, *, duration_sec) -> GmeActivityContext`; `dense_intervals`와 activity provenance를 OpenAI frame manifest에 기록.

- [ ] **Step 1: protected OpenAI 파일의 tracked base를 확인한다**

Run:

```bash
git ls-files --error-unmatch scripts/rba_openai_frame_policy.py
git ls-files --error-unmatch tests/test_rba_openai_frame_policy.py
git ls-files --error-unmatch scripts/run_rba_openai_smoke.py
git ls-files --error-unmatch tests/test_run_rba_openai_smoke.py
```

Expected: 네 파일 모두 tracked. 하나라도 실패하면 현재 80-file cleanup의 해당 OpenAI 기능 그룹을 먼저 독립 검수·승인·커밋하고, 다른 untracked 파일은 stage하지 않는다.

- [ ] **Step 2: strict parser RED 테스트를 작성한다**

```python
def test_parse_gme_activity_returns_moving_intervals_and_activity() -> None:
    context = parse_gme_activity(
        {
            "id": RUN_SHA,
            "status": "ok",
            "candidate_moving_sec_any_gecko": 3.0,
            "visible_sec": 8.0,
            "max_simultaneous_geckos": 1,
            "state_intervals": [
                {"state": "static", "start_sec": 0.0, "end_sec": 2.0},
                {"state": "moving", "start_sec": 2.0, "end_sec": 5.0},
            ],
        },
        duration_sec=10.0,
    )
    assert context.detected is True
    assert context.activity_sec == 3.0
    assert context.dense_intervals == ({"start_sec": 1.5, "end_sec": 5.5},)
```

bool-as-number, NaN/Inf, 음수, 겹치거나 역전된 구간, duration 초과, `moving_sec > visible_sec`, unknown state는 모두 `GmeActivityError`가 나야 한다.

- [ ] **Step 3: parser 테스트 RED를 확인한다**

Run: `uv run pytest -q tests/test_rba_gme_activity.py`

Expected: import failure.

- [ ] **Step 4: immutable context와 parser를 구현한다**

```python
UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
GME_STATES = frozenset({"moving", "static", "not_visible", "unknown", "camera_motion"})


@dataclass(frozen=True)
class GmeActivityContext:
    run_id: str
    detected: bool
    activity_sec: float
    visible_sec: float
    dense_intervals: tuple[dict[str, float], ...]


def _strict_finite_number(value: object, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GmeActivityError(code)
    number = float(value)
    if not math.isfinite(number):
        raise GmeActivityError(code)
    return number


def _merge_touching_intervals(
    intervals: list[dict[str, float]],
) -> list[dict[str, float]]:
    merged: list[dict[str, float]] = []
    for interval in intervals:
        if merged and interval["start_sec"] <= merged[-1]["end_sec"]:
            merged[-1]["end_sec"] = max(
                merged[-1]["end_sec"], interval["end_sec"]
            )
        else:
            merged.append(dict(interval))
    return merged


def parse_gme_activity(
    run: Mapping[str, object], *, duration_sec: float
) -> GmeActivityContext:
    duration = _strict_finite_number(duration_sec, "duration_sec")
    activity = _strict_finite_number(
        run.get("candidate_moving_sec_any_gecko"), "activity_sec"
    )
    visible = _strict_finite_number(run.get("visible_sec"), "visible_sec")
    count = run.get("max_simultaneous_geckos")
    run_id = run.get("id")
    intervals = run.get("state_intervals")
    if (
        duration <= 0
        or activity < 0
        or visible < activity
        or visible > duration + 0.001
        or type(count) is not int
        or count < 0
        or not isinstance(run_id, str)
        or not UUID.fullmatch(run_id)
        or run.get("status") != "ok"
        or not isinstance(intervals, list)
    ):
        raise GmeActivityError("run_contract")
    moving: list[dict[str, float]] = []
    previous_end = 0.0
    for raw in intervals:
        if not isinstance(raw, Mapping) or raw.get("state") not in GME_STATES:
            raise GmeActivityError("state_interval")
        start = _strict_finite_number(raw.get("start_sec"), "state_interval")
        end = _strict_finite_number(raw.get("end_sec"), "state_interval")
        if start < previous_end or end < start or end > duration + 0.001:
            raise GmeActivityError("state_interval")
        previous_end = end
        if raw["state"] == "moving":
            moving.append({
                "start_sec": max(0.0, start - 0.5),
                "end_sec": min(duration, end + 0.5),
            })
    merged = _merge_touching_intervals(moving)
    return GmeActivityContext(
        run_id=run_id,
        detected=visible > 0 and count > 0,
        activity_sec=activity,
        visible_sec=visible,
        dense_intervals=tuple(merged),
    )
```

`moving` 구간만 앞뒤 0.5초를 확장하고 `[0,duration_sec]`로 clamp한다. 서로 닿거나 겹친 확장 구간은 합친다. 이 함수는 행동명을 만들지 않는다.

- [ ] **Step 5: frame manifest RED 테스트를 추가한다**

아래 exact 호출 결과가 다음을 만족해야 한다.

```python
manifest = materialize_frame_manifest(
    video,
    output_dir=tmp_path / "frames",
    base_fps=4.0,
    dense_fps=20.0,
    dense_intervals=(),
    gme_context=context,
    window_sec=6.0,
    overlap_sec=1.0,
)
assert manifest["gme_activity"]["run_id"] == RUN_SHA
assert manifest["gme_activity"]["detected"] is True
assert manifest["gme_activity"]["activity_sec"] == 3.0
assert any("gme-moving-dense" in row["source_policies"] for row in manifest["frames"])
assert manifest["base_coverage_preserved"] is True
```

- [ ] **Step 6: frame policy와 smoke runner를 구현한다**

기존 `dense_intervals` 일반 인자는 보존한다. `gme_context`가 있으면 그 moving 구간을 dense 집합에 합치고 source policy를 `gme-moving-dense`로 기록한다. smoke input의 각 clip은 `gme_run` mapping을 필수로 받고, parser 결과를 frame policy에 전달한다. API prompt에는 activity 값이나 “moving 정답”을 텍스트로 넣지 않는다.

- [ ] **Step 7: VLM 관련 테스트를 GREEN으로 만든다**

Run:

```bash
uv run pytest -q tests/test_rba_gme_activity.py \
  tests/test_rba_openai_frame_policy.py \
  tests/test_run_rba_openai_smoke.py \
  tests/test_run_rba_openai_vlm.py
```

Expected: PASS, API 호출 fake count 기존 계약 유지, frame/output mode 0600 유지.

- [ ] **Step 8: Task 3만 커밋한다**

```bash
git add scripts/rba_gme_activity.py tests/test_rba_gme_activity.py \
  scripts/rba_openai_frame_policy.py tests/test_rba_openai_frame_policy.py \
  scripts/run_rba_openai_smoke.py tests/test_run_rba_openai_smoke.py
git commit -m "feat: GME 활동 구간을 OpenAI VLM 입력에 연결"
```

---

### Task 4: 활동량 기반 하이라이트 후보 provenance

**Files:**
- Modify: `scripts/rba_gme_activity.py`
- Modify: `tests/test_rba_gme_activity.py`
- Modify: `scripts/rba_openai_clip_aggregate.py`
- Modify: `tests/test_rba_openai_clip_aggregate.py`

**Interfaces:**
- Consumes: Task 3의 `GmeActivityContext`와 OpenAI clip aggregate.
- Produces: `rank_activity_candidates(rows) -> list[dict[str, object]]`; aggregate의 `gme_activity`와 `highlight_activity_priority` provenance.

- [ ] **Step 1: 카메라·활동일 내부 순위 RED 테스트를 작성한다**

```python
def test_rank_activity_candidates_is_per_camera_day_and_deterministic() -> None:
    ranked = rank_activity_candidates([
        candidate("a", camera="cam-1", day="2026-08-21", activity=9.0),
        candidate("b", camera="cam-1", day="2026-08-21", activity=2.0),
        candidate("c", camera="cam-2", day="2026-08-21", activity=1.0),
    ])
    assert [(r["clip_ref"], r["activity_rank"]) for r in ranked] == [
        ("a", 1), ("b", 2), ("c", 1)
    ]
```

같은 activity는 `started_at DESC, clip_ref ASC`로 tie-break한다. 서로 다른 카메라의 raw seconds를 직접 우열 비교하지 않는다.

- [ ] **Step 2: aggregate provenance RED 테스트를 작성한다**

```python
aggregate = aggregate_clip_ledger(
    ledger,
    clip_ref="smoke-abc",
    expected_window_ids=["window-000"],
    gme_context=context,
    highlight_activity_priority={"camera_day_rank": 1, "camera_day_count": 4},
    output=output,
)
assert aggregate["gme_activity"] == {
    "run_id": RUN_SHA,
    "detected": True,
    "activity_sec": 3.0,
    "visible_sec": 8.0,
}
assert aggregate["highlight_activity_priority"] == {
    "camera_day_rank": 1,
    "camera_day_count": 4,
}
```

- [ ] **Step 3: 테스트를 RED로 확인한다**

Run: `uv run pytest -q tests/test_rba_gme_activity.py tests/test_rba_openai_clip_aggregate.py`

Expected: 새 함수·인자 부재로 FAIL.

- [ ] **Step 4: 최소 순위 함수와 aggregate 필드를 구현한다**

순위 함수는 GT/VLM 행동을 만들지 않고 GME activity ordinal만 계산한다. aggregate는 exact GME run id와 수치를 별도 객체로 기록해 이후 VLM·사람 `highlight_recommendation`과 결합할 수 있게 한다. 활동량만으로 `include`를 만들지 않는다.

- [ ] **Step 5: 테스트를 GREEN으로 만든다**

Run:

```bash
uv run pytest -q tests/test_rba_gme_activity.py \
  tests/test_rba_openai_clip_aggregate.py \
  tests/test_run_rba_openai_smoke.py
```

Expected: PASS, 동일 입력 역순에서도 rank와 canonical aggregate bytes 동일.

- [ ] **Step 6: Task 4만 커밋한다**

```bash
git add scripts/rba_gme_activity.py tests/test_rba_gme_activity.py \
  scripts/rba_openai_clip_aggregate.py tests/test_rba_openai_clip_aggregate.py
git commit -m "feat: 하이라이트 후보에 GME 활동량 순위 기록"
```

---

### Task 5: 통합 검증·preview canary·운영 handoff

**Files:**
- Create: `docs/handoff-prompts/2026-08-22-gme-detected-labeling-activity-report.md`
- Modify: `docs/DATABASE.md`
- Modify: `docs/FEATURES.md`

**Interfaces:**
- Consumes: Task 1~4의 migration, web cursor, VLM/highlight provenance.
- Produces: tracked 검증 보고서와 exact commit 기반 runtime handoff manifest.

- [ ] **Step 1: 전체 정적 회귀를 실행한다**

Run:

```bash
uv run pytest -q
cd web && npm test -- --run && npx tsc --noEmit && npm run build
```

Expected: Python 전체 PASS(기존 명시 skip만 허용), web tests/tsc/build PASS.

- [ ] **Step 2: disposable DB rollback probe를 실행한다**

Task 2에서 완성된 단일 migration과 probe를 production schema snapshot 순서로 적용한다. 다음 marker를 모두 확인한다.

```text
GME_ACTIVITY_CONTEXT_OK
GME_ACTIVITY_BLIND_QUEUE_OK
PROBE_RESIDUE=0
```

- [ ] **Step 3: preview에서 사람 체험 canary를 확인한다**

production 원문/GT를 출력하지 않는 테스트 fixture 또는 preview cohort로 아래만 확인한다.

1. 어제 activity 9 탐지 영상이 activity 2 탐지 영상보다 먼저 나온다.
2. activity 0 탐지 영상과 미탐지 eligible 영상도 뒤에 남는다.
3. 두 라벨러 응답 JSON에 GME activity/VLM/rank 필드가 없다.
4. canary cohort의 기존 시간순과 제출 수는 변하지 않는다.

- [ ] **Step 4: 문서와 보고서를 갱신한다**

`docs/DATABASE.md`에는 함수·RPC signature와 아직 production 적용 여부를, `docs/FEATURES.md`에는 사용자 흐름과 blind 비노출을 기록한다. 보고서에는 HEAD, upstream, scoped/full test, migration apply 여부, DB/R2/service/model write 수를 실제 값 그대로 쓴다.

- [ ] **Step 5: 문서 커밋 후 handoff를 검증한다**

```bash
git add docs/DATABASE.md docs/FEATURES.md \
  docs/handoff-prompts/2026-08-22-gme-detected-labeling-activity-report.md
git commit -m "docs: GME 활동량 라벨링 연계 검증 기록"
uv run python scripts/verify_agent_handoff.py \
  --manifest docs/handoff-prompts/2026-08-22-gme-detected-labeling-activity-report.md
```

Expected: `HANDOFF_OK`.

- [ ] **Step 6: 별도 owner 승인 뒤에만 production 적용한다**

승인 후 단일 migration `2026-08-22_gme_activity_blind_queue.sql`, Vercel labeling web 배포,
Mac mini OpenAI 연구 runner handoff를 각각 exact commit으로 수행한다. 적용 뒤 read-only로 다음을 확인한다.

- 어제 GME detected eligible clip의 두 review slot 누락 0
- live queue rank 단조 감소와 페이지 중복/누락 0
- GME/VLM/rank 공개 응답 노출 0
- 기존 consensus/submission 수정 0
- GME worker identity/checkpoint 변화 0
- 원본 R2·production 모델 배포 0

실패하면 새 slot·submission을 삭제하지 않는다. web은 이전 commit으로 되돌리고 새 RPC를 호출하지 않게 한 뒤, migration의 함수 정의만 직전 signature로 forward 복구한다.

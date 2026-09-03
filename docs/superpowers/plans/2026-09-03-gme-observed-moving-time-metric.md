# GME Observed Moving Time Metric Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현재 GME detector identity의 관측 움직임 시간과 측정 상태를 정확한 run provenance와 함께 조회하고, 최초 사람 GT 잠금 뒤 라벨링 상세 화면에 안전하게 표시한다.

**Architecture:** append-only `gme_jobs`/`gme_runs`를 정본으로 유지하고 service-role 전용 versioned RPC가 exact detector identity의 상태를 해석한다. Next.js 상세 API는 GT 잠금 뒤에만 RPC를 호출하고 strict allowlist 매퍼로 공개 필드만 전달하며, 클라이언트는 측정 상태별 한국어 문구만 렌더링한다.

**Tech Stack:** PostgreSQL/Supabase migration, Next.js App Router, TypeScript, Vitest, pytest

**Spec:** `docs/superpowers/specs/2026-09-03-gme-observed-moving-time-metric-design.md`

**Status:** `DEPLOYED_VERIFIED` — 2026-09-03 전체 회귀, 일회용 PostgreSQL 검증, production migration·권한·실데이터 canary, Preview, Production 배포와 Owner 운영 화면 canary까지 완료했다.

## Global Constraints

- 대표값은 `gme_runs.candidate_moving_sec_any_gecko`이며 단위는 초다.
- `moving_time_sec`는 `measurement_status = measured`일 때만 숫자이며, `visible_sec > 0`인 정상 run에서만 `0`을 허용한다.
- 현재 `detector_identity`와 exact job/run 연결만 사용하고 과거 identity 결과로 fallback하지 않는다.
- `gme_jobs`와 append-only `gme_runs`를 정본으로 유지하며 `motion_clips`에 값을 복사하거나 기존 run을 수정하지 않는다.
- 최초 blind 사람 GT 잠금 전에는 API 응답과 화면 모두 GME 지표를 노출하지 않고 RPC도 호출하지 않는다.
- 낮은 활동값과 측정 불가 상태는 자동 제외, 영상 삭제, 행동 확정, 모델 승격 근거로 사용하지 않는다.
- 이동 거리, Flutter 앱 노출, 기존 backfill 재시작은 이번 구현 범위가 아니다. production DB와 웹 배포는
  후속 사용자 승인으로 범위에 포함해 append-only migration과 canary까지 완료했다.

---

### Task 1: Versioned DB 조회 계약

**Files:**
- Create: `tests/test_gme_observed_moving_time_migration.py`
- Create: `migrations/2026-09-03_gme_observed_moving_time_v1.sql`

**Interfaces:**
- Consumes: `public.gme_jobs`, `public.gme_runs`, `public.motion_clips`
- Produces: `public.fn_get_gme_observed_moving_time_v1(p_clip_id uuid, p_detector_identity text)` returning one row with `run_id uuid`, `detector_identity text`, `measurement_status text`, `moving_time_sec numeric`, `visible_sec numeric`, `unknown_sec numeric`, `camera_motion_sec numeric`

- [x] **Step 1: Write the failing migration contract tests**

```python
def test_rpc_maps_exact_identity_states_without_fallback(sql: str) -> None:
    assert "fn_get_gme_observed_moving_time_v1" in sql
    assert "j.detector_identity = p_detector_identity" in sql
    assert "candidate_moving_sec_any_gecko" in sql
    assert "'measured'" in sql
    assert "'not_observed'" in sql
    assert "'pending'" in sql
    assert "'failed'" in sql

def test_rpc_is_read_only_and_service_role_only(sql: str) -> None:
    lowered = sql.lower()
    assert "security invoker set search_path = ''" in " ".join(lowered.split())
    assert "revoke all on function public.fn_get_gme_observed_moving_time_v1" in lowered
    assert "grant execute on function public.fn_get_gme_observed_moving_time_v1" in lowered
    assert "update public.motion_clips" not in lowered
    assert "update public.gme_runs" not in lowered
    assert "delete from" not in lowered
```

- [x] **Step 2: Run the tests and verify the migration is missing**

Run: `uv run pytest tests/test_gme_observed_moving_time_migration.py -q`

Expected: FAIL because `migrations/2026-09-03_gme_observed_moving_time_v1.sql` does not exist.

- [x] **Step 3: Implement the read-only RPC**

```sql
create function public.fn_get_gme_observed_moving_time_v1(
  p_clip_id uuid,
  p_detector_identity text
) returns table (
  run_id uuid,
  detector_identity text,
  measurement_status text,
  moving_time_sec numeric,
  visible_sec numeric,
  unknown_sec numeric,
  camera_motion_sec numeric
)
language plpgsql security invoker set search_path='' as $$
```

The body must validate the 64-character lowercase SHA, confirm the clip exists, fail closed if more than one job exists for the same clip/identity, and map states exactly as follows:

```text
no exact job / queued / processing / failed_retryable -> pending, moving_time_sec NULL
failed_terminal -> failed, moving_time_sec NULL
succeeded + exact ok run + visible_sec > 0 -> measured, candidate_moving_sec_any_gecko
succeeded + exact ok run + visible_sec = 0 -> not_observed, moving_time_sec NULL
succeeded + missing/mismatched/non-ok run -> failed, moving_time_sec NULL
```

The function must revoke `public`, `anon`, and `authenticated`, then grant execution only to `service_role`.

- [x] **Step 4: Run the focused migration contract tests**

Run: `uv run pytest tests/test_gme_observed_moving_time_migration.py tests/test_gecko_motion_engine_migration.py -q`

Expected: PASS.

### Task 2: Server type and strict mapper contract

**Files:**
- Modify: `web/src/lib/labelingV3.ts`
- Modify: `web/src/lib/labelingV3Server.ts`
- Modify: `web/src/lib/labelingV3Server.test.ts`

**Interfaces:**
- Consumes: RPC row fields from Task 1
- Produces: `GmeMeasurementStatus`, `GmeObservedMovingTime`, `GmeObservedMovingTimeRow`, `mapGmeObservedMovingTimeRow(row)`, `readGmeActiveDetectorIdentity()`

- [x] **Step 1: Write failing mapper and identity tests**

```typescript
expect(mapGmeObservedMovingTimeRow({
  run_id: RUN,
  detector_identity: IDENTITY,
  measurement_status: 'measured',
  moving_time_sec: 0,
  visible_sec: 12.5,
  unknown_sec: 1,
  camera_motion_sec: 0,
})).toEqual({
  run_id: RUN,
  detector_identity: IDENTITY,
  measurement_status: 'measured',
  moving_time_sec: 0,
  visible_sec: 12.5,
  unknown_sec: 1,
  camera_motion_sec: 0,
});

expect(() => mapGmeObservedMovingTimeRow({
  measurement_status: 'not_observed',
  moving_time_sec: 0,
} as never)).toThrow('invalid_gme_observed_moving_time');
```

Also verify that a missing or malformed `GME_ACTIVE_DETECTOR_IDENTITY` throws the public-safe configuration error instead of accepting an old identity.

- [x] **Step 2: Run the focused test and verify missing exports fail**

Run: `cd web && npm test -- --run src/lib/labelingV3Server.test.ts`

Expected: FAIL because the new types and mapper do not exist.

- [x] **Step 3: Implement strict public types and mapper**

```typescript
export type GmeMeasurementStatus =
  | 'measured'
  | 'not_observed'
  | 'pending'
  | 'failed';

export interface GmeObservedMovingTime {
  run_id: string | null;
  detector_identity: string;
  measurement_status: GmeMeasurementStatus;
  moving_time_sec: number | null;
  visible_sec: number | null;
  unknown_sec: number | null;
  camera_motion_sec: number | null;
}
```

Add optional `gme_activity?: GmeObservedMovingTime` to `MotionClipDetail`. The mapper must reject non-finite, negative, structurally inconsistent values and must not copy raw row properties.

- [x] **Step 4: Run the focused mapper tests**

Run: `cd web && npm test -- --run src/lib/labelingV3Server.test.ts`

Expected: PASS.

### Task 3: Blind-safe detail API integration

**Files:**
- Modify: `web/src/app/api/labeling-v3/[clipId]/route.ts`
- Modify: `web/src/app/api/labeling-v3/[clipId]/route.test.ts`
- Modify: `web/.env.example`
- Modify: `docs/ENV.md`

**Interfaces:**
- Consumes: `readGmeActiveDetectorIdentity()`, `mapGmeObservedMovingTimeRow(row)`
- Produces: optional `MotionClipDetail.gme_activity` after `gt_locked` or `completed`

- [x] **Step 1: Write failing API tests for blind and post-lock behavior**

```typescript
it('GT 잠금 전에는 GME RPC를 호출하지 않고 필드를 노출하지 않는다', async () => {
  const res = await GET(req(), { params: { clipId: CLIP } });
  expect(rpc).not.toHaveBeenCalled();
  expect(await res.json()).not.toHaveProperty('gme_activity');
});

it('GT 잠금 뒤 exact active identity로 GME RPC를 한 번 호출한다', async () => {
  const res = await GET(req(), { params: { clipId: CLIP } });
  expect(rpc).toHaveBeenCalledWith('fn_get_gme_observed_moving_time_v1', {
    p_clip_id: CLIP,
    p_detector_identity: ACTIVE_IDENTITY,
  });
  expect((await res.json()).gme_activity.measurement_status).toBe('measured');
});
```

Add cases for RPC error → generalized 502 and missing identity → generalized 502 without raw environment values.

- [x] **Step 2: Run the route tests and verify they fail**

Run: `cd web && npm test -- --run 'src/app/api/labeling-v3/[clipId]/route.test.ts'`

Expected: FAIL because the route does not call the versioned RPC.

- [x] **Step 3: Integrate RPC only after GT lock**

Build the normal detail first. Only when `detail.session?.stage` is `gt_locked` or `completed`, read `GME_ACTIVE_DETECTOR_IDENTITY`, call the versioned RPC exactly once, require exactly one returned row, map it, and assign `detail.gme_activity`. Pre-lock requests must not read the env or call the RPC.

Document `GME_ACTIVE_DETECTOR_IDENTITY` as a non-secret required setting for post-lock GME activity display. Do not hardcode a model identity in source.

- [x] **Step 4: Run route, mapper, and type checks**

Run: `cd web && npm test -- --run 'src/app/api/labeling-v3/[clipId]/route.test.ts' src/lib/labelingV3Server.test.ts && npx tsc --noEmit`

Expected: PASS.

### Task 4: Post-lock labeling UI

**Files:**
- Create: `web/src/lib/gmeObservedMovingTime.ts`
- Create: `web/src/lib/gmeObservedMovingTime.test.ts`
- Create: `web/src/app/labeling/motion/_gme-observed-moving-time-card.tsx`
- Create: `web/src/app/labeling/motion/_gme-observed-moving-time-card.test.tsx`
- Modify: `web/src/app/labeling/motion/[clipId]/page.tsx`

**Interfaces:**
- Consumes: `GmeObservedMovingTime`
- Produces: `formatGmeObservedMovingTime(metric): { title: string; detail: string }`

- [x] **Step 1: Write failing status-copy tests**

```typescript
expect(formatGmeObservedMovingTime(measured(18.44)).title)
  .toBe('영상에서 확인된 움직임 18.4초');
expect(formatGmeObservedMovingTime(measured(0)).title)
  .toBe('영상에서 확인된 움직임 0초');
expect(formatGmeObservedMovingTime(status('not_observed')).title)
  .toBe('게코 미관측 · 측정 불가');
expect(formatGmeObservedMovingTime(status('pending')).title)
  .toBe('GME 분석 대기 중');
expect(formatGmeObservedMovingTime(status('failed')).title)
  .toBe('GME 분석 실패');
```

- [x] **Step 2: Run the formatter test and verify the module is missing**

Run: `cd web && npm test -- --run src/lib/gmeObservedMovingTime.test.ts`

Expected: FAIL because the formatter module does not exist.

- [x] **Step 3: Implement formatter and post-lock card**

The card title is `GME 관측 움직임 시간`. Render it only when `phase` is `review` or `complete` and `detail.gme_activity` exists. Include the formatted status line plus `관측/미확정/카메라 움직임` supporting seconds when available, and state that the value is an observation aid rather than behavior GT.

- [x] **Step 4: Run UI contract tests and TypeScript**

Run: `cd web && npm test -- --run src/lib/gmeObservedMovingTime.test.ts 'src/app/api/labeling-v3/[clipId]/route.test.ts' && npx tsc --noEmit`

Expected: PASS.

### Task 5: Documentation and regression verification

**Files:**
- Modify: `docs/superpowers/specs/2026-09-03-gme-observed-moving-time-metric-design.md`
- Modify: `docs/superpowers/plans/2026-09-03-gme-observed-moving-time-metric.md`
- Modify: `specs/next-session.md`
- Create: `scripts/run_gme_observed_moving_time_probe.py`
- Create: `tests/test_gme_observed_moving_time_probe.py`

**Interfaces:**
- Consumes: completed Tasks 1–4
- Produces: implementation status, deployment prerequisites, verification evidence

- [x] **Step 1: Record implementation status without claiming deployment**

Mark the design as `IMPLEMENTED_UNVERIFIED` only after focused tests pass. Record that production activation still requires migration application, `GME_ACTIVE_DETECTOR_IDENTITY` configuration, Preview canary, and explicit deployment approval.

- [x] **Step 2: Run focused Python and web verification**

Run: `uv run pytest tests/test_gme_observed_moving_time_migration.py tests/test_gecko_motion_engine_migration.py -q`

Run: `cd web && npm test -- --run src/lib/gmeObservedMovingTime.test.ts src/lib/labelingV3Server.test.ts 'src/app/api/labeling-v3/[clipId]/route.test.ts' && npx tsc --noEmit`

Expected: all tests PASS and TypeScript exits 0.

- [x] **Step 3: Run relevant regression suites**

Run: `uv run pytest tests/test_gecko_motion_engine_migration.py tests/test_gecko_motion_engine_cutover.py -q`

Run: `cd web && npm test -- --run src/lib/labelingV3.test.ts src/lib/labelingV3Server.test.ts 'src/app/api/labeling-v3/[clipId]/route.test.ts'`

Expected: all tests PASS.

- [x] **Step 4: Inspect the final diff and forbidden mutations**

Run: `git diff --stat && git diff --check && rg -n "UPDATE public\.motion_clips|UPDATE public\.gme_runs|DELETE FROM public\.gme_(jobs|runs)|candidate_moving_sec_any_gecko" migrations/2026-09-03_gme_observed_moving_time_v1.sql`

Expected: no whitespace errors, no writes to protected ledgers, and the representative field appears only in the read contract.

- [x] **Step 5: Stop before commit, DB apply, Preview, or production deploy**

Report the uncommitted implementation and verification evidence. Commit, push, migration application, environment mutation, Preview canary, and production deployment require their own explicit approval.

## Verification Evidence (2026-09-03)

- 최신 `origin/main` 통합 후 `uv run pytest -q` → `2409 passed, 5 skipped`
- 최신 `origin/main` 통합 후 `cd web && npm test -- --run` → `1272 passed`
- `cd web && npx tsc --noEmit` → exit `0`
- disposable PostgreSQL 15 → `RUNTIME_OK / PRIVILEGE_OK / ROLLBACK_OK / PROBE_RESIDUE=0`
- `git diff --check` → exit `0`
- 신규 migration의 `motion_clips`/`gme_jobs`/`gme_runs` write 패턴 → `0`
- read-only 교차리뷰의 동시 job 선택과 invalid measured-null 지적을 TDD로 수정했다.

## Integration and Deployment Evidence (2026-09-03)

- 구현 commit `09a0407c911c77968a5306125a082e87604ca16b`을 `main`에 fast-forward 반영했다.
- production PostgreSQL preflight에서 대상 3테이블, service-role 조회 권한, exact identity job `11,508`, 중복 clip `0`을 확인했다.
- migration 적용 뒤 RPC `1`, service-role 실행 권한 `true`, anon/authenticated 실행 권한 `false`를 확인했다.
- 실데이터 RPC는 한 행을 반환했고 상태·nullable 숫자 계약을 통과했다. 함수 body의 쓰기 연산은 `0`이다.
- Preview `dpl_6YLQ5RHARpfJ6bUgV4qfRnTsZggM`은 READY, `/labeling` `200`, 비인증 상세 API `401`이었다.
- Production `dpl_AcEaEgDuUDkChCa9m4zmndGKNSQJ`은 READY이며 `label.tera-ai.uk` alias를 받았다.
- Production `/labeling`은 `200`, 비인증 상세 API는 `401`이었다. 로그인한 Owner의 `gt_locked` 영상에서는
  `GME 관측 움직임 시간` 카드와 `GME 분석 대기 중` 상태를 확인해 미측정 값을 `0초`로 표시하지 않음을 검증했다.
- migration 재적용, 기존 GME run 수정, backfill 재시작, 사람 GT 변경, R2 write는 수행하지 않았다.

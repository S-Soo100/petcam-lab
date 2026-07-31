# Motion Blind Live v2 Highlight-Soft Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 2026-08-01 activity-day부터 새로 생성되는 일상 live slot에서 highlight-only 차이를
`uncertain`으로 합의하고 core GT 차이만 owner conflict로 보낸다.

**Architecture:** 기존 `motion-blind-v1` 순수 비교기는 그대로 두고 v1 결과를 좁게 변환하는
`motion-blind-live-v2-highlight-soft` 비교기와 version dispatcher를 추가한다. DB slot에 immutable
comparator snapshot을 저장하고 finalize trigger가 slot/version/scope/date를 검증해 formal canary와
기존 live를 v1로 고정한다.

**Tech Stack:** TypeScript, Next.js App Router, Vitest, PostgreSQL/Supabase, pytest

**현재 상태:** Task 1~5 완료 / `IMPLEMENTED_VERIFIED_NOT_DEPLOYED`. Task 6 미실행.

## Global Constraints

- `motion-blind-v1`, formal Blind30 v1/v2 TEST-SHEET, 기존 cohort/slot/submission/consensus/event를 변경하지 않는다.
- activation은 `2026-08-01` activity-day이고, 그날 이후 **새로 INSERT되는 live slot**만 v2다.
- v2 nonblocking 필드는 `highlight_recommendation` 하나뿐이다.
- highlight-only 합의의 최종 highlight는 `uncertain`이다.
- `interaction_types`, segment 500ms, 나머지 GT 필드는 v1과 같은 core conflict다.
- request body에서 comparator version을 받지 않고 인증된 slot snapshot만 신뢰한다.
- production 기존 row UPDATE/DELETE, 과거 consensus 재계산, R2 write/delete는 0이다.
- Gemini CLI는 사용하지 않는다.

---

### Task 1: 순수 live v2 비교기

**Files:**
- Create: `web/src/lib/motionBlindReviewV2.ts`
- Create: `web/src/lib/motionBlindReviewV2.test.ts`
- Modify: `web/src/lib/motionBlindReview.ts`

**Interfaces:**
- Consumes: `compareBlindSubmissions(a, b)`, `BlindSubmissionInput`, `BlindComparison`
- Produces:
  - `LIVE_V2_COMPARATOR_VERSION = 'motion-blind-live-v2-highlight-soft'`
  - `BlindComparatorVersion`
  - `compareBlindSubmissionsByVersion(version, a, b)`

- [x] **Step 1: v1 공개 type만 넓히는 실패 테스트를 작성한다**

```ts
expect(compareBlindSubmissionsByVersion('motion-blind-v1', a, b))
  .toEqual(compareBlindSubmissions(a, b));
expect(() => compareBlindSubmissionsByVersion('unknown' as never, a, b))
  .toThrow('unknown_blind_comparator_version');
```

- [x] **Step 2: highlight-only와 core 차이 RED 테스트를 작성한다**

```ts
const soft = compareBlindSubmissionsByVersion(
  LIVE_V2_COMPARATOR_VERSION,
  label({ highlight_recommendation: 'include' }),
  label({ highlight_recommendation: 'exclude' }),
);
expect(soft).toMatchObject({
  status: 'agreed',
  final_decision: 'label',
  differing_fields: ['highlight_recommendation'],
  comparator_version: LIVE_V2_COMPARATOR_VERSION,
});
expect(soft.final_gt?.highlight_recommendation).toBe('uncertain');

const core = compareBlindSubmissionsByVersion(
  LIVE_V2_COMPARATOR_VERSION,
  label({ primary_action: 'moving', highlight_recommendation: 'include' }),
  label({ primary_action: 'drinking', highlight_recommendation: 'exclude' }),
);
expect(core.status).toBe('conflict');
expect(core.differing_fields).toEqual(['primary_action', 'highlight_recommendation']);
```

- [x] **Step 3: RED를 확인한다**

Run:

```bash
cd web
npm test -- --run src/lib/motionBlindReviewV2.test.ts
```

Expected: module/export missing으로 FAIL.

- [x] **Step 4: 최소 v2 adapter와 dispatcher를 구현한다**

```ts
export const LIVE_V2_COMPARATOR_VERSION =
  'motion-blind-live-v2-highlight-soft' as const;
export type BlindComparatorVersion =
  | typeof BLIND_COMPARATOR_VERSION
  | typeof LIVE_V2_COMPARATOR_VERSION;

export function compareBlindSubmissionsByVersion(
  version: BlindComparatorVersion,
  a: BlindSubmissionInput,
  b: BlindSubmissionInput,
): VersionedBlindComparison {
  const base = compareBlindSubmissions(a, b);
  if (version === BLIND_COMPARATOR_VERSION) return base;
  if (version !== LIVE_V2_COMPARATOR_VERSION) {
    throw new Error('unknown_blind_comparator_version');
  }
  if (
    base.status === 'conflict'
    && base.differing_fields.length === 1
    && base.differing_fields[0] === 'highlight_recommendation'
  ) {
    const gt = a.initial_gt as GroundTruthInput;
    return {
      status: 'agreed',
      final_decision: 'label',
      final_gt: { ...gt, highlight_recommendation: 'uncertain' },
      differing_fields: ['highlight_recommendation'],
      comparator_version: LIVE_V2_COMPARATOR_VERSION,
    };
  }
  return { ...base, comparator_version: LIVE_V2_COMPARATOR_VERSION };
}
```

- [x] **Step 5: v1·wheel·segment 회귀까지 통과시킨다**

Run:

```bash
cd web
npm test -- --run src/lib/motionBlindReview.test.ts src/lib/motionBlindReviewV2.test.ts
```

Expected: 모든 test PASS. `interaction_types` 차이와 501ms 차이는 v2에서도 conflict.

- [x] **Step 6: 비교기 commit을 만든다**

```bash
git add web/src/lib/motionBlindReview.ts \
  web/src/lib/motionBlindReviewV2.ts \
  web/src/lib/motionBlindReviewV2.test.ts
git commit -m "feat: live highlight 완화 비교기 추가"
```

### Task 2: Slot version snapshot과 DB fail-closed guard

**Files:**
- Create: `migrations/2026-07-31_motion_blind_live_v2_highlight_soft.sql`
- Create: `tests/test_motion_blind_live_v2_highlight_soft_migration.py`
- Create: `tests/sql/motion_blind_live_v2_highlight_soft_probe.sql`
- Create: `scripts/run_motion_blind_live_v2_highlight_soft_probe.py`

**Interfaces:**
- Produces:
  - `motion_clip_review_slots.comparator_version`
  - `fn_set_motion_blind_slot_comparator_version()`
  - `fn_guard_motion_blind_consensus_comparator_version()`
  - 기존 `fn_finalize_motion_blind_consensus(...)`의 known-version allowlist 확장

- [x] **Step 1: migration 정적 RED를 작성한다**

```python
def test_slot_version_activation_and_immutability() -> None:
    assert "ADD COLUMN comparator_version" in SQL
    assert "motion-blind-live-v2-highlight-soft" in SQL
    assert "NEW.activity_day_kst >= DATE '2026-08-01'" in SQL
    assert "OLD.comparator_version IS DISTINCT FROM NEW.comparator_version" in SQL
    assert "ERRCODE = '0A000'" in SQL

def test_formal_canary_is_pinned_to_v1() -> None:
    assert "NEW.cohort_kind = 'canary'" in SQL
    assert "NEW.comparator_version := 'motion-blind-v1'" in SQL
```

- [x] **Step 2: disposable SQL probe RED를 작성한다**

Probe fixtures는 기존 v1 live, activation 이전 late slot, activation 이후 live, canary를 만들고 다음을
assert한다.

```sql
ASSERT v_existing_version = 'motion-blind-v1';
ASSERT v_before_activation = 'motion-blind-v1';
ASSERT v_after_activation = 'motion-blind-live-v2-highlight-soft';
ASSERT v_canary_version = 'motion-blind-v1';
```

다음 전이는 SQLSTATE를 확인하고 전부 rollback한다.

```sql
-- slot comparator UPDATE -> 0A000
-- canary + v2 finalize -> 22023
-- v2 slot + p_comparator_version=v1 -> 22023
-- 두 slot mixed version -> PT425 또는 22023
-- unknown comparator -> 22023
```

- [x] **Step 3: RED를 확인한다**

Run:

```bash
uv run pytest -q tests/test_motion_blind_live_v2_highlight_soft_migration.py
```

Expected: migration missing으로 FAIL.

- [x] **Step 4: forward migration을 구현한다**

Migration은 다음 순서를 하나의 transaction으로 적용한다.

```sql
BEGIN;

ALTER TABLE public.motion_clip_review_slots
  ADD COLUMN comparator_version text NOT NULL DEFAULT 'motion-blind-v1'
  CHECK (comparator_version IN (
    'motion-blind-v1',
    'motion-blind-live-v2-highlight-soft'
  ));

CREATE FUNCTION public.fn_set_motion_blind_slot_comparator_version()
RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF OLD.comparator_version IS DISTINCT FROM NEW.comparator_version THEN
      RAISE EXCEPTION 'slot comparator version is immutable' USING ERRCODE = '0A000';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.cohort_kind = 'canary' THEN
    NEW.comparator_version := 'motion-blind-v1';
  ELSIF NEW.activity_day_kst >= DATE '2026-08-01' THEN
    NEW.comparator_version := 'motion-blind-live-v2-highlight-soft';
  ELSE
    NEW.comparator_version := 'motion-blind-v1';
  END IF;
  RETURN NEW;
END;
$$;
```

INSERT trigger와 `UPDATE OF comparator_version` trigger를 각각 연결한다. consensus guard는
`awaiting -> agreed/conflict` 전이에서 같은 clip/cohort의 slot 두 개를 잠그고, count=2,
distinct version=1, `NEW.comparator_version=slot version`, canary=v1, v2 date boundary를 검사한다.
기존 finalizer 본문은 유지하고 첫 known-version guard만 다음처럼 확장한다.

```sql
IF p_comparator_version NOT IN (
  'motion-blind-v1',
  'motion-blind-live-v2-highlight-soft'
) THEN
  RAISE EXCEPTION 'unknown comparator version' USING ERRCODE = '22023';
END IF;
```

함수·trigger function은 `PUBLIC`, `anon`, `authenticated` EXECUTE를 revoke하고 필요한
table/function 권한은 기존 service-role 계약만 유지한다.

- [x] **Step 5: 정적·disposable DB probe를 통과시킨다**

Run:

```bash
uv run pytest -q tests/test_motion_blind_live_v2_highlight_soft_migration.py
uv run python scripts/run_motion_blind_live_v2_highlight_soft_probe.py --backend local-postgres
```

Expected: pytest PASS, 마지막 marker
`MOTION_BLIND_LIVE_V2_HIGHLIGHT_SOFT_PROBE_OK`, residue 0.

- [x] **Step 6: DB commit을 만든다**

```bash
git add migrations/2026-07-31_motion_blind_live_v2_highlight_soft.sql \
  tests/test_motion_blind_live_v2_highlight_soft_migration.py \
  tests/sql/motion_blind_live_v2_highlight_soft_probe.sql \
  scripts/run_motion_blind_live_v2_highlight_soft_probe.py
git commit -m "feat: live 비교기 버전 snapshot 추가"
```

### Task 3: 인증된 slot version으로 제출·finalize 라우팅

**Files:**
- Modify: `web/src/app/api/labeling-v3/blind/_access.ts`
- Create: `web/src/app/api/labeling-v3/blind/_access.test.ts`
- Modify: `web/src/lib/motionBlindReviewServer.ts`
- Modify: `web/src/app/api/labeling-v3/blind/[clipId]/route.ts`
- Modify: `web/src/app/api/labeling-v3/blind/[clipId]/submit/route.ts`
- Modify: corresponding `*.test.ts`

**Interfaces:**
- `AssignedBlindClip.comparatorVersion: BlindComparatorVersion`
- `BlindClipDetail.comparator_version: BlindComparatorVersion`
- submit route calls `compareBlindSubmissionsByVersion(assigned.comparatorVersion, ...)`
- finalizer receives `p_comparator_version=assigned.comparatorVersion`

- [x] **Step 1: access allowlist RED를 작성한다**

```ts
expect(assigned).toMatchObject({
  comparatorVersion: 'motion-blind-live-v2-highlight-soft',
});
expect(detail.comparator_version).toBe('motion-blind-live-v2-highlight-soft');
```

DB mock select는 `group_id, cohort_kind, comparator_version`을 요구해야 한다. unknown version,
canary+v2, 두 slot version mismatch는 일반화된 database/not-assigned 오류로 닫는다.

- [x] **Step 2: submit dispatch RED를 작성한다**

```ts
expect(finalizeCall?.[1].p_comparator_version)
  .toBe('motion-blind-live-v2-highlight-soft');
expect(await response.json()).toMatchObject({
  status: 'agreed',
  differing_fields: ['highlight_recommendation'],
});
```

request body에 `comparator_version`을 넣으면 기존 allowlist가 400을 반환하는 테스트도 유지한다.

- [x] **Step 3: RED를 확인한다**

Run:

```bash
cd web
npm test -- --run \
  'src/app/api/labeling-v3/blind/[clipId]/route.test.ts' \
  'src/app/api/labeling-v3/blind/[clipId]/submit/route.test.ts'
```

Expected: comparator version field/dispatcher missing으로 FAIL.

- [x] **Step 4: server-derived version 배선을 구현한다**

`_access.ts`의 slot select에 `comparator_version`을 추가하고 다음 allowlist로 닫는다.

```ts
export function isBlindComparatorVersion(value: unknown): value is BlindComparatorVersion {
  return value === BLIND_COMPARATOR_VERSION
    || value === LIVE_V2_COMPARATOR_VERSION;
}
```

상세 응답과 `AssignedBlindClip`에 검증된 version을 싣는다. submit route는 전역 상수 대신
`assigned.comparatorVersion`을 `compareBlindSubmissionsByVersion`과 finalize RPC에 동일하게
넘긴다. comparator 오류는 기존처럼 submission 보존 + `awaiting_peer`로 닫는다.

- [x] **Step 5: route·security 회귀를 통과시킨다**

Run:

```bash
cd web
npm test -- --run \
  src/lib/motionBlindReviewV2.test.ts \
  'src/app/api/labeling-v3/blind/[clipId]/route.test.ts' \
  'src/app/api/labeling-v3/blind/[clipId]/submit/route.test.ts'
```

Expected: PASS, 상대 submission 원문·digest·reviewer id 응답 0.

- [x] **Step 6: server wiring commit을 만든다**

```bash
git add web/src/app/api/labeling-v3/blind/_access.ts \
  web/src/lib/motionBlindReviewServer.ts \
  'web/src/app/api/labeling-v3/blind/[clipId]/route.ts' \
  'web/src/app/api/labeling-v3/blind/[clipId]/submit/route.ts' \
  web/src/app/api/labeling-v3/blind/_access.test.ts \
  web/src/lib/motionBlindReviewServer.test.ts \
  'web/src/app/api/labeling-v3/blind/[clipId]/route.test.ts' \
  'web/src/app/api/labeling-v3/blind/[clipId]/submit/route.test.ts'
git commit -m "feat: slot 비교기 버전으로 합의 라우팅"
```

### Task 4: Draft version 격리와 사용자 흐름

**Files:**
- Modify: `web/src/lib/motionBlindDraft.ts`
- Modify: `web/src/lib/motionBlindDraft.test.ts`
- Modify: `web/src/app/labeling/_blind-review-detail.tsx`
- Modify: `web/src/app/labeling/_blind-review-ui.test.tsx`

**Interfaces:**
- `BlindDraftScope.comparatorVersion: BlindComparatorVersion`
- 상세 API의 `clip.comparator_version`이 draft key/envelope의 유일한 version source

- [x] **Step 1: v1/v2 draft isolation RED를 작성한다**

```ts
expect(blindDraftKey(USER, CLIP, 'live', null, 'motion-blind-v1'))
  .not.toBe(blindDraftKey(
    USER, CLIP, 'live', null, 'motion-blind-live-v2-highlight-soft',
  ));
expect(parseBlindDraft(v1Raw, v2Scope, 60)).toBeNull();
```

- [x] **Step 2: 상세 화면 RED를 작성한다**

v2 detail fixture를 반환하고 `sessionStorage` key가 v2 version을 포함하는지, v1 draft가 복원되지
않는지, 제출 payload에는 version이 추가되지 않는지 검증한다.

- [x] **Step 3: RED를 확인한다**

Run:

```bash
cd web
npm test -- --run src/lib/motionBlindDraft.test.ts src/app/labeling/_blind-review-ui.test.tsx
```

Expected: v2 type/detail wiring missing으로 FAIL.

- [x] **Step 4: detail-derived draft scope를 구현한다**

전역 `BLIND_COMPARATOR_VERSION` 대신 로드된 `detail.comparator_version`으로 key, envelope,
read/write/clear를 모두 만든다. detail이 오기 전에는 draft를 읽거나 쓰지 않는다. lease key와
submit body는 변경하지 않는다.

- [x] **Step 5: draft/UI 회귀를 통과시킨다**

Run:

```bash
cd web
npm test -- --run src/lib/motionBlindDraft.test.ts src/app/labeling/_blind-review-ui.test.tsx
```

Expected: PASS. v1 draft 복원, v2 격리, invalid envelope fail-soft가 모두 유지된다.

- [x] **Step 6: UI wiring commit을 만든다**

```bash
git add web/src/lib/motionBlindDraft.ts web/src/lib/motionBlindDraft.test.ts \
  web/src/app/labeling/_blind-review-detail.tsx \
  web/src/app/labeling/_blind-review-ui.test.tsx
git commit -m "feat: live 비교기별 임시본 격리"
```

### Task 5: 통합 회귀·문서·독립 리뷰

**Files:**
- Modify: `docs/DATABASE.md`
- Modify: `specs/next-session.md`
- Modify: `docs/decision-gate.md`
- Create: `docs/handoff-prompts/2026-07-31-motion-blind-live-v2-highlight-soft-report.md`

**Interfaces:**
- 문서 상태는 배포 전 `IMPLEMENTED_UNVERIFIED`, 배포 후에만 `DEPLOYED_VERIFIED`

- [x] **Step 1: focused suite를 실행한다**

```bash
cd web
npm test -- --run \
  src/lib/motionBlindReview.test.ts \
  src/lib/motionBlindReviewV2.test.ts \
  src/lib/motionBlindDraft.test.ts \
  'src/app/api/labeling-v3/blind/[clipId]/route.test.ts' \
  'src/app/api/labeling-v3/blind/[clipId]/submit/route.test.ts' \
  src/app/labeling/_blind-review-ui.test.tsx
cd ..
uv run pytest -q tests/test_motion_blind_live_v2_highlight_soft_migration.py \
  tests/test_motion_blind_formal30_migration.py \
  tests/test_motion_blind_formal30_v2_migration.py
```

Expected: all PASS.

- [x] **Step 2: full relevant validation을 실행한다**

```bash
cd web
npm test
npx tsc --noEmit
npm run audit:labeling-role-ui
cd ..
uv run pytest -q
git diff --check
```

Expected: 기존 명시된 환경 skip 외 실패 0.

- [x] **Step 3: 계약 diff를 감사한다**

```bash
git diff origin/main...HEAD --stat
git diff origin/main...HEAD -- \
  web/src/lib/motionBlindReview.ts \
  experiments/rba-data-engine-blind30-v2/TEST-SHEET.md \
  migrations/2026-07-31_motion_blind_formal30_v2.sql
```

Expected: v1 순수 comparator 동작과 Blind30 TEST-SHEET/migration 변경 0. 변경 파일 10개 이상이면
`git diff --stat`으로 기능별 그룹을 나눈 뒤 순차 리뷰한다.

- [x] **Step 4: 문서와 보고서를 갱신한다**

보고서에는 exact HEAD/upstream/clean, tests, migration hash, 기존 production row mutation 0,
activation boundary, v1/formal 불변, 배포 전후 상태를 기록한다. decision gate 로그는 기존 행을
수정하지 않고 새 행을 append한다.

- [x] **Step 5: 최종 implementation commit과 non-force push를 수행한다**

```bash
git add docs/DATABASE.md specs/next-session.md docs/decision-gate.md \
  docs/handoff-prompts/2026-07-31-motion-blind-live-v2-highlight-soft-report.md
git commit -m "docs: live highlight 완화 운영 계약 기록"
git fetch origin
git merge-base --is-ancestor origin/main HEAD
git push --set-upstream origin codex/live-comparator-v2-highlight-soft
```

Expected: non-force push 성공, worktree clean.

### Task 6: Production migration·Web 배포·activation 검증

**Files:**
- No new source files unless a failing production-equivalent test requires a TDD fix.

**Interfaces:**
- Supabase project ref: `slxjvzzfisxqwnghvrit`
- activation: `2026-08-01` activity-day
- production URL: `https://label.tera-ai.uk`

- [ ] **Step 1: 배포 전 read-only baseline을 고정한다**

기존 slot version column 부재, formal v1 closed 1/60/0/30, formal v2 0/0/0/0, live
slot/submission/consensus count와 지문, 현재 open canary를 기록한다. GT 원문·UUID·R2 key·secret은
보고하지 않는다.

- [ ] **Step 2: main 통합 조건을 확인한다**

```bash
git fetch origin
git merge-base --is-ancestor origin/main HEAD
git status --short
```

Expected: fast-forward 가능, clean. 아니면 rebase 대신 새 origin/main 기반 worktree에서 검증 후
ff-only 통합한다. force push 금지.

- [ ] **Step 3: migration을 정확히 한 번 적용한다**

적용 파일 SHA-256을 기록하고 authenticated Terra AI Supabase session 또는 승인된 migration
경로로 transaction 전체를 한 번 실행한다. 실패 시 재실행하지 않고 catalog와 transaction rollback
상태를 읽기 전용 확인한다.

- [ ] **Step 4: migration 사후 구조와 기존 데이터 불변을 확인한다**

```text
slot comparator column/check/default/insert trigger/immutable trigger = present
consensus finalize guard = present
anon/authenticated execute = false
service_role execute = true
existing slots comparator_version = motion-blind-v1
formal canary non-v1 slots = 0
unknown/mixed slot pairs = 0
existing submission/consensus/event hashes = baseline
```

- [ ] **Step 5: Web production을 배포한다**

main exact SHA를 Vercel production에 배포하고 deployment가 `READY`인지 확인한다. 로그인,
v1 live detail, closed formal link 410, owner overview를 smoke한다. reviewer 대신 실제 label
submission은 만들지 않는다.

- [ ] **Step 6: activation 경계를 검증한다**

2026-08-01 activity-day 첫 materialized live slot이 생기면 read-only로 두 slot 모두
`motion-blind-live-v2-highlight-soft`인지 확인한다. activation 이전/기존/canary slot은 v1이어야
한다. 아직 새 slot이 없으면 배포 완료와 trigger disposable probe를 보고하고, 실제 첫 slot 확인은
기존 heartbeat가 후속 점검하되 source 배포 완료를 과장하지 않는다.

- [ ] **Step 7: 완료 상태를 기록한다**

다음을 모두 만족할 때만 `DEPLOYED_VERIFIED`로 보고한다.

```text
HEAD = origin/main = deployed SHA
worktree clean
DB migration/function/trigger/privilege verified
Web deployment READY
v1/formal rows unchanged
production existing row UPDATE/DELETE = 0
focused/full tests pass
```

실제 첫 v2 slot이 아직 없다면 상태를
`DEPLOYED_VERIFIED_ACTIVATION_PENDING_FIRST_LIVE_SLOT`로 구분한다.

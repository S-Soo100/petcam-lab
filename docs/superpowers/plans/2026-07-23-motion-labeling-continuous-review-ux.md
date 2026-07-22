# Motion Labeling v3 연속 검수 UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** owner가 분류 결과를 확인한 뒤 현재 필터에서 다음 미분류 영상으로 이동하는 연속 검수 UX를 제공한다.

**Architecture:** 목록 필터를 상세 URL query로 전달하고, 신규 owner-only next endpoint가 기존 큐 RPC의 `(started_at,id)` keyset을 재사용한다. 분류 성공 후 강제 탭 이동을 없애고 undo·다음 영상 Card를 표시하며, 기존 DB GT guard와 blind 계약은 그대로 유지한다.

**Tech Stack:** Next.js 14 App Router, React, TypeScript, Vitest, Supabase RPC, Tailwind CSS, pytest

## Global Constraints

- 신규 DB migration·RPC 생성 금지. 기존 `fn_list_motion_clip_labeling_queue`만 재사용한다.
- 기존 PT424 GT guard, blind GT, append-only event 계약을 변경하지 않는다.
- owner `/labeling/motion` 기본 탭은 `unreviewed`, `all`은 URL에 명시한다.
- 자동 다음 이동 금지. 사용자가 결과 확인 후 버튼으로 이동한다.
- legacy/tutorial/VLM/Python Evidence/behavior/activity 변경 금지.
- production canary는 test-camera clip만 사용하고 종료 시 `reset`한다.
- TDD RED→GREEN, task별 conventional commit, force push·파괴적 git 금지.

---

### Task 1: 미분류 기본 탭과 목록 문맥 helper

**Files:**
- Modify: `web/src/lib/labelingV3QueueClient.ts`
- Modify: `web/src/lib/labelingV3QueueClient.test.ts`
- Modify: `web/src/app/labeling/_motion-queue.tsx`

**Interfaces:**
- Produces: `motionQueuePath(filters: MotionQueueUiFilters, extra?: { reviewComplete?: boolean }): string`
- Produces: `motionDetailPath(clipId: string, filters: MotionQueueUiFilters): string`
- Produces: `motionQueueScrollKey(filters: MotionQueueUiFilters): string`

- [ ] **Step 1: 기본 탭·path helper RED 테스트 작성**

```ts
expect(parseMotionQueueFilters(new URLSearchParams()).state).toBe('unreviewed');
expect(toMotionQueueQuery({ state: 'all' })).toBe('state=all');
expect(motionQueuePath({ state: 'unreviewed' })).toBe('/labeling/motion?state=unreviewed');
expect(motionDetailPath('clip-1', {
  state: 'unreviewed', camera_id: ['cam-1'], media: 'ready',
})).toBe('/labeling/motion/clip-1?state=unreviewed&camera_id=cam-1&media=ready');
expect(motionQueueScrollKey({ state: 'unreviewed' }))
  .toBe('petcam-motion-queue-scroll:state=unreviewed');
```

- [ ] **Step 2: RED 확인**

Run from `web/`:

```bash
npm test -- src/lib/labelingV3QueueClient.test.ts
```

Expected: 빈 query가 `all`이고 신규 helper export가 없어 FAIL.

- [ ] **Step 3: 순수 helper 최소 구현**

```ts
export function motionQueuePath(
  filters: MotionQueueUiFilters,
  extra: { reviewComplete?: boolean } = {},
): string {
  const p = new URLSearchParams(toMotionQueueQuery(filters));
  if (extra.reviewComplete) p.set('review_complete', '1');
  return `/labeling/motion?${p.toString()}`;
}

export function motionDetailPath(
  clipId: string,
  filters: MotionQueueUiFilters,
): string {
  const query = toMotionQueueQuery(filters);
  return `/labeling/motion/${clipId}${query ? `?${query}` : ''}`;
}

export function motionQueueScrollKey(filters: MotionQueueUiFilters): string {
  return `petcam-motion-queue-scroll:${toMotionQueueQuery(filters)}`;
}
```

`parseMotionQueueFilters()`의 state 기본값을 `unreviewed`로 바꾸고, `toMotionQueueQuery()`는 `all`도 `state=all`로 기록한다. query 순서는 `state → camera_id → date_from → date_to → media`로 고정한다.

- [ ] **Step 4: owner 탭과 카드 링크 연결**

`OWNER_TABS`를 다음 순서로 바꾼다.

```ts
const OWNER_TABS = [
  { key: 'unreviewed', label: '미분류' },
  { key: 'all', label: '전체 영상' },
  { key: 'label', label: '라벨 대기' },
  { key: 'hold', label: '보류' },
  { key: 'skip', label: '제외' },
] as const;
```

`MotionCard`에 `filters`를 전달하고 `href={motionDetailPath(clip.id, filters)}`를 사용한다. 기존 최신순 정렬·cursor·stale response guard는 변경하지 않는다.

- [ ] **Step 5: GREEN 확인 후 커밋**

```bash
npm test -- src/lib/labelingV3QueueClient.test.ts
git add web/src/lib/labelingV3QueueClient.ts web/src/lib/labelingV3QueueClient.test.ts web/src/app/labeling/_motion-queue.tsx
git commit -m "feat: 미분류 기본 큐와 상세 문맥 연결"
```

### Task 2: 목록 스크롤 복원과 완료 안내

**Files:**
- Modify: `web/src/app/labeling/_motion-queue.tsx`
- Modify: `web/src/lib/labelingV3QueueClient.ts`
- Modify: `web/src/lib/labelingV3QueueClient.test.ts`

**Interfaces:**
- Consumes: `motionQueueScrollKey(filters)`
- Produces: `readStoredMotionQueueScroll(storage: Storage, key: string): number | null`

- [ ] **Step 1: storage parser RED 테스트 작성**

```ts
const storage = new MapStorage({ key: '320.5' });
expect(readStoredMotionQueueScroll(storage, 'key')).toBe(320.5);
expect(storage.getItem('key')).toBeNull();
expect(readStoredMotionQueueScroll(new MapStorage({ key: '-1' }), 'key')).toBeNull();
expect(readStoredMotionQueueScroll(new MapStorage({ key: 'NaN' }), 'key')).toBeNull();
```

테스트용 `MapStorage`는 test 파일 안에서 `getItem/removeItem`만 구현한다.

- [ ] **Step 2: RED 확인**

```bash
npm test -- src/lib/labelingV3QueueClient.test.ts
```

- [ ] **Step 3: one-shot parser 구현**

```ts
export function readStoredMotionQueueScroll(
  storage: Pick<Storage, 'getItem' | 'removeItem'>,
  key: string,
): number | null {
  const raw = storage.getItem(key);
  storage.removeItem(key);
  if (raw === null) return null;
  const value = Number(raw);
  return Number.isFinite(value) && value >= 0 ? value : null;
}
```

- [ ] **Step 4: queue에 저장·복원 연결**

- 카드 `onClick` 직전에 `sessionStorage.setItem(key, String(window.scrollY))`를 best-effort `try/catch`로 저장한다.
- queue가 첫 페이지를 렌더하고 `loadedOnce && !busy`가 되면 저장값을 한 번 읽어 `window.scrollTo({ top, behavior: 'auto' })`한다.
- `searchParams.get('review_complete') === '1'`이면 성공 Card `이 조건의 검수를 모두 마쳤어.`를 표시한다.
- 사용자가 탭·필터를 바꾸면 `review_complete`는 제거한다.

- [ ] **Step 5: GREEN 확인 후 커밋**

```bash
npm test -- src/lib/labelingV3QueueClient.test.ts
git add web/src/app/labeling/_motion-queue.tsx web/src/lib/labelingV3QueueClient.ts web/src/lib/labelingV3QueueClient.test.ts
git commit -m "feat: 운영 큐 문맥과 스크롤 복원"
```

### Task 3: owner 전용 다음 미분류 API

**Files:**
- Create: `web/src/app/api/labeling-v3/[clipId]/next/route.ts`
- Create: `web/src/app/api/labeling-v3/[clipId]/next/route.test.ts`
- Modify: `web/src/app/api/labeling-v3/queue/route.ts`
- Create: `web/src/lib/labelingV3QueueServer.ts`
- Create: `web/src/lib/labelingV3QueueServer.test.ts`
- Modify: `web/src/lib/labelingV3Api.ts`
- Modify: `web/src/lib/labelingV3.ts`

**Interfaces:**
- Produces: `parseMotionQueueRequest(search: URLSearchParams, isOwner: boolean)`
- Produces: `GET /api/labeling-v3/[clipId]/next`
- Produces: `getNextUnreviewedMotionClip(clipId: string, filters: MotionQueueUiFilters): Promise<{ next_clip_id: string | null }>`

- [ ] **Step 1: shared parser RED 테스트 작성**

기존 queue route의 `limit/state/camera/date/media` 검증 케이스를 `labelingV3QueueServer.test.ts`로 옮기고 다음을 추가한다.

```ts
expect(parseMotionQueueRequest(new URLSearchParams('state=unreviewed&media=ready'), true))
  .toMatchObject({ params: { state: 'unreviewed', media: 'ready' } });
expect(parseMotionQueueRequest(new URLSearchParams('camera_id=bad'), true))
  .toEqual({ error: '잘못된 camera_id' });
```

- [ ] **Step 2: RED 확인 후 parser 추출**

```bash
npm test -- src/lib/labelingV3QueueServer.test.ts src/app/api/labeling-v3/queue/route.test.ts
```

`UUID`, RFC3339, owner states, limit clamp와 parser를 `labelingV3QueueServer.ts`로 이동한다. queue route는 이 helper를 호출하고 응답 계약은 byte-equivalent하게 유지한다.

- [ ] **Step 3: next route RED 테스트 작성**

다음 케이스를 route test에 고정한다.

```text
owner + current clip → motion_clips started_at 조회 1회
RPC p_state=unreviewed, p_cursor_started_at=current.started_at,
    p_cursor_id=current.id, p_limit=1
camera/date/media 필터 전달
same timestamp는 current id cursor 전달
결과 1행 → next_clip_id
결과 0행 → null
labeler → 403, DB 접근 0
invalid clip UUID/filter → 400, DB 접근 0
current clip 없음 → 404
DB 원문 → 공개 502, 원문 비노출
```

- [ ] **Step 4: next route 최소 구현**

route는 `requireProductionLabelingAccess()` 뒤 owner를 확인한다. `motion_clips`에서 current `id,started_at`만 읽고 기존 RPC를 호출한다.

```ts
const { data } = await supabaseAdmin.rpc('fn_list_motion_clip_labeling_queue', {
  p_reviewer_id: access.userId,
  p_is_owner: true,
  p_state: 'unreviewed',
  p_camera_ids: parsed.params.cameraIds,
  p_date_from: parsed.params.dateFrom,
  p_date_to: parsed.params.dateTo,
  p_media: parsed.params.media,
  p_cursor_started_at: current.started_at,
  p_cursor_id: clipId,
  p_limit: 1,
});
return NextResponse.json({ next_clip_id: data?.[0]?.clip_id ?? null });
```

client API는 큐 query helper를 재사용하되 `state`는 보내지 않는다. 공개 응답 타입 `MotionNextResponse`를 `labelingV3.ts`에 둔다.

- [ ] **Step 5: GREEN 확인 후 커밋**

```bash
npm test -- src/lib/labelingV3QueueServer.test.ts src/app/api/labeling-v3/queue/route.test.ts 'src/app/api/labeling-v3/[clipId]/next/route.test.ts'
git add web/src/app/api/labeling-v3/queue/route.ts 'web/src/app/api/labeling-v3/[clipId]/next/route.ts' 'web/src/app/api/labeling-v3/[clipId]/next/route.test.ts' web/src/lib/labelingV3QueueServer.ts web/src/lib/labelingV3QueueServer.test.ts web/src/lib/labelingV3Api.ts web/src/lib/labelingV3.ts
git commit -m "feat: 현재 필터의 다음 미분류 영상 조회"
```

### Task 4: 상세 결과 확인·undo·다음 영상 UX

**Files:**
- Modify: `web/src/lib/labelingV3.ts`
- Modify: `web/src/lib/labelingV3.test.ts`
- Modify: `web/src/app/labeling/motion/_motion-decision-controls.tsx`
- Create: `web/src/app/labeling/motion/_motion-review-continuation.tsx`
- Create: `web/src/app/labeling/motion/_motion-review-continuation.test.tsx`
- Modify: `web/src/app/labeling/motion/[clipId]/page.tsx`

**Interfaces:**
- Removes: `motionDecisionListPath()`
- Produces: `motionUndoDecision(previous: MotionLabelingState): MotionDecision`
- Produces: `MotionDecisionChange { previous, next, updatedAt }`

- [ ] **Step 1: undo 순수 규칙 RED 테스트 작성**

```ts
expect(motionUndoDecision('unreviewed')).toBe('reset');
expect(motionUndoDecision('label')).toBe('label');
expect(motionUndoDecision('hold')).toBe('hold');
expect(motionUndoDecision('skip')).toBe('skip');
```

기존 `motionDecisionListPath()` 테스트는 삭제하고, `hold/skip` 후 강제 route를 기대하는 테스트가 남지 않게 한다.

- [ ] **Step 2: RED 확인 후 decision callback 확장**

```bash
npm test -- src/lib/labelingV3.test.ts
```

`MotionDecisionControls`는 성공 전 `state`를 previous로 캡처하고 다음 payload를 전달한다.

```ts
onDecided({ previous: state, next: result.state, updatedAt: result.updated_at });
```

- [ ] **Step 3: continuation component RED 테스트 작성**

React test 환경이 없으면 기존 프로젝트 방식대로 순수 view-model helper를 분리해 테스트한다. 반드시 다음 행위를 고정한다.

```text
skip → "제외로 저장됨", GT CTA 없음, undo/next 표시
hold → "보류로 저장됨", undo/next 표시
label → "라벨 대상으로 저장됨", GT/next 표시
next busy → 중복 클릭 비활성
next error → 저장 성공 문구 유지 + "다음 영상 다시 찾기"
```

- [ ] **Step 4: page 흐름 구현**

- `useSearchParams()`로 상세 query를 `parseMotionQueueFilters()`에 전달한다.
- 목록 링크는 `motionQueuePath(filters)`를 사용한다.
- decision 성공 후 `router.push()`를 호출하지 않는다.
- `decisionChange` state를 저장하고 continuation Card를 표시한다.
- undo는 current `updatedAt`을 expected 값으로 보내고 성공 시 Card를 닫는다.
- next는 `getNextUnreviewedMotionClip()`을 호출한다. id가 있으면 `router.push(motionDetailPath(id, filters))`, null이면 `router.push(motionQueuePath(filters,{reviewComplete:true}))`한다.
- next 이동 중 대상이 409/404이면 최대 3회 재조회하고 이후 목록으로 돌아간다.
- `hold/skip`에서는 `GroundTruthForm`을 렌더하지 않는다. 기존 안내 Card와 PT424 catch는 유지한다.
- label에서는 `지금 사람 판정 작성`이 GT anchor로 스크롤하고 `나중에 라벨링하고 다음 영상`이 next를 호출한다.
- completed phase에도 `다음 미분류 영상`을 표시한다.

- [ ] **Step 5: GREEN 확인 후 커밋**

```bash
npm test -- src/lib/labelingV3.test.ts 'src/app/labeling/motion/_motion-review-continuation.test.tsx'
git add web/src/lib/labelingV3.ts web/src/lib/labelingV3.test.ts web/src/app/labeling/motion/_motion-decision-controls.tsx web/src/app/labeling/motion/_motion-review-continuation.tsx 'web/src/app/labeling/motion/_motion-review-continuation.test.tsx' 'web/src/app/labeling/motion/[clipId]/page.tsx'
git commit -m "feat: 분류 결과 확인과 다음 영상 흐름 추가"
```

### Task 5: 전체 회귀·preview·production 검수

**Files:**
- Create: `docs/handoff-prompts/2026-07-23-motion-labeling-continuous-review-ux-report.md`
- Modify: `docs/FEATURES.md`
- Modify: `specs/next-session.md`
- Modify: `.claude/donts-audit.md`

**Interfaces:**
- Produces: 최종 verdict `MOTION_CONTINUOUS_REVIEW_UX_VERIFIED` 또는 구체적 `BLOCKED_*`.

- [ ] **Step 1: 전체 검증**

```bash
cd web
npm test
npx tsc --noEmit
npm run build
cd ..
uv run pytest -q
git diff --check
```

`npm run build`가 세션 훅으로 막히면 사용자 터미널 실행 명령을 정확히 보고하고 build를 미검증으로 둔다. tsc 성공을 build 성공으로 쓰지 않는다.

- [ ] **Step 2: 금지동작 감사**

```text
migration/RPC DDL 0
GT/VLM/behavior/activity write 신규 경로 0
legacy/tutorial 변경 0
결정 성공 후 hold/skip category router.push 0
외부 returnTo/open redirect 0
자동 next navigation 0
```

- [ ] **Step 3: feature push와 preview 검수**

task별 커밋을 push하고 Vercel preview를 만든다. owner 세션으로 test-camera clip 10건을 다음 조합으로 검수한다.

```text
skip 3 → stay + undo + next
hold 3 → stay + next
label 2 → GT CTA + next
same-timestamp/필터 경계 2 → 중복·누락 0
```

canary decision은 검수 종료 시 원래 state로 복구한다. GT는 저장하지 않는다.

- [ ] **Step 4: report 초안과 commit**

보고서에 RED→GREEN, 변경 파일, test/build, preview 10건, 미검증 항목, rollback을 기록한다.

```bash
git add docs/handoff-prompts/2026-07-23-motion-labeling-continuous-review-ux-report.md docs/FEATURES.md specs/next-session.md .claude/donts-audit.md
git commit -m "docs: 운영 영상 연속 검수 UX 보고"
git push -u origin codex/motion-labeling-continuous-review-ux
```

- [ ] **Step 5: main FF-only·production 배포**

clean disposable worktree에서 feature가 `origin/main`의 descendant인지 확인하고 `--ff-only`만 사용한다. Vercel production 배포 뒤 test-camera clip으로 다음을 확인한다.

```text
제외 → 상세 유지 → 결정 취소 → unreviewed 복구
보류 → 상세 유지 → 다음 미분류 → 원래 필터 유지
목록 복귀 → scroll 복원
다음 없음 → 완료 안내
```

production canary는 종료 시 `reset`하고 GT를 저장하지 않는다. 실패하면 직전 Ready deployment로 rollback하고 DB에는 손대지 않는다.

- [ ] **Step 6: SOT·최종 보고 갱신**

main/Vercel SHA, production canary, canary 복구 state, mutation 범위, rollback 가능성을 보고서에 추가한다. 최종 판정은 모든 게이트가 확인됐을 때만 `MOTION_CONTINUOUS_REVIEW_UX_VERIFIED`로 한다.

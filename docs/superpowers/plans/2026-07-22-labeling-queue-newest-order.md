# Labeling Queue Newest-Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/labeling` 큐가 동일 timestamp, pagination, 필터 경합에서도 `(started_at DESC, id DESC)` 최신순을 누락·중복 없이 유지하게 만든다.

**Architecture:** 서버는 versioned opaque composite cursor를 해석해 PostgREST에 두 정렬키와 keyset 조건을 적용한다. 공통 큐 수집기는 object position을 전달하고, 클라이언트는 request generation과 pure merge helper로 stale 응답·중복·정렬 이탈을 막는다. DB schema와 blind GT 응답 필드는 바꾸지 않는다.

**Tech Stack:** Next.js 14 App Router, TypeScript, Supabase JS/PostgREST, Vitest

## Global Constraints

- 기준 설계: `/Users/baek/petcam-lab/.worktrees/labeling-queue-newest-exec/docs/superpowers/specs/2026-07-22-labeling-queue-newest-order-design.md`
- execution branch: `codex/labeling-queue-newest-exec`; 작업 시작 HEAD는 handoff의 40자리 SHA와 같아야 한다.
- 정본 정렬은 `started_at DESC, id DESC`; 다른 시간 필드로 바꾸지 않는다.
- behavior/VLM/Python Evidence 필드를 조회·응답하지 않는다.
- migration, production DB write, triage 정책 변경, 자동 skip 변경은 금지한다.
- 기존 사용자 미커밋·untracked 파일을 삭제·추가·커밋하지 않는다.
- production 배포는 전체 검증 뒤 owner 승인 범위에서만 수행한다.

---

## File Structure

| File | Responsibility |
|---|---|
| `web/src/lib/labelingQueueCursor.ts` | composite cursor encode/decode와 validation |
| `web/src/lib/labelingQueueCursor.test.ts` | cursor round-trip·invalid input 회귀 |
| `web/src/lib/labelingQueue.ts` | object position을 사용하는 bounded queue scan |
| `web/src/lib/labelingQueue.test.ts` | 동률·필터 skip·다음 cursor 누락/중복 검증 |
| `web/src/lib/labelingQueueClient.ts` | clip dedup·최신순 merge pure helper |
| `web/src/lib/labelingQueueClient.test.ts` | 중복·역순 응답·동률 정렬 검증 |
| `web/src/app/api/labeling-v2/queue/route.ts` | cursor 400·이중 order·composite keyset 적용 |
| `web/src/app/api/labeling-v2/queue/route.test.ts` | route query/응답/오류 회귀 |
| `web/src/app/labeling/page.tsx` | generation guard·replace/append·UI state 초기화 |
| `docs/FEATURES.md` | 큐 최신순·복합 cursor 계약 |
| `.claude/donts-audit.md` | stale response와 timestamp-only cursor 교훈 |

---

### Task 1: Versioned composite cursor

**Files:**
- Create: `web/src/lib/labelingQueueCursor.ts`
- Create: `web/src/lib/labelingQueueCursor.test.ts`

**Interfaces:**
- Produces: `QueuePosition { startedAt: string; id: string }`
- Produces: `InvalidQueueCursorError`
- Produces: `encodeQueueCursor(position: QueuePosition): string`
- Produces: `decodeQueueCursor(raw: string | null): QueuePosition | null`

- [ ] **Step 1: Write RED tests**

```ts
import { describe, expect, it } from 'vitest';
import {
  decodeQueueCursor,
  encodeQueueCursor,
  InvalidQueueCursorError,
} from './labelingQueueCursor';

const POSITION = {
  startedAt: '2026-07-22T01:02:03.456Z',
  id: '11111111-1111-4111-8111-111111111111',
};

describe('labelingQueueCursor', () => {
  it('round-trips a URL-safe version 1 cursor', () => {
    const encoded = encodeQueueCursor(POSITION);
    expect(encoded).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(decodeQueueCursor(encoded)).toEqual(POSITION);
  });

  it.each([
    'not-base64!',
    Buffer.from(JSON.stringify({ v: 2, t: POSITION.startedAt, id: POSITION.id })).toString('base64url'),
    Buffer.from(JSON.stringify({ v: 1, t: 'bad', id: POSITION.id })).toString('base64url'),
    Buffer.from(JSON.stringify({ v: 1, t: POSITION.startedAt, id: 'bad' })).toString('base64url'),
  ])('rejects malformed cursor %s', (raw) => {
    expect(() => decodeQueueCursor(raw)).toThrow(InvalidQueueCursorError);
  });

  it('maps null to the first page', () => {
    expect(decodeQueueCursor(null)).toBeNull();
  });
});
```

- [ ] **Step 2: Run RED**

Run:

```bash
cd /Users/baek/petcam-lab/.worktrees/labeling-queue-newest-exec/web
npm test -- src/lib/labelingQueueCursor.test.ts
```

Expected: FAIL because `labelingQueueCursor.ts` does not exist.

- [ ] **Step 3: Implement the minimal cursor contract**

```ts
import 'server-only';
import { Buffer } from 'node:buffer';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export interface QueuePosition {
  startedAt: string;
  id: string;
}

export class InvalidQueueCursorError extends Error {
  constructor() {
    super('invalid_queue_cursor');
    this.name = 'InvalidQueueCursorError';
  }
}

function validTimestamp(value: unknown): value is string {
  return typeof value === 'string' && value.length <= 64 && !Number.isNaN(Date.parse(value));
}

export function encodeQueueCursor(position: QueuePosition): string {
  return Buffer.from(JSON.stringify({ v: 1, t: position.startedAt, id: position.id }), 'utf8')
    .toString('base64url');
}

export function decodeQueueCursor(raw: string | null): QueuePosition | null {
  if (raw === null || raw === '') return null;
  try {
    const value = JSON.parse(Buffer.from(raw, 'base64url').toString('utf8')) as Record<string, unknown>;
    if (value.v !== 1 || !validTimestamp(value.t) || typeof value.id !== 'string' || !UUID.test(value.id)) {
      throw new InvalidQueueCursorError();
    }
    return { startedAt: new Date(value.t).toISOString(), id: value.id.toLowerCase() };
  } catch (error) {
    if (error instanceof InvalidQueueCursorError) throw error;
    throw new InvalidQueueCursorError();
  }
}
```

- [ ] **Step 4: Run GREEN**

Run the Task 1 test command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/labelingQueueCursor.ts web/src/lib/labelingQueueCursor.test.ts
git commit -m "feat: 라벨링 큐 복합 cursor 계약 추가"
```

---

### Task 2: Queue scan uses a composite position

**Files:**
- Modify: `web/src/lib/labelingQueue.ts`
- Modify: `web/src/lib/labelingQueue.test.ts`

**Interfaces:**
- Consumes: `QueuePosition` from Task 1.
- Changes: `QueuePage.nextCursor` from `string | null` to `QueuePosition | null`.
- Changes: `fetchCandidates(cursor: QueuePosition | null, batchSize: number)`.

- [ ] **Step 1: Add RED tests for equal timestamps and next position**

Add a valid UUID to test clips and assert the tie order survives filtering:

```ts
it('returns an object cursor from the last visible item and preserves equal timestamps', async () => {
  const same = '2026-07-22T02:00:00Z';
  const rows = [
    clip('33333333-3333-4333-8333-333333333333', same),
    clip('22222222-2222-4222-8222-222222222222', same),
    clip('11111111-1111-4111-8111-111111111111', same),
  ];
  const result = await collectQueuePage({
    limit: 2,
    fetchCandidates: vi.fn().mockResolvedValue(rows),
    fetchStages: vi.fn().mockResolvedValue([]),
    fetchTriage: noTriage,
  });
  expect(result.items.map((row) => row.id)).toEqual(rows.slice(0, 2).map((row) => row.id));
  expect(result.nextCursor).toEqual({ startedAt: same, id: rows[1].id });
});
```

Update existing assertions from timestamp strings to `{ startedAt, id }`.

- [ ] **Step 2: Run RED**

```bash
cd /Users/baek/petcam-lab/.worktrees/labeling-queue-newest-exec/web
npm test -- src/lib/labelingQueue.test.ts
```

Expected: type/test failures because cursor is still a string.

- [ ] **Step 3: Implement object cursor propagation**

Import `QueuePosition`. Replace `scanCursor: string | null` with `QueuePosition | null` and advance it with
the final fetched candidate:

```ts
const lastScanned = candidates[candidates.length - 1];
scanCursor = { startedAt: lastScanned.started_at, id: lastScanned.id };
```

Return the last visible item as `nextCursor` only when `hasMore`:

```ts
const lastVisible = items[items.length - 1];
nextCursor: hasMore && lastVisible
  ? { startedAt: lastVisible.started_at, id: lastVisible.id }
  : null,
```

Do not change triage precedence or completed-stage behavior.

- [ ] **Step 4: Run GREEN**

Run Task 2 tests. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/labelingQueue.ts web/src/lib/labelingQueue.test.ts
git commit -m "refactor: 라벨링 큐 scan에 복합 위치 적용"
```

---

### Task 3: API applies deterministic order and returns opaque cursor

**Files:**
- Modify: `web/src/app/api/labeling-v2/queue/route.ts`
- Create: `web/src/app/api/labeling-v2/queue/route.test.ts`

**Interfaces:**
- Consumes: Task 1 cursor functions and Task 2 queue position.
- Produces: existing response shape; `next_cursor` remains `string | null` externally.
- Produces: `{ detail: '페이지 위치가 올바르지 않아.', code: 'invalid_cursor' }`, status 400.

- [ ] **Step 1: Write RED route tests**

Mock `requireProductionLabelingAccess`, `collectQueuePage`, and `supabaseAdmin`. Cover:

```ts
it('returns 400 invalid_cursor before DB access', async () => {
  const response = await GET(new NextRequest('http://test/api/labeling-v2/queue?cursor=bad!'));
  expect(response.status).toBe(400);
  expect(await response.json()).toEqual({
    detail: '페이지 위치가 올바르지 않아.',
    code: 'invalid_cursor',
  });
  expect(collectQueuePage).not.toHaveBeenCalled();
});

it('encodes the object next cursor returned by collectQueuePage', async () => {
  collectQueuePage.mockResolvedValue({
    items: [], hasMore: true,
    nextCursor: { startedAt: '2026-07-22T01:00:00.000Z', id: UUID_A },
  });
  const response = await GET(new NextRequest('http://test/api/labeling-v2/queue'));
  const body = await response.json();
  expect(decodeQueueCursor(body.next_cursor)).toEqual({
    startedAt: '2026-07-22T01:00:00.000Z', id: UUID_A,
  });
});
```

Add a query-builder test that records two `.order` calls and the composite `.or` filter.

- [ ] **Step 2: Run RED**

```bash
cd /Users/baek/petcam-lab/.worktrees/labeling-queue-newest-exec/web
npm test -- src/app/api/labeling-v2/queue/route.test.ts
```

Expected: FAIL before route implementation.

- [ ] **Step 3: Implement parse-before-DB and keyset query**

At the start of `GET`, after access and limit parsing:

```ts
let cursor: QueuePosition | null;
try {
  cursor = decodeQueueCursor(search.get('cursor'));
} catch (error) {
  if (error instanceof InvalidQueueCursorError) {
    return NextResponse.json(
      { detail: '페이지 위치가 올바르지 않아.', code: 'invalid_cursor' },
      { status: 400 },
    );
  }
  throw error;
}
```

The candidate query must contain:

```ts
.order('started_at', { ascending: false })
.order('id', { ascending: false })
```

When cursor exists:

```ts
query = query.or(
  `started_at.lt.${cursor.startedAt},and(started_at.eq.${cursor.startedAt},id.lt.${cursor.id})`,
);
```

Pass the decoded cursor into `collectQueuePage` and encode its object cursor for JSON. Keep DB failures inside the
existing `databaseUnavailable` catch; invalid cursor must stay outside that catch.

- [ ] **Step 4: Run GREEN and focused regression**

```bash
npm test -- src/app/api/labeling-v2/queue/route.test.ts src/lib/labelingQueue.test.ts src/lib/labelingQueueCursor.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/app/api/labeling-v2/queue/route.ts web/src/app/api/labeling-v2/queue/route.test.ts
git commit -m "fix: 라벨링 큐 API 최신순 keyset 보장"
```

---

### Task 4: Client merge and stale-response protection

**Files:**
- Create: `web/src/lib/labelingQueueClient.ts`
- Create: `web/src/lib/labelingQueueClient.test.ts`
- Modify: `web/src/app/labeling/page.tsx`

**Interfaces:**
- Produces: `mergeNewestQueueItems<T extends { id: string; started_at: string }>(base: T[], incoming: T[]): T[]`.
- Consumes: existing `createRequestGeneration()`.

- [ ] **Step 1: Write RED pure merge tests**

```ts
import { describe, expect, it } from 'vitest';
import { mergeNewestQueueItems } from './labelingQueueClient';

describe('mergeNewestQueueItems', () => {
  it('deduplicates by id and sorts started_at/id descending', () => {
    const rows = mergeNewestQueueItems(
      [{ id: 'a', started_at: '2026-07-22T01:00:00Z' }],
      [
        { id: 'a', started_at: '2026-07-22T01:00:00Z' },
        { id: 'c', started_at: '2026-07-22T02:00:00Z' },
        { id: 'b', started_at: '2026-07-22T02:00:00Z' },
      ],
    );
    expect(rows.map((row) => row.id)).toEqual(['c', 'b', 'a']);
  });
});
```

- [ ] **Step 2: Run RED**

```bash
npm test -- src/lib/labelingQueueClient.test.ts
```

Expected: missing module failure.

- [ ] **Step 3: Implement the pure merge helper**

```ts
export function mergeNewestQueueItems<T extends { id: string; started_at: string }>(
  base: T[], incoming: T[],
): T[] {
  const byId = new Map(base.map((row) => [row.id, row]));
  for (const row of incoming) byId.set(row.id, row);
  return [...byId.values()].sort((a, b) => {
    const time = b.started_at.localeCompare(a.started_at);
    return time !== 0 ? time : b.id.localeCompare(a.id);
  });
}
```

- [ ] **Step 4: Add generation guard to the page**

Import `useRef`, `createRequestGeneration`, and `mergeNewestQueueItems`.

```ts
const requestGeneration = useRef(createRequestGeneration());

const load = useCallback(async (nextCursor: string | null) => {
  const generation = requestGeneration.current.next();
  if (nextCursor === null) {
    setItems([]);
    setCursor(null);
    setHasMore(false);
    setLoadedOnce(false);
  }
  setBusy(true);
  setErr(null);
  try {
    const resp = await getQueue(/* existing args */);
    if (!requestGeneration.current.isCurrent(generation)) return;
    setItems((previous) => mergeNewestQueueItems(nextCursor ? previous : [], resp.items));
    setCursor(resp.next_cursor);
    setHasMore(resp.has_more);
  } catch (error) {
    if (!requestGeneration.current.isCurrent(generation)) return;
    // preserve current UnauthorizedError and user-facing error behavior
  } finally {
    if (requestGeneration.current.isCurrent(generation)) {
      setBusy(false);
      setLoadedOnce(true);
    }
  }
}, [router, filters]);
```

The effect cleanup must invalidate the request:

```ts
useEffect(() => {
  load(null);
  return () => { requestGeneration.current.next(); };
}, [load]);
```

Do not introduce polling or auto-refresh.

- [ ] **Step 5: Run GREEN**

```bash
npm test -- src/lib/labelingQueueClient.test.ts src/lib/requestGeneration.test.ts
npx tsc --noEmit
```

Expected: PASS, type errors 0.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/labelingQueueClient.ts web/src/lib/labelingQueueClient.test.ts web/src/app/labeling/page.tsx
git commit -m "fix: 라벨링 큐 stale 응답과 중복 정렬 차단"
```

---

### Task 5: Full verification, docs, and deployment stop report

**Files:**
- Modify: `docs/FEATURES.md`
- Modify: `.claude/donts-audit.md`
- Create: `docs/handoff-prompts/2026-07-22-labeling-queue-newest-order-report.md`

**Interfaces:**
- Produces verdict: `LABELING_QUEUE_NEWEST_READY_FOR_DEPLOY_REVIEW` or `LABELING_QUEUE_NEWEST_BLOCKED_<CODE>`.

- [ ] **Step 1: Update docs additively**

Record `(started_at DESC, id DESC)`, version 1 opaque cursor, stale-response generation, no schema/label change.
Do not rewrite unrelated historical sections.

- [ ] **Step 2: Run full verification**

```bash
cd /Users/baek/petcam-lab/.worktrees/labeling-queue-newest-exec/web
npm test
npx tsc --noEmit
npm run build
cd /Users/baek/petcam-lab/.worktrees/labeling-queue-newest-exec
uv run pytest -q
git diff --check
```

Expected: all web tests pass, TypeScript clean, Next build success, Python baseline pass, whitespace clean.

- [ ] **Step 3: Static privacy audit**

```bash
git diff HEAD~4..HEAD -- web/src | rg "prediction_snapshot|reasoning|clip_python_evidence|behavior_logs" || true
```

Expected: no newly selected/exposed prediction, reasoning, Python Evidence, or behavior GT fields.

- [ ] **Step 4: Write the report**

Report exact commits, tests, cursor cases, stale-response proof, files changed, and explicitly state:

- migration 0
- production DB write 0
- deploy not executed yet
- Evidence GT Work Package B not started

- [ ] **Step 5: Commit and push the feature branch**

```bash
git add docs/FEATURES.md .claude/donts-audit.md \
  docs/handoff-prompts/2026-07-22-labeling-queue-newest-order-report.md
git commit -m "docs: 라벨링 큐 최신순 검증 보고"
git push origin codex/labeling-queue-newest-exec
```

Confirm local HEAD equals origin and working tree is clean. Stop for Codex/owner review; do not start the Evidence GT plan or production deployment in the same run.

---

## Final Review Checklist

- [ ] Invalid cursor is a public 400, not a database 502.
- [ ] API order is `started_at DESC, id DESC`.
- [ ] Keyset predicate handles equal timestamps.
- [ ] Internal queue scan returns object positions; public API returns opaque strings.
- [ ] Client deduplicates and re-sorts every merge.
- [ ] Stale response cannot change items, cursor, error, busy, or loaded state.
- [ ] Existing blind GT, triage, tutorial, and owner/labeler gates are unchanged.
- [ ] Full tests/build pass and no production mutation occurred.

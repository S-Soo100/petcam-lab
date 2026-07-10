# Router Review Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 라벨링 웹에 라우터 리뷰 큐와 단건 검수 화면을 추가한다.

**Architecture:** Next.js 라벨링 웹에 `/labeling/router-review` 메뉴와 API route를 추가한다. Supabase에는 `router_review_items`와 `router_review_labels`를 만들고, seed script가 72개 batch를 DB에 넣는다.

**Tech Stack:** Next.js App Router, TypeScript, Supabase service role, Python seed script, pytest, `npm run lint`.

## Global Constraints

- 행동 GT는 `behavior_labels`에 저장하지 않는다.
- 라우터 검수 결과는 `router_review_labels`에만 저장한다.
- VLM/LLM 호출은 하지 않는다.
- 1차 batch id는 `router-eval-v1-20260710`이다.
- 기존 미커밋 변경은 건드리지 않는다.

---

### Task 1: DB Migration And Seed Script

**Files:**
- Create: `migrations/2026-07-10_router_review_tables.sql`
- Create: `scripts/seed_router_review_batch.py`
- Create: `tests/test_seed_router_review_batch.py`

**Interfaces:**
- Produces: `build_review_item_payload(row: dict[str, str], batch_id: str) -> dict[str, object]`
- Produces: `read_review_queue_csv(path: Path, batch_id: str) -> list[dict[str, object]]`

- [ ] Write failing pytest for CSV parsing and payload mapping.
- [ ] Implement seed helpers and CLI.
- [ ] Verify pytest passes.

### Task 2: Router Review API Routes

**Files:**
- Create: `web/src/app/api/router-review/batches/route.ts`
- Create: `web/src/app/api/router-review/items/route.ts`
- Create: `web/src/app/api/router-review/items/[clipId]/route.ts`
- Create: `web/src/app/api/router-review/items/[clipId]/label/route.ts`
- Modify: `web/src/lib/labelingApi.ts`

**Interfaces:**
- Produces TS types `RouterReviewItem`, `RouterReviewLabel`, `RouterReviewBatch`.
- Produces API functions `getRouterReviewBatches`, `getRouterReviewItems`, `getRouterReviewItem`, `saveRouterReviewLabel`.

- [ ] Add TypeScript API helpers.
- [ ] Add Next.js API routes using `verifyBearer` and `supabaseAdmin`.
- [ ] Verify `npm run lint`.

### Task 3: Router Review UI

**Files:**
- Modify: `web/src/app/labeling/layout.tsx`
- Create: `web/src/app/labeling/router-review/page.tsx`
- Create: `web/src/app/labeling/router-review/[clipId]/page.tsx`

**Interfaces:**
- Consumes API helpers from Task 2.
- Produces review list and single review workflow.

- [ ] Add `라우터 리뷰` nav tab.
- [ ] Build list page with filters, progress, cards.
- [ ] Build single page with video playback, router snapshot, manual inputs, save-next.
- [ ] Verify `npm run lint`.

### Task 4: Docs And Verification

**Files:**
- Modify: `specs/next-session.md`
- Optional create: `reports/router-eval-v1-20260710/WEB_REVIEW.md`

- [ ] Document SQL apply + seed commands.
- [ ] Run pytest and lint.
- [ ] Report remaining Supabase SQL apply status clearly.

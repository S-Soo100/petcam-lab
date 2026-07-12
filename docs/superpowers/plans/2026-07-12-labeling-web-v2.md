# Labeling Web v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `label.tera-ai.uk`에서 실제 썸네일을 보고, VLM을 보기 전 사람 GT와 interaction evidence를 확정한 뒤 같은 화면에서 VLM을 검수하고 다음 clip으로 이동하게 만든다.

**Architecture:** Vercel same-origin API가 Supabase Auth, `camera_clips`, R2 signer를 직접 사용한다. 기존 `behavior_labels`는 대표 action 호환 SOT로 유지하고, 새 `clip_labeling_sessions` JSONB row가 최초 blind GT·현재 GT·exact VLM snapshot·verdict·workflow state를 보존한다. 현재 terra-server 하이라이트 선정식은 건드리지 않고 wheel/object interaction GT를 먼저 축적한다.

**Tech Stack:** Next.js 14 App Router, React 18, TypeScript 5, Supabase/Postgres, Cloudflare R2 AWS SDK, Vitest, Vercel.

**실행 상태 (2026-07-12): 완료.** Supabase migration, Vercel production 배포,
`label.tera-ai.uk` owner-equivalent E2E까지 끝냈다. 운영 검증에서 실제 스키마에 없는
`camera_clips.ended_at`을 blind queue가 조회하는 문제를 발견해 `5479e4f`로 수정·재배포했다.
30개 썸네일, GT 전 prediction 비노출, interaction 필수값, exact snapshot 공개, VLM 오류
tag 저장, 다음 clip 이동을 확인했으며 임시 E2E 계정·세션·라벨은 전부 삭제했다.

## Global Constraints

- 최초 GT 확정 전에는 VLM action·confidence·reasoning을 API 응답과 DOM에서 모두 숨긴다.
- `playing` 의도를 직접 입력·예측하지 않는다. wheel/object의 `ride/push/rotate/chase/repeated_return` evidence를 저장한다.
- 기존 `behavior_labels`와 라벨링/Flutter 소비 계약을 깨지 않는다.
- service role과 R2 secret은 server-only route 밖으로 노출하지 않는다.
- 썸네일 복구 때문에 두 달치 Fly backend 변경을 한 번에 배포하지 않는다.
- 오늘 production 변경은 petcam-lab Vercel 웹과 필요한 Supabase migration까지다. terra-server 정책 변경은 제외한다.

---

### Task 1: 도메인 계약과 DB migration

**Files:**
- Create: `migrations/2026-07-12_clip_labeling_sessions.sql`
- Create: `web/src/lib/labelingV2.ts`
- Create: `web/src/lib/labelingV2.test.ts`
- Modify: `web/package.json`
- Modify: `web/package-lock.json`

**Interfaces:**
- Produces `GroundTruthInput`, `LabelingSession`, `VlmReviewInput`, `validateGroundTruth()`, `validateVlmReview()`.
- `clip_labeling_sessions` has one current row per `(clip_id, reviewed_by)` with immutable `initial_gt` and mutable `current_gt`.

- [x] **Step 1: Add Vitest and failing domain tests**

```ts
it('rejects enrichment evidence without object or interaction', () => {
  expect(() => validateGroundTruth({
    visibility: 'visible', primary_action: 'moving', observed_actions: ['wheel_interaction'],
    segments: [], target: 'none', human_confidence: 'certain', context_tags: [],
    activity_intensity: 'high', enrichment_object: 'none', interaction_types: [], note: null,
  })).toThrow('enrichment evidence');
});

it('accepts objective wheel interaction without playing label', () => {
  const gt = validGt({
    observed_actions: ['moving', 'wheel_interaction'], enrichment_object: 'wheel',
    interaction_types: ['ride', 'rotate'], activity_intensity: 'high',
  });
  expect(validateGroundTruth(gt)).toEqual(gt);
});
```

- [x] **Step 2: Run domain tests and confirm red**

Run: `cd web && npx vitest run src/lib/labelingV2.test.ts`

Expected: FAIL because `labelingV2.ts` does not exist.

- [x] **Step 3: Implement strict TypeScript unions and validation**

The contract must use these exact values:

```ts
export type Visibility = 'visible' | 'partial' | 'absent' | 'uncertain';
export type HumanConfidence = 'certain' | 'likely' | 'uncertain' | 'unjudgeable';
export type ActivityIntensity = 'low' | 'medium' | 'high';
export type EnrichmentObject = 'wheel' | 'toy' | 'other' | 'none' | 'uncertain';
export type InteractionType = 'ride' | 'push' | 'rotate' | 'chase' | 'repeated_return' | 'other';
export type VlmVerdict = 'correct' | 'partially_correct' | 'incorrect' | 'unjudgeable';
```

Validation rules:

- `absent` requires primary action `unseen`.
- `wheel_interaction` or `object_interaction` requires object other than `none` and one interaction type.
- no enrichment evidence may store a customer-facing `playing` action.
- every segment satisfies `0 <= start_sec < end_sec <= clip duration` in API validation.
- verdict requires a locked GT and an exact prediction snapshot.

- [x] **Step 4: Add migration with RLS and immutable-first-label trigger**

```sql
CREATE TABLE public.clip_labeling_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL REFERENCES public.camera_clips(id) ON DELETE CASCADE,
  reviewed_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  stage text NOT NULL DEFAULT 'draft' CHECK (stage IN ('draft','gt_locked','completed')),
  initial_gt jsonb,
  current_gt jsonb,
  prediction_snapshot jsonb,
  vlm_verdict text CHECK (vlm_verdict IS NULL OR vlm_verdict IN ('correct','partially_correct','incorrect','unjudgeable')),
  vlm_error_tags text[] NOT NULL DEFAULT '{}',
  vlm_review_note text,
  gt_locked_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (clip_id, reviewed_by)
);
```

RLS permits the reviewer to select/insert/update their row and the clip owner to select. Vercel writes with service role only after `loadClipWithPerms` validates the bearer token.

- [x] **Step 5: Run tests and TypeScript**

Run: `cd web && npx vitest run src/lib/labelingV2.test.ts && npx tsc --noEmit`

Expected: domain tests PASS and TypeScript exits 0.

---

### Task 2: Same-origin thumbnail recovery

**Files:**
- Create: `web/src/app/api/clips/[id]/thumbnail/url/route.ts`
- Modify: `web/src/lib/labelingV2.ts`
- Modify: `web/src/lib/labelingApi.ts`
- Modify: `web/src/app/labeling/page.tsx`
- Test: `web/src/lib/labelingV2.test.ts`

**Interfaces:**
- `thumbnailKeyForClip(clip)` returns `thumbnail_r2_key` or replaces the final `.mp4` in `r2_key` with `.jpg`.
- `getClipThumbnailUrl()` calls `/api/clips/{id}/thumbnail/url`, never the stale Fly route.

- [x] **Step 1: Add failing key derivation tests**

```ts
expect(thumbnailKeyForClip({thumbnail_r2_key: 'x/thumb.jpg', r2_key: 'x/a.mp4'})).toBe('x/thumb.jpg');
expect(thumbnailKeyForClip({thumbnail_r2_key: null, r2_key: 'x/a.mp4'})).toBe('x/a.jpg');
expect(() => thumbnailKeyForClip({thumbnail_r2_key: null, r2_key: null})).toThrow('thumbnail');
```

- [x] **Step 2: Run the focused test and confirm red**

Run: `cd web && npx vitest run src/lib/labelingV2.test.ts -t thumbnail`

Expected: FAIL because `thumbnailKeyForClip` is missing.

- [x] **Step 3: Implement route using existing permissions and R2 signer**

```ts
const result = await loadClipWithPerms(req, params.id);
if (!result.ok) return result.response;
const key = thumbnailKeyForClip(result.access.clip);
return NextResponse.json({url: await presignGet(key), ttl_sec: SIGNED_URL_TTL_SEC, type: 'r2'});
```

The route returns 410 for clips with neither key. Queue cards show `썸네일 불러오기 실패` and a retry button instead of silently rendering `영상`.

- [x] **Step 4: Point the client to same-origin route and verify**

Run: `cd web && npx vitest run src/lib/labelingV2.test.ts && npx tsc --noEmit && npm run build`

Expected: tests PASS, TypeScript 0, Next build successful.

---

### Task 3: Staged labeling API

**Files:**
- Create: `web/src/app/api/labeling-v2/[clipId]/route.ts`
- Create: `web/src/app/api/labeling-v2/[clipId]/gt/route.ts`
- Create: `web/src/app/api/labeling-v2/[clipId]/vlm-review/route.ts`
- Modify: `web/src/lib/labelingApi.ts`
- Test: `web/src/lib/labelingV2.test.ts`

**Interfaces:**
- GET returns `{clip, system_metadata, session, prediction}`; `prediction` is null until `initial_gt` exists.
- POST `/gt` accepts `GroundTruthInput`, preserves `initial_gt`, updates `current_gt`, snapshots latest VLM row, and upserts compatible `behavior_labels`.
- POST `/vlm-review` requires `gt_locked`, writes verdict/error tags/note, and marks completed.

- [x] **Step 1: Add failing redaction and transition tests**

```ts
expect(revealPrediction(null, prediction)).toBeNull();
expect(revealPrediction({initial_gt: gt}, prediction)).toEqual(prediction);
expect(nextStage('draft', 'lock_gt')).toBe('gt_locked');
expect(nextStage('gt_locked', 'complete_vlm_review')).toBe('completed');
```

- [x] **Step 2: Run focused tests and confirm red**

Run: `cd web && npx vitest run src/lib/labelingV2.test.ts -t 'redaction|transition'`

Expected: FAIL because helpers are missing.

- [x] **Step 3: Implement API validation and atomic order**

GT route order:

1. bearer/clip permission
2. validate JSON and duration-bound segments
3. load existing session
4. load latest exact `behavior_logs(source='vlm')`
5. upsert `behavior_labels`
6. upsert session with `initial_gt = existing.initial_gt ?? input`, `current_gt = input`, prediction snapshot, `stage='gt_locked'`

VLM review route rejects missing snapshot with 409 and never accepts arbitrary model text from the client.

- [x] **Step 4: Run tests, typecheck, and build**

Run: `cd web && npx vitest run && npx tsc --noEmit && npm run build`

Expected: all web tests PASS and build successful.

---

### Task 4: Owner-first two-stage UI

**Files:**
- Create: `web/src/app/labeling/[clipId]/_gt-form.tsx`
- Create: `web/src/app/labeling/[clipId]/_vlm-review.tsx`
- Create: `web/src/app/labeling/[clipId]/_system-metadata.tsx`
- Modify: `web/src/app/labeling/[clipId]/page.tsx`
- Modify: `web/src/app/labeling/page.tsx`
- Modify: `web/src/app/globals.css`

**Interfaces:**
- `_gt-form.tsx` emits a validated `GroundTruthInput` and never receives prediction props.
- `_vlm-review.tsx` receives the server snapshot only after GT lock.
- Page restores session stage and navigates to the next unreviewed clip after completion.

- [x] **Step 1: Implement the frame-by-frame experience from the design**

The page layout is video-first, with a sticky right workflow panel on desktop and stacked sections on mobile. Step header shows `1 사람 GT` then `2 VLM 검수`. Before lock, no VLM text is rendered. After lock, GT becomes a comparison summary and VLM review opens.

- [x] **Step 2: Make moving vs interaction evidence explicit**

The form copy must show:

```text
일반 이동: 지나가기·등반·자세 변경
Wheel/Object 상호작용: 타기·밀기·회전시키기·반복 접근
빠르다는 이유만으로 놀이로 분류하지 않아.
```

Selecting wheel/object interaction reveals required object and interaction controls. Customer-facing `playing` is not an input option.

- [x] **Step 3: Add efficient controls**

- keyboard shortcuts for primary actions and save
- video speed and frame-step controls
- progress/status badge
- retryable thumbnail error
- `GT 확정`, then `완료 후 다음`
- preserve existing owner delete and old-label review in a collapsed compatibility panel

- [x] **Step 4: Verify responsive build**

Run: `cd web && npx vitest run && npx tsc --noEmit && npm run build`

Expected: all checks exit 0.

---

### Task 5: Migration, deployment, and production verification

**Files:**
- Modify: `docs/DATABASE.md`
- Modify: `docs/FEATURES.md`
- Modify: `specs/next-session.md`

**Interfaces:**
- Supabase contains `clip_labeling_sessions` with RLS.
- Vercel production alias `label.tera-ai.uk` serves the verified build.

- [x] **Step 1: Apply migration to linked Supabase project**

Run: `supabase db push --linked`

Expected: migration applies once; querying `clip_labeling_sessions` succeeds with zero rows before first use.

- [x] **Step 2: Run full repository verification**

Run: `uv run pytest && cd web && npx vitest run && npx tsc --noEmit && npm run build`

Expected: Python 334 tests PASS, web tests PASS, typecheck/build exit 0.

- [x] **Step 3: Commit and push the feature branch**

```bash
git add migrations web docs specs
git commit -m "feat: 라벨링 웹 v2 GT·VLM 2단계 검수"
git push origin HEAD
```

- [x] **Step 4: Deploy Vercel production**

Run from `web/`: `npx vercel --prod --yes`

Expected: deployment Ready and `label.tera-ai.uk` alias points to it.

- [x] **Step 5: Verify production with an isolated owner-equivalent session**

Check in the browser:

1. queue shows real thumbnails for the first 30 cards
2. detail video plays
3. VLM text is absent before GT lock
4. wheel interaction requires object/type evidence
5. GT lock reveals the exact VLM snapshot
6. verdict completion moves to the next clip
7. reload restores completed state

- [x] **Step 6: Record deployment evidence and SOT completion state**

Update next-session with deployment URL, commit, test counts, migration status, and any known limitation. Do not mark Gate audit or production highlight policy complete.

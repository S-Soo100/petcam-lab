# Labeling Video Header Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 라벨링 영상 상세 상단에 KST 촬영 일시·영상 길이와 인증된 원본 MP4 다운로드 버튼을 추가한다.

**Architecture:** 표시 문자열과 파일명은 순수 helper로 만들고 Vitest로 고정한다. 다운로드는 기존 playback URL을 재사용하지 않고 `loadClipWithPerms`를 통과한 same-origin route가 attachment disposition이 포함된 R2 signed URL을 발급한다. 브라우저는 Vercel을 거치지 않고 R2에서 원본을 직접 받는다.

**Tech Stack:** Next.js 14 App Router, React 18, TypeScript, AWS SDK v3, Cloudflare R2, Vitest, Vercel.

## Global Constraints

- 촬영 시각 SOT는 `camera_clips.started_at`, 표시 시간대는 `Asia/Seoul`이다.
- 파일명은 `petcam_YYYY-MM-DD_HHmmss_<clip-id 앞 8자리>.mp4`다.
- owner와 labeler는 기존 clip 권한 범위에서 다운로드할 수 있고 외부인은 404/401이다.
- MP4 byte stream을 Vercel로 proxy하지 않는다.
- 기존 playback signed URL과 영상 재생 동작은 변경하지 않는다.

---

### Task 1: 촬영 시각·다운로드 파일명 계약

**Files:**
- Modify: `web/src/lib/labelingV2.test.ts`
- Modify: `web/src/lib/labelingV2.ts`

**Interfaces:**
- Produces: `formatClipCapturedAt(startedAt: string, durationSec: number | null): string`
- Produces: `clipDownloadFilename(startedAt: string, clipId: string): string`

- [ ] **Step 1: Write failing helper tests**

```ts
expect(formatClipCapturedAt('2026-07-07T20:11:29Z', 31.9184))
  .toBe('촬영 · 2026년 7월 8일 (수) 오전 5:11:29 · 32초');
expect(clipDownloadFilename('2026-07-07T20:11:29Z', '29a74166-1024-4bdd-a497-b1133a86549b'))
  .toBe('petcam_2026-07-08_051129_29a74166.mp4');
```

- [ ] **Step 2: Verify RED**

Run: `cd web && npx vitest run src/lib/labelingV2.test.ts -t 'clip header'`  
Expected: FAIL because both helpers are missing.

- [ ] **Step 3: Implement KST helpers with `Intl.DateTimeFormat`**

Use fixed `timeZone: 'Asia/Seoul'`, Korean weekday/dayPeriod, two-digit filename parts, rounded duration, and the first eight clip-id characters.

- [ ] **Step 4: Verify GREEN**

Run: `cd web && npx vitest run src/lib/labelingV2.test.ts -t 'clip header'`  
Expected: 2 tests PASS.

---

### Task 2: Attachment signed URL API

**Files:**
- Modify: `web/src/lib/r2.ts`
- Create: `web/src/app/api/clips/[id]/download/url/route.ts`
- Modify: `web/src/lib/labelingApi.ts`

**Interfaces:**
- Extends: `presignGet(r2Key, ttlSec, options?: { downloadFilename?: string })`
- Produces: `getClipDownloadUrl(clipId: string): Promise<PlaybackUrl>`

- [ ] **Step 1: Extend `presignGet` minimally**

When `downloadFilename` exists, create `GetObjectCommand` with:

```ts
ResponseContentDisposition: `attachment; filename="${downloadFilename}"`,
ResponseContentType: 'video/mp4',
```

Playback callers omit the option and retain current behavior.

- [ ] **Step 2: Add authenticated download route**

Route flow:

```ts
const result = await loadClipWithPerms(req, params.id);
if (!result.ok) return result.response;
if (!result.access.clip.r2_key) return NextResponse.json({detail: '...'}, {status: 410});
const filename = clipDownloadFilename(String(result.access.clip.started_at), params.id);
const url = await presignGet(result.access.clip.r2_key, SIGNED_URL_TTL_SEC, {downloadFilename: filename});
return NextResponse.json({url, ttl_sec: SIGNED_URL_TTL_SEC, type: 'r2', filename});
```

- [ ] **Step 3: Add client response and function**

Define `DownloadUrl extends PlaybackUrl { filename: string }` and request
`/api/clips/${clipId}/download/url`.

- [ ] **Step 4: Typecheck**

Run: `cd web && npx tsc --noEmit`  
Expected: exit 0.

---

### Task 3: Header UI, verification, and deployment

**Files:**
- Modify: `web/src/app/labeling/[clipId]/page.tsx`
- Modify: `docs/FEATURES.md`
- Modify: `specs/next-session.md`

**Interfaces:**
- Consumes: `formatClipCapturedAt`, `getClipDownloadUrl`

- [ ] **Step 1: Add header information and state**

Render the formatted capture line between title and description. Add `downloading` state and a `영상 다운로드` secondary button next to the stage badge.

- [ ] **Step 2: Implement download action**

```ts
const result = await getClipDownloadUrl(clipId);
const anchor = document.createElement('a');
anchor.href = result.url;
anchor.download = result.filename;
document.body.appendChild(anchor);
anchor.click();
anchor.remove();
```

Disable the button during URL issue. On failure set page error and show an error toast.

- [ ] **Step 3: Run full verification**

Run: `uv run pytest && cd web && npm test && npx tsc --noEmit && cd .. && git diff --check`  
Expected: Python 334 PASS, Web 18 PASS, TypeScript and diff check exit 0.

- [ ] **Step 4: Update SOT and commit**

Record the production behavior and verification evidence, then commit with:

```bash
git commit -m "feat: 라벨링 영상 촬영정보·원본 다운로드"
```

- [ ] **Step 5: Deploy and browser E2E**

Deploy with `npx vercel --prod --yes`. Verify on `label.tera-ai.uk`:

1. header displays KST capture time and rounded duration;
2. download button is visible on desktop and mobile wrapping remains readable;
3. issued URL response includes filename and R2 response uses attachment disposition;
4. playback still works;
5. unauthorized behavior remains unchanged.

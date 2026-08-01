# Labeling Review Video Player Implementation Plan

**Status:** Completed and production-verified on 2026-08-01.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 모든 라벨링 실제 영상을 음소거 자동재생하고, 영상 아래 조작바와 최대 1200px 데스크톱 폭을 공통 적용한다.

**Architecture:** `ReviewVideo`가 유일한 raw `<video>` 소유자가 되고 재생 상태·seek·mute·fullscreen을 관리한다. 기존 `VideoPlayer`와 직접 영상 렌더링 화면은 이 컴포넌트를 사용하며, 역할 셸과 영상 상세 화면의 폭 제한을 함께 넓힌다.

**Tech Stack:** Next.js 14, React 18, TypeScript, Tailwind CSS, Vitest 4

## Global Constraints

- 자동재생은 `autoPlay + muted + playsInline + preload="auto"`로 시작한다.
- native `controls`를 제거하고 조작바를 영상 바깥 아래에 둔다.
- DB, R2, API, GT, 사람 제출 payload는 변경하지 않는다.
- 영상 자동 제출·문제 자동 이동은 추가하지 않는다.
- 데스크톱 영상 콘텐츠 최대 폭은 1200px이며 모바일 수평 스크롤을 만들지 않는다.

---

### Task 1: 공통 ReviewVideo 플레이어

**Files:**
- Create: `web/src/app/labeling/_review-video.tsx`
- Create: `web/src/app/labeling/_review-video.test.tsx`

**Interfaces:**
- Produces: `ReviewVideo({ src, videoRef?, className?, onLoadedMetadata?, onError? })`
- Produces: `formatReviewVideoTime(seconds: number): string`
- Consumes: 표준 `HTMLVideoElement`의 play/pause/currentTime/muted/duration/fullscreen API

- [x] **Step 1: 시간 표시와 기본 markup RED 테스트 작성**

```tsx
expect(formatReviewVideoTime(65.9)).toBe('1:05');
const html = renderToStaticMarkup(<ReviewVideo src="https://media.example/test.mp4" />);
expect(html).toContain('autoplay=""');
expect(html).toContain('muted=""');
expect(html).toContain('playsinline=""');
expect(html).not.toContain(' controls=""');
expect(html).toContain('aria-label="영상 재생 위치"');
```

- [x] **Step 2: RED 확인**

Run: `cd web && npm test -- src/app/labeling/_review-video.test.tsx`
Expected: FAIL because `_review-video` does not exist.

- [x] **Step 3: 최소 공통 플레이어 구현**

```tsx
'use client';

export function formatReviewVideoTime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

export default function ReviewVideo(props: ReviewVideoProps) {
  // videoRef와 wrapperRef를 사용해 autoplay, play/pause, seek, mute, fullscreen을 관리한다.
  // `<video>`와 별도 `<div>` 조작바를 형제로 렌더링한다.
}
```

구현 시 영상에는 `autoPlay muted playsInline preload="auto"`를 주고, 조작바에는 `재생/일시정지`, `현재/전체 시간`, range, `소리 켜기/음소거`, `전체화면`을 둔다. `play()` 거부와 fullscreen 실패는 catch 후 사람 판정 상태를 바꾸지 않는다.

- [x] **Step 4: GREEN 확인**

Run: `cd web && npm test -- src/app/labeling/_review-video.test.tsx && npx tsc --noEmit`
Expected: component tests PASS and TypeScript exit 0.

- [x] **Step 5: Commit**

```bash
git add web/src/app/labeling/_review-video.tsx web/src/app/labeling/_review-video.test.tsx
git commit -m "feat: 라벨링 공통 영상 플레이어 추가"
```

### Task 2: 모든 라벨링 영상 경로 통합

**Files:**
- Modify: `web/src/app/labeling/_labeling-forms.tsx`
- Modify: `web/src/app/labeling/boundary/_boundary-pair-view.tsx`
- Modify: `web/src/app/labeling/boundary/_eligibility-pair-view.tsx`
- Modify: `web/src/app/labeling/boundary/conflicts/page.tsx`
- Modify: `web/src/app/labeling/quarantine/[clipId]/page.tsx`
- Modify: `web/src/app/labeling/router-review/[clipId]/page.tsx`
- Create: `web/src/app/labeling/_review-video-usage.test.ts`

**Interfaces:**
- Consumes: Task 1 `ReviewVideo`
- Preserves: `VideoPlayer`의 `onLoadedMetadata`, `onError`, frame step, playback rate

- [x] **Step 1: raw video 단일소유 RED 감사 테스트 작성**

`web/src/app/labeling`을 재귀 탐색해 `_review-video.tsx` 이외 파일에 `<video`가 있으면 파일 목록과 함께 실패하게 한다.

- [x] **Step 2: RED 확인**

Run: `cd web && npm test -- src/app/labeling/_review-video-usage.test.ts`
Expected: FAIL listing the six existing raw-video source files.

- [x] **Step 3: 모든 raw video를 ReviewVideo로 교체**

```tsx
import ReviewVideo from '../_review-video';

<ReviewVideo src={urls[side]} />
```

`VideoPlayer`는 `videoRef`를 넘겨 기존 frame/speed 조작이 같은 element에 적용되게 하고, 기존 URL 준비 중·오류 fallback 문구는 보존한다.

- [x] **Step 4: GREEN과 관련 화면 회귀 확인**

Run: `cd web && npm test -- src/app/labeling/_review-video-usage.test.ts src/app/labeling/_blind-review-ui.test.tsx src/app/labeling/boundary/_eligibility-pair-view.test.tsx src/app/labeling/boundary/_boundary-pair-view.test.tsx`
Expected: all selected tests PASS.

- [x] **Step 5: Commit**

```bash
git add web/src/app/labeling
git commit -m "refactor: 라벨링 영상을 공통 플레이어로 통합"
```

### Task 3: 데스크톱 1200px 폭 계약

**Files:**
- Modify: `web/src/app/labeling/_role-shell.tsx`
- Modify: `web/src/app/labeling/motion/[clipId]/page.tsx`
- Modify: `web/src/app/labeling/_blind-review-detail.tsx`
- Modify: `web/src/app/labeling/blind/conflicts/[clipId]/page.tsx`
- Modify: `web/src/app/labeling/quarantine/[clipId]/page.tsx`
- Create: `web/src/app/labeling/_review-video-layout.test.ts`

**Interfaces:**
- Role shell desktop grid: `220px + minmax(0,1200px)`
- Outer desktop max width: `max-w-[1480px]`
- Video detail main width: `max-w-6xl`

- [x] **Step 1: 폭 계약 RED 정적 테스트 작성**

```ts
expect(roleShell).toContain('max-w-[1480px]');
expect(roleShell).toContain('lg:grid-cols-[220px_minmax(0,1200px)]');
expect(videoDetailSources.every((source) => source.includes('max-w-6xl'))).toBe(true);
```

- [x] **Step 2: RED 확인**

Run: `cd web && npm test -- src/app/labeling/_review-video-layout.test.ts`
Expected: FAIL because shell is still max-w-7xl and content 960px.

- [x] **Step 3: 폭 클래스 최소 변경**

역할 셸과 영상 상세 main만 지정된 폭으로 바꾸고, 모바일 padding·1열과 사건 이어짐 desktop 2열 계약은 유지한다.

- [x] **Step 4: GREEN 확인**

Run: `cd web && npm test -- src/app/labeling/_review-video-layout.test.ts src/app/labeling/_role-shell.test.tsx`
Expected: all selected tests PASS.

- [x] **Step 5: Commit**

```bash
git add web/src/app/labeling
git commit -m "style: 라벨링 영상 영역을 넓게 조정"
```

### Task 4: 전체 검증·배포·운영 smoke

**Files:**
- Modify: `specs/next-session.md`
- Modify: `.claude/donts-audit.md`

**Interfaces:**
- Production URL: `https://label.tera-ai.uk/labeling/boundary`
- Git integration: current feature branch → fast-forward `main`

- [x] **Step 1: 전체 로컬 검증**

Run: `cd web && npm test && npx tsc --noEmit`
Expected: 100 test files plus new tests PASS; TypeScript exit 0.

Run: `git diff --check && git status --short`
Expected: no whitespace errors; only intended tracked files.

- [x] **Step 2: 정본 문서 갱신과 commit**

`specs/next-session.md` 최상단과 `.claude/donts-audit.md`에 공통 플레이어, 자동재생, 외부 조작바, 1200px, DB/R2/GT write 0, 검증 수치를 기록한다.

- [x] **Step 3: main fast-forward와 production 배포**

```bash
git fetch origin main
git merge-base --is-ancestor origin/main HEAD
git push origin HEAD:main
vercel --prod --yes
```

Expected: non-force fast-forward push, deployment `READY`, alias `https://label.tera-ai.uk`.

- [x] **Step 4: 로그인 운영 브라우저 smoke**

사람 답을 제출하지 않고 사건 이어짐 페이지에서 다음을 확인한다.

- 두 video가 로드 뒤 자동으로 진행 중이다.
- 두 video 모두 muted다.
- native controls가 없고 외부 조작바가 각각 존재한다.
- 조작바가 영상 프레임 아래에 있어 촬영 타임스탬프를 가리지 않는다.
- 데스크톱 콘텐츠 폭이 이전 960px보다 넓다.

- [x] **Step 5: final verification**

Run: `git status --short --branch && git rev-parse HEAD && git rev-parse origin/main`
Expected: clean branch, HEAD equals origin/main.

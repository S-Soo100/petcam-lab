# GME Owner Activity Overview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Owner가 영상을 끝까지 재생하지 않아도 GME의 움직임·정지·미확정 시간을 구분하고 현재 박스 상태를 이해할 수 있게 한다.

**Architecture:** 기존 append-only GME artifact의 검증된 `state_intervals`를 overlay 응답에 익명화해 추가한다. Owner 상세는 이 구간으로 재생 전 요약과 타임라인을 렌더링하고, 현재 구간에 따라 박스 색을 바꾼다. 현재 active detector identity와 다른 과거 run은 사용하지 않는다.

**Tech Stack:** Next.js 14, React 18, TypeScript, Vitest, Supabase, R2 gzip artifact

**Spec:** `docs/superpowers/specs/2026-09-03-gme-owner-activity-overview-design.md`

## Global Constraints

- Owner 전용 motion detail/overlay 경로만 변경한다.
- 원본 track id, R2 key, source 식별자, 비밀값을 브라우저에 노출하지 않는다.
- DB migration, 기존 run 수정·삭제·재실행, 모델 교체를 하지 않는다.
- 일반 라벨러 blind 화면의 AI 사전 노출 계약을 변경하지 않는다.
- 사용자 추가 승인 전에는 commit·push·deploy를 하지 않는다.

---

### Task 1: 상태 구간 공개 계약

**Files:**
- Modify: `web/src/lib/gmeOverlay.ts`
- Test: `web/src/lib/gmeOverlay.test.ts`

**Interfaces:**
- Consumes: GME artifact v1의 `intervals`, `track_points`, `duration_sec`
- Produces: `GmeStateInterval`, `ParsedGmeOverlay.intervals`, `stateAtTime()`

- [x] 겹치거나 범위를 벗어난 구간, 미지 상태, 유출 가능한 track id를 막는 실패 테스트를 작성한다.
- [x] 테스트가 새 `intervals` 필드 부재로 실패하는지 확인한다.
- [x] interval을 엄격 검증하고 track id를 기존 익명 index로 변환한다.
- [x] 문제 영상과 같은 literal fixture가 움직임 0초로 요약되는지 통과시킨다.

### Task 2: Active identity overlay source

**Files:**
- Modify: `web/src/lib/gmeOverlayServer.ts`
- Modify: `web/src/app/api/labeling-v3/[clipId]/gme-overlay/route.ts`
- Test: `web/src/lib/gmeOverlayServer.test.ts`
- Test: `web/src/app/api/labeling-v3/[clipId]/gme-overlay/route.test.ts`

**Interfaces:**
- Consumes: `readGmeActiveDetectorIdentity(): string`
- Produces: `loadCurrentGmeOverlaySource(clipId, detectorIdentity)`

- [x] 다른 identity의 더 최신 성공 run이 선택되지 않는 실패 테스트를 작성한다.
- [x] 테스트가 identity filter 부재로 실패하는지 확인한다.
- [x] source query에 exact detector identity를 추가하고 route에서 검증된 env 값을 전달한다.
- [x] unavailable 응답에도 빈 `intervals`를 포함해 응답 형태를 고정한다.

### Task 3: 재생 전 활동 요약과 상태 타임라인

**Files:**
- Create: `web/src/app/labeling/_gme-activity-overview.tsx`
- Create: `web/src/app/labeling/_gme-activity-overview.test.tsx`
- Modify: `web/src/app/labeling/motion/[clipId]/page.tsx`

**Interfaces:**
- Consumes: `GmeOverlayResponse.intervals`, `duration_sec`, 현재 재생 초
- Produces: `GmeActivityOverview`

- [x] 60.8초 fixture가 재생 전 `움직임 0초`, `보인 시간 60.5초`, `정지 60.5초`, `미확정 0.3초`를 렌더링하는 실패 테스트를 작성한다.
- [x] 테스트가 컴포넌트 부재로 실패하는지 확인한다.
- [x] 구간 합계를 계산하는 순수 함수와 요약·타임라인 컴포넌트를 최소 구현한다.
- [x] Owner 상세에서 overlay가 준비되는 즉시 영상 위에 렌더링한다.

### Task 4: 상태별 박스 색과 문구

**Files:**
- Modify: `web/src/app/labeling/_gme-overlay.tsx`
- Modify: `web/src/app/labeling/_gme-overlay.test.tsx`
- Modify: `web/src/lib/gmeObservedMovingTime.ts`
- Test: `web/src/app/labeling/motion/_gme-observed-moving-time-card.test.tsx`

**Interfaces:**
- Consumes: `GmeStateInterval[]`, 현재 재생 초와 track index
- Produces: 정지 회색, 움직임 초록, 미확정 노랑의 bbox와 명확한 시간 문구

- [x] 정지 구간의 observed bbox가 초록으로 렌더링되는 기존 동작을 잡는 실패 테스트를 작성한다.
- [x] 테스트가 현재 provenance 기반 색상 때문에 실패하는지 확인한다.
- [x] provenance는 선 모양, motion state는 선 색을 담당하도록 분리한다.
- [x] `관측 N초`를 `게코가 보인 시간 N초`로 변경하고 회귀 테스트를 통과시킨다.

### Task 5: 회귀와 실제 영상 검증

**Files:**
- Modify: `docs/superpowers/specs/2026-09-03-gme-owner-activity-overview-design.md`

**Interfaces:**
- Consumes: Tasks 1-4 결과
- Produces: 검증 상태와 운영 반영 전 보고

- [x] 관련 Vitest를 실행한다.
- [x] 웹 전체 test, typecheck, diff check를 실행한다. build는 세션 resource hook이 차단해 운영 반영 전 별도 실행한다.
- [x] production 문제 영상의 기존 GME 원장과 로컬 렌더 결과가 일치하는지 읽기 전용으로 확인한다.
- [x] commit·push·deploy 없이 변경 파일과 검증 결과를 사용자에게 보고한다.

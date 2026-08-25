# 라벨링 YOLO/GME 오버레이·미탐 제보 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 라벨링 영상에 frozen GME v2.5 bbox trajectory를 표시하고 라벨러의 YOLO 미탐 시점을 append-only로 수집한다.

**Architecture:** 기존 blind slot 인가 뒤 최신 성공 GME run과 SHA-pinned R2 artifact를 서버에서 strict 검증해 익명 overlay만 반환한다. 미탐 버튼은 현재 overlay revision을 보내고 서버·DB가 current run과 slot을 다시 검증한 뒤 별도 이벤트 원장에 저장한다.

**Tech Stack:** PostgreSQL/Supabase SQL RPC, Next.js 14 Route Handlers, React/TypeScript/Vitest, AWS S3-compatible R2, Node zlib, pytest

**Spec:** `docs/superpowers/specs/2026-08-25-labeling-yolo-overlay-miss-report-design.md`

## Global Constraints

- 사람 GT·consensus·GME run·원본 영상은 수정하지 않는다.
- production DB/R2/service/model/Flutter write·deploy는 별도 승인 전 0이다.
- 기존 GME artifact는 read-only이며 R2 key·run UUID·detector identity를 브라우저에 노출하지 않는다.
- 모든 구현은 테스트 RED 확인 뒤 최소 코드로 GREEN을 만든다.
- 기존 dirty Future Holdout 변경은 보존하고 이번 파일만 다룬다.

---

### Task 1: GME audit 종료 완전성 guard

**Files:**
- Create: `migrations/2026-08-25_gme_negative_audit_close_completion_guard.sql`
- Modify: `scripts/run_gme_negative_audit_probe.py`
- Modify: `tests/sql/gme_negative_audit_probe.sql`
- Create: `tests/test_gme_negative_audit_close_guard_migration.py`
- Modify: `tests/test_run_gme_negative_audit_probe.py`

**Interfaces:**
- Consumes: immutable audit items/submissions and batch expected count.
- Produces: incomplete close → `PT409 batch_incomplete`.

- [x] **Step 1: missing migration RED를 확인한다.**
- [x] **Step 2: forward migration으로 close trigger를 교체한다.**
- [x] **Step 3: runtime probe에 incomplete reject와 complete success를 추가한다.**
- [x] **Step 4: disposable PostgreSQL과 local canary에서 검증한다.**

### Task 2: 미탐 append-only DB 원장

**Files:**
- Create: `migrations/2026-08-25_motion_clip_gme_miss_events.sql`
- Create: `tests/test_motion_clip_gme_miss_events_migration.py`
- Create: `tests/sql/motion_clip_gme_miss_events_probe.sql`

**Interfaces:**
- Produces: `fn_append_motion_clip_gme_miss(p_event_id,p_clip_id,p_reviewer_id,p_cohort_kind,p_cohort_id,p_gme_run_id,p_timestamp_sec)`.

- [x] **Step 1: table/RPC/append-only/current-run/slot 검증 RED 테스트를 작성한다.**
- [x] **Step 2: 정적 테스트 실패를 확인한다.**
- [x] **Step 3: forward migration을 최소 구현한다.**
- [x] **Step 4: SQL probe로 live/canary 인가·중복 멱등·stale run·mutation 차단을 검증한다.**
- [x] **Step 5: 관련 migration 테스트를 GREEN으로 만든다.**

### Task 3: GME artifact strict overlay API

**Files:**
- Create: `web/src/lib/gmeOverlay.ts`
- Create: `web/src/lib/gmeOverlay.test.ts`
- Create: `web/src/lib/gmeOverlayServer.ts`
- Create: `web/src/lib/gmeOverlayServer.test.ts`
- Create: `web/src/app/api/labeling-v3/blind/[clipId]/gme-overlay/route.ts`
- Create: `web/src/app/api/labeling-v3/blind/[clipId]/gme-overlay/route.test.ts`
- Create: `web/src/app/api/labeling-v3/blind/[clipId]/gme-miss/route.ts`
- Create: `web/src/app/api/labeling-v3/blind/[clipId]/gme-miss/route.test.ts`
- Modify: `web/src/lib/motionBlindReviewApi.ts`

**Interfaces:**
- Produces: `GmeOverlayResponse`, `getBlindGmeOverlay`, `reportBlindGmeMiss`.

- [x] **Step 1: artifact schema/SHA/size/geometry parser RED 테스트를 작성한다.**
- [x] **Step 2: parser RED를 확인하고 strict parser를 구현한다.**
- [x] **Step 3: assignment/current-run/R2 bounded read route RED 테스트를 작성한다.**
- [x] **Step 4: overlay GET과 miss POST를 구현해 route 테스트를 GREEN으로 만든다.**

### Task 4: 영상 오버레이와 미탐 버튼

**Files:**
- Modify: `web/src/app/labeling/_review-video.tsx`
- Modify: `web/src/app/labeling/_review-video.test.tsx`
- Modify: `web/src/app/labeling/_labeling-forms.tsx`
- Modify: `web/src/app/labeling/_blind-review-detail.tsx`
- Create: `web/src/app/labeling/_gme-overlay.tsx`
- Create: `web/src/app/labeling/_gme-overlay.test.tsx`

**Interfaces:**
- Consumes: Task 3 overlay/miss API.
- Produces: current-time normalized boxes, warning, miss report feedback.

- [x] **Step 1: nearest track selection과 SVG bbox RED 테스트를 작성한다.**
- [x] **Step 2: component RED를 확인하고 overlay component를 구현한다.**
- [x] **Step 3: VideoPlayer currentTime/overlay passthrough와 blind detail 버튼 RED를 작성한다.**
- [x] **Step 4: UI를 최소 구현하고 component 테스트를 GREEN으로 만든다.**

### Task 5: 통합 검증·local canary

**Files:**
- Modify: `docs/superpowers/specs/2026-08-25-labeling-yolo-overlay-miss-report-design.md`
- Modify: `docs/superpowers/plans/2026-08-25-labeling-yolo-overlay-miss-report.md`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: implementation verification evidence without production deployment.

- [x] **Step 1: focused Python/SQL/web tests와 TypeScript compile을 실행한다.**
- [x] **Step 2: disposable PostgreSQL runtime probe를 실행하고 residue 0을 확인한다.**
- [x] **Step 3: local route compile·component render·runtime DB 결합 canary로 overlay/miss/GT 분리를 확인한다.**
- [x] **Step 4: 금지된 production/R2/model/Flutter write 0과 git diff를 최종 검수한다.**

### Task 6: iTerm Claude 교차검수·자동 승인

**Files:**
- Modify: `migrations/2026-08-25_motion_clip_gme_miss_events.sql`
- Modify: `tests/test_motion_clip_gme_miss_events_migration.py`
- Modify: `web/src/app/labeling/_review-video.tsx`
- Modify: `web/src/app/labeling/_review-video.test.tsx`

- [x] **Step 1: Claude 읽기 전용 검수에서 확장 DDL 의존과 비-16:9 bbox 오정렬을 확인한다.**
- [x] **Step 2: 두 문제를 재현하는 RED 테스트를 실행한다.**
- [x] **Step 3: core sha256과 실제 object-contain content rect 매핑으로 최소 수정한다.**
- [x] **Step 4: focused 테스트 GREEN과 Claude 2차 `CLAUDE_REVIEW_APPROVE`를 확인한다.**

### Task 7: main 통합·운영 적용·canary

**Interfaces:**
- Consumes: Owner 운영 적용 승인, Tasks 1-6, 기존 공개 YOLO 데모 브랜치.
- Produces: migration 적용, 통합 `main`, production web, 첫 배정 영상 canary 경계.

- [x] **Step 1: 별도 통합 worktree에서 `main`과 GME 브랜치를 병합하고 양쪽 화면을 보존한다.**
- [x] **Step 2: web/Python 전체 회귀, TypeScript, 반응형 감사와 Vercel Preview build를 통과한다.**
- [x] **Step 3: 운영 DB forward migration과 권한·RLS·append-only 상태를 독립 재조회한다.**
- [x] **Step 4: `main` 반영과 production 배포 뒤 Owner 메뉴·GME queue·무인증 401을 확인한다.**
- [ ] **Step 5: 첫 실제 배정 clip에서 미탐 버튼 1회와 miss row 증가·사람 GT 불변을 확인한다.**

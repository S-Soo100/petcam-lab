# RAP C500G Owner Admin Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Owner가 RAP C500G test/production bundle의 업로드 상태와 관찰일별 누락을 보고, 안전한 presigned URL로 영상과 썸네일을 확인하는 내부 웹을 만든다.

**Architecture:** Next.js server-only repository가 별도 `rap_c500g_recordings` table의 allowlist 컬럼만 읽는다. 모든 API route는 `requireOwner`로 보호하고, detail route만 R2 key를 내부에서 소비해 짧은 presigned GET을 만든다. React 화면은 night/camera/status 필터와 72-slot coverage를 표시하며 write/delete 기능은 제공하지 않는다.

**Tech Stack:** Next.js 14 App Router, TypeScript, React 18, Supabase service role, AWS SDK R2 presigner, Vitest

**Spec:** `docs/superpowers/specs/2026-08-26-rap-c500g-r2-recording-design.md`

## Global Constraints

- page는 `/research/rap/recordings`, API는 `/api/research/rap/recordings/**`다.
- API는 `requireOwner` 성공 전 DB/R2를 호출하지 않는다.
- query input은 mode/camera/night/status/cursor/limit allowlist와 strict bounds를 적용한다.
- 공개 JSON에 R2 key, SHA-256, absolute/relative local path, credential, 내부 error message를 넣지 않는다.
- presigned GET TTL은 최대 3600초다.
- production coverage는 카메라당 24, night당 72 expected를 기준으로 표시한다.
- test row는 production coverage 분모에 넣지 않는다.
- write/delete/retry 버튼과 RAP 외부 계정은 v1에 없다.
- 커밋·Preview/production 배포는 Owner의 별도 승인과 실행 계약을 따른다.

## File Map

- `web/src/lib/rapRecordings.ts`: query/public DTO validator와 coverage 계산.
- `web/src/lib/rapRecordingsServer.ts`: server-only Supabase query와 row mapping.
- `web/src/app/api/research/rap/recordings/route.ts`: Owner list API.
- `web/src/app/api/research/rap/recordings/[id]/route.ts`: Owner detail/presigned API.
- `web/src/app/research/rap/recordings/page.tsx`: Owner page guard/shell.
- `web/src/app/research/rap/recordings/_recordings-view.tsx`: 필터·coverage·cards·player.
- `web/src/app/labeling/_owner-overview-view.tsx`: 내부 Owner research 링크.

---

### Task 1: Public DTO·query·coverage 순수 계약

**Files:**
- Create: `web/src/lib/rapRecordings.ts`
- Create: `web/src/lib/rapRecordings.test.ts`

**Interfaces:**
- Produces: `parseRapRecordingQuery(searchParams) -> RapRecordingQuery`.
- Produces: `toPublicRecording(row) -> RapRecordingSummary`.
- Produces: `computeNightCoverage(rows, night) -> {expected,captured,uploaded,failed,missing}`.

- [ ] **Step 1: RED — invalid query·field leak·72 coverage 테스트 작성**

  camera `cam04`, malformed date, limit 0/101을 거부하고 public object에 `r2_key`, `sha256`,
  `local_bundle_path`가 없는지 검사한다. production 71 uploaded + 1 failed는 expected 72, missing 0,
  failed 1이어야 한다.

- [ ] **Step 2: RED 확인**

  Run: `cd web && npm test -- src/lib/rapRecordings.test.ts`
  Expected: 새 모듈 import 실패.

- [ ] **Step 3: GREEN — strict parser와 literal slot 계산 구현**

  mode `test|production`, camera `cam01|cam02|cam03`, status allowlist,
  night `YYYY-MM-DD`, limit 1..100, cursor UUID만 받는다.

- [ ] **Step 4: GREEN 확인**

  Run: `cd web && npm test -- src/lib/rapRecordings.test.ts`
  Expected: PASS.

### Task 2: Owner-only list/detail API

**Files:**
- Create: `web/src/lib/rapRecordingsServer.ts`
- Create: `web/src/app/api/research/rap/recordings/route.ts`
- Create: `web/src/app/api/research/rap/recordings/route.test.ts`
- Create: `web/src/app/api/research/rap/recordings/[id]/route.ts`
- Create: `web/src/app/api/research/rap/recordings/[id]/route.test.ts`

**Interfaces:**
- Produces: list `{items, coverage, nextCursor}` and detail `{recording, videoUrl, thumbnailUrl}`.
- Consumes: `requireOwner`, `supabaseAdmin`, `presignGet`.

- [ ] **Step 1: RED — 401/403 short-circuit와 query validation 테스트 작성**

  unauthorized에서 repository/presigner 0회, invalid query 400, DB failure 502 generic detail,
  not-found 404를 검사한다. mock은 외부 Supabase/R2 경계만 대체하고 route JSON을 직접 검증한다.

- [ ] **Step 2: RED 확인**

  Run: `cd web && npm test -- 'src/app/api/research/rap/recordings/**/*.test.ts'`
  Expected: route 부재 실패.

- [ ] **Step 3: GREEN — server-only allowlist select와 presign 구현**

  list select는 public mapping에 필요한 필드만, detail select는 server 내부 R2 key까지 가져온다.
  detail은 `uploaded` row에만 URL을 발급하고 TTL은 3600을 넘지 않는다. UUID는 strict regex로 검증한다.

- [ ] **Step 4: GREEN 확인과 leak mutation check**

  Run: `cd web && npm test -- 'src/app/api/research/rap/recordings/**/*.test.ts'`
  Expected: PASS; public mapper 제거 시 key leak test가 실패해야 한다.

### Task 3: Owner research 화면

**Files:**
- Create: `web/src/app/research/rap/recordings/page.tsx`
- Create: `web/src/app/research/rap/recordings/_recordings-view.tsx`
- Create: `web/src/app/research/rap/recordings/_recordings-view.test.tsx`
- Modify: `web/src/app/labeling/owner/research/page.tsx`

**Interfaces:**
- Consumes list/detail API bearer 계약과 `RapRecordingSummary`.
- Produces filter/coverage/cards/player UI.

- [ ] **Step 1: RED — 사용자 체험 테스트 작성**

  production night에서 `72개 중 70개 업로드`, camera/status filter, failed badge, thumbnail 선택 후 video player,
  test mode에서 coverage 미표시를 accessible role/text로 검사한다.

- [ ] **Step 2: RED 확인**

  Run: `cd web && npm test -- src/app/research/rap/recordings/_recordings-view.test.tsx`
  Expected: component 부재 실패.

- [ ] **Step 3: GREEN — 최소 반응형 화면 구현**

  기존 labeling visual token을 재사용하고 desktop 3열/mobile 1열 card grid를 만든다. 오류는 안전한
  `연결 실패`, `녹화 실패`, `업로드 실패`, `무결성 충돌` label만 표시한다.

- [ ] **Step 4: GREEN 확인**

  Run: `cd web && npm test -- src/app/research/rap/recordings/_recordings-view.test.tsx`
  Expected: PASS.

### Task 4: 웹 회귀·보안·Preview gate

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEPLOYMENT.md`

- [ ] **Step 1: 전체 web test와 build**

  Run: `cd web && npm test && npm run build`
  Expected: 전부 PASS, TypeScript/build 오류 0건.

- [ ] **Step 2: 공개 응답 secret/key 정적 검사**

  Run: `rg -n "r2_key|sha256|local_bundle_path|R2_SECRET|SUPABASE_SERVICE" web/src/app/research/rap web/src/app/api/research/rap web/src/lib/rapRecordings*`
  Expected: server-only row 타입/query 외 public DTO/JSX/route JSON에서 0건.

- [ ] **Step 3: Preview Owner/non-Owner canary**

  Owner는 목록·thumbnail·영상 재생 성공, non-Owner는 403, 무인증은 401, detail URL TTL은 3600초 이하,
  브라우저 network response에 object key/local path가 없는지 확인한다.

- [ ] **Step 4: 상태 문서화**

  Preview가 실제 배포되지 않았으면 `IMPLEMENTED_UNVERIFIED`, 배포와 canary까지 됐으면
  `PREVIEW_READY`로만 기록하고 production 완료로 과장하지 않는다.

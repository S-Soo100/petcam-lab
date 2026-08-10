# YOLO 게코 감지 시연과 초대 팀원 bbox 기여 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 공개 사진·영상 게코 bbox 시연과 초대 팀원 blind-first bbox 기여, Owner dataset/model 승격 계약을 라벨링 웹에 추가한다.

**Architecture:** Next.js same-origin route가 입력을 검증한 뒤 주입 가능한 inference provider를 호출하고, deterministic fake로 실제 checkpoint 없는 계약을 검증한다. 사람 bbox는 blind submission → reveal → revision → Owner decision → Dataset membership의 append-only 원장으로 관리하며, model activation도 evaluation/approval/activation event를 분리한다.

**Tech Stack:** Next.js 14 App Router, React 18, TypeScript 5, Vitest 4, Supabase/PostgreSQL, Python 3.12/pytest, 기존 role/auth/R2 signer 패턴.

## Global Constraints

- 설계 정본은 `docs/superpowers/specs/2026-08-10-yolo-demo-team-contribution-design.md`다.
- 공개 업로드는 기본 학습 제외이며 opt-in도 `candidate_only`일 뿐 GT가 아니다.
- 학습 기여는 `requireLabelingAccess`를 통과하고 본인에게 배정된 task만 접근하는 초대 팀원으로 제한한다.
- reveal 전 API·DOM에는 model version, confidence, prediction box가 없어야 한다.
- blind submission, reveal, revision, Owner decision, Dataset membership은 서로 다른 append-only 원장이다.
- Owner 승인된 사람 revision만 Dataset membership에 들어간다.
- model activation은 fixed test pass + future holdout pass + Owner approve를 모두 요구한다.
- 모델 version/artifact metadata와 activation history는 immutable이며 이전 version을 재활성화해 롤백한다.
- model prediction은 GT·자동 skip·삭제·행동명·사건 묶기 근거가 아니다.
- Vercel process는 YOLO를 직접 실행하지 않는다. 실제 checkpoint/HTTP worker 연결은 별도 gate다.
- 공개 image는 JPEG/PNG/WebP 10 MiB, video는 MP4/WebM 50 MiB로 제한한다.
- fake provider는 deterministic이고 `provider_mode=fake`를 표시하며 production 기본값에서는 503이다.
- production DB migration apply, R2 write, service 변경, Vercel deploy는 수행하지 않는다.
- 기존 변경을 되돌리거나 요청 밖 refactor를 하지 않는다.
- 모든 동작 변경은 RED → 실패 원인 확인 → 최소 GREEN → 관련 회귀 순서로 구현한다.

---

## File Map

### 새 파일

- `web/src/lib/yoloDetection.ts` — 공개 detection DTO와 runtime validator.
- `web/src/lib/yoloDetection.test.ts` — provider 응답 불변식과 video frame 선택.
- `web/src/lib/yoloDetectionServer.ts` — upload sniff/limit, limiter, provider interface/fake, route factory.
- `web/src/lib/yoloDetectionServer.test.ts` — 입력 거부·fake·rate limit·production guard.
- `web/src/app/api/yolo-demo/infer/route.ts` — 공개 same-origin POST.
- `web/src/app/api/yolo-demo/infer/route.test.ts` — 실제 Request/FormData 경계 테스트.
- `web/src/app/gecko-detector/_detection-overlay.tsx` — image/video normalized bbox overlay.
- `web/src/app/gecko-detector/_detection-overlay.test.tsx` — 메타데이터·frame sync·경고 렌더.
- `web/src/app/gecko-detector/_detector-demo.tsx` — upload/consent/error 상태.
- `web/src/app/gecko-detector/page.tsx` — 공개 진입 페이지.
- `migrations/2026-08-10_yolo_demo_team_contribution.sql` — bbox/model/dataset append-only 원장과 RPC.
- `tests/test_yolo_demo_team_contribution_migration.py` — migration 정적 보안 계약.
- `tests/sql/yolo_demo_team_contribution_probe.sql` — disposable PostgreSQL 실행 불변식.
- `tests/test_yolo_demo_team_contribution_runtime_probe.py` — prerequisites+migration+probe runner.
- `web/src/lib/yoloContribution.ts` — blind/reveal/revision 공개 DTO와 allowlist mapper.
- `web/src/lib/yoloContribution.test.ts` — prediction 비노출과 box validation.
- `web/src/lib/yoloContributionApi.ts` — bearer client.
- `web/src/app/api/yolo-contributions/workspace/route.ts` — 팀원 본인 workspace.
- `web/src/app/api/yolo-contributions/workspace/route.test.ts` — auth/assignment/blind projection.
- `web/src/app/api/yolo-contributions/tasks/[taskId]/blind/route.ts` — blind 제출.
- `web/src/app/api/yolo-contributions/tasks/[taskId]/blind/route.test.ts` — 순서·오류 매핑.
- `web/src/app/api/yolo-contributions/tasks/[taskId]/reveal/route.ts` — 제출 뒤 reveal.
- `web/src/app/api/yolo-contributions/tasks/[taskId]/reveal/route.test.ts` — prediction allowlist.
- `web/src/app/api/yolo-contributions/tasks/[taskId]/revision/route.ts` — reveal 뒤 revision.
- `web/src/app/api/yolo-contributions/tasks/[taskId]/revision/route.test.ts` — revision validation.
- `web/src/lib/yoloBboxEditor.ts` — normalized box 생성·이동·resize·삭제 순수 로직.
- `web/src/lib/yoloBboxEditor.test.ts` — clamp/min-size/frame 분리.
- `web/src/app/labeling/yolo/_bbox-editor.tsx` — pointer 기반 bbox canvas.
- `web/src/app/labeling/yolo/_contribution-workspace.tsx` — blind/reveal/revision 상태 UI.
- `web/src/app/labeling/yolo/_contribution-workspace.test.tsx` — blind DOM·상태 전환.
- `web/src/app/labeling/yolo/page.tsx` — 팀원 페이지.
- `web/src/app/api/yolo-owner/reviews/route.ts` — Owner review queue.
- `web/src/app/api/yolo-owner/reviews/[revisionId]/decision/route.ts` — 승인/반려+Dataset membership.
- `web/src/app/api/yolo-owner/models/[version]/activate/route.ts` — evaluation/approval gate activation.
- `web/src/app/api/yolo-owner/owner-routes.test.ts` — owner-only·승격·activation 오류 매핑.
- `web/src/app/labeling/owner/yolo/page.tsx` — Owner 최소 review/model 화면.
- `web/src/app/labeling/owner/yolo/_owner-yolo-view.tsx` — queue와 activation form.

### 수정 파일

- `web/src/lib/labelingRoleNavigation.ts` / `.test.ts` — 승인 역할의 `게코 박스` 메뉴.
- `web/src/lib/labelingRouteAccess.ts` / `.test.ts` — `/labeling/yolo`, `/labeling/owner/yolo` 경로 분류.
- `web/src/app/page.tsx` — 공개 detector 진입 링크.
- `web/src/app/globals.css` — overlay/editor의 최소 responsive style.
- `web/.env.example` — fake provider 안전 플래그와 후속 worker 변수 설명.
- `docs/FEATURES.md`, `docs/DATABASE.md`, `specs/next-session.md`, `.claude/donts-audit.md` — additive SOT.

---

### Task 1: 공개 detection DTO와 provider boundary

**Files:**
- Create: `web/src/lib/yoloDetection.ts`
- Create: `web/src/lib/yoloDetection.test.ts`
- Create: `web/src/lib/yoloDetectionServer.ts`
- Create: `web/src/lib/yoloDetectionServer.test.ts`

**Interfaces:**
- Produces: `NormalizedBox`, `Detection`, `DetectionFrame`, `GeckoDetectionResult`.
- Produces: `validateDetectionResult(value): GeckoDetectionResult | null`.
- Produces: `frameAtTime(frames, timeMs, maxGapMs=500): DetectionFrame | null`.
- Produces: `GeckoDetectionProvider.analyze(input): Promise<GeckoDetectionResult>`.
- Produces: `FakeGeckoDetectionProvider`, `InMemoryRateLimiter`, `createInferHandler(deps)`.

- [x] **Step 1: DTO validator와 frame 선택 RED 작성**

```ts
expect(validateDetectionResult(validResult)).toEqual(validResult);
expect(validateDetectionResult({ ...validResult, frames: [{ ...frame, timestamp_ms: -1 }] })).toBeNull();
expect(validateDetectionResult({ ...validResult, frames: [{ ...frame, detections: [{ ...box, confidence: 2 }] }] })).toBeNull();
expect(frameAtTime([at0, at1000], 1200, 500)).toBe(at1000);
expect(frameAtTime([at0], 800, 500)).toBeNull();
```

- [x] **Step 2: RED 확인**

Run: `cd web && npm test -- src/lib/yoloDetection.test.ts`

Expected: FAIL because `yoloDetection.ts` does not exist.

- [x] **Step 3: 최소 DTO와 validator GREEN 구현**

```ts
export type NormalizedBox = { x: number; y: number; width: number; height: number };
export type Detection = { label: 'gecko'; confidence: number; bbox: NormalizedBox };
export type DetectionFrame = { frame_index: number; timestamp_ms: number; detections: Detection[] };

export function frameAtTime(frames: DetectionFrame[], timeMs: number, maxGapMs = 500) {
  let found: DetectionFrame | null = null;
  for (const frame of frames) {
    if (frame.timestamp_ms > timeMs) break;
    found = frame;
  }
  return found && timeMs - found.timestamp_ms <= maxGapMs ? found : null;
}
```

Validator는 plain object, exact enum, finite number, 정렬, bbox 범위를 검사하고 입력 객체를 spread로
반환하지 않고 allowlist 객체를 새로 만든다.

- [x] **Step 4: upload/provider/limiter RED 작성**

```ts
expect(sniffMedia(jpegBytes, 'image/jpeg')).toEqual({ kind: 'image', contentType: 'image/jpeg' });
expect(sniffMedia(zipBytes, 'image/jpeg')).toBeNull();
await expect(fake.analyze(imageInput)).resolves.toMatchObject({ model_version: 'fake-yolo-v0', provider_mode: 'fake' });
expect(limiter.consume('ip', now)).toBe(true);
expect(fifthThenSixth.allowed).toBe(false);
```

`createInferHandler` 테스트는 413/415/429/503, `Cache-Control: no-store`, fake success와 invalid provider
502를 실제 `Request`로 검증한다.

- [x] **Step 5: provider boundary GREEN 구현**

```ts
export interface GeckoDetectionProvider {
  readonly mode: 'fake' | 'worker';
  analyze(input: DetectionInput): Promise<GeckoDetectionResult>;
}

export function createInferHandler(deps: InferDependencies) {
  return async function POST(req: Request): Promise<Response> {
    // limiter → multipart shape → size → magic → production fake guard → provider → schema 순서
  };
}
```

Fake는 image 1 frame, video 3 timestamp frame을 고정 수식으로 만들며 input bytes나 파일명을 log/storage에
남기지 않는다.

- [x] **Step 6: focused GREEN**

Run: `cd web && npm test -- src/lib/yoloDetection.test.ts src/lib/yoloDetectionServer.test.ts`

Expected: both files PASS.

---

### Task 2: 공개 API와 사진·영상 overlay UI

**Files:**
- Create: `web/src/app/api/yolo-demo/infer/route.ts`
- Create: `web/src/app/api/yolo-demo/infer/route.test.ts`
- Create: `web/src/app/gecko-detector/_detection-overlay.tsx`
- Create: `web/src/app/gecko-detector/_detection-overlay.test.tsx`
- Create: `web/src/app/gecko-detector/_detector-demo.tsx`
- Create: `web/src/app/gecko-detector/page.tsx`
- Modify: `web/src/app/page.tsx`
- Modify: `web/src/app/globals.css`
- Modify: `web/.env.example`

**Interfaces:**
- Consumes: `createInferHandler`, `FakeGeckoDetectionProvider`, `GeckoDetectionResult`.
- Produces: public `POST /api/yolo-demo/infer` and `/gecko-detector`.

- [x] **Step 1: route integration RED 작성**

```ts
const data = new FormData();
data.set('media', new File([jpegBytes], 'gecko.jpg', { type: 'image/jpeg' }));
data.set('training_consent', 'false');
const response = await POST(new NextRequest('http://localhost/api/yolo-demo/infer', { method: 'POST', body: data }));
expect(response.status).toBe(200);
expect(response.headers.get('cache-control')).toBe('no-store');
expect(await response.json()).toMatchObject({ contribution_status: 'not_requested' });
```

- [x] **Step 2: RED 확인**

Run: `cd web && npm test -- src/app/api/yolo-demo/infer/route.test.ts`

Expected: FAIL because route does not exist.

- [x] **Step 3: route GREEN 구현**

실제 route는 module-level in-memory limiter와 environment provider resolver를 주입한다.
`NODE_ENV=production`에서는 fake provider와 local in-memory limiter를 항상 503으로 막는다.

- [x] **Step 4: overlay/UI RED 작성**

```tsx
const html = renderToStaticMarkup(<DetectionOverlay result={imageResult} mediaUrl="blob:test" />);
expect(html).toContain('fake-yolo-v0');
expect(html).toContain('연구용 결과이며 오류 가능');
expect(html).toContain('87%');
```

순수 `frameAtTime`과 video component의 `data-current-frame` 갱신 함수를 분리해 0ms/400ms/800ms의
박스 표시/삭제를 테스트한다. object URL revoke는 injectable callback으로 실제 cleanup 결과를 검사한다.

- [x] **Step 5: UI GREEN 구현**

`_detector-demo.tsx`는 file/consent/status/result/error/object URL을 관리한다. `_detection-overlay.tsx`는
image/video media 위 absolute SVG rect를 그리고 video는 `requestAnimationFrame`으로 currentTime을
동기화한다. normalized 좌표는 `x*100%` 형태로 그린다.

- [x] **Step 6: focused GREEN과 build smoke**

Run:

```bash
cd web
npm test -- src/app/api/yolo-demo/infer/route.test.ts src/app/gecko-detector/_detection-overlay.test.tsx
npx tsc --noEmit
```

Expected: tests and typecheck PASS.

---

### Task 3: append-only bbox/model/dataset migration

**Files:**
- Create: `migrations/2026-08-10_yolo_demo_team_contribution.sql`
- Create: `tests/test_yolo_demo_team_contribution_migration.py`
- Create: `tests/sql/yolo_demo_team_contribution_probe.sql`
- Create: `tests/test_yolo_demo_team_contribution_runtime_probe.py`

**Interfaces:**
- Produces tables named in design §8.
- Produces RPC:
  - `fn_get_yolo_bbox_workspace(uuid) -> jsonb`
  - `fn_submit_yolo_bbox_blind(uuid,uuid,jsonb,boolean) -> jsonb`
  - `fn_reveal_yolo_bbox_prediction(uuid,uuid) -> jsonb`
  - `fn_submit_yolo_bbox_revision(uuid,uuid,jsonb,boolean,text) -> jsonb`
  - `fn_owner_decide_yolo_bbox_revision(uuid,uuid,text,text,uuid) -> jsonb`
  - `fn_activate_yolo_model(uuid,text,text) -> jsonb`

- [x] **Step 1: migration behavior RED 작성**

Python test는 disposable probe를 우선하며 정적 검사는 권한 signature와 migration boundary만 보조한다.

```python
def test_runtime_probe_enforces_blind_dataset_and_activation_contract():
    result = run_probe()
    assert result.returncode == 0, result.stderr
    assert "YOLO_PROBE_OK" in result.stdout
```

- [x] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_yolo_demo_team_contribution_migration.py tests/test_yolo_demo_team_contribution_runtime_probe.py`

Expected: FAIL because migration/probe files do not exist.

- [x] **Step 3: schema와 append-only trigger GREEN 구현**

모든 bbox JSON은 `jsonb_typeof='array'`, 각 item의 `frame_index`, `bbox`, finite/range를
`fn_validate_yolo_boxes(jsonb)`로 검증한다. submission/reveal/revision/decision/membership/evaluation/
approval/activation에는 UPDATE/DELETE/TRUNCATE 차단 trigger를 둔다. model/dataset version metadata도
immutable trigger를 사용한다.

- [x] **Step 4: RPC ordering/authorization GREEN 구현**

```sql
IF v_task.assignee_id <> p_actor_id THEN
  RAISE EXCEPTION 'contributor_forbidden' USING ERRCODE = 'PT403';
END IF;
IF EXISTS (SELECT 1 FROM public.yolo_bbox_reveals WHERE task_id = p_task_id) THEN
  RAISE EXCEPTION 'prediction_already_revealed' USING ERRCODE = 'PT409';
END IF;
```

Owner decision RPC는 `p_owner_id` 자체를 신뢰하지 않고 Next API의 owner guard 뒤 service role 호출을
전제로 하되, DB에는 decision actor와 target dataset을 남긴다. 승인 분기에서만 membership을 같은
transaction으로 insert한다. activation RPC는 두 suite의 latest pass와 latest owner approve를 확인한다.

- [x] **Step 5: SQL probe 작성**

probe는 합성 owner/contributor/outsider, task/prediction/model/dataset을 만들고 다음을 ASSERT한다.

1. workspace JSON에 `prediction`, `model_version`, `confidence` key가 없다.
2. outsider blind submit은 PT403이다.
3. blind submit 전 reveal은 PT409다.
4. reveal 전 revision은 PT409다.
5. Owner approve 전 dataset membership은 0이다.
6. approve 후 membership은 1이고 duplicate approve는 PT409다.
7. fixed_test 또는 future_holdout 하나라도 없으면 activation은 PT409다.
8. 두 pass와 owner approve 뒤 activation되고 이전 version target event로 롤백된다.
9. append-only UPDATE/DELETE가 거부된다.
10. 전체 probe는 transaction rollback 후 residue 0이다.

- [x] **Step 6: focused GREEN**

Run: `uv run pytest -q tests/test_yolo_demo_team_contribution_migration.py tests/test_yolo_demo_team_contribution_runtime_probe.py`

Expected: tests PASS; Docker가 없으면 existing runtime probe convention에 따라 명시 skip하고 정적 계약은 PASS.

---

### Task 4: 팀원 blind/reveal/revision API

**Files:**
- Create: `web/src/lib/yoloContribution.ts`
- Create: `web/src/lib/yoloContribution.test.ts`
- Create: `web/src/lib/yoloContributionApi.ts`
- Create: `web/src/app/api/yolo-contributions/workspace/route.ts`
- Create: `web/src/app/api/yolo-contributions/workspace/route.test.ts`
- Create: `web/src/app/api/yolo-contributions/tasks/[taskId]/blind/route.ts`
- Create: `web/src/app/api/yolo-contributions/tasks/[taskId]/blind/route.test.ts`
- Create: `web/src/app/api/yolo-contributions/tasks/[taskId]/reveal/route.ts`
- Create: `web/src/app/api/yolo-contributions/tasks/[taskId]/reveal/route.test.ts`
- Create: `web/src/app/api/yolo-contributions/tasks/[taskId]/revision/route.ts`
- Create: `web/src/app/api/yolo-contributions/tasks/[taskId]/revision/route.test.ts`

**Interfaces:**
- Consumes: existing `requireLabelingAccess`, `supabaseAdmin`, `databaseUnavailable`.
- Produces: `mapBlindWorkspace`, `mapReveal`, `parseHumanBoxes`, bearer client methods.

- [x] **Step 1: allowlist mapper RED 작성**

```ts
expect(mapBlindWorkspace(rawWithPrediction)).toEqual({
  enabled: true,
  total: 2,
  completed: 0,
  next_task: expectedTaskWithoutPrediction,
});
expect(JSON.stringify(mapBlindWorkspace(rawWithPrediction))).not.toContain('confidence');
```

box parser는 unknown key 제거, UUID/frame/bbox validation, max 100 boxes, `no_gecko=true`와 boxes 비어 있음
동시 조건을 검사한다.

- [x] **Step 2: RED 확인**

Run: `cd web && npm test -- src/lib/yoloContribution.test.ts`

Expected: FAIL because module does not exist.

- [x] **Step 3: mapper/parser GREEN 구현**

```ts
export type HumanBox = { frame_index: number; bbox: NormalizedBox };
export type HumanAnnotation = { boxes: HumanBox[]; no_gecko: boolean };

export function parseHumanAnnotation(value: unknown): HumanAnnotation | null {
  // exact arrays/booleans, finite normalized values, max 100, explicit empty decision
}
```

- [x] **Step 4: route RED 작성**

각 route에서 다음 실제 결과를 테스트한다.

- bearer 없음 401
- 승인 labeler가 아니면 403
- assignment 불일치는 RPC PT403 → 403
- ordering PT409 → 409 generic detail
- DB raw error → 502 generic detail
- workspace response에 prediction keys 없음
- reveal response에는 submission 이후 allowlisted model/frame/confidence만 있음

- [x] **Step 5: route GREEN 구현**

route는 UUID/JSON을 DB 호출 전에 검증한다. `workspace`는 `fn_get_yolo_bbox_workspace`, 동작 route는
각 RPC를 호출하고 row spread 없이 mapper 결과만 반환한다. 내부 Supabase error message는 log에서도
기존 `databaseUnavailable` 경계로만 처리한다.

- [x] **Step 6: focused GREEN**

Run: `cd web && npm test -- src/lib/yoloContribution.test.ts src/app/api/yolo-contributions`

Expected: contribution test files PASS.

---

### Task 5: normalized bbox editor와 팀원 상태 UI

**Files:**
- Create: `web/src/lib/yoloBboxEditor.ts`
- Create: `web/src/lib/yoloBboxEditor.test.ts`
- Create: `web/src/app/labeling/yolo/_bbox-editor.tsx`
- Create: `web/src/app/labeling/yolo/_contribution-workspace.tsx`
- Create: `web/src/app/labeling/yolo/_contribution-workspace.test.tsx`
- Create: `web/src/app/labeling/yolo/page.tsx`
- Modify: `web/src/lib/labelingRoleNavigation.ts`
- Modify: `web/src/lib/labelingRoleNavigation.test.ts`
- Modify: `web/src/lib/labelingRouteAccess.ts`
- Modify: `web/src/lib/labelingRouteAccess.test.ts`

**Interfaces:**
- Produces: `createBox`, `moveBox`, `resizeBox`, `boxesForFrame` pure functions.
- Consumes: contribution API client and existing auth/session pattern.

- [x] **Step 1: editor math RED 작성**

```ts
expect(createBox({ x: 0.8, y: 0.8 }, { x: 1.2, y: 1.1 })).toEqual({ x: 0.8, y: 0.8, width: 0.2, height: 0.2 });
expect(createBox({ x: 0.2, y: 0.2 }, { x: 0.201, y: 0.201 })).toBeNull();
expect(moveBox(box, -1, 0)).toEqual({ ...box, x: 0 });
expect(boxesForFrame(items, 12)).toEqual(frame12Only);
```

- [x] **Step 2: RED 확인 후 최소 GREEN**

Run: `cd web && npm test -- src/lib/yoloBboxEditor.test.ts`

Expected RED: module missing. Implement 0..1 clamp와 minimum 0.005 size만 추가하고 GREEN 확인.

- [x] **Step 3: blind DOM RED 작성**

```tsx
const blindHtml = renderToStaticMarkup(<ContributionWorkspace initial={blindWorkspace} />);
expect(blindHtml).not.toContain('model_version');
expect(blindHtml).not.toContain('confidence');
expect(blindHtml).toContain('내 박스 잠그고 모델 결과 보기');

const revealedHtml = renderToStaticMarkup(<ContributionWorkspace initial={revealedWorkspace} />);
expect(revealedHtml).toContain('사람 박스');
expect(revealedHtml).toContain('모델 박스');
```

- [x] **Step 4: component GREEN 구현**

pointer down/move/up은 element bounding rect로 normalized 좌표를 계산하고 순수 editor 함수를 호출한다.
영상 task는 task manifest의 frame timestamps만 이동하며 임의 frame을 dataset 후보로 추가하지 않는다.
blind submit 성공 응답을 받은 뒤에만 reveal 요청 버튼을 활성화한다.

- [x] **Step 5: role navigation GREEN**

labeler menu에 `/labeling/yolo` `게코 박스`, owner menu에 `/labeling/owner/yolo` `게코 연구`를 추가한다.
route category는 팀원 경로를 `labeler`, Owner 경로를 `owner`로 분류한다.

- [x] **Step 6: focused GREEN과 accessibility smoke**

Run:

```bash
cd web
npm test -- src/lib/yoloBboxEditor.test.ts src/app/labeling/yolo/_contribution-workspace.test.tsx \
  src/lib/labelingRoleNavigation.test.ts src/lib/labelingRouteAccess.test.ts
```

Expected: PASS; editor buttons have names, canvas has instructions, keyboard delete and escape are covered.

---

### Task 6: Owner review, Dataset 승격, model activation API/UI

**Files:**
- Create: `web/src/app/api/yolo-owner/reviews/route.ts`
- Create: `web/src/app/api/yolo-owner/reviews/[revisionId]/decision/route.ts`
- Create: `web/src/app/api/yolo-owner/models/[version]/activate/route.ts`
- Create: `web/src/app/api/yolo-owner/owner-routes.test.ts`
- Create: `web/src/app/labeling/owner/yolo/_owner-yolo-view.tsx`
- Create: `web/src/app/labeling/owner/yolo/page.tsx`

**Interfaces:**
- Consumes: existing `requireOwner` and migration RPCs.
- Produces: Owner-only list/decision/activation HTTP contract.

- [x] **Step 1: Owner route RED 작성**

```ts
expect((await listAsLabeler()).status).toBe(403);
expect((await approveWithoutDataset()).status).toBe(400);
expect((await approveValid()).status).toBe(200);
expect((await activateMissingGate()).status).toBe(409);
expect((await rollbackToApprovedOldVersion()).status).toBe(200);
```

응답 mapper는 contributor display name, task media metadata, blind boxes, revision boxes, prediction snapshot,
dataset/model gate summary만 allowlist한다. user email, raw r2 key, artifact path는 제외한다.

- [x] **Step 2: RED 확인**

Run: `cd web && npm test -- src/app/api/yolo-owner/owner-routes.test.ts`

Expected: FAIL because routes do not exist.

- [x] **Step 3: API GREEN 구현**

모든 route는 `requireOwner`를 첫 단계로 사용한다. approve에는 dataset UUID와 3..1000자 reason,
reject에는 reason만 요구한다. activate에는 target version과 reason을 받고 RPC gate error를 409로 바꾼다.

- [x] **Step 4: Owner UI RED/GREEN**

SSR test는 `Owner 승인 전 Dataset 미포함`, fixed test/future holdout/Owner approve 상태, `활성화`,
`이전 버전으로 롤백` 문구를 검사한다. UI는 API 결과를 표시하되 자동 activation을 호출하지 않는다.

- [x] **Step 5: focused GREEN**

Run: `cd web && npm test -- src/app/api/yolo-owner/owner-routes.test.ts src/app/labeling/owner/yolo`

Expected: owner tests PASS.

---

### Task 7: 문서·전체 검증·독립 리뷰

**Files:**
- Modify: `docs/FEATURES.md`
- Modify: `docs/DATABASE.md`
- Modify: `specs/next-session.md`
- Modify: `.claude/donts-audit.md`

**Interfaces:**
- Documents exact fake-only local state and prohibited operational actions.

- [x] **Step 1: 문서 갱신**

기능/DB 문서에 public demo, blind provenance, activation gate를 추가한다. next-session에는 실제
checkpoint/HTTP worker/production migration/deploy가 별도 owner gate라는 재개 조건을 기록한다.
donts audit에는 최소 변경, 비밀값, Vercel inference 금지, prediction≠GT 감사를 한 줄 남긴다.

- [x] **Step 2: focused suites**

Run:

```bash
uv run pytest -q tests/test_yolo_demo_team_contribution_migration.py \
  tests/test_yolo_demo_team_contribution_runtime_probe.py
cd web && npm test -- src/lib/yoloDetection.test.ts src/lib/yoloDetectionServer.test.ts \
  src/app/api/yolo-demo/infer/route.test.ts src/app/gecko-detector/_detection-overlay.test.tsx \
  src/lib/yoloContribution.test.ts src/app/api/yolo-contributions \
  src/lib/yoloBboxEditor.test.ts src/app/labeling/yolo \
  src/app/api/yolo-owner/owner-routes.test.ts
```

- [x] **Step 3: 전체 회귀와 build** — Python/Web 전체 회귀·tsc·diff check와 사용자 터미널의
  현재 worktree `npm run build`를 완료했다.

Run:

```bash
uv run pytest -q
cd web && npm test
cd web && npm run build
git diff --check
```

Expected: Python/Web all pass, Next build succeeds, whitespace errors 0.

- [x] **Step 4: DB safety evidence**

disposable PostgreSQL이 사용 가능하면 prerequisites → migration → probe → rollback을 실제 실행하고
residue 0을 기록한다. 사용할 수 없으면 runtime probe skip 사유와 정적 migration test의 한계를
`IMPLEMENTED_UNVERIFIED`가 아닌 정확한 미검증 항목으로 보고한다.

- [x] **Step 5: 독립 코드 리뷰**

변경 stat으로 공개 inference, contribution, DB/Owner 세 그룹을 나누어 보안·blind·dataset/model gate를
검토한다. P0/P1은 TDD 회귀를 먼저 추가한 뒤 수정하고 focused+전체 검증을 다시 실행한다.

- [x] **Step 6: 최종 상태 기록**

production DB/R2/service/Vercel write가 모두 0임을 확인한다. 실제 checkpoint가 없으므로 결과 상태는
최대 `REVIEWED_READY_FOR_INTEGRATION`이며 `PREVIEW_READY`나 `DEPLOYED_VERIFIED`를 주장하지 않는다.

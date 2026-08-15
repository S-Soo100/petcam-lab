# YOLO26n v2.5 Owner Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 동결된 YOLO26n v2.5 warm-start를 기존 공개 v2.3 흐름과 분리된 라벨링 웹 Owner 전용 Vercel Preview에 연결한다.

**Status:** `PREVIEW_READY_V25_OWNER_ONLY` — 2026-08-15 Owner image/video UI canary 완료. future holdout·main merge·production promote는 미진행.

**Architecture:** v2.3 배포 branch를 기반으로 v2.5 exact manifest와 병렬 Mac mini worker를 추가한다. 새 same-origin API는 Owner 인증과 Preview 환경을 먼저 검증한 뒤 exact v2.5 worker만 호출하며, 별도 Owner 화면은 prediction overlay만 표시하고 GT·학습·DB/R2 write path를 갖지 않는다.

**Tech Stack:** Python 3.12, FastAPI, Ultralytics 8.4.104, PyTorch MPS, launchd, Cloudflare Named Tunnel, Next.js 14, TypeScript, Vitest, Vercel Preview

## Global Constraints

- Research commit: `125d6433c887402dbc244f4adf713e9bb05b2835`.
- Candidate: `warm-start`; checkpoint size `5,400,517`; SHA-256 `2b128f105e898bc472ed66861583ab80007dae6e94b291db497d7a2f8081f84a`.
- Model version: `yolo26n-owner-dataset-v2.5-warm-start+2b128f105e89`.
- Threshold `0.20`; fixed-test TP 68 / FP 25 / FN 22 / duplicate 9 / precision `0.7311827956989247` / recall `0.7555555555555555`.
- Evaluation tier `development`; old-distribution regression-only; `future_holdout_required=true`; `production_adoption=false`.
- Allowed use `owner_preview_bbox_suggestion_only`.
- Prediction은 GT 자동 저장·승인·Dataset membership·학습 enqueue·absence decision에 사용하지 않는다.
- Public v2.3 worker/service/tunnel/API, production Vercel alias/env, DB/R2, GME, Gecko Vision Gate를 변경하지 않는다.
- Main merge와 production promote를 하지 않는다.
- Artifact copy와 runtime 시작 전에 각각 `HANDOFF_OK`를 확보한다.
- Secret, private path, raw media/GT는 Git, HTTP response, stdout, deployment report에 넣지 않는다.

---

### Task 1: v2.5 exact immutable release 계약

**Files:**
- Modify: `backend/yolo_release.py`
- Create: `scripts/create_yolo_v25_release.py`
- Modify: `tests/test_yolo_release.py`

**Interfaces:**
- Consumes: existing `YoloReleaseManifest`, v2.5 source checkpoint.
- Produces: `v25_release_manifest() -> YoloReleaseManifest`, v2.3/v2.5 exact allowlist validation, v2.5 release CLI.

- [x] **Step 1: v2.5 manifest RED 테스트 작성**

```python
def test_v25_manifest_is_exact_development_owner_preview_contract():
    manifest = v25_release_manifest()
    assert manifest.model_version == "yolo26n-owner-dataset-v2.5-warm-start+2b128f105e89"
    assert manifest.checkpoint_sha256 == V25_CHECKPOINT_SHA256
    assert manifest.checkpoint_size == 5_400_517
    assert manifest.threshold == 0.20
    assert manifest.allowed_use == "owner_preview_bbox_suggestion_only"
    assert manifest.fixed_test == FixedTestMetrics(
        tp=68, fp=25, fn=22,
        precision=0.7311827956989247,
        recall=0.7555555555555555,
    )
```

v2.5 threshold/size/SHA/metrics/scope 변조 거부와 기존 v2.3 round-trip 회귀를 같은 test file에 추가한다.

- [x] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_yolo_release.py`

Expected: `v25_release_manifest` import 부재 또는 v2.3-only validator 때문에 FAIL.

- [x] **Step 3: 최소 구현**

`v23_release_manifest()`와 `v25_release_manifest()`를 version-keyed immutable registry로 묶는다.
`_validate_manifest()`는 전달된 version의 exact registry manifest와 전체 equality를 검사한다. CLI는 source와
release root를 인자로 받되 fixed v2.5 manifest만 사용하고 path를 출력하지 않는다.

- [x] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/test_yolo_release.py && uv run python -m py_compile backend/yolo_release.py scripts/create_yolo_v25_release.py`

- [x] **Step 5: Task commit**

```bash
git add backend/yolo_release.py scripts/create_yolo_v25_release.py tests/test_yolo_release.py
git commit -m "feat: YOLO v2.5 immutable release 계약"
```

### Task 2: 병렬 v2.5 worker identity와 manager

**Files:**
- Modify: `backend/yolo_preview_worker.py`
- Create: `scripts/manage_yolo_v25_owner_preview_worker.py`
- Modify: `tests/test_yolo_preview_worker.py`
- Create: `tests/test_manage_yolo_v25_owner_preview_worker.py`

**Interfaces:**
- Consumes: `load_release_manifest()`, `v25_release_manifest()`, existing inference/decode helpers.
- Produces: env-selected exact manifest worker, `com.petcam.yolo-preview-worker-v25` on `127.0.0.1:8095`.

- [x] **Step 1: worker/manager RED 테스트 작성**

```python
def test_v25_worker_uses_frozen_threshold_and_owner_preview_scope(tmp_path):
    config = worker_config(tmp_path, manifest=v25_release_manifest())
    runner = FakeRunner()
    with TestClient(create_app(config=config, runner=runner)) as client:
        response = client.get("/v1/health", headers=auth(config.token))
    assert response.json()["threshold"] == 0.20
    assert response.json()["usage_scope"] == "owner_preview_bbox_suggestion_only"

def test_v25_manager_is_parallel_to_v23(tmp_path):
    plist = build_v25_plist(repo=tmp_path / "repo", env_file=tmp_path / "worker.env")
    encoded = plistlib.dumps(plist).decode()
    assert V25_LABEL == "com.petcam.yolo-preview-worker-v25"
    assert "8095" in encoded
    assert "com.petcam.yolo-preview-worker-v23" not in encoded
```

manifest/version mismatch는 model factory 전 실패, v23 env default 회귀, checkpoint mode/SHA, health full
identity, uninstall target isolation을 추가한다.

- [x] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_yolo_preview_worker.py tests/test_manage_yolo_v25_owner_preview_worker.py`

- [x] **Step 3: 최소 구현**

`WorkerConfig.from_env()`는 `YOLO_EXPECTED_MODEL_VERSION`이 없으면 v2.3, 있으면 exact registry manifest를
요구한다. 새 v2.5 manager는 기존 v2.3 manager를 호출하지 않고 label/port/health expected identity를
v2.5로 고정한다.

- [x] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/test_yolo_release.py tests/test_yolo_preview_worker.py tests/test_manage_yolo_preview_worker.py tests/test_manage_yolo_v25_owner_preview_worker.py`

- [x] **Step 5: Task commit**

```bash
git add backend/yolo_preview_worker.py scripts/manage_yolo_v25_owner_preview_worker.py tests/test_yolo_preview_worker.py tests/test_manage_yolo_v25_owner_preview_worker.py
git commit -m "feat: YOLO v2.5 병렬 Preview worker"
```

### Task 3: Owner-only Preview API

**Files:**
- Create: `web/src/lib/yoloOwnerPreviewRoute.ts`
- Create: `web/src/lib/yoloOwnerPreviewRoute.test.ts`
- Create: `web/src/app/api/yolo-owner/preview/infer/route.ts`
- Create: `web/src/app/api/yolo-owner/preview/infer/route.test.ts`
- Modify: `web/src/lib/yoloDetection.ts`
- Modify: `web/src/lib/yoloDetection.test.ts`

**Interfaces:**
- Consumes: `requireOwner(req)`, `HttpGeckoDetectionProvider`, `createInferHandler()`.
- Produces: `createOwnerPreviewPostFromEnv(env, fetchImpl)` and authenticated `POST /api/yolo-owner/preview/infer`.

- [x] **Step 1: 권한·환경 RED 테스트 작성**

```ts
it('비인증·비Owner·production 요청은 body parse와 worker 호출 전에 닫는다', async () => {
  const workerFetch = vi.fn();
  expect((await post(requestWithoutBearer(), previewEnv(), workerFetch)).status).toBe(401);
  expect(workerFetch).not.toHaveBeenCalled();
  expect((await post(nonOwnerRequest(), previewEnv(), workerFetch)).status).toBe(403);
  expect((await post(ownerRequest(), { ...previewEnv(), VERCEL_ENV: 'production' }, workerFetch)).status).toBe(404);
  expect(workerFetch).not.toHaveBeenCalled();
});
```

flag/url/token 누락, wrong origin, wrong model/threshold/scope, training consent `true`, candidate status를 모두
worker call 0 또는 502로 고정한다. 성공 응답은 v2.5 exact identity만 허용한다.

- [x] **Step 2: RED 확인**

Run: `cd web && npm test -- --run src/lib/yoloOwnerPreviewRoute.test.ts src/app/api/yolo-owner/preview/infer/route.test.ts`

- [x] **Step 3: 최소 구현**

route는 `requireOwner` 성공 뒤에만 preview factory를 호출한다. factory는
`VERCEL_ENV=preview`, `YOLO_V25_OWNER_PREVIEW_ENABLED=true`, exact origin
`https://yolo-v25-preview.tera-ai.uk`, 유효 token을 요구하고 expected identity를 아래처럼 고정한다.

```ts
const V25_IDENTITY = {
  modelVersion: 'yolo26n-owner-dataset-v2.5-warm-start+2b128f105e89',
  threshold: 0.20,
  developmentOnly: true,
  usageScope: 'owner_preview_bbox_suggestion_only',
} as const;
```

DTO usage scope union에 owner-preview 값을 추가하되 공개 v2.3 parser 회귀를 유지한다.

- [x] **Step 4: GREEN 확인**

Run: `cd web && npm test -- --run src/lib/yoloOwnerPreviewRoute.test.ts src/app/api/yolo-owner/preview/infer/route.test.ts src/app/api/yolo-demo/infer/route.test.ts src/lib/yoloDetection.test.ts`

- [x] **Step 5: Task commit**

```bash
git add web/src/lib/yoloOwnerPreviewRoute.ts web/src/lib/yoloOwnerPreviewRoute.test.ts web/src/app/api/yolo-owner/preview/infer web/src/lib/yoloDetection.ts web/src/lib/yoloDetection.test.ts
git commit -m "feat: Owner 전용 YOLO v2.5 Preview API"
```

### Task 4: 라벨링 웹 Owner Preview 화면

**Files:**
- Create: `web/src/app/labeling/owner/yolo/preview/page.tsx`
- Create: `web/src/app/labeling/owner/yolo/preview/_owner-preview.tsx`
- Create: `web/src/app/labeling/owner/yolo/preview/_owner-preview.test.tsx`
- Modify: `web/src/app/labeling/owner/yolo/_owner-yolo-view.tsx`
- Modify: `web/src/app/api/yolo-owner/owner-routes.test.tsx`

**Interfaces:**
- Consumes: Supabase browser session, Owner Preview API, `DetectionOverlay`.
- Produces: `/labeling/owner/yolo/preview` upload/drop/result UI and Owner research link.

- [x] **Step 1: UI RED 테스트 작성**

```tsx
it('development-only model identity와 no-write 경계를 업로드 전에 표시한다', () => {
  const html = renderToStaticMarkup(<OwnerYoloV25Preview />);
  expect(html).toContain('Development-only Owner Preview');
  expect(html).toContain('v2.5 warm-start');
  expect(html).toContain('threshold 0.20');
  expect(html).toContain('prediction은 GT로 저장되지 않아');
  expect(html).toContain('future holdout');
  expect(html).not.toContain('학습 반영');
  expect(html).not.toContain('자동 승인');
});
```

실제 submit은 bearer header와 `training_consent=false`만 보내고, result 0 detection은 absence가 아니라는
문구, response version/threshold 표시, 다중/잘못된 파일 거부를 추가한다.

- [x] **Step 2: RED 확인**

Run: `cd web && npm test -- --run src/app/labeling/owner/yolo/preview src/app/api/yolo-owner/owner-routes.test.tsx`

- [x] **Step 3: 최소 구현**

기존 drag/drop 검증과 `DetectionOverlay`를 재사용한다. 업로드 상태는 component state에만 두고
localStorage·DB client·GT/revision API import를 추가하지 않는다. Owner 연구 화면에는 Preview로 가는 링크만
추가한다.

- [x] **Step 4: GREEN 확인**

Run: `cd web && npm test -- --run src/app/labeling/owner/yolo/preview src/app/api/yolo-owner/owner-routes.test.tsx src/app/gecko-detector`

- [x] **Step 5: Task commit**

```bash
git add web/src/app/labeling/owner/yolo/preview web/src/app/labeling/owner/yolo/_owner-yolo-view.tsx web/src/app/api/yolo-owner/owner-routes.test.tsx
git commit -m "feat: 라벨링 웹 v2.5 Owner Preview 화면"
```

### Task 5: 전체 검증과 runtime handoff commit

**Files:**
- Modify: `.claude/donts-audit.md`
- Modify: `specs/next-session.md`
- Create: `docs/handoff-prompts/2026-08-15-yolo-v25-owner-preview-handoff.md`

**Interfaces:**
- Consumes: Tasks 1-4 reviewed implementation.
- Produces: exact pushed implementation SHA and Mac mini runtime `HANDOFF_OK` manifest.

- [x] **Step 1: fresh 전체 검증**

```bash
uv run pytest -q
cd web && npm test
cd web && npx tsc --noEmit
cd web && npm run build
git diff --check
```

- [x] **Step 2: 범위 감사**

`rg`로 새 route/component/worker에 Supabase write, R2 upload, GT/revision, GME/Gate, training call이 없음을
확인한다. `git diff --stat`으로 기능 그룹을 순서대로 검토한다.

- [x] **Step 3: 문서와 구현 commit/push**

검증 수치와 `IMPLEMENTED_UNVERIFIED_RUNTIME` 상태를 문서에 기록하고 승인 범위 파일만 commit/push한다.

- [x] **Step 4: Mac mini runtime handoff 검증**

Mac mini 별도 repo를 exact implementation SHA의 clean detached HEAD로 만든다. repo 밖 mode 0600 manifest에
Mac mini execution repo/design/plan 절대경로, SHA, implementation host, runtime host, `runtime_kind=launchagent`,
`runtime_label=com.petcam.yolo-preview-worker-v25`를 기록한다.

Run: `uv run python scripts/verify_agent_handoff.py --manifest /Users/baek-end/private-rba/yolo26n-v25-owner-preview/handoff-v1.private.md`

Expected: literal `HANDOFF_OK ... runtime=launchagent@baeg-endeuui-Macmini.local`.

### Task 6: Mac mini v2.5 release·worker·tunnel canary

**Runtime:**
- Host: `baeg-endeuui-Macmini.local`
- Service: `com.petcam.yolo-preview-worker-v25`
- Local port: `8095`
- Remote origin: `https://yolo-v25-preview.tera-ai.uk`

- [x] **Step 1: immutable release 생성**

private source size/SHA와 research manifest metrics를 다시 확인하고 v2.5 release CLI를 실행한다. source
before/after SHA, copy SHA, files mode 0444, partial residue 0을 확인한다.

- [x] **Step 2: 병렬 worker 설치**

v2.5 전용 mode 0600 env를 만들고 manager install을 실행한다. v2.3/v2.5 service가 동시에 loaded이며
각각 8094/8095에서 exact health를 반환하는지 확인한다.

- [x] **Step 3: localhost canary**

인증 없는 health/infer 401, 잘못된 token 401, image/video actual inference, version/threshold/scope,
zero-detection warning, temp residue 0, secret/path log 0을 확인한다.

- [x] **Step 4: 별도 Named Tunnel**

v2.5 전용 named tunnel과 DNS route를 만들고 별도 LaunchAgent로 실행한다. remote unauthenticated 401,
authenticated health 200과 exact full SHA를 확인한다. v2.3 remote health는 계속 200이어야 한다.

### Task 7: Vercel Owner Preview와 최종 canary

- [x] **Step 1: branch-scoped Preview deploy**

feature branch Preview에만 `YOLO_V25_OWNER_PREVIEW_ENABLED=true`, v2.5 URL/token을 주입한다. production env와
alias를 건드리지 않고 deployment `READY`를 확인한다.

- [x] **Step 2: API negative/positive canary**

Preview API의 unauthenticated 401, non-owner 403, Owner image/video 200, exact v2.5 identity를 확인한다.
production `/api/yolo-demo/infer`는 계속 v2.3 identity이고 production 새 owner-preview route는 존재하지 않아야
한다.

- [x] **Step 3: Owner 브라우저 체험**

로그인된 Owner가 `/labeling/owner/yolo/preview`에서 image/video drop→bbox overlay→version/threshold/warning을
확인한다. console error 0, horizontal overflow 0, GT/save/approval request 0을 확인한다.

- [x] **Step 4: 최종 증거 기록**

Preview deployment ID/URL, implementation/runtime SHA, service/tunnel 상태, canary counts, DB/R2/GT/GME/Gate
write 0, production alias 불변을 기록한다. 상태를 `PREVIEW_READY_V25_OWNER_ONLY`로 갱신한다.

### Final Evidence — 2026-08-15

- Implementation SHA: `a9c225b7521b31a7dc3c827afa85e22f606e60b3` (branch `codex/yolo-v25-owner-preview`).
- Preview deployment: `dpl_J42aneLMiSgK9ZrKbWqh97xRuiot`, branch alias
  `https://petcam-lab-git-codex-yolo-v25-owner-preview-ssoo100s-projects.vercel.app`, `READY`.
- Branch Preview env는 trailing newline을 제거해 exact `true`/worker origin으로 교정했고, sensitive token은
  Mac mini mode 0600 runtime env에서 stdout 비노출 pipe로 재등록했다. production env는 변경하지 않았다.
- Mac mini localhost/remote health 모두 v2.5 exact full version, threshold `0.20`, MPS,
  `owner_preview_bbox_suggestion_only`; v2.5 worker/tunnel과 기존 v2.3 worker가 동시에 loaded다.
- Owner UI: positive image `1` bbox/`98%`, zero image 안전 문구/감지 없음, video element+video overlay/감지 없음,
  bbox hide/show, console error `0`, horizontal overflow `0`, 저장·승인·학습 버튼 `0`.
- Preview API unauthenticated `401`; Owner image/zero/video 요청은 exact identity validation을 통과했다.
- Fresh verification: Python `1277 passed, 5 skipped`; Web `125 files, 1060 passed`; TypeScript exit `0`.
- Production alias는 `dpl_FtC5Up5MANYieALZyqysagvmgC3Y` 그대로이며 공개 inference는 v2.3/threshold `0.25`,
  production Owner Preview page는 `404`다.
- Preview route/component write-path audit: DB/R2/GT/Dataset/GME/Gate write `0`; main merge·production promote `0`.

## Completion Boundary

Owner가 보호 Vercel Preview에서 v2.5 bbox 제안을 실제로 확인하고, public v2.3과 production 데이터/모델이
불변임을 검증하면 완료다. future holdout, 팀원 기본 승격, main merge, production promote는 후속 별도 gate다.

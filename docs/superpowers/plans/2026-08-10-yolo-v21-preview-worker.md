# YOLO v2.1 Protected Preview Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 보호된 Vercel Preview의 `/gecko-detector`를 Mac mini의 pinned YOLO v2.1 worker에 연결해 실제 사진·영상 bbox 시연을 제공한다.

**Architecture:** Mac mini FastAPI worker가 localhost에서 pinned checkpoint를 MPS로 실행하고 기존 Cloudflare Named Tunnel의 별도 hostname으로만 노출된다. Vercel route는 `VERCEL_ENV=preview`와 명시적 enable/URL/token이 모두 있을 때만 HTTP provider를 주입하며 production은 환경변수와 무관하게 기존 503 fail-closed를 유지한다.

**Tech Stack:** Python 3.12, FastAPI, Ultralytics 8.4.104, PyTorch MPS, OpenCV/Pillow/ffprobe, Next.js 14, TypeScript, Vitest, Cloudflare Named Tunnel, launchd, Vercel Preview

## Global Constraints

- checkpoint path는 `/Users/baek-end/private-rba/yolo26n-owner-dataset-v21/attempt-20260810-owner-final-v1/runs/baseline-960-v21/weights/best.pt`다.
- expected checkpoint SHA-256은 `9ba825697693a0e84078a32120f64ea4e9da6a20bb50b9636403c9409200036e`, size는 `5,408,389` bytes다.
- inference는 `imgsz=960`, `conf=0.25`, `iou=0.7`, `max_det=20`, `device=mps`, `verbose=false`로 고정한다.
- image는 10 MiB/20 MP, video는 50 MiB/60초/30 fps/1920×1080 이하이며 video inference는 최대 5 fps·300 sampled frames다.
- worker bind는 `127.0.0.1:8093`, LaunchAgent label은 `com.petcam.yolo-preview-worker`다.
- tunnel은 기존 `1e7a9232-2934-44de-a39b-aee1c6b54af7`와 `cvat.tera-ai.uk` ingress를 보존하고 `yolo-preview.tera-ai.uk`만 추가한다.
- production Vercel provider/active model, DB/R2/Dataset/GT/skip/삭제/행동명/사건 묶기는 변경하지 않는다.
- development holdout 34장 수치는 provenance일 뿐 production 승격 근거가 아니다.
- secret/checkpoint path/worker exception은 HTTP 응답, Git, plist, Vercel build log에 넣지 않는다.
- 최종 상태는 최대 `PREVIEW_READY_SHADOW_ONLY`다.

---

### Task 1: Worker runtime identity와 model output 정규화

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `backend/yolo_preview_worker.py`
- Create: `tests/test_yolo_preview_worker.py`

**Interfaces:**
- Consumes: checkpoint path/SHA/token/expected host를 환경변수로 받는다.
- Produces: `WorkerConfig.from_env()`, `checkpoint_sha256(path)`, `YoloModelRunner.predict_image(frame)`, `create_app(config, runner)`.

- [ ] **Step 1: runtime identity RED 테스트 작성**

```python
def test_config_rejects_wrong_host_or_checkpoint_hash(tmp_path, monkeypatch):
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"wrong")
    monkeypatch.setenv("YOLO_CHECKPOINT_PATH", str(checkpoint))
    monkeypatch.setenv("YOLO_CHECKPOINT_SHA256", "9ba825697693a0e84078a32120f64ea4e9da6a20bb50b9636403c9409200036e")
    monkeypatch.setenv("YOLO_WORKER_TOKEN", "x" * 43)
    monkeypatch.setenv("YOLO_EXPECTED_HOST", "baeg-endeuui-Macmini.local")
    with pytest.raises(WorkerStartupError, match="checkpoint_identity_invalid"):
        WorkerConfig.from_env(hostname=lambda: "baeg-endeuui-Macmini.local")
```

같은 파일에 token 최소 32 bytes, regular non-symlink checkpoint, exact size/SHA, expected hostname, MPS
required, public model version `yolo26n-owner-v2.1+9ba825697693` 테스트를 추가한다.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_yolo_preview_worker.py`

Expected: module/import가 없어 FAIL.

- [ ] **Step 3: optional runtime dependency 고정**

Run: `uv add --group yolo-preview 'ultralytics==8.4.104'`

`ultralytics` import는 `YoloModelRunner.load()` 안에서 lazy import해 기본 test/import에 AGPL runtime을
강제하지 않는다.

- [ ] **Step 4: identity와 runner 최소 구현**

```python
MODEL_VERSION = "yolo26n-owner-v2.1+9ba825697693"
EXPECTED_CHECKPOINT_SIZE = 5_408_389

def checkpoint_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

`WorkerConfig.from_env()`는 secret 값이나 path를 exception 문자열에 넣지 않고 allowlisted error code만
낸다. `YoloModelRunner.load()`는 `torch.backends.mps.is_available()`을 확인하고
`YOLO(checkpoint)`를 한 번 load한다. `predict_image()`는 결과의 `xyxy/conf/cls`를 frame 크기로
normalize하고 finite, positive, `[0,1]` clamp 후 `gecko`만 반환한다.

- [ ] **Step 5: fake result 정규화 GREEN 테스트**

fake tensor/result로 음수/프레임 밖 좌표 clamp, confidence finite, class allowlist, empty detection,
`max_det=20` 호출 인자를 검증한다.

Run: `uv run pytest -q tests/test_yolo_preview_worker.py`

Expected: identity/model tests PASS.

- [ ] **Step 6: Task 1 커밋**

```bash
git add pyproject.toml uv.lock backend/yolo_preview_worker.py tests/test_yolo_preview_worker.py
git commit -m "feat: YOLO v2.1 worker identity 고정"
```

---

### Task 2: Worker HTTP 입력 방어·영상 sampling·cleanup

**Files:**
- Modify: `backend/yolo_preview_worker.py`
- Modify: `tests/test_yolo_preview_worker.py`

**Interfaces:**
- Consumes: Task 1의 `WorkerConfig`, `YoloModelRunner`.
- Produces: authenticated `GET /v1/health`, `POST /v1/infer`, 기존 `GeckoDetectionResult` JSON.

- [ ] **Step 1: HTTP/auth/temp RED 테스트 작성**

```python
def test_infer_requires_bearer_and_cleans_temp_after_decode_failure(app, temp_root):
    with TestClient(app) as client:
        assert client.post("/v1/infer", content=b"bad").status_code == 401
        response = client.post(
            "/v1/infer",
            headers=valid_headers(content_type="image/jpeg"),
            content=b"not-jpeg",
        )
    assert response.status_code == 422
    assert list(temp_root.iterdir()) == []
    assert "checkpoint" not in response.text.lower()
```

추가 RED: duplicate/missing metadata, chunked body cap, signature mismatch, image 20 MP, animated image,
video duration/fps/dimension, decode timeout, global 30/min limiter, concurrency 1, model exception redaction,
health auth와 path non-disclosure.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_yolo_preview_worker.py`

Expected: routes/validation/cleanup 미구현으로 FAIL.

- [ ] **Step 3: bounded body와 temp lifecycle 구현**

`Request.stream()`을 순회해 선언 kind 기준 10/50 MiB를 넘는 순간 413으로 중단한다. 각 요청은
`tempfile.mkdtemp(prefix="petcam-yolo-preview-", dir=config.temp_root)` 후 mode 0700을 확인하고,
client filename 없이 `media.bin`만 쓴다. 전체 handler를 `try/finally: shutil.rmtree(..., ignore_errors=True)`로
감싼다. startup에서는 같은 prefix 중 mtime 900초 초과 directory만 삭제한다.

- [ ] **Step 4: image/video validation과 sampling 구현**

image는 magic sniff → Pillow `verify()` → 재open RGB decode → 20 MP 검사 순서다. video는 magic sniff →
ffprobe JSON을 `subprocess.run(..., timeout=15, check=True)`로 읽고 duration/fps/dimension을 검사한 뒤
OpenCV sequential decode한다. `stride=max(1, ceil(source_fps/5))`로 최대 300 frames를 추론하고 실제
`frame_index`와 `timestamp_ms=round(frame_index/source_fps*1000)`를 반환한다. `VideoCapture.release()`는
`finally`에서 호출한다.

- [ ] **Step 5: auth/rate/concurrency 구현**

bearer는 `secrets.compare_digest`로 검사한다. 단일 process global sliding window 30/min과
`asyncio.Semaphore(1)`을 둔다. semaphore가 이미 사용 중이면 queue하지 않고 503을 반환한다.
health는 인증 뒤 `status/model_version/device/checkpoint_sha256`만 반환한다.

- [ ] **Step 6: GREEN 확인**

Run: `uv run pytest -q tests/test_yolo_preview_worker.py`

Expected: worker tests PASS, temp residue 0.

- [ ] **Step 7: Task 2 커밋**

```bash
git add backend/yolo_preview_worker.py tests/test_yolo_preview_worker.py
git commit -m "feat: YOLO Preview worker 입력 방어 추가"
```

---

### Task 3: Vercel Preview HTTP provider와 production hard guard

**Files:**
- Create: `web/src/lib/yoloHttpProvider.ts`
- Create: `web/src/lib/yoloHttpProvider.test.ts`
- Modify: `web/src/lib/yoloDetectionServer.ts`
- Modify: `web/src/lib/yoloDetectionServer.test.ts`
- Modify: `web/src/app/api/yolo-demo/infer/route.ts`
- Modify: `web/src/app/api/yolo-demo/infer/route.test.ts`
- Modify: `web/.env.example`

**Interfaces:**
- Consumes: `DetectionInput`, `GeckoDetectionProvider`, `GeckoDetectionResult`.
- Produces: `HttpGeckoDetectionProvider`, `deploymentTarget()`, `createRouteDependencies(env)`.

- [ ] **Step 1: HTTP provider RED 테스트 작성**

```ts
it('worker에 raw bytes와 allowlisted metadata만 보내고 응답을 반환한다', async () => {
  const fetchImpl = vi.fn().mockResolvedValue(Response.json(workerResult));
  const provider = new HttpGeckoDetectionProvider({
    baseUrl: 'https://yolo-preview.example.test', token: 'secret', fetchImpl,
  });
  await provider.analyze(input);
  expect(fetchImpl).toHaveBeenCalledWith(
    'https://yolo-preview.example.test/v1/infer',
    expect.objectContaining({ method: 'POST', body: input.bytes }),
  );
});
```

추가 RED: 65초 abort, non-HTTPS URL 거부(`localhost`는 test only explicit option), non-2xx redaction,
invalid JSON, request/consent identity mismatch는 기존 route 502.

- [ ] **Step 2: Preview/production 선택 RED 테스트**

```ts
it('production은 worker env가 모두 있어도 provider를 호출하지 않고 503이다', async () => {
  const fetchImpl = vi.fn();
  const post = createPostFromEnv(workerEnv({ VERCEL_ENV: 'production' }), fetchImpl);
  expect((await post(request())).status).toBe(503);
  expect(fetchImpl).not.toHaveBeenCalled();
});
```

Preview enable/url/token 누락은 503, 셋이 모두 있으면 worker mode, development/test는 기존 fake라는
matrix를 고정한다.

- [ ] **Step 3: RED 확인**

Run:

```bash
cd web && npm test -- --run src/lib/yoloHttpProvider.test.ts \
  src/lib/yoloDetectionServer.test.ts src/app/api/yolo-demo/infer/route.test.ts
```

Expected: provider/factory가 없어 FAIL.

- [ ] **Step 4: provider와 target 구현**

`InferDependencies.environment`에 `preview`를 추가한다. `VERCEL_ENV`를 `preview/production`으로 먼저
판정하고 그 외는 `NODE_ENV`를 사용한다. production guard는 현재와 동일하게 distributed limiter와
non-fake provider 두 조건을 요구하므로 worker env만으로 열리지 않는다. Preview는 local route limiter와
Mac worker limiter를 함께 쓴다.

`HttpGeckoDetectionProvider`는 URL/token을 private field로 유지하고 error 문자열에 넣지 않는다.
`AbortSignal.timeout(65_000)`과 `Cache-Control: no-store`를 사용한다.

- [ ] **Step 5: route DI 구현**

route module은 `createPostFromEnv(env, fetchImpl=fetch)`를 export하고 실제 `POST`는 그 factory 결과다.
Preview worker 조건이 불완전하면 fake provider를 만들되 preview handler가 명시적으로 503이 되게 한다.
환경변수 예시는 값 없이 이름과 Preview-only 경고만 추가한다.

- [ ] **Step 6: GREEN 확인**

Run:

```bash
cd web && npm test -- --run src/lib/yoloHttpProvider.test.ts \
  src/lib/yoloDetectionServer.test.ts src/app/api/yolo-demo/infer/route.test.ts
cd web && npx tsc --noEmit
```

Expected: provider/route tests와 typecheck PASS.

- [ ] **Step 7: Task 3 커밋**

```bash
git add web/src/lib/yoloHttpProvider.ts web/src/lib/yoloHttpProvider.test.ts \
  web/src/lib/yoloDetectionServer.ts web/src/lib/yoloDetectionServer.test.ts \
  web/src/app/api/yolo-demo/infer/route.ts web/src/app/api/yolo-demo/infer/route.test.ts web/.env.example
git commit -m "feat: Vercel Preview YOLO worker adapter 추가"
```

---

### Task 4: Preview shadow 사용자 경험

**Files:**
- Modify: `web/src/app/gecko-detector/page.tsx`
- Create: `web/src/app/gecko-detector/page.test.tsx`
- Modify: `web/src/app/gecko-detector/_detector-demo.tsx`
- Modify: `web/src/app/gecko-detector/_detector-demo.test.tsx`

**Interfaces:**
- Consumes: server-only preview enable 판정.
- Produces: `DetectorDemo({ previewEnabled })`, Preview banner/processing copy, production fake copy 유지.

- [ ] **Step 1: Preview UX RED 테스트 작성**

```tsx
it('Preview에서 shadow 경계와 실제 worker 처리 문구를 표시한다', () => {
  const html = renderToStaticMarkup(<DetectorDemo previewEnabled />);
  expect(html).toContain('YOLO v2.1 보호 Preview');
  expect(html).toContain('production active 아님');
});
```

production/default render는 Preview 문구가 없고 기존 fake 설명을 유지한다. submit loading 상태는
Preview에서 `v2.1 worker에 안전하게 전달하고 있어.`를 사용한다.

- [ ] **Step 2: RED 확인**

Run: `cd web && npm test -- --run src/app/gecko-detector`

Expected: prop/banner가 없어 FAIL.

- [ ] **Step 3: 최소 UI 구현**

page server component는 `VERCEL_ENV==='preview' && YOLO_PREVIEW_ENABLED==='true'`만 boolean prop으로
내린다. token/URL은 client component/HTML에 전달하지 않는다. 배너는 research warning과 별도이며
결과 overlay의 model version/confidence/processed time 계약은 그대로 재사용한다.

- [ ] **Step 4: GREEN 확인**

Run: `cd web && npm test -- --run src/app/gecko-detector`

Expected: detector tests PASS.

- [ ] **Step 5: Task 4 커밋**

```bash
git add web/src/app/gecko-detector/page.tsx web/src/app/gecko-detector/page.test.tsx \
  web/src/app/gecko-detector/_detector-demo.tsx web/src/app/gecko-detector/_detector-demo.test.tsx
git commit -m "feat: YOLO v2.1 Preview 경계 표시"
```

---

### Task 5: Mac mini LaunchAgent 재현 도구

**Files:**
- Create: `scripts/manage_yolo_preview_worker.py`
- Create: `tests/test_manage_yolo_preview_worker.py`

**Interfaces:**
- Consumes: exact repo/checkpoint/env/runtime label.
- Produces: `install`, `status`, `uninstall` CLI와 secret-free plist.

- [ ] **Step 1: manager RED 테스트 작성**

```python
def test_plist_is_localhost_exact_repo_and_contains_no_secret(tmp_path):
    plist = build_plist(repo=tmp_path / "repo", env_file=tmp_path / "worker.env")
    encoded = plistlib.dumps(plist).decode()
    assert "127.0.0.1" in encoded and "8093" in encoded
    assert "YOLO_WORKER_TOKEN" not in encoded
    assert "com.petcam.yolo-preview-worker" in encoded
```

wrong hostname, dirty repo, non-40 HEAD, env mode !=0600, checkpoint identity mismatch, broad bind, overwrite
without explicit `--replace`, uninstall idempotency를 추가한다.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_manage_yolo_preview_worker.py`

Expected: manager module이 없어 FAIL.

- [ ] **Step 3: manager 구현**

plist ProgramArguments는 exact repo의 `/opt/homebrew/bin/uv run --group yolo-preview uvicorn
backend.yolo_preview_worker:app --host 127.0.0.1 --port 8093`다. secret은 mode 0600 env file을 읽는
작은 `/bin/zsh -lc 'set -a; source "$ENV_FILE"; ...'` wrapper에만 있고 plist에는 env file path만 둔다.
stdout/stderr는 `~/Library/Logs/petcam/yolo-preview-worker.{out,err}.log`다.

`install`은 expected host/repo HEAD/clean/checkpoint/env mode를 확인해 plist를 atomic replace한 뒤
`launchctl bootstrap gui/$UID`한다. `status`는 launchctl print와 authenticated localhost health를
분리 출력한다. `uninstall`은 bootout만 하고 env/checkpoint/repo를 삭제하지 않는다.

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/test_manage_yolo_preview_worker.py`

Expected: manager tests PASS.

- [ ] **Step 5: Task 5 커밋**

```bash
git add scripts/manage_yolo_preview_worker.py tests/test_manage_yolo_preview_worker.py
git commit -m "feat: Mac mini YOLO Preview LaunchAgent 관리 추가"
```

---

### Task 6: 전체 검증·독립 리뷰·Preview branch publish

**Files:**
- Modify as required by review findings only.

**Interfaces:**
- Consumes: Tasks 1-5.
- Produces: reviewed branch SHA safe for Mac mini and Vercel Preview.

- [ ] **Step 1: focused suites**

Run:

```bash
uv run pytest -q tests/test_yolo_preview_worker.py tests/test_manage_yolo_preview_worker.py
cd web && npm test -- --run src/lib/yoloHttpProvider.test.ts \
  src/lib/yoloDetectionServer.test.ts src/app/api/yolo-demo/infer/route.test.ts \
  src/app/gecko-detector
```

- [ ] **Step 2: full verification**

Run:

```bash
uv run pytest -q
cd web && npm test
cd web && npx tsc --noEmit
git diff --check
```

Expected: all PASS, warning/error 0 except documented skips.

- [ ] **Step 3: independent read-only review**

Review groups: Python input/auth/temp/model, Web preview/production gate, runtime manager. Critical/Important는
회귀 RED→GREEN으로 수정하고 focused/full suites를 다시 실행한다.

- [ ] **Step 4: publish branch**

```bash
git push -u origin codex/yolo-v21-preview-worker
```

ready PR은 만들되 main에 merge하지 않는다. GitHub/Vercel production deployment를 발생시키는 merge는
future holdout+Owner approval 전 금지다.

---

### Task 7: Mac mini exact runtime과 Cloudflare Preview tunnel

**Files/Runtime:**
- Remote worktree: `/Users/baek-end/petcam-lab-yolo-v21-preview`
- Remote env: `/Users/baek-end/Library/Application Support/petcam/yolo-preview-worker.env`
- Remote plist: `/Users/baek-end/Library/LaunchAgents/com.petcam.yolo-preview-worker.plist`
- Existing tunnel config: `/Users/baek-end/.cloudflared/config.yml`

**Interfaces:**
- Consumes: Task 6 exact branch SHA.
- Produces: authenticated `https://yolo-preview.tera-ai.uk/v1/*`.

- [ ] **Step 1: Mac mini worktree pin**

기존 `/Users/baek-end/petcam-lab`에서 fetch 후 새 worktree를 exact remote branch SHA로 만든다. 다른
worktree dirty state를 건드리지 않는다. `git rev-parse HEAD`, upstream, status를 기록한다.

- [ ] **Step 2: dependency와 actual checkpoint preflight**

Run on Mac mini:

```bash
/opt/homebrew/bin/uv sync --group yolo-preview
/opt/homebrew/bin/uv run --group yolo-preview python -c \
  'import ultralytics, torch; print(ultralytics.__version__, torch.backends.mps.is_available())'
shasum -a 256 /Users/baek-end/private-rba/yolo26n-owner-dataset-v21/attempt-20260810-owner-final-v1/runs/baseline-960-v21/weights/best.pt
```

Expected: `8.4.104`, `True`, exact SHA.

- [ ] **Step 3: secret/env와 LaunchAgent**

256-bit random token을 local temporary mode 0600 file에 생성해 stdout에 출력하지 않는다. Mac mini env
file을 mode 0600으로 만들고 checkpoint path/SHA/host/token/temp root를 기록한다. manager `install` 뒤
launchctl loaded, localhost authenticated health 200, unauthenticated 401을 확인한다.

- [ ] **Step 4: actual media smoke**

development artifact에서 공개 가능한 사진 1장과 5초 이하 영상 1개를 고르고 원본 경로나 GT를 로그에
출력하지 않는다. localhost response가 schema valid, model version exact, bbox normalized, temp residue 0,
로그 secret/path 0인지 확인한다. 결과는 GT 정확도 평가가 아니라 runtime smoke다.

- [ ] **Step 5: tunnel config 안전 변경**

config를 timestamp backup하고 기존 `cvat.tera-ai.uk` entry와 catch-all을 보존한 채 그 앞에
`yolo-preview.tera-ai.uk → http://127.0.0.1:8093`을 추가한다.

Run:

```bash
/opt/homebrew/bin/cloudflared tunnel ingress validate
/opt/homebrew/bin/cloudflared tunnel route dns \
  1e7a9232-2934-44de-a39b-aee1c6b54af7 yolo-preview.tera-ai.uk
```

기존 tunnel process/service의 실제 owner를 확인해 같은 방식으로만 reload한다. 새 중복 tunnel을 띄우지
않는다. CVAT 200, unauthenticated YOLO 401, authenticated health 200을 확인한다.

---

### Task 8: Branch-specific Vercel Preview와 브라우저 E2E

**Files:**
- Modify: `specs/next-session.md`
- Modify: `docs/superpowers/plans/2026-08-10-yolo-v21-preview-worker.md`
- Modify: `.claude/donts-audit.md`

**Interfaces:**
- Consumes: tunnel URL와 token, published branch.
- Produces: protected Vercel Preview URL and `PREVIEW_READY_SHADOW_ONLY` evidence.

- [ ] **Step 1: branch-specific Preview env**

Vercel CLI의 branch-specific Preview environment에만 다음을 입력한다. token은 stdin/file로 전달하고
command argv/log에 넣지 않는다.

```text
YOLO_PREVIEW_ENABLED=true
YOLO_WORKER_URL=https://yolo-preview.tera-ai.uk
YOLO_WORKER_TOKEN=(mode 0600 temporary file의 값을 stdin으로 전달)
```

Production environment에 세 값이 없거나 사용되지 않음을 별도로 확인한다.

- [ ] **Step 2: protected Preview deploy**

branch를 Vercel Preview로 배포하고 build `READY`를 기다린다. deployment ID/URL/commit SHA를 기록한다.
Deployment Protection이 302/인증 gate를 유지하는지 확인한다.

- [ ] **Step 3: HTTP canary**

보호 우회가 적용된 Preview에서 page 200, banner text, worker health proxy/actual infer 200을 확인한다.
invalid type 415, oversize 413, unauthenticated worker 401을 확인한다.

- [ ] **Step 4: Chrome E2E**

사용자가 연결한 Chrome의 Preview tab에서 실제 사진 drag/drop → bbox overlay → model version/confidence/
processed time/warning을 확인한다. 짧은 영상도 재생/scrub 시 sampled frame bbox를 확인한다. console error 0,
화면에 token/worker URL/checkpoint path 0인지 검사한다. 사용자 파일 업로드가 필요한 시점에는 사용자가
이미 이 작업에서 실제 demo media 전송을 승인한 범위만 사용한다.

- [ ] **Step 5: production negative canary**

`https://label.tera-ai.uk/gecko-detector` 200과 `POST /api/yolo-demo/infer` 503을 확인하고, 전후 Mac mini
worker request count가 증가하지 않았음을 확인한다. production deployment/alias를 promote하지 않는다.

- [ ] **Step 6: SOT와 최종 evidence commit**

next-session에 checkpoint 준비, development metrics, worker/tunnel/Preview deployment, actual media smoke,
production 503, future holdout/Owner gate를 기록한다. donts audit에 Preview-only/AGPL/production guard를
추가하고 계획 체크박스를 닫는다.

```bash
git add specs/next-session.md docs/superpowers/plans/2026-08-10-yolo-v21-preview-worker.md \
  .claude/donts-audit.md docs/handoff-prompts/2026-08-10-yolo-v21-preview-worker-handoff.md
git commit -m "docs: YOLO v2.1 보호 Preview 검증 기록"
git push
```

- [ ] **Step 7: 최종 상태 확인**

최종 보고에는 branch HEAD/upstream/status, PR URL, Mac mini hostname/service/repo HEAD/checkpoint SHA/actual
run, tunnel hostname, Vercel Preview ID, Web/Python/TypeScript/build, production 503, 남은 future holdout+Owner
승인 gate를 포함한다. worktree와 branch는 Preview 피드백을 위해 보존한다.

# YOLO Dataset v2.3 Labeling Assist Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dataset v2.3 warm-start checkpoint를 immutable release로 고정하고, 기존 v2.1을 보존한 채 보호 Vercel Preview의 라벨링 보조 bbox worker로 blue/green 배포한다.

**Architecture:** Mac mini의 학습 원본을 SHA-256으로 검증해 별도 read-only release directory에 복사하고, exact-SHA worktree의 별도 LaunchAgent가 localhost 8094에서 실행한다. 새 tunnel hostname과 branch-scoped Vercel Preview만 v2.3을 가리키며 production은 503, 기존 v2.1은 8093에서 계속 실행돼 Preview env 전환만으로 rollback한다.

**Tech Stack:** Python 3.12, FastAPI, Ultralytics 8.4.104, PyTorch MPS, OpenCV/Pillow/ffprobe, launchd, Cloudflare Named Tunnel, Next.js 14, TypeScript, Vitest, Vercel Preview

## Global Constraints

- Source checkpoint: `/Users/baek-end/private-rba/yolo26n-owner-dataset-v23/attempt-20260812-owner-v1/runs/warm-start/weights/best.pt`.
- Source checkpoint size: `5,400,581 bytes`.
- Source checkpoint SHA-256: `dbed3a2d8018a2eb6e4130de57d301414fcd6c9ba80aef8aafdaba55b19a6a34`.
- Public model version: `yolo26n-owner-dataset-v2.3-warm-start+dbed3a2d8018`.
- Inference threshold: `0.25`; fixed test TP 53 / FP 19 / FN 37, precision `0.7361111111111112`, recall `0.5888888888888889`.
- Evaluation tier is `development`; `future_holdout_required=true`.
- Allowed use is `labeling_bbox_assist_only`.
- GT 자동확정, 빈 이미지/게코 부재 판정, GME routing, R2 A/B 분류, 삭제, VLM skip, 행동명, 사건 묶기에 연결하지 않는다.
- Existing v2.1 runtime `com.petcam.yolo-preview-worker`, port 8093, hostname `yolo-preview.tera-ai.uk`, checkpoint, worktree, env를 수정하거나 중단하지 않는다.
- v2.3 runtime label은 `com.petcam.yolo-preview-worker-v23`, port는 `8094`, hostname은 `yolo-v23-preview.tera-ai.uk`다.
- Production `https://label.tera-ai.uk/api/yolo-demo/infer`는 항상 503이다.
- DB/R2 schema/data mutation은 0이어야 한다.
- Secret, local checkpoint path, private manifest content, 원문 GT는 stdout, Git, plist, HTTP response, Slack에 넣지 않는다.

## File Structure

- Create `backend/yolo_release.py`: release manifest schema, source/copy identity verification, atomic immutable copy.
- Create `scripts/create_yolo_v23_release.py`: Mac mini one-shot release creation CLI; secret이나 private GT를 출력하지 않는다.
- Modify `backend/yolo_preview_worker.py`: v2.3 manifest-derived identity/threshold/health/response.
- Modify `tests/test_yolo_preview_worker.py`: v2.3 worker identity, threshold, usage scope 회귀.
- Create `tests/test_yolo_release.py`: immutable release unit tests.
- Modify `scripts/manage_yolo_preview_worker.py`: v2.3 별도 label/port/release manifest 검증.
- Modify `tests/test_manage_yolo_preview_worker.py`: v2.3 plist/port/rollback isolation tests.
- Modify `web/src/app/gecko-detector/_detector-demo.tsx`: v2.3 assist-only banner와 0 detection 경고.
- Modify `web/src/app/gecko-detector/_detector-demo.test.tsx`: copy와 결과 상태 tests.
- Modify `web/src/app/gecko-detector/page.tsx` and `page.test.tsx`: preview-only v2.3 labeling-assist copy.
- Modify `web/src/lib/yoloHttpProvider.test.ts`: v2.3 version/result contract.
- Create `docs/handoff-prompts/2026-08-13-yolo-v23-labeling-assist-worker-handoff.md`: cross-host runtime manifest.
- Modify `docs/superpowers/plans/2026-08-13-yolo-v23-labeling-assist-worker.md`, `specs/next-session.md`, `.claude/donts-audit.md`: verified completion evidence.

---

### Task 1: Immutable v2.3 Release Manifest

**Files:**
- Create: `backend/yolo_release.py`
- Create: `scripts/create_yolo_v23_release.py`
- Test: `tests/test_yolo_release.py`

**Interfaces:**
- Consumes: source checkpoint path and fixed v2.3 provenance.
- Produces: `YoloReleaseManifest`, `load_release_manifest(path)`, `create_immutable_release(source, release_root) -> tuple[Path, Path]`.

- [x] **Step 1: Write manifest and copy RED tests**

```python
def test_create_release_copies_exact_checkpoint_and_writes_read_only_manifest(tmp_path):
    source = tmp_path / "source.pt"
    source.write_bytes(b"checkpoint")
    manifest = test_manifest(checkpoint_sha256=sha256(b"checkpoint"), checkpoint_size=10)
    checkpoint, manifest_path = create_immutable_release(
        source=source,
        release_root=tmp_path / "releases",
        manifest=manifest,
    )
    assert checkpoint.read_bytes() == b"checkpoint"
    assert stat.S_IMODE(checkpoint.stat().st_mode) == 0o444
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o444
    assert load_release_manifest(manifest_path) == manifest
```

같은 test file에 source size/SHA mismatch, existing release content mismatch, symlink source/release 거부,
temporary residue 0, threshold `0.25`, development/allowed-use/forbidden-use exact validation을 추가한다.

- [x] **Step 2: Run RED tests**

Run: `uv run pytest -q tests/test_yolo_release.py`

Expected: `ModuleNotFoundError: backend.yolo_release`.

- [x] **Step 3: Implement immutable release module**

```python
@dataclass(frozen=True, slots=True)
class YoloReleaseManifest:
    schema: str
    model_version: str
    checkpoint_sha256: str
    checkpoint_size: int
    candidate: str
    threshold: float
    evaluation_tier: str
    future_holdout_required: bool
    allowed_use: str
    fixed_test: FixedTestMetrics

def create_immutable_release(*, source: Path, release_root: Path,
                             manifest: YoloReleaseManifest) -> tuple[Path, Path]:
    verify_source_identity(source, manifest)
    target = release_root / f"{manifest.model_version}-{manifest.checkpoint_sha256}"
    return _write_release_directory(
        source=source,
        target=target,
        manifest=manifest,
    )
```

`_write_release_directory()`는 target의 sibling temporary directory에서 checkpoint copy, fsync, SHA/size
재검증, canonical JSON write, mode 0444를 완료한 뒤 target으로 atomic rename한다. CLI는 fixed v2.3
manifest를 만들고 최종 public model version, full SHA, size, release status만 JSON으로
출력한다. source/release absolute path는 출력하지 않는다.

- [x] **Step 4: Run GREEN tests**

Run: `uv run pytest -q tests/test_yolo_release.py`

Expected: all tests pass.

- [x] **Step 5: Commit Task 1**

```bash
git add backend/yolo_release.py scripts/create_yolo_v23_release.py tests/test_yolo_release.py
git commit -m "feat: YOLO v2.3 immutable release 추가"
```

### Task 2: Worker Identity, Threshold, and Health Scope

**Files:**
- Modify: `backend/yolo_preview_worker.py`
- Modify: `tests/test_yolo_preview_worker.py`

**Interfaces:**
- Consumes: `YOLO_RELEASE_MANIFEST`, `load_release_manifest()` and release `best.pt`.
- Produces: `WorkerConfig.manifest`, manifest-derived model invocation and authenticated `/v1/health`.

- [x] **Step 1: Write v2.3 RED tests**

```python
def test_health_exposes_v23_assist_identity_without_local_path(tmp_path):
    config = v23_worker_config(tmp_path)
    with TestClient(create_app(config=config, runner=FakeRunner())) as client:
        response = client.get("/v1/health", headers=auth(config.token))
    assert response.json() == {
        "status": "ok",
        "model_version": "yolo26n-owner-dataset-v2.3-warm-start+dbed3a2d8018",
        "device": "mps",
        "checkpoint_sha256": V23_CHECKPOINT_SHA256,
        "threshold": 0.25,
        "development_only": True,
        "usage_scope": "labeling_bbox_assist_only",
    }
    assert str(config.checkpoint_path) not in response.text
```

추가 RED: manifest/checkpoint mismatch startup failure, threshold mismatch startup failure,
`YoloModelRunner.predict_image()`가 `conf=config.manifest.threshold`를 사용, 0 detection success response가
빈 frames가 아닌 detection 0 frame을 유지, warning에 `게코 없음 판정 아님` 포함.

- [x] **Step 2: Run RED tests**

Run: `uv run pytest -q tests/test_yolo_preview_worker.py`

Expected: health shape/model identity assertions fail.

- [x] **Step 3: Implement manifest-derived worker**

`WorkerConfig.from_env()`는 manifest를 먼저 읽고 sibling `best.pt`를 exact identity로 검증한다.
`YoloModelRunner` constructor는 threshold를 받아 predict call의 `conf`에 전달한다. health와 inference
response는 manifest identity를 사용하며 module-level v2.1 constants는 제거한다.

- [x] **Step 4: Run worker GREEN and regression tests**

Run: `uv run pytest -q tests/test_yolo_preview_worker.py tests/test_yolo_release.py`

Expected: all tests pass.

- [x] **Step 5: Commit Task 2**

```bash
git add backend/yolo_preview_worker.py tests/test_yolo_preview_worker.py
git commit -m "feat: YOLO v2.3 worker identity 고정"
```

### Task 3: v2.3 Labeling-Assist UI Boundary

**Files:**
- Modify: `web/src/app/gecko-detector/_detector-demo.tsx`
- Modify: `web/src/app/gecko-detector/_detector-demo.test.tsx`
- Modify: `web/src/app/gecko-detector/page.tsx`
- Modify: `web/src/app/gecko-detector/page.test.tsx`
- Modify: `web/src/lib/yoloHttpProvider.test.ts`

**Interfaces:**
- Consumes: existing `GeckoDetectionResult.frames[].detections` and preview flag.
- Produces: v2.3 development-only banner and explicit zero-detection warning.

- [x] **Step 1: Write UI RED tests**

```tsx
it('v2.3 Preview에서 labeling assist와 미검출 안전 경계를 표시한다', async () => {
  const html = renderToStaticMarkup(<DetectorDemo previewEnabled />);
  expect(html).toContain('Dataset v2.3 라벨링 보조');
  expect(html).toContain('production 자동판정 모델이 아니야');
  expect(html).toContain('박스가 없어도 게코가 없다는 뜻은 아니야');
});
```

response frames의 detection 합계가 0인 component test는
`후보 박스를 찾지 못했어. 게코 없음 판정이 아니니 직접 확인해줘.`를 기대한다. production page test는
v2.3 Preview copy가 HTML에 없음을 계속 확인한다.

- [x] **Step 2: Run UI RED tests**

Run: `cd web && npm test -- src/app/gecko-detector/_detector-demo.test.tsx src/app/gecko-detector/page.test.tsx src/lib/yoloHttpProvider.test.ts`

Expected: v2.1 copy and missing zero-detection notice cause failures.

- [x] **Step 3: Implement minimal copy/result-state changes**

Preview banner만 v2.3 assist copy로 바꾸고,
`result.frames.reduce((sum, frame) => sum + frame.detections.length, 0) === 0`일 때 warning card를
렌더한다. 업로드, provider, bbox overlay, contribution consent 동작은 바꾸지 않는다.

- [x] **Step 4: Run UI GREEN and TypeScript tests**

Run: `cd web && npm test -- src/app/gecko-detector/_detector-demo.test.tsx src/app/gecko-detector/page.test.tsx src/lib/yoloHttpProvider.test.ts && npx tsc --noEmit`

Expected: focused tests and TypeScript pass.

- [x] **Step 5: Commit Task 3**

```bash
git add web/src/app/gecko-detector/_detector-demo.tsx web/src/app/gecko-detector/_detector-demo.test.tsx web/src/app/gecko-detector/page.tsx web/src/app/gecko-detector/page.test.tsx web/src/lib/yoloHttpProvider.test.ts
git commit -m "feat: YOLO v2.3 라벨링 보조 경계 표시"
```

### Task 4: Parallel v2.3 LaunchAgent Manager

**Files:**
- Modify: `scripts/manage_yolo_preview_worker.py`
- Modify: `tests/test_manage_yolo_preview_worker.py`

**Interfaces:**
- Consumes: exact clean runtime repo, release manifest, mode 0600 env.
- Produces: install/status/uninstall for `com.petcam.yolo-preview-worker-v23` on `127.0.0.1:8094`.

- [x] **Step 1: Write isolation RED tests**

```python
def test_v23_plist_uses_distinct_label_port_and_never_mentions_v21_service(tmp_path):
    plist = build_plist(repo=tmp_path / "repo", env_file=tmp_path / "worker.env")
    encoded = plistlib.dumps(plist).decode()
    assert LABEL == "com.petcam.yolo-preview-worker-v23"
    assert "127.0.0.1" in encoded and "8094" in encoded
    assert "com.petcam.yolo-preview-worker.plist" not in encoded
    assert "YOLO_WORKER_TOKEN" not in encoded
```

추가 RED: release manifest/checkpoint mode 0444, exact branch HEAD/clean, env 0600, status health full SHA and
threshold, uninstall only v23 target, replace bounded retry.

- [x] **Step 2: Run RED tests**

Run: `uv run pytest -q tests/test_manage_yolo_preview_worker.py`

Expected: v2.1 label/8093 assertions fail.

- [x] **Step 3: Implement v2.3 manager profile**

`LABEL`과 `PORT`를 v2.3 값으로 바꾸고 install validation이 `YOLO_RELEASE_MANIFEST` sibling checkpoint를
검증하게 한다. plist target/log filenames도 v23 label에서 파생한다. v2.1 target path를 읽거나 bootout하지
않는다.

- [x] **Step 4: Run manager GREEN tests**

Run: `uv run pytest -q tests/test_manage_yolo_preview_worker.py tests/test_yolo_preview_worker.py tests/test_yolo_release.py`

Expected: all tests pass.

- [x] **Step 5: Commit Task 4**

```bash
git add scripts/manage_yolo_preview_worker.py tests/test_manage_yolo_preview_worker.py
git commit -m "feat: YOLO v2.3 병렬 LaunchAgent 관리 추가"
```

### Task 5: Full Verification and Independent Review

**Files:**
- Modify only files required by verified review findings.

**Interfaces:**
- Consumes: Tasks 1-4 implementation.
- Produces: reviewed exact SHA with Critical/Important findings 0.

- [x] **Step 1: Run full local verification**

```bash
uv run pytest -q
cd web && npm test
cd web && npx tsc --noEmit
cd web && npm run build
git diff --check
```

Expected: Python/Web/TypeScript/build pass and whitespace errors 0.

- [x] **Step 2: Request independent review**

Review scope는 model provenance/immutable copy, v2.1 isolation/rollback, production hard guard, zero-detection
copy, secret/path redaction, DB/R2/GT prohibited paths다. Reviewer에게 변경하지 말고 Critical/Important만
근거와 파일/라인으로 보고하게 한다.

- [x] **Step 3: Resolve findings with TDD**

각 valid finding마다 focused failing test를 먼저 추가하고 failure를 확인한 뒤 최소 수정한다. 세 번의
수정/검증 loop 후에도 남는 오류는 목록화하고 배포를 중단한다.

- [x] **Step 4: Re-run full verification and record exact SHA**

Run the Step 1 command block again and `git status --short --branch && git rev-parse HEAD`.

- [x] **Step 5: Push reviewed branch**

```bash
git push -u origin codex/yolo-v23-labeling-assist-worker
```

### Task 6: Mac mini Immutable Release and Parallel Worker Canary

**Runtime:**
- Host: `baeg-endeuui-Macmini.local`
- New worktree: `/Users/baek-end/petcam-lab-yolo-v23-assist`
- Release root: `/Users/baek-end/Library/Application Support/petcam/models`
- Env: `/Users/baek-end/Library/Application Support/petcam/yolo-preview-worker-v23.env`
- LaunchAgent: `/Users/baek-end/Library/LaunchAgents/com.petcam.yolo-preview-worker-v23.plist`

**Interfaces:**
- Consumes: Task 5 exact pushed SHA and verified handoff manifest.
- Produces: localhost v2.3 health/inference on 8094 while v2.1 remains healthy on 8093.

- [x] **Step 1: Verify handoff and remote preflight**

Run local handoff validator and record literal `HANDOFF_OK`. On Mac mini record hostname, existing v2.1 loaded
state/health, source checkpoint size/SHA, and training manifest development/future-holdout flags without printing
private paths or tokens.

- [x] **Step 2: Create immutable release**

Run the release CLI against the fixed source and release root. Verify final checkpoint/manifest mode 0444,
checkpoint full SHA, source SHA unchanged, and no temporary residue.

- [x] **Step 3: Create exact-SHA runtime worktree**

Fetch the pushed branch from the existing Mac mini clone, create the new worktree at exact Task 5 SHA, and verify
HEAD exact, upstream/status, clean tree. Run `uv sync --group yolo-preview` and confirm Ultralytics `8.4.104`, MPS
available.

- [x] **Step 4: Install isolated env and LaunchAgent**

Create a new 256-bit token without stdout, write v23 env mode 0600, run manager install without touching v2.1,
and verify `launchctl print`, localhost unauthenticated 401, authenticated health 200/full SHA/threshold/scope.

- [x] **Step 5: Run actual image and short-video canary**

Use development artifacts only for runtime smoke. Verify schema, normalized boxes, public model version, threshold,
temp residue 0, log secret/path 0. Detection count is not an accuracy or adoption claim.

- [x] **Step 6: Verify v2.1 remains unchanged**

Re-check v2.1 label loaded, port 8093 listener, exact old health SHA/model version, and actual inference success.

### Task 7: Tunnel, Protected Preview, and Rollback Canary

**Runtime:**
- Tunnel config: `/Users/baek-end/Library/Application Support/petcam/cloudflared-v23/config.yml`
- New hostname: `yolo-v23-preview.tera-ai.uk`
- Existing protected Vercel Preview branch: `codex/yolo-v23-labeling-assist-worker`

**Interfaces:**
- Consumes: healthy localhost v2.3 worker.
- Produces: `PREVIEW_READY_LABELING_ASSIST_ONLY` with proven v2.1 rollback.

- [x] **Step 1: Add isolated tunnel ingress**

Backup config, preserve `yolo-preview.tera-ai.uk`, `cvat.tera-ai.uk`, catch-all order, insert only
`yolo-v23-preview.tera-ai.uk -> http://127.0.0.1:8094`, validate ingress, create DNS route, reload the single existing
tunnel process using its current owner/mechanism.

- [x] **Step 2: Verify remote boundary**

Check existing CVAT status, v2.1 unauth/auth health, v2.3 unauthenticated 401, v2.3 authenticated 200 with exact
SHA/threshold/scope. No token appears in shell history/output.

- [x] **Step 3: Configure branch-scoped protected Preview**

Set `YOLO_PREVIEW_ENABLED=true`, v2.3 worker URL, and token only for the v2.3 branch Preview. Deploy exact branch
SHA, wait for READY, and verify deployment protection remains enabled. Do not alias/promote to production.

- [x] **Step 4: Browser canary**

Using the signed-in Chrome session only if needed, upload one image and one short video. Verify candidate bbox,
model version, threshold, processed time, development-only/absence warnings, overlay toggle/video sync, console errors
0, secret/path exposure 0. Exercise a safe 0-detection fake/fixture path in Preview tests rather than interpreting a
real miss as absence.

- [x] **Step 5: Production negative canary**

Verify `label.tera-ai.uk/gecko-detector` 200, production infer 503, and v2.3 worker request count unchanged across
the production POST. Confirm DB/R2/GT/skip/delete/GME/VLM mutations 0 from code path and deployment logs.

- [x] **Step 6: Prove rollback and restore v2.3**

Change the protected Preview branch env back to existing v2.1 URL/token, redeploy, and verify v2.1 health and actual
inference. Then restore v2.3 URL/token, redeploy, and repeat exact v2.3 browser health/inference canary. Both workers
remain installed and immutable artifacts remain unchanged.

### Task 8: Evidence, Final Verification, and Slack Share

**Files:**
- Modify: `docs/superpowers/plans/2026-08-13-yolo-v23-labeling-assist-worker.md`
- Modify: `specs/next-session.md`
- Modify: `.claude/donts-audit.md`
- Add: `docs/handoff-prompts/2026-08-13-yolo-v23-labeling-assist-worker-handoff.md`

**Interfaces:**
- Consumes: verified local/runtime/deployment evidence.
- Produces: tracked audit trail and one Slack completion message.

- [x] **Step 1: Record evidence without secrets**

Record exact code SHA, branch/upstream/status, test counts, release full SHA/size/modes, runtime hostname/label/port/
HEAD/health, tunnel hostname, Preview deployment ID/URL, browser canary, production 503, rollback round trip, and
remaining development-only/future-holdout gate.

#### 2026-08-13 execution evidence

- Reviewed runtime code SHA: `dc11b2d68723f9473100599da481c390561485ef`; independent review
  Critical/Important/Minor `0/0/0`.
- Local regression: Python `1266 passed, 5 skipped`; Web `121 files / 1026 passed`; TypeScript and Vercel Next
  production build passed.
- Mac mini runtime: `baeg-endeuui-Macmini.local`, clean exact-SHA worktree, Ultralytics `8.4.104`, MPS available,
  `com.petcam.yolo-preview-worker-v23` on `127.0.0.1:8094`.
- Immutable release: checkpoint SHA-256
  `dbed3a2d8018a2eb6e4130de57d301414fcd6c9ba80aef8aafdaba55b19a6a34`, size `5,400,581`, checkpoint and
  manifest mode `0444`; source SHA/size unchanged; temp/log token/private-source-path residue `0`.
- Existing v2.1 stayed loaded on 8093 with SHA
  `9ba825697693a0e84078a32120f64ea4e9da6a20bb50b9636403c9409200036e` and clean worktree.
- Runtime deviation: the existing v2.1/CVAT tunnel is a root LaunchDaemon and could not be safely reloaded without
  interactive sudo. To preserve it, v2.3 uses a separate local-config Named Tunnel and user LaunchAgent. Remote
  unauth health is `401`, auth health is exact v2.3 SHA/threshold/scope `200`; v2.1 and CVAT remain `200`.
- Final protected Preview: `dpl_5i4EL3rcpFTMjXnZmKffvuG3ik45`,
  `https://petcam-eftt5b9uq-ssoo100s-projects.vercel.app`; branch-only sensitive env, production YOLO env keys `0`.
- Canary: Preview image `1 frame / 3 detections`, generated 4-second video `20 frames / 60 detections`; browser UI
  image/video bbox rects, actual model version, threshold `0.25`, development-only and not-training-data copy,
  console error/warn `0`. Black-image miss produced rect `0` and explicit `게코 없음 판정이 아니니 직접 확인`
  warning.
- Rollback round trip: protected Preview switched to v2.1 and returned exact v2.1 model with no pre-result v2.3 or
  threshold claim, then restored to exact v2.3 and repeated actual inference successfully.
- Production negative: `label.tera-ai.uk/gecko-detector` `200`, production inference `503`, v2.3 infer count
  `6 -> 6`; DB/R2/GT/GME/delete/VLM code paths and data were not changed.
- Scope remains `development-only / labeling_bbox_assist_only`; fixed-test recall `58.9%` is never absence evidence,
  and future holdout plus separate Owner approval remain required for any production adoption.

- [ ] **Step 2: Run verification-before-completion**

Re-run focused/full tests as proportional final verification, remote v2.1/v2.3 health, protected Preview canary,
production negative canary, and `git diff --check`. Do not reuse earlier output for final claims.

- [ ] **Step 3: Commit and push evidence**

```bash
git add docs/superpowers/plans/2026-08-13-yolo-v23-labeling-assist-worker.md specs/next-session.md .claude/donts-audit.md docs/handoff-prompts/2026-08-13-yolo-v23-labeling-assist-worker-handoff.md
git commit -m "docs: YOLO v2.3 Preview 배포 검증 기록"
git push
```

- [ ] **Step 4: Share completion in Slack**

Use the project’s existing deployment/AI engineering channel found through Slack search. Send one concise Korean
message containing Preview-only status, public model version and SHA prefix, threshold, fixed-test precision/recall,
Preview URL, canary/rollback success, production 503, and explicit prohibitions. Do not include token, checkpoint
path, private manifest, raw GT, or local host paths. If no unambiguous existing channel is found, stop only the Slack
write and report the channel ambiguity; do not guess a recipient.

- [ ] **Step 5: Final status**

Report `PREVIEW_READY_LABELING_ASSIST_ONLY`, not production adoption. Include Slack permalink, exact final HEAD,
upstream, tracked/untracked status, Preview URL, rollback target, and future holdout requirement.

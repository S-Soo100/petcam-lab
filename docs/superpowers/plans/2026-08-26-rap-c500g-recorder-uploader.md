# RAP C500G Recorder/Uploader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** C500G 3대의 60초 test와 매일 20:00~08:00 KST production 영상을 검증 가능한 bundle로 만들고 Mac mini 로컬 및 R2에 이중 보관한다.

**Architecture:** 순수 naming/schedule/manifest 모듈과 FFmpeg capture adapter를 분리하고, 완성 bundle을 local manifest scan 기반의 bounded uploader가 처리한다. R2는 multipart upload 후 HEAD size/hash를 검증하며 manifest를 마지막에 올리고, 별도 Supabase 원장에 idempotent upsert한다.

**Tech Stack:** Python 3.12, FFmpeg/ffprobe, boto3 TransferManager, Supabase, pytest, moto, launchd

**Spec:** `docs/superpowers/specs/2026-08-26-rap-c500g-r2-recording-design.md`

## Global Constraints

- Python은 3.12 이상이며 패키지 관리는 `uv`만 쓴다.
- camera key는 `cam01|cam02|cam03`, mode는 `test|production` allowlist만 허용한다.
- production은 KST 20:00~익일 08:00의 30분 slot이고 night는 시작일이다.
- test/production R2 key는 spec §7 형식을 정확히 따른다.
- video는 `video.part.mp4`에서 검증 성공 후 `video.mp4`로 atomic rename한다.
- RTSP credential·전체 URL·R2/Supabase secret은 로그, manifest, DB에 넣지 않는다.
- R2 object metadata의 SHA-256과 HEAD ContentLength가 일치해야 한다.
- video/thumbnail/log 검증 후 manifest를 마지막에 업로드한다.
- local bundle은 자동 삭제하지 않는다.
- 기존 `camera_clips`, `motion_clips`, GME, 행동 GT와 기존 R2 prefix를 수정하지 않는다.
- 실제 Mac mini launchd 설치는 tracked commit과 `HANDOFF_OK` 뒤에만 진행한다.
- 커밋은 Owner가 별도로 명시 승인한 뒤에만 한다.

## File Map

- `backend/rap_c500g_types.py`: immutable domain types와 상태 enum.
- `backend/rap_c500g_naming.py`: allowlist, KST slot, local/R2 상대경로.
- `backend/rap_c500g_manifest.py`: artifact hash, manifest build/read/atomic write.
- `backend/rap_c500g_capture.py`: env camera config, sanitizer, FFmpeg/ffprobe/thumbnail, atomic capture.
- `backend/rap_c500g_r2.py`: multipart upload, HEAD integrity, manifest-last.
- `backend/rap_c500g_repository.py`: Supabase idempotent row sync.
- `backend/rap_c500g_service.py`: concurrent camera capture, durable upload scan, retry, scheduler.
- `backend/rap_c500g_main.py`: `test`, `run`, `sync` CLI.
- `migrations/2026-08-26_rap_c500g_recordings.sql`: 별도 원장/RLS/index.
- `deploy/launchd/com.teraai.rap-c500g-recorder.plist.template`: Mac mini service template.
- `scripts/render_rap_c500g_launchd.py`: secret 없는 plist 렌더러.

---

### Task 1: Naming·schedule·domain 계약

**Files:**
- Create: `backend/rap_c500g_types.py`
- Create: `backend/rap_c500g_naming.py`
- Create: `tests/test_rap_c500g_naming.py`

**Interfaces:**
- Produces: `RecordingMode`, `CameraKey`, `SegmentIdentity`, `BundlePaths`.
- Produces: `observation_night(datetime) -> date`, `current_or_next_slot(datetime) -> SlotDecision | None`, `build_bundle_paths(root, identity) -> BundlePaths`.

- [ ] **Step 1: RED — allowlist와 KST 관찰일 테스트 작성**

  `2026-08-27T00:15+09:00`가 `night=2026-08-26`이고, 19:59에는 slot이 없으며,
  `cam/01`, `..`, 잘못된 mode가 `ValueError`인 literal fixture를 작성한다.

- [ ] **Step 2: RED 확인**

  Run: `uv run pytest tests/test_rap_c500g_naming.py -q`
  Expected: 새 모듈 import 실패.

- [ ] **Step 3: GREEN — 최소 immutable type과 경로 구현**

  `c500g` 버킷의 Test key는 `test/{run}/{camera}/{YYYYMMDDTHHMMSS+0900}`,
  production key는 `recordings/{camera}/night={date}/{timestamp}`를 반환한다.

- [ ] **Step 4: GREEN 확인**

  Run: `uv run pytest tests/test_rap_c500g_naming.py -q`
  Expected: PASS.

### Task 2: 안전 manifest와 로그 sanitizer

**Files:**
- Create: `backend/rap_c500g_manifest.py`
- Create: `tests/test_rap_c500g_manifest.py`

**Interfaces:**
- Produces: `sha256_file(path: Path) -> str`, `sanitize_text(text: str, secrets: Sequence[str]) -> str`.
- Produces: `build_local_manifest(identity, media, artifacts) -> dict[str, object]`, `atomic_write_manifest(path, payload) -> None`, `read_manifest(path) -> dict[str, object]`.

- [ ] **Step 1: RED — credential 치환·schema·원자 기록 테스트 작성**

  literal RTSP URL, query token, known secret가 결과에 없고 host/camera/error class는 남는지 검사한다.
  manifest에 절대경로와 URL key가 들어오면 거부하고 `.part`가 남지 않는지 검사한다.

- [ ] **Step 2: RED 확인**

  Run: `uv run pytest tests/test_rap_c500g_manifest.py -q`
  Expected: 새 모듈 import 실패.

- [ ] **Step 3: GREEN — streaming SHA와 schema v1 구현**

  1 MiB chunk로 SHA-256을 계산하고 `os.replace`로 JSON을 원자 기록한다. JSON은 UTF-8,
  stable key order, newline 1개로 직렬화한다.

- [ ] **Step 4: GREEN 확인과 secret mutation check**

  Run: `uv run pytest tests/test_rap_c500g_manifest.py -q`
  Expected: PASS; sanitizer 제거 시 literal secret test가 실패해야 한다.

### Task 3: FFmpeg capture bundle

**Files:**
- Create: `backend/rap_c500g_capture.py`
- Create: `tests/test_rap_c500g_capture.py`
- Modify: `.env.example`
- Modify: `docs/ENV.md`

**Interfaces:**
- Produces: `load_camera_configs(environ) -> tuple[CameraConfig, ...]`.
- Produces: `capture_segment(config, identity, paths, duration_sec, runner=subprocess.run) -> CaptureResult`.
- Consumes: Task 1 `BundlePaths`, Task 2 sanitizer/manifest.

- [ ] **Step 1: RED — env fail-closed와 command/atomic behavior 테스트 작성**

  fake runner가 `video.part.mp4`와 synthetic ffprobe JSON을 만들게 하고 성공 시 final mp4/thumbnail/log/manifest가
  생기는지 검사한다. 실패 종료코드에서는 final mp4와 완료 manifest가 없어야 한다. argv/log/manifest에
  password가 없다는 결과를 검사하되, subprocess boundary의 입력 URL 자체에는 assertion하지 않는다.

- [ ] **Step 2: RED 확인**

  Run: `uv run pytest tests/test_rap_c500g_capture.py -q`
  Expected: 새 모듈 import 실패.

- [ ] **Step 3: GREEN — subprocess 경계와 검증 구현**

  FFmpeg는 TCP RTSP, `-t`, `-c copy`, MP4 faststart를 사용한다. ffprobe JSON에서 HEVC/H264 video stream,
  양수 duration·width·height·fps를 검증하고 thumbnail은 별도 FFmpeg 호출로 JPEG를 만든다.
  timeout은 `duration_sec + 90`이며 timeout 시 TERM/KILL을 적용한다.

- [ ] **Step 4: GREEN 확인**

  Run: `uv run pytest tests/test_rap_c500g_capture.py -q`
  Expected: PASS.

### Task 4: Multipart R2 manifest-last uploader

**Files:**
- Create: `backend/rap_c500g_r2.py`
- Create: `tests/test_rap_c500g_r2.py`

**Interfaces:**
- Produces: `R2BundleUploader(client, bucket, transfer_config)`.
- Produces: `upload_bundle(bundle_dir: Path, manifest: Mapping) -> UploadResult`.
- Consumes: manifest artifact size/SHA와 spec §7 key.

- [ ] **Step 1: RED — moto로 idempotency·HEAD·manifest-last 테스트 작성**

  upload order를 기록하는 thin client proxy로 manifest가 마지막인지 검사한다. 같은 size/hash object는 skip,
  다른 hash object는 `IntegrityConflict`, video upload 실패 시 manifest 부재를 검사한다.

- [ ] **Step 2: RED 확인**

  Run: `uv run pytest tests/test_rap_c500g_r2.py -q`
  Expected: 새 모듈 import 실패.

- [ ] **Step 3: GREEN — TransferConfig와 HEAD 검증 구현**

  threshold/chunk 16 MiB, multipart concurrency 2, thread 사용. `upload_file` ExtraArgs에 ContentType과
  lower-case metadata를 넣고 HEAD `ContentLength`/`Metadata.sha256`을 비교한다.

- [ ] **Step 4: GREEN 확인**

  Run: `uv run pytest tests/test_rap_c500g_r2.py -q`
  Expected: PASS.

### Task 5: DB 원장과 재동기화 repository

**Files:**
- Create: `migrations/2026-08-26_rap_c500g_recordings.sql`
- Create: `backend/rap_c500g_repository.py`
- Create: `tests/test_rap_c500g_recordings_migration.py`
- Create: `tests/test_rap_c500g_repository.py`
- Modify: `docs/DATABASE.md`

**Interfaces:**
- Produces: `RapRecordingRepository.upsert_capture(manifest)`, `mark_uploading(bundle_id, attempts)`, `mark_uploaded(manifest, uploaded_at)`, `mark_failed(bundle_id, code)`.

- [ ] **Step 1: RED — migration 보안·상태 constraint 테스트 작성**

  table/RLS/revoke, mode/camera/status constraints, bundle unique, 기존 table 변경문 0건을 SQL parser fixture로 검사한다.

- [ ] **Step 2: RED 확인**

  Run: `uv run pytest tests/test_rap_c500g_recordings_migration.py tests/test_rap_c500g_repository.py -q`
  Expected: migration/module 부재 실패.

- [ ] **Step 3: GREEN — forward-only migration과 service-role adapter 구현**

  repository는 `.table('rap_c500g_recordings').upsert(..., on_conflict='bundle_id')`를 쓰며 credential이나
  absolute path를 payload/error에 넣지 않는다. 업로드 완료 전에 `uploaded`를 허용하지 않는 check를 둔다.

- [ ] **Step 4: GREEN 확인**

  Run: `uv run pytest tests/test_rap_c500g_recordings_migration.py tests/test_rap_c500g_repository.py -q`
  Expected: PASS.

### Task 6: Scheduler·durable upload scan·CLI

**Files:**
- Create: `backend/rap_c500g_service.py`
- Create: `backend/rap_c500g_main.py`
- Create: `tests/test_rap_c500g_service.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces CLI: `uv run python -m backend.rap_c500g_main test --duration 60`, `uv run python -m backend.rap_c500g_main run`, `uv run python -m backend.rap_c500g_main sync`.
- Produces: `scan_uploadable_bundles(root)`, `run_test_capture`, `run_production_scheduler`, `sync_pending`.

- [ ] **Step 1: RED — 3-camera concurrency·restart·queue 테스트 작성**

  fake clock/capture/uploader로 세 카메라 start skew가 scheduler 호출 기준 100 ms 이내인지, 00:15 재시작이
  전날 night의 00:30까지 partial인지, upload failure가 다음 capture를 막지 않는지 검사한다.

- [ ] **Step 2: RED 확인**

  Run: `uv run pytest tests/test_rap_c500g_service.py -q`
  Expected: 새 모듈 import 실패.

- [ ] **Step 3: GREEN — ThreadPoolExecutor와 manifest scan 구현**

  capture pool size 3, upload pool 기본 1로 분리한다. `sync`는 local `manifest.json`을 정렬 scan하고
  R2 완료가 아닌 bundle만 같은 key로 처리한다. SIGTERM에서 새 작업을 중단하고 현재 capture를 정리한다.

- [ ] **Step 4: GREEN 확인과 CLI help smoke**

  Run: `uv run pytest tests/test_rap_c500g_service.py -q && uv run python -m backend.rap_c500g_main --help`
  Expected: PASS와 secret 없는 help.

### Task 7: launchd 렌더러와 운영 handoff

**Files:**
- Create: `deploy/launchd/com.teraai.rap-c500g-recorder.plist.template`
- Create: `scripts/render_rap_c500g_launchd.py`
- Create: `tests/test_render_rap_c500g_launchd.py`
- Create: `docs/runbooks/rap-c500g-recorder.md`

**Interfaces:**
- Produces: `render_plist(repo, env_file, local_root, log_dir) -> bytes`.

- [ ] **Step 1: RED — plist에 credential 값이 없고 env file 경로만 있는 테스트 작성**
- [ ] **Step 2: RED 확인**

  Run: `uv run pytest tests/test_render_rap_c500g_launchd.py -q`
  Expected: 새 렌더러 import 실패.

- [ ] **Step 3: GREEN — KeepAlive/WorkingDirectory/ProgramArguments/로그 경로 렌더링 구현**

  plist는 `/usr/bin/env`, `uv`, `run`, `python`, `-m`, `backend.rap_c500g_main`, `run`만 실행하고 `.env` 내용을 embed하지 않는다.
  runbook에는 설치 전 free-space, camera ping/RTSP 10초 probe, test canary, rollback(unload만, 파일 삭제 없음)을 적는다.

- [ ] **Step 4: GREEN 확인**

  Run: `uv run pytest tests/test_render_rap_c500g_launchd.py -q`
  Expected: PASS.

- [ ] **Step 5: handoff gate 준비**

  Owner의 별도 커밋 승인 뒤 40자리 SHA를 포함한 manifest를 만들고
  `uv run python scripts/verify_agent_handoff.py --manifest <absolute-path>`에서 `HANDOFF_OK`를 확인한다.
  그 전에는 Mac mini에 plist를 설치하지 않는다.

### Task 8: 통합·보안·실제 test prefix canary

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `specs/next-session.md`
- Modify: `.claude/donts-audit.md`

- [ ] **Step 1: 전체 Python 회귀검증**

  Run: `uv run pytest -q`
  Expected: 기준선 포함 전부 PASS, 기존 5 skip 외 신규 skip 없음.

- [ ] **Step 2: secret/path 정적 검사**

  Run: `rg -n "rtsp://[^*]|RAP_CAM_C500G_RTSP_PASSWORD=.+|R2_(C500G_)?SECRET_ACCESS_KEY=.+|SUPABASE_SERVICE_ROLE_KEY=.+" backend tests migrations deploy docs .env.example`
  Expected: 실제 secret/전체 credential URL 0건; 문서의 변수명·마스킹 예시는 수동 확인.

- [ ] **Step 3: synthetic 3-camera 60초 dry run**

  fake RTSP fixture에서 3개 local bundle, artifact 12개, completed manifest 3개를 검증한다.

- [ ] **Step 4: 실제 R2 bounded canary**

  전용 credential preflight 후 `c500g` 버킷의 `test/<new-run-id>/`에만 3 bundle을 쓰고 HEAD size/hash와 manifest-last,
  DB 3 row를 확인한다. 원본과 canary object를 삭제하지 않는다.

- [ ] **Step 5: 문서 상태 갱신**

  실제 검증값과 미실행 gate를 사실대로 기록하고 `IMPLEMENTED_UNVERIFIED`, `PREVIEW_READY`,
  `DEPLOYED_VERIFIED`를 구분한다.

# RAP C500G Capture-First Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mac mini가 매일 20:00~08:00 KST에 C500G 3대의 30분 HEVC 원본을 우선 녹화해 즉시 R2에 백업하고, 08:00 이후 전체 검증·썸네일·manifest·DB 동기화를 독립 완료하게 한다.

**Architecture:** 기존 `com.teraai.rap-c500g-manager` 단일 launchd 서비스와 기존 RAP 경로/R2/DB 계약을 유지한다. 서비스 내부에 durable capture-first pipeline을 추가해 capture executor, 원본 upload executor(concurrency 1), daytime finalize executor(concurrency 3)를 분리하고, SQLite 상태를 기준으로 재부팅 후에도 멱등 재개한다.

**Tech Stack:** Python 3.12, FFmpeg/ffprobe, SQLite WAL, boto3/R2, Supabase, FastAPI, launchd, pytest, moto

**Spec:** `docs/superpowers/specs/2026-09-03-rap-c500g-capture-first-pipeline-design.md`

## Global Constraints

- production owner는 `com.teraai.rap-c500g-manager` 하나뿐이며 새 daemon/service label을 만들지 않는다.
- production slot은 KST `20:00`부터 다음 날 `07:30`까지 30분 간격이며, 카메라는 `cam01`, `cam02`, `cam03`, segment는 30분 고정이다.
- 야간에는 전체 decode와 thumbnail 생성을 0건으로 유지한다.
- C500G HEVC bitstream은 `-c copy -tag:v hvc1`로만 저장하며 픽셀 재인코딩을 하지 않는다.
- 빠른 검사를 통과한 `video.mp4`만 R2에 먼저 올리고, 최종 `manifest.json`은 전체 검증 뒤 마지막에 올린다.
- 이미 올라간 R2 video는 full verification 실패 시에도 삭제·덮어쓰기·교체하지 않는다.
- 외장 볼륨이 없거나 RW가 아니거나 안전 하한 미만이면 내부 SSD fallback 없이 새 capture를 차단한다.
- RTSP/R2/Supabase/Slack 비밀값과 전체 RTSP URL은 SQLite, log, manifest, API, UI, Slack에 노출하지 않는다.
- 기존 `camera_clips`, `motion_clips`, GME, Dataset v2, 행동 GT와 `petcam-clips` 버킷을 수정하지 않는다.
- package 명령은 `uv`만 사용한다. `pip install`을 사용하지 않는다.
- 기존 local/R2 영상과 DB row를 삭제하지 않는다.
- Mac mini runtime의 검증된 90초 capture close grace를 먼저 코드·테스트로 보존한 뒤 구조 변경을 시작한다.
- 각 commit 단계는 owner가 명시적으로 커밋을 승인한 경우에만 실행한다. 승인 전에는 검증된 working tree 상태로 멈춘다.

---

### Task 1: 현장 capture 종료 여유를 정식 회귀 계약으로 고정

**Files:**
- Modify: `backend/rap_c500g_capture.py`
- Modify: `tests/test_rap_c500g_split_capture.py`
- Modify: `tests/test_rap_c500g_capture.py`

**Interfaces:**
- Consumes: 기존 `record_raw_segment(config, identity, paths, *, duration_sec, runner)` API
- Produces: `RAW_CAPTURE_CLOSE_GRACE_SEC: float = 90.0`; raw runner timeout은 `duration_sec + RAW_CAPTURE_CLOSE_GRACE_SEC`

- [ ] **Step 1: Mac mini hotfix와 branch 차이를 읽기 전용으로 대조**

Run on Mac mini and local worktree:

```bash
git -C /Users/baek-end/.codex/worktrees/rap-c500g-r2/petcam-lab diff -- backend/rap_c500g_capture.py tests/test_rap_c500g_split_capture.py
git -C /Users/baek/.codex/worktrees/petcam-lab/rap-c500g-r2 diff -- backend/rap_c500g_capture.py tests/test_rap_c500g_split_capture.py
```

Expected: runtime의 capture timeout 변경을 식별하고 다른 uncommitted runtime 변경은 되돌리지 않는다. 출력에 secret이나 전체 RTSP URL이 없는지 확인한다.

- [ ] **Step 2: 90초 close grace를 요구하는 실패 테스트 작성**

```python
def test_raw_recording_allows_ninety_seconds_for_rtsp_close(tmp_path: Path) -> None:
    seen: list[float] = []

    def runner(args: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
        seen.append(timeout)
        Path(args[-1]).write_bytes(b"raw")
        return subprocess.CompletedProcess(args, 0, "", "")

    config = load_camera_configs(ENV)[0]
    identity = make_identity()
    bundle_paths = build_bundle_paths(tmp_path, identity)
    raw = record_raw_segment(
        config,
        identity,
        bundle_paths,
        duration_sec=1800,
        runner=runner,
    )

    assert raw.paths.video_part.is_file()
    assert seen == [1890.0]
```

- [ ] **Step 3: 테스트가 기존 `duration + 2`에서 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_rap_c500g_split_capture.py::test_raw_recording_allows_ninety_seconds_for_rtsp_close -q
```

Expected: `1802.0 != 1890.0`으로 FAIL.

- [ ] **Step 4: 상수와 최소 구현 추가**

```python
RAW_CAPTURE_CLOSE_GRACE_SEC = 90.0

# _record_raw_segment_unleased 내부
captured = runner(args, float(duration_sec) + RAW_CAPTURE_CLOSE_GRACE_SEC)
```

- [ ] **Step 5: capture 회귀 테스트 실행**

Run:

```bash
uv run pytest tests/test_rap_c500g_capture.py tests/test_rap_c500g_split_capture.py -q
```

Expected: PASS, capture timeout test가 `1890.0`을 확인하며 비밀값 redaction 테스트도 유지된다.

- [ ] **Step 6: Owner의 커밋 승인이 있을 때만 Task 1 커밋**

```bash
git add backend/rap_c500g_capture.py tests/test_rap_c500g_capture.py tests/test_rap_c500g_split_capture.py
git commit -m "fix: C500G 원본 종료 여유 회귀 방지"
```

### Task 2: Durable pipeline 상태 원장 추가

**Files:**
- Create: `backend/rap_c500g_pipeline_types.py`
- Modify: `backend/rap_c500g_manager_store.py`
- Create: `tests/test_rap_c500g_pipeline_store.py`
- Modify: `tests/test_rap_c500g_manager_store.py`

**Interfaces:**
- Consumes: `(slot_start, camera_key)` capture identity와 secret-free bundle root/payload
- Produces: `PipelineState`, `PipelineItem`, `ManagerStore.upsert_pipeline_item()`, `ManagerStore.claim_pipeline_stage()`, `ManagerStore.list_pipeline_items()`, `ManagerStore.complete_pipeline_stage()`, `ManagerStore.fail_pipeline_stage()`

- [ ] **Step 1: 상태와 durable resume 실패 테스트 작성**

```python
def test_pipeline_item_survives_restart_and_advances_monotonically(tmp_path: Path) -> None:
    path = tmp_path / "manager.sqlite3"
    first = ManagerStore(path)
    first.upsert_pipeline_item(item(state=PipelineState.CAPTURED))
    first.complete_pipeline_stage(SLOT, "cam01", PipelineState.RAW_UPLOADED)

    reopened = ManagerStore(path)
    rows = reopened.list_pipeline_items(states=(PipelineState.RAW_UPLOADED,))

    assert [(row.slot_start, row.camera_key, row.state) for row in rows] == [
        (SLOT, "cam01", PipelineState.RAW_UPLOADED)
    ]
    with pytest.raises(ValueError, match="monotonic"):
        reopened.complete_pipeline_stage(SLOT, "cam01", PipelineState.CAPTURED)
```

- [ ] **Step 2: 신규 테스트가 import/table 부재로 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_rap_c500g_pipeline_store.py -q
```

Expected: `rap_c500g_pipeline_types` 또는 pipeline store method 부재로 FAIL.

- [ ] **Step 3: 상태 타입과 SQLite table 구현**

```python
class PipelineState(StrEnum):
    SCHEDULED = "scheduled"
    CAPTURING = "capturing"
    QUICK_VERIFYING = "quick_verifying"
    CAPTURED = "captured"
    RAW_UPLOADING = "raw_uploading"
    RAW_UPLOADED = "raw_uploaded"
    FULL_VERIFYING = "full_verifying"
    FINALIZING = "finalizing"
    VERIFIED_UPLOADED = "verified_uploaded"
    CAPTURE_FAILED = "capture_failed"
    QUICK_VERIFICATION_FAILED = "quick_verification_failed"
    RAW_UPLOAD_FAILED = "raw_upload_failed"
    FULL_VERIFICATION_FAILED = "full_verification_failed"
    FINAL_ARTIFACT_FAILED = "final_artifact_failed"
    DB_SYNC_FAILED = "db_sync_failed"
    INTEGRITY_CONFLICT = "integrity_conflict"


@dataclass(frozen=True, slots=True)
class PipelineItem:
    slot_start: str
    camera_key: str
    state: PipelineState
    root: str
    payload: Mapping[str, Any]
    raw_upload_attempts: int
    finalize_attempts: int
    next_attempt_at: str | None
    updated_at: str
```

SQLite schema:

```sql
CREATE TABLE IF NOT EXISTS manager_pipeline_item (
    slot_start TEXT NOT NULL,
    camera_key TEXT NOT NULL,
    state TEXT NOT NULL,
    root TEXT NOT NULL,
    payload TEXT NOT NULL,
    raw_upload_attempts INTEGER NOT NULL DEFAULT 0,
    finalize_attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    claimed_stage TEXT,
    claimed_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (slot_start, camera_key)
);
```

- [ ] **Step 4: 상태 전진·claim·재시작·secret 거부 테스트 실행**

Run:

```bash
uv run pytest tests/test_rap_c500g_pipeline_store.py tests/test_rap_c500g_manager_store.py -q
```

Expected: PASS. 동일 stage의 두 번째 claim은 false이고, 재시작 뒤 만료 claim만 회수되며 payload의 `rtsp://`, password/token key는 거부된다.

상태 전이는 명시적 allowlist로 제한한다. 성공 경로는
`scheduled → capturing → quick_verifying → captured → raw_uploading → raw_uploaded → full_verifying → finalizing → verified_uploaded`이며,
각 실패 상태에서는 해당 단계의 재시도 상태로만 돌아갈 수 있다. raw upload는 60초, 300초, 900초 backoff 후 900초 간격으로 계속 보존·재시도하고 3회 실패 시 Slack incident를 연다. `integrity_conflict`는 자동 재시도하지 않는다.

- [ ] **Step 5: Owner의 커밋 승인이 있을 때만 Task 2 커밋**

```bash
git add backend/rap_c500g_pipeline_types.py backend/rap_c500g_manager_store.py tests/test_rap_c500g_pipeline_store.py tests/test_rap_c500g_manager_store.py
git commit -m "feat: C500G 후처리 작업 원장 추가"
```

### Task 3: 야간 quick gate와 원본 atomic promote 구현

**Files:**
- Modify: `backend/rap_c500g_capture.py`
- Modify: `backend/rap_c500g_pipeline_types.py`
- Modify: `tests/test_rap_c500g_split_capture.py`

**Interfaces:**
- Consumes: `RawCaptureResult`
- Produces: `QuickVerifiedRaw`; `quick_verify_raw_capture(raw, *, runner=_default_runner) -> QuickVerifiedRaw`
- Produces: `finalize_quick_verified_raw(raw, *, runner=_default_runner) -> CaptureResult`

- [ ] **Step 1: quick gate가 전체 decode·thumbnail을 호출하지 않는 실패 테스트 작성**

```python
def test_quick_gate_only_ffprobes_and_promotes_video(tmp_path: Path) -> None:
    runner = FakeRunner()
    config = load_camera_configs(ENV)[0]
    identity = make_identity()
    paths = build_bundle_paths(tmp_path, identity)
    raw = record_raw_segment(config, identity, paths, duration_sec=60, runner=runner)
    runner.calls.clear()

    verified = quick_verify_raw_capture(raw, runner=runner)

    assert verified.paths.video.is_file()
    assert not verified.paths.video_part.exists()
    assert verified.media["codec"] == "hevc"
    assert verified.media["codec_tag"] == "hvc1"
    assert len(verified.video_sha256) == 64
    assert [call[0] for call in runner.calls] == ["ffprobe"]
    assert not verified.paths.thumbnail.exists()
    assert not verified.paths.manifest.exists()
```

- [ ] **Step 2: 테스트가 함수 부재로 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_rap_c500g_split_capture.py::test_quick_gate_only_ffprobes_and_promotes_video -q
```

Expected: `quick_verify_raw_capture` import failure로 FAIL.

- [ ] **Step 3: `QuickVerifiedRaw`와 quick gate 최소 구현**

```python
@dataclass(frozen=True, slots=True)
class QuickVerifiedRaw:
    config: CameraConfig
    identity: SegmentIdentity
    paths: BundlePaths
    media: Mapping[str, object]
    video_sha256: str


def quick_verify_raw_capture(
    raw: RawCaptureResult,
    *,
    runner: Runner = _default_runner,
) -> QuickVerifiedRaw:
    probed = runner(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(raw.paths.video_part)],
        60.0,
    )
    if probed.returncode != 0:
        raise CaptureFailed("quick verification failed: ffprobe error")
    media = _parse_probe(probed.stdout)
    if media["codec"] != "hevc" or media["codec_tag"] != "hvc1":
        raise CaptureFailed("quick verification failed: media contract")
    os.replace(raw.paths.video_part, raw.paths.video)
    return QuickVerifiedRaw(raw.config, raw.identity, raw.paths, media, sha256_file(raw.paths.video))
```

- [ ] **Step 4: 기존 finalizer를 promoted video 입력에 맞게 분리**

`finalize_quick_verified_raw()`는 `paths.video` 전체 decode, thumbnail 생성, sanitized log 확정,
`build_local_manifest()`와 atomic manifest만 수행한다. 원본 video를 rename·수정하지 않는다.
기존 `finalize_raw_capture()`는 test/legacy 호출을 위해 `quick_verify_raw_capture()` 다음
`finalize_quick_verified_raw()`를 호출하는 호환 wrapper로 유지한다.

- [ ] **Step 5: quick gate·legacy finalizer 회귀 테스트 실행**

Run:

```bash
uv run pytest tests/test_rap_c500g_split_capture.py tests/test_rap_c500g_capture.py tests/test_rap_c500g_manifest.py -q
```

Expected: PASS. quick gate에는 decode/thumbnail/manifest 호출이 없고 legacy `capture_segment()` 결과는 기존 4종 bundle을 유지한다.

- [ ] **Step 6: Owner의 커밋 승인이 있을 때만 Task 3 커밋**

```bash
git add backend/rap_c500g_capture.py backend/rap_c500g_pipeline_types.py tests/test_rap_c500g_split_capture.py
git commit -m "feat: C500G 원본 빠른 검증 단계 분리"
```

### Task 4: R2 원본 video 단독 업로드 구현

**Files:**
- Modify: `backend/rap_c500g_r2.py`
- Modify: `backend/rap_c500g_manifest.py`
- Modify: `tests/test_rap_c500g_r2.py`
- Modify: `tests/test_rap_c500g_manifest.py`

**Interfaces:**
- Consumes: `QuickVerifiedRaw`
- Produces: `R2BundleUploader.upload_raw_video(raw: QuickVerifiedRaw) -> RawUploadResult`
- Produces: `bundle_id_for(identity: SegmentIdentity) -> str`
- Preserves: `R2BundleUploader.upload_bundle()`의 video/thumb/log/manifest-last 최종 계약

- [ ] **Step 1: 원본 단독 업로드·멱등·충돌 실패 테스트 작성**

```python
def test_upload_raw_video_puts_only_video_and_verifies_head(tmp_path: Path) -> None:
    raw = quick_verified_raw(tmp_path)
    uploader, recording = make_uploader()

    result = uploader.upload_raw_video(raw)

    assert result.key.endswith("/video.mp4")
    assert result.size_bytes == raw.paths.video.stat().st_size
    assert result.sha256 == raw.video_sha256
    assert recording.uploaded_keys == [result.key]
    assert not any(key.endswith("manifest.json") for key in recording.uploaded_keys)
```

```python
def test_upload_raw_video_refuses_different_existing_object(tmp_path: Path) -> None:
    raw = quick_verified_raw(tmp_path)
    uploader, recording = make_uploader(existing_sha="different")

    with pytest.raises(IntegrityConflict):
        uploader.upload_raw_video(raw)

    assert recording.uploaded_keys == []
```

- [ ] **Step 2: 신규 테스트가 method 부재로 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_rap_c500g_r2.py -k raw_video -q
```

Expected: `upload_raw_video` 부재로 FAIL.

- [ ] **Step 3: raw video key·metadata·HEAD 검증 구현**

```python
@dataclass(frozen=True, slots=True)
class RawUploadResult:
    key: str
    size_bytes: int
    sha256: str
    uploaded: bool


def upload_raw_video(self, raw: QuickVerifiedRaw) -> RawUploadResult:
    key = f"{raw.paths.relative_dir.as_posix()}/video.mp4"
    changed = self._ensure_object(
        path=raw.paths.video,
        key=key,
        content_type="video/mp4",
        sha256=raw.video_sha256,
        bundle_id=bundle_id_for(raw.identity),
        camera_key=raw.identity.camera_key,
    )
    return RawUploadResult(key, raw.paths.video.stat().st_size, raw.video_sha256, changed)
```

`backend/rap_c500g_manifest.py`에서 기존 `relative_bundle_path` 해시 규칙을 함수로 분리한다.

```python
def bundle_id_for(identity: SegmentIdentity) -> str:
    relative = build_bundle_paths(Path("."), identity).relative_dir.as_posix()
    digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:32]
    return f"rap-{digest}"
```

같은 파일에 `from backend.rap_c500g_naming import build_bundle_paths`를 추가한다. `build_local_manifest()`도 이 함수를 호출하게 바꾸고, 같은 identity가 raw upload와 final manifest에서 같은 ID를 반환하는 테스트를 `tests/test_rap_c500g_manifest.py`에 추가한다.

- [ ] **Step 4: R2 전체 회귀 테스트 실행**

Run:

```bash
uv run pytest tests/test_rap_c500g_r2.py tests/test_rap_c500g_naming.py tests/test_rap_c500g_manifest.py -q
```

Expected: PASS. raw upload는 video 1개만 만들고 최종 `upload_bundle()`은 기존 video를 skip한 뒤 manifest를 마지막에 올린다.

- [ ] **Step 5: Owner의 커밋 승인이 있을 때만 Task 4 커밋**

```bash
git add backend/rap_c500g_r2.py backend/rap_c500g_manifest.py tests/test_rap_c500g_r2.py tests/test_rap_c500g_manifest.py
git commit -m "feat: C500G 원본 R2 즉시 백업 추가"
```

### Task 5: Capture-first pipeline orchestration 구현

**Files:**
- Create: `backend/rap_c500g_pipeline.py`
- Create: `tests/test_rap_c500g_pipeline.py`
- Modify: `backend/rap_c500g_manager_runtime.py`
- Modify: `tests/test_rap_c500g_manager_runtime.py`

**Interfaces:**
- Consumes: `ManagerStore`, `R2BundleUploader`, `RapRecordingRepository`, quick/finalize functions
- Produces: `pipeline_window(now: datetime) -> PipelineWindow`
- Produces: `CaptureFirstPipeline.accept_capture(raw: RawCaptureResult) -> None`
- Produces: `CaptureFirstPipeline.run_once(now: datetime, *, capture_active: bool) -> PipelineSnapshot`
- Produces: `CaptureFirstPipeline.shutdown(timeout: float) -> None`

- [ ] **Step 1: 시간창과 capture 우선순위 실패 테스트 작성**

```python
@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (kst(7, 59), PipelineWindow.CAPTURE),
        (kst(8, 0), PipelineWindow.FINALIZE),
        (kst(19, 29), PipelineWindow.FINALIZE),
        (kst(19, 30), PipelineWindow.DRAIN),
        (kst(20, 0), PipelineWindow.CAPTURE),
    ],
)
def test_pipeline_window_uses_fixed_kst_boundaries(now: datetime, expected: PipelineWindow) -> None:
    assert pipeline_window(now) is expected
```

```python
def test_night_capture_runs_quick_gate_and_raw_upload_but_not_full_finalize(tmp_path: Path) -> None:
    calls: list[str] = []
    pipeline = make_pipeline(tmp_path, calls=calls)

    pipeline.accept_capture(raw_result(tmp_path))
    pipeline.drain_ready_for_test(now=kst(20, 31))

    assert calls == ["quick_verify", "raw_upload"]
    assert pipeline.snapshot().finalize_active == 0
```

- [ ] **Step 2: 테스트가 module 부재로 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_rap_c500g_pipeline.py -q
```

Expected: `backend.rap_c500g_pipeline` import failure로 FAIL.

- [ ] **Step 3: pipeline window와 executor 경계 구현**

```python
class PipelineWindow(StrEnum):
    CAPTURE = "capture"
    FINALIZE = "finalize"
    DRAIN = "drain"


@dataclass(frozen=True, slots=True)
class PipelineSnapshot:
    mode: PipelineWindow
    raw_upload_pending: int
    raw_upload_active: int
    raw_upload_failed: int
    raw_upload_oldest_age_sec: float | None
    finalize_pending: int
    finalize_active: int
    finalize_failed: int
    finalize_completed: int


class CaptureFirstPipeline:
    def __init__(
        self,
        *,
        store: ManagerStore,
        uploader: R2BundleUploader,
        repository: RapRecordingRepository,
        quick_verify_fn: Callable[[RawCaptureResult], QuickVerifiedRaw],
        finalize_fn: Callable[[QuickVerifiedRaw], CaptureResult],
        raw_upload_executor: Executor,
        finalize_executor: Executor,
        notifier: Callable[[str, Mapping[str, Any]], None],
    ) -> None:
        self._store = store
        self._uploader = uploader
        self._repository = repository
        self._quick_verify = quick_verify_fn
        self._finalize = finalize_fn
        self._raw_upload_executor = raw_upload_executor
        self._finalize_executor = finalize_executor
        self._notifier = notifier
        self._raw_upload_futures: dict[Future[RawUploadResult], tuple[str, str]] = {}
        self._finalize_futures: dict[Future[CaptureResult], tuple[str, str]] = {}
```

Implementation rules:

- raw upload executor `max_workers=1`
- daytime finalize executor `max_workers=3`
- `accept_capture()`는 durable `captured` row를 먼저 쓰고 quick/upload future를 제출
- CAPTURE window에는 `RAW_UPLOADED` item을 finalize executor에 제출하지 않음
- FINALIZE window에는 `capture_active is False`일 때만 최대 3개 claim
- DRAIN window에는 새 finalize claim을 만들지 않고 진행 중 작업만 회수
- future 종료 시 SQLite 상태를 성공/실패로 원자 전진

`run_once()`는 위 필드를 모두 채운 immutable `PipelineSnapshot`을 반환하고, `snapshot()`은 마지막 값을 그대로 반환한다. 테스트 전용 `drain_ready_for_test()`는 등록된 future를 기다린 뒤 같은 completion handler를 호출할 뿐 production 분기를 따로 만들지 않는다.

- [ ] **Step 4: manager가 raw 결과를 pipeline으로 넘기도록 연결**

`RapC500GManager._capture_with_retries()`에서 `RawCaptureResult`를 기존 verification executor에 바로
제출하지 않고 `self.pipeline.accept_capture(result)`에 넘긴다. manager loop의 각 tick에서
`self.pipeline.run_once(now, capture_active=bool(self._active))`를 호출하고 snapshot에 pipeline 상태를
병합한다.

- [ ] **Step 5: 야간/주간/경계/비차단 테스트 실행**

Run:

```bash
uv run pytest tests/test_rap_c500g_pipeline.py tests/test_rap_c500g_manager_runtime.py -q
```

Expected: PASS. 20:00~08:00 full finalize 0건, 08:00 이후 capture active면 finalize 0건, raw upload가 block된 동안 다음 slot capture가 시작된다.

- [ ] **Step 6: Owner의 커밋 승인이 있을 때만 Task 5 커밋**

```bash
git add backend/rap_c500g_pipeline.py backend/rap_c500g_manager_runtime.py tests/test_rap_c500g_pipeline.py tests/test_rap_c500g_manager_runtime.py
git commit -m "feat: C500G 녹화 우선 파이프라인 연결"
```

### Task 6: Daytime finalizer와 manifest-last 최종화 구현

**Files:**
- Modify: `backend/rap_c500g_capture.py`
- Modify: `backend/rap_c500g_pipeline.py`
- Modify: `backend/rap_c500g_service.py`
- Modify: `tests/test_rap_c500g_split_capture.py`
- Modify: `tests/test_rap_c500g_pipeline.py`
- Modify: `tests/test_rap_c500g_service.py`
- Modify: `tests/test_rap_c500g_repository.py`

**Interfaces:**
- Consumes: durable `RAW_UPLOADED` item과 immutable local/R2 `video.mp4`
- Produces: local `thumbnail.jpg`, `ffmpeg.sanitized.log`, `manifest.json`
- Produces: R2 thumbnail/log/manifest-last와 DB `uploaded` row

- [ ] **Step 1: immutable raw와 failure preservation 테스트 작성**

```python
def test_daytime_finalize_never_changes_uploaded_video(tmp_path: Path) -> None:
    raw = quick_verified_raw(tmp_path)
    before = sha256_file(raw.paths.video)

    result = finalize_quick_verified_raw(raw, runner=successful_finalize_runner)

    assert sha256_file(raw.paths.video) == before
    assert result.paths.thumbnail.is_file()
    assert result.paths.log.is_file()
    assert result.paths.manifest.is_file()
```

```python
def test_decode_failure_preserves_local_and_r2_raw_without_manifest(tmp_path: Path) -> None:
    pipeline, r2 = raw_uploaded_pipeline(tmp_path, decode_returncode=1)

    pipeline.run_once(kst(8, 1), capture_active=False)
    pipeline.drain_ready_for_test(now=kst(8, 2))

    assert local_video(tmp_path).is_file()
    assert r2.video_exists()
    assert not local_manifest(tmp_path).exists()
    assert not r2.manifest_exists()
    assert pipeline.snapshot().full_verification_failed == 1
```

- [ ] **Step 2: 테스트가 current raw/finalizer path 차이로 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_rap_c500g_split_capture.py tests/test_rap_c500g_pipeline.py -k "daytime or decode_failure" -q
```

Expected: promoted `video.mp4`를 finalizer가 처리하지 못하거나 pipeline 상태가 없어 FAIL.

- [ ] **Step 3: finalizer와 최종 sync 경로 구현**

`finalize_quick_verified_raw()`는 다음 순서만 사용한다.

```text
R2 video HEAD size/SHA 재확인
→ ffmpeg full decode local video.mp4
→ thumbnail.part.jpg 생성
→ sanitized log.part 확정
→ thumbnail/log atomic promote
→ build_local_manifest(media + original video SHA)
→ local manifest atomic write
→ upload_bundle(): video same-hash skip, thumbnail/log upload, manifest last
→ repository.upsert_manifest(uploaded manifest)
→ pipeline state verified_uploaded
```

어느 단계에서 실패해도 `video.mp4`와 이미 존재하는 R2 video는 보존하고 completion manifest를 만들지 않는다.

- [ ] **Step 4: finalizer·manifest·R2·DB 회귀 테스트 실행**

Run:

```bash
uv run pytest tests/test_rap_c500g_split_capture.py tests/test_rap_c500g_manifest.py tests/test_rap_c500g_r2.py tests/test_rap_c500g_service.py tests/test_rap_c500g_repository.py tests/test_rap_c500g_pipeline.py -q
```

Expected: PASS. R2 upload 순서의 마지막 key는 `manifest.json`, DB `uploaded`는 manifest-last와 `r2_verified=true`일 때만 생성된다.

- [ ] **Step 5: Owner의 커밋 승인이 있을 때만 Task 6 커밋**

```bash
git add backend/rap_c500g_capture.py backend/rap_c500g_pipeline.py backend/rap_c500g_service.py tests/test_rap_c500g_split_capture.py tests/test_rap_c500g_pipeline.py tests/test_rap_c500g_service.py tests/test_rap_c500g_repository.py
git commit -m "feat: C500G 주간 최종 검증과 동기화 분리"
```

### Task 7: 상태 JSON·UI·Slack을 3단계로 분리

**Files:**
- Modify: `backend/rap_c500g_manager_store.py`
- Modify: `backend/rap_c500g_manager_runtime.py`
- Modify: `backend/rap_c500g_manager_notify.py`
- Modify: `backend/rap_c500g_manager_ui.py`
- Modify: `tests/test_rap_c500g_manager_store.py`
- Modify: `tests/test_rap_c500g_manager_runtime.py`
- Modify: `tests/test_rap_c500g_manager_notify.py`
- Modify: `tests/test_rap_c500g_manager_web.py`

**Interfaces:**
- Consumes: `PipelineSnapshot`
- Produces: `ManagerSnapshot.schema_version = "rap-c500g-manager-status/v2"`
- Produces: `pipeline.mode`, `raw_upload.pending/failed/oldest_age_sec`, `finalize.pending/active/failed/completed`
- Produces: Slack kinds `slot_raw_summary`, `pipeline_incident`, `pipeline_recovered`, `night_finalize_summary`

- [ ] **Step 1: public status와 알림 payload 실패 테스트 작성**

```python
def test_status_v2_separates_capture_raw_upload_and_final_verify(tmp_path: Path) -> None:
    payload = snapshot_with_pipeline().to_public_dict()

    assert payload["schema_version"] == "rap-c500g-manager-status/v2"
    assert payload["pipeline"]["mode"] == "capture"
    assert payload["pipeline"]["raw_upload"]["pending"] == 2
    assert payload["pipeline"]["finalize"]["pending"] == 5
    assert "rtsp://" not in json.dumps(payload)
```

```python
def test_slot_raw_summary_is_one_safe_message_for_three_cameras() -> None:
    message = render_slack("slot_raw_summary", slot_summary_payload())

    assert message.count("cam01") == 1
    assert message.count("cam02") == 1
    assert message.count("cam03") == 1
    assert "rtsp://" not in message
    assert "/Volumes/" not in message
```

- [ ] **Step 2: v2 테스트가 schema/pipeline field 부재로 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_rap_c500g_manager_store.py tests/test_rap_c500g_manager_notify.py tests/test_rap_c500g_manager_web.py -q
```

Expected: v2 schema 또는 pipeline key 부재로 FAIL.

- [ ] **Step 3: snapshot과 Slack event 구현**

`ManagerSnapshot.from_dict()`는 v1 snapshot에 `pipeline={}` 기본값을 적용해 기존 SQLite를 읽는다.
같은 slot 세 카메라가 terminal raw upload 상태에 도달하면 `slot_raw_summary`를 정확히 한 번 기록한다.
pipeline incident는 `(kind, camera_key, slot)` dedupe key로 open/recovered 전환만 알린다.

- [ ] **Step 4: dashboard를 3단계 상태로 변경**

각 카메라 카드에 다음 metric을 고정한다.

```text
원본 녹화: recording/captured/failed
R2 원본: pending/uploaded/failed
최종 검증: waiting/verifying/verified/failed
```

상단 mode badge는 `녹화 우선 모드`, `후처리 모드`, `전환 대기` 중 하나이며, raw upload 완료 후
full verification 대기는 경고가 아닌 중립/대기 색상으로 표시한다.

- [ ] **Step 5: status/UI/Slack 테스트 실행**

Run:

```bash
uv run pytest tests/test_rap_c500g_manager_store.py tests/test_rap_c500g_manager_runtime.py tests/test_rap_c500g_manager_notify.py tests/test_rap_c500g_manager_web.py -q
```

Expected: PASS. HTML은 세 단계 라벨을 포함하고 좁은 화면에서도 camera card grid를 유지하며 secret scanner hit가 0이다.

- [ ] **Step 6: Owner의 커밋 승인이 있을 때만 Task 7 커밋**

```bash
git add backend/rap_c500g_manager_store.py backend/rap_c500g_manager_runtime.py backend/rap_c500g_manager_notify.py backend/rap_c500g_manager_ui.py tests/test_rap_c500g_manager_store.py tests/test_rap_c500g_manager_runtime.py tests/test_rap_c500g_manager_notify.py tests/test_rap_c500g_manager_web.py
git commit -m "feat: C500G 녹화 백업 검증 상태 분리"
```

### Task 8: 재부팅 복구와 단일-service lifecycle 완성

**Files:**
- Modify: `backend/rap_c500g_pipeline.py`
- Modify: `backend/rap_c500g_manager_runtime.py`
- Modify: `backend/rap_c500g_manager_main.py`
- Modify: `tests/test_rap_c500g_pipeline.py`
- Modify: `tests/test_rap_c500g_manager_runtime.py`
- Modify: `tests/test_rap_c500g_manager_main.py`
- Modify: `tests/test_render_rap_c500g_manager_launchd.py`

**Interfaces:**
- Consumes: SQLite pipeline rows, local bundle scan, R2 HEAD
- Produces: `CaptureFirstPipeline.resume() -> ResumeSummary`
- Preserves: 기존 manager CLI `serve`, `status --json`, `diagnostic --duration 60`

- [ ] **Step 1: restart matrix 실패 테스트 작성**

```python
@pytest.mark.parametrize(
    ("state", "expected_action"),
    [
        (PipelineState.CAPTURED, "quick_and_upload"),
        (PipelineState.RAW_UPLOADING, "head_then_upload"),
        (PipelineState.RAW_UPLOADED, "wait_for_daytime_finalize"),
        (PipelineState.FULL_VERIFYING, "reclaim_finalize"),
        (PipelineState.VERIFIED_UPLOADED, "none"),
    ],
)
def test_resume_reconciles_durable_stage_without_recapture(
    tmp_path: Path, state: PipelineState, expected_action: str
) -> None:
    pipeline = reopened_pipeline(tmp_path, state=state)

    summary = pipeline.resume()

    assert summary.action_for("cam01", SLOT) == expected_action
    assert summary.recapture_count == 0
```

- [ ] **Step 2: 테스트가 resume 부재로 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_rap_c500g_pipeline.py -k resume -q
```

Expected: `resume` 부재로 FAIL.

- [ ] **Step 3: filesystem/R2/SQLite reconciliation 구현**

```python
@dataclass(frozen=True, slots=True)
class ResumeAction:
    slot_start: str
    camera_key: str
    action: str


@dataclass(frozen=True, slots=True)
class ResumeSummary:
    actions: Sequence[ResumeAction]
    recapture_count: int

    def action_for(self, camera_key: str, slot_start: str) -> str:
        return next(
            item.action
            for item in self.actions
            if item.camera_key == camera_key and item.slot_start == slot_start
        )
```

Resume rules:

```text
video.part.mp4 only       → failed evidence 보존, recapture 금지
video.mp4 + no raw HEAD   → quick metadata 복원 후 raw upload
video.mp4 + matching HEAD → raw_uploaded로 전진
local manifest + no final manifest HEAD → upload_bundle + DB retry
matching final manifest HEAD + DB missing → DB upsert only
verified_uploaded         → no-op
```

claim TTL을 넘은 pipeline stage만 재회수하며 살아 있는 child/future가 있는 item은 건드리지 않는다.

- [ ] **Step 4: manager startup/shutdown에 pipeline lifecycle 연결**

`RapC500GManager.start()` 전에 `pipeline.resume()`을 호출한다. `stop()`은 새 claim을 중단하고 capture child를
먼저 안전 종료한 뒤 raw upload/finalize future의 SQLite 상태를 보존한다. launchd plist label과 working
directory는 변경하지 않는다.

- [ ] **Step 5: restart·single service·CLI 회귀 테스트 실행**

Run:

```bash
uv run pytest tests/test_rap_c500g_pipeline.py tests/test_rap_c500g_manager_runtime.py tests/test_rap_c500g_manager_main.py tests/test_render_rap_c500g_manager_launchd.py -q
```

Expected: PASS. 재시작 시 같은 camera/slot capture 0건, legacy recorder와 동시 실행 거부, status JSON은 v2 pipeline을 반환한다.

- [ ] **Step 6: Owner의 커밋 승인이 있을 때만 Task 8 커밋**

```bash
git add backend/rap_c500g_pipeline.py backend/rap_c500g_manager_runtime.py backend/rap_c500g_manager_main.py tests/test_rap_c500g_pipeline.py tests/test_rap_c500g_manager_runtime.py tests/test_rap_c500g_manager_main.py tests/test_render_rap_c500g_manager_launchd.py
git commit -m "feat: C500G 작업 대기열 재부팅 복구 추가"
```

### Task 9: 문서·전체 회귀·Mac mini handoff와 canary

**Files:**
- Modify: `docs/runbooks/rap-c500g-recorder.md`
- Modify: `docs/superpowers/specs/2026-09-03-rap-c500g-capture-first-pipeline-design.md`
- Create: `docs/handoff-prompts/2026-09-03-rap-c500g-capture-first-runtime-handoff.md`
- Test: `tests/test_rap_c500g_*.py`

**Interfaces:**
- Consumes: Task 1~8의 capture-first runtime
- Produces: tracked handoff manifest와 `HANDOFF_OK`; Mac mini canary 증거

- [ ] **Step 1: runbook에 운영 상태와 복구 명령 추가**

Runbook은 다음 read-only 점검을 정확히 문서화한다.

```bash
uv run python -m backend.rap_c500g_manager_main --state-path \
  "/Users/baek-end/Library/Application Support/rap-c500g-manager/manager.sqlite3" \
  status --json
```

정상 야간은 `pipeline.mode=capture`, full verification active 0, raw backlog가 증가 후 감소하는 상태다.
정상 주간은 `pipeline.mode=finalize`, capture active 0, finalize completed가 증가하는 상태다.

- [ ] **Step 2: focused C500G 테스트 전체 실행**

Run:

```bash
uv run pytest -q tests/test_rap_c500g_capture.py tests/test_rap_c500g_main.py tests/test_rap_c500g_manager_main.py tests/test_rap_c500g_manager_notify.py tests/test_rap_c500g_manager_probe.py tests/test_rap_c500g_manager_runtime.py tests/test_rap_c500g_manager_store.py tests/test_rap_c500g_manager_web.py tests/test_rap_c500g_manifest.py tests/test_rap_c500g_naming.py tests/test_rap_c500g_pipeline.py tests/test_rap_c500g_pipeline_store.py tests/test_rap_c500g_production_lock.py tests/test_rap_c500g_r2.py tests/test_rap_c500g_recordings_migration.py tests/test_rap_c500g_repository.py tests/test_rap_c500g_service.py tests/test_rap_c500g_split_capture.py tests/test_render_rap_c500g_manager_launchd.py
```

Expected: exit 0, failures 0.

- [ ] **Step 3: repository 전체 Python 회귀 실행**

Run:

```bash
uv run pytest -q
git diff --check
```

Expected: pytest exit 0, `git diff --check` 출력 없음.

- [ ] **Step 4: handoff manifest 작성·검증**

Manifest에는 다음 값을 실제 출력으로 고정한다.

```text
execution_repo=/Users/baek/.codex/worktrees/petcam-lab/rap-c500g-r2
design_path=/Users/baek/.codex/worktrees/petcam-lab/rap-c500g-r2/docs/superpowers/specs/2026-09-03-rap-c500g-capture-first-pipeline-design.md
plan_path=/Users/baek/.codex/worktrees/petcam-lab/rap-c500g-r2/docs/superpowers/plans/2026-09-03-rap-c500g-capture-first-pipeline.md
implementation_host=<actual local hostname>
runtime_host=baeg-endeuui-Macmini.local
runtime_kind=launchd
service_label=com.teraai.rap-c500g-manager
commit_sha=<actual 40-character SHA after owner-approved commits>
```

Run:

```bash
uv run python scripts/verify_agent_handoff.py --manifest \
  /Users/baek/.codex/worktrees/petcam-lab/rap-c500g-r2/docs/handoff-prompts/2026-09-03-rap-c500g-capture-first-runtime-handoff.md
```

Expected: `HANDOFF_OK` 전문, tracked design/plan, clean committed tree.

- [ ] **Step 5: Mac mini read-only preflight**

Verify without mutation:

```text
runtime HEAD equals handoff SHA
service label loaded exactly once
legacy recorder not loaded
active production/test FFmpeg count = 0
/Volumes/RAP-C500G mounted, RW, safety free-space floor passed
cam01~cam03 TCP 554 and RTSP probe passed
R2/DB/Slack connection probes passed without secret output
pending old pipeline work counted and preserved
```

- [ ] **Step 6: 안전창에 runtime cutover 후 60초 capture-first canary**

Canary expected result:

```text
capture: cam01~cam03 3/3
quick gate: 3/3
R2 raw video HEAD size/SHA: 3/3
night-style stage: thumbnail=0, final manifest=0, DB final row=0
manager restart: raw_uploaded 3/3 restored, recapture=0
daytime finalize: full decode/QuickLook 3/3
local final artifacts: 12/12
R2 final artifacts: 12/12, manifest-last 3/3
DB: uploaded 3/3
secret scanner: 0
```

- [ ] **Step 7: 실제 30분 slot canary와 다음 경계 확인**

Measure:

```text
three capture start skew
next 00/30 boundary delay
capture FFmpeg count
night full-decode/thumbnail process count
raw upload completion latency and backlog oldest age
local/R2 video size/SHA
Slack slot summary count
```

Expected: start delay p95 5초 이하, 최대 15초 이하, 야간 full decode/thumbnail 0, raw video 3/3 matching, Slack summary 1건.

- [ ] **Step 8: 첫 12시간 acceptance와 주간 drain 검증**

Expected:

```text
expected: 24 slots/camera, 72 videos/night
captured/raw-uploaded: 72/72 or every real outage explicitly classified
08:00 이후 new capture: 0
daytime full verification starts only after capture idle
final local/R2/DB bundle counts converge
19:30 remaining backlog: 0, or quantified safe drain with 20:00 capture unaffected
existing local/R2/DB data deleted or overwritten: 0
MacBook/Codex/browser dependency: 0
```

- [ ] **Step 9: Owner의 커밋 승인이 있을 때만 문서·handoff 커밋**

```bash
git add docs/runbooks/rap-c500g-recorder.md docs/superpowers/specs/2026-09-03-rap-c500g-capture-first-pipeline-design.md docs/superpowers/plans/2026-09-03-rap-c500g-capture-first-pipeline.md docs/handoff-prompts/2026-09-03-rap-c500g-capture-first-runtime-handoff.md
git commit -m "docs: C500G 녹화 우선 운영 절차 확정"
```

## Final Review Gate

- [ ] Spec §1~§15의 모든 요구가 Task 1~9 중 하나에 연결되는지 대조한다.
- [ ] 야간 full decode/thumbnail 실행 경로가 0인지 코드 검색과 fake clock 통합 테스트로 확인한다.
- [ ] raw R2 video와 local video SHA가 full finalize 전후 동일한지 확인한다.
- [ ] manifest-last와 DB final row가 full verification 이전에 생길 수 없는지 확인한다.
- [ ] MacBook/Codex/browser가 scheduler·queue·recovery의 dependency가 아닌지 launchd 재부팅 canary로 확인한다.
- [ ] secret, 전체 RTSP URL, 절대 local path가 status/UI/Slack/manifest/DB에 없는지 scanner로 확인한다.
- [ ] 기존 영상/R2 object/DB row 삭제·덮어쓰기 0건을 cutover 전후 inventory로 확인한다.
- [ ] runtime HEAD, service label, working directory, 실제 run 증거가 모두 일치할 때만 `DEPLOYED_VERIFIED`로 보고한다.

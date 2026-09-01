# RAP C500G 로컬 녹화 매니저 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mac mini가 브라우저나 MacBook에 의존하지 않고 cam01~cam03의 20:00~08:00 30분 녹화, 외장 저장소 검증, R2/DB 동기화와 상태 UI를 운영하게 한다.

**Architecture:** 기존 `rap_c500g_*` 캡처·manifest·R2·DB 계약을 adapter로 재사용하고, SQLite 설정/상태 원장과 단일 background manager를 추가한다. FastAPI는 `127.0.0.1`에만 bind하고 같은 상태 정본을 dashboard와 `status --json` CLI가 읽는다. 기존 recorder와 manager의 production 권한은 동시에 켜지 않는다.

**Tech Stack:** Python 3.12, FastAPI, SQLite WAL, FFmpeg/ffprobe, boto3 R2, Supabase, launchd, pytest

**Spec:** `docs/superpowers/specs/2026-08-31-rap-c500g-local-manager-design.md`

## Global Constraints

- 카메라는 `.env`의 `cam01|cam02|cam03` allowlist만 사용하고 RTSP 비밀값/전체 URL을 UI·JSON·SQLite·로그에 쓰지 않는다.
- production은 KST 20:00~08:00, 30분 wall-clock slot을 사용한다.
- 외장 volume이 실제 mount/RW가 아니거나 여유 공간이 8 GiB 미만이면 내부 SSD fallback 없이 새 capture를 차단한다.
- 기존 bundle, R2 object, DB row를 삭제하거나 수정하지 않는다.
- 기존 `com.teraai.rap-c500g-recorder`와 새 manager를 동시에 production 실행하지 않는다.
- Mac mini 배포는 tracked design/plan/runtime manifest와 `HANDOFF_OK` 뒤에만 수행한다.

---

### Task 1: 설정·상태 SQLite 정본

**Files:**
- Create: `backend/rap_c500g_manager_store.py`
- Test: `tests/test_rap_c500g_manager_store.py`

**Interfaces:**
- Produces: `ManagerPlan`, `CameraRuntimeState`, `ManagerSnapshot`, `ManagerStore`.
- Produces: `ManagerStore.load_plan()`, `save_pending_plan()`, `apply_pending_plan()`, `write_snapshot()`, `read_snapshot()`.

- [x] **Step 1: RED — 기본 plan, pending revision, secret-free snapshot 테스트 작성**

```python
def test_store_applies_pending_plan_atomically(tmp_path):
    store = ManagerStore(tmp_path / "manager.sqlite3")
    pending = store.save_pending_plan(
        start_local="20:00", end_local="08:00",
        selected_cameras=("cam01", "cam02", "cam03"),
        volume_name="RAP-C500G", max_capture_retries=3,
    )
    assert store.load_plan().revision == 0
    assert store.apply_pending_plan().revision == pending.revision
```

- [x] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_rap_c500g_manager_store.py`

Expected: module import failure.

- [x] **Step 3: GREEN — SQLite WAL schema와 immutable DTO 구현**

`manager_plan` single-row active/pending JSON, `manager_snapshot` single-row JSON, `manager_event` append-only table을 만든다. camera allowlist, `HH:MM`, retry 0..5, volume label basename을 저장 전에 검증한다.

- [x] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/test_rap_c500g_manager_store.py`

Expected: PASS.

### Task 2: 외장 볼륨·카메라 read-only probe

**Files:**
- Create: `backend/rap_c500g_manager_probe.py`
- Test: `tests/test_rap_c500g_manager_probe.py`

**Interfaces:**
- Consumes: `CameraConfig`.
- Produces: `VolumeStatus`, `CameraProbeStatus`, `list_external_volumes()`, `validate_selected_volume()`, `probe_camera()`.

- [x] **Step 1: RED — mount/RW/free와 secret redaction 테스트 작성**

```python
def test_selected_volume_fails_closed_when_mount_disappears(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "is_mount", lambda _: False)
    status = validate_selected_volume("RAP-C500G", volumes_root=tmp_path)
    assert status.ready is False
    assert status.reason == "volume_missing"
```

TCP 554 실패, ffprobe 실패, 정상 probe에서 status에 username/password/URL이 없는지도 검사한다.

- [x] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_rap_c500g_manager_probe.py`

Expected: module import failure.

- [x] **Step 3: GREEN — `/Volumes` allowlist와 bounded probe 구현**

실제 mount만 반환하고 system/data/network path와 임의 입력을 거부한다. `socket.create_connection((ip,554), timeout=2)` 뒤 `ffprobe -rtsp_transport tcp`를 bounded subprocess로 실행하며 반환 DTO에는 안전 필드만 둔다.

- [x] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/test_rap_c500g_manager_probe.py`

Expected: PASS.

### Task 3: 단일 manager scheduler와 카메라별 supervisor

**Files:**
- Create: `backend/rap_c500g_manager_runtime.py`
- Modify: `backend/rap_c500g_service.py`
- Test: `tests/test_rap_c500g_manager_runtime.py`
- Modify test: `tests/test_rap_c500g_service.py`

**Interfaces:**
- Consumes: `ManagerStore`, `CameraConfig`, `capture_segment`, `sync_bundles`.
- Produces: `RapC500GManager.start()`, `stop()`, `run_once(now)`, `run_diagnostic(duration_sec=60)`.
- Produces: `capture_selected_slot(configs, root, slot, capture_fn)` for non-empty camera subsets.

- [x] **Step 1: RED — 00/30 boundary, 중복 방지, 선택 카메라 독립 실패 테스트 작성**

```python
def test_one_camera_failure_does_not_block_other_cameras_or_next_slot(...):
    manager.run_once(datetime(2026, 9, 1, 20, 0, tzinfo=KST))
    assert started == ["cam01", "cam02", "cam03"]
    assert snapshot.cameras["cam02"].state == "retry_wait"
    assert snapshot.cameras["cam01"].state == "recording"
```

같은 camera/slot을 두 번 호출해도 child 1개, 08:00 새 capture 0개, volume missing이면 전체 child 0개를 검사한다.

- [x] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_rap_c500g_manager_runtime.py tests/test_rap_c500g_service.py`

Expected: 새 manager/runtime interface 부재 실패.

- [x] **Step 3: GREEN — scheduler/supervisor 최소 구현**

slot key와 camera key를 `(night, scheduled_start, camera)`로 고정하고 active worker map으로 중복을 막는다. 카메라별 worker가 10/30/60초 bounded retry를 수행하되 slot end를 넘기지 않는다. capture worker와 single sync worker를 분리하고 모든 상태 전이는 store snapshot에 반영한다.

- [x] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/test_rap_c500g_manager_runtime.py tests/test_rap_c500g_service.py`

Expected: PASS.

### Task 4: 상태 JSON·설정 API·반응형 dashboard

**Files:**
- Create: `backend/rap_c500g_manager_web.py`
- Create: `backend/rap_c500g_manager_ui.py`
- Test: `tests/test_rap_c500g_manager_web.py`

**Interfaces:**
- Consumes: `RapC500GManager`, `ManagerStore`, probe DTO.
- Produces: `create_manager_app(context) -> FastAPI`.
- Produces endpoints: `GET /api/status`, `GET /api/settings`, `PUT /api/settings/pending`, `GET /api/volumes`, `POST /api/probes/cameras`, `POST /api/diagnostics/recording`, `GET /api/incidents`, `GET /`.

- [x] **Step 1: RED — loopback mutation, validation, secret leak, UI 체험 테스트 작성**

```python
def test_status_and_dashboard_never_expose_secrets(client):
    body = client.get("/api/status").text + client.get("/").text
    assert "rtsp://" not in body
    assert "password" not in body.lower()
    assert "카메라 상태" in body
```

비-loopback mutation 403, invalid camera/volume 422, active production 중 diagnostic 409도 검사한다.

- [x] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_rap_c500g_manager_web.py`

Expected: module import failure.

- [x] **Step 3: GREEN — 승인 UI와 API 구현**

Python 문자열 template 한 장으로 외부 CDN 없는 dashboard/settings를 제공한다. camera table 대신 반응형 card grid, 16:9 thumbnail placeholder, 충분한 padding/margin, storage cards, 최근 완료/incident를 구현하고 3초 polling으로 status를 갱신한다.

- [x] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/test_rap_c500g_manager_web.py`

Expected: PASS.

### Task 5: CLI·launchd·운영 문서

**Files:**
- Create: `backend/rap_c500g_manager_main.py`
- Create: `scripts/render_rap_c500g_manager_launchd.py`
- Create: `tests/test_rap_c500g_manager_main.py`
- Create: `tests/test_render_rap_c500g_manager_launchd.py`
- Modify: `pyproject.toml`
- Modify: `docs/runbooks/rap-c500g-recorder.md`

**Interfaces:**
- Produces commands: `rap-manager serve`, `rap-manager status --json`, `rap-manager diagnostic --duration 60`.
- Produces launchd label: `com.teraai.rap-c500g-manager`, bind `127.0.0.1:8766`.

- [x] **Step 1: RED — CLI exit code와 secret-free plist 테스트 작성**

status 정상은 exit 0, manager unavailable은 2, owner action은 3이다. plist에는 `.env` 값이 없고 runtime worktree, uv absolute path, log path, KeepAlive/RunAtLoad만 포함한다.

- [x] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_rap_c500g_manager_main.py tests/test_render_rap_c500g_manager_launchd.py`

Expected: module import failure.

- [x] **Step 3: GREEN — CLI와 renderer 구현**

`serve`만 runtime을 생성하고 uvicorn을 loopback으로 실행한다. `status`는 SQLite read-only snapshot만 읽고 mutation을 하지 않는다. `diagnostic`은 production active일 때 fail closed한다.

- [x] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/test_rap_c500g_manager_main.py tests/test_render_rap_c500g_manager_launchd.py`

Expected: PASS.

### Task 6: 회귀·handoff·Mac mini 진단과 cutover

**Files:**
- Modify: `docs/superpowers/specs/2026-08-31-rap-c500g-local-manager-design.md`
- Modify: `docs/decision-gate.md`
- Create: `docs/handoff-prompts/2026-09-01-rap-c500g-manager-runtime-handoff.md`

**Interfaces:**
- Consumes: tracked design/plan/code commit.
- Produces: verified handoff manifest and Mac mini `DEPLOYED_VERIFIED` evidence.

- [x] **Step 1: focused와 전체 RAP 회귀 실행**

Run: `uv run pytest -q tests/test_rap_c500g_*.py tests/test_render_rap_c500g_*.py`

Expected: all pass, failures 0.

- [x] **Step 2: secret/static safety audit**

Run: `rg -n "rtsp://|R2_SECRET|SERVICE_ROLE|SLACK_WEBHOOK" backend/rap_c500g_manager* scripts/render_rap_c500g_manager_launchd.py`

Expected: safe redaction assertions/env key names 외 credential literal 0건.

- [x] **Step 3: tracked handoff gate**

Manifest에 execution repo, design/plan 절대경로, 40자리 commit SHA, implementation/runtime host, runtime kind, 기존/new service label을 기록하고 `uv run python scripts/verify_agent_handoff.py --manifest <absolute-path>`가 `HANDOFF_OK`를 출력해야 한다.

- [x] **Step 4: Mac mini read-only preflight와 60초 diagnostic**

LAN, camera 3대 RTSP, `/Volumes/RAP-C500G` RW/free, 기존 active FFmpeg 0을 확인하고 기존 recorder를 unload한 뒤 manager를 foreground diagnostic mode로 실행한다. local/R2 artifact 12, DB test captured/uploaded 3, QuickLook 3을 검증한다. 진단 실패 시 기존 recorder를 즉시 복원한다.

- [x] **Step 5: 단일-service cutover**

60초 진단 성공 뒤에만 새 `com.teraai.rap-c500g-manager`를 bootstrap한다. loaded/running/PID/working directory/HEAD를 확인하고 기존 recorder가 unloaded이며 production owner가 정확히 하나인지 검사한다.

- [x] **Step 6: 현장 UI와 rollback 증거**

Mac mini에서 `http://127.0.0.1:8766`을 열어 cam01~03, `RAP-C500G`, plan, service 상태를 확인한다. manager 실패 시 새 service를 unload하고 기존 recorder를 복원하며 기존 영상/R2/DB 삭제는 0건이어야 한다.

## Self-review

- Spec sections 1~17은 Task 1~6의 store, probe, runtime, UI, CLI/launchd, field cutover로 연결된다.
- delete/retention, camera registration, public UI, playback, ROI/YOLO/DLC/SPI는 계획에 없다.
- `ManagerPlan`, `ManagerStore`, `RapC500GManager`, `create_manager_app` 이름은 모든 task에서 일치한다.
- 미확정 상태를 뜻하는 임시 문구는 없다.

## 2026-09-01 현장 배포 결과

- Mac mini: `baeg-endeuui-Macmini.local`, Ethernet `192.168.50.12`, repo clean.
- 60초 진단: cam01~03 captured 3/3, local/R2 artifact 12/12, DB captured/uploaded 3/3.
- MP4: HEVC/hvc1 2880×1620 ffprobe 3/3, full decode 3/3, Quick Look 3/3.
- 단일 owner: 기존 recorder unloaded, manager running, production lock owner 1, active FFmpeg 0.
- UI/API: 기존 YOLO worker의 8765와 충돌하지 않는 `127.0.0.1:8766`, HTTP 200.
- probe: cam01~03 TCP 554와 RTSP 3/3, USB `RAP-C500G` RW.
- 상태 JSON: credential, RTSP URL, 실제 mount 절대경로 노출 0건.
- rollback: 기존 recorder plist를 보존했고 diagnostic 실패 branch에서만 bootstrap하도록 유지했다.
- 판정: `DEPLOYED_VERIFIED`.

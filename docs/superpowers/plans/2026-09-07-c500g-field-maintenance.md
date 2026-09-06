# RAP C500G 화요일 현장 정비 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** C500G 3카메라의 30분 녹화를 절대 벽시계 deadline으로 정렬하고, lifecycle·Slack·저장공간 관측 및 검증 기반 local prune와 1시간 현장 절차를 완성한다.

**Architecture:** 기존 `com.teraai.rap-c500g-manager` 단일 서비스와 capture-first executor 분리를 유지한다. capture child만 절대 deadline에 SIGINT/SIGKILL로 닫고, 기존 local SQLite event를 lifecycle 원장으로 확장하며, prune은 독립 CLI에서 R2 HEAD와 DB 완료를 재검증한 뒤 명시 digest가 있을 때만 local bundle을 지운다.

**Tech Stack:** Python 3.12, `subprocess.Popen`, `threading`, SQLite, FastAPI manager, Cloudflare R2 S3 HEAD, Supabase REST client, launchd, pytest, uv

**Spec:** `docs/superpowers/specs/2026-09-07-c500g-field-maintenance-design.md`

## Global Constraints

- 기준 runtime commit은 `7b0d19e9039ab5fd46089e4a86c80e99e5df8d63`이며 구현은 `codex/rap-c500g-field-maintenance`에서만 한다.
- production owner는 `com.teraai.rap-c500g-manager` 하나뿐이다.
- `/Users/baek-end/.codex/worktrees/rap-c500g-capture-first/petcam-lab`과 현재 service는 배포 gate 전까지 변경하지 않는다.
- production DB schema와 R2 object는 수정·삭제·덮어쓰지 않는다.
- local prune은 기본 dry-run이며 exact mount/root, R2 size/SHA, DB 완료, plan digest를 모두 요구한다.
- 비밀값, 전체 RTSP URL, webhook URL을 stdout·event·Slack·tracked artifact에 기록하지 않는다.
- USB 포맷, FileVault 해제, 카메라 설정 변경, 다른 LaunchAgent 변경은 금지한다.
- 각 behavior는 TDD RED 확인 뒤 최소 GREEN 구현과 focused test를 거친다.

---

### Task 1: 절대 wall-clock deadline capture runner

**Files:**
- Modify: `backend/rap_c500g_capture.py`
- Modify: `backend/rap_c500g_manager_runtime.py`
- Modify: `tests/test_rap_c500g_capture.py`
- Modify: `tests/test_rap_c500g_manager_runtime.py`

**Interfaces:**
- Produces: `CaptureDeadline(graceful_stop_monotonic: float, force_kill_monotonic: float)`
- Produces: `_run_capture_process(args, deadline, *, popen_factory, monotonic, wait_interval) -> subprocess.CompletedProcess[str]`
- Changes: `record_raw_segment(..., duration_sec, deadline: CaptureDeadline | None = None)`
- Changes: `RapC500GManager._capture_with_retries()`가 현재 slot의 monotonic deadline을 capture 함수에 전달한다.

- [ ] **Step 1: 느린 media clock RED 테스트 작성**

`tests/test_rap_c500g_capture.py`에 controllable monotonic clock과 fake `Popen`을 만들고 다음을 검증한다.

```python
def test_capture_deadline_sends_sigint_then_accepts_verified_close(tmp_path: Path) -> None:
    process = DeadlineProcess(exit_after_sigint=True, returncode=255)
    result = run_capture_process_for_test(process, graceful=1797.0, force=1799.0)
    assert process.signals == [signal.SIGINT]
    assert result.deadline_stop is True
    assert process.killed is False
```

강제 종료 case는 SIGINT 뒤 2초 동안 끝나지 않으면 해당 child만 kill되고 성공 결과를 반환하지 않아야 한다.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_rap_c500g_capture.py -k 'deadline or wall_clock'`

Expected: `CaptureDeadline` 또는 `_run_capture_process` import 실패.

- [ ] **Step 3: 최소 process deadline 구현**

`backend/rap_c500g_capture.py`에 frozen dataclass와 runner를 추가한다. deadline이 없을 때 test/diagnostic의 기존 `_default_runner` 동작을 유지한다. deadline stop에 의한 255만 별도 정상 종료 class로 전달하고, 파일·ffprobe 검사는 기존 quick gate가 그대로 결정한다.

- [ ] **Step 4: 다음 슬롯 누적 지연 RED 테스트 작성**

`tests/test_rap_c500g_manager_runtime.py`에서 24개 slot과 3개 camera를 fake clock으로 실행한다. 각 child의 media clock은 wall clock보다 3% 느리게 만들고 모든 actual start가 예정 경계에서 2초 이내인지 검증한다.

```python
assert max(item.start_delay_sec for item in starts) <= 2.0
assert len(starts) == 72
assert manager.active_capture_count() == 0
```

- [ ] **Step 5: manager deadline 전달 GREEN 구현**

`scheduled_end_kst - 3초`를 monotonic deadline으로 변환하고 force deadline을 `scheduled_end_kst - 1초`로 고정한다. 재시도마다 deadline을 늘리지 않는다. `_consume_done()`은 새 slot claim 전에 실행한다.

- [ ] **Step 6: focused GREEN 검증**

Run: `uv run pytest -q tests/test_rap_c500g_capture.py tests/test_rap_c500g_manager_runtime.py`

Expected: 모든 테스트 PASS, forced stop 뒤 stale child 0.

- [ ] **Step 7: 의도적 commit**

```bash
git add backend/rap_c500g_capture.py backend/rap_c500g_manager_runtime.py tests/test_rap_c500g_capture.py tests/test_rap_c500g_manager_runtime.py
git commit -m "fix: C500G 절대 슬롯 deadline 적용"
```

### Task 2: append-only slot lifecycle와 restart reason

**Files:**
- Modify: `backend/rap_c500g_manager_store.py`
- Modify: `backend/rap_c500g_manager_runtime.py`
- Modify: `backend/rap_c500g_pipeline.py`
- Modify: `backend/rap_c500g_manager_main.py`
- Modify: `tests/test_rap_c500g_manager_store.py`
- Modify: `tests/test_rap_c500g_manager_runtime.py`
- Modify: `tests/test_rap_c500g_pipeline.py`
- Modify: `tests/test_rap_c500g_manager_main.py`

**Interfaces:**
- Produces: `ManagerStore.append_lifecycle_once(stage: str, slot: str, camera_key: str, payload: Mapping[str, object]) -> bool`
- Produces: `ManagerStore.read_slot_lifecycle(slot: str) -> list[dict[str, object]]`
- Produces event kinds `capture_scheduled`, `capture_started`, `capture_stopped`, `raw_uploaded`, `finalize_started`, `finalize_completed`, `db_synced`, `manager_started`, `manager_stopped`.

- [ ] **Step 1: idempotent lifecycle RED 테스트**

동일 `stage/slot/camera`를 두 번 기록해도 한 row만 남고 UTC event time과 안전 필드만 허용하는 테스트를 작성한다. payload에 `password`, `rtsp://`, `/Volumes/`가 들어오면 `ValueError`가 나야 한다.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_rap_c500g_manager_store.py -k lifecycle`

Expected: lifecycle API 부재로 FAIL.

- [ ] **Step 3: 기존 manager_event 기반 GREEN 구현**

새 production table 없이 event payload에 `identity = stage|slot|camera`를 넣고 transaction 안에서 존재 확인과 insert를 수행한다. 읽기는 stage/time 순으로 반환한다.

- [ ] **Step 4: capture/pipeline boundary RED 테스트**

정상 slot이 `scheduled → started → stopped → raw_uploaded → finalize_started → finalize_completed → db_synced` 순서로 한 번씩 기록되고 restart resume에서 중복되지 않는 테스트를 추가한다.

- [ ] **Step 5: runtime/pipeline GREEN 연결**

각 단계 성공 직후 event를 기록한다. capture event에는 start delay, wall elapsed, stop class만 넣고 local path나 URL은 넣지 않는다. DB upsert가 반환된 뒤에만 `db_synced`를 쓴다.

- [ ] **Step 6: process lifecycle RED→GREEN**

`manager_started`는 process 시작 시 boot marker와 이전 종료 분류를, `manager_stopped`는 정상 shutdown reason을 기록한다. fatal callback 전 `manager_fatal`은 기존처럼 남긴다. test에서는 정상 signal, fatal, launchd 재시작 추정이 서로 다른 상태인지 검증한다.

- [ ] **Step 7: focused 검증과 commit**

Run: `uv run pytest -q tests/test_rap_c500g_manager_store.py tests/test_rap_c500g_manager_runtime.py tests/test_rap_c500g_pipeline.py tests/test_rap_c500g_manager_main.py`

```bash
git add backend/rap_c500g_manager_store.py backend/rap_c500g_manager_runtime.py backend/rap_c500g_pipeline.py backend/rap_c500g_manager_main.py tests/test_rap_c500g_manager_store.py tests/test_rap_c500g_manager_runtime.py tests/test_rap_c500g_pipeline.py tests/test_rap_c500g_manager_main.py
git commit -m "feat: C500G 슬롯 생명주기 원장 추가"
```

### Task 3: Slack delivery receipt와 storage runway 경보

**Files:**
- Modify: `backend/rap_c500g_manager_notify.py`
- Modify: `backend/rap_c500g_manager_probe.py`
- Modify: `backend/rap_c500g_manager_runtime.py`
- Modify: `backend/rap_c500g_manager_store.py`
- Modify: `tests/test_rap_c500g_manager_notify.py`
- Modify: `tests/test_rap_c500g_manager_probe.py`
- Modify: `tests/test_rap_c500g_manager_runtime.py`

**Interfaces:**
- Produces: `SlackDeliveryResult(delivered: bool, status_class: str, elapsed_ms: int)`
- Produces: `StorageRunway(free_bytes: int, mean_night_bytes: int | None, estimated_nights: float | None, state: str)`
- Produces: `calculate_storage_runway(free_bytes: int, completed_night_bytes: Sequence[int]) -> StorageRunway`

- [ ] **Step 1: Slack receipt RED 테스트**

2xx, HTTP 4xx/5xx, timeout, webhook disabled를 fake opener로 검증한다. 결과에는 URL·body가 없어야 하고 status class와 elapsed milliseconds만 있어야 한다.

- [ ] **Step 2: RED 확인 및 GREEN 구현**

Run: `uv run pytest -q tests/test_rap_c500g_manager_notify.py -k delivery`

Expected: `SlackDeliveryResult` import 실패.

notifier가 exception을 외부로 던지지 않고 안전 결과를 반환하게 한다. manager는 결과를 `slack_delivery` event로 기록하며 capture 결과는 바꾸지 않는다.

- [ ] **Step 3: runway 경계 RED 테스트**

`35 GiB`, `2.0 nights`, 회복 hysteresis `40 GiB/2.5 nights`, 이력 없음 case를 table-driven test로 고정한다.

```python
@pytest.mark.parametrize(("free_gib", "nights", "state"), [
    (34.9, 3.0, "low"),
    (50.0, 1.9, "low"),
    (50.0, None, "insufficient_history"),
    (50.0, 3.0, "ok"),
])
def test_storage_runway_thresholds(free_gib, nights, state): ...
```

- [ ] **Step 4: aggregate-only GREEN 구현**

완결된 최근 최대 3개 night의 pipeline media bytes만 합산하고 clip path를 payload에 넣지 않는다. slot summary/night acceptance 시점에만 계산하며 low/recovered transition은 `append_event_once`로 억제한다.

- [ ] **Step 5: focused 검증과 commit**

Run: `uv run pytest -q tests/test_rap_c500g_manager_notify.py tests/test_rap_c500g_manager_probe.py tests/test_rap_c500g_manager_runtime.py`

```bash
git add backend/rap_c500g_manager_notify.py backend/rap_c500g_manager_probe.py backend/rap_c500g_manager_runtime.py backend/rap_c500g_manager_store.py tests/test_rap_c500g_manager_notify.py tests/test_rap_c500g_manager_probe.py tests/test_rap_c500g_manager_runtime.py
git commit -m "feat: C500G 전달 영수증과 저장공간 경보 추가"
```

### Task 4: 검증 기반 local prune CLI

**Files:**
- Create: `backend/rap_c500g_local_prune.py`
- Create: `scripts/prune_rap_c500g_local.py`
- Create: `tests/test_rap_c500g_local_prune.py`
- Modify: `docs/runbooks/rap-c500g-recorder.md`

**Interfaces:**
- Produces: `PruneCandidate(bundle_dir: Path, bytes_total: int, identity_digest: str)`
- Produces: `PrunePlan(candidates: tuple[PruneCandidate, ...], excluded: Mapping[str, int], plan_digest: str)`
- Produces: `build_prune_plan(root: Path, *, uploader, repository, store, now: datetime) -> PrunePlan`
- Produces: `execute_prune(plan: PrunePlan, *, supplied_digest: str, receipt_dir: Path) -> PruneReceipt`
- CLI: `uv run python scripts/prune_rap_c500g_local.py --root /Volumes/RAP-C500G/RAP-c500g-recordings [--execute --plan-digest SHA256]`

- [ ] **Step 1: fail-closed path RED 테스트**

임시 mount adapter를 사용해 wrong basename, non-mount, symlink root, path escape, active claim을 모두 거부한다. 실제 `/Volumes`나 production DB/R2는 사용하지 않는다.

- [ ] **Step 2: provenance RED 테스트**

fake local manifest, fake R2 HEAD, fake repository를 사용해 size/SHA 불일치, DB 미완료, manifest-last 실패, pipeline 실패를 각각 제외하는 테스트를 쓴다. 네 검증이 모두 맞는 bundle만 candidate가 된다.

- [ ] **Step 3: RED 확인**

Run: `uv run pytest -q tests/test_rap_c500g_local_prune.py`

Expected: module import 실패.

- [ ] **Step 4: deterministic dry-run GREEN 구현**

candidate는 stable identity digest로 정렬한다. 출력은 count/bytes/excluded reason/plan digest만 포함하고 bundle path나 key를 출력하지 않는다. 동일 입력 3회 plan digest가 byte-identical이어야 한다.

- [ ] **Step 5: explicit execution RED→GREEN**

`--execute` 단독, 잘못된 digest, dry-run 이후 상태 변화는 모두 delete call 0이어야 한다. 일치할 때만 각 bundle의 네 exact artifact를 `Path.unlink()`로 지우고 빈 leaf 디렉터리만 `rmdir()`한다. 첫 실패 뒤 추가 unlink 0을 검증한다.

- [ ] **Step 6: receipt와 idempotency 검증**

receipt directory는 mode 0700, receipt는 write-new-only mode 0600이다. 재실행은 이미 없는 bundle을 성공으로 과장하지 않고 새 plan에서 제외한다. R2/DB delete API는 인터페이스에 존재하지 않게 한다.

- [ ] **Step 7: focused 검증과 commit**

Run: `uv run pytest -q tests/test_rap_c500g_local_prune.py tests/test_rap_c500g_manifest.py tests/test_rap_c500g_r2.py tests/test_rap_c500g_repository.py`

```bash
git add backend/rap_c500g_local_prune.py scripts/prune_rap_c500g_local.py tests/test_rap_c500g_local_prune.py docs/runbooks/rap-c500g-recorder.md
git commit -m "feat: C500G 검증 기반 로컬 정리 도구 추가"
```

### Task 5: launchd·전원·USB 복구 및 현장 one-hour runner

**Files:**
- Modify: `scripts/render_rap_c500g_manager_launchd.py`
- Create: `scripts/audit_rap_c500g_field_readiness.py`
- Create: `tests/test_audit_rap_c500g_field_readiness.py`
- Modify: `tests/test_render_rap_c500g_manager_launchd.py`
- Modify: `docs/runbooks/rap-c500g-recorder.md`

**Interfaces:**
- Produces: `FieldReadinessResult` with aggregate booleans for host, power, login dependency, Ethernet, camera probes, volume, service, lifecycle, storage runway.
- CLI: `uv run python scripts/audit_rap_c500g_field_readiness.py --state-path ... --json`
- launchd remains `RunAtLoad=true`, `KeepAlive=true`, exact WorkingDirectory, secret-free environment.

- [ ] **Step 1: readiness RED 테스트**

subprocess adapter를 fake로 주입해 `pmset`, FileVault, loginwindow, route, network link, TCP 554, mount identity, launchctl 결과를 aggregate-only로 변환한다. command stderr에 secret-like input이 있어도 output에서 제거되는지 검증한다.

- [ ] **Step 2: RED 확인과 GREEN 구현**

Run: `uv run pytest -q tests/test_audit_rap_c500g_field_readiness.py`

Expected: script import 실패.

readiness CLI는 설정을 바꾸지 않는다. `autorestart=0`, sleep enabled, no auto-login with LaunchAgent, non-Ethernet default route, wrong mount를 각각 owner action으로 표시한다.

- [ ] **Step 3: launchd recovery RED→GREEN**

plist가 absolute worktree, state DB, log dir를 고정하고 `ProcessType=Background`, `RunAtLoad`, `KeepAlive`를 유지하는지 검증한다. 다른 label이나 credential 환경변수가 들어가면 실패한다.

- [ ] **Step 4: 현장 runbook 명령 고정**

runbook에 0~10, 10~20, 20~30, 30~60분 순서를 쓰고 다음 규칙을 명시한다.

```text
readiness audit → prune dry-run → optional exact-digest execute
→ target service graceful bootout → active owned ffmpeg 0
→ 30-minute test namespace canary → local/R2/DB verification
→ success bootstrap, failure previous plist bootstrap
```

관리자 변경은 현장 Owner 확인 뒤 `sudo pmset -a sleep 0 autorestart 1`만 허용하고, 변경 전 값을 durable audit에 기록한다. FileVault·auto-login은 자동 변경하지 않는다.

- [ ] **Step 5: focused 검증과 commit**

Run: `uv run pytest -q tests/test_audit_rap_c500g_field_readiness.py tests/test_render_rap_c500g_manager_launchd.py tests/test_rap_c500g_manager_probe.py`

```bash
git add scripts/audit_rap_c500g_field_readiness.py scripts/render_rap_c500g_manager_launchd.py tests/test_audit_rap_c500g_field_readiness.py tests/test_render_rap_c500g_manager_launchd.py docs/runbooks/rap-c500g-recorder.md
git commit -m "feat: C500G 현장 복구 점검 자동화"
```

### Task 6: 전체 검증, handoff 갱신, 배포 전 freeze

**Files:**
- Modify: `docs/superpowers/specs/2026-09-07-c500g-field-maintenance-design.md`
- Modify: `docs/superpowers/plans/2026-09-07-c500g-field-maintenance.md`
- Modify: `docs/handoff-prompts/2026-09-07-c500g-field-maintenance-handoff.md`
- Modify: `docs/runbooks/rap-c500g-recorder.md`

**Interfaces:**
- Consumes: Task 1~5의 code/tests와 aggregate evidence.
- Produces: clean tracked implementation SHA와 literal `HANDOFF_OK`.

- [ ] **Step 1: focused와 관련 회귀 실행**

Run:

```bash
uv run pytest -q tests/test_rap_c500g_*.py tests/test_render_rap_c500g_launchd.py tests/test_render_rap_c500g_manager_launchd.py tests/test_audit_rap_c500g_field_readiness.py
```

Expected: 실패 0.

- [ ] **Step 2: 정적·보안 검증**

Run:

```bash
uv run python -m compileall -q backend scripts tests
git diff --check
git grep -nE 'rtsp://[^ ]+@|R2_C500G_SECRET_ACCESS_KEY=|SLACK_WEBHOOK_URL=https://' -- backend scripts tests docs
```

Expected: compile/diff PASS, secret scan match 0.

- [ ] **Step 3: fake 24-slot acceptance 실행**

Run: `uv run pytest -q tests/test_rap_c500g_manager_runtime.py -k 'wall_clock or deadline or twenty_four'`

Expected: 72 starts, p95 `<=2초`, 누적 지연 0, stale child 0.

- [ ] **Step 4: production read-only preflight**

현재 service label/WD/HEAD, SQLite baseline count, local/R2/DB aggregate, USB mount/free space를 read-only로 고정한다. prune은 dry-run까지만 실행하고 delete call 0을 확인한다.

- [ ] **Step 5: 문서 상태와 runtime SHA 갱신 및 commit**

구현 검증값을 문서에 additive 기록한다. handoff의 `commit_sha`는 design/plan/runbook과 구현을 포함한 clean 40자리 SHA로 고정하고, manifest-only descendant 규칙을 사용한다.

```bash
git add docs/superpowers/specs/2026-09-07-c500g-field-maintenance-design.md docs/superpowers/plans/2026-09-07-c500g-field-maintenance.md docs/runbooks/rap-c500g-recorder.md
git commit -m "docs: C500G 현장 정비 구현 검증 기록"
```

그 SHA를 manifest에 기록한 뒤 manifest만 별도 commit한다.

- [ ] **Step 6: literal HANDOFF_OK 확인**

Run:

```bash
uv run python scripts/verify_agent_handoff.py --manifest /Users/baek-end/.codex/worktrees/rap-c500g-field-maintenance/petcam-lab/docs/handoff-prompts/2026-09-07-c500g-field-maintenance-handoff.md
```

Expected: `HANDOFF_OK task=rap-c500g-field-maintenance repo=petcam-lab commit=<8자> runtime=launchagent@baeg-endeuui-Macmini.local`

- [ ] **Step 7: 배포 전 stop point**

운영 service, plist, USB, R2, DB가 baseline과 동일한지 확인하고 `FIELD_MAINTENANCE_IMPLEMENTED_VERIFIED`로 보고한다. 별도 runtime 배포 승인 범위가 확인되기 전에는 bootout/bootstrap/canary를 실행하지 않는다.

### Task 7: 화요일 1시간 canary, 조건부 배포, rollback

**Files:**
- Modify after evidence: `docs/runbooks/rap-c500g-recorder.md`
- Modify after evidence: `docs/handoff-prompts/2026-09-07-c500g-field-maintenance-handoff.md`

**Interfaces:**
- Consumes: Task 6 clean SHA/HANDOFF_OK and previous plist/HEAD baseline.
- Produces: `FIELD_MAINTENANCE_CANARY_VERIFIED`, `FIELD_MAINTENANCE_DEPLOYED_VERIFIED`, or `FIELD_MAINTENANCE_ROLLED_BACK`.

- [ ] **Step 1: 현장 baseline과 rollback bundle 고정**

target service의 label, plist SHA, WorkingDirectory, HEAD, state DB count와 active FFmpeg를 기록한다. 다른 LaunchAgent는 조회 외 접근하지 않는다.

- [ ] **Step 2: readiness와 optional prune**

readiness audit를 실행하고 USB 포맷 없이 blocker를 해소한다. prune은 dry-run 결과와 Owner가 확인한 동일 plan digest가 있을 때만 한 번 실행한다.

- [ ] **Step 3: target만 graceful stop**

`launchctl bootout gui/$(id -u)/com.teraai.rap-c500g-manager` 뒤 manager-owned FFmpeg 0을 확인한다. 실패하면 canary를 시작하지 않는다.

- [ ] **Step 4: 30분 3카메라 test canary**

test namespace에서 정확히 한 번 실행한다. local/R2/DB 기존 production identity와 분리하고 다음을 검증한다.

```text
camera 3/3, start-delay p95 <=2초, stale child 0
local artifacts 12/12, ffprobe/full decode 3/3
R2 HEAD size/SHA 12/12, manifest-last 3/3, DB rows 3/3
```

- [ ] **Step 5: 성공 배포 또는 즉시 rollback**

전부 통과하면 새 plist를 exact worktree SHA로 렌더하고 target label만 bootstrap한다. 하나라도 실패하면 새 target을 unload하고 기존 plist를 bootstrap한다. local/R2/DB evidence는 삭제하지 않는다.

- [ ] **Step 6: 자연 슬롯 2회 검증**

연속 두 슬롯의 camera 6개 start delay p95 `<=2초`, raw R2 6/6, retry/terminal 0을 확인한다. 실패하면 target만 이전 runtime으로 rollback한다.

- [ ] **Step 7: 최종 evidence commit**

실제 상태를 runbook/handoff report에 기록하고 검증을 다시 실행한다. branch 통합·push는 별도 Owner 범위에 따른다.

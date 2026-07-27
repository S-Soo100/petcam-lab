# R1 Mac mini Research Runtime Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mac mini에서 승인된 synthetic research job을 중복 없이 실행·복구하고 SSH로 관측하는 durable local runtime foundation을 만든다.

**Architecture:** 사람 주도 구현은 A→M→B→C RUN-MANIFEST lifecycle로 통제하고, 반복 job은 Git을 변경하지 않는 ledger-native job spec으로 실행한다. SQLite는 현재 상태, fsync JSONL은 감사 이력, attempt별 디렉터리는 결과를 분리한다. runner는 single concurrency, boot/PID/lease epoch fencing, production lock·quiet-window 양보, 쓰기 전 redaction을 강제한다.

**Tech Stack:** Python 3.12 stdlib (`sqlite3`, `fcntl`, `subprocess`, `signal`, `json`, `hashlib`, `pathlib`, `argparse`), launchd plist, pytest.

## Global Constraints

- R1 workload는 `synthetic_noop_v1` 하나뿐이며 DB, R2, media, model, Claude/VLM을 호출하지 않는다.
- 구현 RUN-MANIFEST는 `runtime_kind: none`, `max_permission: P1`, provider call·cost 0이다.
- 실제 Mac mini checkout, LaunchAgent bootstrap, 재부팅, 24시간 시험은 별도 P3 package다.
- runner는 Git commit·push를 실행하지 않는다.
- production flock을 보유한 채 연구를 실행하지 않는다.
- max concurrency는 1이다.
- runtime files는 `storage/research-runtime/` 아래에서 `0700/0600` 권한만 사용한다.
- raw child stdout/stderr, secret, signed URL, email, RTSP URL을 디스크나 CLI에 출력하지 않는다.
- SQLite 현재 상태와 append-only JSONL 감사 원장을 서로 대체하지 않는다.
- 코드 변경은 Task별 TDD RED→GREEN과 task별 commit으로 수행한다.

---

## File map

| 파일 | 책임 |
|---|---|
| `backend/research_runtime/contracts.py` | 상태·exit code·dataclass·공통 enum |
| `backend/research_runtime/job_spec.py` | duplicate-key-safe parser와 allowlisted job spec |
| `backend/research_runtime/paths.py` | secure runtime root, umask, 권한 |
| `backend/research_runtime/redaction.py` | 쓰기 전 redaction |
| `backend/research_runtime/ledger.py` | SQLite schema, transaction, CAS, recovery |
| `backend/research_runtime/events.py` | append-only JSONL flush+fsync |
| `backend/research_runtime/production_guard.py` | lock probe와 quiet-window 판정 |
| `backend/research_runtime/budget.py` | monotonic wall budget와 absolute deadline |
| `backend/research_runtime/supervisor.py` | child process group, cancel, TERM/KILL |
| `backend/research_runtime/handlers.py` | handler registry와 `synthetic_noop_v1` |
| `backend/research_runtime/runner.py` | singleton loop, claim, execute, recover |
| `backend/research_runtime/cli.py` | `researchctl` 명령 |
| `config/research-runtime-quiet-windows.json` | tracked KST 예약창 |
| `scripts/install_research_runtime_launchd.sh` | P3에서 사용할 fail-closed installer |
| `scripts/run_research_runtime_adversarial.py` | synthetic adversarial suite |

---

### Task 1: 공통 계약과 secure runtime paths

**Files:**
- Create: `backend/research_runtime/__init__.py`
- Create: `backend/research_runtime/contracts.py`
- Create: `backend/research_runtime/paths.py`
- Create: `tests/research_runtime/test_contracts_paths.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `JobState`, `RuntimeExit`, `RuntimePaths`, `initialize_runtime_paths(root: Path) -> RuntimePaths`
- Consumes: 없음

- [ ] **Step 1: RED 테스트 작성**

```python
from pathlib import Path

from backend.research_runtime.contracts import JobState, RuntimeExit
from backend.research_runtime.paths import initialize_runtime_paths


def test_runtime_contract_is_single_concurrency_and_versioned(tmp_path: Path) -> None:
    assert JobState.values() == (
        "queued", "running", "deferred", "blocked",
        "succeeded", "failed", "cancelled",
    )
    assert RuntimeExit.OK == 0
    assert RuntimeExit.LEDGER_FAILURE == 5


def test_initialize_runtime_paths_uses_private_permissions(tmp_path: Path) -> None:
    paths = initialize_runtime_paths(tmp_path / "runtime")
    assert paths.root.stat().st_mode & 0o777 == 0o700
    assert paths.jobs.stat().st_mode & 0o777 == 0o700
    assert paths.events.stat().st_mode & 0o777 == 0o700
    assert paths.ledger.parent == paths.root
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/research_runtime/test_contracts_paths.py`

Expected: FAIL with `ModuleNotFoundError: backend.research_runtime`.

- [ ] **Step 3: 최소 계약 구현**

```python
# backend/research_runtime/contracts.py
from enum import IntEnum, StrEnum


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DEFERRED = "deferred"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(item.value for item in cls)


class RuntimeExit(IntEnum):
    OK = 0
    INVALID_INPUT = 2
    PREFLIGHT_MISMATCH = 3
    JOB_NOT_FOUND = 4
    LEDGER_FAILURE = 5
    SAFETY_VIOLATION = 6
```

```python
# backend/research_runtime/paths.py
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    root: Path
    ledger: Path
    events: Path
    jobs: Path


def initialize_runtime_paths(root: Path) -> RuntimePaths:
    os.umask(0o077)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    events = root / "events"
    jobs = root / "jobs"
    for directory in (root, events, jobs):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    return RuntimePaths(
        root=root,
        ledger=root / "ledger.sqlite3",
        events=events / "events.jsonl",
        jobs=jobs,
    )
```

Add `storage/research-runtime/` to `.gitignore`.

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/research_runtime/test_contracts_paths.py`

Expected: PASS.

- [ ] **Step 5: commit**

```bash
git add .gitignore backend/research_runtime tests/research_runtime/test_contracts_paths.py
git commit -m "feat: R1 runtime 기본 계약과 보안 경로"
```

---

### Task 2: job spec parser와 handler allowlist

**Files:**
- Create: `backend/research_runtime/job_spec.py`
- Create: `backend/research_runtime/handlers.py`
- Create: `tests/research_runtime/test_job_spec.py`
- Create: `tests/research_runtime/test_handlers.py`

**Interfaces:**
- Consumes: `RuntimeExit`
- Produces: `JobSpec`, `parse_job_spec(path: Path, now: datetime) -> JobSpec`, `handler_for(name: str) -> JobHandler`

- [ ] **Step 1: RED parser 테스트 작성**

```python
def test_job_spec_accepts_only_noop_and_zero_external_budget(tmp_path, valid_spec):
    path = tmp_path / "job.json"
    path.write_text(json.dumps(valid_spec), encoding="utf-8")
    parsed = parse_job_spec(path, now=datetime(2026, 7, 28, tzinfo=timezone.utc))
    assert parsed.handler == "synthetic_noop_v1"
    assert parsed.resources == ()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(handler="shell"),
        lambda value: value["budget"].update(max_provider_calls=1),
        lambda value: value.update(password="not-allowed"),
        lambda value: value.update(job_id="../escape"),
    ],
)
def test_job_spec_fails_closed(tmp_path, valid_spec, mutation):
    mutation(valid_spec)
    path = tmp_path / "job.json"
    path.write_text(json.dumps(valid_spec), encoding="utf-8")
    with pytest.raises(JobSpecError):
        parse_job_spec(path, now=datetime(2026, 7, 28, tzinfo=timezone.utc))
```

Add duplicate-key, expired deadline, uppercase SHA, unknown field, noncanonical string, and same-id
different-bytes cases.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/research_runtime/test_job_spec.py tests/research_runtime/test_handlers.py`

Expected: FAIL because parser and registry do not exist.

- [ ] **Step 3: parser와 registry 구현**

```python
@dataclass(frozen=True, slots=True)
class JobSpec:
    schema_version: int
    job_id: str
    task_id: str
    handler: str
    handler_args: Mapping[str, int]
    manifest_blob_sha: str
    manifest_commit_sha: str
    repo_head: str
    expected_host: str
    max_provider_calls: int
    max_cost_krw: int
    max_wall_seconds: int
    deadline: datetime
    resources: tuple[str, ...]
    privacy_class: str
    canonical_bytes: bytes
```

Use `json.loads(..., object_pairs_hook=reject_duplicate_keys)`. Validate exact field sets and refuse
secret-key names recursively. `handler_for()` must index a constant mapping containing only
`synthetic_noop_v1`.

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/research_runtime/test_job_spec.py tests/research_runtime/test_handlers.py`

Expected: PASS.

- [ ] **Step 5: commit**

```bash
git add backend/research_runtime/job_spec.py backend/research_runtime/handlers.py tests/research_runtime
git commit -m "feat: R1 job spec과 noop handler allowlist"
```

---

### Task 3: 쓰기 전 redaction

**Files:**
- Create: `backend/research_runtime/redaction.py`
- Create: `tests/research_runtime/test_redaction.py`

**Interfaces:**
- Produces: `redact_text(text: str, *, home: Path) -> str`, `safe_error_detail(value: str) -> str`
- Consumes: 없음

- [ ] **Step 1: RED corpus 테스트 작성**

```python
@pytest.mark.parametrize(
    "secret",
    [
        "Authorization: Bearer fake-token-value",
        "https://example.invalid/x?X-Amz-Signature=abcdef",
        "rtsp://user:pass@example.invalid/live",
        "SLACK_WEBHOOK_URL=https://hooks.slack.invalid/abc",
        "owner@example.com",
        "/Users/baek-end/private/file",
    ],
)
def test_redactor_removes_secret_like_values(secret: str) -> None:
    redacted = redact_text(secret, home=Path("/Users/baek-end"))
    assert secret not in redacted
    assert "fake-token-value" not in redacted
    assert "pass@" not in redacted
    assert "/Users/baek-end" not in redacted
```

Test undecodable bytes are represented only by stable `binary_output_blocked`.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/research_runtime/test_redaction.py`

Expected: FAIL because module does not exist.

- [ ] **Step 3: redactor 구현**

Compile bounded regex patterns for Bearer, signed query parameters, RTSP credentials, webhook URLs,
email, key/token assignments, and absolute home path. Apply every pattern before truncating to 512
characters. Never return the original string on redactor failure.

```python
def safe_error_detail(value: str, *, home: Path) -> str:
    try:
        return redact_text(value, home=home)[:512]
    except (ValueError, UnicodeError, re.error):
        return "redaction_failed"
```

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/research_runtime/test_redaction.py`

Expected: PASS.

- [ ] **Step 5: commit**

```bash
git add backend/research_runtime/redaction.py tests/research_runtime/test_redaction.py
git commit -m "feat: R1 로그 쓰기 전 비밀값 차단"
```

---

### Task 4: SQLite ledger와 append-only event log

**Files:**
- Create: `backend/research_runtime/ledger.py`
- Create: `backend/research_runtime/events.py`
- Create: `tests/research_runtime/test_ledger.py`
- Create: `tests/research_runtime/test_events.py`

**Interfaces:**
- Consumes: `JobSpec`, `JobState`, `RuntimePaths`, `safe_error_detail`
- Produces: `Ledger.open(paths)`, `enqueue`, `claim`, `heartbeat`, `transition`, `request_cancel`, `recoverable_jobs`

- [ ] **Step 1: RED ledger 테스트 작성**

Cover:

- WAL/FULL/busy_timeout/foreign_keys pragmas
- byte-identical enqueue idempotency and different spec conflict
- claim increments `lease_epoch`
- stale epoch heartbeat/transition updates 0 rows
- concurrent claim returns one owner
- DB/WAL/SHM modes are private
- schema version mismatch fails without creating a replacement DB

```python
def test_stale_epoch_cannot_commit_result(ledger, queued_spec):
    ledger.enqueue(queued_spec)
    first = ledger.claim(boot_id="boot-a", pid=100, now_mono=1.0, now_utc=NOW)
    ledger.reclaim_dead(first.job_id, expected_epoch=first.lease_epoch, pid=101)
    assert ledger.transition(
        first.job_id,
        expected_epoch=first.lease_epoch,
        target=JobState.SUCCEEDED,
    ) is False
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/research_runtime/test_ledger.py tests/research_runtime/test_events.py`

Expected: FAIL because ledger/events do not exist.

- [ ] **Step 3: schema와 CAS 구현**

Every state-changing method opens `BEGIN IMMEDIATE`, validates current state and epoch, performs one
bounded update, commits, then appends a redacted event through `EventWriter`.

```python
UPDATE jobs
SET state = ?, heartbeat_at_utc = ?, lease_expires_monotonic = ?
WHERE job_id = ? AND state = 'running' AND lease_epoch = ?
```

`EventWriter.append()` writes one canonical JSON line, flushes, and calls `os.fsync()`. Failure raises
`EventWriteError`; caller moves the job to `blocked` in a new transaction without reporting success.

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/research_runtime/test_ledger.py tests/research_runtime/test_events.py`

Expected: PASS.

- [ ] **Step 5: commit**

```bash
git add backend/research_runtime/ledger.py backend/research_runtime/events.py tests/research_runtime
git commit -m "feat: R1 SQLite ledger와 감사 원장"
```

---

### Task 5: production coexistence gate

**Files:**
- Create: `backend/research_runtime/production_guard.py`
- Create: `config/research-runtime-quiet-windows.json`
- Create: `tests/research_runtime/test_production_guard.py`

**Interfaces:**
- Produces: `GuardDecision`, `probe_lock(path: Path) -> bool`, `evaluate_guard(now, config, segment_seconds) -> GuardDecision`
- Consumes: job budget

- [ ] **Step 1: RED 경계 테스트 작성**

```python
def test_guard_defers_without_holding_busy_production_lock(tmp_path):
    lock_path = tmp_path / "activity.lock"
    with held_flock(lock_path):
        decision = evaluate_guard(
            now=KST_DATETIME,
            config=config_for(lock_path),
            segment_seconds=300,
        )
    assert decision.allowed is False
    assert decision.reason == "activity_lock_busy"


def test_guard_defers_when_segment_plus_buffer_crosses_reserved_window():
    decision = evaluate_guard(
        now=datetime(2026, 7, 28, 10, 21, tzinfo=KST),
        config=DEFAULT_CONFIG,
        segment_seconds=300,
    )
    assert decision.allowed is False
    assert decision.reason == "quiet_window_insufficient"
```

Test exact `:25`, `:35`, `:55` boundaries, VLM 22/00/02/04 windows, invalid config, and lock probe
release.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/research_runtime/test_production_guard.py`

Expected: FAIL because guard/config do not exist.

- [ ] **Step 3: tracked config와 evaluator 구현**

```json
{
  "schema_version": 1,
  "timezone": "Asia/Seoul",
  "segment_max_seconds": 300,
  "minimum_buffer_seconds": 300,
  "locks": [
    {"name": "vlm", "path": "/tmp/petcam-vlm-candidate-worker.lock"},
    {"name": "activity", "path": "/tmp/petcam-activity-worker.lock"}
  ],
  "windows": [
    {"name": "regular-vlm", "hours": [0, 2, 4, 22], "minute": 0, "before_minutes": 30, "after_minutes": 15},
    {"name": "rolling-backfill", "hours": "every", "minute": 35, "before_minutes": 10, "after_minutes": 20}
  ]
}
```

`probe_lock` acquires nonblocking and immediately releases. It never returns an open lock handle.

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/research_runtime/test_production_guard.py`

Expected: PASS.

- [ ] **Step 5: commit**

```bash
git add backend/research_runtime/production_guard.py config/research-runtime-quiet-windows.json tests/research_runtime/test_production_guard.py
git commit -m "feat: R1 production 양보 게이트"
```

---

### Task 6: budget와 child process supervisor

**Files:**
- Create: `backend/research_runtime/budget.py`
- Create: `backend/research_runtime/supervisor.py`
- Create: `tests/research_runtime/test_budget.py`
- Create: `tests/research_runtime/test_supervisor.py`

**Interfaces:**
- Produces: `RuntimeBudget`, `ProcessSupervisor.run(argv, ...) -> ProcessResult`
- Consumes: `redact_text`, ledger cancel callback, heartbeat callback

- [ ] **Step 1: RED 테스트 작성**

Test monotonic timeout, absolute deadline before start, cancel, TERM grace then KILL, bounded redacted
log, process-group cleanup, and no raw output file.

```python
def test_supervisor_escalates_cancel_and_cleans_process_group(fake_process, ledger):
    result = supervisor.run(
        argv=(sys.executable, "-c", IGNORE_TERM_SCRIPT),
        budget=RuntimeBudget(wall_seconds=2, deadline=FUTURE),
        cancel_requested=lambda: True,
    )
    assert result.outcome == "cancelled"
    assert fake_process.signals == [signal.SIGTERM, signal.SIGKILL]
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/research_runtime/test_budget.py tests/research_runtime/test_supervisor.py`

Expected: FAIL because modules do not exist.

- [ ] **Step 3: budget와 supervisor 구현**

Use `time.monotonic()` for elapsed wall budget and aware UTC for absolute deadline. Spawn with
`start_new_session=True`. Read pipes incrementally, redact, and rotate at 10 MiB with three files.
Call heartbeat every five seconds and before every state transition.

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/research_runtime/test_budget.py tests/research_runtime/test_supervisor.py`

Expected: PASS.

- [ ] **Step 5: commit**

```bash
git add backend/research_runtime/budget.py backend/research_runtime/supervisor.py tests/research_runtime
git commit -m "feat: R1 budget과 child process 감독"
```

---

### Task 7: runner claim·recovery·defer loop

**Files:**
- Create: `backend/research_runtime/runner.py`
- Create: `backend/research_runtime/main.py`
- Create: `tests/research_runtime/test_runner.py`

**Interfaces:**
- Consumes: paths, ledger, handlers, guard, budget, supervisor
- Produces: `run_once(...) -> RuntimeExit`, `recover_stale_jobs(...) -> RecoverySummary`

- [ ] **Step 1: RED recovery 테스트 작성**

Cover:

- wrong host and dirty/wrong HEAD before ledger mutation
- second runner singleton rejection
- other boot immediate reclaim
- same boot alive PID no reclaim
- same boot dead PID reclaim once
- unknown PID blocked
- deferred yield count and 12/6h blocked threshold
- stale attempt result CAS 0
- handler exception sanitized
- temp/result attempt isolation

```python
def test_other_boot_reclaims_once(ledger, running_job):
    summary = recover_stale_jobs(
        ledger,
        current_boot_id="boot-b",
        pid_alive=lambda _: False,
    )
    assert summary.reclaimed == 1
    assert ledger.get(running_job.job_id).attempt == 2
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/research_runtime/test_runner.py`

Expected: FAIL because runner does not exist.

- [ ] **Step 3: runner 구현**

Order is fixed:

1. expected host
2. repo root, branch, HEAD, tracked clean
3. singleton flock
4. runtime path and ledger integrity
5. stale recovery
6. guard evaluation
7. claim one job
8. attempt directory creation
9. supervised handler
10. CAS final transition and residue check

`run_once` handles one job and exits; LaunchAgent `StartInterval=60` supplies polling. No infinite loop is
introduced in R1.

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/research_runtime/test_runner.py`

Expected: PASS.

- [ ] **Step 5: commit**

```bash
git add backend/research_runtime/runner.py backend/research_runtime/main.py tests/research_runtime/test_runner.py
git commit -m "feat: R1 runner 복구와 양보 실행"
```

---

### Task 8: `researchctl` submit·관측·cancel

**Files:**
- Create: `backend/research_runtime/cli.py`
- Create: `scripts/researchctl`
- Create: `tests/research_runtime/test_cli.py`

**Interfaces:**
- Consumes: `parse_job_spec`, `Ledger`, `RuntimeExit`, redacted logs
- Produces: stable CLI and JSON schema version 1

- [ ] **Step 1: RED CLI 테스트 작성**

```python
def test_status_json_is_versioned_and_secret_free(cli, seeded_ledger):
    result = cli("status", "--json")
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["jobs"][0]["state"] == "queued"
    assert "manifest_blob_sha" not in payload["jobs"][0]
    assert "token" not in result.stdout.lower()


def test_cancel_only_records_intent(cli, running_job):
    result = cli("cancel", running_job.job_id)
    assert result.returncode == 0
    assert ledger.get(running_job.job_id).state == "running"
    assert ledger.get(running_job.job_id).cancel_requested_at is not None
```

Test exit codes 2–6, missing job, idempotent submit, conflicting submit, bounded tail, corrupt ledger, and
wrong host.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/research_runtime/test_cli.py`

Expected: FAIL because CLI does not exist.

- [ ] **Step 3: CLI 구현**

`scripts/researchctl` is a thin executable that runs
`uv run python -m backend.research_runtime.cli "$@"` from its own repo root. JSON output contains only
allowlisted fields and stable machine error codes.

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/research_runtime/test_cli.py`

Expected: PASS.

- [ ] **Step 5: commit**

```bash
git add backend/research_runtime/cli.py scripts/researchctl tests/research_runtime/test_cli.py
git commit -m "feat: R1 researchctl 제출과 원격 관측"
```

---

### Task 9: LaunchAgent artifact와 fail-closed installer

**Files:**
- Create: `scripts/install_research_runtime_launchd.sh`
- Create: `tests/research_runtime/test_install_launchd.py`
- Modify: `CLAUDE.md`
- Modify: `docs/ENV.md`

**Interfaces:**
- Consumes: runner module, expected Mac mini path/host, quiet-window config
- Produces: plist `com.petcam.research-runtime`, rollback command

- [ ] **Step 1: RED installer 테스트 작성**

Render into a temporary HOME with stubbed `hostname`, `uv`, `plutil`, and `launchctl`. Assert:

- missing/mismatched expected host exits before plist write
- dirty/wrong HEAD exits before launchctl
- PATH contains actual uv/python directories
- ProgramArguments uses `caffeinate -dimsu`
- WorkingDirectory is exact runtime checkout
- `RunAtLoad=true`, `StartInterval=60`
- stdout/stderr point only to private runtime logs
- lint runs before bootstrap
- rollback command is printed

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/research_runtime/test_install_launchd.py`

Expected: FAIL because installer does not exist.

- [ ] **Step 3: installer artifact 구현**

The script requires:

```bash
: "${RESEARCH_EXPECTED_HOST:?RESEARCH_EXPECTED_HOST is required}"
[ "$(hostname)" = "$RESEARCH_EXPECTED_HOST" ] || exit 2
[ "$(git status --porcelain --untracked-files=all)" = "" ] || exit 2
```

It renders and lints the plist. The test path uses a stub `launchctl`; production bootstrap is prohibited
under the current `runtime_kind: none` manifest.

Update `CLAUDE.md` to allow one dedicated
`/Users/baek-end/petcam-lab-research-runtime` checkout while preserving the production worker separation
rule.

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/research_runtime/test_install_launchd.py`

Expected: PASS without touching the real LaunchAgent directory.

- [ ] **Step 5: commit**

```bash
git add scripts/install_research_runtime_launchd.sh tests/research_runtime/test_install_launchd.py CLAUDE.md docs/ENV.md
git commit -m "feat: R1 LaunchAgent 설치 artifact"
```

---

### Task 10: synthetic adversarial harness와 운영 문서

**Files:**
- Create: `scripts/run_research_runtime_adversarial.py`
- Create: `tests/research_runtime/test_adversarial_runner.py`
- Create: `docs/research/R1-RUNTIME-RUNBOOK.md`
- Modify: `docs/research/RETENTION.md`
- Modify: `docs/research/README.md`
- Modify: `docs/research/catalog.json`
- Modify: `specs/next-session.md`
- Modify: `.claude/donts-audit.md`

**Interfaces:**
- Consumes: complete runtime package
- Produces: 14 synthetic gate markers and P3 handoff prerequisites

- [ ] **Step 1: RED harness 테스트 작성**

The harness must emit these exact markers only after each scenario passes:

```text
R1_SIGKILL_RECOVERY_OK
R1_REBOOT_FENCING_OK
R1_STALE_EPOCH_OK
R1_SINGLETON_OK
R1_MONOTONIC_CLOCK_OK
R1_PRODUCTION_DEFER_OK
R1_STARVATION_BLOCK_OK
R1_DEADLINE_OK
R1_DISK_FAILURE_OK
R1_REDACTION_OK
R1_BOUNDED_TAIL_OK
R1_LEDGER_FAIL_CLOSED_OK
R1_CANCEL_CLEANUP_OK
R1_RESIDUE_ZERO
```

Test failure injection suppresses the affected marker and returns nonzero.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/research_runtime/test_adversarial_runner.py`

Expected: FAIL because harness does not exist.

- [ ] **Step 3: harness와 문서 구현**

The harness creates a temporary runtime root, fake boot IDs/PIDs/clocks, and no-op children only. It must
not import Supabase/R2/model code or access network. The runbook separates:

- local implementation verification
- P3 Mac mini install
- manual no-op canary
- natural cycle
- reboot recovery
- 24-hour endurance
- rollback

Add runtime files to retention policy: raw runtime files stay gitignored for 14 days; redacted summary and
final REPORT are tracked after human review.

- [ ] **Step 4: GREEN 확인**

Run:

```bash
uv run pytest -q tests/research_runtime/test_adversarial_runner.py
uv run python scripts/run_research_runtime_adversarial.py
```

Expected: all 14 markers and exit 0.

- [ ] **Step 5: commit**

```bash
git add scripts/run_research_runtime_adversarial.py tests/research_runtime/test_adversarial_runner.py docs/research docs/research/catalog.json specs/next-session.md .claude/donts-audit.md
git commit -m "test: R1 runtime 적대 검증과 운영 문서"
```

---

### Task 11: B 검증·독립 리뷰·C final record

**Files:**
- Modify: `docs/research/run-manifests/2026-07-28-r1-mac-mini-runtime-foundation.json`
- Create: `docs/handoff-prompts/2026-07-28-r1-mac-mini-runtime-foundation-implementation-report.md`

**Interfaces:**
- Consumes: A, M, all implementation commits
- Produces: B implementation commit, C final-record commit, final validator marker

- [ ] **Step 1: fresh 전체 검증**

Run:

```bash
uv run pytest -q
uv run python -m compileall -q backend/research_runtime scripts/run_research_runtime_adversarial.py
bash -n scripts/researchctl scripts/install_research_runtime_launchd.sh
uv run python scripts/run_research_runtime_adversarial.py
git diff --check
```

Expected: all tests pass, 14 markers, syntax/compile/diff exit 0.

- [ ] **Step 2: B commit과 push**

Write the implementation report with exact test counts, start manifest SHA M, implementation SHA B,
upstream, tracked/untracked state, actual mutations, cost/provider calls 0, and unverified P3 items.

```bash
git add docs/handoff-prompts/2026-07-28-r1-mac-mini-runtime-foundation-implementation-report.md
git commit -m "docs: R1 runtime 구현 검증 보고"
git push origin codex/r1-mac-mini-runtime-foundation
```

The resulting HEAD is B.

- [ ] **Step 3: independent read-only review**

Review concurrency, fencing, secret boundaries, production yield, and manifest lifecycle from a different
model family or independent session. Any Critical/Important finding returns to the relevant task and creates
a new implementation commit; rerun Step 1.

- [ ] **Step 4: final manifest record**

Change only the five allowed provenance fields:

- `source.start_manifest_commit_sha = M`
- `source.final_commit_sha = B`
- `model.actual_model`
- `model.actual_reasoning`
- `model.fallback_reason`

If runtime identity cannot be proven, use `actual_model: "unverified"`,
`actual_reasoning: "unverified"`, `fallback_reason: null`.

```bash
git add docs/research/run-manifests/2026-07-28-r1-mac-mini-runtime-foundation.json
git commit -m "docs: R1 runtime final manifest 기록"
```

This manifest-only commit is C.

- [ ] **Step 5: final validator와 push**

Run:

```bash
uv run python scripts/verify_research_run_manifest.py \
  --manifest /Users/baek/petcam-lab/.worktrees/r1-mac-mini-runtime-foundation/docs/research/run-manifests/2026-07-28-r1-mac-mini-runtime-foundation.json \
  --phase final
git status --short
git push origin codex/r1-mac-mini-runtime-foundation
```

Expected: `RUN_MANIFEST_OK` with runtime `none`, clean status, push success.

- [ ] **Step 6: stop**

Do not install the LaunchAgent or access Mac mini. Prepare a separate P3 design/manifest with exact runtime
target, trusted approval verifier, attestation verifier, rollback, manual/natural/reboot/24-hour canaries.

---

## Self-review checklist

- Every design requirement maps to Tasks 1–11.
- No task accesses production DB, R2, media, model, or external provider.
- The runner does not create Git commits.
- RUN-MANIFEST governs the implementation package; job spec governs repeated jobs.
- boot fencing, same-boot monotonic lease, attempt isolation, CAS are covered separately.
- production locks are probed and released; R1 workload is no-op only.
- secret corpus covers ledger, JSONL, log, JSON CLI, tail.
- Mac mini installation remains a separate P3 action.

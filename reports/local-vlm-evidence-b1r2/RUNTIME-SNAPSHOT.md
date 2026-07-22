# B1R2 Runtime 정본 스냅샷 (Task 0)

> read-only 실측. secret/R2 key/signed URL 미포함. B1R namespace 파일은 수정 안 함, 전부 B1R2 신규.

## 시작 계약 (Task 0 Step 1)

- validator 전문:
  `HANDOFF_OK task=local-vlm-evidence-b1r2-media-availability repo=local-vlm-evidence-web-gt commit=6c5c3d8e runtime=scheduled-job@baeg-endeuui-Macmini.local`
- lab worktree: `/Users/baek/petcam-lab/.worktrees/local-vlm-evidence-web-gt`, branch `codex/local-vlm-evidence-web-gt`.
- HEAD == manifest `commit_sha` `6c5c3d8e1d3e3f00c29d07b687bd74902d9ade3c`, tree clean, `git diff --check` 통과.
- `uv run pytest -q` = **736 passed** (plan 기대 ≥736 충족).
- implementation host(현재 세션): `BaekBook-Pro-14-M5.local`. runtime host(정본): `baeg-endeuui-Macmini.local`.

## Mac mini runtime (Task 0 Step 2, ssh home-mac read-only)

- hostname = `baeg-endeuui-Macmini.local` (expected host 정확 일치).

| repo | Mac mini path | HEAD | origin/main | tree |
|---|---|---|---|---|
| petcam-lab | `/Users/baek-end/petcam-lab` | `7a087b74` | `7a087b74` | clean |
| petcam-nightly-reporter | `/Users/baek-end/petcam-nightly-reporter` | `a7635a9` | `a7635a9` | untracked `.env.bak-20260708-vlmoff` (다른 세션 소유, 미접촉) |
| gecko-vision-gate | `/Users/baek-end/myPythonProjects/gecko-vision-gate` | `9ea55eb7` | `9ea55eb7` | clean |

- nightly-reporter `a7635a9` = B1R Task 6 FF 배포 결과(enqueuer 하드닝). B1R2 Task 3~5 는 그 위에 failure-typing 추가.

### LaunchAgent `com.petcam.python-evidence-worker`

- 등록됨(loaded). `program = /opt/homebrew/bin/uv`, ProgramArguments 마지막 = `reporter.python_evidence_worker`.
- `StartInterval = 1800`, `RunAtLoad = true`, `WorkingDirectory = /Users/baek-end/petcam-nightly-reporter`.
- feature flag(비-secret): `PYTHON_EVIDENCE_ENABLED=1`, `PYTHON_EVIDENCE_EXPECTED_HOST=baeg-endeuui-Macmini.local`, `PYTHON_EVIDENCE_GATE_THRESHOLD=0.10`.
- `state = not running`(StartInterval 사이 정상 대기), `runs = 221`, **`last exit code = 1`**.

## Evidence / selector identity (고정 계약)

- Evidence identity: `evidence_schema_version = python-evidence-raw-v1`, `algorithm_version = croi-temporal-v1`.
  - 소스: `reporter.python_evidence_store` → `gecko_vision_gate.temporal_evidence`(EVIDENCE_SCHEMA_VERSION/ALGORITHM_VERSION), lab side `scripts/audit_local_vlm_evidence_b1r_coverage.py:39-40`·`scripts/probe_local_vlm_evidence_candidates.py:48-49` 와 1:1.
- Selector identity: `local-vlm-evidence-selector-v2`.
- Fixed history cutoff: `2026-07-22T02:45:33+00:00` (B1R 재사용).

## `last exit code = 1` 진단 (drift 아님, 원인 규명됨)

worker stdout/stderr(`/tmp/python-evidence-worker.log`) 마지막 사이클 요약(비-secret, URL redacted):

```
07-22 04:08 jobs=30 ok=1 reused=1 fail=28 terminal=0
07-22 04:39 jobs=30 ok=2 reused=0 fail=28 terminal=0
07-22 05:09 jobs=30 ok=0 reused=1 fail=29 terminal=0
07-22 05:39 jobs=30 ok=0 reused=0 fail=30 terminal=0
07-22 06:09 jobs=30 ok=2 reused=1 fail=27 terminal=0
07-22 06:40 jobs=6  ok=3 reused=0 fail=3  terminal=0
07-22 07:10 jobs=2  ok=0 reused=0 fail=2  terminal=0
```

- 이 `jobs=30 fail≈28~30` 배치 = **B1R 잔여 canary 30건**(old cohort 2026-06-17·06-22, R2 원본 보존창 초과 삭제).
- 현재 worker 는 모든 R2 download 예외를 retryable `r2_download_failed` 로 처리 → 매 cycle 재시도 → `terminal=0` 유지 → cycle 에 실패가 있어 프로세스 **nonzero(exit 1)**.
- 이는 **B1R2 Task 3 이 고치는 바로 그 결함**: 404/NoSuchKey → `source_media_missing` terminal 로 분리하면 이 잔여 job 이 자연 terminal 로 닫히고 nonzero 도 해소된다.
- host / 3-repo HEAD(==origin/main) / service label / WorkingDirectory / expected host / feature flag 계약은 **전부 일치** → `B1R2_BLOCKED_RUNTIME_DRIFT` 아님.
- 원인이 **규명됨**(미해소·미스터리 반복 아님) → stop condition #6("worker nonzero 원인 미해소 반복") 미해당.
- B1R 잔여 job 은 강제 수정/삭제하지 않는다(design §6, handoff 금지). Task 1 partition 이 media 존재 여부로 재분류하고, Task 3 migration + worker 하드닝이 분류를 교정한다.

## Task 0 판정

**`B1R2_RUNTIME_OK`** — runtime drift 없음. 유일한 이상은 B1R 잔여 retryable job 로 인한 `last exit code = 1`이며, 이는 이번 handoff 가 해결 대상으로 명시한 상태다. 진행 승인 범위 내에서 Task 1 로 진행한다.

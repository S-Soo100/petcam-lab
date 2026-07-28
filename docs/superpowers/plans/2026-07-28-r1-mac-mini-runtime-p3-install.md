# R1 Mac mini 연구 runtime P3 설치 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 검증된 R1 synthetic no-op runtime을 exact Mac mini target에 설치하고 crash/reboot/24시간 지속성을 검증해.

**Architecture:** P3 controller RUN-MANIFEST가 production runtime service write를 승인하고, Mac mini runtime handoff가 exact checkout·HEAD·host·service를 다시 검증해. 설치 뒤 canary를 manual→natural→SIGKILL→reboot→24h 순으로 승격하며, final C는 runtime attestation 뒤에만 만든다.

**Tech Stack:** Python 3.12, uv, SQLite, JSONL, launchd, bash, macOS `caffeinate`, Git.

## Global Constraints

- Runtime host는 `baeg-endeuui-Macmini.local`, user는 `baek-end`로 고정해.
- Runtime code HEAD는 `8a7ea47041d02180f2fe03ada54f39f45ccf7c26`이야.
- Checkout은 `/Users/baek-end/petcam-lab-research-runtime`, service는 `com.petcam.research-runtime`이야.
- `synthetic_noop_v1`, provider calls 0, cost 0, media/dataset/model access 0만 허용해.
- DB/R2/기존 production service/main/credential은 수정하지 않아.
- P3 start marker와 Mac mini `HANDOFF_OK` 전에 installer를 실행하지 않아.
- 실패 시 bootout+plist 제거 후 ledger·JSONL은 보존해.

---

### Task 1: P3 A→M start gate

**Files:**
- Create: `docs/research/run-manifests/2026-07-28-r1-mac-mini-runtime-p3-install.json`

**Interfaces:**
- Consumes: P3 design, this plan, Owner approval turn.
- Produces: immutable P3 start manifest commit M and trusted start marker.

- [ ] **Step 1: A commit 확인**

Run:

```bash
git status --short
git rev-parse HEAD
git diff --check
```

Expected: design·plan tracked, clean, A exact SHA 확보.

- [ ] **Step 2: manifest-only M 작성**

Manifest must set:

```json
{
  "runtime_kind": "launchagent",
  "runtime_host": "baeg-endeuui-Macmini.local",
  "runtime_label": "com.petcam.research-runtime",
  "max_permission": "P3",
  "allowed_actions": [
    "docs_write",
    "local_code_write",
    "feature_branch_commit",
    "feature_branch_push",
    "nonproduction_canary",
    "runtime_service_write"
  ]
}
```

`p3_targets`는 `runtime_service_write` exact target 하나와 rollback·canary를 포함해.

- [ ] **Step 3: M 전용성 검증·commit**

Run:

```bash
git diff --name-only
git add docs/research/run-manifests/2026-07-28-r1-mac-mini-runtime-p3-install.json
git commit -m "docs: R1 runtime P3 start manifest"
```

Expected: M에는 manifest 한 파일만 추가.

- [ ] **Step 4: trusted approval start 검증**

Controller는 현재 Owner approval turn과 exact task/target/phase를 대조하는 injected verifier로
`validate_run_manifest(..., phase="start")`를 실행해.

Expected marker:

```text
RUN_MANIFEST_OK task=r1-mac-mini-runtime-p3-install permission=P3 runtime=launchagent@baeg-endeuui-Macmini.local
```

기본 CLI의 `approval_verifier_missing`은 정상 fail-closed 증거로 별도 기록해.

---

### Task 2: Mac mini runtime handoff와 canary spec

**Files:**
- Create: `docs/handoff-prompts/2026-07-28-r1-mac-mini-runtime-p3-install-handoff.md`
- Create: `docs/research/run-manifests/jobs/2026-07-28-r1-p3-synthetic-canary.json`
- Create: `docs/handoff-prompts/2026-07-28-r1-mac-mini-runtime-p3-preinstall-report.md`

**Interfaces:**
- Consumes: exact M SHA, manifest SHA-256, runtime code C.
- Produces: Mac mini에서 바로 검증·설치 가능한 handoff package.

- [ ] **Step 1: canary spec 작성**

고정값:

```json
{
  "handler": "synthetic_noop_v1",
  "handler_args": {"steps": 3, "step_seconds": 1},
  "repo_head": "8a7ea47041d02180f2fe03ada54f39f45ccf7c26",
  "expected_host": "baeg-endeuui-Macmini.local",
  "max_provider_calls": 0,
  "max_cost_krw": 0,
  "resources": []
}
```

`manifest_blob_sha`는 M manifest bytes의 SHA-256, `manifest_commit_sha`는 M exact SHA를 써.

- [ ] **Step 2: local parser 검증**

Run:

```bash
uv run python -c "from datetime import datetime, timezone; from pathlib import Path; from backend.research_runtime.job_spec import parse_job_spec; print(parse_job_spec(Path('docs/research/run-manifests/jobs/2026-07-28-r1-p3-synthetic-canary.json'), now=datetime.now(timezone.utc)).job_id)"
```

Expected: `r1-p3-synthetic-canary-001`.

- [ ] **Step 3: runtime handoff 작성**

Front matter exact values:

```yaml
execution_repo: /Users/baek-end/petcam-lab-research-runtime
commit_sha: 8a7ea47041d02180f2fe03ada54f39f45ccf7c26
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.research-runtime
```

Body에는 checkout 생성, `HANDOFF_OK`, local tests, installer command, canary, rollback, stop
conditions를 실제 명령으로 기록해.

- [ ] **Step 4: preinstall report와 commit/push**

Report에는 A/M SHA, start marker, base runtime C, local tests, tracked/untracked 상태, 실제 Mac mini
mutation 0을 적어.

```bash
git add docs/handoff-prompts docs/research/run-manifests/jobs
git commit -m "docs: R1 runtime P3 설치 handoff"
git push origin codex/r1-mac-mini-runtime-p3-preinstall
```

Stop verdict: `P3_START_VALIDATED_INSTALL_NOT_STARTED`.

---

### Task 3: Mac mini checkout·handoff 검증

**Files:**
- Runtime create: `/Users/baek-end/petcam-lab-research-runtime`
- Runtime audit copy: `/Users/baek-end/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-p3-install-handoff.md`

**Interfaces:**
- Consumes: pushed handoff package and runtime code C.
- Produces: Mac mini `HANDOFF_OK`; no LaunchAgent yet.

- [ ] **Step 1: runtime checkout 생성**

Run on Mac mini:

```bash
git clone --no-checkout https://github.com/S-Soo100/petcam-lab.git \
  /Users/baek-end/petcam-lab-research-runtime
git -C /Users/baek-end/petcam-lab-research-runtime fetch origin
git -C /Users/baek-end/petcam-lab-research-runtime checkout --detach \
  8a7ea47041d02180f2fe03ada54f39f45ccf7c26
test -z "$(git -C /Users/baek-end/petcam-lab-research-runtime status --porcelain --untracked-files=all)"
```

Expected: exact detached HEAD, clean.

- [ ] **Step 2: handoff audit copy 준비**

P3 control branch에서 handoff를 mode 0600 audit path로 복사해. 복사 뒤 SHA-256을 laptop tracked
source와 대조해.

- [ ] **Step 3: handoff validator**

Run on Mac mini:

```bash
cd /Users/baek-end/petcam-lab-research-runtime
uv run python scripts/verify_agent_handoff.py \
  --manifest "/Users/baek-end/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-p3-install-handoff.md"
```

Expected:

```text
HANDOFF_OK task=r1-mac-mini-runtime-p3-install repo=petcam-lab-research-runtime commit=8a7ea470 runtime=launchagent@baeg-endeuui-Macmini.local
```

- [ ] **Step 4: Mac mini local verification**

```bash
uv run pytest -q tests/research_runtime
uv run python scripts/run_research_runtime_adversarial.py
```

Expected: 39 tests pass, 14 markers, residue 0.

---

### Task 4: LaunchAgent install과 manual canary

**Files:**
- Runtime create: `~/Library/LaunchAgents/com.petcam.research-runtime.plist`
- Runtime create: `/Users/baek-end/Library/Application Support/petcam/research-runtime/`

**Interfaces:**
- Consumes: P3 start marker, HANDOFF_OK, Mac mini local verification.
- Produces: loaded service and one succeeded synthetic job.

- [ ] **Step 1: installer 실행**

```bash
cd /Users/baek-end/petcam-lab-research-runtime
RESEARCH_EXPECTED_HOST=baeg-endeuui-Macmini.local \
RESEARCH_EXPECTED_HEAD=8a7ea47041d02180f2fe03ada54f39f45ccf7c26 \
bash scripts/install_research_runtime_launchd.sh
```

Expected: plist lint→bootstrap, `INSTALLED com.petcam.research-runtime`.

- [ ] **Step 2: loaded attestation**

```bash
launchctl print gui/$(id -u)/com.petcam.research-runtime
```

Assert label, WorkingDirectory, `StartInterval=60`, exit code, stdout/stderr private path.

- [ ] **Step 3: canary submit**

```bash
scripts/researchctl submit \
  --spec "/Users/baek-end/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-p3-synthetic-canary.json"
scripts/researchctl status --json
```

Expected: queued→succeeded, attempt 1, provider/cost/media 0.

- [ ] **Step 4: failure rollback**

Any mismatch:

```bash
launchctl bootout gui/$(id -u)/com.petcam.research-runtime
rm "$HOME/Library/LaunchAgents/com.petcam.research-runtime.plist"
```

Preserve ledger/events, verify runtime process 0 and production services unchanged.

---

### Task 5: natural·SIGKILL·reboot·24시간 attestation

**Files:**
- Create after runtime execution: `docs/handoff-prompts/2026-07-28-r1-mac-mini-runtime-p3-deployment-report.md`
- Modify after runtime execution: `docs/research/run-manifests/2026-07-28-r1-mac-mini-runtime-p3-install.json`

**Interfaces:**
- Consumes: installed service and successful manual canary.
- Produces: B deployment evidence, C final record, runtime attestation.

- [ ] **Step 1: 자연 cycle**

Wait one StartInterval without kickstart. Confirm service exit 0 and no duplicate attempt.

- [ ] **Step 2: SIGKILL recovery**

Submit a bounded synthetic job, kill only its research-runtime process group, wait natural cycle, confirm
attempt 2 succeeds and stale epoch mutation 0.

- [ ] **Step 3: reboot recovery**

Submit bounded synthetic job, reboot Mac mini while running, confirm boot ID change, exactly one recovery,
event duplication 0.

- [ ] **Step 4: 24시간 지속 시험**

Confirm production lock defer, production exit/deadline drift 0, secret match 0, temp media 0.

- [ ] **Step 5: B→C**

Deployment report commit is B. Then change only the five allowed manifest provenance fields and commit
manifest-only C. Final validator must receive trusted approval and runtime attestation verifiers.

Expected verdict: `R1_RUNTIME_P3_DEPLOYED_VERIFIED`.

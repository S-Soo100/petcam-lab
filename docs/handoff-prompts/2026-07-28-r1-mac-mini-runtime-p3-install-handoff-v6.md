---
handoff_version: 1
task_id: r1-mac-mini-runtime-p3-install
execution_repo: /Users/baek-end/petcam-lab-research-runtime
plan_path: /Users/baek-end/petcam-lab-research-runtime/docs/research/R1-RUNTIME-RUNBOOK.md
design_path: /Users/baek-end/petcam-lab-research-runtime/scripts/install_research_runtime_launchd.sh
commit_sha: 7267b642dd9e25a0e199e57c5d41d1e2c04ee419
implementation_host: baeg-endeuui-Macmini.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.research-runtime
---

# R1 Mac mini 연구 runtime P3 설치 handoff v6

## v6 변경 사유

v5 RunAtLoad 2회는 정상 통과했지만 manual canary가 production guard의
`activity_lock_busy`로 attempt 0 `deferred`됐어. target만 rollback했고, 이어진 read-only
probe는 `quiet_window_insufficient`였다.

v6는 production lock/service/schedule을 바꾸지 않는다. guard가 자연스럽게 `allowed`가 된
시점에 fresh `006` IDs로 전체 설치 순서를 다시 시작한다. runtime과 tracked reboot verifier
SHA는 변경하지 않는다.

## 고정 provenance

- runtime code: `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- P3 manifest commit M: `85a270f89d3803553203e91e9ee72841affd7cf0`
- P3 manifest SHA-256:
  `9cd0eabf298833e21ee8ae14d573ad13176cf1154923573a8f6fbfd4d2c93e46`
- runtime checkout: `/Users/baek-end/petcam-lab-research-runtime`
- runtime root:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime`
- forbidden legacy root: `/Users/baek-end/.petcam-research-runtime`
- runtime host: `baeg-endeuui-Macmini.local`
- service: `com.petcam.research-runtime`
- verifier SHA-256:
  `e71fc0732882cbda570ad15ae6a6783e72bc98af0eea6511e229f65ec2725111`
- manual canary v6 SHA-256:
  `263b61dca7ace08103357ddc5e8f6eec3653e529149e1a119ba0e6270b6e2947`
- SIGKILL recovery v6 SHA-256:
  `0f0e48df4c8ab5310fe1c57ab3bd3dfd9e1eb2a25ef00888d4b5867ca6767e19`

production DB/R2/media/dataset/model, Claude/VLM/local LLM, provider와 기존 production service
접근·변경은 0이어야 해. Gemini CLI는 폐기 상태를 유지한다.

## 0. guard와 fail-closed gate

service가 absent인 상태에서 runtime의 `evaluate_guard`를 `uv run python`으로 read-only
호출한다. `allowed=True` 전에는 설치하지 않는다. production lock 파일을 삭제하거나 lock
owner를 signal하지 않는다.

그다음 host/user, Gemini 폐기 상태, target absent, legacy root absent, runtime exact
SHA/clean과 control clean/upstream을 확인한다. production 8개 plist의 label, SHA-256,
WorkingDirectory와 repo HEAD/status fingerprint를 새 baseline으로 기록한다.

## 1. audit copy와 HANDOFF_OK

이 handoff, 두 v6 spec과 tracked verifier를 runtime root의 `handoff/`와 `audit/`에 mode
0600으로 복사하고 source/copy SHA-256을 대조한다.

```bash
cd /Users/baek-end/petcam-lab-research-runtime
uv run python scripts/verify_agent_handoff.py \
  --manifest "$HOME/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-mac-mini-runtime-p3-install-handoff-v6.md"
```

필수 출력:

```text
HANDOFF_OK task=r1-mac-mini-runtime-p3-install repo=petcam-lab-research-runtime commit=7267b642 runtime=launchagent@baeg-endeuui-Macmini.local
```

## 2. code gate

```bash
cd /Users/baek-end/petcam-lab-r1-runtime-p3-control
uv run pytest -q tests/research_runtime/test_reboot_verifier.py
/usr/bin/python3 -m py_compile scripts/verify_research_runtime_reboot.py

cd /Users/baek-end/petcam-lab-research-runtime
uv run pytest -q tests/research_runtime
uv run python scripts/run_research_runtime_adversarial.py
bash -n scripts/researchctl scripts/install_research_runtime_launchd.sh
```

verifier 7 tests, runtime 41 tests, adversarial marker 14줄과 `R1_RESIDUE_ZERO`, system Python
compile과 bash syntax가 모두 exit 0이어야 해.

## 3. RunAtLoad 2회

```bash
cd /Users/baek-end/petcam-lab-research-runtime
RESEARCH_EXPECTED_HOST=baeg-endeuui-Macmini.local \
RESEARCH_EXPECTED_HEAD=7267b642dd9e25a0e199e57c5d41d1e2c04ee419 \
bash scripts/install_research_runtime_launchd.sh
```

첫 RunAtLoad exit 0 확인 뒤 exact target만 bootout하고 target plist만 제거한다. 같은 명령으로
두 번째 설치하고 exit 0을 확인한다. WorkingDirectory, StartInterval 60, canonical root와
expected HEAD가 정확해야 해.

## 4. manual → natural 2회 → SIGKILL

```bash
cd /Users/baek-end/petcam-lab-research-runtime
scripts/researchctl submit \
  --spec "$HOME/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-p3-synthetic-canary-v6.json"
launchctl kickstart "gui/$(id -u)/com.petcam.research-runtime"
scripts/researchctl show r1-p3-synthetic-canary-006 --json
```

manual canary는 root env/option 없이 attempt 1 `succeeded`여야 해. 이어서 kickstart 없이
`runs`가 두 번 증가하고 두 cycle 모두 exit 0, canary attempt 불변이어야 한다.

그 뒤 v6 recovery spec을 default root로 submit한다. 자연 cycle에서 running이 되면 ledger
PID와 process tree를 대조하고 exact research parent/child process group만 SIGKILL한다.
다음 자연 cycle이 stale lease를 reclaim해 `r1-p3-sigkill-recovery-006`을 attempt 2, 새
lease epoch, exit 0 `succeeded`로 끝내야 해.

provider/cost/media/model/legacy residue, duplicate result와 orphan process는 모두 0이어야 한다.

## 5. reboot marker

앞 단계가 전부 통과한 뒤 schema 2 marker를 mode 0600으로 원자 작성한다. 필수 필드는
host/user, runtime/control SHA, runtime checkout/root, legacy root, label, target plist와
SHA-256, launch agents dir, pre-reboot boot sec, production baseline path/SHA-256이다.

control SHA는 clean checkout의 `git rev-parse HEAD`를 직접 기록하고 upstream SHA와 같음을
검증한다. 별도 hardcoded expected SHA를 두지 않는다. boot parser는 `sec = <integer>`만
선택한다.

임시 marker에서 `pre_reboot_boot_sec`만 다른 값으로 바꿔 verifier 전체 read-only preflight를
수행하고 `R1_REBOOT_VERIFIER_PREFLIGHT_OK`를 확인한다.

reboot 후:

```bash
/usr/bin/python3 \
  "$HOME/Library/Application Support/petcam/research-runtime/audit/verify_research_runtime_reboot-v6.py" \
  --marker "$HOME/Library/Application Support/petcam/research-runtime/audit/r1-p3-reboot-pending-v6.json"
```

마지막 출력은 `R1_RUNTIME_P3_REBOOT_RECOVERY_OK`여야 해.

## 6. 24시간과 rollback

reboot recovery 통과 시각과 정확히 24시간 뒤 완료 예정 시각을 기록하고 service를 유지한다.
그 전에는 `R1_RUNTIME_P3_PENDING_24H`로만 보고한다.

어느 단계든 오류, drift, off-target mutation이면 뒤 단계로 가지 않고 exact target만
bootout하고 target plist만 제거한다. ledger/event/audit 증거는 보존한다.

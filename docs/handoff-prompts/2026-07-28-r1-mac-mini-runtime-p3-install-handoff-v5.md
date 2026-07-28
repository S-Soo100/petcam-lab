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

# R1 Mac mini 연구 runtime P3 설치 handoff v5

## v5 변경 사유

v4 runtime 검증과 canary는 모두 통과했지만 pre-reboot marker 작성 코드가 control SHA를 잘못
하드코딩해 marker를 쓰기 전에 assertion failure가 났어. reboot는 하지 않았고 exact target
service만 rollback했다.

v5는 runtime/verifier 코드를 바꾸지 않는다. fresh `005` job IDs로 전체 설치 순서를 다시
실행하고, marker의 control SHA는 clean control checkout의 `git rev-parse HEAD` 결과를 직접
기록한다. 사람이 옮긴 별도 expected SHA와 비교하지 않는다.

## 고정 provenance와 경계

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
- tracked verifier:
  `/Users/baek-end/petcam-lab-r1-runtime-p3-control/scripts/verify_research_runtime_reboot.py`
- verifier SHA-256:
  `e71fc0732882cbda570ad15ae6a6783e72bc98af0eea6511e229f65ec2725111`
- manual canary v5 SHA-256:
  `629ebb9eda450843c44f279d82b7c2d2872bb6247c075ba58e33d701e6b77cbd`
- SIGKILL recovery v5 SHA-256:
  `9e58e000ca4fb0fd0254765bf413f3139f674bc6accf8239939bec75ab99b390`

production DB/R2/media/dataset/model, Claude/VLM/local LLM, provider, 기존 production service
접근·변경은 0이어야 해. Gemini CLI는 폐기 상태를 유지하고 Gemini API는 건드리지 않는다.

## 0. fail-closed gate와 exact checkout

```bash
test "$(hostname)" = "baeg-endeuui-Macmini.local"
test "$(id -un)" = "baek-end"
test ! -e "$HOME/.petcam-research-runtime"
test ! -e "$HOME/Library/LaunchAgents/com.petcam.research-runtime.plist"
! launchctl print "gui/$(id -u)/com.petcam.research-runtime" >/dev/null 2>&1
! command -v gemini >/dev/null 2>&1
test ! -e "$HOME/.gemini"
! pgrep -f '[g]emini-cli' >/dev/null 2>&1

test "$(git -C /Users/baek-end/petcam-lab-research-runtime rev-parse HEAD)" = \
  "7267b642dd9e25a0e199e57c5d41d1e2c04ee419"
test -z "$(git -C /Users/baek-end/petcam-lab-research-runtime \
  status --porcelain --untracked-files=all)"
```

production 8개 plist의 label, SHA-256, WorkingDirectory와 repo HEAD/status fingerprint를
read-only baseline으로 기록한다. target 이외 service를 bootout, bootstrap, kickstart,
signal 또는 수정하지 않는다.

## 1. audit copy와 HANDOFF_OK

이 handoff, 두 v5 spec과 tracked verifier를 runtime root의 `handoff/`와 `audit/`에 mode
0600으로 복사하고 source/copy SHA-256을 대조한다.

```bash
cd /Users/baek-end/petcam-lab-research-runtime
uv run python scripts/verify_agent_handoff.py \
  --manifest "$HOME/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-mac-mini-runtime-p3-install-handoff-v5.md"
```

필수 출력:

```text
HANDOFF_OK task=r1-mac-mini-runtime-p3-install repo=petcam-lab-research-runtime commit=7267b642 runtime=launchagent@baeg-endeuui-Macmini.local
```

새 `HANDOFF_OK` 없이는 설치하지 않는다.

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
두 번째 설치하고 exit 0을 다시 확인한다. WorkingDirectory, StartInterval 60, canonical
root와 expected HEAD가 정확해야 해.

## 4. manual → natural 2회 → SIGKILL

manual canary는 root env/option을 생략한다.

```bash
cd /Users/baek-end/petcam-lab-research-runtime
scripts/researchctl submit \
  --spec "$HOME/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-p3-synthetic-canary-v5.json"
launchctl kickstart "gui/$(id -u)/com.petcam.research-runtime"
scripts/researchctl show r1-p3-synthetic-canary-005 --json
```

attempt 1 `succeeded` 뒤 kickstart 없이 `runs`가 두 번 증가하고 두 cycle 모두 exit 0, canary
attempt 불변이어야 해.

그 뒤 `2026-07-28-r1-p3-sigkill-recovery-v5.json`을 default root로 submit한다. 자연
cycle에서 running이 되면 ledger PID와 process tree를 대조하고 exact research parent/child
process group만 SIGKILL한다. 다음 자연 cycle이 stale lease를 reclaim해
`r1-p3-sigkill-recovery-005`를 attempt 2, 새 lease epoch, exit 0 `succeeded`로 끝내야 해.

모든 단계에서 provider/cost/media/model/legacy residue와 orphan process는 0이어야 한다.

## 5. reboot marker

앞 단계가 전부 통과한 뒤 schema 2 marker를 mode 0600으로 원자 작성한다.

필수 필드:

```text
schema_version=2
marker=R1_RUNTIME_P3_REBOOT_PENDING
created_at
host
user
runtime_sha
control_sha
runtime_checkout
runtime_root
legacy_root
runtime_label
target_plist
target_plist_sha256
launch_agents_dir
pre_reboot_boot_sec
production_baseline_artifact
production_baseline_sha256
```

`control_sha`는 clean control checkout에서 직접 읽고 upstream SHA와 같음을 검증한다.
boot parser는 `sec = <integer>`만 선택한다. production immutable contract는 label, plist
SHA-256과 non-null WorkingDirectory다. loaded/runs/last-exit는 판정 입력이 아니다.

marker 생성 후 임시 복사본의 `pre_reboot_boot_sec`만 다른 값으로 바꿔 verifier 전체
read-only preflight를 수행하고 `R1_REBOOT_VERIFIER_PREFLIGHT_OK`를 확인한다.

reboot 후:

```bash
/usr/bin/python3 \
  "$HOME/Library/Application Support/petcam/research-runtime/audit/verify_research_runtime_reboot-v5.py" \
  --marker "$HOME/Library/Application Support/petcam/research-runtime/audit/r1-p3-reboot-pending-v5.json"
```

마지막 출력은 `R1_RUNTIME_P3_REBOOT_RECOVERY_OK`여야 해.

## 6. 24시간 지속 검증

reboot recovery 통과 시각과 정확히 24시간 뒤 완료 예정 시각을 기록하고 service를 유지한다.
그 전에는 `DEPLOYED_VERIFIED`가 아니라 `R1_RUNTIME_P3_PENDING_24H`로만 보고한다.

## rollback

어느 단계든 오류, drift, off-target mutation이면 뒤 단계로 가지 않고 exact target만
rollback한다.

```bash
launchctl bootout "gui/$(id -u)/com.petcam.research-runtime"
rm "$HOME/Library/LaunchAgents/com.petcam.research-runtime.plist"
```

ledger/event/audit 증거는 보존한다.

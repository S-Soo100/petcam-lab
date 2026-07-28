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

# R1 Mac mini 연구 runtime P3 설치 handoff v4

## v4 변경 사유

v3 runtime은 RunAtLoad 2회, manual canary, 자연 cycle 2회, SIGKILL recovery와 reboot
RunAtLoad까지 정상 통과했어. reboot gate는 runtime이 아니라 untracked audit verifier의 두
결함 때문에 fail-closed rollback했다.

1. `kern.boottime`의 `sec` 대신 뒤의 `usec`를 파싱했다.
2. reboot마다 정상적으로 변하는 launchd `loaded/runs/last-exit`를 production mutation으로
   판정했다.

v4는 control branch에 tracked Python verifier와 regression test를 둔다. boot ID는 첫
`sec = <integer>`만 파싱하고, production baseline은 label, plist SHA-256, plist의
`WorkingDirectory`만 immutable contract로 검증한다. launchd volatile state는 관찰 기록일
뿐 pass/fail 입력이 아니다.

runtime 동작 결함이 아니므로 runtime SHA는 변경하지 않는다.

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
- tracked verifier:
  `/Users/baek-end/petcam-lab-r1-runtime-p3-control/scripts/verify_research_runtime_reboot.py`
- verifier SHA-256:
  `e71fc0732882cbda570ad15ae6a6783e72bc98af0eea6511e229f65ec2725111`
- manual canary: `2026-07-28-r1-p3-synthetic-canary-v4.json`
- manual canary SHA-256:
  `ce83c281c3ddcafa44d4e3ad2bcf6aefd0391444aa78f298bd60151c4c12118e`
- SIGKILL recovery spec: `2026-07-28-r1-p3-sigkill-recovery-v4.json`
- SIGKILL recovery SHA-256:
  `b7571311e8caa9afb6720ad8d5bd7550a0ae35c3e4326b9faad46e98c934b405`

production DB/R2/media/dataset/model, Claude/VLM/local LLM, 외부 provider, 기존 production
service 접근·변경은 모두 0이어야 해. Gemini CLI는 폐기 상태를 유지하고 Gemini API는
건드리지 않는다.

## 0. 설치 전 gate

```bash
test "$(hostname)" = "baeg-endeuui-Macmini.local"
test "$(id -un)" = "baek-end"
test ! -e "$HOME/.petcam-research-runtime"
test ! -e "$HOME/Library/LaunchAgents/com.petcam.research-runtime.plist"
! launchctl print "gui/$(id -u)/com.petcam.research-runtime" >/dev/null 2>&1
! command -v gemini >/dev/null 2>&1
test ! -e "$HOME/.gemini"
! pgrep -f '[g]emini-cli' >/dev/null 2>&1
```

production baseline은 기존 8개 plist의 label, SHA-256과 plist
`WorkingDirectory`를 기록한다. target label 이외 service를 bootout, kickstart, bootstrap,
signal 또는 수정하지 않는다.

## 1. exact checkout과 HANDOFF_OK

runtime checkout은 destructive reset 없이 detached exact SHA와 clean 상태를 확인한다.

```bash
git -C /Users/baek-end/petcam-lab-research-runtime fetch origin
git -C /Users/baek-end/petcam-lab-research-runtime checkout --detach \
  7267b642dd9e25a0e199e57c5d41d1e2c04ee419
test "$(git -C /Users/baek-end/petcam-lab-research-runtime rev-parse HEAD)" = \
  "7267b642dd9e25a0e199e57c5d41d1e2c04ee419"
test -z "$(git -C /Users/baek-end/petcam-lab-research-runtime \
  status --porcelain --untracked-files=all)"
```

controller source의 handoff, 두 v4 spec과 verifier를 runtime root에 복사하고 mode 0600,
source/copy SHA-256 일치를 확인한다.

```text
/Users/baek-end/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-mac-mini-runtime-p3-install-handoff-v4.md
/Users/baek-end/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-p3-synthetic-canary-v4.json
/Users/baek-end/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-p3-sigkill-recovery-v4.json
/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/verify_research_runtime_reboot-v4.py
```

그 뒤 새 handoff만 검증한다.

```bash
cd /Users/baek-end/petcam-lab-research-runtime
uv run python scripts/verify_agent_handoff.py \
  --manifest "$HOME/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-mac-mini-runtime-p3-install-handoff-v4.md"
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

## 3. 설치와 RunAtLoad 2회

```bash
cd /Users/baek-end/petcam-lab-research-runtime
RESEARCH_EXPECTED_HOST=baeg-endeuui-Macmini.local \
RESEARCH_EXPECTED_HEAD=7267b642dd9e25a0e199e57c5d41d1e2c04ee419 \
bash scripts/install_research_runtime_launchd.sh
```

첫 RunAtLoad가 exit 0인지 확인하고 exact target만 bootout한 뒤 target plist만 제거한다. 같은
명령으로 두 번째 설치하고 두 번째 RunAtLoad도 exit 0이어야 해. 두 번 모두
WorkingDirectory, StartInterval 60, canonical runtime root와 expected HEAD를 확인한다.

## 4. manual canary와 자연 cycle

root option과 env를 생략해 canonical default를 실제로 검증한다.

```bash
cd /Users/baek-end/petcam-lab-research-runtime
scripts/researchctl submit \
  --spec "$HOME/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-p3-synthetic-canary-v4.json"
test ! -e "$HOME/.petcam-research-runtime"
launchctl kickstart "gui/$(id -u)/com.petcam.research-runtime"
scripts/researchctl show r1-p3-synthetic-canary-004 --json
```

attempt 1 `succeeded`, provider calls 0, cost 0, media/model residue 0이어야 해. 그 뒤 manual
kickstart 없이 StartInterval에 따른 `runs` 증가를 두 번 확인한다. 두 cycle 모두 exit 0,
job attempt 불변, legacy root 부재여야 해.

## 5. SIGKILL recovery

v4 recovery spec을 default root로 submit한다. 자연 cycle에서 state가 `running`이 된 뒤
ledger PID와 `ps` process tree로 runtime child process group을 정확히 식별한다. target
research process group만 SIGKILL하고 다른 process에는 signal하지 않는다.

다음 자연 cycle이 stale lease를 회수하고 새 attempt/lease epoch로 bounded job을
`succeeded` 처리해야 해. duplicate success, orphan process, provider/cost/media/model
residue는 모두 0이어야 해.

## 6. reboot marker와 검증

앞 단계가 전부 통과한 경우에만 schema 2 JSON marker를 audit root에 쓴다.

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

production baseline artifact와 marker는 mode 0600으로 고정한다. baseline의 immutable
contract는 production label, plist SHA-256, non-null `WorkingDirectory`다. reboot로
변하는 loaded/runs/last-exit는 별도 관찰할 수 있지만 verifier pass/fail 입력으로 쓰지 않는다.

reboot 후 exact 명령:

```bash
/usr/bin/python3 \
  "$HOME/Library/Application Support/petcam/research-runtime/audit/verify_research_runtime_reboot-v4.py" \
  --marker "$HOME/Library/Application Support/petcam/research-runtime/audit/r1-p3-reboot-pending-v4.json"
```

필수 마지막 marker:

```text
R1_RUNTIME_P3_REBOOT_RECOVERY_OK
```

## 7. 24시간 지속 검증

reboot recovery가 통과한 시각을 시작 시각으로 기록하고 완료 예정 시각을 정확히 24시간 뒤로
계산한다. service는 유지하되 24시간 전에는 `DEPLOYED_VERIFIED`를 주장하지 않고
`R1_RUNTIME_P3_PENDING_24H`로만 보고한다.

## rollback

오류, drift, off-target mutation이 나오면 뒤 단계로 진행하지 않고 target service만
rollback한다.

```bash
launchctl bootout "gui/$(id -u)/com.petcam.research-runtime"
rm "$HOME/Library/LaunchAgents/com.petcam.research-runtime.plist"
```

ledger, event, diagnostics, marker와 baseline 증거는 보존한다. production
DB/R2/media/dataset/model/provider 접근, target 이외 service/process mutation, secret-like
output, provider 비용, temp media, legacy root 중 하나라도 0이 아니면 즉시 중단한다.

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

# R1 Mac mini 연구 runtime P3 설치 handoff v3

## v3 변경 사유

v2 runtime `a47bea6202b708dd0066155d41904dcb19fccbe5`의 LaunchAgent RunAtLoad는 2회
exit 0이었지만, root를 생략한 `researchctl` manual canary가 legacy
`~/.petcam-research-runtime` ledger를 만들어 rollback했어.

v3 runtime `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`은 CLI default를 LaunchAgent와
같은 canonical root로 고정한다. `submit/status/show/tail/cancel`은 모두 parser에서 결정된
단일 root를 사용하고, regression test가 legacy root 생성을 금지한다.

## 고정 범위

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
- manual canary: `2026-07-28-r1-p3-synthetic-canary-v3.json`
- manual canary SHA-256:
  `1b5e45b980a237c7466f869eb7b22b88d73e132541481c59f62ee58da68a9d57`
- SIGKILL recovery spec: `2026-07-28-r1-p3-sigkill-recovery-v3.json`
- SIGKILL recovery SHA-256:
  `2ca0e02d4c3f1f57cb4978355c89e8cefea287414b994c7bdf0284c743ee647e`

production DB/R2/media/dataset/model, Claude/VLM/local LLM, 외부 provider, 기존 production
service 접근·변경은 모두 0이어야 해.

## 0. 설치 전 gate

Gemini CLI는 폐기 상태를 유지하고 Gemini API credential은 건드리지 않는다.

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

기존 production LaunchAgent의 label, plist hash, working directory, repo HEAD, last exit와
tracked/untracked 상태를 설치 전후 같은 방식으로 비교한다. target label 이외 service를
bootout하거나 수정하지 않는다.

## 1. exact checkout과 HANDOFF_OK

runtime checkout을 fetch한 뒤 destructive reset 없이 detached exact SHA로 이동하고 clean을
확인한다.

```bash
git -C /Users/baek-end/petcam-lab-research-runtime fetch origin
git -C /Users/baek-end/petcam-lab-research-runtime checkout --detach \
  7267b642dd9e25a0e199e57c5d41d1e2c04ee419
test "$(git -C /Users/baek-end/petcam-lab-research-runtime rev-parse HEAD)" = \
  "7267b642dd9e25a0e199e57c5d41d1e2c04ee419"
test -z "$(git -C /Users/baek-end/petcam-lab-research-runtime \
  status --porcelain --untracked-files=all)"
```

controller source의 handoff와 두 canary spec을 runtime root의 `handoff/`에 복사하고 mode
0600, SHA-256 일치를 확인한다. 그 뒤:

```bash
cd /Users/baek-end/petcam-lab-research-runtime
uv run python scripts/verify_agent_handoff.py \
  --manifest "$HOME/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-mac-mini-runtime-p3-install-handoff-v3.md"
```

필수 출력:

```text
HANDOFF_OK task=r1-mac-mini-runtime-p3-install repo=petcam-lab-research-runtime commit=7267b642 runtime=launchagent@baeg-endeuui-Macmini.local
```

## 2. runtime 검증

```bash
cd /Users/baek-end/petcam-lab-research-runtime
uv run pytest -q tests/research_runtime
uv run python scripts/run_research_runtime_adversarial.py
bash -n scripts/researchctl scripts/install_research_runtime_launchd.sh
```

41 tests, adversarial marker 14줄과 `R1_RESIDUE_ZERO`, bash exit 0이 모두 있어야 해.

## 3. 설치와 RunAtLoad 2회

```bash
cd /Users/baek-end/petcam-lab-research-runtime
RESEARCH_EXPECTED_HOST=baeg-endeuui-Macmini.local \
RESEARCH_EXPECTED_HEAD=7267b642dd9e25a0e199e57c5d41d1e2c04ee419 \
bash scripts/install_research_runtime_launchd.sh
```

첫 설치의 RunAtLoad가 exit 0인지 확인하고 exact target만 bootout·plist 제거한 뒤 같은 명령으로
두 번째 설치를 수행한다. 두 번째 RunAtLoad도 exit 0이어야 해. label, WorkingDirectory,
StartInterval 60, runtime root, expected HEAD를 `launchctl print`와 plist로 확인한다.

## 4. manual canary와 root 계약

manual canary는 root 옵션과 env를 생략해 코드 default를 실제로 검증한다.

```bash
cd /Users/baek-end/petcam-lab-research-runtime
scripts/researchctl submit \
  --spec "$HOME/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-p3-synthetic-canary-v3.json"
test ! -e "$HOME/.petcam-research-runtime"
launchctl kickstart "gui/$(id -u)/com.petcam.research-runtime"
scripts/researchctl \
  --root "$HOME/Library/Application Support/petcam/research-runtime" \
  show r1-p3-synthetic-canary-003 --json
```

attempt 1 `succeeded`, target ledger/event/job path 존재, legacy root 부재를 확인한다.
default-root `status/show/tail`도 같은 job을 봐야 하고, `cancel`의 동일-root 계약은 앞의
regression test로 확인한다.

## 5. 자연 cycle 2회와 SIGKILL recovery

manual kickstart 없이 StartInterval에 따른 `runs` 증가를 두 번 확인한다. 각 cycle은 exit 0,
target jobs 불변, legacy root 부재여야 해.

그 뒤 bounded recovery spec을 default root로 submit한다. 자연 cycle에서 state가 `running`이
되고 runtime child process group을 정확히 식별한 뒤 그 group에만 SIGKILL한다. production
process나 다른 LaunchAgent에는 signal을 보내지 않는다. 다음 자연 cycle이 stale lease를
회수하고 bounded job을 새 epoch/attempt로 재실행해 `succeeded`로 끝내야 해.

## 6. reboot gate

앞 단계가 모두 통과한 경우에만 durable audit marker에 다음을 기록하고 reboot한다.

- marker: `R1_RUNTIME_P3_REBOOT_PENDING`
- runtime SHA와 control SHA
- service label, target root, pre-reboot `runs`/last exit
- production baseline hash
- reboot 후 실행할 exact 검증 명령
- 작성 시각과 host

reboot 후 service 자동 load, exit 0, exact runtime HEAD, target root와 legacy root 부재,
production baseline 불변을 확인한다.

## 7. 24시간 지속 검증

reboot recovery가 통과한 시각을 시작 시각으로 기록하고 완료 예정 시각을 정확히 24시간 뒤로
계산한다. service는 유지하되 24시간 전에는 `DEPLOYED_VERIFIED`를 주장하지 않고
`R1_RUNTIME_P3_PENDING_24H`로만 보고한다.

## rollback

오류·drift·off-target mutation이 나오면 뒤 단계로 진행하지 않고 target service만 제거한다.

```bash
launchctl bootout "gui/$(id -u)/com.petcam.research-runtime"
rm "$HOME/Library/LaunchAgents/com.petcam.research-runtime.plist"
```

ledger/event/audit 증거는 보존한다. production DB/R2/media/dataset/model/provider 접근,
target 이외 process signal, secret-like output, 비용, temp media 또는 legacy root 생성 중
하나라도 0이 아니면 즉시 rollback한다.

---
handoff_version: 1
task_id: r1-mac-mini-runtime-p3-install
execution_repo: /Users/baek-end/petcam-lab-research-runtime
plan_path: /Users/baek-end/petcam-lab-research-runtime/docs/research/R1-RUNTIME-RUNBOOK.md
design_path: /Users/baek-end/petcam-lab-research-runtime/scripts/install_research_runtime_launchd.sh
commit_sha: a47bea6202b708dd0066155d41904dcb19fccbe5
implementation_host: baeg-endeuui-Macmini.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.research-runtime
---

# R1 Mac mini 연구 runtime P3 설치 handoff v2

## v2 변경 사유

v1 runtime code `8a7ea47041d02180f2fe03ada54f39f45ccf7c26`의 LaunchAgent RunAtLoad가
Mac mini launchd 환경에서 `SAFETY_VIOLATION(6)`으로 재현됐어. 원인은 launchd PATH에
`/usr/sbin`이 없는데 runtime `current_boot_id()`가 bare `sysctl`을 호출한 거야.

v2 runtime code `a47bea6202b708dd0066155d41904dcb19fccbe5`는 `current_boot_id()`를
`/usr/sbin/sysctl` 절대경로로 호출하게 고정한다. permission manifest M은 기존 P3 start
manifest `85a270f89d3803553203e91e9ee72841affd7cf0` 그대로야.

## 실행 범위

검증된 `synthetic_noop_v1` runtime만 Mac mini 전용 checkout과
`com.petcam.research-runtime` LaunchAgent에 설치해. production DB/R2/media/dataset/model,
Claude/VLM/local LLM, 외부 provider, 기존 production service는 건드리지 마.

고정 provenance:

- runtime code v2: `a47bea6202b708dd0066155d41904dcb19fccbe5`
- P3 manifest commit M: `85a270f89d3803553203e91e9ee72841affd7cf0`
- P3 manifest SHA-256:
  `9cd0eabf298833e21ee8ae14d573ad13176cf1154923573a8f6fbfd4d2c93e46`
- runtime checkout: `/Users/baek-end/petcam-lab-research-runtime`
- runtime data root:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime`
- runtime host: `baeg-endeuui-Macmini.local`
- service: `com.petcam.research-runtime`
- canary v2:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-p3-synthetic-canary-v2.json`

## 0. Gemini CLI 제거 선행 게이트

Gemini CLI는 계속 폐기 상태여야 해. Gemini API credential·backend는 삭제하지 마.

```bash
! command -v gemini >/dev/null 2>&1
test ! -e "$HOME/.gemini"
! pgrep -f '[g]emini-cli' >/dev/null 2>&1
echo GEMINI_CLI_MAC_MINI_REMOVED
```

## 1. 설치 전 fail-closed 확인

```bash
test "$(hostname)" = "baeg-endeuui-Macmini.local"
test "$(id -un)" = "baek-end"
test ! -e "$HOME/Library/LaunchAgents/com.petcam.research-runtime.plist"
! launchctl print "gui/$(id -u)/com.petcam.research-runtime" >/dev/null 2>&1
```

기존 production LaunchAgent의 plist hash·working directory·HEAD·last exit를 설치 전후로 대조해.
이 handoff는 기존 service를 bootout하거나 수정할 권한을 주지 않아.

## 2. exact checkout

checkout이 이미 있으면 임의 reset하지 말고 exact HEAD·clean 여부만 확인해. v1 checkout이면
fetch 뒤 새 exact commit으로 detached checkout해.

```bash
git -C /Users/baek-end/petcam-lab-research-runtime fetch origin
git -C /Users/baek-end/petcam-lab-research-runtime checkout --detach \
  a47bea6202b708dd0066155d41904dcb19fccbe5
test "$(git -C /Users/baek-end/petcam-lab-research-runtime rev-parse HEAD)" = \
  "a47bea6202b708dd0066155d41904dcb19fccbe5"
test -z "$(git -C /Users/baek-end/petcam-lab-research-runtime \
  status --porcelain --untracked-files=all)"
```

## 3. audit artifact 복사와 handoff 검증

controller가 이 파일과 canary v2 JSON을 아래 경로에 복사한 뒤 mode 0600으로 고정해.

```text
/Users/baek-end/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-mac-mini-runtime-p3-install-handoff-v2.md
/Users/baek-end/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-p3-synthetic-canary-v2.json
```

복사본 SHA-256을 controller source와 대조한 뒤:

```bash
cd /Users/baek-end/petcam-lab-research-runtime
uv run python scripts/verify_agent_handoff.py \
  --manifest "/Users/baek-end/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-mac-mini-runtime-p3-install-handoff-v2.md"
```

필수 출력:

```text
HANDOFF_OK task=r1-mac-mini-runtime-p3-install repo=petcam-lab-research-runtime commit=a47bea62 runtime=launchagent@baeg-endeuui-Macmini.local
```

## 4. 설치 전 runtime 검증

```bash
cd /Users/baek-end/petcam-lab-research-runtime
uv run pytest -q tests/research_runtime
uv run python scripts/run_research_runtime_adversarial.py
bash -n scripts/researchctl scripts/install_research_runtime_launchd.sh
```

40 tests와 adversarial marker 14개, `R1_RESIDUE_ZERO`가 모두 있어야 해.

## 5. LaunchAgent 설치

앞의 모든 검증이 통과한 경우에만:

```bash
cd /Users/baek-end/petcam-lab-research-runtime
RESEARCH_EXPECTED_HOST=baeg-endeuui-Macmini.local \
RESEARCH_EXPECTED_HEAD=a47bea6202b708dd0066155d41904dcb19fccbe5 \
bash scripts/install_research_runtime_launchd.sh
```

그다음 `launchctl print gui/$(id -u)/com.petcam.research-runtime`에서 label,
WorkingDirectory, `StartInterval=60`, private log path, `last exit code = 0`을 확인해.

## 6. canary 순서

1. RunAtLoad 2회 안정성을 먼저 확인해. 두 번 모두 exit 0이어야 해.
2. tracked canary v2를 `scripts/researchctl submit --spec <audit-copy>`로 제출해.
3. manual synthetic no-op이 attempt 1 `succeeded`인지 확인해.
4. kickstart 없이 자연 60초 cycle 두 번을 확인해.
5. 별도 bounded synthetic job 실행 중 research runtime process group만 SIGKILL하고 자연 복구를 확인해.
6. 여기까지 통과할 때만 service를 유지하고 reboot recovery와 24시간 지속 시험으로 넘어가.

앞 단계가 실패하면 뒤 단계로 넘어가지 마.

## 7. rollback과 즉시 중단 조건

오류가 나면 exact service만 제거해.

```bash
launchctl bootout gui/$(id -u)/com.petcam.research-runtime
rm "$HOME/Library/LaunchAgents/com.petcam.research-runtime.plist"
```

ledger·event JSONL은 원인 분석용으로 보존해. 다음 중 하나라도 관측되면 즉시 rollback하고
`BLOCKED`로 보고해.

- production service/DB/R2/media/model/provider 접근 또는 변화
- Gemini CLI executable·credential·process가 남아 있음
- checkout HEAD·hostname·service label 불일치
- stale epoch mutation, duplicate execution, unbounded log, secret-like output
- provider call 또는 비용이 0이 아님
- temp media 또는 rollback residue가 0이 아님

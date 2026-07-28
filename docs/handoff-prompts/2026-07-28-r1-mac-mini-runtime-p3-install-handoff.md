---
handoff_version: 1
task_id: r1-mac-mini-runtime-p3-install
execution_repo: /Users/baek-end/petcam-lab-research-runtime
plan_path: /Users/baek-end/petcam-lab-research-runtime/docs/research/R1-RUNTIME-RUNBOOK.md
design_path: /Users/baek-end/petcam-lab-research-runtime/scripts/install_research_runtime_launchd.sh
commit_sha: 8a7ea47041d02180f2fe03ada54f39f45ccf7c26
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.research-runtime
---

# R1 Mac mini 연구 runtime P3 설치 handoff

## 실행 범위

검증된 `synthetic_noop_v1` runtime만 Mac mini 전용 checkout과
`com.petcam.research-runtime` LaunchAgent에 설치해. production DB/R2/media/dataset/model,
Claude/VLM/local LLM, 외부 provider, 기존 production service는 건드리지 마.

고정 provenance:

- runtime code: `8a7ea47041d02180f2fe03ada54f39f45ccf7c26`
- P3 manifest commit M: `85a270f89d3803553203e91e9ee72841affd7cf0`
- P3 manifest SHA-256:
  `9cd0eabf298833e21ee8ae14d573ad13176cf1154923573a8f6fbfd4d2c93e46`
- runtime checkout: `/Users/baek-end/petcam-lab-research-runtime`
- runtime data root:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime`
- runtime host: `baeg-endeuui-Macmini.local`
- service: `com.petcam.research-runtime`

## 0. Gemini CLI 제거 선행 게이트

Gemini CLI는 2026-07-28 운영 폐기됐어. runtime checkout이나 LaunchAgent를 만들기 전에
Mac mini에서 package와 CLI 전용 credential을 제거해. Gemini API credential·backend는
삭제하지 마.

먼저 package owner를 기록해.

```bash
command -v gemini || true
type -a gemini 2>/dev/null || true
for npm_bin in /opt/homebrew/bin/npm /usr/local/bin/npm; do
  if [[ -x "$npm_bin" ]]; then
    "$npm_bin" list -g --depth=0 2>/dev/null | grep '@google/gemini-cli' || true
  fi
done
brew list --versions 2>/dev/null | grep '^gemini-cli ' || true
test -d "$HOME/.gemini" && echo GEMINI_CREDENTIAL_ROOT_PRESENT || true
```

확인된 package manager만 사용해서 제거해.

```bash
for npm_bin in /opt/homebrew/bin/npm /usr/local/bin/npm; do
  if [[ -x "$npm_bin" ]] && \
     "$npm_bin" list -g --depth=0 2>/dev/null | grep -q '@google/gemini-cli'; then
    "$npm_bin" uninstall -g @google/gemini-cli
  fi
done
if brew list --formula gemini-cli >/dev/null 2>&1; then
  brew uninstall gemini-cli
fi
if [[ -d "$HOME/.gemini" ]]; then
  find "$HOME/.gemini" -depth -type f -exec unlink {} \;
  find "$HOME/.gemini" -depth -type l -exec unlink {} \;
  find "$HOME/.gemini" -depth -type d ! -path "$HOME/.gemini" -exec rmdir {} \;
  rmdir "$HOME/.gemini"
fi
```

다음 세 조건이 모두 참이 아니면 P3 설치를 시작하지 마.

```bash
! command -v gemini >/dev/null 2>&1
test ! -e "$HOME/.gemini"
! pgrep -f '[g]emini-cli' >/dev/null 2>&1
echo GEMINI_CLI_MAC_MINI_REMOVED
```

`/Users/baek-end/AGENTS.md`와 `/Users/baek-end/.codex/AGENTS.md`가 있으면 Gemini CLI 허용
문구를 제거하고 다음 계약을 넣어. 다른 규칙은 바꾸지 마.

```text
Gemini CLI는 2026-07-28 운영 폐기됐다. 실행·재설치·인증·wrapper·fallback 등록을 금지한다.
과거 문서의 Gemini CLI 언급은 감사 이력일 뿐 현재 사용 권한이 아니다.
```

다음 active allowance가 0이어야 해.

```bash
! grep -E 'gemini -p|tools/gemini-cli\.sh' \
  /Users/baek-end/AGENTS.md /Users/baek-end/.codex/AGENTS.md 2>/dev/null
```

## 1. 설치 전 fail-closed 확인

Mac mini에서 다음 값이 하나라도 다르면 즉시 중단해.

```bash
test "$(hostname)" = "baeg-endeuui-Macmini.local"
test "$(id -un)" = "baek-end"
test ! -e "$HOME/Library/LaunchAgents/com.petcam.research-runtime.plist"
! launchctl print "gui/$(id -u)/com.petcam.research-runtime" >/dev/null 2>&1
```

기존 production LaunchAgent의 label·working directory·HEAD·last exit를 설치 전 기록하고,
설치 뒤 byte-for-byte 또는 값 기준으로 대조해. 이 handoff는 기존 service를 bootout하거나
수정할 권한을 주지 않아.

## 2. exact checkout

checkout이 없을 때만:

```bash
git clone --no-checkout https://github.com/S-Soo100/petcam-lab.git \
  /Users/baek-end/petcam-lab-research-runtime
git -C /Users/baek-end/petcam-lab-research-runtime fetch origin
git -C /Users/baek-end/petcam-lab-research-runtime checkout --detach \
  8a7ea47041d02180f2fe03ada54f39f45ccf7c26
```

checkout이 이미 있으면 임의 reset하지 말고 exact HEAD·clean 여부만 확인해.

```bash
test "$(git -C /Users/baek-end/petcam-lab-research-runtime rev-parse HEAD)" = \
  "8a7ea47041d02180f2fe03ada54f39f45ccf7c26"
test -z "$(git -C /Users/baek-end/petcam-lab-research-runtime \
  status --porcelain --untracked-files=all)"
```

## 3. audit artifact 복사와 handoff 검증

controller가 이 파일과 canary JSON을 아래 경로에 복사한 뒤 mode 0600으로 고정해.

```text
/Users/baek-end/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-mac-mini-runtime-p3-install-handoff.md
/Users/baek-end/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-p3-synthetic-canary.json
```

controller 보고서에 기록된 각 SHA-256과 복사본을 대조한 뒤:

```bash
cd /Users/baek-end/petcam-lab-research-runtime
uv run python scripts/verify_agent_handoff.py \
  --manifest "/Users/baek-end/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-mac-mini-runtime-p3-install-handoff.md"
```

필수 출력:

```text
HANDOFF_OK task=r1-mac-mini-runtime-p3-install repo=petcam-lab-research-runtime commit=8a7ea470 runtime=launchagent@baeg-endeuui-Macmini.local
```

## 4. 설치 전 runtime 검증

```bash
cd /Users/baek-end/petcam-lab-research-runtime
uv run pytest -q tests/research_runtime
uv run python scripts/run_research_runtime_adversarial.py
bash -n scripts/researchctl scripts/install_research_runtime_launchd.sh
```

39 tests와 adversarial marker 14개, `R1_RESIDUE_ZERO`가 모두 있어야 해.

## 5. LaunchAgent 설치

앞의 모든 검증이 통과한 경우에만:

```bash
cd /Users/baek-end/petcam-lab-research-runtime
RESEARCH_EXPECTED_HOST=baeg-endeuui-Macmini.local \
RESEARCH_EXPECTED_HEAD=8a7ea47041d02180f2fe03ada54f39f45ccf7c26 \
bash scripts/install_research_runtime_launchd.sh
```

그다음 `launchctl print gui/$(id -u)/com.petcam.research-runtime`에서 label,
WorkingDirectory, `StartInterval=60`, private log path를 확인해.

## 6. canary 순서

1. tracked canary를 `scripts/researchctl submit --spec <audit-copy>`로 제출해.
2. manual synthetic no-op이 attempt 1 `succeeded`인지 확인해.
3. kickstart 없이 자연 60초 cycle 한 번을 확인해.
4. 별도 bounded synthetic job 실행 중 research runtime process group만 SIGKILL하고 자연 복구를 확인해.
5. 별도 bounded synthetic job 실행 중 Mac mini를 reboot하고 boot fencing 복구를 확인해.
6. 24시간 동안 production lock defer, duplicate 0, provider/cost/media/temp residue 0을 확인해.

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

## 현재 stop

이 handoff를 만든 세션은 Mac mini에 접속하지 않았고 checkout·plist·LaunchAgent를 만들지
않았어. 다음 실행은 위 1번부터 시작해.

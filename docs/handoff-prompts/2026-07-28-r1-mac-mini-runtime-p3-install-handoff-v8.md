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

# R1 Mac mini 연구 runtime P3 설치 handoff v8

## v8 변경 사유

v7 첫 RunAtLoad는 정상 통과했지만 target 제거 뒤 baseline 재검증 command가 control-only
verifier를 runtime cwd에서 import해 `ModuleNotFoundError`로 실패했어. target은 이미 absent라
두 번째 설치와 뒤 단계는 실행하지 않았다.

v8은 verifier invocation의 cwd를 control checkout으로 고정한다. runtime/verifier 코드는
바꾸지 않고 fresh `008` job ID와 새 v8 baseline으로 전체 순서를 다시 시작한다.

## 고정 provenance

- runtime SHA:
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- control verifier SHA-256:
  `8982bafadb5dd8e9fd7baa3a1f6adc6d84d73c0a9450f090c28babeaa132c389`
- manual canary v8 SHA-256:
  `c7d0b44359381d1ed6a23c9f8c2c6bcdc795b4108631a73b3d7c049e8057409b`
- SIGKILL recovery v8 SHA-256:
  `4d129358a244eabbce44783c2b85b2126fa4a28ecf77305abb9f684a726f1fdc`
- runtime checkout:
  `/Users/baek-end/petcam-lab-research-runtime`
- runtime root:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime`
- forbidden legacy root:
  `/Users/baek-end/.petcam-research-runtime`
- target label:
  `com.petcam.research-runtime`
- expected-absent production label:
  `com.petcam.vlm-backfill-finalizer`

v6의 autonomous Claude 실행 이력은 별도 root-cause 보고에 보존한다. fresh v8 시작 이후
production DB/R2/media/dataset/model, Claude/VLM/local LLM/provider 접근과 production
service 변경은 0이어야 해. primary checkout은 읽거나 수정하지 않고 Gemini CLI 폐기 상태를
유지한다.

## 0. fresh baseline과 guard

target service/plist/process, finalizer service/plist와 legacy root가 모두 absent여야 한다.
runtime/control checkout은 exact clean/upstream이어야 한다.

현재 production plist 7개의 label, SHA-256, WorkingDirectory와 다음 sentinel을
`r1-p3-production-immutable-baseline-v8.json`에 mode 0600으로 기록한다.

```json
{
  "expected_absent_labels": [
    "com.petcam.vlm-backfill-finalizer"
  ]
}
```

baseline 검증은 반드시 다음 cwd에서 실행한다.

```bash
cd /Users/baek-end/petcam-lab-r1-runtime-p3-control
/usr/bin/python3 -c \
  'from pathlib import Path; from scripts.verify_research_runtime_reboot import verify_production_baseline; h=Path.home(); print(verify_production_baseline(h / "Library/Application Support/petcam/research-runtime/audit/r1-p3-production-immutable-baseline-v8.json", h / "Library/LaunchAgents"))'
```

production service/lock/schedule은 조작하지 않는다. runtime `evaluate_guard`가 자연스럽게
`allowed=True`가 된 충분한 연속 구간에서만 설치한다.

## 1. audit copy, HANDOFF_OK, code gate

handoff, 두 v8 spec과 verifier를 runtime root에 mode 0600으로 복사하고 source/copy hash를
대조한다.

```bash
cd /Users/baek-end/petcam-lab-research-runtime
uv run python scripts/verify_agent_handoff.py \
  --manifest "$HOME/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-mac-mini-runtime-p3-install-handoff-v8.md"
```

필수 출력:

```text
HANDOFF_OK task=r1-mac-mini-runtime-p3-install repo=petcam-lab-research-runtime commit=7267b642 runtime=launchagent@baeg-endeuui-Macmini.local
```

control verifier 8 tests와 system Python compile, runtime 41 tests, adversarial 14 marker와
`R1_RESIDUE_ZERO`, installer/CLI bash syntax를 다시 통과해야 한다.

## 2. RunAtLoad 2회

```bash
cd /Users/baek-end/petcam-lab-research-runtime
RESEARCH_EXPECTED_HOST=baeg-endeuui-Macmini.local \
RESEARCH_EXPECTED_HEAD=7267b642dd9e25a0e199e57c5d41d1e2c04ee419 \
bash scripts/install_research_runtime_launchd.sh
```

첫 RunAtLoad `runs=1`, last exit 0과 exact WD/root/HEAD/60초를 확인한다. exact target만
bootout하고 target plist만 제거한 뒤 위의 control cwd baseline command를 다시 통과시킨다.
그다음 같은 installer로 두 번째 RunAtLoad를 검증한다.

## 3. manual, natural 2회, SIGKILL

```bash
cd /Users/baek-end/petcam-lab-research-runtime
scripts/researchctl submit \
  --spec "$HOME/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-p3-synthetic-canary-v8.json"
launchctl kickstart "gui/$(id -u)/com.petcam.research-runtime"
scripts/researchctl show r1-p3-synthetic-canary-008 --json
```

manual은 root option/env 없이 attempt 1 `succeeded`여야 한다. kickstart 없이 자연 60초
cycle이 두 번 증가하고 exit 0, manual attempt 불변이어야 한다.

v8 SIGKILL spec을 default root로 submit한다. running attempt 1/epoch 1의 ledger PID,
사용자, checkout, parent/child process group을 assert한 뒤 exact research PGID만
child-first SIGKILL한다. 다음 자연 cycle에서 attempt 2/new epoch `succeeded`여야 한다.

provider/cost/media/model/legacy/secret residue, duplicate result와 orphan process는 0이어야 한다.

## 4. reboot와 24시간

schema 2 marker에 current clean control SHA/upstream, runtime SHA, target plist/hash, pre boot sec,
v8 baseline/hash, verifier/handoff hash와 실제 job 결과를 mode 0600으로 기록한다. boot sec만
다른 임시 marker로 full verifier preflight를 통과시킨다.

reboot 후 audit verifier의 마지막 출력이 `R1_RUNTIME_P3_REBOOT_RECOVERY_OK`여야 한다.
그때만 시작/완료 예정 시각을 기록하고 `R1_RUNTIME_P3_PENDING_24H`로 service를 유지한다.

어느 단계든 오류, drift, off-target mutation이면 뒤 단계로 가지 않고 exact target만
bootout하고 target plist만 제거한다. 증거는 보존한다.

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

# R1 Mac mini 연구 runtime P3 설치 handoff v7

## v7 변경 사유

v6 pre-reboot gate는 모두 통과했지만 첫 restart 요청이 iTerm2 quit timeout으로 중단돼
target만 rollback했어. 뒤이은 실제 reboot에서 production one-shot
`com.petcam.vlm-backfill-finalizer`가 실행되고 자기 `EXIT` trap으로 plist를 제거했다.

v7은 이 이력을 drift에서 삭제하지 않는다. 현재 남은 production plist 7개를 새 immutable
baseline으로 고정하고 finalizer label은 반드시 absent인 sentinel로 검증한다. finalizer를
복구하거나 다른 production service를 조작하지 않는다.

## 고정 provenance

- runtime code:
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- P3 manifest commit M:
  `85a270f89d3803553203e91e9ee72841affd7cf0`
- P3 manifest SHA-256:
  `9cd0eabf298833e21ee8ae14d573ad13176cf1154923573a8f6fbfd4d2c93e46`
- runtime checkout:
  `/Users/baek-end/petcam-lab-research-runtime`
- runtime root:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime`
- forbidden legacy root:
  `/Users/baek-end/.petcam-research-runtime`
- runtime host:
  `baeg-endeuui-Macmini.local`
- service:
  `com.petcam.research-runtime`
- expected-absent production label:
  `com.petcam.vlm-backfill-finalizer`
- verifier SHA-256:
  `8982bafadb5dd8e9fd7baa3a1f6adc6d84d73c0a9450f090c28babeaa132c389`
- manual canary v7 SHA-256:
  `723e6c3038d2fb1e3afe8beaa22b177d57cba69b82107c4d151392bb1a69cfe3`
- SIGKILL recovery v7 SHA-256:
  `d48d40014b691613b4330cc648294ede47921ee003104f46b921af7f9369a905`

v6의 autonomous Claude process/network 증거는 root-cause 보고에 보존한다. fresh v7 시작
이후 production DB/R2/media/dataset/model, Claude/VLM/local LLM, provider와 기존
production service 접근·변경은 0이어야 해. Gemini CLI는 폐기 상태를 유지한다.

## 0. fresh baseline과 fail-closed gate

target service/plist/process, legacy root, finalizer service/plist가 모두 absent여야 한다.
runtime과 control checkout은 exact clean/upstream이어야 한다. production service를
bootout, bootstrap, kickstart, signal하거나 lock/schedule을 바꾸지 않는다.

현재 존재하는 production plist 7개의 label, SHA-256, WorkingDirectory를
`r1-p3-production-immutable-baseline-v7.json`에 mode 0600으로 기록한다.
primary checkout과 production repo content/status는 읽지 않는다.

baseline에 다음 sentinel을 반드시 넣는다.

```json
{
  "expected_absent_labels": [
    "com.petcam.vlm-backfill-finalizer"
  ]
}
```

tracked verifier로 baseline을 즉시 읽기 전용 검증한다. existing 7개 drift나 finalizer
재등장이면 설치하지 않는다.

그다음 runtime `evaluate_guard`를 read-only 호출한다. `allowed=True` 전에는 설치하지 않고
production lock owner를 signal하거나 lock file을 삭제하지 않는다.

## 1. audit copy와 HANDOFF_OK

이 handoff, 두 v7 spec과 tracked verifier를 runtime root의 `handoff/`와 `audit/`에 mode
0600으로 복사하고 source/copy SHA-256을 대조한다.

```bash
cd /Users/baek-end/petcam-lab-research-runtime
uv run python scripts/verify_agent_handoff.py \
  --manifest "$HOME/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-mac-mini-runtime-p3-install-handoff-v7.md"
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

verifier 8 tests, runtime 41 tests, adversarial marker 14줄과 `R1_RESIDUE_ZERO`, system Python
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

## 4. manual, natural 2회, SIGKILL

```bash
cd /Users/baek-end/petcam-lab-research-runtime
scripts/researchctl submit \
  --spec "$HOME/Library/Application Support/petcam/research-runtime/handoff/2026-07-28-r1-p3-synthetic-canary-v7.json"
launchctl kickstart "gui/$(id -u)/com.petcam.research-runtime"
scripts/researchctl show r1-p3-synthetic-canary-007 --json
```

manual canary는 root env/option 없이 attempt 1 `succeeded`여야 해. 이어서 kickstart 없이
`runs`가 두 번 증가하고 두 cycle 모두 exit 0, canary attempt 불변이어야 한다.

recovery v7 spec을 default root로 submit한다. 자연 cycle에서 running이 되면 ledger PID와
process tree를 대조하고 exact research parent/child process group만 SIGKILL한다. 다음 자연
cycle이 stale lease를 reclaim해 `r1-p3-sigkill-recovery-007`을 attempt 2, 새 lease epoch,
exit 0 `succeeded`로 끝내야 해.

provider/cost/media/model/legacy residue, duplicate result와 orphan process는 모두 0이어야 한다.

## 5. reboot marker

앞 단계가 전부 통과한 뒤 schema 2 marker를 mode 0600으로 원자 작성한다. 필수 필드는
host/user, runtime/control SHA, runtime checkout/root, legacy root, label, target plist와
SHA-256, launch agents dir, pre-reboot boot sec, v7 production baseline path/SHA-256이다.

control SHA는 clean checkout의 `git rev-parse HEAD`를 직접 기록하고 upstream SHA와 같음을
검증한다. boot parser는 `sec = <integer>`만 선택한다.

임시 marker에서 `pre_reboot_boot_sec`만 다른 값으로 바꿔 verifier 전체 read-only preflight를
수행하고 `R1_REBOOT_VERIFIER_PREFLIGHT_OK`를 확인한다.

reboot 후:

```bash
/usr/bin/python3 \
  "$HOME/Library/Application Support/petcam/research-runtime/audit/verify_research_runtime_reboot-v7.py" \
  --marker "$HOME/Library/Application Support/petcam/research-runtime/audit/r1-p3-reboot-pending-v7.json"
```

마지막 출력은 `R1_RUNTIME_P3_REBOOT_RECOVERY_OK`여야 한다.

## 6. 24시간과 rollback

reboot recovery 통과 시각과 정확히 24시간 뒤 완료 예정 시각을 기록하고 service를 유지한다.
그 전에는 `R1_RUNTIME_P3_PENDING_24H`로만 보고한다.

어느 단계든 오류, drift, off-target mutation이면 뒤 단계로 가지 않고 exact target만
bootout하고 target plist만 제거한다. ledger/event/audit 증거는 보존한다.

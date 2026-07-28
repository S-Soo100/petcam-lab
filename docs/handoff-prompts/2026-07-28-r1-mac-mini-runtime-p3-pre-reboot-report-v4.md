# R1 Mac mini runtime P3 v4 pre-reboot 보고

## 판정

`R1_RUNTIME_P3_REBOOT_READY_V4`

tracked reboot verifier 수정, 새 handoff, RunAtLoad 2회, manual canary, 자연 60초 cycle 2회와
SIGKILL recovery가 모두 통과했어. 아직 reboot recovery와 24시간 지속 검증 전이므로
`DEPLOYED_VERIFIED`는 주장하지 않는다.

## provenance와 code gate

- runtime branch: `codex/r1-runtime-launchd-exit6-fix`
- runtime SHA: `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- control branch: `codex/r1-mac-mini-runtime-p3-preinstall`
- verifier fix commit: `7fd0ea33ba271141e67421c6a5f08d8344f3895d`
- v4 handoff SHA-256:
  `3ad105f57664cd42f927e7ffbea9641c69f7ad1f11ab073bf740c094b4c1537f`
- verifier SHA-256:
  `e71fc0732882cbda570ad15ae6a6783e72bc98af0eea6511e229f65ec2725111`
- `HANDOFF_OK task=r1-mac-mini-runtime-p3-install repo=petcam-lab-research-runtime commit=7267b642 runtime=launchagent@baeg-endeuui-Macmini.local`
- control verifier focused suite: `7 passed`
- control research runtime suite: `46 passed`
- runtime exact suite: `41 passed`
- adversarial marker: 14줄, `R1_RESIDUE_ZERO` 포함
- system Python 3.9 compile: exit 0
- bash syntax: exit 0

runtime checkout은 detached clean exact SHA이고 control fix branch도 push됐다. runtime 동작 결함이
아니므로 runtime SHA는 변경하지 않았다.

## LaunchAgent와 manual canary

- target service: `com.petcam.research-runtime`
- RunAtLoad 1: `runs=1`, last exit 0
- RunAtLoad 2: `runs=1`, last exit 0
- expected HEAD, WorkingDirectory, canonical root, StartInterval 60 확인
- manual canary는 root env/option을 생략해 canonical default를 검증
- manual canary `r1-p3-synthetic-canary-004`: attempt 1, `succeeded`
- target plist SHA-256:
  `c5847755d5198902e0a69c83de8ffc56dfe38f0c7a9b09b73abcefe67bff0fd6`
- legacy `/Users/baek-end/.petcam-research-runtime`: absent

## 자연 cycle

manual kickstart 뒤 service `runs=2`를 기준으로 추가 kickstart 없이 두 interval을 확인했어.

```text
2026-07-28T20:03:12+0900 runs=3 last exit=0
2026-07-28T20:04:13+0900 runs=4 last exit=0
```

두 cycle 모두 manual canary는 attempt 1 `succeeded`로 유지됐다.

## SIGKILL recovery

bounded job `r1-p3-sigkill-recovery-004`의 ledger와 process tree를 대조했다.

```text
ledger PID=8295, attempt=1, lease_epoch=1
parent PGID=8293: uv/caffeinate/run-once only
child PGID=8299: synthetic_noop_v1 only
```

사용자, checkout, command, parent/child 관계를 assert한 뒤 두 exact research process group만
child-first로 SIGKILL했다. PID 8293/8294/8295/8299가 모두 사라진 것을 확인했다.

다음 자연 cycle이 stale PID를 reclaim했고:

```text
2026-07-28T20:06:59+0900 PID=8469 attempt=2 lease_epoch=3
2026-07-28T20:09:00+0900 succeeded exit_code=0
```

event 순서는 `queued -> running(1/1) -> recovery_queued(previous=1) ->
running(2/3) -> succeeded(3)`이고 attempt 1 result와 orphan process는 0이야. service는
`runs=6`, last exit 0으로 복구됐다.

## zero-cost와 production baseline

- local ledger: 4 jobs
- provider calls 합계: 0
- cost 합계: 0
- media/model residue: 0
- secret-like runtime residue: 0
- production DB/R2/media/dataset/model/Claude/VLM/local LLM 접근: 0
- production service mutation: 0
- production immutable services: 8
- production baseline:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-production-immutable-baseline-v4.json`
- production baseline SHA-256:
  `3ce6126e9adcb80ad1a0093caf8146664ae6a1fb30b4c2223088ee8468da717d`

baseline은 label, plist SHA-256, plist WorkingDirectory와 repo HEAD/status fingerprint를
기록했다. verifier pass/fail은 reboot-stable인 label/plist hash/WorkingDirectory만 사용하고
launchd loaded/runs/last-exit는 사용하지 않는다.

## reboot 준비

- pre-reboot boot sec: `1785233472`
- raw boot output의 `usec`: `865155`
- parser 결과는 `1785233472`로 정확히 `sec`를 선택

control report commit/push 뒤 그 exact control SHA를 schema 2 marker에 기록하고, tracked
verifier의 mode 0600 audit copy로 reboot recovery를 검증한다.

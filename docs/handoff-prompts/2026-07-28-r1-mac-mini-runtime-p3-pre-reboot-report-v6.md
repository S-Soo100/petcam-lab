# R1 Mac mini runtime P3 v6 pre-reboot 보고

## 판정

`R1_RUNTIME_P3_REBOOT_READY_V6`

v6는 production guard가 자연스럽게 allowed가 된 뒤 RunAtLoad 2회, manual canary, 자연
60초 cycle 2회와 SIGKILL recovery를 모두 통과했어. 아직 reboot recovery와 24시간 지속
검증 전이므로 `DEPLOYED_VERIFIED`는 주장하지 않는다.

## provenance와 code gate

- runtime SHA: `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- control branch: `codex/r1-mac-mini-runtime-p3-preinstall`
- pre-report control SHA:
  `4681f49cedc0a6ec4a45a9e6ee44e91c74b7127c`
- v6 handoff SHA-256:
  `fb23cae599da2998f054e40f91011172301746d552beb8e2c9d129118279ab1e`
- verifier SHA-256:
  `e71fc0732882cbda570ad15ae6a6783e72bc98af0eea6511e229f65ec2725111`
- `HANDOFF_OK task=r1-mac-mini-runtime-p3-install repo=petcam-lab-research-runtime commit=7267b642 runtime=launchagent@baeg-endeuui-Macmini.local`
- verifier focused suite: `7 passed`
- runtime exact suite: `41 passed`
- adversarial marker: 14줄, `R1_RESIDUE_ZERO` 포함
- system Python compile와 bash syntax: exit 0

## guard와 LaunchAgent

target absent 상태에서 read-only guard를 기다렸고:

```text
2026-07-28T20:55:00+0900 allowed=True reason=allowed
```

production lock/service/schedule은 변경하지 않았다.

- RunAtLoad 1: `runs=1`, last exit 0
- RunAtLoad 2: `runs=1`, last exit 0
- WorkingDirectory: `/Users/baek-end/petcam-lab-research-runtime`
- runtime root:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime`
- StartInterval: 60 seconds
- target plist SHA-256:
  `c5847755d5198902e0a69c83de8ffc56dfe38f0c7a9b09b73abcefe67bff0fd6`

## manual과 자연 cycle

- manual `r1-p3-synthetic-canary-006`: attempt 1 `succeeded`
- root env/option을 생략해 canonical default를 검증

```text
2026-07-28T20:57:11+0900 runs=3 last exit=0
2026-07-28T20:58:11+0900 runs=4 last exit=0
```

두 자연 cycle에서 manual canary attempt는 1로 유지됐다.

## SIGKILL recovery

```text
ledger PID=11501 attempt=1 lease_epoch=1
parent PGID=11499: uv/caffeinate/run-once only
child PGID=11505: synthetic_noop_v1 only
```

사용자, checkout, command와 process tree를 assert한 뒤 exact research parent/child PGID만
child-first SIGKILL했다. PID 11499/11500/11501/11505는 모두 사라졌다.

```text
2026-07-28T21:00:35+0900 PID=11652 attempt=2 lease_epoch=3
2026-07-28T21:02:36+0900 succeeded exit_code=0
```

event 순서는 `queued -> running(1/1) -> recovery_queued(previous=1) ->
running(2/3) -> succeeded(3)`이야. attempt 1 result, duplicate success와 orphan process는
0이고 service는 `runs=6`, last exit 0으로 복구됐다.

## zero-cost와 production baseline

- local ledger: 7 jobs
- provider calls 합계: 0
- cost 합계: 0
- media/model residue: 0
- secret-like runtime residue: 0
- legacy root: absent
- production DB/R2/media/dataset/model/Claude/VLM/local LLM 접근: 0
- production service mutation: 0
- production immutable services: 8
- baseline:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-production-immutable-baseline-v6.json`
- baseline SHA-256:
  `17514aba088d9751023476ea2b17ab839c58f760685d5a76ec86c90a13cea7a4`

## reboot 준비

- pre-reboot boot sec: `1785233472`
- raw usec: `865155`
- parser result: `1785233472`

이 보고를 commit/push한 뒤 marker는 최종 clean control HEAD와 upstream HEAD를 직접 읽어
기록한다. 별도 hardcoded SHA assertion은 사용하지 않는다.
